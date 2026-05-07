"""
Phase 9 — SD Card Auto-Import
Detects mounted SD cards, scans for images, and COPIES them to the watch folder.
SD cards are NEVER modified — source files stay untouched until the user formats manually.
"""
import json
import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.config import settings
from core.database import get_db

logger = logging.getLogger("lens.sd_importer")

SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".raw", ".arw", ".cr2", ".cr3",
    ".nef", ".orf", ".rw2", ".dng", ".tiff", ".tif", ".heic",
}

_IMPORT_STATUS_FILE = Path("/tmp/lens_import_status.json")

# Volumes to always skip (the user's personal 8TB drive and macOS system mounts)
_SKIP_VOLUMES = {
    "/Volumes/8TB",
    "/Volumes/Macintosh HD",
    "/Volumes/Recovery",
    "/Volumes/Preboot",
    "/Volumes/VM",
    "/Volumes/Update",
    "/Volumes/Data",
}


# ---------------------------------------------------------------------------
# SD Detection
# ---------------------------------------------------------------------------

def detect_sd_cards() -> list[dict]:
    """
    Return a list of mounted volumes that could be SD cards.
    Runs `diskutil list -plist` for accurate machine-readable output,
    then cross-references /Volumes/ for what is currently mounted.

    Returns list of dicts:
        {"mount_point": str, "name": str, "size": str, "is_sd": bool}
    """
    results = []

    try:
        # Get all disk info in plist format for reliable parsing
        raw = subprocess.run(
            ["diskutil", "list", "-plist", "external"],
            capture_output=True, text=True, timeout=10,
        )

        # Also gather human-readable output for size info
        human_raw = subprocess.run(
            ["diskutil", "list", "external"],
            capture_output=True, text=True, timeout=10,
        )

        # Parse size info from human output — build map of disk_id → size string
        size_map: dict[str, str] = {}
        for line in human_raw.stdout.splitlines():
            # Lines like:   0:  GUID_partition_scheme   *31.3 GB    disk4
            parts = line.split()
            if len(parts) >= 4 and parts[-1].startswith("disk"):
                disk_id = parts[-1]
                # Size is the part with GB/MB/TB
                for part in parts:
                    if any(unit in part for unit in ["GB", "MB", "TB", "KB"]):
                        size_map[disk_id] = part
                        break

        # Use plist output to find external disk identifiers
        import plistlib
        if raw.returncode == 0 and raw.stdout.strip():
            plist_data = plistlib.loads(raw.stdout.encode())
            all_disks_any_partition = plist_data.get("AllDisksAndPartitions", [])
            external_disk_ids = {d.get("DeviceIdentifier", "") for d in all_disks_any_partition}
        else:
            external_disk_ids = set()

    except Exception as e:
        logger.warning(f"diskutil plist parsing failed: {e}")
        external_disk_ids = set()
        size_map = {}

    # Walk /Volumes/ to find actual mount points
    volumes_dir = Path("/Volumes")
    if not volumes_dir.exists():
        return results

    for vol_path in sorted(volumes_dir.iterdir()):
        if not vol_path.is_dir():
            continue
        mount_str = str(vol_path)

        # Skip protected volumes
        if any(mount_str == skip or mount_str.startswith(skip + "/") for skip in _SKIP_VOLUMES):
            continue

        # Skip macOS system-internal mounts
        name = vol_path.name
        if name in {"Macintosh HD", "Recovery", "Preboot", "VM", "Update", "Data"}:
            continue

        # Try to determine disk identifier for this volume
        disk_id = ""
        try:
            info = subprocess.run(
                ["diskutil", "info", "-plist", mount_str],
                capture_output=True, text=True, timeout=5,
            )
            if info.returncode == 0:
                import plistlib
                info_data = plistlib.loads(info.stdout.encode())
                disk_id = info_data.get("DeviceIdentifier", "")
                # Get more accurate size
                size_bytes = info_data.get("TotalSize", 0)
                if size_bytes:
                    size_gb = size_bytes / (1024 ** 3)
                    size_str = f"{size_gb:.1f}GB"
                else:
                    size_str = size_map.get(disk_id, "unknown")
            else:
                size_str = size_map.get(disk_id, "unknown")
        except Exception:
            size_str = "unknown"

        # Determine if this looks like an SD card
        # Heuristics: external disk, small size, typical SD card names, DCIM folder
        has_dcim = (vol_path / "DCIM").exists()
        is_external = bool(disk_id) and any(
            disk_id.startswith(ext_id) or ext_id.startswith(disk_id.rstrip("0123456789"))
            for ext_id in external_disk_ids
        )

        # If we can't determine externality but DCIM exists, still flag it
        is_sd = has_dcim or is_external

        results.append({
            "mount_point": mount_str,
            "name": name,
            "size": size_str,
            "is_sd": is_sd,
            "has_dcim": has_dcim,
            "disk_id": disk_id,
        })

    return results


