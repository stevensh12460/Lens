"""
Pass 1 — Technical cull with multi-signal quality scoring.
CPU only, no GPU. Face-aware sharpness, exposure clipping analysis,
noise estimation, and perceptual hash deduplication.

Produces a cull_score (0-10) with sub-signal breakdown.
Threshold: >= 4.5 = pass, 3.0-4.5 = raw_review (RAW only), < 3.0 = fail.
"""
import json
import logging
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import imagehash
import numpy as np
from PIL import Image

_FILE_TIMEOUT = 120  # seconds — skip file if it takes longer than this

logger = logging.getLogger("lens.pass1")

from core.config import settings
from core.database import get_db
from lens_core.tz import now_et

_BLUR_THRESHOLD = settings.blur_threshold
_EXPOSURE_LOW = settings.exposure_low
_EXPOSURE_HIGH = settings.exposure_high

_RAW_EXTENSIONS = {".arw", ".cr2", ".cr3", ".nef", ".raf", ".dng", ".orf", ".rw2", ".pef"}

# Cull score thresholds
_CULL_PASS = 4.5
_CULL_RAW_REVIEW = 3.0   # RAW files between this and _CULL_PASS get raw_review

# Cull sub-signal weights
_CULL_WEIGHTS = {
    "zone_sharpness": 0.30,
    "edge_density": 0.15,
    "frequency_ratio": 0.10,
    "highlight_clip": 0.15,
    "shadow_clip": 0.10,
    "dynamic_range": 0.10,
    "noise": 0.10,
}

# Haar cascade — cached at module level
_face_cascade_cache = None


def _get_face_cascade():
    global _face_cascade_cache
    if _face_cascade_cache is None:
        _face_cascade_cache = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
    return _face_cascade_cache


# ─── Image loading ────────────────────────────────────────────────────────────


def _decode_raw(image_path: Path) -> Optional[np.ndarray]:
    """Decode a RAW file to a numpy BGR array using rawpy.

    Some older CR2/ARW files have damaged sensor data — LibRaw reports
    "data corrupted at <offset>" — while still carrying an intact
    full-resolution embedded JPEG. The photo is fine; only the raw payload
    rotted. Fall back to that preview rather than discarding the image.
    """
    try:
        import rawpy
        with rawpy.imread(str(image_path)) as raw:
            rgb = raw.postprocess(
                use_camera_wb=True,
                half_size=True,
                no_auto_bright=False,
                output_bps=8,
            )
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    except Exception:
        return _decode_raw_preview(image_path)


def _decode_raw_preview(image_path: Path) -> Optional[np.ndarray]:
    """Last resort: pull the embedded JPEG preview out of a damaged RAW."""
    try:
        import io
        import rawpy
        from PIL import Image as _PILImage
        with rawpy.imread(str(image_path)) as raw:
            thumb = raw.extract_thumb()
        if thumb.format == rawpy.ThumbFormat.JPEG:
            img = _PILImage.open(io.BytesIO(thumb.data)).convert("RGB")
            arr = np.asarray(img)
        else:
            arr = np.asarray(thumb.data)
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    except Exception:
        return None


def _load_image_array(image_path: Path) -> Optional[np.ndarray]:
    """Load image as BGR numpy array, handling RAW files."""
    if image_path.suffix.lower() in _RAW_EXTENSIONS:
        return _decode_raw(image_path)
    img = cv2.imread(str(image_path))
    return img


# ─── Cull Sub-Signals ─────────────────────────────────────────────────────────


def _detect_faces(gray: np.ndarray, h: int, w: int) -> list[tuple]:
    """Detect faces via Haar cascade. Returns list of (x,y,w,h) rects."""
    cascade = _get_face_cascade()
    gray_u8 = gray.astype(np.uint8) if gray.dtype != np.uint8 else gray
    min_size = int(max(w, h) * 0.05)
    faces = cascade.detectMultiScale(gray_u8, scaleFactor=1.1, minNeighbors=6,
                                      minSize=(min_size, min_size))
    if faces is None or len(faces) == 0:
        return []
    return [(int(x), int(y), int(fw), int(fh)) for x, y, fw, fh in faces]


