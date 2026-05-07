"""
Phase 11 — Priority Queue
4-tier priority queue system. Manages which images get processed in what order.

Priority tiers (lower number = higher priority):
  1 — Top 500 by nima_composite score
  2 — All lr_pick = 'pick' images
  3 — All images where nima_composite >= 6.0 (not in tier 1 or 2)
  4 — Everything else still needing pass3
"""
from pathlib import Path
from typing import Optional

from core.database import get_db
from pipeline.idle_monitor import ProcessingMode

_BASELINE_RATE = 230          # images processed per hour (baseline estimate)
_TOP_N = 500                  # number of images in priority 1
_NIMA_THRESHOLD_P3 = 6.0      # minimum nima_composite for priority 3


def build_priority_queue() -> dict:
    """
    Count images in each priority tier that still need Pass 3.
    Returns per-tier totals and remaining counts.
    """
    with get_db() as conn:
        # Priority 1 — top 500 by nima_composite
        p1_total = _TOP_N
        p1_complete = conn.execute("""
            SELECT COUNT(*) FROM (
                SELECT id FROM images
                WHERE nima_composite IS NOT NULL
                ORDER BY nima_composite DESC
                LIMIT ?
            ) top
            JOIN images i ON top.id = i.id
            WHERE i.pass3_at IS NOT NULL
        """, (_TOP_N,)).fetchone()[0]
        # Simpler equivalent that works correctly:
        p1_complete = conn.execute("""
            SELECT COUNT(*) FROM images
            WHERE id IN (
                SELECT id FROM images
                WHERE nima_composite IS NOT NULL
                ORDER BY nima_composite DESC
                LIMIT ?
            )
            AND pass3_at IS NOT NULL
        """, (_TOP_N,)).fetchone()[0]
        p1_remaining = max(0, p1_total - p1_complete)

        # Priority 2 — lr_pick = 'pick'
        p2_total = conn.execute(
            "SELECT COUNT(*) FROM images WHERE lr_pick = 'pick'"
        ).fetchone()[0]
        p2_complete = conn.execute(
            "SELECT COUNT(*) FROM images WHERE lr_pick = 'pick' AND pass3_at IS NOT NULL"
        ).fetchone()[0]
        p2_remaining = max(0, p2_total - p2_complete)

        # Priority 3 — nima_composite >= threshold, not top-500, not lr_pick='pick'
        p3_total = conn.execute("""
            SELECT COUNT(*) FROM images
            WHERE nima_composite >= ?
            AND pass2_at IS NOT NULL
            AND id NOT IN (
                SELECT id FROM images
                WHERE nima_composite IS NOT NULL
                ORDER BY nima_composite DESC
                LIMIT ?
            )
            AND lr_pick != 'pick'
        """, (_NIMA_THRESHOLD_P3, _TOP_N)).fetchone()[0]
        p3_complete = conn.execute("""
            SELECT COUNT(*) FROM images
            WHERE nima_composite >= ?
            AND pass3_at IS NOT NULL
            AND id NOT IN (
                SELECT id FROM images
                WHERE nima_composite IS NOT NULL
                ORDER BY nima_composite DESC
                LIMIT ?
            )
            AND lr_pick != 'pick'
        """, (_NIMA_THRESHOLD_P3, _TOP_N)).fetchone()[0]
        p3_remaining = max(0, p3_total - p3_complete)

        # Priority 4 — everything else needing pass3
        p4_total = conn.execute("""
            SELECT COUNT(*) FROM images
            WHERE pass2_at IS NOT NULL
            AND (nima_composite IS NULL OR nima_composite < ?)
            AND (lr_pick IS NULL OR lr_pick != 'pick')
            AND id NOT IN (
                SELECT id FROM images
                WHERE nima_composite IS NOT NULL
                ORDER BY nima_composite DESC
                LIMIT ?
            )
        """, (_NIMA_THRESHOLD_P3, _TOP_N)).fetchone()[0]
        p4_complete = conn.execute("""
            SELECT COUNT(*) FROM images
            WHERE pass2_at IS NOT NULL
            AND pass3_at IS NOT NULL
            AND (nima_composite IS NULL OR nima_composite < ?)
            AND (lr_pick IS NULL OR lr_pick != 'pick')
            AND id NOT IN (
                SELECT id FROM images
                WHERE nima_composite IS NOT NULL
                ORDER BY nima_composite DESC
                LIMIT ?
            )
        """, (_NIMA_THRESHOLD_P3, _TOP_N)).fetchone()[0]
        p4_remaining = max(0, p4_total - p4_complete)

    return {
        "priority_1": {"total": p1_total, "remaining": p1_remaining, "complete": p1_complete},
        "priority_2": {"total": p2_total, "remaining": p2_remaining, "complete": p2_complete},
        "priority_3": {"total": p3_total, "remaining": p3_remaining, "complete": p3_complete},
        "priority_4": {"total": p4_total, "remaining": p4_remaining, "complete": p4_complete},
    }


