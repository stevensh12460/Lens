"""
pipeline/social_evaluator.py

Post-pass3 hook: evaluates newly tagged images for Instagram posting.
Called by queue_manager after pass3 completes.
"""
import logging
from datetime import datetime, timedelta

from core.database import get_db
from services.grid_aesthetic import evaluate_grid_fit
from services.social_queue import DAY_PILLARS

logger = logging.getLogger("lens.social_evaluator")

_GRID_FIT_THRESHOLD = 0.6


def evaluate_new_images(limit: int = 50) -> dict:
    """
    Find images that are content-ready but haven't been scored for grid fit yet.
    Run the grid aesthetic evaluator and mark qualifying images for the social queue.

    Returns summary dict with counts.
    """
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id FROM images
            WHERE content_ready = TRUE
              AND (social_queue = FALSE OR social_queue IS NULL)
              AND posted_at IS NULL
              AND grid_fit_score IS NULL
            ORDER BY pass3_at DESC
            LIMIT ?
        """, (limit,)).fetchall()

    if not rows:
        return {"evaluated": 0, "queued": 0, "skipped": 0}

    evaluated = 0
    queued = 0
    skipped = 0

    for row in rows:
        image_id = row["id"]
        try:
            result = evaluate_grid_fit(image_id)
            evaluated += 1

            if result["score"] >= _GRID_FIT_THRESHOLD:
                with get_db() as conn:
                    conn.execute(
                        "UPDATE images SET social_queue = TRUE WHERE id = ?",
                        (image_id,),
                    )
                queued += 1
                logger.debug(f"[social] image {image_id} queued (score={result['score']:.3f})")
            else:
                skipped += 1
                logger.debug(f"[social] image {image_id} skipped (score={result['score']:.3f})")
        except Exception as e:
            logger.warning(f"[social] error evaluating image {image_id}: {e}")

    summary = {"evaluated": evaluated, "queued": queued, "skipped": skipped}
    if evaluated:
        logger.info(f"[social] evaluated={evaluated}, queued={queued}, skipped={skipped}")
    return summary


def auto_fill_calendar() -> dict:
    """
    DISABLED — never auto-pick photos for the IG calendar.

    Inappropriate photos (boudoir/wedding) were getting auto-selected and
    inserted into the IG calendar. Brand risk. Calendar is now manual-pick
    only via the Post Candidate Pool. Body intentionally gutted so any
    accidental future caller is a no-op.
    """
    logger.warning("[social] auto_fill_calendar() called but is permanently disabled — no-op")
    return {"slots_checked": 0, "filled": 0, "disabled": True}
