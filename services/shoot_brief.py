"""
services/shoot_brief.py

Shoot brief generator.
- Takes client_id (optional), shoot_date, location, genre as input
- Generates: shot list by category, gear checklist, golden hour time for Hudson Valley NY,
  weather note placeholder
- Uses qwen2.5:14b to generate creative shot list and concepts
- Saves to shoot_briefs table
"""

import json
import math
import re
from datetime import date, datetime
from typing import Optional

from core.database import get_db
from core.ollama import ollama

# Hudson Valley, NY approximate coordinates
HV_LAT = 41.7  # degrees North
HV_LNG = -73.9  # degrees West

# Ensure shoot_briefs table exists
_SHOOT_BRIEFS_SCHEMA = """
CREATE TABLE IF NOT EXISTS shoot_briefs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id       INTEGER REFERENCES clients(id),
    shoot_date      DATE,
    location        TEXT,
    genre           TEXT,
    golden_hour_time TEXT,
    shot_list       TEXT,
    gear_checklist  TEXT,
    concepts        TEXT,
    weather_note    TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


def _ensure_table() -> None:
    with get_db() as conn:
        conn.executescript(_SHOOT_BRIEFS_SCHEMA)


def _calculate_golden_hour(shoot_date: date, lat: float = HV_LAT, lng: float = HV_LNG) -> dict:
    """
    Calculate approximate sunrise/sunset and golden hour windows for a given date
    at the given lat/lng using the NOAA solar calculation method.
    Returns dict with sunrise, sunset, morning_golden, evening_golden as HH:MM strings (local time).

    This is an approximation accurate to within ~a few minutes for Hudson Valley.
    All times are in local civil time (UTC-5 in winter, UTC-4 in summer — EST/EDT).
    """
    # Day of year
    doy = shoot_date.timetuple().tm_yday

    # Fractional year (radians)
    gamma = 2 * math.pi / 365 * (doy - 1 + (12 - 12) / 24)

    # Equation of time (minutes)
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.04089 * math.sin(2 * gamma)
    )

    # Solar declination (radians)
    decl = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )

    lat_rad = math.radians(lat)

    # Hour angle at sunrise/sunset (radians) — 90.833° accounts for refraction
    cos_ha = math.cos(math.radians(90.833)) / (math.cos(lat_rad) * math.cos(decl)) - math.tan(lat_rad) * math.tan(decl)
    cos_ha = max(-1.0, min(1.0, cos_ha))  # clamp
    ha = math.degrees(math.acos(cos_ha))

    # Solar noon in UTC minutes from midnight
    # Standard meridian for UTC-5 is 75°W; Hudson Valley ~74°W
    solar_noon_utc = 720 - 4 * lng - eqtime  # minutes from UTC midnight

    # Sunrise/sunset in UTC minutes
    sunrise_utc = solar_noon_utc - ha * 4
    sunset_utc = solar_noon_utc + ha * 4

    # Determine UTC offset (rough DST: Mar 2nd Sunday to Nov 1st Sunday)
    # For simplicity: April–October = EDT (UTC-4), else EST (UTC-5)
    month = shoot_date.month
    utc_offset = -4 if 4 <= month <= 10 else -5

    def utc_min_to_local(utc_min: float) -> str:
        local_min = utc_min + utc_offset * 60
        local_min = local_min % (24 * 60)
        h = int(local_min // 60)
        m = int(local_min % 60)
        period = "AM" if h < 12 else "PM"
        display_h = h % 12 or 12
        return f"{display_h}:{m:02d} {period}"

    def add_minutes(time_str: str, delta: int) -> str:
        """Add delta minutes to a HH:MM AM/PM string."""
        if "AM" in time_str:
            period = "AM"
        else:
            period = "PM"
        parts = time_str.replace(" AM", "").replace(" PM", "").split(":")
        h, m = int(parts[0]), int(parts[1])
        if period == "PM" and h != 12:
            h += 12
        elif period == "AM" and h == 12:
            h = 0
        total = h * 60 + m + delta
        total = total % (24 * 60)
        nh = int(total // 60)
        nm = int(total % 60)
        np_ = "AM" if nh < 12 else "PM"
        display_nh = nh % 12 or 12
        return f"{display_nh}:{nm:02d} {np_}"

    sunrise_local = utc_min_to_local(sunrise_utc)
    sunset_local = utc_min_to_local(sunset_utc)

    # Golden hour: ~30–45 minutes after sunrise, ~60 minutes before sunset
    morning_golden_start = sunrise_local
    morning_golden_end = add_minutes(sunrise_local, 45)
    evening_golden_start = add_minutes(sunset_local, -60)
    evening_golden_end = sunset_local

    return {
        "sunrise": sunrise_local,
        "sunset": sunset_local,
        "morning_golden_hour": f"{morning_golden_start} – {morning_golden_end}",
        "evening_golden_hour": f"{evening_golden_start} – {evening_golden_end}",
        "recommended": f"Evening golden hour: {evening_golden_start} – {evening_golden_end}",
    }


def _gear_checklist(genre: str) -> list[str]:
    """Return standard gear checklist for the given genre."""
    base = [
        "Primary camera body",
        "Backup camera body",
        "Extra batteries (fully charged)",
        "Extra memory cards (formatted)",
        "Lens cleaning kit",
        "Black gaffer tape",
        "Multi-tool",
        "Phone + charger",
        "Water + snacks",
    ]
    genre_gear = {
        "wedding": [
            "24-70mm f/2.8 zoom",
            "70-200mm f/2.8 telephoto",
            "35mm f/1.4 prime",
            "85mm f/1.4 portrait prime",
            "External flash x2 (with batteries)",
            "Flash triggers + receivers",
            "Reflector (5-in-1)",
            "Monopod for ceremony",
            "Second shooter kit",
            "Venue walk-through checklist",
        ],
        "portrait": [
            "85mm f/1.4 or 85mm f/1.8",
            "50mm f/1.4 prime",
            "Reflector (5-in-1, silver + white)",
            "Portable LED panel (optional)",
            "Stool or apple box",
        ],
        "boudoir": [
            "85mm f/1.4 portrait prime",
            "50mm f/1.4",
            "Continuous LED panels x2",
            "Diffusion material / softbox",
            "Posing guide reference",
            "Privacy screen or blinds check",
            "Robe or wrap for client comfort",
        ],
        "commercial": [
            "24-70mm f/2.8",
            "Tilt-shift or macro for product",
            "Strobe lighting kit x2",
            "Light stands x4",
            "Sandbags",
            "Color checker / gray card",
            "Tethering cable + laptop",
            "Shot list printout",
        ],
        "events": [
            "24-70mm f/2.8",
            "70-200mm f/2.8",
            "50mm f/1.8 fast prime",
            "Speedlight x2",
            "Extra flash batteries",
            "Wide-angle 16-35mm",
        ],
        "nature": [
            "16-35mm wide angle",
            "70-200mm telephoto",
            "100-400mm super-tele (optional)",
            "Tripod + ball head",
            "Remote shutter release",
            "ND filter set (3, 6, 10 stop)",
            "Polarizing filter",
            "Weatherproof camera cover",
            "Headlamp",
            "Hiking boots / weatherproof footwear",
        ],
    }
    return base + genre_gear.get(genre.lower(), ["Standard portrait prime", "Reflector"])


SYSTEM_BRIEF = """You are a professional photographer's creative assistant specializing in Hudson Valley, NY photography.
You generate detailed, actionable shoot briefs.
Always respond with valid JSON only — no markdown, no extra text."""


async def _generate_shot_list_and_concepts(
    genre: str,
    location: str,
    shoot_date: date,
    client_history: Optional[list[str]] = None,
) -> dict:
    """Use qwen2.5:14b to generate shot list and concepts."""
    history_note = ""
    if client_history:
        history_note = f"\nClient previously shot: {', '.join(client_history[:10])}. Avoid repeating these concepts."

    prompt = f"""Generate a detailed shoot brief for a {genre} photography session.

