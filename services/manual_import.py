"""
services/manual_import.py

Manual injection of already-rendered photographs (PNG/JPG/TIFF/HEIC/WebP)
into the candidate pool, bypassing pass1/2/3 scoring entirely.

Use case: photographer has photos they consider portfolio-worthy that the
automatic scoring rejected (low NIMA, etc). They want to override the system's
judgment for specific keepers.

Rules (enforced by RAW exclusion):
- ONLY non-RAW formats accepted. Raw files (ARW/CR2/DNG/etc.) are skipped
  with a logged reason. RAWs need editing before posting; that's what the
  full pipeline is for.
- Each imported image is marked `manual_added = 1` so the UI can show it as
  UNRATED and so the user can find/audit them later.
- pass1_status='pass', pass1_at/pass2_at/pass3_at populated, content_ready=1
  so the candidate-pool query treats them like any other ready image.
- NIMA / quality_score / portfolio_worthy stay NULL — these are unscored.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from core.database import get_db


# Edit-format extensions accepted by manual import. Mirrors
# services.edit_lineage._EDIT_EXTS so behavior stays consistent.
_ACCEPTED_EXTS = {".tif", ".tiff", ".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}

# RAW extensions that we explicitly reject — manual import cannot bypass
# pipeline scoring on a RAW because RAWs aren't post-ready.
_RAW_EXTS = {
    ".arw", ".cr2", ".cr3", ".dng", ".nef", ".raf", ".orf", ".rw2", ".pef",
    ".srw", ".rwl", ".srf",
}


def import_folder(
    folder: str,
    genre: Optional[str] = None,
    pillar: Optional[str] = None,
    recursive: bool = True,
) -> dict:
    """Walk `folder` and inject every PNG/JPG/TIFF/HEIC/WebP it finds into the
    images table as a manually-added, unscored, content-ready row.

    Args:
        folder: directory path to scan
        genre: optional genre string ("nature", "portrait", "events", etc.)
            applied to all imported rows. If None, genre stays NULL — the
            user can set it later from the modal.
        pillar: not stored on images directly; reserved for future use.
        recursive: walk subdirectories

    Returns:
        {
          imported: N,
          updated:  N,    # already-existing rows that got marked manual
          skipped_raw: N, # raw files explicitly rejected
          skipped_other: N,
          errors: [...],
        }
    """
    folder_path = Path(folder).expanduser()
    if not folder_path.exists() or not folder_path.is_dir():
        return {
            "ok": False,
            "error": f"Folder does not exist or is not a directory: {folder_path}",
        }

    summary = {
        "ok": True,
        "folder": str(folder_path),
        "imported": 0,
        "updated": 0,
        "skipped_raw": 0,
        "skipped_other": 0,
        "errors": [],
        "examples": [],  # first 5 imported file names for confirmation
    }

    iterator = folder_path.rglob("*") if recursive else folder_path.iterdir()
    now_iso = datetime.utcnow().isoformat()

    with get_db() as conn:
        for path in iterator:
            if not path.is_file():
                continue
            if path.name.startswith("._"):
                # macOS AppleDouble metadata
                continue
            ext = path.suffix.lower()
            if ext in _RAW_EXTS:
                summary["skipped_raw"] += 1
                continue
            if ext not in _ACCEPTED_EXTS:
                summary["skipped_other"] += 1
                continue

            try:
                # Try INSERT first; if file_path already exists, UPDATE instead
                # to mark the row manual_added without re-creating.
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO images (file_path, file_name) VALUES (?, ?)",
                    (str(path), path.name),
                )
                is_new = cursor.rowcount > 0

                # Apply manual-import bypass: pass1/2/3 marked done, content_ready,
                # genre if provided. NIMA stays NULL — we want UNRATED.
                conn.execute(
                    """UPDATE images SET
                         pass1_status = COALESCE(pass1_status, 'pass'),
                         pass1_at     = COALESCE(pass1_at, ?),
                         pass2_at     = COALESCE(pass2_at, ?),
                         pass3_at     = COALESCE(pass3_at, ?),
                         content_ready = 1,
                         manual_added = 1,
                         genre        = COALESCE(?, genre)
                       WHERE file_path = ?""",
                    (now_iso, now_iso, now_iso, genre, str(path)),
                )
                if is_new:
                    summary["imported"] += 1
                    if len(summary["examples"]) < 5:
                        summary["examples"].append(path.name)
                else:
                    summary["updated"] += 1
            except Exception as e:
                summary["errors"].append({"file": str(path), "error": str(e)})

    return summary


def preview(folder: str, recursive: bool = True) -> dict:
    """Read-only scan: count how many files would be imported, by category.
    Used by the UI to confirm before committing."""
    folder_path = Path(folder).expanduser()
    if not folder_path.exists() or not folder_path.is_dir():
        return {"ok": False, "error": f"Folder does not exist: {folder_path}"}

    counts = {
        "ok": True, "folder": str(folder_path),
        "would_import": 0, "would_update": 0, "raw_count": 0, "other_count": 0,
        "examples": [],
    }
    iterator = folder_path.rglob("*") if recursive else folder_path.iterdir()
    seen_paths: list[str] = []
    for path in iterator:
        if not path.is_file() or path.name.startswith("._"):
            continue
        ext = path.suffix.lower()
        if ext in _RAW_EXTS:
            counts["raw_count"] += 1
            continue
        if ext not in _ACCEPTED_EXTS:
            counts["other_count"] += 1
            continue
        seen_paths.append(str(path))
        if len(counts["examples"]) < 5:
            counts["examples"].append(path.name)

    if seen_paths:
        with get_db() as conn:
            placeholders = ",".join("?" * len(seen_paths))
            existing = conn.execute(
                f"SELECT COUNT(*) FROM images WHERE file_path IN ({placeholders})",
                seen_paths,
            ).fetchone()[0]
        counts["would_update"] = existing
        counts["would_import"] = len(seen_paths) - existing

    return counts
