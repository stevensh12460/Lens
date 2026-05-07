"""
services/priority_ops.py

Bump / rescue / promote operations that respect:
  • Strict waterfall: pass1 → pass2 → pass3, never skipped.
  • Cross-system dedup: an image already past a stage (pass*_at IS NOT NULL)
    is never re-enqueued for that stage — both regular and priority paths
    look at the same images table, so there's no double-processing.

Public functions:
  bump_image(image_id)            — bump the image's *current* stage to priority 10
  bump_folder(folder, override_nima=False) — bump every image in a folder
  promote_tier(min_nima, max_nima, priority, limit) — bulk pass3 promotion at given priority

All operations are idempotent. Calling bump_image() twice in a row on the
same image is a no-op the second time.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from core.database import get_db


# Stage detection: which pass does this image need NEXT?
def _next_stage(img: dict) -> str:
    """Return the next pipeline stage this image is waiting for, or 'complete'.

    Honors the waterfall — we never enqueue pass3 for an image that hasn't
    finished pass2, etc. Cross-system dedup-safe because we check the
    pass*_at columns (the source of truth) not the pipeline_jobs table.
    """
    if img.get("pass3_at"):
        return "complete"
    if not img.get("pass1_at"):
        return "pass1"
    if img.get("pass1_status") == "fail":
        return "culled"
    if img.get("pass1_status") == "raw_review":
        return "raw_review"
    if not img.get("pass2_at"):
        return "pass2"
    return "pass3"


def _existing_job(conn, image_id: int, job_type: str) -> Optional[dict]:
    """Latest job for this image+type, regardless of status."""
    row = conn.execute(
        """SELECT id, status, priority, attempts, queued_at
           FROM pipeline_jobs
           WHERE image_id = ? AND job_type = ?
           ORDER BY id DESC LIMIT 1""",
        (image_id, job_type),
    ).fetchone()
    return dict(row) if row else None


def _bump_or_create_job(
    conn, image_id: int, job_type: str, priority: int = 10
) -> dict:
    """If a queued/running/error job already exists for (image, job_type),
    update its priority. Otherwise insert a new one at the requested priority.

    Returns {action: 'bumped'|'created'|'noop'|'requeued', job_id, priority}.

    Skip-if-complete: if the image is past this stage (pass*_at set), the
    caller should not be calling us — we still no-op rather than insert a
    duplicate.
    """
    img_row = conn.execute(
        f"SELECT {job_type}_at FROM images WHERE id = ?", (image_id,)
    ).fetchone()
    # only pass1/pass2/pass3 columns end in _at; sanity check
    if img_row and img_row[0]:
        # Stage already complete — never enqueue
        return {"action": "noop", "reason": f"{job_type} already complete", "job_id": None, "priority": None}

    job = _existing_job(conn, image_id, job_type)
    if job and job["status"] in ("queued", "running"):
        if job["priority"] >= priority:
            return {"action": "noop", "reason": "already at >= requested priority",
                    "job_id": job["id"], "priority": job["priority"]}
        conn.execute(
            "UPDATE pipeline_jobs SET priority = ? WHERE id = ?",
            (priority, job["id"]),
        )
        return {"action": "bumped", "job_id": job["id"], "priority": priority}

    if job and job["status"] == "error":
        # Reset and bump: clear error state, reset attempts, set priority.
        # The worker will re-attempt on next dispatch.
        conn.execute(
            """UPDATE pipeline_jobs
               SET status='queued', priority=?, attempts=0, error=NULL,
                   queued_at=CURRENT_TIMESTAMP, started_at=NULL,
                   completed_at=NULL, heartbeat_at=NULL
               WHERE id = ?""",
            (priority, job["id"]),
        )
        return {"action": "requeued", "job_id": job["id"], "priority": priority}

    if job and job["status"] == "complete":
        # Job marked complete but pass*_at not set — data inconsistency, but
        # the caller probably wants progress. Insert a fresh job.
        cursor = conn.execute(
            """INSERT INTO pipeline_jobs (job_type, image_id, status, priority)
               VALUES (?, ?, 'queued', ?)""",
            (job_type, image_id, priority),
        )
        return {"action": "created", "job_id": cursor.lastrowid, "priority": priority,
                "note": "previous job was 'complete' but pass*_at not set — created fresh job"}

    # No existing job — create one
    cursor = conn.execute(
        """INSERT INTO pipeline_jobs (job_type, image_id, status, priority)
           VALUES (?, ?, 'queued', ?)""",
        (job_type, image_id, priority),
    )
    return {"action": "created", "job_id": cursor.lastrowid, "priority": priority}


def bump_image(image_id: int, priority: int = 10) -> dict:
    """Bump a single image to the requested priority.

    Detects the image's current stage and bumps that stage's job. Does not
    skip stages — if image needs pass2, we bump pass2 (not pass3). When
    pass2 finishes, the auto-promoter will create the pass3 job at the
    inherited priority chain.

    Returns:
      {image_id, stage, action, message, ...op-specific fields}
    """
    with get_db() as conn:
        img_row = conn.execute(
            """SELECT id, file_name, pass1_at, pass1_status, pass2_at, pass3_at,
                      pass3_model, nima_composite
               FROM images WHERE id = ?""",
            (image_id,),
        ).fetchone()
    if not img_row:
        return {"image_id": image_id, "ok": False, "error": "image not found"}
    img = dict(img_row)

    stage = _next_stage(img)

    if stage == "complete":
        return {
            "image_id": image_id, "ok": True, "stage": "complete",
            "action": "noop",
            "message": (f"Already complete via {img.get('pass3_model') or 'pipeline'} "
                        f"at {img.get('pass3_at')}. No bump needed."),
        }

    if stage == "culled":
        return {
            "image_id": image_id, "ok": False, "stage": "culled",
            "action": "blocked",
            "message": ("Image was culled at pass1 (failed blur/exposure). "
                        "Bump refused — would override the cull. Use force_pass2 "
                        "if you really want to override."),
        }

    if stage == "raw_review":
        # Don't bump pass1_raw silently — caller should explicitly call salvage
        return {
            "image_id": image_id, "ok": False, "stage": "raw_review",
            "action": "blocked",
            "message": "Image flagged for raw_review. Use the Salvage button instead.",
        }

    with get_db() as conn:
        result = _bump_or_create_job(conn, image_id, stage, priority=priority)

    return {
        "image_id": image_id, "ok": True, "stage": stage,
        "action": result["action"],
        "job_id": result.get("job_id"),
        "priority": result.get("priority"),
        "message": (
            f"{result['action'].title()} {stage} job for image {image_id} "
            f"at priority {priority}. Strict waterfall: it will run when its "
            f"upstream queue ({'pass1' if stage == 'pass2' else 'pass1+pass2' if stage == 'pass3' else 'none'}) is empty."
        ),
    }


def bump_folder(folder: str, priority: int = 10, override_nima: bool = False) -> dict:
    """Bump every image whose file_path is under `folder`.

    Each image is routed to its own stage (waterfall preserved). Already-
    complete images at any stage are skipped (no duplicate work).

    `override_nima=True` will, for images currently complete-through-pass2,
    create a pass3 job even if NIMA is below the auto-promote threshold —
    this is the only way to force pass3 on sub-6.0 NIMA images in bulk.
    """
    folder_path = str(Path(folder).resolve())
    summary = {
        "folder": folder_path,
        "scanned": 0,
        "bumped_pass1": 0, "bumped_pass2": 0, "bumped_pass3": 0,
        "created_pass3_below_threshold": 0,
        "already_complete": 0,
        "culled": 0, "raw_review": 0,
        "errors": [],
    }

    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, file_name, pass1_at, pass1_status, pass2_at, pass3_at,
                      nima_composite
               FROM images WHERE file_path LIKE ?""",
            (folder_path.rstrip("/") + "/%",),
        ).fetchall()

        summary["scanned"] = len(rows)

        for r in rows:
            img = dict(r)
            stage = _next_stage(img)
            if stage == "complete":
                summary["already_complete"] += 1
                continue
            if stage == "culled":
                summary["culled"] += 1
                continue
            if stage == "raw_review":
                summary["raw_review"] += 1
                continue

            try:
                if stage == "pass3" and override_nima and (img.get("nima_composite") or 0) < 6.0:
                    # Force pass3 below NIMA threshold
                    result = _bump_or_create_job(conn, img["id"], "pass3", priority=priority)
                    if result["action"] in ("created", "bumped", "requeued"):
                        summary["created_pass3_below_threshold"] += 1
                    continue

                result = _bump_or_create_job(conn, img["id"], stage, priority=priority)
                if result["action"] in ("created", "bumped", "requeued"):
                    summary[f"bumped_{stage}"] += 1
            except Exception as e:
                summary["errors"].append({"image_id": img["id"], "error": str(e)})

    return summary


