"""
Phase 9 — SD Card Import API Routes

GET  /api/v1/import/detect    — detect connected SD cards
POST /api/v1/import/scan      — scan a specific mount point
POST /api/v1/import/start     — start import (mount_point, shoot_name, genre)
GET  /api/v1/import/progress  — current import progress
GET  /api/v1/import/history   — past imports from import_logs table
"""
import threading
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from core.database import get_db
from pipeline.sd_importer import (
    detect_sd_cards,
    get_import_progress,
    import_sd_card,
    scan_sd_card,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ScanRequest(BaseModel):
    mount_point: str


class ImportRequest(BaseModel):
    mount_point: str
    shoot_name: str
    genre: str
    destination_base: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/detect")
def detect_cards():
    """Detect mounted SD cards and external volumes."""
    cards = detect_sd_cards()
    return {
        "count": len(cards),
        "cards": cards,
    }


@router.post("/scan")
def scan_card(req: ScanRequest):
    """Scan a specific mount point for image files."""
    result = scan_sd_card(req.mount_point)
    return result


@router.post("/start")
def start_import(req: ImportRequest, background_tasks: BackgroundTasks):
    """
    Start an SD card import in the background.
    Returns immediately with the log_id; poll /progress for updates.
    """
    # Check that an import isn't already running
    progress = get_import_progress()
    if progress.get("running"):
        raise HTTPException(
            status_code=409,
            detail=f"An import is already in progress: {progress.get('shoot_name')}",
        )

    # Validate mount point exists
    from pathlib import Path
    if not Path(req.mount_point).exists():
        raise HTTPException(
            status_code=404,
            detail=f"Mount point not found: {req.mount_point}",
        )

    # Run import in a background thread (non-blocking for the API)
    def _run():
        import_sd_card(
            mount_point=req.mount_point,
            shoot_name=req.shoot_name,
            genre=req.genre,
            destination_base=req.destination_base,
        )

    thread = threading.Thread(target=_run, daemon=True, name="sd_import")
    thread.start()

    return {
        "status": "started",
        "shoot_name": req.shoot_name,
        "source": req.mount_point,
        "message": "Import running in background — poll /progress for updates",
    }


@router.get("/progress")
def import_progress():
    """Return current import status (or idle if none running)."""
    return get_import_progress()


@router.get("/history")
def import_history(limit: int = 50):
    """Return past import records from import_logs table."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM import_logs
               ORDER BY started_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return {
        "count": len(rows),
        "imports": [dict(r) for r in rows],
    }