def get_next_batch(mode: ProcessingMode, batch_size: int = 50) -> list[str]:
    """
    Return the next batch of image paths to process based on the current mode.

    PAUSE      → []
    THROTTLED  → Priority 1 and 2 only
    FULL       → All tiers in order (exhaust priority 1 first, then 2, etc.)

    Within each tier, ordered by nima_composite DESC.
    """
    if mode == ProcessingMode.PAUSE:
        return []

    paths: list[str] = []

    with get_db() as conn:
        def _fetch_tier(sql: str, params: tuple = ()) -> list[str]:
            rows = conn.execute(sql, params).fetchall()
            return [r["file_path"] for r in rows if r["file_path"]]

        # Priority 1 — top 500 by NIMA, not yet pass3
        p1_sql = """
            SELECT file_path FROM images
            WHERE id IN (
                SELECT id FROM images
                WHERE nima_composite IS NOT NULL
                ORDER BY nima_composite DESC
                LIMIT ?
            )
            AND pass3_at IS NULL
            AND pass2_at IS NOT NULL
            AND file_path NOT IN (
                SELECT i.file_path FROM pipeline_jobs j
                JOIN images i ON j.image_id = i.id
                WHERE j.job_type = 'pass3' AND j.status IN ('queued','running')
            )
            ORDER BY nima_composite DESC
            LIMIT ?
        """
        p1_paths = _fetch_tier(p1_sql, (_TOP_N, batch_size))
        paths.extend(p1_paths)

        remaining = batch_size - len(paths)
        if remaining <= 0:
            return paths

        # Priority 2 — lr_pick = 'pick', not yet pass3
        p2_sql = """
            SELECT file_path FROM images
            WHERE lr_pick = 'pick'
            AND pass3_at IS NULL
            AND pass2_at IS NOT NULL
            AND file_path NOT IN (
                SELECT i.file_path FROM pipeline_jobs j
                JOIN images i ON j.image_id = i.id
                WHERE j.job_type = 'pass3' AND j.status IN ('queued','running')
            )
            ORDER BY nima_composite DESC NULLS LAST
            LIMIT ?
        """
        p2_paths = _fetch_tier(p2_sql, (remaining,))
        paths.extend(p2_paths)

        # If THROTTLED, stop here
        if mode == ProcessingMode.THROTTLED:
            return paths

        remaining = batch_size - len(paths)
        if remaining <= 0:
            return paths

        # Priority 3 — nima >= threshold, not top-500, not lr_pick
        p3_sql = """
            SELECT file_path FROM images
            WHERE nima_composite >= ?
            AND pass2_at IS NOT NULL
            AND pass3_at IS NULL
            AND id NOT IN (
                SELECT id FROM images
                WHERE nima_composite IS NOT NULL
                ORDER BY nima_composite DESC
                LIMIT ?
            )
            AND (lr_pick IS NULL OR lr_pick != 'pick')
            AND file_path NOT IN (
                SELECT i.file_path FROM pipeline_jobs j
                JOIN images i ON j.image_id = i.id
                WHERE j.job_type = 'pass3' AND j.status IN ('queued','running')
            )
            ORDER BY nima_composite DESC
            LIMIT ?
        """
        p3_paths = _fetch_tier(p3_sql, (_NIMA_THRESHOLD_P3, _TOP_N, remaining))
        paths.extend(p3_paths)

        remaining = batch_size - len(paths)
        if remaining <= 0:
            return paths

        # Priority 4 — everything else
        p4_sql = """
            SELECT file_path FROM images
            WHERE pass2_at IS NOT NULL
            AND pass3_at IS NULL
            AND (nima_composite IS NULL OR nima_composite < ?)
            AND (lr_pick IS NULL OR lr_pick != 'pick')
            AND id NOT IN (
                SELECT id FROM images
                WHERE nima_composite IS NOT NULL
                ORDER BY nima_composite DESC
                LIMIT ?
            )
            AND file_path NOT IN (
                SELECT i.file_path FROM pipeline_jobs j
                JOIN images i ON j.image_id = i.id
                WHERE j.job_type = 'pass3' AND j.status IN ('queued','running')
            )
            ORDER BY nima_composite DESC NULLS LAST
            LIMIT ?
        """
        p4_paths = _fetch_tier(p4_sql, (_NIMA_THRESHOLD_P3, _TOP_N, remaining))
        paths.extend(p4_paths)

    return paths