def promote_tier(
    min_nima: float = 5.0,
    max_nima: float = 6.0,
    priority: int = 10,
    limit: int = 5000,
) -> dict:
    """Bulk-create pass3 jobs for images in a NIMA range that are pass2-complete
    but not pass3-complete and don't already have a pass3 job.

    This is the explicit override for the auto-promoter's hardcoded 6.0
    threshold. Strict waterfall still applies — if pass1/pass2 are still
    draining, the new pass3 jobs will sit at the requested priority and
    dispatch only after upstream is clear.
    """
    with get_db() as conn:
        rows = conn.execute(
            """SELECT i.id FROM images i
               WHERE i.pass2_at IS NOT NULL
                 AND i.pass3_at IS NULL
                 AND i.nima_composite >= ?
                 AND i.nima_composite < ?
                 AND NOT EXISTS (
                     SELECT 1 FROM pipeline_jobs j
                     WHERE j.image_id = i.id
                       AND j.job_type = 'pass3'
                       AND j.status IN ('queued', 'running')
                 )
               ORDER BY i.nima_composite DESC
               LIMIT ?""",
            (min_nima, max_nima, limit),
        ).fetchall()

        ids = [r["id"] for r in rows]
        if not ids:
            return {"promoted": 0, "image_ids": [], "min_nima": min_nima,
                    "max_nima": max_nima, "priority": priority}

        # Bulk insert
        conn.executemany(
            """INSERT INTO pipeline_jobs (job_type, image_id, status, priority)
               VALUES ('pass3', ?, 'queued', ?)""",
            [(img_id, priority) for img_id in ids],
        )

    return {
        "promoted": len(ids),
        "image_ids": ids[:50],  # truncate for response size
        "total_promoted": len(ids),
        "min_nima": min_nima,
        "max_nima": max_nima,
        "priority": priority,
        "note": "Pass3 jobs created. Will dispatch when waterfall (pass1+pass2) is clear AND mode is auto/priority.",
    }