Location: {location} (Hudson Valley, NY area)
Date: {shoot_date.strftime('%B %d, %Y')}
Photographer base: Hudson Valley, NY{history_note}

Generate:
1. shot_list: A categorized list of shots. Each category has a name and 3–5 specific shots.
   Categories appropriate to {genre} photography (e.g., for wedding: Preparation, Ceremony, Portraits, Details, Reception).
2. concepts: 2–3 creative, specific concepts not just generic poses. Each concept has a title and 2-sentence description.

Respond with this exact JSON:
{{
  "shot_list": [
    {{
      "category": "Category Name",
      "shots": ["Shot description 1", "Shot description 2", ...]
    }}
  ],
  "concepts": [
    {{
      "title": "Concept title",
      "description": "2-sentence creative description of this specific concept."
    }}
  ]
}}"""

    raw = await ollama.text(prompt, system=SYSTEM_BRIEF)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0].strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {
            "shot_list": [{"category": "General", "shots": ["Standard coverage shots"]}],
            "concepts": [{"title": "Natural Light Portraits", "description": "Utilise the available natural light."}],
        }


async def generate_shoot_brief(
    shoot_date: date,
    location: str,
    genre: str,
    client_id: Optional[int] = None,
) -> dict:
    """
    Generate a complete shoot brief and save to shoot_briefs table.
    Returns the full brief dict including id.
    """
    _ensure_table()

    # Fetch client history if provided
    client_history: list[str] = []
    client_name = None
    if client_id:
        with get_db() as conn:
            client = conn.execute(
                "SELECT name FROM clients WHERE id = ?", (client_id,)
            ).fetchone()
            if client:
                client_name = client["name"]

            # Get concepts from previous shoots
            previous_briefs = conn.execute(
                """SELECT sb.concepts FROM shoot_briefs sb WHERE sb.client_id = ?
                   ORDER BY sb.created_at DESC LIMIT 5""",
                (client_id,),
            ).fetchall()
            for pb in previous_briefs:
                if pb["concepts"]:
                    try:
                        concepts_data = json.loads(pb["concepts"])
                        if isinstance(concepts_data, list):
                            for c in concepts_data:
                                if isinstance(c, dict) and "title" in c:
                                    client_history.append(c["title"])
                    except (json.JSONDecodeError, TypeError):
                        pass

    # Calculate golden hour
    golden_hour = _calculate_golden_hour(shoot_date)
    golden_hour_time = golden_hour["recommended"]

    # Generate shot list and concepts via LLM
    ai_result = await _generate_shot_list_and_concepts(
        genre=genre,
        location=location,
        shoot_date=shoot_date,
        client_history=client_history or None,
    )

    shot_list = ai_result.get("shot_list", [])
    concepts = ai_result.get("concepts", [])
    gear = _gear_checklist(genre)

    weather_note = (
        f"Check weather forecast for {shoot_date.strftime('%B %d')} in Hudson Valley, NY. "
        "Have contingency plan for rain. Golden hour quality depends on cloud cover — "
        "light overcast can produce beautiful diffused light."
    )

    # Save to DB
    shot_list_json = json.dumps(shot_list)
    gear_json = json.dumps(gear)
    concepts_json = json.dumps(concepts)

    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO shoot_briefs
                   (client_id, shoot_date, location, genre, golden_hour_time,
                    shot_list, gear_checklist, concepts, weather_note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (
                client_id,
                str(shoot_date),
                location,
                genre,
                golden_hour_time,
                shot_list_json,
                gear_json,
                concepts_json,
                weather_note,
            ),
        )
        brief_id = cursor.lastrowid

    return {
        "id": brief_id,
        "client_id": client_id,
        "client_name": client_name,
        "shoot_date": str(shoot_date),
        "location": location,
        "genre": genre,
        "golden_hour": golden_hour,
        "shot_list": shot_list,
        "gear_checklist": gear,
        "concepts": concepts,
        "weather_note": weather_note,
    }


def get_brief(brief_id: int) -> Optional[dict]:
    """Retrieve a saved brief by ID."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM shoot_briefs WHERE id = ?", (brief_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    for field in ("shot_list", "gear_checklist", "concepts"):
        if d.get(field):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return d
