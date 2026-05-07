"""
services/edit_lineage.py

Detect when a newly-ingested image is the Lightroom-edited version of an
existing RAW already in the database. Sets `images.edited_from_id` so future
queries can show before/after score deltas.

Heuristic match:
1. The candidate must be a non-RAW format (TIFF/JPEG/PNG/HEIC) — RAWs are originals.
2. Strip common LR/edit suffixes from the stem ("DSC01571_edit" → "DSC01571").
3. Look for a RAW row in the DB whose stem matches, ranked by:
   a. Same parent dir (most likely)
   b. Sibling dir (LR exports often go to ./edited/ or ../exports/)
   c. Anywhere in the DB (fallback)

Conservative — only links when the stem match is unambiguous.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.database import get_db
# Pure stem-matching helpers moved to lens_core.edit_lineage.detector
# 2026-05-07. Re-imported under the original underscored names so the rest
# of this module's DB-walking logic keeps working unchanged.
from lens_core.edit_lineage.detector import (
    RAW_EXTS as _RAW_EXTS,
    EDIT_EXTS as _EDIT_EXTS,
    normalize_stem as _normalize_stem,
)
import re

# Compatibility: some downstream code may inspect _EDIT_SUFFIX_RE directly.
# Mirror the regex from lens_core (kept local to avoid cross-package private import).
_EDIT_SUFFIX_RE = re.compile(
    r"[-_\s](edit(ed)?|edits|final|export(ed)?|v\d+|v[0-9]+|hires|hi-res|"
    r"web|print|color|bw|b&w|retouched|enhanced)$",
    re.IGNORECASE,
)


def detect_parent_id(file_path: str | Path) -> Optional[int]:
    """If file_path looks like an edit of an existing RAW in the DB, return
    the RAW's image_id. Otherwise None.

    Safe to call from any ingestion path — read-only, returns quickly.
    """
    p = Path(file_path)
    suffix = p.suffix.lower()
    if suffix in _RAW_EXTS:
        # RAWs are never edits.
        return None
    if suffix not in _EDIT_EXTS:
        return None

    stem = p.stem
    base = _normalize_stem(stem)
    if not base or base == stem and not _EDIT_SUFFIX_RE.search(stem):
        # No edit-suffix marker. Still check by exact stem in case the user
        # exports as `<stem>.tiff` next to `<stem>.ARW`.
        base = stem

    if not base:
        return None

    candidates: list[Path] = []
    parent = p.parent
    sibling_dirs = []
    if parent.exists():
        # Sibling subdirs in the same parent that often hold LR exports
        for d in parent.parent.iterdir() if parent.parent.exists() else []:
            if d.is_dir() and d != parent:
                sibling_dirs.append(d)
        # Also check the parent's parent (..)
        sibling_dirs.append(parent.parent)

    raw_exts = list(_RAW_EXTS)

    # Tier 1: same dir, exact base stem with each RAW extension.
    for ext in raw_exts:
        for variant in (ext, ext.upper()):
            cand = parent / f"{base}{variant}"
            candidates.append(cand)

    # Tier 2: sibling dirs.
    for d in sibling_dirs[:8]:  # cap to avoid huge fanout
        for ext in raw_exts:
            for variant in (ext, ext.upper()):
                candidates.append(d / f"{base}{variant}")

    # Filter to candidates whose path exists OR is in the DB.
    with get_db() as conn:
        for cand in candidates:
            row = conn.execute(
                "SELECT id FROM images WHERE file_path = ? LIMIT 1",
                (str(cand),),
            ).fetchone()
            if row:
                return row["id"]

        # Tier 3 fallback: any RAW in the DB with a matching stem (file_name LIKE).
        # Cheap LIKE on the file_name column; we then verify the stem exactly.
        rows = conn.execute(
            """SELECT id, file_path, file_name FROM images
               WHERE file_name LIKE ? AND file_path != ?
               ORDER BY pass3_at DESC NULLS LAST, id ASC LIMIT 25""",
            (f"{base}.%", str(p)),
        ).fetchall()
        for row in rows:
            rp = Path(row["file_path"])
            if rp.suffix.lower() in _RAW_EXTS and rp.stem.lower() == base.lower():
                return row["id"]

    return None


def link_if_edit(image_id: int, file_path: str | Path) -> Optional[int]:
    """Detect lineage and persist the result to images.edited_from_id.

    Returns the parent id if linked, None otherwise. Safe to call multiple
    times — a row that already has edited_from_id set is left alone.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT edited_from_id FROM images WHERE id = ?", (image_id,)
        ).fetchone()
        if row and row["edited_from_id"] is not None:
            return row["edited_from_id"]

    parent_id = detect_parent_id(file_path)
    if parent_id is None or parent_id == image_id:
        return None

    with get_db() as conn:
        conn.execute(
            "UPDATE images SET edited_from_id = ? WHERE id = ?",
            (parent_id, image_id),
        )
    return parent_id


