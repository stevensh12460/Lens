import os
import signal
import subprocess
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import Optional

from core.database import get_db
from pipeline.queue_manager import enqueue

router = APIRouter()

_PIPELINE_PID_FILE = Path("/tmp/lens_pipeline.pid")
_PIPELINE_LOG = Path("/tmp/lens_pipeline.log")
_VENV_PYTHON = Path("/Users/stevenhoward/lens/venv/bin/python3")
_LENS_DIR = Path("/Users/stevenhoward/lens")


def _get_pipeline_pid() -> Optional[int]:
    if not _PIPELINE_PID_FILE.exists():
        return None
    try:
        pid = int(_PIPELINE_PID_FILE.read_text().strip())
        os.kill(pid, 0)  # check if alive
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        _PIPELINE_PID_FILE.unlink(missing_ok=True)
        return None


@router.get("/process/status")
def pipeline_process_status():
    pid = _get_pipeline_pid()
    return {"running": pid is not None, "pid": pid}


@router.post("/process/start")
def pipeline_process_start():
    if _get_pipeline_pid():
        return {"status": "already_running"}
    log_fh = open(_PIPELINE_LOG, "a")
    proc = subprocess.Popen(
        [str(_VENV_PYTHON), "-c",
         "import asyncio; from pipeline.queue_manager import run_full_pipeline_loop; asyncio.run(run_full_pipeline_loop())"],
        cwd=str(_LENS_DIR),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_fh.close()
    _PIPELINE_PID_FILE.write_text(str(proc.pid))
    return {"status": "started", "pid": proc.pid}


@router.post("/process/stop")
def pipeline_process_stop():
    pid = _get_pipeline_pid()
    if not pid:
        return {"status": "not_running"}
    try:
        os.kill(pid, signal.SIGTERM)
        _PIPELINE_PID_FILE.unlink(missing_ok=True)
        return {"status": "stopped", "pid": pid}
    except ProcessLookupError:
        _PIPELINE_PID_FILE.unlink(missing_ok=True)
        return {"status": "already_gone"}


# ---------------------------------------------------------------------------
# Pause mode — idle the pipeline without tearing down the service
# ---------------------------------------------------------------------------

_PAUSED_FLAG = Path("/tmp/lens_paused")


@router.get("/pause/status")
def pause_status():
    """Return whether the pipeline is currently paused."""
    return {"paused": _PAUSED_FLAG.exists()}


@router.post("/pause")
def pause_pipeline():
    """Pause the pipeline — main loop idles, no new work fetched.
    In-flight batches finish gracefully; no pass0/1/2/3/promote/social runs."""
    _PAUSED_FLAG.touch()
    return {"paused": True, "message": "Pipeline paused. In-flight work will finish, then the loop will idle."}


@router.post("/resume")
def resume_pipeline():
    """Resume the pipeline — main loop returns to normal operation."""
    _PAUSED_FLAG.unlink(missing_ok=True)
    return {"paused": False, "message": "Pipeline resumed."}


@router.get("/llm/current")
def llm_current_job():
    """Returns the currently running LLM job — file, pass type, started_at, and median rate."""
    import statistics
    with get_db() as conn:
        row = conn.execute("""
            SELECT j.job_type, j.started_at, i.file_path
            FROM pipeline_jobs j JOIN images i ON j.image_id = i.id
            WHERE j.status = 'running' AND j.job_type IN ('pass1_raw', 'pass3')
            ORDER BY j.started_at DESC LIMIT 1
        """).fetchone()
        if not row:
            return {"active": False}
        rate_rows = conn.execute("""
            SELECT (julianday(completed_at) - julianday(started_at)) * 86400 as secs
            FROM pipeline_jobs
            WHERE job_type = ? AND status = 'complete'
            AND started_at IS NOT NULL AND completed_at IS NOT NULL
            ORDER BY completed_at DESC LIMIT 20
        """, (row["job_type"],)).fetchall()
        times = [r[0] for r in rate_rows if r[0] and r[0] > 0]
        rate = statistics.median(times) if times else None
    return {
        "active": True,
        "job_type": row["job_type"],
        "file_name": row["file_path"].split("/")[-1],
        "started_at": row["started_at"],
        "rate_seconds": round(rate, 1) if rate else None,
    }


@router.post("/llm/unload")
def llm_unload():
    """Force-unload all Ollama models by restarting the Ollama service."""
    import subprocess
    try:
        uid = os.getuid()
        result = subprocess.run(
            ["launchctl", "kickstart", "-k", f"gui/{uid}/com.lens.ollama"],
            capture_output=True, text=True, timeout=15
        )
        return {"status": "restarted", "detail": "Ollama restarted — all models unloaded"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

_SUPPORTED = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".cr2", ".cr3", ".nef", ".arw", ".raf", ".dng", ".orf", ".rw2", ".pef"}

# Path fragments that indicate non-photo junk (app caches, system libraries, backups, etc.)
# If any of these appears anywhere in the path, the file is skipped during scan.
_JUNK_PATH_FRAGMENTS = (
    "/.Trash",
    "/.Spotlight-",
    "/.fseventsd",
    "/.DocumentRevisions-",
    "/.TemporaryItems",
    "/.DS_Store",
    "/Library/Caches",
    "/Library/Application Support",
    "/Library/Containers",
    "/Library/Group Containers",
    "/Library/Preferences",
    "/Library/Thumbnails",
    "/Library/CloudStorage",
    "/Library/Mobile Documents",
    "/System/",
    "/private/",
    "/Applications/",
    "/artwork.noindex",           # macOS app art caches
    "/Ch Data/",                   # animator app data
    "/node_modules/",
    "/.git/",
    "/.cache/",
    "/cache/",
    "/thumbs/",
    "/Thumbs/",
    "/Derivatives/",               # Finder/Photos derivatives
    "/previews.lrdata/",           # Lightroom preview caches
    "/Smart Previews.lrdata/",
    ".photoslibrary/",             # Apple Photos library internals
    ".aplibrary/",                 # iPhoto library internals
    "/Backups.backupdb/",          # Time Machine
    "/.TemporaryItems/",
)

# Minimum file size for a file to be considered a real photo (bytes)
# Real JPG/PNG photos from a camera are almost always > 200KB.
_MIN_PHOTO_SIZE = 200 * 1024  # 200KB

def _is_junk_path(path: Path) -> bool:
    """True if the path looks like an app cache, system file, or non-photo junk."""
    s = str(path)
    return any(frag in s for frag in _JUNK_PATH_FRAGMENTS)

def _is_real_photo(path: Path) -> bool:
    """Filter: extension supported, not hidden, large enough, not in junk path."""
    if path.name.startswith("._") or path.name.startswith("."):
        return False
    if path.suffix.lower() not in _SUPPORTED:
        return False
    if _is_junk_path(path):
        return False
    try:
        # RAW files are always big; only small JPG/PNG are suspect
        if path.suffix.lower() in (".jpg", ".jpeg", ".png", ".tif", ".tiff"):
            if path.stat().st_size < _MIN_PHOTO_SIZE:
                return False
    except (OSError, FileNotFoundError):
        return False
    return True


class EnqueueRequest(BaseModel):
    shoot_id: Optional[int] = None
    image_path: Optional[str] = None
    job_type: str = "full_pipeline"
    priority: int = 5


class ScanRequest(BaseModel):
    path: str
    shoot_id: Optional[int] = None
    recursive: bool = True


@router.post("/enqueue")
def enqueue_job(req: EnqueueRequest):
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO pipeline_jobs (job_type, shoot_id, status, priority)
               VALUES (?, ?, 'queued', ?)""",
            (req.job_type, req.shoot_id, req.priority),
        )
        return {"job_id": cursor.lastrowid, "status": "queued"}


@router.get("/jobs")
def list_jobs(status: Optional[str] = None, limit: int = 50):
    with get_db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM pipeline_jobs WHERE status = ? ORDER BY queued_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM pipeline_jobs ORDER BY queued_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


@router.get("/queue-counts")
def queue_counts():
    """Return queued job counts per pass type for dashboard display."""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT job_type, COUNT(*) as count
            FROM pipeline_jobs WHERE status = 'queued'
            GROUP BY job_type
        """).fetchall()
    counts = {r["job_type"]: r["count"] for r in rows}
    return {
        "pass1": counts.get("pass1", 0),
        "pass1_raw": counts.get("pass1_raw", 0),
        "pass2": counts.get("pass2", 0),
        "pass3": counts.get("pass3", 0),
        "privacy": counts.get("privacy", 0),
        "total": sum(counts.values()),
    }


