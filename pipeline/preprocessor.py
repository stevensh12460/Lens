"""
Resize images to max 1024px longest edge, save as JPEG quality 85.
Every pipeline pass that sends images to Ollama calls this first.
RAW files (CR2, ARW, NEF, etc.) are decoded via rawpy before resizing.
"""
from pathlib import Path

from PIL import Image

from core.config import settings

_MAX_DIM = settings.resize_max_dimension
_QUALITY = 85
_CACHE_DIR = Path("/tmp/lens_preprocessed")
_RAW_EXTENSIONS = {".arw", ".cr2", ".cr3", ".nef", ".raf", ".dng", ".orf", ".rw2", ".pef"}


def get_preprocessed_path(source_path: Path) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Include hash of parent directory to avoid collisions when different
    # folders contain files with the same stem (e.g. DSC_0001.arw in two shoots)
    import hashlib
    dir_hash = hashlib.md5(str(source_path.parent).encode()).hexdigest()[:8]
    return _CACHE_DIR / (f"{source_path.stem}_{dir_hash}_prep.jpg")


def _open_raw_preview(source_path: Path) -> "Image.Image":
    """Embedded JPEG preview from a RAW whose sensor data is damaged.

    Older CR2/ARW files can rot in the raw payload while the full-resolution
    preview stays intact. Scoring the preview beats losing the photo.
    """
    import io
    import rawpy
    with rawpy.imread(str(source_path)) as raw:
        thumb = raw.extract_thumb()
    if thumb.format == rawpy.ThumbFormat.JPEG:
        return Image.open(io.BytesIO(thumb.data)).convert("RGB")
    return Image.fromarray(thumb.data).convert("RGB")


def _open_image(source_path: Path) -> Image.Image:
    """Open any image including RAW formats, return a PIL Image."""
    if source_path.suffix.lower() in _RAW_EXTENSIONS:
        import rawpy
        try:
            with rawpy.imread(str(source_path)) as raw:
                rgb = raw.postprocess(use_camera_wb=True, half_size=True, no_auto_bright=False, output_bps=8)
            return Image.fromarray(rgb)
        except Exception:
            return _open_raw_preview(source_path)
    return Image.open(source_path)


def preprocess(source_path: Path, force: bool = False) -> Path:
    """
    Resize image to max 1024px and return path to the resized JPEG.
    Returns cached version if it already exists and force=False.
    """
    out_path = get_preprocessed_path(source_path)
    if out_path.exists() and not force:
        return out_path

    img = _open_image(source_path)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((_MAX_DIM, _MAX_DIM), Image.LANCZOS)
    img.save(out_path, "JPEG", quality=_QUALITY)

    return out_path