# ---------------------------------------------------------------------------
# SD Scanning
# ---------------------------------------------------------------------------

def scan_sd_card(mount_point: str) -> dict:
    """
    Recursively scan a mounted volume for supported image files.

    Returns:
        {
            "mount_point": str,
            "total_images": int,
            "total_size_mb": float,
            "folders": list[str],   # unique parent folders containing images
            "file_list": list[str], # absolute paths to all image files
        }
    """
    root = Path(mount_point)
    if not root.exists():
        return {
            "mount_point": mount_point,
            "total_images": 0,
            "total_size_mb": 0.0,
            "folders": [],
            "file_list": [],
            "error": "Mount point does not exist",
        }

    file_list: list[str] = []
    total_bytes = 0
    folders: set[str] = set()

    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
            file_list.append(str(p))
            total_bytes += p.stat().st_size
            folders.add(str(p.parent))

    return {
        "mount_point": mount_point,
        "total_images": len(file_list),
        "total_size_mb": round(total_bytes / (1024 * 1024), 2),
        "folders": sorted(folders),
        "file_list": sorted(file_list),
    }


# ---------------------------------------------------------------------------
# Import Status File Helpers
# ---------------------------------------------------------------------------

def _write_status(status: dict) -> None:
    try:
        _IMPORT_STATUS_FILE.write_text(json.dumps(status))
    except Exception as e:
        logger.warning(f"Could not write import status: {e}")


def _clear_status() -> None:
    try:
        if _IMPORT_STATUS_FILE.exists():
            _IMPORT_STATUS_FILE.unlink()
    except Exception:
        pass


def get_import_progress() -> dict:
    """Return current import progress, or idle status if no import is running."""
    if not _IMPORT_STATUS_FILE.exists():
        return {"status": "idle", "running": False}
    try:
        data = json.loads(_IMPORT_STATUS_FILE.read_text())
        return data
    except Exception:
        return {"status": "idle", "running": False}


# ---------------------------------------------------------------------------
# Main Import
# ---------------------------------------------------------------------------

