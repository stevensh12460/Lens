"""
content/pillars.py

Content pillar config and rotation logic.
No LLM calls — pure data and date arithmetic.
"""

from datetime import date, timedelta
from typing import Optional

# ── Pillar definitions ────────────────────────────────────────────────────────

PILLARS: dict[str, dict] = {
    "transformation": {
        "description": "Before/after edits, color grade breakdowns, how-I-shot-this",
        "best_formats": ["carousel", "reel"],
        "caption_angle": "Show the transformation — technical process, creative decision",
    },
    "genre_spotlight": {
        "description": "Deep dive into one genre per week on 6-week rotation",
        "best_formats": ["single", "carousel"],
        "caption_angle": "Tell the story of this type of work and what makes it special",
    },
    "bts": {
        "description": "Behind the scenes — location, gear setup, editing process",
        "best_formats": ["reel", "story", "carousel"],
        "caption_angle": "Take them behind the curtain — real, unpolished, human",
    },
    "social_proof": {
        "description": "Testimonials, session recaps, what-it's-like-to-book",
        "best_formats": ["single", "carousel"],
        "caption_angle": "Client voice — what they felt, what they got, why it mattered",
    },
    "personality": {
        "description": "Your voice, opinions, local scenery, background story",
        "best_formats": ["single", "reel"],
        "caption_angle": "First person, honest, opinionated — this is you not a brand",
    },
    "flexible": {
        "description": "Weekend wildcard — highest scoring content-ready image",
        "best_formats": ["single", "carousel", "reel"],
        "caption_angle": "Let the image lead — beauty, story, or mood",
    },
}

# Monday=0 ... Sunday=6 pillar map
DAY_PILLARS: dict[int, str] = {
    0: "transformation",   # Monday
    1: "genre_spotlight",  # Tuesday
    2: "bts",              # Wednesday
    3: "social_proof",     # Thursday
    4: "personality",      # Friday
    5: "flexible",         # Saturday
    6: "flexible",         # Sunday
}

# 6-genre rotation for Tuesday genre_spotlight (ISO week % 6)
GENRE_ROTATION: list[str] = [
    "wedding",
    "portrait",
    "boudoir",
    "commercial",
    "events",
    "nature",
]


# ── Public functions ──────────────────────────────────────────────────────────

def get_pillar_for_day(d: date) -> str:
    """Return the pillar name for any given date based on day-of-week."""
    return DAY_PILLARS.get(d.weekday(), "flexible")


def get_genre_for_week(d: date) -> str:
    """
    Return which genre is in the spotlight for the week containing `d`.
    Uses ISO week number (1-based) minus 1, mod 6.
    """
    week_index = (d.isocalendar()[1] - 1) % len(GENRE_ROTATION)
    return GENRE_ROTATION[week_index]


def get_pillar_config(pillar_name: str) -> dict:
    """Return full pillar config dict. Raises KeyError if pillar not found."""
    if pillar_name not in PILLARS:
        raise KeyError(f"Unknown pillar: {pillar_name!r}. Valid pillars: {list(PILLARS)}")
    return PILLARS[pillar_name]


def get_week_plan(start_date: Optional[date] = None) -> list[dict]:
    """
    Return Mon–Sun plan for the week containing `start_date` (defaults to today).
    Each entry includes: date, day_name, pillar, pillar_config, genre (for genre_spotlight days).
    """
    today = start_date or date.today()
    # Roll back to Monday of this week
    monday = today - timedelta(days=today.weekday())

    plan = []
    for offset in range(7):
        d = monday + timedelta(days=offset)
        pillar = get_pillar_for_day(d)
        genre = get_genre_for_week(d) if pillar == "genre_spotlight" else None
        plan.append(
            {
                "date": d.isoformat(),
                "day_name": d.strftime("%A"),
                "pillar": pillar,
                "genre": genre,
                "pillar_config": PILLARS.get(pillar, {}),
            }
        )
    return plan