def seed_priority_queue() -> dict:
    """
    Ensure pipeline_jobs exist for Priority 1 (top 500) and Priority 2 (lr_pick) images.
    Creates pass3 jobs at priority=10 for top 500, priority=8 for LR picks.
    RESPECTS WATERFALL: will NOT seed pass3 if pass1 or pass2 jobs are still active.
    Returns counts of jobs seeded per tier.
    """
    seeded_p1 = 0
    seeded_p2 = 0

    with get_db() as conn:
        # Waterfall gate: do NOT seed pass3 while pass1 or pass2 are still active
        p1_active = conn.execute(
            "SELECT COUNT(*) FROM pipeline_jobs WHERE job_type='pass1' AND status IN ('queued','running')"
        ).fetchone()[0]
        p2_active = conn.execute(
            "SELECT COUNT(*) FROM pipeline_jobs WHERE job_type='pass2' AND status IN ('queued','running')"
        ).fetchone()[0]
        if p1_active > 0 or p2_active > 0:
            return {
                "priority_1_seeded": 0,
                "priority_2_seeded": 0,
                "total_seeded": 0,
                "blocked_by": f"pass1={p1_active} pass2={p2_active} still active — waterfall enforced",
            }

        # Priority 1 — top 500 by nima_composite (must be >= 6.0 to be worth GPU time)
        p1_rows = conn.execute("""
            SELECT id, file_path FROM images
            WHERE nima_composite IS NOT NULL
            AND nima_composite >= 6.0
            AND pass2_at IS NOT NULL
            AND pass3_at IS NULL
            AND id NOT IN (
                SELECT image_id FROM pipeline_jobs
                WHERE job_type = 'pass3'
                AND status IN ('queued','running','complete')
                AND image_id IS NOT NULL
            )
            ORDER BY nima_composite DESC
            LIMIT ?
        """, (_TOP_N,)).fetchall()

        for row in p1_rows:
            conn.execute(
                """INSERT INTO pipeline_jobs (job_type, image_id, status, priority)
                   VALUES ('pass3', ?, 'queued', 10)""",
                (row["id"],),
            )
            seeded_p1 += 1

        # Priority 2 — lr_pick = 'pick' (not already in queue/complete)
        p2_rows = conn.execute("""
            SELECT id, file_path FROM images
            WHERE lr_pick = 'pick'
            AND pass2_at IS NOT NULL
            AND pass3_at IS NULL
            AND id NOT IN (
                SELECT image_id FROM pipeline_jobs
                WHERE job_type = 'pass3'
                AND status IN ('queued','running','complete')
                AND image_id IS NOT NULL
            )
            ORDER BY nima_composite DESC NULLS LAST
        """).fetchall()

        for row in p2_rows:
            conn.execute(
                """INSERT INTO pipeline_jobs (job_type, image_id, status, priority)
                   VALUES ('pass3', ?, 'queued', 8)""",
                (row["id"],),
            )
            seeded_p2 += 1

    return {
        "priority_1_seeded": seeded_p1,
        "priority_2_seeded": seeded_p2,
        "total_seeded": seeded_p1 + seeded_p2,
    }


def get_queue_summary() -> dict:
    """
    Full summary: per-tier counts, total remaining, estimated hours at baseline rate.
    """
    tiers = build_priority_queue()
    total_remaining = sum(t["remaining"] for t in tiers.values())
    estimated_hours = round(total_remaining / _BASELINE_RATE, 2)

    return {
        "tiers": tiers,
        "total_remaining": total_remaining,
        "baseline_rate_per_hour": _BASELINE_RATE,
        "estimated_completion_hours": estimated_hours,
    }