@router.get("/jobs/{job_id}")
def get_job(job_id: int):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM pipeline_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Job not found")
        return dict(row)


@router.post("/scan")
def scan_folder(req: ScanRequest):
    folder = Path(req.path)
    if not folder.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {req.path}")
    if not folder.is_dir():
        raise HTTPException(status_code=400, detail="Path must be a directory")

    glob = folder.rglob("*") if req.recursive else folder.glob("*")
    image_paths: list[Path] = []
    skipped_junk = 0
    skipped_tiny = 0
    skipped_hidden = 0
    for p in glob:
        try:
            if not p.is_file():
                continue
        except OSError:
            continue
        if p.name.startswith("._") or p.name.startswith("."):
            skipped_hidden += 1
            continue
        if p.suffix.lower() not in _SUPPORTED:
            continue
        if _is_junk_path(p):
            skipped_junk += 1
            continue
        # Size filter (only for JPG/PNG/TIF — RAW is always large)
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".tif", ".tiff"):
            try:
                if p.stat().st_size < _MIN_PHOTO_SIZE:
                    skipped_tiny += 1
                    continue
            except OSError:
                continue
        image_paths.append(p)

    if not image_paths:
        return {
            "registered": 0, "queued": 0,
            "skipped_junk": skipped_junk,
            "skipped_tiny": skipped_tiny,
            "skipped_hidden": skipped_hidden,
            "message": "No supported photo files found",
        }

    # Register all images in DB (ignore already-known paths)
    with get_db() as conn:
        for path in image_paths:
            conn.execute(
                "INSERT OR IGNORE INTO images (file_path, file_name, shoot_id) VALUES (?, ?, ?)",
                (str(path), path.name, req.shoot_id),
            )

    # Enqueue Pass 1 for any not yet processed AND not previously errored
    path_strs = [str(p) for p in image_paths]
    with get_db() as conn:
        # files that already have a pass1 job (any status) — skip them, don't re-queue
        already_has_job = {
            r["file_path"] for r in conn.execute(
                f"""SELECT DISTINCT i.file_path FROM pipeline_jobs j
                   JOIN images i ON i.id = j.image_id
                   WHERE j.job_type='pass1'
                   AND i.file_path IN ({','.join('?' * len(path_strs))})""",
                path_strs,
            ).fetchall()
        }
        unprocessed = conn.execute(
            f"""SELECT file_path FROM images
               WHERE pass1_status IS NULL
               AND file_path IN ({','.join('?' * len(path_strs))})""",
            path_strs,
        ).fetchall()

    to_queue = [Path(r["file_path"]) for r in unprocessed if r["file_path"] not in already_has_job]
    job_ids = enqueue("pass1", to_queue, shoot_id=req.shoot_id, priority=5) if to_queue else []

    return {
        "path": req.path,
        "found": len(image_paths),
        "registered": len(image_paths),
        "queued": len(job_ids),
        "skipped_previously_errored_or_queued": len(unprocessed) - len(to_queue),
        "skipped_junk": skipped_junk,
        "skipped_tiny": skipped_tiny,
        "skipped_hidden": skipped_hidden,
        "already_processed": len(image_paths) - len(unprocessed),
    }


