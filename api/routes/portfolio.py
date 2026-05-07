from fastapi import APIRouter, HTTPException
from typing import Optional

from core.database import get_db
import services.portfolio as portfolio_svc

router = APIRouter()


@router.get("/{genre}")
def get_portfolio_by_genre(genre: str, limit: int = 20):
    """Return top images for a specific genre ranked by combined NIMA + quality score."""
    images = portfolio_svc.get_portfolio_by_genre(genre, limit=limit)
    return {"genre": genre, "count": len(images), "images": images}


@router.get("/all/summary")
def portfolio_summary():
    """Summary stats per genre: count, avg scores."""
    return portfolio_svc.get_portfolio_summary()


@router.post("/all/refresh")
def refresh_portfolio_flags():
    """
    Recompute and update portfolio_worthy flags for all genres.
    Marks top 20 per genre by combined NIMA + quality score.
    """
    results = portfolio_svc.update_portfolio_flags()
    return {"status": "updated", "by_genre": results}
