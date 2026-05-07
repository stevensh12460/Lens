"""
CRM — Per-genre intake form logic.
No LLM calls. Rule-based only. All DB access through core/database.py.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from core.database import get_db

# ---------------------------------------------------------------------------
# Intake form definitions
# ---------------------------------------------------------------------------

INTAKE_FORMS: dict[str, list[dict]] = {
    "wedding": [
        {"field": "wedding_date", "label": "Wedding Date", "type": "date", "required": True},
        {"field": "venue_name", "label": "Venue Name", "type": "text", "required": True},
        {"field": "venue_location", "label": "Venue City/Town", "type": "text", "required": True},
        {"field": "guest_count", "label": "Approximate Guest Count", "type": "number"},
        {"field": "ceremony_time", "label": "Ceremony Start Time", "type": "time"},
        {"field": "reception_end", "label": "Reception End Time", "type": "time"},
        {"field": "second_shooter", "label": "Second Shooter Needed?", "type": "boolean"},
        {"field": "engagement_session", "label": "Include Engagement Session?", "type": "boolean"},
        {
            "field": "style_preference",
            "label": "Style (editorial/documentary/traditional)",
            "type": "select",
            "options": ["editorial", "documentary", "traditional", "mix"],
        },
        {"field": "special_notes", "label": "Anything else we should know?", "type": "textarea"},
    ],
    "portrait": [
        {
            "field": "session_type",
            "label": "Session Type",
            "type": "select",
            "options": ["individual", "couple", "family", "maternity", "newborn", "senior"],
        },
        {
            "field": "location_preference",
            "label": "Preferred Location",
            "type": "select",
            "options": ["outdoor_nature", "outdoor_urban", "studio", "client_home", "no_preference"],
        },
        {"field": "outfit_count", "label": "Number of Outfit Changes", "type": "number"},
        {
            "field": "style_preference",
            "label": "Style Preference",
            "type": "select",
            "options": ["bright_airy", "moody_dramatic", "natural_candid", "editorial"],
        },
        {"field": "special_notes", "label": "Anything special about this session?", "type": "textarea"},
    ],
    "boudoir": [
        {
            "field": "comfort_level",
            "label": "Comfort Level",
            "type": "select",
            "options": ["implied_only", "lingerie", "artistic_nude"],
            "private": True,
        },
        {"field": "wardrobe_pieces", "label": "Number of Wardrobe Changes", "type": "number"},
        {"field": "hair_makeup", "label": "Hair & Makeup Services Needed?", "type": "boolean"},
        {"field": "gift_for", "label": "Is this a gift?", "type": "boolean"},
        {
            "field": "privacy_level",
            "label": "Privacy Level for Gallery",
            "type": "select",
            "options": ["standard_pin", "extra_private", "no_watermark"],
        },
        {
            "field": "special_notes",
            "label": "Any concerns or questions? (This stays private)",
            "type": "textarea",
            "private": True,
        },
    ],
    "commercial": [
        {"field": "client_company", "label": "Company/Brand Name", "type": "text", "required": True},
        {
            "field": "deliverable_type",
            "label": "Primary Deliverable",
            "type": "select",
            "options": ["product", "headshots", "brand_lifestyle", "event", "food_bev", "360_spin"],
        },
        {
            "field": "usage_rights",
            "label": "Usage Rights Needed",
            "type": "select",
            "options": ["digital_only", "print", "broadcast", "unlimited"],
        },
        {"field": "deadline", "label": "Delivery Deadline", "type": "date"},
        {"field": "image_count", "label": "Approximate Images Needed", "type": "number"},
        {"field": "art_direction", "label": "Will you provide art direction?", "type": "boolean"},
        {"field": "special_notes", "label": "Brief / Creative Direction", "type": "textarea"},
    ],
    "events": [
        {
            "field": "event_type",
            "label": "Event Type",
            "type": "select",
            "options": ["corporate", "concert", "party", "conference", "fundraiser", "other"],
        },
        {"field": "venue", "label": "Venue Name", "type": "text"},
        {"field": "duration_hours", "label": "Event Duration (hours)", "type": "number"},
        {"field": "expected_attendance", "label": "Expected Attendance", "type": "number"},
        {"field": "key_moments", "label": "Key Moments to Capture", "type": "textarea"},
        {
            "field": "turnaround",
            "label": "Delivery Turnaround Needed",
            "type": "select",
            "options": ["24h", "48h", "1_week", "standard"],
        },
    ],
    "nature": [
        {
            "field": "purpose",
            "label": "Purpose",
            "type": "select",
            "options": ["personal", "commercial_license", "editorial", "fine_art_print"],
        },
        {"field": "location_request", "label": "Specific Location Request?", "type": "text"},
        {
            "field": "season_preference",
            "label": "Season Preference",
            "type": "select",
            "options": ["spring", "summer", "autumn", "winter", "flexible"],
        },
        {"field": "special_notes", "label": "Additional Notes", "type": "textarea"},
    ],
}


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------

def get_intake_form(genre: str) -> list[dict]:
    """Return form field definitions for the given genre. Unknown genres return []."""
    return INTAKE_FORMS.get(genre.lower(), [])


def validate_intake(genre: str, data: dict[str, Any]) -> list[str]:
    """
    Validate intake data against the genre form.
    Returns a list of error strings (empty list = valid).
    """
    form = get_intake_form(genre)
    errors: list[str] = []
    for field_def in form:
        if field_def.get("required"):
            val = data.get(field_def["field"])
            if val is None or str(val).strip() == "":
                errors.append(f"'{field_def['label']}' is required.")
    return errors


def save_intake(booking_id: int, genre: str, data: dict[str, Any]) -> dict:
    """
    Validate then persist intake responses as JSON in bookings.intake_data.
    Also marks intake_complete = TRUE.
    Returns {"booking_id": ..., "saved": True/False, "errors": [...]}
    """
    errors = validate_intake(genre, data)
    if errors:
        return {"booking_id": booking_id, "saved": False, "errors": errors}

    payload = json.dumps(data)
    with get_db() as conn:
        conn.execute(
            "UPDATE bookings SET intake_data = ?, intake_complete = TRUE WHERE id = ?",
            (payload, booking_id),
        )
    return {"booking_id": booking_id, "saved": True, "errors": []}


def get_intake(booking_id: int) -> Optional[dict]:
    """
    Retrieve saved intake data for a booking.
    Returns parsed dict or None if no intake has been saved.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT intake_data FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
        if not row or not row["intake_data"]:
            return None
        try:
            return json.loads(row["intake_data"])
        except (json.JSONDecodeError, TypeError):
            return None