# ---------------------------------------------------------------------------
# Pass 0 — Metadata extraction endpoints
# ---------------------------------------------------------------------------

class Pass0RunRequest(BaseModel):
    limit: int = 500


@router.post("/pass0/run")
def run_pass0(req: Pass0RunRequest, background_tasks: BackgroundTasks):
    """
    Trigger Pass 0 metadata extraction on unprocessed images.
    Runs in the background; returns immediately.
    """
    def _run():
        from pipeline.pass0_metadata import process_all_unprocessed
        count = process_all_unprocessed(limit=req.limit)
        import logging
        logging.getLogger("lens.pass0").info(f"API-triggered Pass 0 complete: {count} images")

    background_tasks.add_task(_run)
    return {"status": "started", "limit": req.limit, "message": "Pass 0 running in background"}


@router.get("/pass0/status")
def pass0_status():
    """Return counts of images with and without Pass 0 metadata."""
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        with_meta = conn.execute(
            "SELECT COUNT(*) FROM images WHERE captured_at IS NOT NULL"
        ).fetchone()[0]
        without_meta = total - with_meta

        # Break down by creative intent for quick insight
        intents = conn.execute(
            """SELECT creative_intent, COUNT(*) as count FROM images
               WHERE creative_intent IS NOT NULL
               GROUP BY creative_intent
               ORDER BY count DESC"""
        ).fetchall()

        seasons = conn.execute(
            """SELECT season, COUNT(*) as count FROM images
               WHERE season IS NOT NULL
               GROUP BY season
               ORDER BY count DESC"""
        ).fetchall()

    return {
        "total_images": total,
        "pass0_complete": with_meta,
        "pass0_pending": without_meta,
        "creative_intent_breakdown": [dict(r) for r in intents],
        "season_breakdown": [dict(r) for r in seasons],
    }


# ---------------------------------------------------------------------------
# Phase 11 — Idle Processing System endpoints
# ---------------------------------------------------------------------------

@router.get("/idle")
def get_idle_status():
    """Current idle time, processing mode, and worker count."""
    from pipeline.idle_monitor import get_idle_status
    return get_idle_status()


@router.get("/priority-queue")
def get_priority_queue():
    """Full priority queue summary: per-tier counts, remaining, estimated hours."""
    from pipeline.priority_queue import get_queue_summary
    return get_queue_summary()


@router.post("/priority-queue/seed")
def seed_priority_queue():
    """Seed pass3 jobs for Priority 1 (top 500 NIMA) and Priority 2 (LR picks)."""
    from pipeline.priority_queue import seed_priority_queue as _seed
    result = _seed()
    return result


@router.get("/overnight")
def get_overnight_report():
    """Latest nightly processing report (last 8 hours of pass3 activity)."""
    from pipeline.nightly_report import get_latest_report
    return get_latest_report()


@router.get("/coverage")
def get_library_coverage():
    """Library coverage percentage and pass3 completion projection."""
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        pass3_done = conn.execute(
            "SELECT COUNT(*) FROM images WHERE pass3_at IS NOT NULL"
        ).fetchone()[0]
        pass3_remaining = conn.execute(
            "SELECT COUNT(*) FROM images WHERE pass2_at IS NOT NULL AND pass3_at IS NULL"
        ).fetchone()[0]

    coverage_pct = round(pass3_done / total * 100, 2) if total > 0 else 0.0
    estimated_hours = round(pass3_remaining / 230, 2)

    return {
        "total_imported": total,
        "pass3_complete": pass3_done,
        "pass3_remaining": pass3_remaining,
        "coverage_pct": coverage_pct,
        "estimated_completion_hours": estimated_hours,
        "baseline_rate_per_hour": 230,
    }


_SUPPORTED_EXTS = _SUPPORTED  # single source of truth for supported extensions
_PRIORITY_HIGH = 10
_PRIORITY_STATE_FILE = Path("/tmp/lens_priority_state.json")
_PRIORITY_MODE_FILE = Path("/tmp/lens_priority_mode")


