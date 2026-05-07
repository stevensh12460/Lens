from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import json

from core.database import get_db

router = APIRouter()


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
    now = datetime.utcnow().isoformat()
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
             datetime.utcnow().isoformat(), payload.file_path),
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
                 datetime.utcnow().isoformat(), item.file_path),
            )
            synced += 1
    return {"synced": synced}


@router.get("/picks")
def get_picks(min_stars: int = 0):
    with get_db() as conn:
        rows = conn.execute(
            """SELECT file_path, file_name, lr_pick_flag, lr_color_label,
               lr_star_rating, nima_composite, genre
               FROM images WHERE lr_pick_flag = 'pick'
               AND (lr_star_rating IS NULL OR lr_star_rating >= ?)
               ORDER BY lr_star_rating DESC, nima_composite DESC""",
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
