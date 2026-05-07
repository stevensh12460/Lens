"""
services/social_queue.py

Social media content queue manager.
- Pulls content_ready images that haven't been posted yet (posted_at IS NULL)
- Assigns content pillar based on day of week
- Genre spotlight rotates through 6 genres on 6-week cycle
- Creates calendar_posts entries for unscheduled content-ready images
- Returns queue depth per pillar
"""

from datetime import date, timedelta
from typing import Optional

from core.database import get_db
from core.config import settings

# Monday=0 ... Friday=4, Saturday=5, Sunday=6
DAY_PILLARS = {
    0: "transformation",     # Monday
    1: "genre_spotlight",    # Tuesday
    2: "bts",                # Wednesday
    3: "social_proof",       # Thursday
    4: "personality",        # Friday
    5: "weekend_beauty",     # Saturday (bonus)
    6: "inspiration",        # Sunday (bonus)
}

# 6-genre rotation for Tuesday genre_spotlight (week index 0–5)
GENRE_ROTATION = [
    "wedding",
    "portrait",
    "boudoir",
    "commercial",
    "events",
    "nature",
]


def _pillar_for_date(d: date) -> str:
    return DAY_PILLARS.get(d.weekday(), "transformation")


def _genre_spotlight_for_date(d: date) -> str:
    """Determine which genre is spotlighted in a given week using ISO week number mod 6."""
    week_index = (d.isocalendar()[1] - 1) % len(GENRE_ROTATION)
    return GENRE_ROTATION[week_index]


def get_queue_depth() -> dict:
    """
    Return count of unscheduled content-ready images per pillar bucket
    (based on today's day-of-week mapping) and total unposted.
    """
    with get_db() as conn:
        # Total content-ready, not yet posted, not yet in calendar
        unposted = conn.execute(
            """SELECT COUNT(*) FROM images
               WHERE content_ready = TRUE AND posted_at IS NULL""",
        ).fetchone()[0]

        # Depth per genre
        by_genre = conn.execute(
            """SELECT genre, COUNT(*) as count
               FROM images
               WHERE content_ready = TRUE AND posted_at IS NULL
               GROUP BY genre ORDER BY count DESC""",
        ).fetchall()

        # Scheduled but not yet posted calendar posts
        scheduled = conn.execute(
            """SELECT pillar, COUNT(*) as count
               FROM calendar_posts
               WHERE posted_at IS NULL
               GROUP BY pillar ORDER BY count DESC""",
        ).fetchall()

        # Queue depth per day-of-week pillar over next 7 days
        today = date.today()
        week_pillars = {}
        for offset in range(7):
            d = today + timedelta(days=offset)
            pillar = _pillar_for_date(d)
            week_pillars[d.isoformat()] = {
                "pillar": pillar,
                "genre_spotlight": _genre_spotlight_for_date(d) if pillar == "genre_spotlight" else None,
            }

    return {
        "total_unposted_ready": unposted,
        "by_genre": [dict(r) for r in by_genre],
        "scheduled_calendar_posts": [dict(r) for r in scheduled],
        "next_7_days": week_pillars,
    }



# Pillar preferences for morning vs evening slots
MORNING_PILLARS = {"transformation", "genre_spotlight", "social_proof"}
EVENING_PILLARS = {"bts", "personality", "weekend_beauty", "inspiration"}

# Scoring: prefer grid_fit_score if available, else composite fallback
_SCORE_EXPR = """COALESCE(
    grid_fit_score,
    COALESCE(nima_composite, 0) * 0.6 + COALESCE(quality_score, 0) * 0.4
) DESC"""


# Genres for auto-fill by default — nature/landscape only until expanded manually
DEFAULT_SAFE_GENRES = {"nature", "landscape"}