class PriorityRequest(BaseModel):
    path: str


# ── Priority Mode endpoints ──────────────────────────────────────────────────

@router.post("/priority/preview")
def priority_preview(req: PriorityRequest):
    """Scan a folder and return image counts before starting priority mode."""
    folder = Path(req.path)
    if not folder.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {req.path}")
    if not folder.is_dir():
        raise HTTPException(status_code=400, detail="Path must be a directory")
    all_files = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTS and not p.name.startswith("._")]
    paths_str = [str(p) for p in all_files]
    with get_db() as conn:
        if paths_str:
            placeholders = ",".join("?" * len(paths_str))
            in_db = conn.execute(
                f"SELECT COUNT(*) FROM images WHERE file_path IN ({placeholders})", paths_str
            ).fetchone()[0]
        else:
            in_db = 0
    return {"total": len(all_files), "in_db": in_db, "new": len(all_files) - in_db}


@router.post("/priority/start")
def priority_start(req: PriorityRequest):
    """Start or append to priority mode. If active, new folder's images are added to the session."""
    import json
    from datetime import datetime

    folder = Path(req.path)
    if not folder.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {req.path}")
    if not folder.is_dir():
        raise HTTPException(status_code=400, detail="Path must be a directory")

    all_files = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTS and not p.name.startswith("._")]
    if not all_files:
        raise HTTPException(status_code=400, detail="No supported image files found in folder")

    paths_str = [str(p) for p in all_files]

    # Register any new images in the DB
    with get_db() as conn:
        for p in all_files:
            conn.execute(
                "INSERT OR IGNORE INTO images (file_path, file_name) VALUES (?, ?)",
                (str(p), p.name)
            )

    # Enqueue pass1 for images not yet processed
    with get_db() as conn:
        placeholders = ",".join("?" * len(paths_str))
        unprocessed = conn.execute(
            f"SELECT file_path FROM images WHERE pass1_status IS NULL AND file_path IN ({placeholders})",
            paths_str
        ).fetchall()
    new_paths = [Path(r["file_path"]) for r in unprocessed]
    if new_paths:
        enqueue("pass1", new_paths, priority=_PRIORITY_HIGH)

    # Bump ALL existing queued jobs for these images to high priority
    with get_db() as conn:
        placeholders = ",".join("?" * len(paths_str))
        conn.execute(
            f"""UPDATE pipeline_jobs SET priority = ?
                WHERE status = 'queued'
                AND image_id IN (
                    SELECT id FROM images WHERE file_path IN ({placeholders})
                )""",
            [_PRIORITY_HIGH] + paths_str
        )

    # Append to existing session or create new one
    appended = False
    if _PRIORITY_STATE_FILE.exists():
        try:
            existing = json.loads(_PRIORITY_STATE_FILE.read_text())
            existing_paths = set(existing.get("image_paths", []))
            new_count = len([p for p in paths_str if p not in existing_paths])
            existing_paths.update(paths_str)
            existing["image_paths"] = list(existing_paths)
            existing["image_count"] = len(existing_paths)
            existing["folders"] = existing.get("folders", [existing.get("path", "")])
            if req.path not in existing["folders"]:
                existing["folders"].append(req.path)
            existing["path"] = ", ".join(existing["folders"])
            _PRIORITY_STATE_FILE.write_text(json.dumps(existing))
            appended = True
        except Exception:
            appended = False

    if not appended:
        state = {
            "path": req.path,
            "folders": [req.path],
            "image_paths": paths_str,
            "image_count": len(all_files),
            "started_at": datetime.utcnow().isoformat(),
        }
        _PRIORITY_STATE_FILE.write_text(json.dumps(state))

    _PRIORITY_MODE_FILE.touch()

    return {
        "status": "appended" if appended else "started",
        "path": req.path,
        "image_count": len(all_files),
        "new_queued": len(new_paths),
    }


@router.post("/priority/cancel")
def priority_cancel():
    """Cancel priority mode — remove state files, downgrade priority jobs back to normal."""
    _PRIORITY_STATE_FILE.unlink(missing_ok=True)
    _PRIORITY_MODE_FILE.unlink(missing_ok=True)

    # Downgrade any remaining priority jobs back to normal
    with get_db() as conn:
        downgraded = conn.execute(
            "UPDATE pipeline_jobs SET priority = 5 WHERE priority >= ? AND status IN ('queued', 'running')",
            (_PRIORITY_HIGH,)
        ).rowcount

    return {"cancelled": True, "jobs_downgraded": downgraded}


