"""
Pass 2 — Multi-model quality scoring with batched GPU inference.
4-signal ensemble: NIMA technical + LAION aesthetic + composition (8 sub-signals) + EXIF.
Outputs nima_technical, nima_aesthetic, nima_composite (0–10 scale).

GPU signals (NIMA, CLIP) are batched — one forward pass per batch instead of per image.
Composition scoring uses 8 sub-signals with face-aware weighting profiles.
Runs on Apple Silicon MPS.
"""
import json
import logging
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import torch
from PIL import Image

_FILE_TIMEOUT = 120

logger = logging.getLogger("lens.pass2")

from core.config import settings
from core.database import get_db

_DEVICE = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
_MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
_RAW_EXTENSIONS = {".arw", ".cr2", ".cr3", ".nef", ".raf", ".dng", ".orf", ".rw2", ".pef"}

# Composite weights (4 main signals)
_W_TECHNICAL = 0.30
_W_AESTHETIC = 0.35
_W_COMPOSITION = 0.20
_W_EXIF = 0.15

# GPU lock — serializes GPU work between concurrent workers so one does GPU
# while the other does CPU composition. Better than fighting over MPS.
_gpu_lock = threading.Lock()

# Haar cascade for face detection — loaded once, reused
_face_cascade_cache = None

# Composition weighting profiles
_WEIGHTS_FACES = {
    "thirds": 0.10, "golden_ratio": 0.15, "harmony": 0.10, "balance": 0.08,
    "symmetry": 0.07, "visual_weight": 0.10, "face_placement": 0.25, "dof": 0.15,
}
_WEIGHTS_NO_FACES = {
    "thirds": 0.18, "golden_ratio": 0.18, "harmony": 0.15, "balance": 0.15,
    "visual_weight": 0.15, "symmetry": 0.12, "dof": 0.07,
}


# ─── Image loading ────────────────────────────────────────────────────────────


def _open_image(image_path: Path) -> Image.Image:
    """Open any image including RAW formats, return a PIL Image in RGB mode."""
    if image_path.suffix.lower() in _RAW_EXTENSIONS:
        import rawpy
        with rawpy.imread(str(image_path)) as raw:
            rgb = raw.postprocess(use_camera_wb=True, half_size=True, no_auto_bright=False, output_bps=8)
        return Image.fromarray(rgb)
    return Image.open(image_path).convert("RGB")


# ─── Preprocessing ────────────────────────────────────────────────────────────


@dataclass
class _Preprocessed:
    index: int
    path: Path
    cv_arr: Optional[np.ndarray] = None      # 512px-max RGB numpy
    cv_gray: Optional[np.ndarray] = None     # grayscale of cv_arr
    cv_h: int = 0
    cv_w: int = 0
    nima_tensor: Optional[torch.Tensor] = None   # (3,224,224) ImageNet-normed
    clip_tensor: Optional[torch.Tensor] = None   # (3,224,224) CLIP-normed
    error: Optional[str] = None


def _preprocess_image(path: Path, index: int, clip_preprocess) -> _Preprocessed:
    """Load one image and prepare all tensors/arrays needed by every signal."""
    import torchvision.transforms as transforms

    p = _Preprocessed(index=index, path=path)
    try:
        img = _open_image(path)
    except Exception as e:
        p.error = f"load failed: {e}"
        return p

    try:
        # CV array — resize to 512px max for composition signals
        img_arr = np.array(img)
        h, w = img_arr.shape[:2]
        scale = min(512 / max(h, w), 1.0)
        if scale < 1.0:
            img_arr = cv2.resize(img_arr, (int(w * scale), int(h * scale)))
        p.cv_arr = img_arr
        p.cv_h, p.cv_w = img_arr.shape[:2]
        p.cv_gray = cv2.cvtColor(img_arr, cv2.COLOR_RGB2GRAY)

        # NIMA tensor — ImageNet normalization
        nima_transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])
        p.nima_tensor = nima_transform(img)

        # CLIP tensor — CLIP-specific preprocessing
        p.clip_tensor = clip_preprocess(img)

    except Exception as e:
        p.error = f"preprocess failed: {e}"
    finally:
        img.close()

    return p