def _zone_sharpness(gray: np.ndarray, h: int, w: int, face_rects: list[tuple]) -> float:
    """Zone-based sharpness: 5x5 grid Laplacian variance, face-aware.
    If faces detected, face zone sharpness is weighted 3x.
    Returns 0-10."""
    grid_rows, grid_cols = 5, 5
    zone_h, zone_w = h // grid_rows, w // grid_cols

    if zone_h < 10 or zone_w < 10:
        # Image too small for grid — fall back to global
        var = cv2.Laplacian(gray, cv2.CV_64F).var()
        return min(10.0, var / 200.0 * 10.0)

    zone_scores = []
    for r in range(grid_rows):
        for c in range(grid_cols):
            y1, y2 = r * zone_h, (r + 1) * zone_h
            x1, x2 = c * zone_w, (c + 1) * zone_w
            zone = gray[y1:y2, x1:x2]
            var = cv2.Laplacian(zone, cv2.CV_64F).var()
            zone_scores.append((var, r, c, y1, y2, x1, x2))

    # Best zone score (sharpest area)
    best_var = max(s[0] for s in zone_scores)

    # Face zone sharpness — if faces detected, measure sharpness at face
    face_var = 0.0
    if face_rects:
        largest = max(face_rects, key=lambda f: f[2] * f[3])
        fx, fy, fw, fh = largest
        face_region = gray[fy:fy + fh, fx:fx + fw]
        if face_region.size > 0:
            face_var = cv2.Laplacian(face_region, cv2.CV_64F).var()

    # Use the better of: best zone or face sharpness (face weighted higher)
    effective_var = max(best_var, face_var * 1.2) if face_var > 0 else best_var

    # Map to 0-10: <50 = very blurry (0-2), 50-200 = soft (2-5), 200-500 = sharp (5-8), >500 = very sharp (8-10)
    if effective_var > 500:
        return min(10.0, 8.0 + (effective_var - 500) / 500 * 2.0)
    elif effective_var > 200:
        return 5.0 + (effective_var - 200) / 300 * 3.0
    elif effective_var > 50:
        return 2.0 + (effective_var - 50) / 150 * 3.0
    else:
        return effective_var / 50 * 2.0


def _edge_density(gray: np.ndarray, face_rects: list[tuple], h: int, w: int) -> float:
    """Edge density: percentage of strong edges. Face-aware — measures subject area.
    Returns 0-10."""
    gray_u8 = gray.astype(np.uint8) if gray.dtype != np.uint8 else gray
    edges = cv2.Canny(gray_u8, 50, 150)

    if face_rects:
        # Measure edge density around the face/subject
        largest = max(face_rects, key=lambda f: f[2] * f[3])
        fx, fy, fw, fh = largest
        pad_x, pad_y = int(fw * 0.5), int(fh * 0.5)
        sx1 = max(0, fx - pad_x)
        sy1 = max(0, fy - pad_y)
        sx2 = min(w, fx + fw + pad_x)
        sy2 = min(h, fy + fh + int(fh * 1.0))
        subject_edges = edges[sy1:sy2, sx1:sx2]
        if subject_edges.size > 0:
            density = np.count_nonzero(subject_edges) / subject_edges.size
        else:
            density = np.count_nonzero(edges) / edges.size
    else:
        density = np.count_nonzero(edges) / edges.size

    # Map to 0-10: 0% = 0, 5% = 5, 10%+ = 8-10
    return min(10.0, density * 100 * 1.0)


