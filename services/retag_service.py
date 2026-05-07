"""
services/retag_service.py

Retag Queue — re-runs pass3 vision tagging on images flagged as mis-tagged.
Called from the scheduling mode panel after the user flags wrong-genre images
in the candidate pool.

Mirrors the pipeline approach: one image at a time, shared semaphore,
long timeout (pass3 takes ~580s/img on 32b).

Uses a background task with progress tracking so the UI can poll for updates.
"""
import asyncio
import logging
import time
from pathlib import Path

from core.database import get_db
from pipeline.pass3_tag import _tag_single
from services.grid_aesthetic import evaluate_grid_fit

logger = logging.getLogger("lens.retag_service")

_GRID_FIT_THRESHOLD = 0.6

# ── Progress state (in-memory, single-worker safe) ──────────────────────────
_retag_progress = {
    "running": False,
    "total": 0,
    "completed": 0,
    "errors": 0,
    "current_file": None,
    "current_id": None,
    "started_at": None,
    "results": [],
}


def get_retag_progress() -> dict:
    """Return current retag processing progress for UI polling."""
    p = _retag_progress.copy()
    p["results"] = list(p["results"])  # shallow copy
    remaining = p["total"] - p["completed"]
    # ETA based on avg time per completed image
    if p["completed"] > 0 and p["started_at"]:
        elapsed = time.time() - p["started_at"]
        avg_per_image = elapsed / p["completed"]
        p["eta_seconds"] = round(avg_per_image * remaining)
        p["avg_seconds_per_image"] = round(avg_per_image)
    else:
        p["eta_seconds"] = None
        p["avg_seconds_per_image"] = None
    p["remaining"] = remaining
    return p


def get_retag_queue() -> list[dict]:
    """Return all images currently flagged for retagging."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, file_path, file_name, genre, mood, tags,
                      grid_fit_score, nima_composite, quality_score,
                      content_ready, retag_queued, retag_note
               FROM images
               WHERE retag_queued = TRUE
               ORDER BY id DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def flag_for_retag(image_id: int, note: str = None) -> dict:
    """
    Flag an image as mis-tagged. Removes it from the social queue until
    re-evaluated. Optionally store a user note about what's wrong.
    """
    with get_db() as conn:
        img = conn.execute(
            "SELECT id, genre, file_name FROM images WHERE id = ?", (image_id,)
        ).fetchone()
        if not img:
            raise ValueError(f"Image {image_id} not found")

        conn.execute(
            """UPDATE images
               SET retag_queued = TRUE,
                   social_queue  = FALSE,
                   retag_note    = ?
               WHERE id = ?""",
            (note, image_id),
        )
    logger.info(f"[retag] flagged image {image_id} ({img['file_name']}, was genre={img['genre']})")
    return {"image_id": image_id, "status": "flagged", "previous_genre": img["genre"]}


def unflag_retag(image_id: int) -> dict:
    """Remove the retag flag without re-processing (user changed their mind)."""
    with get_db() as conn:
        conn.execute(
            "UPDATE images SET retag_queued = FALSE, retag_note = NULL WHERE id = ?",
            (image_id,),
        )
    return {"image_id": image_id, "status": "unflagged"}


async def _retag_one(image_id: int, semaphore: asyncio.Semaphore) -> dict:
    """
    Re-run pass3 on a single image, exactly like the pipeline does:
    one at a time through a shared semaphore.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT file_path, genre FROM images WHERE id = ?",
            (image_id,),
        ).fetchone()
    if not row:
        return {"image_id": image_id, "status": "error", "error": "not found"}

    file_path = Path(row["file_path"])
    old_genre = row["genre"]

    if not file_path.exists():
        logger.warning(f"[retag] file missing: {file_path}")
        with get_db() as conn:
            conn.execute(
                "UPDATE images SET retag_queued = FALSE WHERE id = ?", (image_id,)
            )
        return {"image_id": image_id, "status": "error", "error": "file_not_found"}

    # Update progress — currently processing this image
    _retag_progress["current_file"] = file_path.name
    _retag_progress["current_id"] = image_id

    # Re-run pass3 tagging — _tag_single uses the shared semaphore
    # and writes updated genre/mood/tags/etc directly to the DB
    result = await _tag_single(file_path, semaphore)

    if result.get("status") == "error":
        error_msg = result.get("error", "unknown")
        logger.warning(f"[retag] pass3 failed for {image_id}: {error_msg}")
        return {"image_id": image_id, "status": "error", "error": error_msg}

    new_genre = result.get("genre", old_genre)
    genre_changed = new_genre != old_genre

    # Re-score grid fit
    grid_score = None
    requeued = False
    try:
        gf = evaluate_grid_fit(image_id)
        grid_score = gf.get("score")
        if grid_score is not None and grid_score >= _GRID_FIT_THRESHOLD:
            requeued = True
    except Exception as e:
        logger.warning(f"[retag] grid_fit failed for {image_id}: {e}")

    # If genre changed, update any calendar posts using this image
    # and remove the post if the new genre no longer fits
    calendar_removed = 0
    if genre_changed:
        with get_db() as conn:
            # Update genre on calendar posts that reference this image
            conn.execute(
                "UPDATE calendar_posts SET genre = ? WHERE image_id = ? AND status != 'posted'",
                (new_genre, image_id),
            )
            # If the new genre doesn't match safe genres,
            # remove unposted calendar posts using this image
            _SAFE_GENRES = {"nature", "landscape"}
            if new_genre and new_genre not in _SAFE_GENRES:
                cursor = conn.execute(
                    "DELETE FROM calendar_posts WHERE image_id = ? AND status NOT IN ('posted', 'scheduled')",
                    (image_id,),
                )
                calendar_removed = cursor.rowcount
                if calendar_removed:
                    logger.info(
                        f"[retag] removed {calendar_removed} calendar post(s) for image {image_id} "
                        f"— genre changed to '{new_genre}' (not in safe genres)"
                    )

    # Clear retag flag, update social_queue
    with get_db() as conn:
        conn.execute(
            """UPDATE images
               SET retag_queued = FALSE,
                   retag_note   = NULL,
                   social_queue = ?
               WHERE id = ?""",
            (requeued, image_id),
        )

    gf_str = f"{grid_score:.3f}" if grid_score is not None else "n/a"
    cal_str = f" | removed {calendar_removed} calendar post(s)" if calendar_removed else ""
    logger.info(
        f"[retag] {image_id}: {old_genre} -> {new_genre} | "
        f"grid_fit={gf_str} | requeued={requeued}{cal_str}"
    )
    return {
        "image_id": image_id,
        "status": "retagged",
        "old_genre": old_genre,
        "new_genre": new_genre,
        "genre_changed": genre_changed,
        "grid_fit_score": grid_score,
        "requeued": requeued,
        "calendar_posts_removed": calendar_removed,
    }