# ─── Signal 1: NIMA Technical (VGG16, pretrained on AVA via pyiqa) ────────────

_nima_cache = None


def _get_nima():
    global _nima_cache
    if _nima_cache is None:
        import pyiqa
        _nima_cache = pyiqa.create_metric("nima-vgg16-ava", device=_DEVICE)
        logger.info("[pass2] NIMA VGG16-AVA model loaded (pyiqa)")
    return _nima_cache


def _batch_nima(tensors: list[torch.Tensor]) -> list[float]:
    """Batch NIMA inference — one forward pass for all images."""
    model = _get_nima()
    batch = torch.stack(tensors).to(_DEVICE)
    with torch.no_grad():
        scores = model.net(batch)
    return [float(max(0.0, min(10.0, s.item()))) for s in scores]


# ─── Signal 2: LAION Aesthetic Predictor V2 (CLIP + MLP) ─────────────────────

import torch.nn as nn


class _AestheticMLP(nn.Module):
    """MLP head matching christophschuhmann/improved-aesthetic-predictor."""

    def __init__(self) -> None:
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(768, 1024),
            nn.Dropout(0.2),
            nn.Linear(1024, 128),
            nn.Dropout(0.2),
            nn.Linear(128, 64),
            nn.Dropout(0.1),
            nn.Linear(64, 16),
            nn.Linear(16, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.layers(x)


_clip_model_cache = None
_clip_preprocess_cache = None
_aesthetic_mlp_cache: Optional[_AestheticMLP] = None


def _get_aesthetic():
    global _clip_model_cache, _clip_preprocess_cache, _aesthetic_mlp_cache
    if _clip_model_cache is None:
        import os
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        import open_clip
        clip_model, _, preprocess = open_clip.create_model_and_transforms(
            "ViT-L-14", pretrained="openai", device=_DEVICE
        )
        clip_model.eval()
        _clip_model_cache = clip_model
        _clip_preprocess_cache = preprocess
        logger.info("[pass2] CLIP ViT-L/14 loaded")

    if _aesthetic_mlp_cache is None:
        mlp = _AestheticMLP()
        weights_path = _MODELS_DIR / "sac_logos_ava1_l14_linearMSE.pth"
        if not weights_path.exists():
            raise FileNotFoundError(f"LAION aesthetic weights not found at {weights_path}")
        state = torch.load(str(weights_path), map_location="cpu", weights_only=False)
        mlp.load_state_dict(state)
        mlp = mlp.to(_DEVICE)
        mlp.eval()
        _aesthetic_mlp_cache = mlp
        logger.info("[pass2] LAION aesthetic MLP loaded")

    return _clip_model_cache, _clip_preprocess_cache, _aesthetic_mlp_cache


def _batch_aesthetic(tensors: list[torch.Tensor]) -> list[float]:
    """Batch LAION aesthetic inference — one CLIP + MLP forward pass for all images."""
    clip_model, _, mlp = _get_aesthetic()
    batch = torch.stack(tensors).to(_DEVICE)
    with torch.no_grad():
        embeddings = clip_model.encode_image(batch)
        embeddings = embeddings / embeddings.norm(dim=-1, keepdim=True)
        scores = mlp(embeddings.float())
    return [float(max(1.0, min(10.0, s.item()))) for s in scores]


# ─── Signal 3: Enhanced Composition (8 sub-signals) ──────────────────────────


def _get_face_cascade():
    global _face_cascade_cache
    if _face_cascade_cache is None:
        _face_cascade_cache = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
    return _face_cascade_cache


def _compute_saliency(gray: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Spectral residual saliency map. Returns (saliency_map, centroid_x, centroid_y)."""
    h, w = gray.shape[:2]
    gray_f = gray.astype(np.float32)
    dft = cv2.dft(gray_f, flags=cv2.DFT_COMPLEX_OUTPUT)
    magnitude = cv2.magnitude(dft[:, :, 0], dft[:, :, 1])
    log_mag = np.log(magnitude + 1e-10)
    smooth = cv2.blur(log_mag, (3, 3))
    spectral_residual = log_mag - smooth
    phase = cv2.phase(dft[:, :, 0], dft[:, :, 1])
    cos_p, sin_p = np.cos(phase), np.sin(phase)
    exp_sr = np.exp(spectral_residual)
    recon = np.zeros_like(dft)
    recon[:, :, 0] = exp_sr * cos_p
    recon[:, :, 1] = exp_sr * sin_p
    saliency = cv2.idft(recon)
    saliency = cv2.magnitude(saliency[:, :, 0], saliency[:, :, 1])
    saliency = cv2.GaussianBlur(saliency, (9, 9), 2.5)
    sal_range = saliency.max() - saliency.min()
    if sal_range > 0:
        saliency = (saliency - saliency.min()) / sal_range
    else:
        saliency = np.zeros_like(saliency)

    threshold = np.percentile(saliency, 80)
    mask = (saliency > threshold).astype(np.uint8)
    moments = cv2.moments(mask)
    if moments["m00"] > 0:
        cx = moments["m10"] / moments["m00"]
        cy = moments["m01"] / moments["m00"]
    else:
        cx, cy = w / 2.0, h / 2.0

    return saliency, cx, cy


def _s1_thirds(cx: float, cy: float, w: int, h: int) -> float:
    """Rule of thirds: distance from saliency centroid to nearest thirds intersection."""
    thirds_points = [
        (w / 3, h / 3), (2 * w / 3, h / 3),
        (w / 3, 2 * h / 3), (2 * w / 3, 2 * h / 3),
    ]
    min_dist = min(math.hypot(cx - px, cy - py) for px, py in thirds_points)
    max_possible = math.hypot(w / 3, h / 3)
    return max(0.0, 10.0 * (1 - min_dist / max_possible))


def _s2_golden_ratio(cx: float, cy: float, w: int, h: int) -> tuple[float, list[str]]:
    """Golden ratio: phi-line intersections + 4 spiral orientations. Returns (score, notes)."""
    phi = 0.618
    phi_points = [
        (w * (1 - phi), h * (1 - phi)), (w * phi, h * (1 - phi)),
        (w * (1 - phi), h * phi), (w * phi, h * phi),
    ]

    # Score for current orientation
    min_dist = min(math.hypot(cx - px, cy - py) for px, py in phi_points)
    max_possible = math.hypot(w * (1 - phi), h * (1 - phi))
    current_score = max(0.0, 10.0 * (1 - min_dist / max_possible))

    # Test all 4 spiral orientations by transforming the centroid
    orientations = {
        "original": (cx, cy),
        "flipped horizontally": (w - cx, cy),
        "flipped vertically": (cx, h - cy),
        "flipped both": (w - cx, h - cy),
    }
    best_name = "original"
    best_score = current_score
    for name, (ox, oy) in orientations.items():
        dist = min(math.hypot(ox - px, oy - py) for px, py in phi_points)
        s = max(0.0, 10.0 * (1 - dist / max_possible))
        if s > best_score:
            best_score = s
            best_name = name

    notes = []
    if best_name != "original" and (best_score - current_score) > 1.5:
        notes.append(f"Stronger composition if {best_name} — subject aligns better with golden spiral")

    # Check if centroid is close to a phi line but not on it (crop suggestion)
    phi_x_lines = [w * (1 - phi), w * phi]
    phi_y_lines = [h * (1 - phi), h * phi]
    for px in phi_x_lines:
        offset = cx - px
        offset_pct = abs(offset) / w * 100
        if 3 < offset_pct < 12:
            direction = "right" if offset > 0 else "left"
            notes.append(f"Crop {offset_pct:.0f}% from {direction} to align subject with phi line")
            break
    for py in phi_y_lines:
        offset = cy - py
        offset_pct = abs(offset) / h * 100
        if 3 < offset_pct < 12:
            direction = "bottom" if offset > 0 else "top"
            notes.append(f"Crop {offset_pct:.0f}% from {direction} to align subject with phi line")
            break

    return best_score, notes


def _s3_color_harmony(img_arr: np.ndarray) -> float:
    """Color harmony via K-means clustering in CIELab."""
    lab = cv2.cvtColor(img_arr, cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    _, _, centers = cv2.kmeans(lab, 5, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    a_vals = centers[:, 1] - 128
    b_vals = centers[:, 2] - 128
    hues = np.degrees(np.arctan2(b_vals, a_vals)) % 360
    hues_sorted = np.sort(hues)
    diffs = np.diff(hues_sorted)
    if len(diffs) > 0:
        diffs = np.append(diffs, 360 - hues_sorted[-1] + hues_sorted[0])
    hue_range = hues_sorted[-1] - hues_sorted[0]
    if hue_range > 180:
        hue_range = 360 - hue_range
    if hue_range < 60:
        return 8.5  # analogous
    elif any(abs(d - 180) < 30 for d in diffs):
        return 8.0  # complementary
    elif any(abs(d - 120) < 20 for d in diffs):
        return 7.5  # triadic
    else:
        return 5.0 + min(3.0, (180 - hue_range) / 60)


def _s4_visual_balance(gray: np.ndarray, w: int, h: int) -> float:
    """Visual balance: entropy comparison across halves."""
    def _entropy(region):
        hist = cv2.calcHist([region.astype(np.uint8)], [0], None, [64], [0, 256])
        hist = hist.flatten() / (hist.sum() + 1e-10)
        hist = hist[hist > 0]
        return -np.sum(hist * np.log2(hist))

    left_e = _entropy(gray[:, :w // 2])
    right_e = _entropy(gray[:, w // 2:])
    top_e = _entropy(gray[:h // 2, :])
    bottom_e = _entropy(gray[h // 2:, :])

    lr_balance = 1 - abs(left_e - right_e) / max(left_e, right_e, 1e-10)
    tb_balance = 1 - abs(top_e - bottom_e) / max(top_e, bottom_e, 1e-10)
    return (lr_balance + tb_balance) / 2 * 10


def _s5_symmetry(gray: np.ndarray) -> float:
    """Symmetry via SSIM — horizontal and vertical flip, take best."""
    from skimage.metrics import structural_similarity as ssim

    gray_u8 = gray.astype(np.uint8) if gray.dtype != np.uint8 else gray
    h, w = gray_u8.shape[:2]

    # Horizontal symmetry — compare left half with flipped right half
    half_w = w // 2
    left = gray_u8[:, :half_w]
    right = gray_u8[:, w - half_w:]
    right_flipped = np.fliplr(right)
    h_ssim = ssim(left, right_flipped, data_range=255)

    # Vertical symmetry — compare top half with flipped bottom half
    half_h = h // 2
    top = gray_u8[:half_h, :]
    bottom = gray_u8[h - half_h:, :]
    bottom_flipped = np.flipud(bottom)
    v_ssim = ssim(top, bottom_flipped, data_range=255)

    best = max(h_ssim, v_ssim)
    # Map SSIM to 0-10: >0.85 = 9-10, 0.6-0.85 = 6-8.5, <0.4 = 3-5
    if best > 0.85:
        return 8.5 + (best - 0.85) / 0.15 * 1.5
    elif best > 0.6:
        return 6.0 + (best - 0.6) / 0.25 * 2.5
    elif best > 0.4:
        return 4.0 + (best - 0.4) / 0.2 * 2.0
    else:
        return 3.0 + best / 0.4 * 1.0


def _s6_visual_weight(gray: np.ndarray, cx: float, cy: float, w: int, h: int) -> float:
    """Visual weight (edge center of mass) + leading lines (Hough)."""
    # Edge map — Sobel magnitude
    sobelx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    sobely = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    edge_mag = np.sqrt(sobelx ** 2 + sobely ** 2)

    # Center of mass of edge map
    total = edge_mag.sum()
    if total > 0:
        ys, xs = np.mgrid[:gray.shape[0], :gray.shape[1]]
        ecx = (xs * edge_mag).sum() / total
        ecy = (ys * edge_mag).sum() / total
    else:
        ecx, ecy = w / 2.0, h / 2.0

    # Score: how close is edge CoM to the saliency centroid (subject)?
    dist_to_subject = math.hypot(ecx - cx, ecy - cy)
    max_dist = math.hypot(w, h) / 2
    weight_score = max(0.0, 10.0 * (1 - dist_to_subject / max_dist))

    # Leading lines via probabilistic Hough transform
    gray_u8 = gray.astype(np.uint8) if gray.dtype != np.uint8 else gray
    edges = cv2.Canny(gray_u8, 50, 150)
    min_len = int(min(w, h) * 0.15)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=50,
                             minLineLength=min_len, maxLineGap=10)
    line_score = 5.0  # neutral default
    if lines is not None and len(lines) > 0:
        # Check how many lines "point toward" the saliency centroid
        converging = 0
        for line in lines[:20]:
            x1, y1, x2, y2 = line[0]
            # Extend line and check if it passes near the centroid
            dx, dy = x2 - x1, y2 - y1
            line_len = math.hypot(dx, dy)
            if line_len < 1:
                continue
            # Distance from centroid to the infinite line
            dist = abs(dy * cx - dx * cy + x2 * y1 - y2 * x1) / line_len
            if dist < max(w, h) * 0.1:
                converging += 1
        ratio = converging / min(len(lines), 20)
        line_score = 4.0 + ratio * 6.0  # 4-10 based on convergence

    return (weight_score + line_score) / 2


def _s7_face_placement(gray: np.ndarray, w: int, h: int) -> tuple[float, list[str], list[tuple]]:
    """Face detection + placement scoring relative to golden ratio / thirds points.
    Returns (score, notes, face_rects)."""
    cascade = _get_face_cascade()
    gray_u8 = gray.astype(np.uint8) if gray.dtype != np.uint8 else gray
    faces = cascade.detectMultiScale(gray_u8, scaleFactor=1.1, minNeighbors=6,
                                      minSize=(int(max(w, h) * 0.05), int(max(w, h) * 0.05)))

    if faces is None or len(faces) == 0:
        return 5.0, [], []

    face_rects = [(int(x), int(y), int(fw), int(fh)) for x, y, fw, fh in faces]

    # Power points — golden ratio + thirds
    phi = 0.618
    power_points = [
        (w / 3, h / 3), (2 * w / 3, h / 3),
        (w / 3, 2 * h / 3), (2 * w / 3, 2 * h / 3),
        (w * (1 - phi), h * (1 - phi)), (w * phi, h * (1 - phi)),
        (w * (1 - phi), h * phi), (w * phi, h * phi),
    ]

    # Score primary face (largest)
    largest = max(face_rects, key=lambda f: f[2] * f[3])
    face_cx = largest[0] + largest[2] / 2
    face_cy = largest[1] + largest[3] / 2

    min_dist = min(math.hypot(face_cx - px, face_cy - py) for px, py in power_points)
    max_possible = math.hypot(w / 3, h / 3)
    norm_dist = min_dist / max_possible

    if norm_dist < 0.05:
        score = 9.5
    elif norm_dist < 0.10:
        score = 8.0 + (0.10 - norm_dist) / 0.05 * 1.5
    elif norm_dist < 0.20:
        score = 6.0 + (0.20 - norm_dist) / 0.10 * 2.0
    elif norm_dist < 0.40:
        score = 4.0 + (0.40 - norm_dist) / 0.20 * 2.0
    else:
        score = 2.0 + (1.0 - min(norm_dist, 1.0)) * 2.0

    # If multiple faces, also score centroid of all faces
    if len(face_rects) > 1:
        all_cx = sum(f[0] + f[2] / 2 for f in face_rects) / len(face_rects)
        all_cy = sum(f[1] + f[3] / 2 for f in face_rects) / len(face_rects)
        group_dist = min(math.hypot(all_cx - px, all_cy - py) for px, py in power_points)
        group_norm = group_dist / max_possible
        group_score = max(0.0, 10.0 * (1 - group_norm))
        score = max(score, group_score)

    notes = []
    if norm_dist > 0.10:
        # Find which direction to move
        best_point = min(power_points, key=lambda p: math.hypot(face_cx - p[0], face_cy - p[1]))
        dx_pct = (face_cx - best_point[0]) / w * 100
        dy_pct = (face_cy - best_point[1]) / h * 100
        if abs(dx_pct) > 3:
            direction = "right" if dx_pct > 0 else "left"
            notes.append(f"Crop {abs(dx_pct):.0f}% from {direction} to place face on power point")
        if abs(dy_pct) > 3:
            direction = "bottom" if dy_pct > 0 else "top"
            notes.append(f"Crop {abs(dy_pct):.0f}% from {direction} to place face on power point")

    # Centered face note
    center_dist = math.hypot(face_cx - w / 2, face_cy - h / 2) / max_possible
    if center_dist < 0.08 and norm_dist > 0.15:
        notes.append("Subject centered — try rule-of-thirds placement for more dynamic composition")

    return score, notes, face_rects


def _s8_dof(gray: np.ndarray, face_rects: list[tuple], w: int, h: int) -> float:
    """Depth of field: Laplacian variance ratio between subject and background."""
    gray_u8 = gray.astype(np.uint8) if gray.dtype != np.uint8 else gray

    # Subject region — face bbox if available, otherwise center 40%
    if face_rects:
        largest = max(face_rects, key=lambda f: f[2] * f[3])
        fx, fy, fw, fh = largest
        # Expand face region slightly for upper body
        pad_x, pad_y = int(fw * 0.3), int(fh * 0.5)
        sx1 = max(0, fx - pad_x)
        sy1 = max(0, fy - pad_y)
        sx2 = min(w, fx + fw + pad_x)
        sy2 = min(h, fy + fh + int(fh * 1.0))
    else:
        margin_x = int(w * 0.3)
        margin_y = int(h * 0.3)
        sx1, sy1 = margin_x, margin_y
        sx2, sy2 = w - margin_x, h - margin_y

    subject = gray_u8[sy1:sy2, sx1:sx2]
    if subject.size == 0:
        return 5.0

    # Background — everything outside subject region
    bg_mask = np.ones_like(gray_u8, dtype=bool)
    bg_mask[sy1:sy2, sx1:sx2] = False
    background = gray_u8[bg_mask]
    if background.size == 0:
        return 5.0

    subject_var = cv2.Laplacian(subject, cv2.CV_64F).var()
    # Background needs to be 2D for Laplacian — use periphery strips
    periphery_regions = []
    if sy1 > 20:
        periphery_regions.append(gray_u8[:sy1, :])
    if sy2 < h - 20:
        periphery_regions.append(gray_u8[sy2:, :])
    if sx1 > 20:
        periphery_regions.append(gray_u8[:, :sx1])
    if sx2 < w - 20:
        periphery_regions.append(gray_u8[:, sx2:])

    if not periphery_regions:
        return 5.0

    bg_vars = [cv2.Laplacian(r, cv2.CV_64F).var() for r in periphery_regions if r.size > 0]
    if not bg_vars:
        return 5.0
    bg_var = np.mean(bg_vars)

    ratio = subject_var / (bg_var + 1e-6)

    if ratio > 5.0:
        return 10.0
    elif ratio > 3.0:
        return 8.0 + (ratio - 3.0) / 2.0
    elif ratio > 2.0:
        return 7.0 + (ratio - 2.0)
    elif ratio > 1.5:
        return 6.0 + (ratio - 1.5) * 2.0
    elif ratio > 1.0:
        return 4.0 + (ratio - 1.0) * 4.0
    else:
        return 3.0 + ratio


def _score_composition_enhanced(cv_arr: np.ndarray, cv_gray: np.ndarray,
                                 cv_h: int, cv_w: int) -> tuple[float, dict, list[str]]:
    """Enhanced composition scoring with 8 sub-signals and face-aware weighting.
    Returns (composite_score, sub_scores_dict, notes_list)."""
    # Shared saliency map
    saliency, cx, cy = _compute_saliency(cv_gray)

    # S1: Rule of thirds
    thirds = _s1_thirds(cx, cy, cv_w, cv_h)

    # S2: Golden ratio + spiral orientations
    golden, golden_notes = _s2_golden_ratio(cx, cy, cv_w, cv_h)

    # S3: Color harmony
    harmony = _s3_color_harmony(cv_arr)

    # S4: Visual balance
    balance = _s4_visual_balance(cv_gray, cv_w, cv_h)

    # S5: Symmetry
    symmetry = _s5_symmetry(cv_gray)

    # S6: Visual weight & leading lines
    visual_weight = _s6_visual_weight(cv_gray, cx, cy, cv_w, cv_h)

    # S7: Face-aware placement
    face_score, face_notes, face_rects = _s7_face_placement(cv_gray, cv_w, cv_h)

    # S8: Depth of field
    dof = _s8_dof(cv_gray, face_rects, cv_w, cv_h)

    # Select weighting profile based on face detection
    has_faces = len(face_rects) > 0
    weights = _WEIGHTS_FACES if has_faces else _WEIGHTS_NO_FACES

    sub_scores = {
        "thirds": round(float(thirds), 2),
        "golden_ratio": round(float(golden), 2),
        "harmony": round(float(harmony), 2),
        "balance": round(float(balance), 2),
        "symmetry": round(float(symmetry), 2),
        "visual_weight": round(float(visual_weight), 2),
        "face_placement": round(float(face_score), 2),
        "dof": round(float(dof), 2),
        "has_faces": has_faces,
        "profile": "faces" if has_faces else "no_faces",
    }

    # Weighted composite
    composite = sum(sub_scores.get(k, 5.0) * v for k, v in weights.items())
    composite = max(0.0, min(10.0, composite))

    # Collect and prioritize notes (max 3)
    all_notes = face_notes + golden_notes
    # Add DOF note for portraits with flat DOF
    if has_faces and dof < 5.0:
        all_notes.append("Subject and background have similar sharpness — wider aperture would add separation")

    return composite, sub_scores, all_notes[:3]


# ─── Signal 4: EXIF Bonus ────────────────────────────────────────────────────


def _score_exif(image_path: Path) -> float:
    """EXIF-derived score from aperture and ISO already in DB. Returns 0-10.
    JPG/PNG exports get 7.5 — human-curated and edited, strongest quality proxy."""
    if image_path.suffix.lower() in {".jpg", ".jpeg", ".png", ".tif", ".tiff"}:
        return 7.5

    with get_db() as conn:
        row = conn.execute(
            "SELECT aperture, iso FROM images WHERE file_path = ?",
            (str(image_path),),
        ).fetchone()

    if not row:
        return 5.0

    base = 5.0
    aperture = row["aperture"]
    iso = row["iso"]

    if aperture:
        try:
            f = float(aperture)
            if 4.0 <= f <= 8.0:
                base += 2.5
            elif 2.8 <= f < 4.0 or 8.0 < f <= 11.0:
                base += 1.5
            elif 1.4 <= f < 2.8 or 11.0 < f <= 16.0:
                base += 0.5
        except (ValueError, TypeError):
            pass

    if iso:
        try:
            iso_val = int(iso)
            if iso_val <= 400:
                base += 2.5
            elif iso_val <= 1600:
                base += 1.5
            elif iso_val <= 3200:
                base += 0.5
            elif iso_val <= 6400:
                base -= 0.5
            else:
                base -= 1.0
        except (ValueError, TypeError):
            pass

    return float(max(0.0, min(10.0, base)))


# ─── Batch scoring pipeline ──────────────────────────────────────────────────


def score_image(image_path: Path) -> dict:
    """Score a single image. Convenience wrapper — uses batch pipeline internally."""
    results = process_batch([image_path])
    if results and not results[0].get("error"):
        return results[0]
    raise RuntimeError(results[0].get("error", "unknown error"))


def process_image(image_path: Path) -> dict:
    """Score image and write results to DB. Convenience wrapper."""
    return process_batch([image_path])[0]


def process_batch(image_paths: list[Path]) -> list[dict]:
    """Score a batch with batched GPU inference and enhanced composition.

    Phase 1: Load & preprocess all images (tensors + CV arrays)
    Phase 2: GPU batch — 1 NIMA forward pass, 1 CLIP forward pass (with gpu_lock)
    Phase 3: CPU — enhanced composition (8 sub-signals) + EXIF per image
    Phase 4: Combine scores & batch DB write
    """
    if not image_paths:
        return []

    # Ensure models are loaded (needed for CLIP preprocess fn)
    _, clip_preprocess, _ = _get_aesthetic()

    # ── Phase 1: Load & preprocess ──
    preprocessed = []
    for i, path in enumerate(image_paths):
        try:
            p = _preprocess_image(path, i, clip_preprocess)
            preprocessed.append(p)
        except Exception as e:
            preprocessed.append(_Preprocessed(index=i, path=path, error=str(e)))

    valid = [p for p in preprocessed if p.error is None]
    if not valid:
        return [{"file_path": str(p.path), "error": p.error} for p in preprocessed]

    # ── Phase 2: GPU batch inference (with lock) ──
    nima_scores = {}
    aesthetic_scores = {}

    with _gpu_lock:
        try:
            nima_results = _batch_nima([p.nima_tensor for p in valid])
            for p, s in zip(valid, nima_results):
                nima_scores[p.index] = s
        except Exception as e:
            logger.warning(f"[pass2] NIMA batch failed, falling back to per-image: {e}")
            for p in valid:
                try:
                    nima_scores[p.index] = _batch_nima([p.nima_tensor])[0]
                except Exception:
                    nima_scores[p.index] = 5.0

        try:
            aesthetic_results = _batch_aesthetic([p.clip_tensor for p in valid])
            for p, s in zip(valid, aesthetic_results):
                aesthetic_scores[p.index] = s
        except Exception as e:
            logger.warning(f"[pass2] Aesthetic batch failed, falling back to per-image: {e}")
            for p in valid:
                try:
                    aesthetic_scores[p.index] = _batch_aesthetic([p.clip_tensor])[0]
                except Exception:
                    aesthetic_scores[p.index] = 5.0

    # ── Phase 3: CPU signals (composition + EXIF) ──
    composition_results = {}
    exif_scores = {}

    for p in valid:
        try:
            comp, comp_sub, comp_notes = _score_composition_enhanced(
                p.cv_arr, p.cv_gray, p.cv_h, p.cv_w
            )
            composition_results[p.index] = (comp, comp_sub, comp_notes)
        except Exception as e:
            logger.warning(f"[pass2] Composition failed for {p.path.name}: {e}")
            composition_results[p.index] = (5.0, {}, [])

        exif_scores[p.index] = _score_exif(p.path)

    # ── Phase 4: Combine & batch DB write ──
    results = []
    now = datetime.utcnow().isoformat()

    with get_db() as conn:
        for p in valid:
            tech = nima_scores.get(p.index, 5.0)
            aest = aesthetic_scores.get(p.index, 5.0)
            comp, comp_sub, comp_notes = composition_results.get(p.index, (5.0, {}, []))
            exif = exif_scores.get(p.index, 5.0)

            composite = (
                tech * _W_TECHNICAL
                + aest * _W_AESTHETIC
                + comp * _W_COMPOSITION
                + exif * _W_EXIF
            )
            composite = max(0.0, min(10.0, composite))

            conn.execute(
                """UPDATE images SET nima_technical = ?, nima_aesthetic = ?,
                   nima_composite = ?, score_composition = ?, score_exif = ?,
                   composition_notes = ?, composition_sub = ?,
                   pass2_at = ? WHERE file_path = ?""",
                (round(tech, 3), round(aest, 3), round(composite, 3),
                 round(comp, 3), round(exif, 3),
                 json.dumps(comp_notes[:3]) if comp_notes else None,
                 json.dumps(comp_sub) if comp_sub else None,
                 now, str(p.path)),
            )

            results.append({
                "file_path": str(p.path),
                "nima_technical": round(tech, 3),
                "nima_aesthetic": round(aest, 3),
                "nima_composite": round(composite, 3),
                "score_composition": round(comp, 3),
                "score_exif": round(exif, 3),
            })

    # Add failed images
    for p in preprocessed:
        if p.error is not None:
            results.append({"file_path": str(p.path), "error": p.error})

    return results


def get_eligible_images(limit: int = 500) -> list[Path]:
    """Fetch images that passed Pass 1 but haven't been scored yet."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT file_path FROM images
               WHERE pass1_status = 'pass' AND pass2_at IS NULL
               ORDER BY imported_at LIMIT ?""",
            (limit,),
        ).fetchall()
    return [Path(r["file_path"]) for r in rows]
