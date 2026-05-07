"""
API routes — CRM Layer (Phase 6)
All endpoints under /crm (prefix set in main.py).
"""
from __future__ import annotations

from typing import Any, Optional
from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.database import get_db
from crm import clients as crm_clients
from crm import bookings as crm_bookings
from crm import intake as crm_intake
from crm import contracts as crm_contracts
from crm import sequences as crm_sequences
from crm import gallery as crm_gallery

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ClientCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None
    referred_by_id: Optional[int] = None


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None
    preferences: Optional[str] = None
    anniversary: Optional[date] = None
    birthday: Optional[date] = None
    referred_by: Optional[int] = None
    referred_by_vendor: Optional[int] = None


class BookingCreate(BaseModel):
    client_id: int
    genre: str
    shoot_date: date
    package: Optional[str] = None
    package_tier: Optional[str] = None
    amount: Optional[float] = None
    source: Optional[str] = None
    source_detail: Optional[str] = None


class BookingStatusUpdate(BaseModel):
    status: str


class IntakeSave(BaseModel):
    data: dict[str, Any]


class ContractSign(BaseModel):
    signed_by: str
    signed_at: Optional[str] = None


class ReminderComplete(BaseModel):
    pass


class GalleryCreate(BaseModel):
    shoot_id: int
    image_paths: list[str]
    pin: Optional[str] = None
    expires_days: int = 90


class GalleryVerify(BaseModel):
    pin: str


# ---------------------------------------------------------------------------
# CLIENTS
# ---------------------------------------------------------------------------

@router.get("/clients")
def list_clients(
    search: Optional[str] = Query(None),
    active_only: bool = Query(False),
):
    if search:
        return crm_clients.search_clients(search)
    return crm_clients.get_all_clients(active_only=active_only)


@router.post("/clients")
def create_client(payload: ClientCreate):
    return crm_clients.create_client(
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        notes=payload.notes,
        referred_by_id=payload.referred_by_id,
    )


@router.get("/clients/upcoming-dates")
def upcoming_client_dates(days: int = Query(30)):
    return crm_clients.check_upcoming_dates(days=days)


@router.get("/clients/top")
def top_clients(limit: int = Query(10)):
    return crm_clients.get_top_clients(limit=limit)


@router.get("/clients/{client_id}")
def get_client(client_id: int):
    client = crm_clients.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    shoots = crm_clients.get_client_shoots(client_id)
    return {**client, "shoots": shoots}


@router.patch("/clients/{client_id}")
def update_client(client_id: int, payload: ClientUpdate):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    # Convert date objects to strings
    for field in ("anniversary", "birthday"):
        if field in updates and isinstance(updates[field], date):
            updates[field] = str(updates[field])
    result = crm_clients.update_client(client_id, **updates)
    if not result:
        raise HTTPException(status_code=404, detail="Client not found")
    return result


@router.get("/clients/{client_id}/stats")
def client_stats(client_id: int):
    stats = crm_clients.get_client_stats(client_id)
    if not stats:
        raise HTTPException(status_code=404, detail="Client not found")
    return stats


# ---------------------------------------------------------------------------
# BOOKINGS
# ---------------------------------------------------------------------------

@router.get("/bookings")
def list_bookings(
    status: Optional[str] = Query(None),
    genre: Optional[str] = Query(None),
):
    return crm_bookings.get_all_bookings(status=status, genre=genre)


@router.post("/bookings")
def create_booking(payload: BookingCreate):
    return crm_bookings.create_booking(
        client_id=payload.client_id,
        genre=payload.genre,
        shoot_date=payload.shoot_date,
        package=payload.package,
        package_tier=payload.package_tier,
        amount=payload.amount,
        source=payload.source,
        source_detail=payload.source_detail,
    )


@router.get("/bookings/upcoming")
def upcoming_shoots(days: int = Query(30)):
    return crm_bookings.get_upcoming_shoots(days=days)


@router.get("/bookings/pipeline")
def pipeline_summary():
    return crm_bookings.get_pipeline_summary()