def _frequency_ratio(gray: np.ndarray) -> float:
    """High vs low frequency energy ratio via FFT. Sharp = more high freq.
    Returns 0-10."""
    gray_f = gray.astype(np.float32)
    dft = cv2.dft(gray_f, flags=cv2.DFT_COMPLEX_OUTPUT)
    magnitude = cv2.magnitude(dft[:, :, 0], dft[:, :, 1])
    magnitude = np.fft.fftshift(magnitude)

    h, w = magnitude.shape[:2]
    cy, cx = h // 2, w // 2
    radius = min(cy, cx)

    # Low freq: center 20% of spectrum
    low_r = int(radius * 0.2)
    y, x = np.ogrid[:h, :w]
    low_mask = ((x - cx) ** 2 + (y - cy) ** 2) <= low_r ** 2
    high_mask = ~low_mask

    low_energy = magnitude[low_mask].sum()
    high_energy = magnitude[high_mask].sum()

    if low_energy == 0:
        return 5.0

    ratio = high_energy / low_energy
    # Map: ratio < 0.5 = very blurry (0-3), 0.5-2.0 = normal (3-7), >2.0 = sharp (7-10)
    if ratio > 2.0:
        return min(10.0, 7.0 + (ratio - 2.0) / 3.0 * 3.0)
    elif ratio > 0.5:
        return 3.0 + (ratio - 0.5) / 1.5 * 4.0
    else:
        return ratio / 0.5 * 3.0


def _highlight_clipping(gray: np.ndarray) -> tuple[float, float]:
    """Highlight clipping analysis. Returns (score_0_10, clipping_percentage)."""
    gray_u8 = gray.astype(np.uint8) if gray.dtype != np.uint8 else gray
    total_pixels = gray_u8.size
    blown = np.count_nonzero(gray_u8 >= 250)
    pct = blown / total_pixels * 100

    # Map: 0% = 10 (perfect), 5% = 7, 15% = 3, 30%+ = 0
    if pct < 1:
        score = 10.0
    elif pct < 5:
        score = 7.0 + (5 - pct) / 4 * 3.0
    elif pct < 15:
        score = 3.0 + (15 - pct) / 10 * 4.0
    elif pct < 30:
        score = (30 - pct) / 15 * 3.0
    else:
        score = 0.0
    return score, round(pct, 2)


def _shadow_clipping(gray: np.ndarray) -> tuple[float, float]:
    """Shadow clipping analysis. Returns (score_0_10, clipping_percentage)."""
    gray_u8 = gray.astype(np.uint8) if gray.dtype != np.uint8 else gray
    total_pixels = gray_u8.size
    crushed = np.count_nonzero(gray_u8 <= 5)
    pct = crushed / total_pixels * 100

    # More lenient than highlights — dark shadows are often intentional
    # Map: 0% = 10, 10% = 7, 25% = 4, 50%+ = 1
    if pct < 2:
        score = 10.0
    elif pct < 10:
        score = 7.0 + (10 - pct) / 8 * 3.0
    elif pct < 25:
        score = 4.0 + (25 - pct) / 15 * 3.0
    elif pct < 50:
        score = 1.0 + (50 - pct) / 25 * 3.0
    else:
        score = 1.0
    return score, round(pct, 2)


def _dynamic_range(gray: np.ndarray) -> float:
    """Dynamic range utilization — how much of 0-255 is used.
    Returns 0-10."""
    gray_u8 = gray.astype(np.uint8) if gray.dtype != np.uint8 else gray
    hist = cv2.calcHist([gray_u8], [0], None, [256], [0, 256]).flatten()

    # Find the 1st and 99th percentile to ignore outliers
    cumsum = np.cumsum(hist)
    total = cumsum[-1]
    p1 = np.searchsorted(cumsum, total * 0.01)
    p99 = np.searchsorted(cumsum, total * 0.99)

    used_range = p99 - p1
    # Map: 0-50 = poor (0-3), 50-150 = moderate (3-6), 150-220 = good (6-9), 220+ = excellent (9-10)
    if used_range > 220:
        return min(10.0, 9.0 + (used_range - 220) / 35 * 1.0)
    elif used_range > 150:
        return 6.0 + (used_range - 150) / 70 * 3.0
    elif used_range > 50:
        return 3.0 + (used_range - 50) / 100 * 3.0
    else:
        return used_range / 50 * 3.0


