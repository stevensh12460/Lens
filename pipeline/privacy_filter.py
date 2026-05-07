"""
Privacy filter — face detection and boudoir image segregation.
Runs on ALL boudoir images regardless of face detection result.
Uses OpenCV DNN face detector.
"""
import shutil
from datetime import datetime
from pathlib import Path

import cv2

from core.config import settings
from core.database import get_db

_BOUDOIR_PATH = settings.boudoir_private_path

# OpenCV DNN face detector model paths (ships with opencv-python)
_PROTO = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"


def detect_faces(image_path: Path) -> tuple[bool, int]:
    """Returns (faces_present, face_count) using Haar cascade."""
    img = cv2.imread(str(image_path))
    if img is None:
        return False, 0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cascade = cv2.CascadeClassifier(_PROTO)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    count = len(faces) if len(faces) > 0 else 0
    return count > 0, count


def segregate_boudoir(image_path: Path, image_id: int) -> Path:
    """Move boudoir image to private folder. Returns new path."""
    _BOUDOIR_PATH.mkdir(parents=True, exist_ok=True)
    dest = _BOUDOIR_PATH / image_path.name
    if image_path != dest:
        shutil.move(str(image_path), str(dest))
    return dest


def process_image(image_path: Path) -> dict:
    """
    Run privacy filter on a single image.
    - Detects faces on all images
    - Boudoir images are always segregated to private folder
    - Images with identifiable faces are flagged
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, genre FROM images WHERE file_path = ?", (str(image_path),)
        ).fetchone()
        if not row:
            return {"file_path": str(image_path), "status": "not_found"}

        image_id = row["id"]
        genre = row["genre"] or ""

    faces_present, face_count = detect_faces(image_path)
    identifiable = faces_present and face_count > 0

    privacy_folder = None
    final_path = image_path

    if genre.lower() == "boudoir":
        final_path = segregate_boudoir(image_path, image_id)
        privacy_folder = str(_BOUDOIR_PATH)

    with get_db() as conn:
        conn.execute(
            """UPDATE images SET
               faces_present = ?, face_count = ?, identifiable = ?,
               privacy_folder = ?, privacy_at = ?
               WHERE id = ?
               """,
            (faces_present, face_count, identifiable,
             privacy_folder, datetime.utcnow().isoformat(), image_id),
        )
        if final_path != image_path:
            conn.execute(
                "UPDATE images SET file_path = ? WHERE id = ?",
                (str(final_path), image_id),
            )

    return {
        "image_id": image_id,
        "file_path": str(final_path),
        "faces_present": faces_present,
        "face_count": face_count,
        "identifiable": identifiable,
        "privacy_folder": privacy_folder,
        "genre": genre,
    }


def process_batch(image_paths: list[Path]) -> list[dict]:
    results = []
    for path in image_paths:
        try:
            results.append(process_image(path))
        except Exception as e:
            results.append({"file_path": str(path), "error": str(e)})
    return results


def get_eligible_images(limit: int = 500) -> list[Path]:
    """Boudoir images not yet privacy-filtered, plus any identifiable images."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT file_path FROM images
               WHERE (genre = 'boudoir' OR faces_present = TRUE)
               AND privacy_at IS NULL AND pass3_at IS NOT NULL
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [Path(r["file_path"]) for r in rows]
