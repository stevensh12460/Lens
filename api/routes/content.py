"""
api/routes/content.py

Content Layer API routes — Phase 4.
Mounts at /api/v1/content (registered in api/main.py).
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import date

import content.calendar as cal_svc
import content.hashtags as hashtag_svc
import content.pillars as pillar_svc
import content.seasonal as seasonal_svc

router = APIRouter()


# ── Calendar ──────────────────────────────────────────────────────────────────

@router.get("/calendar")
def get_calendar(days: int = Query(default=30, ge=1, le=90)):
    """Return all calendar posts for the next N days, grouped by date."""
    return cal_svc.get_calendar(days=days)


@router.post("/calendar/fill")
def fill_calendar(days: int = Query(default=30, ge=1, le=90)):
    """Disabled by user policy — never auto-pick photos for the IG calendar."""
    raise HTTPException(
        status_code=403,
        detail="Auto-fill is permanently disabled. Pick each post manually from the Post Candidate Pool.",
    )


@router.get("/today")
def get_today():
    """Return today's scheduled calendar post, or null if none exists."""
    post = cal_svc.get_today()
    if post is None:
        return {"post": None, "message": "No post scheduled for today"}
    return {"post": post}


@router.get("/week")
def get_week(week_offset: int = Query(default=0, ge=-52, le=52)):
    """Return full week view (Mon–Sun) for current week + optional offset."""
    return cal_svc.get_week(week_offset=week_offset)


class MarkPostedRequest(BaseModel):
    platform: str = "instagram"


@router.patch("/calendar/{post_id}/posted")
def mark_calendar_posted(post_id: int, req: MarkPostedRequest):
    """Mark a calendar post as posted on the given platform."""
    try:
        return cal_svc.mark_posted(post_id=post_id, platform=req.platform)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Hashtags ──────────────────────────────────────────────────────────────────

@router.get("/hashtags")
def get_hashtags(
    genre: str = Query(..., description="Primary genre (wedding/portrait/boudoir/commercial/events/nature)"),
    mood: Optional[str] = Query(default=None, description="Mood tag set (dramatic/romantic/playful/serene/bold/ethereal)"),
    location: Optional[str] = Query(default=None, description="Location name (fuzzy matched)"),
    season: Optional[str] = Query(default=None, description="Season override (spring/summer/autumn/winter); defaults to current"),
    limit: int = Query(default=30, ge=1, le=30),
):
    """Return a combined, deduplicated hashtag list for the given parameters (max 30)."""
    resolved_season = season or hashtag_svc.get_season()
    tags = hashtag_svc.get_hashtags(
        genre=genre,
        mood=mood,
        location=location,
        season=resolved_season,
        limit=limit,
    )
    return {
        "tags": tags,
        "count": len(tags),
        "genre": genre,
        "mood": mood,
        "location": location,
        "season": resolved_season,
    }


# ── Pillars ───────────────────────────────────────────────────────────────────

@router.get("/pillars")
def get_pillars():
    """Return all content pillar definitions."""
    return {
        "pillars": pillar_svc.PILLARS,
        "genre_rotation": pillar_svc.GENRE_ROTATION,
        "day_pillar_map": {
            "0_monday": "transformation",
            "1_tuesday": "genre_spotlight",
            "2_wednesday": "bts",
            "3_thursday": "social_proof",
            "4_friday": "personality",
            "5_saturday": "flexible",
            "6_sunday": "flexible",
        },
    }


@router.get("/week-plan")
def get_week_plan(start_date: Optional[date] = Query(default=None)):
    """Return Mon–Sun content plan with pillars and genre for a given week."""
    return pillar_svc.get_week_plan(start_date=start_date)


# ── Seasonal ──────────────────────────────────────────────────────────────────

@router.get("/seasonal")
def get_seasonal():
    """Return seasonal context: current season, top genres, and caption hooks."""
    season = seasonal_svc.get_current_season()
    return {
        "current_season": season,
        "top_genres": seasonal_svc.get_seasonal_genres(season),
        "caption_hooks": seasonal_svc.get_seasonal_caption_hooks(season),
    }


@router.get("/seasonal/opportunities")
def get_seasonal_opportunities(days: int = Query(default=60, ge=7, le=365)):
    """Return upcoming seasonal events and booking opportunities."""
    return {
        "opportunities": seasonal_svc.get_upcoming_opportunities(days=days),
        "days_ahead": days,
    }
