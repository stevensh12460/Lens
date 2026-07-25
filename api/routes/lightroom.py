from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from zoneinfo import ZoneInfo
import json

from core.database import get_db

router = APIRouter()

ET = ZoneInfo("America/New_York")


def _now_et() -> str:
    """Eastern, timezone-aware. Never use naive utcnow() in this codebase."""
    return datetime.now(ET).isoformat()


# ---------------------------------------------------------------------------
# Existing models (unchanged)
# ---------------------------------------------------------------------------

class LRSyncPayload(BaseModel):
    file_path: str
    pick_flag: Optional[str] = None   # "pick", "reject", "unflagged"
    color_label: Optional[str] = None
    star_rating: Optional[int] = None


class LRBatchSync(BaseModel):
    images: list[LRSyncPayload]


# ---------------------------------------------------------------------------
# New Phase-5 models
# ---------------------------------------------------------------------------

class LRRatingItem(BaseModel):
    file_path: str
    lr_rating: Optional[int] = None        # 0-5 stars
    lr_pick: Optional[str] = None          # "pick", "reject", "unflagged"
    lr_color_label: Optional[str] = None
    lr_keywords: Optional[List[str]] = None


class LRRatingsBatch(BaseModel):
    ratings: List[LRRatingItem]


class LRSingleRating(BaseModel):
    file_path: str
    lr_rating: Optional[int] = None
    lr_pick: Optional[str] = None
    lr_color_label: Optional[str] = None
    lr_keywords: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_trust_score(lr_rating, nima_composite, quality_score) -> float:
    """
    trust_score = lr_rating * 2 + nima_composite + quality_score, normalised 0-10.
    Max raw: 5*2 + 10 + 10 = 30 → scale to 10.
    """
    r = (lr_rating or 0) * 2
    n = nima_composite or 0
    q = quality_score or 0
    raw = r + n + q
    return round(min(raw / 30.0 * 10.0, 10.0), 4)


def _apply_rating_update(conn, item: LRRatingItem):
    """
    Apply one LRRatingItem to the DB. Returns a dict with action flags:
      promoted_to_portfolio, rejected
    """
    now = _now_et()
    keywords_json = json.dumps(item.lr_keywords) if item.lr_keywords is not None else None

    # Ensure the row exists
    conn.execute(
        "INSERT OR IGNORE INTO images (file_path, file_name) VALUES (?, ?)",
        (item.file_path, item.file_path.split("/")[-1]),
    )

    # Fetch current values needed for trust_score and business logic
    row = conn.execute(
        """SELECT nima_composite, quality_score, portfolio_worthy, pass1_status
           FROM images WHERE file_path = ?""",
        (item.file_path,),
    ).fetchone()

    nima_composite = row["nima_composite"] if row else None
    quality_score  = row["quality_score"]  if row else None
    portfolio_worthy = bool(row["portfolio_worthy"]) if row else False

    trust = _compute_trust_score(item.lr_rating, nima_composite, quality_score)

    # Business logic flags
    promoted = False
    rejected  = False

    new_portfolio_worthy = portfolio_worthy
    new_pass1_status     = None  # only set if pick == reject

    if item.lr_rating is not None and item.lr_rating >= 4 and not portfolio_worthy:
        new_portfolio_worthy = True
        promoted = True

    if item.lr_pick == "reject":
        new_pass1_status = "fail"
        rejected = True

    # Build SET clause dynamically so we only touch columns that have values
    updates = {
        "lr_rating":      item.lr_rating,
        "lr_pick":        item.lr_pick,
        "lr_color_label": item.lr_color_label,
        "lr_keywords":    keywords_json,
        "lr_synced_at":   now,
        "trust_score":    trust,
    }
    # Mirror into the legacy column set. pipeline/priority_queue.py reads
    # lr_pick while /picks historically read lr_pick_flag, so writing only one
    # let them silently disagree. Only mirror values actually supplied so we
    # never blank an existing rating.
    if item.lr_rating is not None:
        updates["lr_star_rating"] = item.lr_rating
    if item.lr_pick is not None:
        updates["lr_pick_flag"] = item.lr_pick

    if promoted:
        updates["portfolio_worthy"] = True
    if new_pass1_status:
        updates["pass1_status"] = new_pass1_status

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values     = list(updates.values()) + [item.file_path]
    conn.execute(f"UPDATE images SET {set_clause} WHERE file_path = ?", values)

    return {"promoted": promoted, "rejected": rejected}