def fill_queue(
    days_ahead: int = 14,
    posts_per_day: int = 2,
    start_date: Optional[date] = None,
    included_genres: Optional[list] = None,
) -> dict:
    """
    DISABLED — never auto-pick photos for the IG calendar. Brand risk.
    Body gutted so any accidental future caller is a no-op.
    """
    return {
        "posts_created": 0,
        "dates_skipped_no_content": [],
        "posts": [],
        "disabled": True,
        "reason": "Auto-fill is permanently disabled by user policy.",
    }
    # Unreachable legacy body retained below for reference only.
    today = start_date or date.today()
    created = []
    skipped_no_content = []

    # Genre allow-list: default to safe genres, override if caller specifies
    genre_allow = set(included_genres) if included_genres else DEFAULT_SAFE_GENRES

    with get_db() as conn:
        for offset in range(days_ahead):
            target_date = today + timedelta(days=offset)
            pillar = _pillar_for_date(target_date)
            genre_spotlight = (
                _genre_spotlight_for_date(target_date)
                if pillar == "genre_spotlight"
                else None
            )

            # Check existing posts for this date and which slots are filled
            existing = conn.execute(
                "SELECT post_time FROM calendar_posts WHERE post_date = ?",
                (str(target_date),),
            ).fetchall()
            existing_times = {r["post_time"] for r in existing if r["post_time"]}
            existing_count = len(existing)

            slots_needed = posts_per_day - existing_count
            if slots_needed <= 0:
                continue

            # Determine which time slots need filling
            slots_to_fill = []
            if posts_per_day >= 2:
                if "morning" not in existing_times:
                    slots_to_fill.append("morning")
                if "evening" not in existing_times:
                    slots_to_fill.append("evening")
            else:
                if "morning" not in existing_times:
                    slots_to_fill.append("morning")

            # Cap to slots_needed
            slots_to_fill = slots_to_fill[:slots_needed]
            if not slots_to_fill:
                continue

            for slot_idx, slot_time in enumerate(slots_to_fill):
                # Select pillar for this slot
                if slot_time == "morning":
                    slot_pillar = pillar if pillar in MORNING_PILLARS else "transformation"
                else:
                    slot_pillar = pillar if pillar in EVENING_PILLARS else "personality"

                # For genre_spotlight, only apply genre filter on the spotlight slot
                slot_genre_filter = genre_spotlight if slot_pillar == "genre_spotlight" else None

                # Pick the best image for this slot
                # Build genre placeholders for the allow-list
                genre_placeholders = ",".join("?" * len(genre_allow))
                base_filter = f"""content_ready = TRUE
                             AND posted_at IS NULL
                             AND genre IN ({genre_placeholders})
                             AND id NOT IN (SELECT image_id FROM calendar_posts WHERE image_id IS NOT NULL)"""
                genre_params = list(genre_allow)

                params: list = []
                if slot_genre_filter and slot_genre_filter in genre_allow:
                    # Spotlight genre must be in allow-list to apply
                    query = f"SELECT id, genre FROM images WHERE {base_filter} AND genre = ? ORDER BY {_SCORE_EXPR} LIMIT 1"
                    params = genre_params + [slot_genre_filter]
                else:
                    query = f"SELECT id, genre FROM images WHERE {base_filter} ORDER BY {_SCORE_EXPR} LIMIT 1"
                    params = genre_params

                candidate = conn.execute(query, params).fetchone()

                # Fallback: spotlight genre not available — any allowed genre
                if not candidate and slot_genre_filter:
                    fallback_query = f"SELECT id, genre FROM images WHERE {base_filter} ORDER BY {_SCORE_EXPR} LIMIT 1"
                    candidate = conn.execute(fallback_query, genre_params).fetchone()

                if not candidate:
                    if slot_idx == 0:
                        skipped_no_content.append(str(target_date))
                    continue

                image_id = candidate["id"]
                genre = candidate["genre"]
                cursor = conn.execute(
                    """INSERT INTO calendar_posts
                           (post_date, post_time, pillar, genre, image_id, status, created_at)
                       VALUES (?, ?, ?, ?, ?, 'planned', CURRENT_TIMESTAMP)""",
                    (str(target_date), slot_time, slot_pillar, genre or slot_genre_filter, image_id),
                )
                created.append({
                    "calendar_post_id": cursor.lastrowid,
                    "post_date": str(target_date),
                    "post_time": slot_time,
                    "pillar": slot_pillar,
                    "genre": genre or slot_genre_filter,
                    "image_id": image_id,
                })

    return {
        "posts_created": len(created),
        "dates_skipped_no_content": skipped_no_content,
        "posts": created,
    }


def get_upcoming_schedule(days: int = 7) -> list[dict]:
    """Return the scheduled calendar posts for the next N days."""
    today = date.today()
    end = today + timedelta(days=days)
    with get_db() as conn:
        rows = conn.execute(
            """SELECT cp.*, i.file_path, i.genre as image_genre, i.mood
               FROM calendar_posts cp
               LEFT JOIN images i ON cp.image_id = i.id
               WHERE cp.post_date BETWEEN ? AND ?
               ORDER BY cp.post_date ASC""",
            (str(today), str(end)),
        ).fetchall()
    return [dict(r) for r in rows]