def _noise_estimate(gray: np.ndarray) -> tuple[float, float]:
    """Estimate noise level via median absolute deviation of Laplacian.
    Returns (score_0_10, noise_level)."""
    gray_u8 = gray.astype(np.uint8) if gray.dtype != np.uint8 else gray
    laplacian = cv2.Laplacian(gray_u8, cv2.CV_64F)
    # Robust noise estimate: sigma = MAD * 1.4826
    noise = np.median(np.abs(laplacian)) * 1.4826

    # Map: noise < 3 = clean (9-10), 3-8 = good (6-9), 8-15 = noisy (3-6), >15 = very noisy (0-3)
    if noise < 3:
        score = 9.0 + (3 - noise) / 3 * 1.0
    elif noise < 8:
        score = 6.0 + (8 - noise) / 5 * 3.0
    elif noise < 15:
        score = 3.0 + (15 - noise) / 7 * 3.0
    else:
        score = max(0.0, 3.0 - (noise - 15) / 10 * 3.0)
    return score, round(float(noise), 2)


def _is_blank_frame(gray: np.ndarray) -> bool:
    """Detect blank/black frames — accidental shutter fires, lens cap on."""
    gray_u8 = gray.astype(np.uint8) if gray.dtype != np.uint8 else gray
    std = gray_u8.std()
    return std < 5.0  # Nearly uniform image


# ─── Perceptual hash ──────────────────────────────────────────────────────────


