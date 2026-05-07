"""
services/pipeline_diagnose.py

"Why isn't this image in pass3 yet?" — single source of truth that walks the
pipeline state for one image and reports, in plain English, exactly what stage
it's at and what's blocking advancement.

Used by:
- GET /pipeline/why/{image_id} (REST diagnostic for the dashboard)
- The Priority tab to surface mode warnings + waterfall blocks
- Future: tooltips on the image preview modal

Design principles:
- Read-only. Never mutates state. Bumping/rescuing happens elsewhere.
- Honors the strict waterfall: pass1 → pass2 → pass3, no skipping.
- Dedupe-aware: if an image already has pass3_at, it reports "complete" — the
  caller should not re-enqueue. Likewise complete-pass1/pass2 is reported so
  any priority-side bump knows to skip those stages.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.database import get_db
from core.ollama import get_mode


# Mirrors queue_manager.py constants. Kept here so the diagnostic doesn't
# import the queue manager (which has heavier dependencies).
_PRIORITY_MODE_FILE = Path("/tmp/lens_priority_mode")
_PRIORITY_THRESHOLD = 10
_AUTO_PROMOTE_NIMA_TIER1 = 6.5
_AUTO_PROMOTE_NIMA_TIER2 = 6.0


def _is_priority_mode() -> bool:
    return _PRIORITY_MODE_FILE.exists()


def _pass3_runs_in_mode(mode: str) -> bool:
    """Pass3 (vision) only runs when the LLM mode loads the vision model.
    Mode 'auto' and 'priority' load it; 'text' loads only the caption model;
    'off' loads nothing."""
    return mode in ("auto", "priority")


def _queue_position_and_eta(image_id: int) -> Optional[dict]:
    """Given an image with a queued pass3 job, return {position, ahead, eta_min}.

    Position = 1 + count of pass3 jobs strictly ahead in the dispatch order.
    Dispatch order: priority DESC, queued_at ASC.

    ETA = position / pass3 throughput per minute (computed from the last 60 min
    of completions). Returns None if no recent completions to base ETA on.
    """
    with get_db() as conn:
        my_job = conn.execute(
            """SELECT id, priority, queued_at FROM pipeline_jobs
               WHERE image_id = ? AND job_type = 'pass3' AND status = 'queued'
               ORDER BY id DESC LIMIT 1""",
            (image_id,),
        ).fetchone()
        if not my_job:
            return None

        ahead = conn.execute(
            """SELECT COUNT(*) FROM pipeline_jobs
               WHERE job_type = 'pass3' AND status = 'queued'
                 AND (priority > ?
                      OR (priority = ? AND queued_at < ?))""",
            (my_job["priority"], my_job["priority"], my_job["queued_at"]),
        ).fetchone()[0]

        # Throughput: pass3 completions in the last 60 minutes.
        thr_row = conn.execute(
            """SELECT COUNT(*) FROM pipeline_jobs
               WHERE job_type = 'pass3' AND status = 'complete'
                 AND completed_at >= datetime('now', '-60 minutes')"""
        ).fetchone()
        thr_per_hr = thr_row[0] if thr_row else 0

    position = ahead + 1
    eta_min: Optional[float] = None
    if thr_per_hr > 0:
        # convert per-hour to per-minute, then divide
        eta_min = position / (thr_per_hr / 60.0)
    return {
        "position": position,
        "ahead": ahead,
        "throughput_last_hour": thr_per_hr,
        "eta_minutes": round(eta_min, 1) if eta_min else None,
    }


def _waterfall_active() -> dict:
    """How many pass1 / pass2 jobs are queued or running. Pass3 promotion AND
    pass3 dispatch are both gated until both queues are empty (per
    queue_manager._auto_promote and the loop's sequential waterfall)."""
    with get_db() as conn:
        p1 = conn.execute(
            "SELECT COUNT(*) FROM pipeline_jobs WHERE job_type='pass1' AND status IN ('queued','running')"
        ).fetchone()[0]
        p2 = conn.execute(
            "SELECT COUNT(*) FROM pipeline_jobs WHERE job_type='pass2' AND status IN ('queued','running')"
        ).fetchone()[0]
    return {
        "pass1_active": p1,
        "pass2_active": p2,
        "blocked": p1 > 0 or p2 > 0,
    }


def _job_for(image_id: int, job_type: str) -> Optional[dict]:
    """Latest pipeline_jobs row for this image+type, or None."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT id, status, priority, attempts, error, queued_at,
                      started_at, completed_at
               FROM pipeline_jobs
               WHERE image_id = ? AND job_type = ?
               ORDER BY id DESC LIMIT 1""",
            (image_id, job_type),
        ).fetchone()
    return dict(row) if row else None