@router.get("/priority/status")
def priority_status():
    """Return priority mode progress: per-pass completion counts."""
    import json

    if not _PRIORITY_STATE_FILE.exists():
        return {"active": False, "path": None, "image_count": 0, "progress": None}

    state = json.loads(_PRIORITY_STATE_FILE.read_text())
    image_paths = state["image_paths"]

    if not image_paths:
        return {"active": True, "path": state["path"], "image_count": 0,
                "progress": {"all_complete": True}}

    with get_db() as conn:
        placeholders = ",".join("?" * len(image_paths))

        total = len(image_paths)

        # Pass 1: images that have any pass1_status set
        pass1_done = conn.execute(
            f"SELECT COUNT(*) FROM images WHERE pass1_status IS NOT NULL AND file_path IN ({placeholders})",
            image_paths
        ).fetchone()[0]

        # Images that won't continue (culled/duplicate/fail) — these are "done"
        terminal_rows = conn.execute(
            f"""SELECT pass1_status, COUNT(*) as c FROM images
                WHERE pass1_status IN ('fail', 'duplicate', 'raw_review')
                AND file_path IN ({placeholders})
                GROUP BY pass1_status""",
            image_paths
        ).fetchall()
        terminal_breakdown = {r["pass1_status"]: r["c"] for r in terminal_rows}
        terminal = sum(terminal_breakdown.values())

        # Pass 2: images with pass2_at set
        pass2_done = conn.execute(
            f"SELECT COUNT(*) FROM images WHERE pass2_at IS NOT NULL AND file_path IN ({placeholders})",
            image_paths
        ).fetchone()[0]

        # Pass 3: images with pass3_at set
        pass3_done = conn.execute(
            f"SELECT COUNT(*) FROM images WHERE pass3_at IS NOT NULL AND file_path IN ({placeholders})",
            image_paths
        ).fetchone()[0]

        # Pass 1 cull score tiers
        pass1_cull_8 = conn.execute(
            f"SELECT COUNT(*) FROM images WHERE cull_score >= 8.0 AND pass1_status = 'pass' AND file_path IN ({placeholders})",
            image_paths
        ).fetchone()[0]
        pass1_cull_6 = conn.execute(
            f"SELECT COUNT(*) FROM images WHERE cull_score >= 6.0 AND cull_score < 8.0 AND pass1_status = 'pass' AND file_path IN ({placeholders})",
            image_paths
        ).fetchone()[0]
        pass1_cull_45 = conn.execute(
            f"SELECT COUNT(*) FROM images WHERE cull_score >= 4.5 AND cull_score < 6.0 AND pass1_status = 'pass' AND file_path IN ({placeholders})",
            image_paths
        ).fetchone()[0]
        pass1_cull_below = conn.execute(
            f"SELECT COUNT(*) FROM images WHERE cull_score IS NOT NULL AND cull_score < 4.5 AND file_path IN ({placeholders})",
            image_paths
        ).fetchone()[0]
        pass1_faces = conn.execute(
            f"SELECT COUNT(*) FROM images WHERE cull_sub LIKE '%\"faces_detected\": 1%' OR cull_sub LIKE '%\"faces_detected\": 2%' OR cull_sub LIKE '%\"faces_detected\": 3%' OR cull_sub LIKE '%\"faces_detected\": 4%' OR cull_sub LIKE '%\"faces_detected\": 5%' AND file_path IN ({placeholders})",
            image_paths
        ).fetchone()[0]

        # Pass 2 composite score tiers
        pass2_tier_7 = conn.execute(
            f"SELECT COUNT(*) FROM images WHERE nima_composite >= 7.0 AND file_path IN ({placeholders})",
            image_paths
        ).fetchone()[0]
        pass2_tier_6 = conn.execute(
            f"SELECT COUNT(*) FROM images WHERE nima_composite >= 6.0 AND nima_composite < 7.0 AND file_path IN ({placeholders})",
            image_paths
        ).fetchone()[0]
        pass2_tier_5 = conn.execute(
            f"SELECT COUNT(*) FROM images WHERE nima_composite >= 5.0 AND nima_composite < 6.0 AND file_path IN ({placeholders})",
            image_paths
        ).fetchone()[0]
        pass2_tier_below = conn.execute(
            f"SELECT COUNT(*) FROM images WHERE nima_composite IS NOT NULL AND nima_composite < 5.0 AND file_path IN ({placeholders})",
            image_paths
        ).fetchone()[0]

        # Pass 3 score tiers (based on nima_composite from pass2)
        pass3_tier_65 = conn.execute(
            f"SELECT COUNT(*) FROM images WHERE pass2_at IS NOT NULL AND nima_composite >= 6.5 AND file_path IN ({placeholders})",
            image_paths
        ).fetchone()[0]
        pass3_tier_55 = conn.execute(
            f"SELECT COUNT(*) FROM images WHERE pass2_at IS NOT NULL AND nima_composite >= 5.5 AND nima_composite < 6.5 AND file_path IN ({placeholders})",
            image_paths
        ).fetchone()[0]
        pass3_tier_50 = conn.execute(
            f"SELECT COUNT(*) FROM images WHERE pass2_at IS NOT NULL AND nima_composite >= 5.0 AND nima_composite < 5.5 AND file_path IN ({placeholders})",
            image_paths
        ).fetchone()[0]
        pass3_tier_below = conn.execute(
            f"SELECT COUNT(*) FROM images WHERE pass2_at IS NOT NULL AND nima_composite < 5.0 AND file_path IN ({placeholders})",
            image_paths
        ).fetchone()[0]

        # Images that need to go through all passes = total - terminal
        need_all_passes = total - terminal

        # All complete when: all pass1 done AND all non-terminal images have pass3
        all_complete = (pass1_done >= total) and (pass3_done >= need_all_passes)

        # Errored jobs that might be blocking completion
        errored = conn.execute(
            f"""SELECT COUNT(*) FROM pipeline_jobs
                WHERE status = 'error' AND priority >= ?
                AND image_id IN (SELECT id FROM images WHERE file_path IN ({placeholders}))""",
            [_PRIORITY_HIGH] + image_paths
        ).fetchone()[0]

        rates = _get_pass_rates(conn)
        current_file = _get_current_file(conn)

    return {
        "active": True,
        "path": state["path"],
        "folder_name": Path(state["path"]).name,
        "image_count": total,
        "started_at": state["started_at"],
        "progress": {
            "pass1_done": pass1_done,
            "pass1_total": total,
            "pass1_tiers": {
                "above_8": pass1_cull_8,
                "6_to_8": pass1_cull_6,
                "45_to_6": pass1_cull_45,
                "below_45": pass1_cull_below,
            },
            "pass2_done": pass2_done,
            "pass2_total": need_all_passes,
            "pass2_tiers": {
                "above_7": pass2_tier_7,
                "6_to_7": pass2_tier_6,
                "5_to_6": pass2_tier_5,
                "below_5": pass2_tier_below,
            },
            "pass3_done": pass3_done,
            "pass3_total": need_all_passes,
            "pass3_tiers": {
                "above_65": pass3_tier_65,
                "55_to_65": pass3_tier_55,
                "50_to_55": pass3_tier_50,
                "below_50": pass3_tier_below,
            },
            "terminal": terminal,
            "terminal_fail": terminal_breakdown.get("fail", 0),
            "terminal_duplicate": terminal_breakdown.get("duplicate", 0),
            "terminal_raw_review": terminal_breakdown.get("raw_review", 0),
            "errored": errored,
            "all_complete": all_complete,
        },
        "rates": rates,
        "current_file": current_file,
    }