def perceptual_hash(image_path: Path) -> str:
    """Perceptual hash for deduplication."""
    if image_path.suffix.lower() in _RAW_EXTENSIONS:
        img_arr = _load_image_array(image_path)
        if img_arr is None:
            return "0" * 16
        rgb = cv2.cvtColor(img_arr, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        return str(imagehash.phash(pil_img))
    with Image.open(image_path) as img:
        return str(imagehash.phash(img))


def find_duplicate(phash: str, phash_cache: dict, image_id: Optional[int] = None) -> Optional[int]:
    """Check for duplicate using in-memory phash cache. Much faster than per-image DB query."""
    target = imagehash.hex_to_hash(phash)
    for existing_id, existing_hash in phash_cache.items():
        if existing_id == image_id:
            continue
        try:
            diff = target - existing_hash
            if diff <= 8:
                return existing_id
        except Exception:
            continue
    return None


def _load_phash_cache() -> dict:
    """Preload all passed image phashes into memory for fast dedup comparison."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, phash FROM images WHERE pass1_status = 'pass' AND phash IS NOT NULL"
        ).fetchall()
    cache = {}
    for row in rows:
        try:
            cache[row["id"]] = imagehash.hex_to_hash(row["phash"])
        except Exception:
            continue
    return cache


# ─── LLM salvage review (async, not in auto pipeline) ────────────────────────


def _save_preview(image_path: Path) -> Optional[Path]:
    """Save a JPEG preview of a RAW for LLM analysis."""
    img_arr = _load_image_array(image_path)
    if img_arr is None:
        return None
    h, w = img_arr.shape[:2]
    scale = min(1024 / max(h, w), 1.0)
    if scale < 1.0:
        img_arr = cv2.resize(img_arr, (int(w * scale), int(h * scale)))
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    cv2.imwrite(tmp.name, img_arr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return Path(tmp.name)


async def _check_raw_potential(image_path: Path) -> dict:
    """Ask the vision model if a technically-flawed image has salvageable potential."""
    from core.ollama import ollama

    preview = _save_preview(image_path)
    if not preview:
        return {"raw_potential": "no", "raw_potential_notes": "Could not decode RAW file"}

    prompt = """This photograph failed a technical quality check (blur or exposure issue).
As an experienced photographer and photo editor, assess whether this image has salvageable potential.

Respond with ONLY a valid JSON object:
{
  "has_potential": boolean (true if the image is worth saving with editing),
  "notes": string (specific actionable advice — e.g. "Strong composition, recrop to eliminate motion blur in lower third", "Underexposed but recoverable in Lightroom — lift shadows", "Good subject framing but too soft overall — not salvageable")
}"""

    try:
        result = await ollama.vision_json(preview, prompt, num_predict=150)
        return {
            "raw_potential": "yes" if result.get("has_potential") else "no",
            "raw_potential_notes": result.get("notes", ""),
        }
    except Exception as e:
        return {"raw_potential": "no", "raw_potential_notes": f"LLM check failed: {e}"}
    finally:
        try:
            preview.unlink()
        except Exception:
            pass


# ─── Core analysis ────────────────────────────────────────────────────────────


def _analyze_image(image_path: Path) -> dict:
    """Full cull analysis with multi-signal scoring. Thread-safe (no DB writes)."""
    is_raw = image_path.suffix.lower() in _RAW_EXTENSIONS

    img = _load_image_array(image_path)
    if img is None:
        return {
            "file_path": str(image_path),
            "is_raw": is_raw,
            "error": "Could not load image",
        }

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    h, w = gray.shape[:2]

    # Resize for analysis speed (max 1024px — more detail than pass2's 512)
    scale = min(1024 / max(h, w), 1.0)
    if scale < 1.0:
        gray_resized = cv2.resize(gray, (int(w * scale), int(h * scale)))
        h_r, w_r = gray_resized.shape[:2]
    else:
        gray_resized = gray
        h_r, w_r = h, w

    # Blank frame check — fast exit
    if _is_blank_frame(gray_resized):
        return {
            "file_path": str(image_path),
            "is_raw": is_raw,
            "blur_score": 0.0,
            "exposure_score": float(gray_resized.mean() / 255.0),
            "cull_score": 0.0,
            "cull_sub": {"blank_frame": True},
            "pass1_status": "fail",
        }

    # Face detection — shared across sharpness and edge density
    face_rects = _detect_faces(gray_resized, h_r, w_r)

    # Sub-signals
    zone_sharp = _zone_sharpness(gray_resized, h_r, w_r, face_rects)
    edge_dens = _edge_density(gray_resized, face_rects, h_r, w_r)
    freq_ratio = _frequency_ratio(gray_resized)
    hi_score, hi_pct = _highlight_clipping(gray_resized)
    sh_score, sh_pct = _shadow_clipping(gray_resized)
    dyn_range = _dynamic_range(gray_resized)
    noise_score, noise_level = _noise_estimate(gray_resized)

    # Compute perceptual hash from full-res
    phash_val = perceptual_hash(image_path)

    # Legacy scores for backwards compatibility
    blur_score_legacy = cv2.Laplacian(gray, cv2.CV_64F).var()
    exposure_legacy = float(gray.mean() / 255.0)

    # Blended cull score
    cull_score = (
        zone_sharp * _CULL_WEIGHTS["zone_sharpness"]
        + edge_dens * _CULL_WEIGHTS["edge_density"]
        + freq_ratio * _CULL_WEIGHTS["frequency_ratio"]
        + hi_score * _CULL_WEIGHTS["highlight_clip"]
        + sh_score * _CULL_WEIGHTS["shadow_clip"]
        + dyn_range * _CULL_WEIGHTS["dynamic_range"]
        + noise_score * _CULL_WEIGHTS["noise"]
    )
    cull_score = max(0.0, min(10.0, cull_score))

    sub_scores = {
        "zone_sharpness": round(float(zone_sharp), 2),
        "edge_density": round(float(edge_dens), 2),
        "frequency_ratio": round(float(freq_ratio), 2),
        "highlight_clip": round(float(hi_score), 2),
        "shadow_clip": round(float(sh_score), 2),
        "dynamic_range": round(float(dyn_range), 2),
        "noise": round(float(noise_score), 2),
        "faces_detected": len(face_rects),
    }

    return {
        "file_path": str(image_path),
        "is_raw": is_raw,
        "blur_score": float(blur_score_legacy),
        "exposure_score": exposure_legacy,
        "phash": phash_val,
        "cull_score": round(float(cull_score), 3),
        "cull_sub": sub_scores,
        "highlight_clipping": hi_pct,
        "shadow_clipping": sh_pct,
        "noise_estimate": noise_level,
        "faces_detected": len(face_rects),
    }


def _determine_status(analysis: dict, is_duplicate: bool, duplicate_of: Optional[int]) -> str:
    """Determine pass1 status from cull score."""
    if is_duplicate:
        return "duplicate"

    cull = analysis.get("cull_score", 0.0)

    if cull >= _CULL_PASS:
        return "pass"
    elif cull >= _CULL_RAW_REVIEW and analysis.get("is_raw", False):
        return "raw_review"
    else:
        return "fail"


# ─── Single image processing ─────────────────────────────────────────────────


def process_image(image_path: Path, shoot_id: Optional[int] = None,
                  phash_cache: Optional[dict] = None) -> dict:
    """Run Pass 1 on a single image synchronously."""
    analysis = _analyze_image(image_path)

    if analysis.get("error"):
        return {"file_path": str(image_path), "error": analysis["error"], "pass1_status": "error"}

    return _commit_result(analysis, shoot_id=shoot_id, phash_cache=phash_cache)


def _commit_result(analysis: dict, shoot_id: Optional[int] = None,
                   phash_cache: Optional[dict] = None) -> dict:
    """DB part of pass1: duplicate check + status update."""
    image_path = Path(analysis["file_path"])
    phash_val = analysis.get("phash", "0" * 16)

    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO images (file_path, file_name, shoot_id) VALUES (?, ?, ?)",
            (str(image_path), image_path.name, shoot_id),
        )
        row = conn.execute(
            "SELECT id FROM images WHERE file_path = ?", (str(image_path),)
        ).fetchone()
        image_id = row["id"]

        # Duplicate check — use in-memory cache if available, else DB query
        if phash_cache is not None:
            duplicate_of = find_duplicate(phash_val, phash_cache, image_id)
        else:
            # Fallback to DB query
            target = imagehash.hex_to_hash(phash_val)
            duplicate_of = None
            rows = conn.execute(
                "SELECT id, phash FROM images WHERE pass1_status = 'pass' AND phash IS NOT NULL AND id != ?",
                (image_id,),
            ).fetchall()
            for r in rows:
                try:
                    if target - imagehash.hex_to_hash(r["phash"]) <= 8:
                        duplicate_of = r["id"]
                        break
                except Exception:
                    continue

        is_duplicate = duplicate_of is not None
        status = _determine_status(analysis, is_duplicate, duplicate_of)

        cull_sub_json = json.dumps(analysis.get("cull_sub", {}))

        conn.execute(
            """UPDATE images SET
               blur_score = ?, exposure_score = ?, is_duplicate = ?,
               duplicate_of = ?, pass1_status = ?, pass1_at = ?,
               phash = ?, cull_score = ?, cull_sub = ?,
               highlight_clipping = ?, shadow_clipping = ?, noise_estimate = ?
               WHERE id = ?""",
            (analysis["blur_score"], analysis["exposure_score"], is_duplicate, duplicate_of,
             status, now_et().isoformat(), phash_val,
             analysis.get("cull_score"), cull_sub_json,
             analysis.get("highlight_clipping"), analysis.get("shadow_clipping"),
             analysis.get("noise_estimate"), image_id),
        )

        # Add to phash cache if passed (for subsequent images in same batch)
        if phash_cache is not None and status == "pass":
            try:
                phash_cache[image_id] = imagehash.hex_to_hash(phash_val)
            except Exception:
                pass

    return {
        "image_id": image_id,
        "file_path": analysis["file_path"],
        "blur_score": analysis["blur_score"],
        "exposure_score": analysis["exposure_score"],
        "phash": phash_val,
        "is_duplicate": is_duplicate,
        "duplicate_of": duplicate_of,
        "pass1_status": status,
        "is_raw": analysis.get("is_raw", False),
        "cull_score": analysis.get("cull_score", 0.0),
    }


# ─── Batch processing ────────────────────────────────────────────────────────


def process_batch(image_paths: list[Path], shoot_id: Optional[int] = None) -> list[dict]:
    """Process a batch with preloaded phash cache and per-image timeout."""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    # Preload phash cache — one DB read for the whole batch instead of per-image
    phash_cache = _load_phash_cache()

    results = []
    for i, path in enumerate(image_paths):
        try:
            print(f"[pass1] {i+1}/{len(image_paths)} {path.name}...", flush=True)
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(process_image, path, shoot_id=shoot_id, phash_cache=phash_cache)
                result = future.result(timeout=_FILE_TIMEOUT)
            status = result.get('pass1_status', '?')
            cull = result.get('cull_score', 0)
            print(f"[pass1] {i+1}/{len(image_paths)} {path.name} -> {status} (cull={cull:.1f})", flush=True)
            results.append(result)
        except FuturesTimeout:
            print(f"[pass1] {i+1}/{len(image_paths)} {path.name} TIMEOUT ({_FILE_TIMEOUT}s)", flush=True)
            results.append({"file_path": str(path), "error": "timeout", "pass1_status": "error"})
        except Exception as e:
            print(f"[pass1] {i+1}/{len(image_paths)} {path.name} ERROR: {e}", flush=True)
            results.append({"file_path": str(path), "error": str(e), "pass1_status": "error"})
    return results


async def process_batch_async(image_paths: list[Path], shoot_id: Optional[int] = None) -> list[dict]:
    """LLM salvage review for images already marked raw_review. Skips re-culling."""
    results = []
    for path in image_paths:
        try:
            potential = await _check_raw_potential(path)
            final_status = "pass" if potential["raw_potential"] == "yes" else "fail"
            with get_db() as conn:
                row = conn.execute(
                    "SELECT id FROM images WHERE file_path = ?", (str(path),)
                ).fetchone()
                if row:
                    conn.execute(
                        """UPDATE images SET pass1_status = ?, raw_potential = ?, raw_potential_notes = ?,
                           pass1_at = ? WHERE id = ?""",
                        (final_status, potential["raw_potential"], potential["raw_potential_notes"],
                         now_et().isoformat(), row["id"]),
                    )
            results.append({"file_path": str(path), "pass1_status": final_status, **potential})
        except Exception as e:
            results.append({"file_path": str(path), "error": str(e), "pass1_status": "error"})
    return results


# ─── Legacy compatibility ────────────────────────────────────────────────────


def blur_score(image_path: Path) -> float:
    """Legacy: global Laplacian variance."""
    img = _load_image_array(image_path)
    if img is None:
        return 0.0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def exposure_score(image_path: Path) -> float:
    """Legacy: mean brightness 0-1."""
    if image_path.suffix.lower() in _RAW_EXTENSIONS:
        img = _load_image_array(image_path)
        if img is None:
            return 0.5
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return float(gray.mean() / 255.0)
    with Image.open(image_path) as img:
        gray = img.convert("L")
        hist = gray.histogram()
        total = sum(hist)
        if total == 0:
            return 0.5
        return float(sum(i * v for i, v in enumerate(hist)) / (total * 255))
