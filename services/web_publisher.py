"""
web_publisher.py — renders and rewrites the gallery blocks on shp-site.

Lightroom is the helm: a published collection decides which photos are on a
gallery page and in what order. This module is the backend half — it turns
web_assets rows into the exact HTML the site expects, and swaps that block into
the page inside a marker fence.

Design rules that are load-bearing, do not "simplify" them away:

  * The renderer must reproduce the hand-written site BYTE FOR BYTE from the
    database. That round-trip is the proof the data model is complete; if it
    ever fails, the model has lost information and publishing would silently
    rewrite Steven's markup.

  * layout is stored per asset and NEVER recomputed. Measured on the live site:
    three landscape frames at identical 1.78 aspect carry two different classes,
    and a 0.80 portrait is `wide` in one slot and `tall` in another. `wide` is a
    full-width breath placed for rhythm — a property of position, not of the
    image.

  * alt/caption are per asset, not per genre. food-07/08/09 are "Cocktail",
    the rest of the same page are "Food".
"""

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

SITE_ROOT = Path.home() / "Code" / "shp-site"

# Sections the publish service is allowed to touch. film.html is Vimeo embeds,
# and index.html's slideshow / work tiles are a curated best-of that stays
# hand-picked — see the referential guard, several of these files are also
# referenced from index.html and from og:image tags on other pages.
SECTIONS = ("landscape", "portraits", "weddings", "food")

MARKER_START = "<!-- LENS:GALLERY {section} START -->"
MARKER_END = "<!-- LENS:GALLERY {section} END -->"

INDENT = "    "

# Layout classes. "standard" renders as a bare <figure> with no class at all.
# "reveal-x" exists only because the current HTML uses it on some food/weddings
# figures; there is NO .reveal-x rule in css/styles.css, so it is dead and
# behaves exactly like a bare figure. It is preserved here purely so the M0
# round-trip is exact, and gets normalised to "standard" in the marker commit.
LAYOUT_CLASSES = {
    "wide": "wide",
    "tall": "tall",
    "reveal-x": "reveal-x",
    "standard": None,
}


@dataclass
class Asset:
    """One <figure> on a gallery page."""

    section: str
    slug: str
    file_name: str
    layout: str
    alt_text: str
    caption: str
    sort_index: int
    cache_bust: str = "2"  # legacy global ?v=2; becomes a content hash on publish
    width: Optional[int] = None
    height: Optional[int] = None

    @property
    def src(self) -> str:
        return f"media/{self.section}/{self.file_name}?v={self.cache_bust}"


def render_figure(asset: Asset, *, include_dimensions: bool = False) -> str:
    """Render one <figure> line exactly as the site writes them by hand."""
    cls = LAYOUT_CLASSES.get(asset.layout)
    figure_open = f'<figure class="{cls}">' if cls else "<figure>"

    dims = ""
    if include_dimensions and asset.width and asset.height:
        dims = f' width="{asset.width}" height="{asset.height}"'

    return (
        f"{INDENT}{figure_open}"
        f'<img src="{asset.src}"'
        f' alt="{html.escape(asset.alt_text, quote=True)}"{dims}'
        f' loading="lazy">'
        f"<figcaption>{html.escape(asset.caption, quote=False)}</figcaption>"
        f"</figure>"
    )


def render_block(assets: Iterable[Asset], *, include_dimensions: bool = False) -> str:
    """Render the full run of figures for one section, in sort_index order."""
    ordered = sorted(assets, key=lambda a: a.sort_index)
    return "\n".join(
        render_figure(a, include_dimensions=include_dimensions) for a in ordered
    )


# ---------------------------------------------------------------------------
# Parsing the existing hand-written HTML (used once, to seed the database)
# ---------------------------------------------------------------------------

_GALLERY_RE = re.compile(r'<div class="gallery">(.*?)\n\s*</div>', re.S)
_FIGURE_RE = re.compile(
    r'<figure(?:\s+class="(?P<cls>[^"]*)")?>'
    r'<img\s+src="media/(?P<section>[^/]+)/(?P<file>[^"?]+)(?:\?v=(?P<ver>[^"]*))?"'
    r'\s+alt="(?P<alt>[^"]*)"'
    r'(?P<extra>[^>]*?)>'
    r"<figcaption>(?P<caption>.*?)</figcaption>"
    r"</figure>"
)