async def _process_retag_background(image_ids: list[int]) -> None:
    """
    Background worker: process retag queue one image at a time.
    Updates _retag_progress after each image so the UI can poll.
    """
    _retag_progress.update({
        "running": True,
        "total": len(image_ids),
        "completed": 0,
        "errors": 0,
        "current_file": None,
        "current_id": None,
        "started_at": time.time(),
        "results": [],
    })

    semaphore = asyncio.Semaphore(1)

    for img_id in image_ids:
        result = await _retag_one(img_id, semaphore)
        _retag_progress["completed"] += 1
        if result["status"] == "error":
            _retag_progress["errors"] += 1
        _retag_progress["results"].append(result)

    _retag_progress["running"] = False
    _retag_progress["current_file"] = None
    _retag_progress["current_id"] = None

    total = _retag_progress["completed"]
    errors = _retag_progress["errors"]
    logger.info(f"[retag] background queue done: {total - errors}/{total} retagged, {errors} errors")


def start_retag_processing(limit: int = 50) -> dict:
    """
    Kick off background retag processing. Returns immediately.
    UI should poll GET /social/retag-progress for updates.
    """
    if _retag_progress["running"]:
        return {
            "status": "already_running",
            **get_retag_progress(),
        }

    with get_db() as conn:
        rows = conn.execute(
            "SELECT id FROM images WHERE retag_queued = TRUE ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()

    if not rows:
        return {"status": "empty", "total": 0}

    image_ids = [r["id"] for r in rows]

    # Launch as a background task in the current event loop
    loop = asyncio.get_event_loop()
    loop.create_task(_process_retag_background(image_ids))

    return {
        "status": "started",
        "total": len(image_ids),
        "message": f"Processing {len(image_ids)} images in background. Poll /social/retag-progress for updates.",
    }