# ---------------------------------------------------------------------------
# Existing endpoints (unchanged)
# ---------------------------------------------------------------------------

@router.post("/sync")
def sync_single(payload: LRSyncPayload):
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM images WHERE file_path = ?", (payload.file_path,)
        ).fetchone()
        if not row:
            # Auto-register image if not seen before
            conn.execute(
                "INSERT OR IGNORE INTO images (file_path, file_name) VALUES (?, ?)",
                (payload.file_path, payload.file_path.split("/")[-1]),
            )
        conn.execute(
            """UPDATE images SET lr_pick_flag = ?, lr_color_label = ?,
               lr_star_rating = ?, lr_synced_at = ? WHERE file_path = ?""",
            (payload.pick_flag, payload.color_label, payload.star_rating,
             _now_et(), payload.file_path),
        )
        return {"status": "synced", "file_path": payload.file_path}


@router.post("/sync/batch")
def sync_batch(batch: LRBatchSync):
    synced = 0
    with get_db() as conn:
        for item in batch.images:
            conn.execute(
                "INSERT OR IGNORE INTO images (file_path, file_name) VALUES (?, ?)",
                (item.file_path, item.file_path.split("/")[-1]),
            )
            conn.execute(
                """UPDATE images SET lr_pick_flag = ?, lr_color_label = ?,
                   lr_star_rating = ?, lr_synced_at = ? WHERE file_path = ?""",
                (item.pick_flag, item.color_label, item.star_rating,
                 _now_et(), item.file_path),
            )
            synced += 1
    return {"synced": synced}


