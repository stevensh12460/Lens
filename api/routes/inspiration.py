from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from core.database import get_db
import services.inspiration as inspiration_svc

router = APIRouter()


# ── AI Concept Generator ───────────────────────────────────────────────────────

class ConceptRequest(BaseModel):
    genre: str
    season: Optional[str] = None
    mood: Optional[str] = None
    count: int = 3


@router.post("/concept")
async def generate_concept(req: ConceptRequest):
    """
    Generate shoot concepts via AI for the given genre/season/mood.
    Saves concepts to DB and returns them.
    """
    try:
        concepts = await inspiration_svc.generate_concepts(
            genre=req.genre,
            season=req.season,
            mood=req.mood,
            count=req.count,
        )
        return {"genre": req.genre, "season": req.season, "mood": req.mood, "concepts": concepts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Concept generation failed: {e}")


# ── Content Gap Detector ───────────────────────────────────────────────────────

@router.get("/gaps")
def get_content_gaps(lookback_days: int = 30):
    """
    Find genres and moods not posted in the last N days.
    Returns gap analysis and suggestions.
    """
    return inspiration_svc.get_content_gaps(lookback_days=lookback_days)


# ── Concept Library (existing CRUD) ───────────────────────────────────────────

class ConceptCreate(BaseModel):
    title: str
    genre: str
    season: Optional[str] = None
    mood: Optional[str] = None
    location_id: Optional[int] = None
    brief: Optional[str] = None
    wardrobe_notes: Optional[str] = None
    lighting_notes: Optional[str] = None
    props: Optional[str] = None
    caption_angle: Optional[str] = None
    source: Optional[str] = None


class LocationCreate(BaseModel):
    name: str
    area: Optional[str] = None
    type: Optional[str] = None
    address: Optional[str] = None
    best_seasons: Optional[str] = None
    best_time_of_day: Optional[str] = None
    golden_hour_notes: Optional[str] = None
    permit_required: bool = False
    permit_notes: Optional[str] = None
    vibe_tags: Optional[str] = None
    notes: Optional[str] = None


@router.get("/concepts")
def list_concepts(genre: Optional[str] = None, used: Optional[bool] = None):
    with get_db() as conn:
        query = "SELECT * FROM concepts WHERE 1=1"
        params = []
        if genre:
            query += " AND genre = ?"
            params.append(genre)
        if used is not None:
            query += " AND used = ?"
            params.append(used)
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


@router.post("/concepts")
def create_concept(concept: ConceptCreate):
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO concepts (title, genre, season, mood, location_id, brief,
               wardrobe_notes, lighting_notes, props, caption_angle, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (concept.title, concept.genre, concept.season, concept.mood,
             concept.location_id, concept.brief, concept.wardrobe_notes,
             concept.lighting_notes, concept.props, concept.caption_angle,
             concept.source),
        )
        return {"id": cursor.lastrowid}


@router.get("/locations")
def list_locations(area: Optional[str] = None):
    with get_db() as conn:
        if area:
            rows = conn.execute(
                "SELECT * FROM locations WHERE area LIKE ? ORDER BY times_used DESC",
                (f"%{area}%",),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM locations ORDER BY times_used DESC"
            ).fetchall()
        return [dict(r) for r in rows]


@router.post("/locations")
def create_location(loc: LocationCreate):
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO locations (name, area, type, address, best_seasons,
               best_time_of_day, golden_hour_notes, permit_required, permit_notes,
               vibe_tags, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (loc.name, loc.area, loc.type, loc.address, loc.best_seasons,
             loc.best_time_of_day, loc.golden_hour_notes, loc.permit_required,
             loc.permit_notes, loc.vibe_tags, loc.notes),
        )
        return {"id": cursor.lastrowid}