def parse_gallery(section: str, site_root: Path = SITE_ROOT) -> list[Asset]:
    """Read the current hand-written gallery for one section, in DOM order.

    DOM order matters and is not filename order — landscape currently runs
    01,02,03,05,04,07,06 by deliberate choice.
    """
    path = site_root / f"{section}.html"
    source = path.read_text()

    gallery = _GALLERY_RE.search(source)
    if not gallery:
        raise ValueError(f"{path}: no <div class=\"gallery\"> block found")

    assets: list[Asset] = []
    for i, m in enumerate(_FIGURE_RE.finditer(gallery.group(1))):
        if m.group("section") != section:
            raise ValueError(
                f"{path}: figure {i} points at media/{m.group('section')}/, "
                f"expected media/{section}/"
            )
        cls = m.group("cls")
        layout = cls if cls in LAYOUT_CLASSES else ("standard" if not cls else cls)
        if layout not in LAYOUT_CLASSES:
            raise ValueError(f"{path}: figure {i} has unknown class {cls!r}")

        file_name = m.group("file")
        assets.append(
            Asset(
                section=section,
                slug=Path(file_name).stem,
                file_name=file_name,
                layout=layout,
                alt_text=html.unescape(m.group("alt")),
                caption=html.unescape(m.group("caption")),
                sort_index=i,
                cache_bust=m.group("ver") or "2",
            )
        )

    if not assets:
        raise ValueError(f"{path}: gallery block parsed to zero figures")
    return assets


class PublishError(RuntimeError):
    """Refused to publish. Nothing was copied or recorded."""


class RewriteError(RuntimeError):
    """Refused to rewrite. The page is untouched."""


# A web JPEG must be big enough to be the real 2400px export rather than a
# thumbnail that slipped through, and small enough that a runaway file cannot
# be committed to the repo. Deployed files today run 265 KB to 1.15 MB.
MIN_LONG_EDGE = 2000
MAX_BYTES = 4 * 1024 * 1024


@dataclass
class IncomingPhoto:
    """One photo handed over by the Lightroom publish service."""

    lr_photo_uuid: str
    staged_path: str          # the rendered JPEG, already moved out of LR's temp
    title: str = ""           # -> alt text
    caption: str = ""         # -> figcaption
    layout: str = ""          # "" means keep existing / auto
    source_path: str = ""     # the master RAW, for joining back to images


def _file_facts(path: Path) -> tuple[str, int, int]:
    """(sha256, width, height), with the checks that keep bad files off the site."""
    import hashlib

    from PIL import Image

    if not path.exists():
        raise PublishError(f"staged file does not exist: {path}")

    size = path.stat().st_size
    if size > MAX_BYTES:
        raise PublishError(f"{path.name} is {size/1e6:.1f} MB, over the {MAX_BYTES/1e6:.0f} MB limit")

    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            width, height = img.size
            fmt = img.format
            exif = img.getexif()
    except PublishError:
        raise
    except Exception as exc:
        raise PublishError(f"{path.name} is not a readable image: {exc}") from exc

    if fmt != "JPEG":
        raise PublishError(f"{path.name} is {fmt}, expected JPEG")

    if max(width, height) < MIN_LONG_EDGE:
        raise PublishError(
            f"{path.name} is {width}x{height}; long edge must be at least "
            f"{MIN_LONG_EDGE}px (is the export preset still 2400?)"
        )

    # 0x8825 is the GPS IFD pointer. The export preset sets
    # LR_removeLocationMetadata, but presets drift and this file is about to be
    # served from a public CDN, so check the bytes rather than trust the setting.
    if exif is not None and 0x8825 in exif:
        raise PublishError(
            f"{path.name} still carries GPS EXIF. Refusing to publish location "
            "data to a public site."
        )

    return hashlib.sha256(path.read_bytes()).hexdigest(), width, height


# Perceptual-hash distance below which two images are treated as the same
# photograph. pHash is DCT-on-32x32-grayscale, so it survives resizing and
# re-compression; 0 is an exact perceptual match and real re-exports of the same
# frame land at 0-4. Kept deliberately tight — a false match would overwrite a
# different photo's slot on the live site, which is far worse than a duplicate.
PHASH_MATCH_DISTANCE = 6


def compute_phash(path: Path) -> Optional[str]:
    """Perceptual hash of an image, or None if it cannot be read."""
    try:
        import imagehash
        from PIL import Image

        with Image.open(path) as img:
            return str(imagehash.phash(img))
    except Exception:
        return None


