from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel
from typing import Optional
from pathlib import Path
import io
import subprocess

from PIL import Image

from core.database import get_db
import services.revenue as revenue_svc
import services.repurpose as repurpose_svc
import services.workload as workload_svc
import services.referral as referral_svc
import services.upsell as upsell_svc
import services.licensing as licensing_svc
import services.style_tracker as style_svc
import services.client_intel as client_intel_svc

router = APIRouter()

# Separate router for /api/v1 prefix endpoints
images_router = APIRouter()


# ── Pydantic models for POST bodies ───────────────────────────────────────────

class VendorCreate(BaseModel):
    name: str
    type: str
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class LicenseCreate(BaseModel):
    client_id: int
    shoot_id: Optional[int] = None
    image_ids: list[int]
    usage_type: str
    expires_at: str
    renewal_amount: float
    notes: Optional[str] = None


# ── Revenue ────────────────────────────────────────────────────────────────────

@router.get("/revenue")
def revenue_summary():
    """
    Full revenue analytics: YTD, all-time, by genre, by month,
    busiest months historically, projected next 3 months.
    """
    return revenue_svc.get_revenue_summary()


@router.get("/revenue/genre")
def revenue_by_genre(genre: Optional[str] = None):
    """Revenue breakdown by genre, or monthly breakdown for a specific genre."""
    return revenue_svc.get_revenue_by_genre(genre=genre)


# ── Repurpose Opportunities ────────────────────────────────────────────────────

@router.get("/repurpose")
def repurpose_opportunities(min_unused: int = 1):
    """
    Find shoots with untapped content: <50% of social-ready images posted.
    Sorted by unused_count DESC — biggest opportunities first.
    """
    return repurpose_svc.get_repurpose_opportunities(min_unused=min_unused)


@router.get("/repurpose/summary")
def repurpose_summary():
    """High-level repurpose summary: totals, by genre, top 5 shoots."""
    return repurpose_svc.get_repurpose_summary()


@router.get("/repurpose/{shoot_id}")
def repurpose_shoot_detail(shoot_id: int):
    """All unposted content-ready images for a specific shoot."""
    result = repurpose_svc.get_repurpose_for_shoot(shoot_id)
    if not result:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Shoot {shoot_id} not found")
    return result


# ── Pipeline Health (existing) ─────────────────────────────────────────────────

@router.get("/pipeline-health")
def pipeline_health():
    with get_db() as conn:
        q = lambda sql: conn.execute(sql).fetchone()[0]
        return {
            "total_imported": q("SELECT COUNT(*) FROM images"),
            "passed_cull": q("SELECT COUNT(*) FROM images WHERE pass1_status = 'pass'"),
            "pass1_processed": q("SELECT COUNT(*) FROM images WHERE cull_score IS NOT NULL"),
            "pass1_dupes": q("SELECT COUNT(*) FROM images WHERE pass1_status = 'duplicate'"),
            "pass1_failed": q("SELECT COUNT(*) FROM images WHERE pass1_status = 'fail'"),
            "nima_scored": q("SELECT COUNT(*) FROM images WHERE pass2_at IS NOT NULL"),
            "vision_tagged": q("SELECT COUNT(*) FROM images WHERE pass3_at IS NOT NULL"),
            "portfolio_worthy": q("SELECT COUNT(*) FROM images WHERE portfolio_worthy = 1"),
            "social_ready": q("SELECT COUNT(*) FROM images WHERE content_ready = 1"),
        }


@router.get("/top-images")
def top_images(limit: int = 10, genre: str = None):
    with get_db() as conn:
        query = """SELECT file_path, file_name, genre, nima_composite, quality_score,
                   portfolio_worthy, content_ready, tags
                   FROM images WHERE pass3_at IS NOT NULL"""
        params = []
        if genre:
            query += " AND genre = ?"
            params.append(genre)
        query += " ORDER BY nima_composite DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


# ── Workload ───────────────────────────────────────────────────────────────────

@router.get("/workload")
def workload_summary():
    """
    Post-production workload summary: queue size, overdue count,
    due this week, average turnaround by genre.
    """
    return workload_svc.get_workload_summary()


@router.get("/workload/overdue")
def workload_overdue():
    """All overdue deliveries — shoots past their genre delivery window."""
    return workload_svc.get_overdue_deliveries()