@router.get("/picks")
def get_picks(min_stars: int = 0):
    """
    Picks as Lightroom sees them. Reads the current lr_pick / lr_rating columns
    (the ones pipeline/priority_queue.py uses) and falls back to the legacy
    lr_pick_flag / lr_star_rating so historical rows still resolve.
    """
    with get_db() as conn:
        rows = conn.execute(
            """SELECT file_path, file_name,
                      COALESCE(lr_pick, lr_pick_flag)     AS lr_pick,
                      lr_color_label,
                      COALESCE(lr_rating, lr_star_rating) AS lr_rating,
                      nima_composite, genre, trust_score
               FROM images
               WHERE COALESCE(lr_pick, lr_pick_flag) = 'pick'
                 AND (COALESCE(lr_rating, lr_star_rating) IS NULL
                      OR COALESCE(lr_rating, lr_star_rating) >= ?)
               ORDER BY COALESCE(lr_rating, lr_star_rating) DESC,
                        nima_composite DESC""",
            (min_stars,),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Phase-5 endpoints
# ---------------------------------------------------------------------------

@router.post("/sync-ratings")
def sync_ratings(batch: LRRatingsBatch):
    """
    Batch-sync LR ratings, picks, labels and keywords.
    Recalculates trust_score; auto-promotes to portfolio; marks rejects.
    """
    updated = promoted_count = rejected_count = 0
    with get_db() as conn:
        for item in batch.ratings:
            result = _apply_rating_update(conn, item)
            updated += 1
            if result["promoted"]:
                promoted_count += 1
            if result["rejected"]:
                rejected_count += 1
    return {
        "updated":               updated,
        "promoted_to_portfolio": promoted_count,
        "rejected":              rejected_count,
    }


@router.post("/sync-single")
def sync_single_rating(payload: LRSingleRating):
    """
    Sync one image's LR metadata immediately. Returns the updated image record.
    """
    item = LRRatingItem(
        file_path=payload.file_path,
        lr_rating=payload.lr_rating,
        lr_pick=payload.lr_pick,
        lr_color_label=payload.lr_color_label,
    )
    with get_db() as conn:
        _apply_rating_update(conn, item)
        row = conn.execute(
            """SELECT id, file_path, file_name, lr_rating, lr_pick, lr_color_label,
                      lr_keywords, trust_score, portfolio_worthy, pass1_status,
                      nima_composite, quality_score, genre, lr_synced_at
               FROM images WHERE file_path = ?""",
            (payload.file_path,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Image not found after sync")
        return dict(row)


@router.get("/unsynced")
def get_unsynced():
    """
    Returns images that have completed pass3 but have never been synced back to LR.
    The plugin uses this to know which paths need attention.
    """
    with get_db() as conn:
        rows = conn.execute(
            """SELECT file_path, file_name, nima_composite, quality_score,
                      portfolio_worthy, genre, mood, tags, caption_draft,
                      pass3_at
               FROM images
               WHERE lr_synced_at IS NULL
                 AND pass3_at IS NOT NULL
               ORDER BY pass3_at DESC""",
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Results flowing DOWN into Lightroom
#
# /unsynced is gated on `lr_synced_at IS NULL`, which is the wrong semantic for
# a repeatable pull. These endpoints can be re-run any time.
# ---------------------------------------------------------------------------

# Tier bands anchored to the ACTUAL score distribution, not the theoretical
# 0-10 range. Measured over 171,419 scored images: min 4.59, max 7.33, mean
# 6.00, and tightly clustered (50th pct 5.99, 95th 6.52, 99th 6.68).
#
# The old bands (Exceptional 7.5+, Cull <4.5) sat outside the real range, so
# two of the five tiers could never match anything. These are percentile
# anchored instead, which makes the top tier a genuine "best of":
#   Exceptional = top 1%    Strong = top 5%
#   Solid       = top 25%   Weak   = top 50%    Low = bottom 50%
_TIER_BANDS = (
    (6.68, "Exceptional"),
    (6.52, "Strong"),
    (6.22, "Solid"),
    (5.99, "Weak"),
)

_RESULT_COLS = """file_path, file_name, nima_composite, quality_score, genre,
                  portfolio_worthy, print_worthy, content_ready, posted_at,
                  composition_notes, print_notes, description, trust_score,
                  lr_rating, pass2_at, pass3_at, pass1_status, is_duplicate,
                  composition_sub"""

# Composition dimensions considered when picking an image's weak point.
# SYMMETRY IS DELIBERATELY EXCLUDED: it is the lowest score on 76.6% of the
# library, because most photography simply isn't symmetrical. Low symmetry is
# not a fault, so including it made the field meaningless.
_WEAKNESS_DIMS = ("thirds", "golden_ratio", "harmony", "balance",
                  "visual_weight", "face_placement", "dof")

# Only call a dimension weak if it is actually weak. Without this floor the
# field just names each image's relative minimum, which is always something.
_WEAKNESS_FLOOR = 5.0


def _weakness_for(row) -> str:
    """The one composition dimension genuinely dragging an image down, or ''."""
    raw = row["composition_sub"]
    if not raw:
        return ""
    try:
        sub = json.loads(raw)
    except (ValueError, TypeError):
        return ""
    vals = {k: sub[k] for k in _WEAKNESS_DIMS
            if isinstance(sub.get(k), (int, float))}
    if not vals:
        return ""
    worst = min(vals, key=vals.get)
    return worst if vals[worst] < _WEAKNESS_FLOOR else ""


def _tier_for(score) -> Optional[str]:
    if score is None:
        return None
    for floor, name in _TIER_BANDS:
        if score >= floor:
            return name
    # "Low", not "Cull" — every image here already survived pass1 culling, so
    # calling it a cull contradicts the pipeline.
    return "Low"


def _status_for(row) -> str:
    # Surface pass1 cull outcomes first — a duplicate or culled frame has no
    # score, and knowing that inside Lightroom is far more useful than a blank.
    if row["pass1_status"] == "missing":
        # File is gone from disk (folders were reorganised on /Volumes/8TB).
        # These were previously indistinguishable from genuinely unprocessed
        # images, which made the Pending count wrong by ~45,000.
        return "Missing"
    if row["pass1_status"] == "corrupt":
        # File is on disk but no decoder can read it. Most are full-size raws
        # whose headers have been scrambled to zeros or random bytes — silent
        # bit-rot, not a LENS limitation. Worth seeing in Lightroom so these
        # can be re-sourced from another backup.
        return "Corrupt"
    if row["pass1_status"] == "video":
        return "Video"
    if row["pass1_status"] == "sidecar":
        # macOS AppleDouble "._" resource fork, not a photograph.
        return "Sidecar"
    if row["is_duplicate"] or row["pass1_status"] == "duplicate":
        # NOT a redundant copy. pass1 dedup is perceptual (phash), so this is a
        # near-identical frame from a burst — a genuinely different exposure
        # that pass2 never scored. Measured 2026-07-24: 280 of 300 sampled
        # pairs differ in file size, 71% sit in the same folder as their
        # keeper with consecutive frame numbers, only 8% share a filename.
        # Labelling these "Duplicate" in Lightroom invites deleting real work.
        return "Burst"
    if row["pass1_status"] == "fail":
        return "Culled"
    if row["posted_at"]:
        return "Posted"
    if row["print_worthy"]:
        return "Print"
    if row["portfolio_worthy"]:
        return "Portfolio"
    if row["content_ready"]:
        return "Ready"
    # "Scored" must actually mean scored. Previously this was the catch-all,
    # so ~45,500 images LENS had never analysed were labelled Scored, which
    # made any collection built on it untrustworthy.
    if row["nima_composite"] is None:
        return "Pending"
    return "Scored"


def _note_for(row) -> str:
    """One readable line for Lightroom's metadata panel (it renders plain text)."""
    raw = row["composition_notes"]
    if raw:
        try:
            notes = json.loads(raw)
            if isinstance(notes, list) and notes:
                return str(notes[0])[:180]
        except (ValueError, TypeError):
            pass
    for key in ("print_notes", "description"):
        val = row[key]
        if val:
            return str(val)[:180]
    return ""


def _result_row(row) -> dict:
    score = row["nima_composite"]
    return {
        "file_path":        row["file_path"],
        "file_name":        row["file_name"],
        "lens_score":       round(score, 2) if score is not None else None,
        "tier":             _tier_for(score),
        "status":           _status_for(row),
        "note":             _note_for(row),
        "weakness":         _weakness_for(row),
        "genre":            row["genre"],
        "portfolio_worthy": bool(row["portfolio_worthy"]),
        "print_worthy":     bool(row["print_worthy"]),
        "trust_score":      row["trust_score"],
        "lr_rating":        row["lr_rating"],
    }


def _tsv(rows: list) -> str:
    """
    Tab-separated representation for the Lightroom plugin.

    Lightroom's Lua has no dependable JSON parser (the plugin's own decoder is a
    flat scraper that cannot represent an array of objects), and a hand-written
    recursive parser is a poor risk in an environment we cannot unit test. TSV
    keeps the plugin-side parse to a handful of verifiable lines. The JSON form
    of the same data is still served for the dashboard and MCP clients.

    Note text is stripped of tabs/newlines so a row can never break the format.
    """
    out = ["file_path\tlens_score\ttier\tstatus\tnote\tweakness"]
    for r in rows:
        note = (r.get("note") or "")
        for ch in ("\t", "\r", "\n"):
            note = note.replace(ch, " ")
        out.append("\t".join([
            r.get("file_path") or "",
            "" if r.get("lens_score") is None else str(r["lens_score"]),
            r.get("tier") or "",
            r.get("status") or "",
            note,
            r.get("weakness") or "",
        ]))
    return "\n".join(out)


class LRPathsRequest(BaseModel):
    paths: List[str]


@router.get("/results")
def get_results(
    changed_since: Optional[str] = Query(
        default=None, description="ISO timestamp; only images scored after this"),
    min_score: float = Query(default=0.0, description="Minimum nima_composite"),
    limit: int = Query(default=500, le=5000),
    format: str = Query(default="json", description="json | tsv (tsv is for the LR plugin)"),
):
    """Bulk pull of LENS intelligence for Lightroom. Re-runnable."""
    where = ["nima_composite IS NOT NULL", "nima_composite >= ?"]
    params: list = [min_score]
    if changed_since:
        where.append("COALESCE(pass3_at, pass2_at) > ?")
        params.append(changed_since)
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT {_RESULT_COLS} FROM images
                WHERE {' AND '.join(where)}
                ORDER BY COALESCE(pass3_at, pass2_at) DESC
                LIMIT ?""",
            params,
        ).fetchall()
        results = [_result_row(r) for r in rows]

    if format == "tsv":
        return PlainTextResponse(_tsv(results))
    return results


@router.post("/results/by-paths")
def get_results_by_paths(
    req: LRPathsRequest,
    format: str = Query(default="json", description="json | tsv (tsv is for the LR plugin)"),
):
    """
    Results for an explicit set of paths — what the plugin sends for the current
    Lightroom selection. POST (not GET) so a few hundred paths can't blow the
    URL length limit.
    """
    if not req.paths:
        return PlainTextResponse(_tsv([])) if format == "tsv" else []
    out: list = []
    with get_db() as conn:
        CHUNK = 400  # stay well under SQLite's variable limit
        for i in range(0, len(req.paths), CHUNK):
            chunk = req.paths[i:i + CHUNK]
            marks = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT {_RESULT_COLS} FROM images WHERE file_path IN ({marks})",
                chunk,
            ).fetchall()
            out.extend(_result_row(r) for r in rows)

    if format == "tsv":
        return PlainTextResponse(_tsv(out))
    return out