def _get_pass_rates(conn) -> dict:
    """Median seconds per image for each pass, from last 20 completions."""
    import statistics
    rates = {}
    for jt in ("pass1", "pass2", "pass3"):
        rows = conn.execute("""
            SELECT (julianday(completed_at) - julianday(started_at)) * 86400 as secs
            FROM pipeline_jobs WHERE job_type = ? AND status = 'complete'
            AND started_at IS NOT NULL AND completed_at IS NOT NULL
            ORDER BY completed_at DESC LIMIT 20
        """, (jt,)).fetchall()
        times = [r[0] for r in rows if r[0] and r[0] > 0]
        rates[jt] = round(statistics.median(times), 1) if times else None
    return rates


def _get_current_file(conn) -> dict | None:
    """Currently running job file name and type."""
    row = conn.execute("""
        SELECT j.job_type, i.file_name FROM pipeline_jobs j
        JOIN images i ON j.image_id = i.id
        WHERE j.status = 'running'
        ORDER BY j.started_at DESC LIMIT 1
    """).fetchone()
    if not row:
        return None
    return {"job_type": row["job_type"], "file_name": row["file_name"]}


# ── Phase 1+2+3: diagnose / bump / promote-tier ─────────────────────────────
# Built 2026-05-07. Honors strict waterfall + cross-system dedup. See
# services/pipeline_diagnose.py and services/priority_ops.py for details.

@router.get("/why/{image_id}")
def pipeline_why(image_id: int):
    """Phase 1 diagnostic. Walks the pipeline state for one image and reports
    in plain English what stage it's at and what (if anything) is blocking
    advancement. Read-only."""
    from services.pipeline_diagnose import why_blocked
    return why_blocked(image_id)


class _BumpResponse(BaseModel):
    image_id: int
    ok: bool
    stage: Optional[str] = None
    action: Optional[str] = None
    job_id: Optional[int] = None
    priority: Optional[int] = None
    message: Optional[str] = None
    error: Optional[str] = None


@router.post("/bump/{image_id}")
def pipeline_bump(image_id: int, priority: int = 10):
    """Phase 2: bump a single image to the requested priority on its CURRENT
    stage. Strict waterfall preserved — bumps pass1/pass2/pass3 depending on
    where the image actually is. Idempotent.

    Cross-system dedup: if the image is already complete at its current
    stage (pass*_at set), returns noop. No double-processing whether the
    image was previously handled by regular or priority pipeline."""
    from services.priority_ops import bump_image
    return bump_image(image_id, priority=priority)


class _BumpFolderRequest(BaseModel):
    folder: str
    priority: int = 10
    override_nima: bool = False  # promote sub-6.0 NIMA images too


@router.post("/bump-folder")
def pipeline_bump_folder(req: _BumpFolderRequest):
    """Phase 2: bump every image whose file_path is under `folder`. Each image
    is routed to its own current stage (waterfall preserved). Already-
    complete images skipped. Set override_nima=true to force pass3 on
    sub-6.0 NIMA images as well."""
    from services.priority_ops import bump_folder
    return bump_folder(
        folder=req.folder, priority=req.priority, override_nima=req.override_nima
    )


class _PromoteTierRequest(BaseModel):
    min_nima: float = 5.0
    max_nima: float = 6.0
    priority: int = 10
    limit: int = 5000