def find_by_phash(conn, section: str, phash: Optional[str]) -> Optional[str]:
    """Slug of an already-published photo that looks like this one.

    This is what makes adoption unnecessary. Steven exports web-ready copies
    into his own folders long before LENS sees them, so the same photograph can
    arrive with a Lightroom uuid we have never recorded. Matching on appearance
    rather than identity means dragging a photo that is ALREADY on the site into
    a published collection updates its existing slot instead of appending a
    second copy of the same picture.

    Compares against at most a couple of dozen rows, so it is effectively free.
    """
    if not phash:
        return None
    try:
        import imagehash

        target = imagehash.hex_to_hash(phash)
    except Exception:
        return None

    best, best_distance = None, PHASH_MATCH_DISTANCE + 1
    for row in conn.execute(
        "SELECT slug, phash FROM web_assets WHERE section = ? AND phash IS NOT NULL",
        (section,),
    ):
        try:
            distance = target - imagehash.hex_to_hash(row["phash"])
        except Exception:
            continue
        if distance < best_distance:
            best, best_distance = row["slug"], distance

    return best if best_distance <= PHASH_MATCH_DISTANCE else None


def allocate_slug(conn, section: str, lr_photo_uuid: str) -> tuple[str, bool]:
    """(slug, is_new) for a photo in a section. Idempotent by construction.

    Keyed on the Lightroom photo uuid, never on file_path: virtual copies all
    report the master's path, so a web crop kept as a virtual copy would collide
    with its master.

    This is the contract that stops a timed-out publish from putting the same
    photograph on the site twice. If the HTTP response is lost after LENS has
    already allocated, Lightroom retries, and the retry finds the SAME row
    instead of allocating a second slug.
    """
    row = conn.execute(
        "SELECT slug FROM web_assets WHERE section = ? AND lr_photo_uuid = ?",
        (section, lr_photo_uuid),
    ).fetchone()
    if row:
        return row["slug"], False

    # Next free index, considering every slug ever issued for the section —
    # including retired ones, so a removed photo's number is never reused and
    # old URLs can never silently point at a different picture.
    used = {
        r["slug"] for r in conn.execute(
            "SELECT slug FROM web_assets WHERE section = ?", (section,)
        )
    }
    highest = 0
    for slug in used:
        m = re.search(r"-(\d+)$", slug)
        if m:
            highest = max(highest, int(m.group(1)))
    return f"{section}-{highest + 1:02d}", True


def rewrite_block(
    section: str,
    block: str,
    *,
    site_root: Path = SITE_ROOT,
    backup_dir: Optional[Path] = None,
) -> str:
    """Swap `block` into the section's marker fence. Returns a status string.

    "unchanged" means the file was not written at all. That short-circuit is
    what makes the whole publish pipeline safely re-runnable: rendering is a
    pure function of the assets, so re-publishing identical state is a no-op
    rather than an empty commit.

    Never opens the target in write mode. Writes a sibling temp file and
    os.replace()s it, which is atomic on APFS — a crash leaves the original
    intact rather than a half-written page.
    """
    path = site_root / f"{section}.html"
    if not path.exists():
        raise RewriteError(f"{path} does not exist")

    source = path.read_text()
    start, end = find_fence(source, section, path)

    head, current, tail = source[:start], source[start:end], source[end:]
    replacement = wrap_fence(block)

    if current == replacement:
        return "unchanged"

    new_source = head + replacement + tail

    # Invariant: everything outside the fence must be untouched. This is the
    # cheapest and strongest check available — if head or tail moved, the fence
    # was located wrongly and we would be rewriting the wrong region of a live
    # page.
    if not new_source.startswith(head) or not new_source.endswith(tail):
        raise RewriteError(f"{path}: rewrite would alter content outside the fence")

    n_open = block.count("<figure")
    n_close = block.count("</figure>")
    if n_open != n_close:
        raise RewriteError(
            f"{section}: unbalanced figures in rendered block "
            f"({n_open} open, {n_close} close)"
        )

    if backup_dir is not None:
        backup_dir.mkdir(parents=True, exist_ok=True)
        (backup_dir / path.name).write_text(source)

    tmp = path.with_suffix(path.suffix + ".lens-tmp")
    try:
        with open(tmp, "w") as fh:
            fh.write(new_source)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()

    return "rewritten"