@router.get("/bookings/{booking_id}")
def get_booking(booking_id: int):
    booking = crm_bookings.get_booking(booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking


@router.patch("/bookings/{booking_id}/status")
def update_booking_status(booking_id: int, payload: BookingStatusUpdate):
    try:
        return crm_bookings.update_booking_status(booking_id, payload.status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/bookings/{booking_id}/deposit")
def mark_deposit(booking_id: int):
    return crm_bookings.mark_deposit_paid(booking_id)


@router.post("/bookings/{booking_id}/balance")
def mark_balance(booking_id: int):
    return crm_bookings.mark_balance_paid(booking_id)


@router.post("/bookings/{booking_id}/contract-signed")
def mark_contract(booking_id: int):
    return crm_bookings.mark_contract_signed(booking_id)


@router.post("/bookings/{booking_id}/intake-complete")
def mark_intake(booking_id: int):
    return crm_bookings.mark_intake_complete(booking_id)


# ---------------------------------------------------------------------------
# INTAKE
# ---------------------------------------------------------------------------

@router.get("/intake/{genre}")
def get_intake_form(genre: str):
    form = crm_intake.get_intake_form(genre)
    if not form:
        raise HTTPException(status_code=404, detail=f"No intake form for genre '{genre}'")
    return {"genre": genre, "fields": form}


@router.post("/intake/{booking_id}")
def save_intake(booking_id: int, payload: IntakeSave):
    booking = crm_bookings.get_booking(booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    genre = booking.get("genre", "")
    result = crm_intake.save_intake(booking_id, genre, payload.data)
    if not result.get("saved"):
        raise HTTPException(status_code=422, detail={"errors": result.get("errors", [])})
    return result


@router.get("/intake/{booking_id}/responses")
def get_intake_responses(booking_id: int):
    data = crm_intake.get_intake(booking_id)
    if data is None:
        raise HTTPException(status_code=404, detail="No intake data found for this booking")
    return {"booking_id": booking_id, "data": data}


# ---------------------------------------------------------------------------
# CONTRACTS
# ---------------------------------------------------------------------------

@router.get("/contracts/{booking_id}")
def get_contract(booking_id: int):
    text = crm_contracts.generate_contract(booking_id)
    if text is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    return {"booking_id": booking_id, "contract": text}


@router.post("/contracts/{booking_id}/sign")
def sign_contract(booking_id: int, payload: ContractSign):
    result = crm_contracts.save_signed_contract(
        booking_id,
        signed_by=payload.signed_by,
        signed_at=payload.signed_at,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Booking not found")
    return result


# ---------------------------------------------------------------------------
# SEQUENCES / REMINDERS
# ---------------------------------------------------------------------------

@router.get("/reminders")
def get_reminders(hours_ahead: int = Query(24)):
    return crm_sequences.get_due_reminders(hours_ahead=hours_ahead)


@router.post("/reminders/{reminder_id}/complete")
def complete_reminder(reminder_id: int):
    result = crm_sequences.complete_reminder(reminder_id)
    if not result:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return result


@router.get("/reminders/booking/{booking_id}")
def booking_reminders(booking_id: int):
    return crm_sequences.get_reminders_for_booking(booking_id)


@router.post("/sequences/trigger/{booking_id}/{sequence_name}")
def trigger_sequence(booking_id: int, sequence_name: str):
    try:
        reminders = crm_sequences.trigger_sequence(booking_id, sequence_name)
        return {"triggered": len(reminders), "reminders": reminders}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sequences/check")
def check_sequences():
    summary = crm_sequences.check_and_trigger_sequences()
    return {"triggered": summary}


# ---------------------------------------------------------------------------
# GALLERY
# ---------------------------------------------------------------------------

@router.post("/gallery")
def create_gallery(payload: GalleryCreate):
    return crm_gallery.create_gallery(
        shoot_id=payload.shoot_id,
        image_paths=payload.image_paths,
        pin=payload.pin,
        expires_days=payload.expires_days,
    )


@router.get("/gallery/{token}")
def get_gallery(token: str):
    gallery = crm_gallery.get_gallery_by_token(token)
    if not gallery:
        raise HTTPException(status_code=404, detail="Gallery not found or expired")
    return gallery


@router.post("/gallery/{token}/verify")
def verify_gallery(token: str, payload: GalleryVerify):
    valid = crm_gallery.verify_gallery_pin(token, payload.pin)
    return {"valid": valid}


@router.get("/gallery/{token}/images")
def gallery_images(token: str):
    images = crm_gallery.get_gallery_images(token)
    return {"token": token, "images": images}


@router.post("/gallery/{token}/download/{image_id}")
def record_download(token: str, image_id: int):
    ok = crm_gallery.record_download(token, image_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Gallery not found")
    return {"recorded": True}


@router.get("/gallery/stats/{shoot_id}")
def gallery_stats(shoot_id: int):
    stats = crm_gallery.get_gallery_stats(shoot_id)
    if not stats:
        raise HTTPException(status_code=404, detail="No galleries found for this shoot")
    return stats