@router.post("/promote-tier")
def pipeline_promote_tier(req: _PromoteTierRequest):
    """Phase 3: bulk-create pass3 jobs for images in a NIMA range that are
    pass2-complete but not pass3-complete and don't already have a pass3
    job. Bypasses the auto-promoter's hardcoded 6.0 threshold."""
    from services.priority_ops import promote_tier
    return promote_tier(
        min_nima=req.min_nima, max_nima=req.max_nima,
        priority=req.priority, limit=req.limit,
    )


# ── Manual Import (bypass scoring on already-rendered PNG/JPG/TIFF/etc.) ────
# Built 2026-05-07. Lets the photographer override the system's judgment for
# images they consider portfolio-worthy. RAWs explicitly rejected — they need
# editing first; that's what the full pipeline is for.

class _ManualImportRequest(BaseModel):
    folder: str
    genre: Optional[str] = None  # nature, portrait, wedding, etc. — optional


@router.post("/import-manual/preview")
def import_manual_preview(req: _ManualImportRequest):
    """Read-only scan: report how many files in `folder` would be imported,
    updated, or rejected (RAW)."""
    from services.manual_import import preview
    return preview(req.folder)


@router.post("/import-manual")
def import_manual(req: _ManualImportRequest):
    """Inject all PNG/JPG/TIFF/HEIC/WebP under `folder` into the candidate pool
    as manually-added, unscored, content-ready images. RAW files in the folder
    are skipped with a count in the response."""
    from services.manual_import import import_folder
    return import_folder(folder=req.folder, genre=req.genre)


@router.get("/stats")
def pipeline_stats():
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        pass1_done = conn.execute(
            "SELECT COUNT(*) FROM images WHERE pass1_status IS NOT NULL"
        ).fetchone()[0]
        pass2_done = conn.execute(
            "SELECT COUNT(*) FROM images WHERE pass2_at IS NOT NULL"
        ).fetchone()[0]
        pass3_done = conn.execute(
            "SELECT COUNT(*) FROM images WHERE pass3_at IS NOT NULL"
        ).fetchone()[0]
        queued = conn.execute(
            "SELECT COUNT(*) FROM pipeline_jobs WHERE status = 'queued'"
        ).fetchone()[0]
        running = conn.execute(
            "SELECT COUNT(*) FROM pipeline_jobs WHERE status = 'running'"
        ).fetchone()[0]
        return {
            "total_images": total,
            "pass1_complete": pass1_done,
            "pass2_complete": pass2_done,
            "pass3_complete": pass3_done,
            "jobs_queued": queued,
            "jobs_running": running,
        }


