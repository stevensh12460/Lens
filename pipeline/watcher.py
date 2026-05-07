"""
Watchdog folder monitor — watches PHOTO_WATCH_PATH for new folders/files.
On new folder detection, registers all images and enqueues full pipeline.
"""
import logging
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler, DirCreatedEvent, FileCreatedEvent
from watchdog.observers import Observer

from core.config import settings
from core.database import get_db
from pipeline.queue_manager import enqueue

logger = logging.getLogger("lens.watcher")

_WATCH_PATH = settings.photo_watch_path
_SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".cr2", ".cr3", ".nef", ".arw", ".raf", ".dng", ".orf", ".rw2", ".pef"}


def _register_and_enqueue_folder(folder_path: Path, shoot_id: int | None = None) -> int:
    """Register all images in a folder and enqueue them for full pipeline processing."""
    image_paths = [
        p for p in folder_path.rglob("*")
        if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTENSIONS and not p.name.startswith("._")
    ]
    if not image_paths:
        return 0

    # Register all images first
    new_image_ids: list[tuple[int, Path]] = []
    with get_db() as conn:
        for path in image_paths:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO images (file_path, file_name, shoot_id) VALUES (?, ?, ?)",
                (str(path), path.name, shoot_id),
            )
            if cursor.rowcount > 0 and cursor.lastrowid:
                new_image_ids.append((cursor.lastrowid, path))

    # Detect Lightroom-edited variants of existing RAWs and persist the link.
    # Best-effort: failure here doesn't block ingestion.
    if new_image_ids:
        try:
            from services.edit_lineage import link_if_edit
            for img_id, p in new_image_ids:
                link_if_edit(img_id, p)
        except Exception as e:
            logger.warning(f"edit_lineage detection failed: {e}")

    # Enqueue Pass 1 for all
    enqueue("pass1", image_paths, shoot_id=shoot_id, priority=5)
    logger.info(f"Enqueued {len(image_paths)} images from {folder_path}")
    return len(image_paths)


class LENSEventHandler(FileSystemEventHandler):
    def on_created(self, event):
        path = Path(event.src_path)

        if isinstance(event, DirCreatedEvent):
            # New folder dropped — wait briefly for files to finish copying, then enqueue
            logger.info(f"New folder detected: {path}")
            time.sleep(2)
            count = _register_and_enqueue_folder(path)
            logger.info(f"Registered {count} images from new folder: {path.name}")

        elif isinstance(event, FileCreatedEvent):
            if path.suffix.lower() in _SUPPORTED_EXTENSIONS and not path.name.startswith("._"):
                logger.info(f"New image file: {path}")
                new_id: int | None = None
                with get_db() as conn:
                    cursor = conn.execute(
                        "INSERT OR IGNORE INTO images (file_path, file_name) VALUES (?, ?)",
                        (str(path), path.name),
                    )
                    if cursor.rowcount > 0:
                        new_id = cursor.lastrowid
                # Link to original RAW if this looks like an LR export.
                if new_id:
                    try:
                        from services.edit_lineage import link_if_edit
                        link_if_edit(new_id, path)
                    except Exception as e:
                        logger.warning(f"edit_lineage failed for {path.name}: {e}")
                enqueue("pass1", [path], priority=5)


def start_watcher() -> None:
    _WATCH_PATH.mkdir(parents=True, exist_ok=True)
    handler = LENSEventHandler()
    observer = Observer()
    observer.schedule(handler, str(_WATCH_PATH), recursive=True)
    observer.start()
    logger.info(f"Watching {_WATCH_PATH}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    start_watcher()
