"""
Phase 10 — Pass 0: Metadata Extraction
CPU-only. No Ollama. No GPU.

Extracts EXIF/XMP data from RAW and JPEG files, derives creative context
(season, time of day, creative intent), and optionally reverse-geocodes GPS.

All updates are safe: only fields with actual data are written to the DB.
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import exifread

from core.database import get_db

logger = logging.getLogger("lens.pass0")

# ---------------------------------------------------------------------------
# GPS helpers
# ---------------------------------------------------------------------------

def _dms_to_decimal(values, ref: str) -> Optional[float]:
    """Convert DMS (degrees/minutes/seconds) ratio list to decimal degrees."""
    try:
        d = float(values[0].num) / float(values[0].den)
        m = float(values[1].num) / float(values[1].den)
        s = float(values[2].num) / float(values[2].den)
        decimal = d + m / 60.0 + s / 3600.0
        if ref in ("S", "W"):
            decimal = -decimal
        return round(decimal, 7)
    except Exception:
        return None


def _ratio_to_float(ratio) -> Optional[float]:
    """Safely convert an exifread Ratio/IFDTag to float."""
    try:
        if hasattr(ratio, "values"):
            v = ratio.values[0]
        else:
            v = ratio
        if hasattr(v, "num") and hasattr(v, "den"):
            if v.den == 0:
                return None
            return float(v.num) / float(v.den)
        return float(v)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# EXIF Extraction
# ---------------------------------------------------------------------------

def extract_exif(file_path: str) -> dict:
    """
    Extract EXIF metadata from a RAW or JPEG file using exifread.

    Returns a flat dict with normalized field names.
    Missing fields are omitted (never None-padded).
    """
    result: dict = {}
    path = Path(file_path)
    if not path.exists():
        return result

    try:
        with open(path, "rb") as f:
            tags = exifread.process_file(f, details=False, stop_tag="GPS GPSImgDirection")
    except Exception as e:
        logger.warning(f"exifread failed on {path.name}: {e}")
        return result

    # --- Capture datetime ---
    for tag_name in ("EXIF DateTimeOriginal", "Image DateTime", "EXIF DateTimeDigitized"):
        tag = tags.get(tag_name)
        if tag:
            try:
                raw = str(tag).strip()
                # EXIF format: "YYYY:MM:DD HH:MM:SS"
                captured_at = datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
                result["captured_at"] = captured_at.isoformat()
            except ValueError:
                pass
            break

    # --- Aperture (F-number) ---
    tag = tags.get("EXIF FNumber")
    if tag:
        val = _ratio_to_float(tag)
        if val is not None:
            result["aperture"] = round(val, 1)

    # --- Shutter speed ---
    # Prefer ExposureTime (actual duration); fallback to ShutterSpeedValue (APEX)
    tag = tags.get("EXIF ExposureTime")
    if tag:
        result["shutter_speed"] = str(tag).strip()
        # Also compute float for creative intent
        val = _ratio_to_float(tag)
        if val is not None:
            result["_shutter_float"] = val
    else:
        tag = tags.get("EXIF ShutterSpeedValue")
        if tag:
            # APEX: shutter = 2^(-APEX)
            apex = _ratio_to_float(tag)
            if apex is not None:
                import math
                val = 2 ** (-apex)
                result["shutter_speed"] = f"1/{int(round(1/val))}" if val < 1 else str(round(val, 3))
                result["_shutter_float"] = val

    # --- ISO ---
    for iso_tag in ("EXIF ISOSpeedRatings", "EXIF ISO"):
        tag = tags.get(iso_tag)
        if tag:
            try:
                result["iso"] = int(str(tag).strip())
            except ValueError:
                pass
            break

    # --- Focal length ---
    tag = tags.get("EXIF FocalLength")
    if tag:
        val = _ratio_to_float(tag)
        if val is not None:
            result["focal_length"] = round(val, 1)

    # --- Lens model ---
    for lens_tag in ("EXIF LensModel", "EXIF LensSpecification", "MakerNote LensModel"):
        tag = tags.get(lens_tag)
        if tag:
            result["lens_model"] = str(tag).strip()
            break

    # --- Camera body ---
    make = tags.get("Image Make")
    model = tags.get("Image Model")
    if model:
        make_str = str(make).strip() if make else ""
        model_str = str(model).strip()
        # Avoid doubling the make if it's already in the model string
        if make_str and not model_str.lower().startswith(make_str.lower()):
            result["camera_body"] = f"{make_str} {model_str}"
        else:
            result["camera_body"] = model_str

    # --- Flash ---
    tag = tags.get("EXIF Flash")
    if tag:
        flash_str = str(tag).lower()
        result["flash_fired"] = "fired" in flash_str

    # --- Orientation ---
    tag = tags.get("Image Orientation")
    if tag:
        result["orientation"] = str(tag).strip()

    # --- Exposure compensation ---
    tag = tags.get("EXIF ExposureBiasValue")
    if tag:
        val = _ratio_to_float(tag)
        if val is not None:
            result["exposure_compensation"] = round(val, 2)

    # --- White balance ---
    tag = tags.get("EXIF WhiteBalance")
    if tag:
        result["white_balance"] = str(tag).strip()

    # --- GPS ---
    lat_tag = tags.get("GPS GPSLatitude")
    lat_ref = tags.get("GPS GPSLatitudeRef")
    lng_tag = tags.get("GPS GPSLongitude")
    lng_ref = tags.get("GPS GPSLongitudeRef")

    if lat_tag and lat_ref and lng_tag and lng_ref:
        lat = _dms_to_decimal(lat_tag.values, str(lat_ref))
        lng = _dms_to_decimal(lng_tag.values, str(lng_ref))
        if lat is not None and lng is not None:
            result["gps_lat"] = lat
            result["gps_lng"] = lng

    return result


# ---------------------------------------------------------------------------
# Creative context derivation
# ---------------------------------------------------------------------------

def get_season(month: int) -> str:
    """Return season name from month (1-12)."""
    if month in (12, 1, 2):
        return "winter"
    elif month in (3, 4, 5):
        return "spring"
    elif month in (6, 7, 8):
        return "summer"
    else:
        return "autumn"


def get_time_of_day(hour: int) -> str:
    """Classify hour (0-23) into photographic time-of-day categories."""
    if 5 <= hour < 7:
        return "blue_hour_morning"
    elif 7 <= hour < 9:
        return "golden_hour_morning"
    elif 9 <= hour < 16:
        return "midday"
    elif 16 <= hour < 19:
        return "golden_hour_evening"
    elif 19 <= hour < 21:
        return "blue_hour_evening"
    else:
        return "night"


def infer_creative_intent(
    aperture: Optional[float],
    shutter_speed_float: Optional[float],
    focal_length: Optional[float],
) -> str:
    """
    Infer creative intent from camera settings.

    Priority order (most distinctive first):
      1. Long exposure (shutter >= 1s)
      2. Motion freeze (shutter <= 1/1000s)
      3. Shallow DOF / low light (aperture <= 2.0)
      4. Landscape deep focus (aperture >= 8.0 + wide lens)
      5. Standard
    """
    if shutter_speed_float is not None and shutter_speed_float >= 1.0:
        return "long_exposure_intentional"
    if shutter_speed_float is not None and shutter_speed_float <= 0.001:
        return "motion_freeze"
    if aperture is not None and aperture <= 2.0:
        return "shallow_dof_portrait_or_low_light"
    if aperture is not None and aperture >= 8.0 and focal_length is not None and focal_length <= 35:
        return "landscape_deep_focus"
    return "standard"


# ---------------------------------------------------------------------------
# GPS reverse geocoding
# ---------------------------------------------------------------------------

def _reverse_geocode(lat: float, lng: float) -> Optional[str]:
    """
    Attempt offline reverse geocoding via reverse_geocoder.
    Returns a human-readable location string or None.
    Completely non-blocking — errors are silently ignored.
    """
    try:
        import reverse_geocoder as rg
        results = rg.search((lat, lng), mode=1, verbose=False)
        if results:
            r = results[0]
            parts = [r.get("name"), r.get("admin1"), r.get("cc")]
            return ", ".join(p for p in parts if p)
    except Exception as e:
        logger.debug(f"Reverse geocode failed for ({lat},{lng}): {e}")
    return None


# ---------------------------------------------------------------------------
# Full image metadata processing
# ---------------------------------------------------------------------------

def process_image_metadata(image_path: str) -> dict:
    """
    Run full Pass 0 on a single image.
    Returns a metadata dict ready to write to the DB.
    """
    meta = extract_exif(image_path)

    # Derive season + time_of_day from captured_at
    captured_str = meta.get("captured_at")
    if captured_str:
        try:
            dt = datetime.fromisoformat(captured_str)
            meta["season"] = get_season(dt.month)
            meta["time_of_day"] = get_time_of_day(dt.hour)
        except ValueError:
            pass

    # Infer creative intent
    meta["creative_intent"] = infer_creative_intent(
        aperture=meta.get("aperture"),
        shutter_speed_float=meta.get("_shutter_float"),
        focal_length=meta.get("focal_length"),
    )

    # Reverse geocode GPS if available
    if "gps_lat" in meta and "gps_lng" in meta:
        location_name = _reverse_geocode(meta["gps_lat"], meta["gps_lng"])
        if location_name:
            meta["gps_location_name"] = location_name

    # Remove internal keys not destined for the DB
    meta.pop("_shutter_float", None)

    return meta


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

# DB columns that Pass 0 may write (guards against injection via key names)
_PASS0_DB_COLUMNS = {
    "captured_at", "season", "time_of_day", "aperture", "shutter_speed",
    "iso", "focal_length", "lens_model", "camera_body", "flash_fired",
    "orientation", "creative_intent", "gps_lat", "gps_lng",
    "gps_location_name", "exposure_compensation", "white_balance",
}


def process_batch(image_paths: list[Path]) -> int:
    """
    Run Pass 0 on a list of image paths.
    Updates the images table for each image where data was found.
    Returns count of images successfully processed (metadata found).
    """
    processed = 0
    for path in image_paths:
        path_str = str(path)
        try:
            meta = process_image_metadata(path_str)
        except Exception as e:
            logger.error(f"Pass 0 error on {path.name}: {e}")
            continue

        # Only write columns that are in our allowed set and have actual values
        update_fields = {k: v for k, v in meta.items() if k in _PASS0_DB_COLUMNS}
        if not update_fields:
            # No metadata found but still update captured_at to a sentinel
            # so we don't keep retrying files with no EXIF at all
            update_fields = {}

        # Always mark as processed (even if no EXIF) using file mtime as fallback
        if "captured_at" not in update_fields:
            try:
                mtime = Path(path_str).stat().st_mtime
                fallback_dt = datetime.fromtimestamp(mtime)
                update_fields["captured_at"] = fallback_dt.isoformat()
                update_fields["season"] = get_season(fallback_dt.month)
                update_fields["time_of_day"] = get_time_of_day(fallback_dt.hour)
            except Exception:
                # Last resort: use current time so we don't retry indefinitely
                now = datetime.now()
                update_fields["captured_at"] = now.isoformat()
                update_fields["season"] = get_season(now.month)
                update_fields["time_of_day"] = get_time_of_day(now.hour)

        if not update_fields:
            continue

        set_clause = ", ".join(f"{col} = ?" for col in update_fields)
        values = list(update_fields.values()) + [path_str]

        try:
            with get_db() as conn:
                conn.execute(
                    f"UPDATE images SET {set_clause} WHERE file_path = ?",
                    values,
                )
            processed += 1
        except Exception as e:
            logger.error(f"DB update failed for {path.name}: {e}")

    return processed


def process_all_unprocessed(limit: int = 1000) -> int:
    """
    Find all images where captured_at IS NULL (not yet Pass 0 processed).
    Runs process_batch on them.
    Returns total count processed.
    """
    with get_db() as conn:
        rows = conn.execute(
            """SELECT file_path FROM images
               WHERE captured_at IS NULL
               ORDER BY imported_at ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()

    paths = [Path(r["file_path"]) for r in rows]
    if not paths:
        logger.debug("Pass 0: no unprocessed images found")
        return 0

    logger.info(f"Pass 0: processing {len(paths)} unprocessed images")
    count = process_batch(paths)
    logger.info(f"Pass 0: completed {count}/{len(paths)} images")
    return count
