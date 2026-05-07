"""
content/calendar.py

30-day content calendar logic.
Pure code — no LLM calls.
All DB access via core.database.get_db().
"""

from datetime import date, timedelta
from typing import Optional

from core.database import get_db
from content.pillars import (
    get_pillar_for_day,
    get_genre_for_week,
    GENRE_ROTATION,
)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _best_image_for_pillar(
    conn,
    pillar: str,
    genre: Optional[str],
    already_scheduled: set[int],
) -> Optional[dict]:
    """
    Pull the highest-scoring content_ready image that hasn't been scheduled yet.
    For genre_spotlight days, prefer the spotlight genre; fall back to any genre.
    For flexible days (Sat/Sun), use highest composite score regardless of genre.
    Returns a dict with id/genre or None.
    """
    base_query = """
        SELECT id, genre, COALESCE(nima_composite, 0) * 0.6 + COALESCE(quality_score, 0) * 0.4 AS score
        FROM images
        WHERE content_ready = TRUE
          AND posted_at IS NULL
          AND id NOT IN (
              SELECT image_id FROM calendar_posts WHERE image_id IS NOT NULL
          )
        {genre_filter}
        ORDER BY score DESC
        LIMIT 1
    """

    # Build excluded-in-session placeholder (already_scheduled may have new IDs not yet in DB)
    exclude_ids = tuple(already_scheduled) if already_scheduled else (-1,)
    id_placeholders = ",".join("?" * len(exclude_ids))
    extra_exclude = f"AND id NOT IN ({id_placeholders})"

    if pillar == "genre_spotlight" and genre:
        # Try preferred genre first
        query = base_query.format(genre_filter=f"AND genre = ? {extra_exclude}")
        row = conn.execute(query, (genre, *exclude_ids)).fetchone()
        if row:
            return dict(row)
        # Fall back to any genre
        query = base_query.format(genre_filter=extra_exclude)
        row = conn.execute(query, exclude_ids).fetchone()
        return dict(row) if row else None
    else:
        query = base_query.format(genre_filter=extra_exclude)
        row = conn.execute(query, exclude_ids).fetchone()
        return dict(row) if row else None


# ── Public functions ──────────────────────────────────────────────────────────

def get_calendar(days: int = 30) -> dict[str, list[dict]]:
    """
    Return all calendar_posts for the next N days, grouped by ISO date string.
    Each date key maps to a list of post dicts.
    """
    today = date.today()
    end = today + timedelta(days=days - 1)

    with get_db() as conn:
        rows = conn.execute(
            """SELECT cp.*, i.file_path, i.genre AS image_genre, i.mood, i.nima_composite, i.quality_score
               FROM calendar_posts cp
               LEFT JOIN images i ON cp.image_id = i.id
               WHERE cp.post_date BETWEEN ? AND ?
               ORDER BY cp.post_date ASC, cp.id ASC""",
            (str(today), str(end)),
        ).fetchall()

    result: dict[str, list[dict]] = {}
    for row in rows:
        d = str(row["post_date"])
        result.setdefault(d, []).append(dict(row))
    return result


def fill_calendar(days: int = 30) -> dict:
    """
    DISABLED — never auto-pick photos for the IG calendar. Brand risk.
    Body gutted so any accidental future caller is a no-op.
    Use the Post Candidate Pool to pick each post manually.
    """
    return {
        "posts_created": 0,
        "dates_skipped_no_content": [],
        "posts": [],
        "disabled": True,
        "reason": "Auto-fill is permanently disabled by user policy.",
    }


def get_today() -> Optional[dict]:
    """Return today's scheduled calendar post (first one if multiple exist), or None."""
    today_str = str(date.today())
    with get_db() as conn:
        row = conn.execute(
            """SELECT cp.*, i.file_path, i.genre AS image_genre, i.mood
               FROM calendar_posts cp
               LEFT JOIN images i ON cp.image_id = i.id
               WHERE cp.post_date = ?
               ORDER BY cp.id ASC
               LIMIT 1""",
            (today_str,),
        ).fetchone()
    return dict(row) if row else None


def get_week(week_offset: int = 0) -> list[dict]:
    """
    Return full week view (Mon–Sun) for the current week + week_offset weeks.
    Each item contains the date, pillar, expected genre, and any existing calendar post.
    """
    today = date.today()
    # Find this week's Monday
    monday = today - timedelta(days=today.weekday())
    # Apply offset
    monday = monday + timedelta(weeks=week_offset)

    dates_in_week = [monday + timedelta(days=i) for i in range(7)]
    date_strs = [str(d) for d in dates_in_week]

    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT cp.*, i.file_path, i.genre AS image_genre, i.mood
                FROM calendar_posts cp
                LEFT JOIN images i ON cp.image_id = i.id
                WHERE cp.post_date IN ({','.join('?' * len(date_strs))})
                ORDER BY cp.post_date ASC, cp.id ASC""",
            date_strs,
        ).fetchall()

    # Index DB posts by date
    posts_by_date: dict[str, list[dict]] = {}
    for row in rows:
        d = str(row["post_date"])
        posts_by_date.setdefault(d, []).append(dict(row))

    result = []
    for d in dates_in_week:
        d_str = str(d)
        pillar = get_pillar_for_day(d)
        genre = get_genre_for_week(d) if pillar == "genre_spotlight" else None
        result.append(
            {
                "date": d_str,
                "day_name": d.strftime("%A"),
                "pillar": pillar,
                "expected_genre": genre,
                "posts": posts_by_date.get(d_str, []),
            }
        )
    return result


def mark_posted(post_id: int, platform: str) -> dict:
    """
    Mark a calendar post as posted. Sets status='posted' and posted_at=now.
    Also updates images.posted_at and images.posted_to for the linked image.
    """
    with get_db() as conn:
        # Verify the post exists
        row = conn.execute(
            "SELECT id, image_id FROM calendar_posts WHERE id = ?", (post_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"calendar_post id={post_id} not found")

        conn.execute(
            """UPDATE calendar_posts
               SET status = 'posted', posted_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (post_id,),
        )
        if row["image_id"]:
            conn.execute(
                """UPDATE images
                   SET posted_at = CURRENT_TIMESTAMP, posted_to = ?
                   WHERE id = ?""",
                (platform, row["image_id"]),
            )

    return {"status": "posted", "post_id": post_id, "platform": platform}
