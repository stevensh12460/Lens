"""
services/post_scheduler.py

Post scheduling and publishing — handles auto-posting via Instagram Graph API.

SAFETY MODEL:
- publish_post(dry_run=True) by default. Caller must explicitly pass dry_run=False
  to actually publish to Instagram.
- dry_run mode performs steps 1-2 (create container, poll status) but stops
  BEFORE step 3 (media_publish). The container expires unused in ~24h and is
  never publicly visible during this window.
- Real publish (dry_run=False) does all 3 steps and updates the DB.

Graph API publish flow (https://developers.facebook.com/docs/instagram-api/guides/content-publishing):
  1. POST /{ig-user-id}/media       → returns creation_id (container)
  2. GET  /{creation_id}?fields=status_code   → poll until FINISHED
  3. POST /{ig-user-id}/media_publish?creation_id=...  → posts to feed
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from core.database import get_db
from core.config import settings
from core.tz import now_et, parse_et, to_iso_et, minutes_between


GRAPH_API = "https://graph.facebook.com/v19.0"
CONTAINER_POLL_SECONDS = 3
CONTAINER_MAX_POLLS = 20  # 60s total — IG usually finishes in <10s

# Auto-publish window: how close to scheduled_at we'll fire. Anything older or
# newer than this is silently ignored. Prevents stale posts going out hours late.
AUTO_PUBLISH_WINDOW_MIN = 15

# Kill-switch file: if this exists, the auto-publisher will exit immediately
# without checking anything. Provides an emergency off-switch independent of launchd.
KILL_SWITCH = Path.home() / "lens" / "AUTO_PUBLISH_DISABLED"


def _build_caption(post: dict) -> str:
    """Combine caption body + hashtags into the final IG caption string."""
    caption = (post.get("caption") or post.get("caption_draft") or "").strip()
    raw = post.get("hashtags") or ""
    tags = []
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                tags = [str(h).lstrip("#").strip() for h in parsed if h]
        except (ValueError, TypeError):
            tags = [t.lstrip("#").strip() for t in raw.split() if t.strip()]
    tag_str = " ".join(f"#{t}" for t in tags)
    return f"{caption}\n\n{tag_str}".strip() if tag_str else caption


def _resolve_public_image_url(post: dict) -> str | None:
    """
    Return a publicly-reachable HTTPS URL for the image, or None.
    Priority: explicit pixieset_url > settings.public_image_base + image_id.
    Local file paths are NOT acceptable — IG fetches the URL server-side.
    """
    if post.get("pixieset_url"):
        return post["pixieset_url"]
    base = getattr(settings, "public_image_base_url", "") or ""
    if base and post.get("image_id"):
        return f"{base.rstrip('/')}/api/v1/images/{post['image_id']}/thumb.jpg"
    return None


async def _create_container(client: httpx.AsyncClient, image_url: str, caption: str) -> dict:
    """Step 1: stage the post as a container. Container is NOT yet visible publicly."""
    url = f"{GRAPH_API}/{settings.instagram_account_id}/media"
    params = {
        "image_url": image_url,
        "caption": caption,
        "access_token": settings.instagram_access_token,
    }
    r = await client.post(url, params=params, timeout=30)
    if r.status_code != 200:
        return {"ok": False, "error": f"create_container: {r.status_code} {r.text}"}
    data = r.json()
    creation_id = data.get("id")
    if not creation_id:
        return {"ok": False, "error": f"create_container: no id in response {data}"}
    return {"ok": True, "creation_id": creation_id}


async def _poll_container(client: httpx.AsyncClient, creation_id: str) -> dict:
    """Step 2: poll until container reports FINISHED (or ERROR)."""
    url = f"{GRAPH_API}/{creation_id}"
    for attempt in range(CONTAINER_MAX_POLLS):
        params = {"fields": "status_code,status", "access_token": settings.instagram_access_token}
        r = await client.get(url, params=params, timeout=15)
        if r.status_code != 200:
            return {"ok": False, "error": f"poll: {r.status_code} {r.text}"}
        data = r.json()
        code = data.get("status_code")
        if code == "FINISHED":
            return {"ok": True, "status_code": code, "polls": attempt + 1}
        if code in ("ERROR", "EXPIRED"):
            return {"ok": False, "error": f"container {code}: {data.get('status', '')}"}
        await asyncio.sleep(CONTAINER_POLL_SECONDS)
    return {"ok": False, "error": "container did not finish within poll budget"}


async def _publish_container(client: httpx.AsyncClient, creation_id: str) -> dict:
    """Step 3: actually post the container. THIS IS THE PUBLIC ACTION."""
    url = f"{GRAPH_API}/{settings.instagram_account_id}/media_publish"
    params = {"creation_id": creation_id, "access_token": settings.instagram_access_token}
    r = await client.post(url, params=params, timeout=30)
    if r.status_code != 200:
        return {"ok": False, "error": f"publish: {r.status_code} {r.text}"}
    data = r.json()
    media_id = data.get("id")
    if not media_id:
        return {"ok": False, "error": f"publish: no media id in response {data}"}
    return {"ok": True, "media_id": media_id}


async def publish_post(post_id: int, dry_run: bool = True) -> dict:
    """
    Publish a calendar post to Instagram.

    Args:
        post_id: calendar_posts.id
        dry_run: if True (default), creates the IG container and verifies it but
                 does NOT call media_publish. Container expires unused in 24h.
                 Pass dry_run=False to actually publish to the feed.
    """
    with get_db() as conn:
        row = conn.execute(
            """SELECT cp.*, i.file_path, i.file_name, i.caption_draft, i.pixieset_url
               FROM calendar_posts cp
               LEFT JOIN images i ON cp.image_id = i.id
               WHERE cp.id = ?""",
            (post_id,),
        ).fetchone()
    if not row:
        return {"status": "error", "error": f"Post {post_id} not found"}
    post = dict(row)

    if not settings.instagram_access_token or not settings.instagram_account_id:
        return {"status": "error", "error": "Instagram API not configured"}

    full_caption = _build_caption(post)
    if len(full_caption) > 2200:
        return {"status": "error", "error": f"Caption too long: {len(full_caption)} (max 2200)"}

    image_url = _resolve_public_image_url(post)
    if not image_url:
        return {
            "status": "error",
            "error": "No public image URL. Need pixieset_url on the image OR PUBLIC_IMAGE_BASE_URL in .env",
        }

    async with httpx.AsyncClient() as client:
        c = await _create_container(client, image_url, full_caption)
        if not c["ok"]:
            return {"status": "error", "stage": "create_container", "error": c["error"]}
        creation_id = c["creation_id"]

        s = await _poll_container(client, creation_id)
        if not s["ok"]:
            return {
                "status": "error",
                "stage": "poll_container",
                "creation_id": creation_id,
                "error": s["error"],
            }

        if dry_run:
            return {
                "status": "dry_run_ok",
                "post_id": post_id,
                "creation_id": creation_id,
                "container_status": s["status_code"],
                "polls": s["polls"],
                "image_url": image_url,
                "caption_length": len(full_caption),
                "note": "Container created and verified. NOT published. Container expires unused in ~24h.",
            }

        # Real publish
        p = await _publish_container(client, creation_id)
        if not p["ok"]:
            return {
                "status": "error",
                "stage": "publish",
                "creation_id": creation_id,
                "error": p["error"],
            }

    # Update DB only on real success — store tz-aware ET (per feedback_timezone.md)
    now = to_iso_et(now_et())
    with get_db() as conn:
        conn.execute(
            "UPDATE calendar_posts SET status = 'posted', posted_at = ? WHERE id = ?",
            (now, post_id),
        )
        if post.get("image_id"):
            conn.execute(
                "UPDATE images SET posted_at = ?, posted_to = 'instagram' WHERE id = ?",
                (now, post["image_id"]),
            )
    return {
        "status": "posted",
        "post_id": post_id,
        "media_id": p["media_id"],
        "posted_at": now,
        "caption_length": len(full_caption),
    }


# ── Auto-publisher (fires every 5 min via launchd) ────────────────────────────

async def _check_tunnel(image_id: int, log: logging.Logger) -> tuple[bool, str]:
    """HEAD the public image URL. Returns (ok, reason).

    Catches the most common deployment failure: the Cloudflare quick tunnel
    rotated overnight and PUBLIC_IMAGE_BASE_URL in .env is now stale, so Meta
    can't fetch the image and the post would fail with error 9004.
    """
    base = (getattr(settings, "public_image_base_url", "") or "").strip()
    if not base:
        return False, "PUBLIC_IMAGE_BASE_URL not set in .env"
    url = f"{base.rstrip('/')}/api/v1/images/{image_id}/thumb.jpg"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.head(url, follow_redirects=True)
        if r.status_code != 200:
            return False, f"thumb HEAD {r.status_code} ({url})"
        return True, "ok"
    except Exception as e:
        return False, f"tunnel unreachable: {type(e).__name__}: {e}"


async def _check_token(log: logging.Logger) -> tuple[bool, str]:
    """Verify the IG access token is still valid via /me. Returns (ok, reason)."""
    token = (settings.instagram_access_token or "").strip()
    if not token:
        return False, "INSTAGRAM_ACCESS_TOKEN not set"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{GRAPH_API}/me",
                params={"access_token": token, "fields": "id"},
            )
        if r.status_code != 200:
            return False, f"token /me check failed {r.status_code}: {r.text[:120]}"
        return True, "ok"
    except Exception as e:
        return False, f"token check failed: {type(e).__name__}: {e}"


async def auto_publish_due(
    window_min: int = AUTO_PUBLISH_WINDOW_MIN,
    log: logging.Logger | None = None,
) -> dict:
    """Find scheduled posts whose scheduled_at is within ±window_min of now,
    apply all safety guardrails, then dry-run + real-publish in sequence.

    Returns a summary dict of posted / skipped / errored ids with reasons.
    """
    log = log or logging.getLogger("post-scheduler")
    summary = {
        "checked": 0,
        "in_window": 0,
        "posted": [],
        "skipped": [],
        "errors": [],
    }

    # Kill switch: instant abort. Lets the user disable auto-publishing without
    # tearing down the launchd service.
    if KILL_SWITCH.exists():
        log.info(f"kill switch present at {KILL_SWITCH} — aborting")
        summary["skipped"].append({"reason": "kill switch active"})
        return summary

    # ET-aware "now" — comparisons against scheduled_at must be tz-aware.
    # Bug fixed 2026-05-06 (post #131 fired at 4:48 AM ET because both sides
    # were naive and "9 AM" was treated as UTC). See core/tz.py.
    now = now_et()

    with get_db() as conn:
        rows = conn.execute(
            """SELECT cp.id, cp.post_date, cp.post_time, cp.scheduled_at, cp.status,
                      cp.image_id, cp.caption, cp.hashtags
               FROM calendar_posts cp
               WHERE cp.status = 'scheduled' AND cp.scheduled_at IS NOT NULL""",
        ).fetchall()

    summary["checked"] = len(rows)

    for row in rows:
        post = dict(row)
        post_id = post["id"]

        # Parse scheduled_at as tz-aware ET. parse_et() promotes legacy naive
        # values to ET to keep older rows behaving correctly while we backfill.
        try:
            sched = parse_et(post["scheduled_at"])
        except (ValueError, TypeError):
            log.warning(f"post {post_id}: bad scheduled_at {post['scheduled_at']!r}, skipping")
            summary["skipped"].append({"id": post_id, "reason": "bad scheduled_at"})
            continue

        delta_min = minutes_between(now, sched)
        if delta_min > window_min:
            # Silent skip for posts not in window — happens every fire for posts
            # scheduled later today or for tomorrow. Don't spam logs.
            continue

        summary["in_window"] += 1
        log.info(f"post {post_id}: in window ({delta_min:.1f}m from scheduled), checking guards")

        # Guard 1: caption non-empty.
        cap = (post.get("caption") or "").strip()
        if not cap:
            reason = "empty caption — was this approved without saving?"
            log.warning(f"post {post_id} SKIP: {reason}")
            summary["skipped"].append({"id": post_id, "reason": reason})
            continue

        # Guard 2: image must exist on the row.
        if not post.get("image_id"):
            reason = "no image_id"
            log.warning(f"post {post_id} SKIP: {reason}")
            summary["skipped"].append({"id": post_id, "reason": reason})
            continue

        # Guard 3: tunnel HEAD — catches stale Cloudflare quick tunnel URL.
        ok, reason = await _check_tunnel(post["image_id"], log)
        if not ok:
            log.error(f"post {post_id} SKIP: tunnel guard: {reason}")
            summary["skipped"].append({"id": post_id, "reason": f"tunnel: {reason}"})
            continue

        # Guard 4: IG token validity.
        ok, reason = await _check_token(log)
        if not ok:
            log.error(f"post {post_id} SKIP: token guard: {reason}")
            summary["skipped"].append({"id": post_id, "reason": f"token: {reason}"})
            continue

        # Guard 5: dry-run must succeed before real publish.
        log.info(f"post {post_id}: running dry-run...")
        dry = await publish_post(post_id, dry_run=True)
        if dry.get("status") != "dry_run_ok":
            log.error(f"post {post_id} ERROR dry-run: {dry}")
            summary["errors"].append({"id": post_id, "stage": "dry_run", "result": dry})
            continue
        log.info(f"post {post_id}: dry-run ok creation_id={dry.get('creation_id')}")

        # Real publish.
        log.info(f"post {post_id}: REAL PUBLISH")
        real = await publish_post(post_id, dry_run=False)
        if real.get("status") == "posted":
            log.info(f"post {post_id}: POSTED media_id={real.get('media_id')}")
            summary["posted"].append({"id": post_id, "media_id": real.get("media_id")})
        else:
            log.error(f"post {post_id} ERROR publish: {real}")
            summary["errors"].append({"id": post_id, "stage": "publish", "result": real})

    return summary


def main() -> None:
    """Launchd entrypoint. Runs auto_publish_due() once and exits.

    Configured to fire every 5 minutes via launchd/com.lens.post-scheduler.plist.
    Idempotent: only acts on posts within the ±15min publish window AND with
    status='scheduled'. After publish, status flips to 'posted' so subsequent
    fires don't re-process.
    """
    log_dir = Path.home() / "lens" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "post-scheduler.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler(),
        ],
        force=True,
    )
    log = logging.getLogger("post-scheduler")

    log.info(f"=== auto-publish run {to_iso_et(now_et())} ===")
    try:
        summary = asyncio.run(auto_publish_due(log=log))
        log.info(
            f"=== summary: checked={summary['checked']} in_window={summary['in_window']} "
            f"posted={len(summary['posted'])} skipped={len(summary['skipped'])} "
            f"errors={len(summary['errors'])} ==="
        )
        if summary["posted"]:
            log.info(f"posted ids: {summary['posted']}")
        if summary["skipped"]:
            log.info(f"skipped: {summary['skipped']}")
        if summary["errors"]:
            log.error(f"errors: {summary['errors']}")
    except Exception as e:
        log.exception(f"=== CRASH: {type(e).__name__}: {e} ===")
        raise


if __name__ == "__main__":
    main()
