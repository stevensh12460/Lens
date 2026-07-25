"""
web.py — website publishing endpoints (/web/*).

The Lightroom publish service drives these: it renders JPEGs, hands LENS the
paths, and LENS places the files, rewrites the fenced gallery block, and commits.

Response format rule, inherited from the Lightroom bridge and NOT optional:
anything returning MULTIPLE ROWS must be TSV with an `#OK` sentinel first line.
LensAPI.lua's jsonDecode is a flat key/value regex scraper — it cannot represent
an array of objects and would silently collapse every row into one, writing
identical values onto every photo. Single-object responses may be JSON.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from core.database import get_db
from lens_core.tz import now_et
from services import web_git
from services.web_publisher import (
    SECTIONS,
    IncomingPhoto,
    PublishError,
    RewriteError,
    load_assets,
    publish_photos,
    render_block,
    rewrite_block,
    find_fence,
    set_order,
)

router = APIRouter()


def _tsv(header: list[str], rows: list[list[str]]) -> PlainTextResponse:
    """TSV with the #OK sentinel the plugin requires.

    The sentinel is what lets the plugin tell a valid empty result set apart
    from a proxy error page or a truncated response. Tabs and newlines are
    stripped from every cell so a stray character can never break the format.
    """
    def clean(v) -> str:
        return str(v if v is not None else "").replace("\t", " ").replace("\n", " ").replace("\r", "")

    lines = ["#OK", "\t".join(header)]
    lines.extend("\t".join(clean(c) for c in row) for row in rows)
    return PlainTextResponse("\n".join(lines) + "\n")


@router.get("/status")
def status():
    """Is publishing possible right now, and why not if not.

    Deliberately runs the real preflight rather than reporting cached state —
    the point is to surface a broken credential or a dirty working tree BEFORE
    Steven starts a publish from Lightroom, not during it.
    """
    checks: dict[str, object] = {"at": now_et().isoformat()}

    checks["kill_switch"] = web_git.KILL_SWITCH.exists()
    checks["deploy_key_present"] = web_git.SSH_KEY.exists()
    checks["site_root"] = str(web_git.SITE_ROOT)

    branch = web_git._git("rev-parse", "--abbrev-ref", "HEAD")
    checks["branch"] = branch.stdout.strip() or f"<error: {branch.stderr.strip()[:80]}>"

    head = web_git._git("rev-parse", "--short", "HEAD")
    checks["local_head"] = head.stdout.strip()

    ls = web_git._git("ls-remote", web_git.REMOTE, web_git.BRANCH)
    checks["remote_reachable"] = ls.returncode == 0
    if ls.returncode == 0:
        checks["remote_head"] = (ls.stdout.split() or [""])[0][:7]
    else:
        checks["remote_error"] = ls.stderr.strip()[:200]

    dirty = web_git._git("status", "--porcelain").stdout.strip()
    checks["working_tree_clean"] = dirty == ""
    if dirty:
        checks["dirty_files"] = [ln[3:] for ln in dirty.splitlines()][:10]

    try:
        web_git.preflight([], for_push=True)
        checks["can_publish"] = True
    except web_git.GitGuardError as exc:
        checks["can_publish"] = False
        checks["blocked_because"] = str(exc).splitlines()[0]

    with get_db() as conn:
        checks["sections"] = {s: len(load_assets(s, conn)) for s in SECTIONS}

    return checks


class PublishItem(BaseModel):
    lr_photo_uuid: str
    staged_path: str
    title: str = ""
    caption: str = ""
    layout: str = ""
    source_path: str = ""


class PublishBatch(BaseModel):
    section: str
    photos: List[PublishItem]


class OrderBatch(BaseModel):
    section: str
    slugs: List[str]


class CommitRequest(BaseModel):
    section: str
    dry_run: bool = True


@router.post("/publish")
def publish(batch: PublishBatch):
    """Place rendered JPEGs and record them. TSV, because this is multi-row.

    Does NOT commit — the plugin calls /web/commit once at the end of a publish
    so a batch of photos becomes one commit and one Cloudflare deploy, not one
    per photo.
    """
    if batch.section not in SECTIONS:
        return PlainTextResponse(
            f"#ERROR unknown section {batch.section!r}; known: {', '.join(SECTIONS)}\n",
            status_code=400,
        )

    photos = [
        IncomingPhoto(
            lr_photo_uuid=p.lr_photo_uuid, staged_path=p.staged_path,
            title=p.title, caption=p.caption, layout=p.layout,
            source_path=p.source_path,
        )
        for p in batch.photos
    ]

    try:
        with get_db() as conn:
            results = publish_photos(conn, batch.section, photos)
    except PublishError as exc:
        # 400 + no sentinel, so LensAPI.postTSV surfaces it as a real failure
        # and the plugin calls rendition:uploadFailed rather than recording a
        # slug that was never allocated.
        return PlainTextResponse(f"#ERROR {exc}\n", status_code=400)

    return _tsv(
        ["lr_photo_uuid", "slug", "url", "sha", "status"],
        [[r["lr_photo_uuid"], r["slug"], r["url"], r["sha"], r["status"]] for r in results],
    )


@router.post("/order")
def order(batch: OrderBatch):
    """Apply the collection's display order. Idempotent."""
    if batch.section not in SECTIONS:
        return {"error": f"unknown section {batch.section!r}"}
    with get_db() as conn:
        moved = set_order(conn, batch.section, batch.slugs)
    return {"section": batch.section, "reordered": moved}