def why_blocked(image_id: int) -> dict:
    """Return a structured diagnostic for one image.

    Shape:
      {
        "image_id": int,
        "stage": "complete" | "pass1_pending" | "pass1_failed" | "raw_review"
                 | "pass2_pending" | "below_threshold" | "pass3_pending"
                 | "pass3_complete" | "missing",
        "blockers": [str, ...],   # plain-English reasons
        "actions": [str, ...],    # what the user can do
        "facts": {...},           # raw data (timestamps, scores, jobs)
        "summary": "one-line plain English"
      }
    """
    with get_db() as conn:
        img = conn.execute(
            """SELECT id, file_path, file_name,
                      pass1_status, pass1_at, pass2_at, pass3_at, pass3_model,
                      nima_aesthetic, nima_technical, nima_composite,
                      content_ready, portfolio_worthy
               FROM images WHERE id = ?""",
            (image_id,),
        ).fetchone()
    if not img:
        return {
            "image_id": image_id,
            "stage": "missing",
            "blockers": ["Image not found in database."],
            "actions": [],
            "facts": {},
            "summary": f"Image {image_id} is not in the database.",
        }

    img = dict(img)
    mode = get_mode()
    priority_mode = _is_priority_mode()
    waterfall = _waterfall_active()
    p1_job = _job_for(image_id, "pass1")
    p2_job = _job_for(image_id, "pass2")
    p3_job = _job_for(image_id, "pass3")

    facts = {
        "image": {
            "file_name": img["file_name"],
            "pass1_status": img["pass1_status"],
            "pass1_at": img["pass1_at"],
            "pass2_at": img["pass2_at"],
            "pass3_at": img["pass3_at"],
            "pass3_model": img["pass3_model"],
            "nima_composite": img["nima_composite"],
        },
        "mode": mode,
        "priority_mode": priority_mode,
        "waterfall": waterfall,
        "pass1_job": p1_job,
        "pass2_job": p2_job,
        "pass3_job": p3_job,
    }

    # ── Stage 0: pass3 already done ─────────────────────────────────────────
    if img["pass3_at"]:
        return {
            "image_id": image_id,
            "stage": "complete",
            "blockers": [],
            "actions": ["retag (only if you want to re-run pass3)"],
            "facts": facts,
            "summary": (
                f"Done. Pass3 ran at {img['pass3_at']} via "
                f"{img['pass3_model'] or 'unknown model'}. No further work needed."
            ),
        }

    # ── Stage 1: pass1 ──────────────────────────────────────────────────────
    if not img["pass1_at"]:
        if p1_job and p1_job["status"] == "queued":
            return {
                "image_id": image_id,
                "stage": "pass1_pending",
                "blockers": [f"Pass1 queued at priority {p1_job['priority']}, waiting to run."],
                "actions": ["bump"],
                "facts": facts,
                "summary": f"Pass1 queued (priority {p1_job['priority']}). Bump to priority 10 to jump the line.",
            }
        if p1_job and p1_job["status"] == "running":
            return {
                "image_id": image_id,
                "stage": "pass1_pending",
                "blockers": ["Pass1 is currently running."],
                "actions": [],
                "facts": facts,
                "summary": "Pass1 in progress.",
            }
        if p1_job and p1_job["status"] == "error":
            return {
                "image_id": image_id,
                "stage": "pass1_failed",
                "blockers": [
                    f"Pass1 errored after {p1_job['attempts']} attempts: "
                    f"{p1_job.get('error') or 'no error message'}"
                ],
                "actions": ["re-enqueue", "investigate file"],
                "facts": facts,
                "summary": (
                    "Pass1 failed terminally. Image needs investigation or re-enqueue. "
                    f"Error: {p1_job.get('error') or 'unknown'}"
                ),
            }
        # No pass1 job and not run — never enqueued
        return {
            "image_id": image_id,
            "stage": "pass1_pending",
            "blockers": ["No pass1 job has been enqueued for this image."],
            "actions": ["enqueue or rescan its folder"],
            "facts": facts,
            "summary": "Image is registered but never queued for pass1. Scan the folder or enqueue manually.",
        }

    if img["pass1_status"] == "fail":
        return {
            "image_id": image_id,
            "stage": "pass1_failed",
            "blockers": ["Image was culled by pass1 (failed blur/exposure check)."],
            "actions": ["accept cull", "force pass2 manually if you disagree"],
            "facts": facts,
            "summary": "Culled at pass1 — blur/exposure score too low. Pipeline considers it not worth scoring further.",
        }

    if img["pass1_status"] == "raw_review":
        return {
            "image_id": image_id,
            "stage": "raw_review",
            "blockers": ["Pass1 flagged image for raw_review (LLM salvage)."],
            "actions": ["salvage"],
            "facts": facts,
            "summary": "Flagged for RAW review — click Salvage to run the LLM second-look.",
        }

    # ── Stage 2: pass2 ──────────────────────────────────────────────────────
    if not img["pass2_at"]:
        if p2_job and p2_job["status"] == "queued":
            blockers = [f"Pass2 queued at priority {p2_job['priority']}."]
            if waterfall["pass1_active"] > 0:
                blockers.append(
                    f"Waterfall block: {waterfall['pass1_active']} pass1 jobs still active. "
                    "Pass2 cannot dispatch until pass1 fully drains."
                )
            return {
                "image_id": image_id,
                "stage": "pass2_pending",
                "blockers": blockers,
                "actions": ["bump"],
                "facts": facts,
                "summary": f"Pass2 queued (priority {p2_job['priority']}). " + blockers[-1],
            }
        if p2_job and p2_job["status"] == "running":
            return {
                "image_id": image_id, "stage": "pass2_pending",
                "blockers": ["Pass2 is currently running."], "actions": [],
                "facts": facts, "summary": "Pass2 in progress.",
            }
        if p2_job and p2_job["status"] == "error":
            return {
                "image_id": image_id, "stage": "pass2_pending",
                "blockers": [
                    f"Pass2 errored after {p2_job['attempts']} attempts: "
                    f"{p2_job.get('error') or 'no error message'}"
                ],
                "actions": ["re-enqueue", "investigate"],
                "facts": facts,
                "summary": "Pass2 failed terminally — re-enqueue to retry.",
            }
        return {
            "image_id": image_id, "stage": "pass2_pending",
            "blockers": ["Pass1 done but no pass2 job exists yet."],
            "actions": ["bump (creates pass2 job at priority 10)"],
            "facts": facts,
            "summary": "Pass1 finished but pass2 not yet queued — bump to force.",
        }

    # ── Stage 3: pass3 ──────────────────────────────────────────────────────
    nima = img["nima_composite"]
    blockers: list[str] = []
    actions: list[str] = []

    # Mode-level block (most common, easy to miss)
    if not _pass3_runs_in_mode(mode):
        blockers.append(
            f"Pass3 is paused — current mode is `{mode}` (only `auto` or `priority` "
            "loads the vision model). Switch to auto mode to drain the queue."
        )
        actions.append(f"switch mode {mode} → auto")

    # Waterfall block (shared with pass2_pending logic)
    if waterfall["blocked"]:
        blockers.append(
            f"Waterfall block: pass1={waterfall['pass1_active']}, "
            f"pass2={waterfall['pass2_active']}. Pass3 cannot dispatch until both drain."
        )

    if p3_job and p3_job["status"] == "queued":
        pos = _queue_position_and_eta(image_id)
        eta_str = ""
        if pos:
            if pos["eta_minutes"] is not None:
                hrs = pos["eta_minutes"] / 60
                eta_str = (
                    f" Position #{pos['position']} of pass3 queue at priority {p3_job['priority']}; "
                    f"~{hrs:.1f}h at current throughput ({pos['throughput_last_hour']}/hr)."
                )
            else:
                eta_str = (
                    f" Position #{pos['position']} of pass3 queue at priority {p3_job['priority']}; "
                    "no recent completions to estimate ETA."
                )
        blockers.insert(0, f"Pass3 queued at priority {p3_job['priority']}.")
        return {
            "image_id": image_id,
            "stage": "pass3_pending",
            "blockers": blockers,
            "actions": actions + ["bump (sets pass3 priority to 10)"],
            "facts": {**facts, "pass3_queue": pos},
            "summary": f"Pass3 queued.{eta_str}",
        }

    if p3_job and p3_job["status"] == "running":
        return {
            "image_id": image_id, "stage": "pass3_pending",
            "blockers": ["Pass3 is currently running on this image."],
            "actions": [], "facts": facts,
            "summary": "Pass3 in progress.",
        }

    if p3_job and p3_job["status"] == "error":
        return {
            "image_id": image_id, "stage": "pass3_pending",
            "blockers": [
                f"Pass3 errored after {p3_job['attempts']} attempts: "
                f"{p3_job.get('error') or 'no error'}"
            ],
            "actions": ["re-enqueue at priority 10", "investigate"],
            "facts": facts,
            "summary": "Pass3 failed — re-enqueue or investigate.",
        }

    # No pass3 job at all — promotion gate
    if nima is None:
        return {
            "image_id": image_id, "stage": "pass3_pending",
            "blockers": ["NIMA score is null. Was pass2 truly completed?"],
            "actions": ["re-run pass2"], "facts": facts,
            "summary": "Pass2 marked done but NIMA is null — data inconsistency.",
        }

    if nima < _AUTO_PROMOTE_NIMA_TIER2:
        return {
            "image_id": image_id, "stage": "below_threshold",
            "blockers": [
                f"NIMA composite {nima:.2f} is below the auto-promote threshold "
                f"({_AUTO_PROMOTE_NIMA_TIER2}). The pipeline never promotes images below this."
            ],
            "actions": ["bump (force pass3 at priority 10, bypasses NIMA threshold)"],
            "facts": facts,
            "summary": (
                f"Below auto-promote threshold (NIMA {nima:.2f} < {_AUTO_PROMOTE_NIMA_TIER2}). "
                "Use Process Now to run pass3 anyway."
            ),
        }

    # NIMA is in promote-able range but no job exists → waterfall is gating it
    if waterfall["blocked"]:
        return {
            "image_id": image_id, "stage": "pass3_pending",
            "blockers": [
                f"NIMA {nima:.2f} qualifies for auto-promote but waterfall is blocked "
                f"(pass1={waterfall['pass1_active']}, pass2={waterfall['pass2_active']}). "
                "Auto-promote will fire when both queues are empty."
            ],
            "actions": ["bump (skip the auto-promote wait)", "wait for waterfall"],
            "facts": facts,
            "summary": "Will auto-promote once pass1+pass2 finish; bump to skip the wait.",
        }

    return {
        "image_id": image_id, "stage": "pass3_pending",
        "blockers": [
            "Eligible for auto-promote but no pass3 job has been created yet. "
            "The next queue manager loop will pick it up."
        ],
        "actions": ["bump (force immediately)", "wait one loop"],
        "facts": facts,
        "summary": (
            f"Eligible (NIMA {nima:.2f}) — auto-promote should run within "
            "the next queue loop iteration."
        ),
    }
