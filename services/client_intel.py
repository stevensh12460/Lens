"""
services/client_intel.py

Client intelligence profile builder.
Uses qwen2.5:14b to parse notes and extract structured intel about clients.
Profiles are cached in the client_profiles table.
"""

import asyncio
import json
from datetime import datetime, date
from typing import Optional

from core.database import get_db
from core.ollama import ollama

# ── Schema ──────────────────────────────────────────────────────────────────────

_CLIENT_PROFILES_SCHEMA = """
CREATE TABLE IF NOT EXISTS client_profiles (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id               INTEGER UNIQUE REFERENCES clients(id),
    communication_style     TEXT,
    style_preferences       TEXT,
    special_considerations  TEXT,
    rebooking_likelihood    TEXT,
    vip_worthy              BOOLEAN DEFAULT FALSE,
    suggested_next_session  TEXT,
    raw_analysis            TEXT,
    generated_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME
)
"""


def _ensure_schema() -> None:
    with get_db() as conn:
        conn.executescript(_CLIENT_PROFILES_SCHEMA)


# ── Internal helpers ─────────────────────────────────────────────────────────────

def _gather_client_context(client_id: int) -> dict:
    """Gather all available context for a client from the DB."""
    with get_db() as conn:
        client = conn.execute(
            "SELECT * FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
        if not client:
            return {}

        bookings = conn.execute(
            """
            SELECT id, genre, shoot_date, package, amount, status,
                   source, balance_paid, booked_date
            FROM bookings
            WHERE client_id = ?
            ORDER BY shoot_date DESC
            """,
            (client_id,),
        ).fetchall()

        shoots = conn.execute(
            """
            SELECT s.id, s.shoot_date, s.genre, s.location, s.notes,
                   s.total_images, s.delivered_at
            FROM shoots s
            WHERE s.client_id = ?
            ORDER BY s.shoot_date DESC
            """,
            (client_id,),
        ).fetchall()

        # Images from this client's shoots (sample of top portfolio_worthy)
        sample_images = conn.execute(
            """
            SELECT i.genre, i.mood, i.lighting, i.subject_type, i.tags, i.caption_draft
            FROM images i
            JOIN shoots s ON s.id = i.shoot_id
            WHERE s.client_id = ? AND i.portfolio_worthy = TRUE
            ORDER BY COALESCE(i.quality_score, i.nima_composite, 0) DESC
            LIMIT 20
            """,
            (client_id,),
        ).fetchall()

        # Referred by
        referred_by = None
        if client["referred_by"]:
            ref_client = conn.execute(
                "SELECT name FROM clients WHERE id = ?", (client["referred_by"],)
            ).fetchone()
            if ref_client:
                referred_by = ref_client["name"]

    return {
        "client": dict(client),
        "bookings": [dict(b) for b in bookings],
        "shoots": [dict(s) for s in shoots],
        "sample_images": [dict(i) for i in sample_images],
        "referred_by": referred_by,
    }


def _build_prompt(context: dict) -> str:
    client = context["client"]
    bookings = context["bookings"]
    shoots = context["shoots"]
    images = context["sample_images"]
    referred_by = context.get("referred_by")

    booking_summary = "\n".join([
        f"  - {b.get('shoot_date', 'unknown date')}: {b.get('genre', 'unknown genre')}, "
        f"${b.get('amount', 0)}, status={b.get('status', '?')}, source={b.get('source', '?')}"
        for b in bookings
    ]) or "  (no bookings)"

    shoot_notes = "\n".join([
        f"  - {s.get('shoot_date', '?')} [{s.get('genre', '?')}]: {s.get('notes', 'no notes')}"
        for s in shoots if s.get("notes")
    ]) or "  (no shoot notes)"

    image_aesthetics = ", ".join(set(
        f"{i.get('mood', '')}/{i.get('lighting', '')}"
        for i in images if i.get("mood") or i.get("lighting")
    )) or "(no image data)"

    today = date.today().isoformat()
    last_booked = client.get("last_booked") or "never"
    days_since = ""
    if client.get("last_booked"):
        try:
            delta = (date.today() - date.fromisoformat(client["last_booked"])).days
            days_since = f" ({delta} days ago)"
        except (ValueError, TypeError):
            pass

    prompt = f"""You are analyzing a photography client profile to extract structured business intelligence.

CLIENT: {client.get('name', 'Unknown')}
Email: {client.get('email', 'N/A')}
Notes: {client.get('notes', 'None')}
Preferences: {client.get('preferences', 'None')}
First booked: {client.get('first_booked', 'unknown')}
Last booked: {last_booked}{days_since}
Total bookings: {client.get('total_bookings', 0)}
Total revenue: ${client.get('total_revenue', 0)}
Referred by: {referred_by or 'not referred'}

BOOKING HISTORY:
{booking_summary}

SHOOT NOTES:
{shoot_notes}

TOP IMAGE AESTHETICS (mood/lighting from best images):
{image_aesthetics}

Today's date: {today}

Based on all of this, respond with ONLY a JSON object (no markdown, no explanation) with these exact fields:
{{
  "communication_style": "brief description of how they likely communicate (e.g. 'quick responder, detail-oriented', 'casual and warm', 'formal, needs clear timelines')",
  "style_preferences": "their aesthetic preferences based on bookings and notes (e.g. 'natural light, candid moments, soft tones')",
  "special_considerations": "anything notable for working with them (allergies, timing needs, location preferences, family dynamics, etc.) — 'none noted' if nothing stands out",
  "rebooking_likelihood": "high, medium, or low — based on revenue, recency, loyalty signals",
  "vip_worthy": true or false — true if they're a high-value long-term client worth VIP treatment,
  "suggested_next_session": "the most logical next session type to pitch them based on their history and timeline",
  "reasoning": "1-2 sentences on your key observations"
}}"""
    return prompt


# ── Public API ────────────────────────────────────────────────────────────────────

async def build_client_profile(client_id: int) -> dict:
    """
    Build (or rebuild) an intelligence profile for a client using qwen2.5:14b.
    Saves to client_profiles table and returns the profile.
    """
    _ensure_schema()

    context = _gather_client_context(client_id)
    if not context:
        return {"error": f"Client {client_id} not found"}

    prompt = _build_prompt(context)

    try:
        raw = await ollama.text(
            prompt=prompt,
            system=(
                "You are a photography business intelligence assistant. "
                "Always respond with valid JSON only — no markdown, no explanation."
            ),
        )
        # Strip code fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw.rsplit("```", 1)[0].strip()

        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        return {"error": f"LLM returned invalid JSON: {e}", "raw": raw}
    except Exception as e:
        return {"error": f"Ollama call failed: {e}"}

    now = datetime.now().isoformat()

    with get_db() as conn:
        # Upsert
        existing = conn.execute(
            "SELECT id FROM client_profiles WHERE client_id = ?", (client_id,)
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE client_profiles SET
                    communication_style    = ?,
                    style_preferences      = ?,
                    special_considerations = ?,
                    rebooking_likelihood   = ?,
                    vip_worthy             = ?,
                    suggested_next_session = ?,
                    raw_analysis           = ?,
                    updated_at             = ?
                WHERE client_id = ?
                """,
                (
                    parsed.get("communication_style"),
                    parsed.get("style_preferences"),
                    parsed.get("special_considerations"),
                    parsed.get("rebooking_likelihood"),
                    parsed.get("vip_worthy", False),
                    parsed.get("suggested_next_session"),
                    json.dumps(parsed),
                    now,
                    client_id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO client_profiles
                    (client_id, communication_style, style_preferences,
                     special_considerations, rebooking_likelihood, vip_worthy,
                     suggested_next_session, raw_analysis, generated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    client_id,
                    parsed.get("communication_style"),
                    parsed.get("style_preferences"),
                    parsed.get("special_considerations"),
                    parsed.get("rebooking_likelihood"),
                    parsed.get("vip_worthy", False),
                    parsed.get("suggested_next_session"),
                    json.dumps(parsed),
                    now,
                ),
            )

        profile = conn.execute(
            "SELECT * FROM client_profiles WHERE client_id = ?", (client_id,)
        ).fetchone()

    return dict(profile)


def get_client_profile(client_id: int) -> Optional[dict]:
    """Retrieve a saved client profile from the DB."""
    _ensure_schema()
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT cp.*, c.name AS client_name, c.email AS client_email
            FROM client_profiles cp
            JOIN clients c ON c.id = cp.client_id
            WHERE cp.client_id = ?
            """,
            (client_id,),
        ).fetchone()
    if not row:
        return None
    return dict(row)


def get_vip_clients() -> list[dict]:
    """Return all clients flagged as VIP worthy."""
    _ensure_schema()
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT cp.*, c.name AS client_name, c.email AS client_email,
                   c.total_bookings, c.total_revenue, c.last_booked
            FROM client_profiles cp
            JOIN clients c ON c.id = cp.client_id
            WHERE cp.vip_worthy = TRUE
            ORDER BY c.total_revenue DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_rebooking_candidates() -> list[dict]:
    """
    Clients with high rebooking likelihood who haven't booked in 90+ days.
    """
    _ensure_schema()
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                cp.*,
                c.name          AS client_name,
                c.email         AS client_email,
                c.phone         AS client_phone,
                c.total_bookings,
                c.total_revenue,
                c.last_booked,
                CAST(julianday('now') - julianday(c.last_booked) AS INTEGER) AS days_since_last_booking
            FROM client_profiles cp
            JOIN clients c ON c.id = cp.client_id
            WHERE cp.rebooking_likelihood = 'high'
              AND (
                c.last_booked IS NULL
                OR julianday('now') - julianday(c.last_booked) >= 90
              )
            ORDER BY days_since_last_booking DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]
