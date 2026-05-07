from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import date

import services.shoot_brief as brief_svc

router = APIRouter()


class ShootBriefRequest(BaseModel):
    shoot_date: date
    location: str
    genre: str
    client_id: Optional[int] = None


@router.post("/brief")
async def create_shoot_brief(req: ShootBriefRequest):
    """
    Generate a complete shoot brief including:
    - AI-generated shot list by category
    - Gear checklist for the genre
    - Golden hour times for Hudson Valley, NY on the shoot date
    - Creative concepts (not yet shot for this client)
    - Weather note placeholder
    Saves to shoot_briefs table and returns the full brief.
    """
    try:
        brief = await brief_svc.generate_shoot_brief(
            shoot_date=req.shoot_date,
            location=req.location,
            genre=req.genre,
            client_id=req.client_id,
        )
        return brief
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Brief generation failed: {e}")


@router.get("/brief/{brief_id}")
def get_shoot_brief(brief_id: int):
    """Retrieve a previously generated shoot brief by ID."""
    brief = brief_svc.get_brief(brief_id)
    if not brief:
        raise HTTPException(status_code=404, detail=f"Brief {brief_id} not found")
    return brief