# ── Referrals ──────────────────────────────────────────────────────────────────

@router.get("/referrals")
def referral_summary():
    """Overall referral network summary: best source, % from referrals, totals."""
    return referral_svc.get_referral_summary()


@router.get("/referrals/sources")
def referral_sources():
    """Booking count and revenue aggregated by referral source."""
    return referral_svc.get_referral_sources()


@router.post("/vendors")
def create_vendor(body: VendorCreate):
    """Add a new vendor to the referral network."""
    return referral_svc.add_vendor(
        name=body.name,
        type=body.type,
        contact_name=body.contact_name,
        email=body.email,
        phone=body.phone,
    )


# ── Upsell ─────────────────────────────────────────────────────────────────────

@router.get("/upsell")
def upsell_queue():
    """All delivered bookings with print upsell opportunities not yet sent."""
    return upsell_svc.get_upsell_summary()


@router.get("/upsell/{booking_id}")
def upsell_booking(booking_id: int):
    """Print upsell opportunities for a specific delivered booking."""
    result = upsell_svc.get_upsell_opportunities(booking_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── Licenses ───────────────────────────────────────────────────────────────────

@router.get("/licenses")
def licenses_overview():
    """License revenue YTD and all-time summary."""
    return licensing_svc.get_license_revenue_ytd()


@router.get("/licenses/expiring")
def licenses_expiring(days_ahead: int = 60):
    """Licenses expiring within the next N days (default 60)."""
    return {
        "days_ahead": days_ahead,
        "expiring": licensing_svc.get_expiring_licenses(days_ahead=days_ahead),
        "expired": licensing_svc.get_expired_licenses(),
    }


@router.post("/licenses")
def create_license(body: LicenseCreate):
    """Create a new commercial image license."""
    return licensing_svc.create_license(
        client_id=body.client_id,
        shoot_id=body.shoot_id,
        image_ids=body.image_ids,
        usage_type=body.usage_type,
        expires_at=body.expires_at,
        renewal_amount=body.renewal_amount,
        notes=body.notes,
    )


# ── Style Tracker ──────────────────────────────────────────────────────────────

@router.get("/style")
def style_overview():
    """Dominant aesthetics across the entire tagged library."""
    return style_svc.get_dominant_aesthetics()


@router.get("/style/evolution")
def style_evolution():
    """Month-by-month aesthetic evolution and genre distribution over time."""
    return {
        "monthly_evolution": style_svc.get_style_evolution(),
        "genre_distribution": style_svc.get_genre_distribution_over_time(),
    }


@router.get("/style/signature")
def style_signature():
    """Tags that appear at higher rates in portfolio-worthy images — your signature."""
    return style_svc.get_signature_tags()


# ── Client Intelligence ────────────────────────────────────────────────────────

@router.post("/clients/{client_id}/profile")
async def build_client_profile(client_id: int):
    """
    Build (or rebuild) an AI-powered intelligence profile for a client.
    Uses qwen2.5:14b to analyze notes, bookings, and shoot history.
    """
    result = await client_intel_svc.build_client_profile(client_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/clients/{client_id}/profile")
def get_client_profile(client_id: int):
    """Retrieve the saved intelligence profile for a client."""
    profile = client_intel_svc.get_client_profile(client_id)
    if not profile:
        raise HTTPException(
            status_code=404,
            detail=f"No profile found for client {client_id}. POST to /clients/{client_id}/profile to generate one.",
        )
    return profile


@router.get("/clients/vip")
def vip_clients():
    """All clients flagged as VIP-worthy by AI analysis."""
    return client_intel_svc.get_vip_clients()


@router.get("/clients/rebooking")
def rebooking_candidates():
    """High rebooking-likelihood clients who haven't booked in 90+ days."""
    return client_intel_svc.get_rebooking_candidates()


# ── Image Library Browser ──────────────────────────────────────────────────────

@images_router.get("/images")
def list_images(
    genre: Optional[str] = Query(None),
    mood: Optional[str] = Query(None),
    portfolio_worthy: Optional[bool] = Query(None),
    content_ready: Optional[bool] = Query(None),
    min_quality: Optional[float] = Query(None),
    has_description: Optional[bool] = Query(None),
    pass1_status: Optional[str] = Query(None),
    pass3_skipped: Optional[bool] = Query(None),
    sort_by: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    """Paginated image library browser with filters."""
    with get_db() as conn:
        conditions = []
        params = []

        if genre:
            conditions.append("genre = ?")
            params.append(genre)
        if mood:
            conditions.append("mood = ?")
            params.append(mood)
        if portfolio_worthy is not None:
            conditions.append("portfolio_worthy = ?")
            params.append(1 if portfolio_worthy else 0)
        if content_ready is not None:
            conditions.append("content_ready = ?")
            params.append(1 if content_ready else 0)
        if min_quality is not None:
            conditions.append("quality_score >= ?")
            params.append(min_quality)
        if has_description:
            conditions.append("pass3_at IS NOT NULL")
        if pass1_status:
            conditions.append("pass1_status = ?")
            params.append(pass1_status)
        if pass3_skipped:
            conditions.append("pass2_at IS NOT NULL AND nima_composite < 6.0 AND pass3_at IS NULL")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        offset = (page - 1) * limit

        total = conn.execute(
            f"SELECT COUNT(*) FROM images {where}", params
        ).fetchone()[0]

        if sort_by == "nima_desc":
            order_by = "ORDER BY nima_composite DESC NULLS LAST"
        elif pass3_skipped:
            order_by = "ORDER BY nima_composite DESC"
        else:
            order_by = "ORDER BY imported_at DESC"
        rows = conn.execute(
            f"""SELECT id, file_name, file_path, genre, mood, lighting,
                       subject_type, quality_score, nima_composite,
                       portfolio_worthy, content_ready, print_worthy,
                       tags, description, composition, subjects,
                       emotional_impact, technical_issues, print_notes,
                       pass1_status, pass2_at, pass3_at, imported_at
                FROM images {where}
                {order_by}
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "pages": max(1, (total + limit - 1) // limit),
            "images": [dict(r) for r in rows],
        }


_THUMB_CACHE_DIR = Path.home() / "lens" / "cache" / "thumbs"
_THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)


@images_router.api_route("/images/{image_id}/thumb.jpg", methods=["GET", "HEAD"])
@images_router.api_route("/images/{image_id}/thumb", methods=["GET", "HEAD"])
def get_image_thumb(image_id: int):
    """Return a JPEG thumbnail (max 800px longest edge) for the given image.
    Cached to disk in ~/lens/cache/thumbs/<id>.jpg — keyed by source mtime."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT file_path FROM images WHERE id = ?", (image_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Image not found")

    file_path = Path(row["file_path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    cache_path = _THUMB_CACHE_DIR / f"{image_id}.jpg"
    try:
        src_mtime = file_path.stat().st_mtime
        if cache_path.exists() and cache_path.stat().st_mtime >= src_mtime:
            return Response(content=cache_path.read_bytes(), media_type="image/jpeg")
    except Exception:
        pass

    _RAW_EXTENSIONS = {".arw", ".cr2", ".cr3", ".nef", ".raf", ".dng", ".orf", ".rw2", ".pef"}
    try:
        if file_path.suffix.lower() in _RAW_EXTENSIONS:
            import rawpy
            with rawpy.imread(str(file_path)) as raw:
                rgb = raw.postprocess(use_camera_wb=True, half_size=True, no_auto_bright=False, output_bps=8)
            img = Image.fromarray(rgb)
        else:
            img = Image.open(file_path)
        img.thumbnail((800, 800), Image.LANCZOS)
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        data = buf.getvalue()
        # Write cache (best-effort)
        try:
            cache_path.write_bytes(data)
        except Exception:
            pass
        return Response(content=data, media_type="image/jpeg")
    except Exception:
        placeholder = Image.new("RGB", (800, 600), color=(20, 20, 20))
        buf = io.BytesIO()
        placeholder.save(buf, format="JPEG", quality=85)
        buf.seek(0)
        return Response(content=buf.read(), media_type="image/jpeg")


@images_router.post("/images/{image_id}/open")
def open_image(image_id: int, body: dict):
    """Open the image in Lightroom Classic or reveal it in Finder."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT file_path FROM images WHERE id = ?", (image_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Image not found")

    file_path = str(row["file_path"])
    app = body.get("app", "finder")

    if app == "lightroom":
        subprocess.Popen(["open", "-a", "Adobe Lightroom Classic", file_path])
    else:
        subprocess.Popen(["open", "-R", file_path])

    return {"status": "ok", "action": app, "file": file_path}