def import_sd_card(
    mount_point: str,
    shoot_name: str,
    genre: str,
    destination_base: Optional[str] = None,
) -> dict:
    """
    Copy all images from an SD card to a new dated shoot folder.

    - NEVER moves or deletes source files on the SD card.
    - Verifies copy integrity via file size comparison.
    - Registers the new folder in the pipeline after a successful copy.

    Returns:
        {
            "copied": int,
            "failed": int,
            "destination": str,
            "shoot_folder": str,
            "log_id": int,
        }
    """
    dest_base = Path(destination_base) if destination_base else settings.photo_watch_path

    # Build shoot folder name: YYYY-MM-DD_shoot_name (spaces → underscores)
    date_str = datetime.now().strftime("%Y-%m-%d")
    safe_name = shoot_name.strip().replace(" ", "_").replace("/", "_")
    shoot_folder = dest_base / f"{date_str}_{safe_name}"
    shoot_folder.mkdir(parents=True, exist_ok=True)

    # Scan source
    scan = scan_sd_card(mount_point)
    file_list = scan["file_list"]
    total_size_mb = scan["total_size_mb"]

    if not file_list:
        return {
            "copied": 0,
            "failed": 0,
            "destination": str(dest_base),
            "shoot_folder": str(shoot_folder),
            "log_id": None,
            "message": "No image files found on SD card",
        }

    # Create import_logs record
    log_id: Optional[int] = None
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO import_logs
               (source_path, destination_path, shoot_name, genre, total_size_mb, status)
               VALUES (?, ?, ?, ?, ?, 'in_progress')""",
            (mount_point, str(shoot_folder), shoot_name, genre, total_size_mb),
        )
        log_id = cursor.lastrowid

    # Write initial status
    _write_status({
        "running": True,
        "status": "copying",
        "log_id": log_id,
        "shoot_name": shoot_name,
        "source": mount_point,
        "destination": str(shoot_folder),
        "total": len(file_list),
        "copied": 0,
        "failed": 0,
        "started_at": datetime.now().isoformat(),
    })

    copied = 0
    failed = 0
    failed_files: list[str] = []

    for i, src_str in enumerate(file_list):
        src = Path(src_str)
        dst = shoot_folder / src.name

        # Handle filename collisions by appending a counter
        if dst.exists():
            stem = src.stem
            suffix = src.suffix
            counter = 1
            while dst.exists():
                dst = shoot_folder / f"{stem}_{counter}{suffix}"
                counter += 1

        try:
            shutil.copy2(src, dst)

            # Integrity check: size must match
            src_size = src.stat().st_size
            dst_size = dst.stat().st_size
            if src_size != dst_size:
                logger.error(
                    f"Size mismatch for {src.name}: src={src_size}, dst={dst_size}"
                )
                dst.unlink(missing_ok=True)
                failed += 1
                failed_files.append(src_str)
            else:
                copied += 1

        except Exception as e:
            logger.error(f"Failed to copy {src}: {e}")
            failed += 1
            failed_files.append(src_str)

        # Update progress every 10 files
        if (i + 1) % 10 == 0:
            _write_status({
                "running": True,
                "status": "copying",
                "log_id": log_id,
                "shoot_name": shoot_name,
                "source": mount_point,
                "destination": str(shoot_folder),
                "total": len(file_list),
                "copied": copied,
                "failed": failed,
                "started_at": datetime.now().isoformat(),
            })

    # Update import_logs with final result
    final_status = "complete" if failed == 0 else "complete_with_errors"
    with get_db() as conn:
        conn.execute(
            """UPDATE import_logs
               SET files_copied = ?, files_failed = ?, status = ?, completed_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (copied, failed, final_status, log_id),
        )

    # Register the new folder in the pipeline if at least some files copied
    if copied > 0:
        _register_shoot_folder(shoot_folder, shoot_name, genre)

    _write_status({
        "running": False,
        "status": final_status,
        "log_id": log_id,
        "shoot_name": shoot_name,
        "source": mount_point,
        "destination": str(shoot_folder),
        "total": len(file_list),
        "copied": copied,
        "failed": failed,
        "failed_files": failed_files,
        "completed_at": datetime.now().isoformat(),
    })

    logger.info(
        f"SD import complete: {copied} copied, {failed} failed → {shoot_folder}"
    )

    return {
        "copied": copied,
        "failed": failed,
        "destination": str(dest_base),
        "shoot_folder": str(shoot_folder),
        "log_id": log_id,
    }


# ---------------------------------------------------------------------------
# Pipeline Registration
# ---------------------------------------------------------------------------

def _register_shoot_folder(folder: Path, shoot_name: str, genre: str) -> None:
    """Register images from the imported folder into the pipeline."""
    from pipeline.queue_manager import enqueue

    image_paths = [
        p for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    if not image_paths:
        return

    # Create a shoot record
    shoot_id: Optional[int] = None
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO shoots (shoot_date, genre, notes, total_images, created_at)
               VALUES (date('now'), ?, ?, ?, CURRENT_TIMESTAMP)""",
            (genre, shoot_name, len(image_paths)),
        )
        shoot_id = cursor.lastrowid

        # Register images
        for path in image_paths:
            conn.execute(
                """INSERT OR IGNORE INTO images (file_path, file_name, shoot_id, genre)
                   VALUES (?, ?, ?, ?)""",
                (str(path), path.name, shoot_id, genre),
            )

    # Enqueue pass1
    enqueue("pass1", image_paths, shoot_id=shoot_id, priority=7)
    logger.info(
        f"Registered {len(image_paths)} images for shoot_id={shoot_id} ({shoot_name})"
    )