def publish_photos(
    conn,
    section: str,
    photos: Sequence[IncomingPhoto],
    *,
    site_root: Path = SITE_ROOT,
) -> list[dict]:
    """Place rendered JPEGs into the repo and record them. Does NOT commit.

    Returns one result dict per photo: slug, url, sha, status. Status is
    "new", "updated" (bytes or metadata changed) or "unchanged".

    Ordering matters and is deliberate: media files are written BEFORE the HTML
    that references them, and neither is committed here. An unreferenced JPEG
    sitting in the repo is harmless; an HTML page referencing a file that is not
    there yet is a broken image on a live site.
    """
    import shutil

    from lens_core.tz import now_et

    media_dir = site_root / "media" / section
    if not media_dir.is_dir():
        raise PublishError(f"no media directory for section {section!r}: {media_dir}")

    stamp = now_et().isoformat()
    results: list[dict] = []

    for photo in photos:
        staged = Path(photo.staged_path)
        sha, width, height = _file_facts(staged)
        phash = compute_phash(staged)

        # Identity first (same Lightroom photo we have seen before), then
        # APPEARANCE. The appearance check is what removes any need for a manual
        # adoption pass: Steven prepares web-ready exports in his own folders, so
        # a photo already on the site can easily arrive with a uuid LENS has
        # never recorded. Without this it would be appended as a second copy of
        # a picture already published.
        slug, is_new = allocate_slug(conn, section, photo.lr_photo_uuid)
        if is_new:
            twin = find_by_phash(conn, section, phash)
            if twin:
                slug, is_new = twin, False
        file_name = f"{slug}.jpg"
        target = media_dir / file_name

        existing = conn.execute(
            "SELECT sha256, layout, alt_text, caption, sort_index, state, cache_bust "
            "FROM web_assets WHERE section = ? AND slug = ?",
            (section, slug),
        ).fetchone()

        # Skip the copy when the bytes already match. metadataThatTriggersRepublish
        # re-lights the Publish button on every caption edit, so Lightroom will
        # re-render an identical JPEG constantly; copying it each time would churn
        # the repo for nothing.
        bytes_changed = not (existing and existing["sha256"] == sha and target.exists())
        if bytes_changed:
            tmp = target.with_suffix(".jpg.lens-tmp")
            try:
                shutil.copyfile(staged, tmp)
                os.replace(tmp, target)
            finally:
                if tmp.exists():
                    tmp.unlink()

        layout = photo.layout or (existing["layout"] if existing else None) or "standard"
        if layout not in LAYOUT_CLASSES:
            raise PublishError(f"{slug}: unknown layout {layout!r}")
        # `tall` forces aspect-ratio 4/5 with object-fit:cover, so a landscape
        # frame in a tall slot silently loses more than half its width.
        if layout == "tall" and width > height:
            raise PublishError(
                f"{slug} is landscape ({width}x{height}); the 'tall' layout would "
                "crop it to 4:5 and discard most of the frame."
            )

        alt = photo.title.strip() or (existing["alt_text"] if existing else "") or ""
        cap = photo.caption.strip() or (existing["caption"] if existing else "") or ""

        if existing:
            changed = (
                bytes_changed
                or existing["layout"] != layout
                or (existing["alt_text"] or "") != alt
                or (existing["caption"] or "") != cap
                or existing["state"] != "live"
            )
            conn.execute(
                """UPDATE web_assets
                      SET sha256=?, width=?, height=?, layout=?, alt_text=?, caption=?,
                          lr_photo_uuid=?, source_path=?, state='live',
                          cache_bust=?, phash=?, last_published_at=?
                    WHERE section=? AND slug=?""",
                # Only move the cache buster when the BYTES changed. A caption
                # edit must not invalidate a CDN copy that is still correct.
                (sha, width, height, layout, alt, cap, photo.lr_photo_uuid,
                 photo.source_path or None,
                 sha[:8] if bytes_changed else (existing["cache_bust"] or "2"),
                 phash, stamp, section, slug),
            )
            status = "updated" if changed else "unchanged"
        else:
            next_index = conn.execute(
                "SELECT COALESCE(MAX(sort_index), -1) + 1 FROM web_assets "
                "WHERE section = ? AND state = 'live'",
                (section,),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO web_assets
                     (section, slug, lr_photo_uuid, source_path, file_name, sha256,
                      width, height, layout, alt_text, caption, sort_index, state,
                      cache_bust, phash, first_published_at, last_published_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'live',?,?,?,?)""",
                (section, slug, photo.lr_photo_uuid, photo.source_path or None,
                 file_name, sha, width, height, layout, alt, cap, next_index,
                 sha[:8], phash, stamp, stamp),
            )
            status = "new"

        results.append({
            "lr_photo_uuid": photo.lr_photo_uuid,
            "slug": slug,
            "url": f"https://stevenhowardphotography.com/{section}#{slug}",
            "sha": sha[:8],
            "status": status,
        })

    return results


def set_order(conn, section: str, slugs: Sequence[str]) -> bool:
    """Apply Lightroom's collection order. Returns True if anything moved."""
    current = [a.slug for a in load_assets(section, conn)]
    desired = [s for s in slugs if s in set(current)]

    # Anything Lightroom did not mention keeps its relative position at the end,
    # so a partial order can never silently drop a photo off the page.
    desired += [s for s in current if s not in set(desired)]

    if desired == current:
        return False

    for i, slug in enumerate(desired):
        conn.execute(
            "UPDATE web_assets SET sort_index = ? WHERE section = ? AND slug = ?",
            (i, section, slug),
        )
    return True


def load_assets(section: str, conn) -> list[Asset]:
    """Live assets for one section, in publish order, straight from the DB."""
    rows = conn.execute(
        """SELECT section, slug, file_name, layout, alt_text, caption,
                  sort_index, width, height, cache_bust
             FROM web_assets
            WHERE section = ? AND state = 'live'
            ORDER BY sort_index""",
        (section,),
    ).fetchall()
    return [
        Asset(
            section=r["section"],
            slug=r["slug"],
            file_name=r["file_name"],
            layout=r["layout"],
            alt_text=r["alt_text"] or "",
            caption=r["caption"] or "",
            sort_index=r["sort_index"],
            width=r["width"],
            height=r["height"],
            cache_bust=r["cache_bust"] or "2",
        )
        for r in rows
    ]


def wrap_fence(block: str) -> str:
    """The exact text that belongs between the two markers.

    Kept as a single function so the writer and the reader can never drift:
    a newline after START, the rendered figures, then a newline and the END
    marker's own indent. `unwrap_fence` is its exact inverse.
    """
    return f"\n{block}\n{INDENT}"


def unwrap_fence(raw: str) -> str:
    """Inverse of wrap_fence: the rendered block with the fence padding removed.

    Cannot be a plain .strip() — that would eat the leading indent of the first
    figure line and break byte-for-byte comparison.
    """
    return re.sub(r"\n[ \t]*$", "", raw.lstrip("\n"))


def find_fence(source: str, section: str, path: Path) -> tuple[int, int]:
    """Byte offsets of the content between the markers, exclusive.

    Requires EXACTLY one marker pair, correctly ordered. Anything else is a
    hand-edit or a botched previous write, and must abort rather than guess —
    a wrong guess here rewrites the wrong region of a live page.
    """
    start_tag = MARKER_START.format(section=section)
    end_tag = MARKER_END.format(section=section)

    n_start, n_end = source.count(start_tag), source.count(end_tag)
    if n_start != 1 or n_end != 1:
        raise ValueError(
            f"{path}: expected exactly one {section} marker pair, "
            f"found {n_start} START and {n_end} END"
        )

    start = source.index(start_tag) + len(start_tag)
    end = source.index(end_tag)
    if end < start:
        raise ValueError(f"{path}: {section} END marker precedes START")

    # The fence must live inside the gallery div. css/styles.css sets
    # `.gallery figure { opacity: 0 }` and js/main.js only adds the .reveal
    # class to `.gallery figure` — so figures written outside that container
    # are invisible on the page with no error anywhere.
    gallery_open = source.rfind('<div class="gallery">', 0, start)
    if gallery_open == -1:
        raise ValueError(f"{path}: {section} fence is not inside a .gallery div")
    if source.find("</div>", gallery_open, start) != -1:
        raise ValueError(f"{path}: {section} fence is not inside a .gallery div")

    return start, end


def extract_block(section: str, site_root: Path = SITE_ROOT) -> str:
    """The current gallery block, verbatim, for round-trip comparison.

    Prefers the marker fence; falls back to the whole .gallery div for pages
    that have not been fenced yet.
    """
    path = site_root / f"{section}.html"
    source = path.read_text()

    if MARKER_START.format(section=section) in source:
        start, end = find_fence(source, section, path)
        return unwrap_fence(source[start:end])

    gallery = _GALLERY_RE.search(source)
    if not gallery:
        raise ValueError(f"{path}: no gallery block found")
    return gallery.group(1).strip("\n")