@router.post("/salvage/{image_id}")
def salvage_image(image_id: int):
    """Enqueue a single raw_review image for LLM salvage (pass1_raw)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, file_path, pass1_status FROM images WHERE id = ?", (image_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Image not found")
        if row["pass1_status"] != "raw_review":
            raise HTTPException(status_code=400, detail=f"Image is '{row['pass1_status']}', not raw_review")

        # Check if already queued
        existing = conn.execute(
            "SELECT id FROM pipeline_jobs WHERE image_id = ? AND job_type = 'pass1_raw' AND status IN ('queued', 'running')",
            (image_id,)
        ).fetchone()
        if existing:
            return {"status": "already_queued", "image_id": image_id}

    enqueue("pass1_raw", [Path(row["file_path"])], priority=5)
    return {"status": "queued", "image_id": image_id, "file_path": row["file_path"]}


@router.get("/health")
def pipeline_health_check():
    """Single health check: pipeline status, worker health, error counts, stuck jobs."""
    import subprocess
    pid = _get_pipeline_pid()
    # Also check launchd-managed pipeline process
    if not pid:
        try:
            result = subprocess.run(["pgrep", "-f", "queue_manager"], capture_output=True, text=True, timeout=5)
            if result.stdout.strip():
                pid = int(result.stdout.strip().split()[0])
        except Exception:
            pass
    with get_db() as conn:
        # Running jobs and their heartbeat age
        running = conn.execute(
            "SELECT COUNT(*) FROM pipeline_jobs WHERE status = 'running'"
        ).fetchone()[0]

        stale_heartbeat = conn.execute("""
            SELECT COUNT(*) FROM pipeline_jobs
            WHERE status = 'running'
            AND heartbeat_at IS NOT NULL
            AND heartbeat_at < datetime('now', '-5 minutes')
        """).fetchone()[0]

        stale_no_heartbeat = conn.execute("""
            SELECT COUNT(*) FROM pipeline_jobs
            WHERE status = 'running'
            AND heartbeat_at IS NULL
            AND started_at < datetime('now', '-15 minutes')
        """).fetchone()[0]

        # Error counts in last hour
        errors_1h = conn.execute("""
            SELECT COUNT(*) FROM error_log
            WHERE timestamp > datetime('now', '-1 hour')
            AND severity = 'error'
        """).fetchone()[0]

        critical_1h = conn.execute("""
            SELECT COUNT(*) FROM error_log
            WHERE timestamp > datetime('now', '-1 hour')
            AND severity = 'critical'
        """).fetchone()[0]

        # Unresolved errors
        unresolved = conn.execute(
            "SELECT COUNT(*) FROM error_log WHERE resolved = FALSE"
        ).fetchone()[0]

        # Errored jobs (permanent failures)
        errored_jobs = conn.execute(
            "SELECT COUNT(*) FROM pipeline_jobs WHERE status = 'error'"
        ).fetchone()[0]

        # Latest heartbeat across all running jobs
        latest_hb = conn.execute(
            "SELECT MAX(heartbeat_at) FROM pipeline_jobs WHERE status = 'running'"
        ).fetchone()[0]

    stuck = stale_heartbeat + stale_no_heartbeat
    # Status: green/yellow/red
    if not pid:
        status = "red"
        reason = "Pipeline process not running"
    elif critical_1h > 0:
        status = "red"
        reason = f"{critical_1h} critical error(s) in last hour"
    elif stuck > 0:
        status = "red"
        reason = f"{stuck} stuck job(s) detected"
    elif errors_1h > 3:
        status = "yellow"
        reason = f"{errors_1h} errors in last hour"
    elif errored_jobs > 0:
        status = "yellow"
        reason = f"{errored_jobs} permanently errored job(s)"
    else:
        status = "green"
        reason = "All systems normal"

    return {
        "status": status,
        "reason": reason,
        "pipeline_running": pid is not None,
        "pid": pid,
        "jobs_running": running,
        "stuck_jobs": stuck,
        "latest_heartbeat": latest_hb,
        "errors_last_hour": errors_1h,
        "critical_last_hour": critical_1h,
        "unresolved_errors": unresolved,
        "errored_jobs": errored_jobs,
    }


@router.get("/errors")
def pipeline_errors(limit: int = 20, severity: str = None, resolved: bool = None):
    """Recent errors from the error_log table."""
    with get_db() as conn:
        query = "SELECT * FROM error_log WHERE 1=1"
        params = []
        if severity:
            query += " AND severity = ?"
            params.append(severity)
        if resolved is not None:
            query += " AND resolved = ?"
            params.append(resolved)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return {"errors": [dict(r) for r in rows]}


@router.post("/errors/{error_id}/resolve")
def resolve_error(error_id: int):
    """Mark an error as resolved."""
    with get_db() as conn:
        from datetime import datetime
        conn.execute(
            "UPDATE error_log SET resolved = TRUE, resolved_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), error_id),
        )
        return {"status": "resolved", "error_id": error_id}


@router.post("/errors/resolve-all")
def resolve_all_errors():
    """Mark all unresolved errors as resolved."""
    with get_db() as conn:
        from datetime import datetime
        r = conn.execute(
            "UPDATE error_log SET resolved = TRUE, resolved_at = ? WHERE resolved = FALSE",
            (datetime.utcnow().isoformat(),),
        )
        return {"status": "resolved", "count": r.rowcount}


@router.post("/rescue/{image_id}")
def rescue_image(image_id: int):
    """Manually queue a below-threshold image for pass3 (like salvage for pass1_raw)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, file_path, nima_composite, pass2_at, pass3_at FROM images WHERE id = ?",
            (image_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Image not found")
        if not row["pass2_at"]:
            raise HTTPException(status_code=400, detail="Image has not completed pass2 yet")
        if row["pass3_at"]:
            raise HTTPException(status_code=400, detail="Image already has pass3 results")

        # Check if already queued for pass3
        existing = conn.execute(
            "SELECT id FROM pipeline_jobs WHERE image_id = ? AND job_type = 'pass3' AND status IN ('queued', 'running')",
            (image_id,),
        ).fetchone()
        if existing:
            return {"status": "already_queued", "image_id": image_id}

    enqueue("pass3", [Path(row["file_path"])], priority=5)
    return {
        "status": "queued",
        "image_id": image_id,
        "file_path": row["file_path"],
        "nima_composite": row["nima_composite"],
    }


@router.post("/pass3/retag-7b")
def retag_7b_images(
    limit: int = 10000,
    min_nima: float = 0.0,
    print_worthy_only: bool = False,
    priority: int = 3,
):
    """
    Re-queue all pass3 images tagged by qwen2.5vl:7b for re-tagging by the current
    vision_model (typically 32b). Clears pass3_at on matched images so they'll be
    picked up by _auto_promote on the next loop.

    Params:
      limit: max images to requeue (default 10000)
      min_nima: only retag images with nima_composite >= this (default 0 = all)
      print_worthy_only: if true, only retag print_worthy images
      priority: pass3 job priority (default 3)
    """
    where = ["pass3_model = 'qwen2.5vl:7b'", "pass3_at IS NOT NULL"]
    params: list = []
    if min_nima > 0:
        where.append("nima_composite >= ?")
        params.append(min_nima)
    if print_worthy_only:
        where.append("print_worthy = 1")

    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT id, file_path FROM images
                WHERE {' AND '.join(where)}
                ORDER BY nima_composite DESC
                LIMIT ?""",
            params + [limit],
        ).fetchall()
        if not rows:
            return {"status": "no_matches", "queued": 0}

        # Clear pass3_at so _auto_promote sees them as needing pass3
        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE images SET pass3_at = NULL WHERE id IN ({placeholders})",
            ids,
        )

    # Enqueue pass3 jobs
    paths = [Path(r["file_path"]) for r in rows]
    enqueue("pass3", paths, priority=priority)

    return {
        "status": "queued",
        "queued": len(rows),
        "priority": priority,
        "filter": {"min_nima": min_nima, "print_worthy_only": print_worthy_only},
    }