@router.post("/commit")
def commit(req: CommitRequest):
    """Rewrite the fenced block from the database, then commit (and maybe push).

    dry_run=True (the default) commits locally and does NOT push. Cloudflare
    deploys on push only, so the live site stays untouched and `git show HEAD`
    is a real artifact to inspect.
    """
    if req.section not in SECTIONS:
        return {"error": f"unknown section {req.section!r}"}

    stamp = now_et().strftime("%Y%m%d-%H%M%S")
    backup = Path.home() / "lens" / "backups" / "shp-site" / stamp

    with get_db() as conn:
        assets = load_assets(req.section, conn)
        block = render_block(assets)

    try:
        outcome = rewrite_block(req.section, block, backup_dir=backup)
    except RewriteError as exc:
        return {"status": "refused", "detail": str(exc)}

    paths = [f"{req.section}.html"] + [
        f"media/{req.section}/{a.file_name}" for a in assets
    ]

    try:
        result = web_git.commit_and_push(
            paths,
            f"LENS publish: {req.section} ({len(assets)} photos)",
            dry_run=req.dry_run,
        )
    except web_git.GitGuardError as exc:
        return {"status": "refused", "rewrite": outcome, "detail": str(exc)}

    with get_db() as conn:
        conn.execute(
            """INSERT INTO web_publish_log
                 (at, section, action, added, removed, reordered, commit_sha, pushed, status, detail)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (now_et().isoformat(), req.section, "commit", 0, 0, False,
             result.commit_sha, result.pushed, result.status, result.detail[:500]),
        )

    return {
        "status": result.status,
        "rewrite": outcome,
        "commit": result.commit_sha[:8] if result.commit_sha else None,
        "pushed": result.pushed,
        "files": result.files,
        "detail": result.detail,
    }


class RemovalRequest(BaseModel):
    slug: str
    confirmed: bool = False


@router.post("/removals/stage")
def stage_removal(req: RemovalRequest):
    """Take a photo off the site. Confirmed in Lightroom before this is called.

    Two deliberate choices:

    * The JPEG is only UNREFERENCED, never `git rm`-ed. A few hundred KB of
      orphan costs nothing, and it makes undoing this a one-line HTML revert
      rather than git archaeology.

    * Refuses if the file is referenced anywhere outside its own fence.
      index.html's slideshow and the og:image tags on several pages point at
      gallery files — landscape-01 is used by index, contact and landscape.
      Unreferencing it there would blank a homepage slide silently, because a
      CSS background-image that 404s just renders as nothing.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT section, file_name FROM web_assets WHERE slug = ? AND state = 'live'",
            (req.slug,),
        ).fetchone()
        if not row:
            return {"status": "not_found", "slug": req.slug}

        section, file_name = row["section"], row["file_name"]

    referenced_in = []
    for page in sorted(web_git.SITE_ROOT.glob("*.html")):
        text = page.read_text()
        if file_name not in text:
            continue
        if page.stem == section:
            # Its own page: only count references OUTSIDE the fence.
            try:
                start, end = find_fence(text, section, page)
            except ValueError:
                referenced_in.append(page.name)
                continue
            if file_name in (text[:start] + text[end:]):
                referenced_in.append(page.name)
        else:
            referenced_in.append(page.name)

    if referenced_in:
        return {
            "status": "blocked",
            "slug": req.slug,
            "referenced_in": referenced_in,
            "detail": (
                f"{file_name} is also used outside the {section} gallery, in: "
                + ", ".join(referenced_in)
                + ". Removing it would break those. Update them by hand first."
            ),
        }

    if not req.confirmed:
        return {"status": "pending_confirmation", "slug": req.slug}

    with get_db() as conn:
        conn.execute(
            "UPDATE web_assets SET state='retired', removed_at=? WHERE slug=? AND section=?",
            (now_et().isoformat(), req.slug, section),
        )
        # Close the gap so sort_index stays contiguous.
        for i, a in enumerate(load_assets(section, conn)):
            conn.execute(
                "UPDATE web_assets SET sort_index=? WHERE section=? AND slug=?",
                (i, section, a.slug),
            )

    return {"status": "retired", "slug": req.slug, "section": section,
            "detail": "unreferenced from the page; the image file was kept"}


@router.get("/sections/{section}")
def section_detail(section: str):
    """What LENS believes is currently published on one gallery page."""
    if section not in SECTIONS:
        return {"error": f"unknown section {section!r}", "known": list(SECTIONS)}
    with get_db() as conn:
        return {
            "section": section,
            "assets": [
                {
                    "slug": a.slug,
                    "file_name": a.file_name,
                    "layout": a.layout,
                    "sort_index": a.sort_index,
                    "alt_text": a.alt_text,
                    "caption": a.caption,
                    "width": a.width,
                    "height": a.height,
                }
                for a in load_assets(section, conn)
            ],
        }
