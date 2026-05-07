"""
Phase 7b — Print Business API Routes
All endpoints under /api/v1/print/
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.config import settings
from core.database import get_db
from services import print_curator, edition_tracker, print_revenue, gbp_print_push

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ScoreRequest(BaseModel):
    limit: int = 50


class CreateEditionRequest(BaseModel):
    image_id: int
    title: str
    edition_size: int
    tier: str = "standard"
    technique: str = "standard"


class RecordSaleRequest(BaseModel):
    image_id: int
    size: str
    paper_type: str
    sale_price: float
    lab_cost: float
    channel: str
    edition_number: int | None = None
    buyer_location: str | None = None
    notes: str | None = None


# ---------------------------------------------------------------------------
# Print-Worthy Images
# ---------------------------------------------------------------------------

@router.get("/worthy")
async def get_print_worthy(
    tier: str | None = Query(None, description="Filter by tier: fine_art or standard"),
    limit: int = Query(50, ge=1, le=500),
) -> dict:
    """Return images assessed as print-worthy, optionally filtered by tier."""
    images = print_curator.get_print_worthy_images(tier=tier, limit=limit)
    return {"count": len(images), "images": images}


@router.get("/top")
async def get_top_prints(
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """Top print candidates by print_score (or nima_composite if unscored)."""
    images = print_curator.get_top_prints(limit=limit)
    return {"count": len(images), "images": images}


@router.get("/pricing")
async def get_pricing() -> dict:
    """Return the full price table for standard and fine_art tiers."""
    return {
        "standard": settings.standard_prices,
        "fine_art": settings.fine_art_prices,
        "fine_art_edition_size": settings.fine_art_edition_size,
        "standard_edition_size": settings.standard_edition_size,
        "currency": "USD",
    }


@router.get("/candidates")
async def get_print_candidates(
    tier: str | None = Query(None, description="Filter: fine_art or standard"),
    genre: str | None = Query(None, description="Filter by genre: nature, portrait, wedding, boudoir, commercial, events"),
    subject_type: str | None = Query(None, description="Filter by subject: landscape, solo portrait, couple, group, product"),
    tag: str | None = Query(None, description="Filter where tags contain this keyword (case-insensitive)"),
    unposted_only: bool = Query(True, description="Exclude already-uploaded to Pixieset"),
    limit: int = Query(500, ge=1, le=10000),
) -> dict:
    """
    Ready-to-upload print candidates with suggested prices per size/medium.
    Use this to generate your Pixieset upload worklist.

    Examples:
      /candidates?genre=nature                  — landscape/nature shots only
      /candidates?subject_type=landscape        — anything tagged landscape subject
      /candidates?tag=sunset                    — keyword search in pass3 tags
      /candidates?tier=fine_art&genre=nature    — top-tier landscape prints
    """
    where = ["print_worthy = 1"]
    params: list = []
    if tier:
        where.append("print_tier = ?")
        params.append(tier)
    if genre:
        where.append("genre = ?")
        params.append(genre)
    if subject_type:
        where.append("subject_type = ?")
        params.append(subject_type)
    if tag:
        where.append("LOWER(tags) LIKE ?")
        params.append(f"%{tag.lower()}%")
    if unposted_only:
        where.append("(pixieset_url IS NULL OR pixieset_url = '')")

    sql = f"""
        SELECT id, file_name, file_path, print_score, print_tier, print_technique,
               genre, subject_type, mood, setting, nima_composite,
               tags, caption_draft, edition_title, edition_size,
               editions_sold, pixieset_url
        FROM images
        WHERE {' AND '.join(where)}
        ORDER BY print_score DESC
        LIMIT ?
    """
    params.append(limit)

    with get_db() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

    for img in rows:
        prices = settings.fine_art_prices if img.get("print_tier") == "fine_art" else settings.standard_prices
        img["suggested_prices"] = prices
        img["suggested_edition_size"] = (
            settings.fine_art_edition_size if img.get("print_tier") == "fine_art"
            else settings.standard_edition_size
        )

    return {"count": len(rows), "images": rows}


class MarkPostedRequest(BaseModel):
    image_id: int
    pixieset_url: str
    pixieset_product_id: str | None = None


@router.post("/mark-posted")
async def mark_posted(body: MarkPostedRequest) -> dict:
    """Record that an image has been uploaded to Pixieset with the given URL."""
    with get_db() as conn:
        row = conn.execute("SELECT id FROM images WHERE id = ?", (body.image_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Image {body.image_id} not found")
        conn.execute(
            """UPDATE images
               SET pixieset_url = ?, pixieset_product_id = ?
               WHERE id = ?""",
            (body.pixieset_url, body.pixieset_product_id, body.image_id),
        )
    return {"status": "marked_posted", "image_id": body.image_id, "pixieset_url": body.pixieset_url}


@router.post("/score")
async def trigger_print_scoring(body: ScoreRequest) -> dict:
    """
    Trigger Ollama vision scoring on a batch of unscored portfolio-worthy images.
    This is a long-running operation — results are saved to the DB as they complete.
    """
    worthy_count = print_curator.score_print_candidates(limit=body.limit)
    return {
        "message": f"Print scoring complete",
        "print_worthy_found": worthy_count,
        "scored_up_to": body.limit,
    }


# ---------------------------------------------------------------------------
# Edition Management
# ---------------------------------------------------------------------------

@router.post("/editions")
async def create_edition(body: CreateEditionRequest) -> dict:
    """Define a limited edition for a print-worthy image."""
    result = edition_tracker.create_edition(
        image_id=body.image_id,
        title=body.title,
        edition_size=body.edition_size,
        tier=body.tier,
        technique=body.technique,
    )
    if not result:
        raise HTTPException(status_code=404, detail=f"Image {body.image_id} not found")
    return result


@router.get("/editions")
async def list_active_editions() -> dict:
    """List all active (non-retired) limited editions."""
    editions = edition_tracker.get_active_editions()
    return {"count": len(editions), "editions": editions}


@router.get("/editions/alerts")
async def get_edition_alerts() -> dict:
    """Editions that have hit 50%, 80%, or 100% sold milestones."""
    alerts = edition_tracker.get_edition_alerts()
    return {"count": len(alerts), "alerts": alerts}


@router.get("/editions/{image_id}")
async def get_edition_status(image_id: int) -> dict:
    """Get edition progress and suggested action for a specific image."""
    status = edition_tracker.get_edition_status(image_id)
    if "error" in status:
        raise HTTPException(status_code=404, detail=status["error"])
    return status


# ---------------------------------------------------------------------------
# Sales Recording
# ---------------------------------------------------------------------------

@router.post("/sales")
async def record_sale(body: RecordSaleRequest) -> dict:
    """Record a print sale. Updates revenue aggregates and edition sold count."""
    try:
        result = edition_tracker.record_sale(
            image_id=body.image_id,
            size=body.size,
            paper_type=body.paper_type,
            sale_price=body.sale_price,
            lab_cost=body.lab_cost,
            channel=body.channel,
            edition_number=body.edition_number,
            buyer_location=body.buyer_location,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return result


# ---------------------------------------------------------------------------
# Revenue Analytics
# ---------------------------------------------------------------------------

@router.get("/revenue")
async def revenue_summary() -> dict:
    """Overall print revenue summary: totals, averages, best month."""
    return print_revenue.get_revenue_summary()


@router.get("/revenue/by-channel")
async def revenue_by_channel() -> dict:
    """Revenue breakdown by sales channel."""
    channels = print_revenue.get_revenue_by_channel()
    return {"channels": channels}


@router.get("/revenue/by-technique")
async def revenue_by_technique() -> dict:
    """Revenue breakdown by print technique (rotation, standard, etc.)."""
    techniques = print_revenue.get_revenue_by_technique()
    return {"techniques": techniques}


@router.get("/revenue/by-month")
async def revenue_by_month(
    months: int = Query(12, ge=1, le=60),
) -> dict:
    """Monthly revenue trend for the past N months."""
    monthly = print_revenue.get_revenue_by_month(months=months)
    return {"months": months, "data": monthly}


@router.get("/revenue/by-image")
async def revenue_by_image(
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    """Top-selling images by total print revenue."""
    images = print_revenue.get_revenue_by_image(limit=limit)
    return {"images": images}


@router.get("/revenue/margins")
async def margin_analysis() -> dict:
    """Margin analysis: average %, best and worst margin images."""
    return print_revenue.get_margin_analysis()


@router.get("/dashboard")
async def print_dashboard() -> dict:
    """Combined print business dashboard data: inventory + revenue + status."""
    return print_revenue.get_print_dashboard_data()


# ---------------------------------------------------------------------------
# Google Business Profile
# ---------------------------------------------------------------------------

@router.get("/gbp/queue")
async def gbp_queue(
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    """Print-worthy images not yet pushed to GBP, ordered by print_score."""
    queue = gbp_print_push.get_gbp_queue(limit=limit)
    return {"count": len(queue), "queue": queue}


@router.get("/gbp/status")
async def gbp_status() -> dict:
    """GBP push status: last push date, this week's count, queue size."""
    return gbp_print_push.get_gbp_status()


@router.get("/gbp/payload/{image_id}")
async def gbp_payload(image_id: int) -> dict:
    """
    Build the GBP API payload for an image.
    Returns the data structure ready for submission once OAuth is configured.
    """
    payload = gbp_print_push.prepare_gbp_payload(image_id)
    if "error" in payload:
        raise HTTPException(status_code=404, detail=payload["error"])
    return payload


@router.post("/gbp/mark-pushed/{image_id}")
async def mark_gbp_pushed(image_id: int) -> dict:
    """Mark an image as pushed to GBP (records timestamp)."""
    return gbp_print_push.mark_gbp_pushed(image_id)