# Score columns surfaced in the side-by-side comparison. Order matters — UI
# renders them in this order. Each entry: (column, label, fmt, higher_is_better)
COMPARE_FIELDS: list[tuple[str, str, str, bool]] = [
    ("cull_score",       "Cull (P1)",       "{:.2f}", True),
    ("blur_score",       "Sharpness (P1)",  "{:.2f}", True),
    ("exposure_score",   "Exposure (P1)",   "{:.2f}", True),
    ("nima_composite",   "NIMA composite",  "{:.2f}", True),
    ("nima_aesthetic",   "NIMA aesthetic",  "{:.2f}", True),
    ("nima_technical",   "NIMA technical",  "{:.2f}", True),
    ("score_composition","Composition",     "{:.2f}", True),
    ("quality_score",    "Quality (P3)",    "{:.2f}", True),
    ("print_score",      "Print score",     "{:.2f}", True),
    ("portfolio_worthy", "Portfolio",       "{}",     True),
    ("print_worthy",     "Print worthy",    "{}",     True),
]


def lineage_for(image_id: int) -> dict:
    """Return a payload describing this image's lineage and side-by-side scores
    against its parent (if any) and its child edits (if any).

    Shape:
        {
          "image_id": int,
          "is_edit": bool,
          "original": {id, file_name, scores...} or None,
          "edits": [{id, file_name, scores...}, ...],   # may be empty
          "self": {id, file_name, scores...},
          "deltas": {field: {original, this, delta} ...}  # only if is_edit
        }
    """
    cols = ", ".join(f[0] for f in COMPARE_FIELDS)
    select_sql = f"""
        SELECT id, file_name, file_path, edited_from_id, {cols}
        FROM images WHERE id = ?
    """
    with get_db() as conn:
        me_row = conn.execute(select_sql, (image_id,)).fetchone()
        if not me_row:
            return {"error": f"image {image_id} not found"}
        me = dict(me_row)

        original = None
        if me.get("edited_from_id"):
            o_row = conn.execute(select_sql, (me["edited_from_id"],)).fetchone()
            if o_row:
                original = dict(o_row)

        edit_rows = conn.execute(
            f"""SELECT id, file_name, file_path, {cols}
                FROM images WHERE edited_from_id = ?
                ORDER BY id ASC""",
            (image_id,),
        ).fetchall()
        edits = [dict(r) for r in edit_rows]

    deltas: dict[str, dict] = {}
    if original:
        for field, label, _fmt, higher_better in COMPARE_FIELDS:
            o = original.get(field)
            t = me.get(field)
            if o is None or t is None:
                continue
            try:
                delta = float(t) - float(o)
            except (TypeError, ValueError):
                # Non-numeric (e.g. portfolio_worthy boolean) — encode as 0/1 diff
                delta = (1 if t else 0) - (1 if o else 0)
            deltas[field] = {
                "label": label,
                "original": o,
                "this": t,
                "delta": delta,
                "higher_is_better": higher_better,
                "improved": (delta > 0) == higher_better and delta != 0,
            }

    return {
        "image_id": image_id,
        "is_edit": bool(me.get("edited_from_id")),
        "self": me,
        "original": original,
        "edits": edits,
        "deltas": deltas,
    }
