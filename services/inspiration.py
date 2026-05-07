"""
services/inspiration.py

Shoot concept generator and content gap detector.
- Concept generator: given genre + season + mood, generates 3 shoot concepts via qwen2.5:14b
- Each concept includes: title, brief description, location suggestion, wardrobe notes,
  lighting approach, best time of day
- Saves to concepts table
- Gap detector: queries calendar_posts to find genres/moods not posted in last 30 days
"""

import json
import re
from datetime import date, timedelta
from typing import Optional

from core.database import get_db
from core.ollama import ollama
from core.config import settings

SYSTEM_CONCEPTS = """You are a creative director for a Hudson Valley, NY photographer.
You generate specific, actionable, visually compelling shoot concepts.
Always respond with valid JSON only — no markdown, no extra text."""


async def generate_concepts(
    genre: str,
    season: Optional[str] = None,
    mood: Optional[str] = None,
    count: int = 3,
) -> list[dict]:
    """
    Generate `count` shoot concepts for the given genre/season/mood.
    Saves each to the concepts table.
    Returns list of concept dicts.
    """
    # Infer season from current date if not provided
    if not season:
        month = date.today().month
        if month in (12, 1, 2):
            season = "winter"
        elif month in (3, 4, 5):
            season = "spring"
        elif month in (6, 7, 8):
            season = "summer"
        else:
            season = "fall"

    mood_str = f" with a {mood} mood" if mood else ""

    prompt = f"""Generate {count} distinct, creative shoot concepts for a {genre} photography session
in Hudson Valley, NY during {season}{mood_str}.

Each concept must be specific and actionable — not generic. Think of real locations, real wardrobe,
real lighting situations in the Hudson Valley region (Catskills, Hudson River, small farms, historic
towns, apple orchards, forest trails, old barns, riverside parks).

Respond with this exact JSON (array of {count} concepts):
[
  {{
    "title": "Short evocative title (4-6 words)",
    "description": "2–3 sentences describing the visual story, emotion, and what makes it unique.",
    "location_suggestion": "Specific type of location in Hudson Valley (e.g., 'apple orchard in peak bloom, Warwick or Marlboro area')",
    "wardrobe_notes": "1–2 sentences on clothing, colors, and styling that fit this concept.",
    "lighting_approach": "1–2 sentences on light quality, direction, and time of day.",
    "best_time_of_day": "morning golden hour / midday / afternoon / evening golden hour / blue hour / overcast"
  }}
]"""

    raw = await ollama.text(prompt, system=SYSTEM_CONCEPTS)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0].strip()

    try:
        concepts_data = json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON array from response
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            concepts_data = json.loads(match.group())
        else:
            concepts_data = []

    if not isinstance(concepts_data, list):
        concepts_data = [concepts_data] if isinstance(concepts_data, dict) else []

    saved_concepts = []
    with get_db() as conn:
        for c in concepts_data:
            if not isinstance(c, dict):
                continue
            cursor = conn.execute(
                """INSERT INTO concepts
                       (title, genre, season, mood, brief, wardrobe_notes, lighting_notes,
                        caption_angle, source, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ai_generated', CURRENT_TIMESTAMP)""",
                (
                    c.get("title", "Untitled Concept"),
                    genre,
                    season,
                    mood,
                    c.get("description", ""),
                    c.get("wardrobe_notes", ""),
                    c.get("lighting_approach", ""),
                    c.get("best_time_of_day", ""),
                ),
            )
            c["id"] = cursor.lastrowid
            c["genre"] = genre
            c["season"] = season
            c["mood"] = mood
            saved_concepts.append(c)

    return saved_concepts


def get_content_gaps(lookback_days: int = 30) -> dict:
    """
    Find genres and moods that haven't been posted to in the last `lookback_days`.
    Also surfaces genres with low scheduled post counts vs. others.
    Returns suggestions.
    """
    cutoff = date.today() - timedelta(days=lookback_days)
    all_genres = settings.genre_list

    with get_db() as conn:
        # Genres posted to in the last N days
        recent_genres = conn.execute(
            """SELECT DISTINCT genre FROM calendar_posts
               WHERE posted_at >= ? AND genre IS NOT NULL""",
            (str(cutoff),),
        ).fetchall()
        recent_genre_set = {r["genre"] for r in recent_genres}

        # Also check images.posted_at
        recent_posted = conn.execute(
            """SELECT DISTINCT genre FROM images
               WHERE posted_at >= ? AND genre IS NOT NULL""",
            (str(cutoff),),
        ).fetchall()
        recent_genre_set |= {r["genre"] for r in recent_posted}

        # Genres not posted at all recently
        missing_genres = [g for g in all_genres if g not in recent_genre_set]

        # Post count per genre in last N days
        genre_counts = conn.execute(
            """SELECT genre, COUNT(*) as posts
               FROM calendar_posts
               WHERE post_date >= ? AND genre IS NOT NULL
               GROUP BY genre ORDER BY posts DESC""",
            (str(cutoff),),
        ).fetchall()
        genre_count_dict = {r["genre"]: r["posts"] for r in genre_counts}

        # Moods posted recently from images
        recent_moods = conn.execute(
            """SELECT DISTINCT mood FROM images
               WHERE posted_at >= ? AND mood IS NOT NULL""",
            (str(cutoff),),
        ).fetchall()
        recent_mood_set = {r["mood"] for r in recent_moods}

        # All moods in library
        all_moods = conn.execute(
            """SELECT DISTINCT mood, COUNT(*) as count
               FROM images WHERE mood IS NOT NULL AND content_ready = TRUE
               GROUP BY mood ORDER BY count DESC LIMIT 20""",
        ).fetchall()
        unexplored_moods = [
            {"mood": r["mood"], "available_images": r["count"]}
            for r in all_moods
            if r["mood"] not in recent_mood_set
        ]

        # Underrepresented genres (have content but few posts)
        content_by_genre = conn.execute(
            """SELECT genre, COUNT(*) as ready_count
               FROM images WHERE content_ready = TRUE AND genre IS NOT NULL
               GROUP BY genre""",
        ).fetchall()
        content_dict = {r["genre"]: r["ready_count"] for r in content_by_genre}

    suggestions = []

    for genre in missing_genres:
        ready = content_dict.get(genre, 0)
        suggestions.append({
            "type": "missing_genre",
            "genre": genre,
            "last_posted": "never" if genre not in recent_genre_set else f">{lookback_days} days ago",
            "content_ready_images": ready,
            "action": f"Generate a {genre} concept and schedule a post",
        })

    for genre in all_genres:
        if genre in recent_genre_set:
            posts = genre_count_dict.get(genre, 0)
            avg = sum(genre_count_dict.values()) / max(len(genre_count_dict), 1)
            if posts < avg * 0.5:
                suggestions.append({
                    "type": "underrepresented_genre",
                    "genre": genre,
                    "posts_in_period": posts,
                    "avg_posts": round(avg, 1),
                    "content_ready_images": content_dict.get(genre, 0),
                    "action": f"Boost {genre} content — only {posts} posts vs avg {round(avg, 1)}",
                })

    return {
        "lookback_days": lookback_days,
        "missing_genres": missing_genres,
        "unexplored_moods": unexplored_moods[:10],
        "suggestions": suggestions,
        "genre_post_counts": genre_count_dict,
    }
