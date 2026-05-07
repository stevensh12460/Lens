"""
services/repurpose.py

Repurposing opportunity detector.
- Finds shoots where social-ready images exist but fewer than 50% have been posted
- Returns: shoot_id, shoot_date, genre, total_social_ready, total_posted, unused_count
- Sorted by unused_count DESC — biggest opportunity first
"""

from typing import Optional

from core.database import get_db


def get_repurpose_opportunities(min_unused: int = 1) -> list[dict]:
    """
    Find shoots with untapped content.

    A shoot qualifies if:
    - It has at least 1 content_ready image
    - Less than 50% of those images have been posted (posted_at IS NOT NULL)

    Returns sorted by unused_count DESC.
    """
    with get_db() as conn:
        rows = conn.execute(
            """SELECT
                  s.id as shoot_id,
                  s.shoot_date,
                  s.genre,
                  s.location,
                  c.name as client_name,
                  COUNT(i.id) as total_social_ready,
                  SUM(CASE WHEN i.posted_at IS NOT NULL THEN 1 ELSE 0 END) as total_posted,
                  COUNT(i.id) - SUM(CASE WHEN i.posted_at IS NOT NULL THEN 1 ELSE 0 END) as unused_count,
                  ROUND(
                      CAST(SUM(CASE WHEN i.posted_at IS NOT NULL THEN 1 ELSE 0 END) AS REAL)
                      / COUNT(i.id) * 100, 1
                  ) as pct_posted,
                  ROUND(AVG(COALESCE(i.nima_composite, 0) * 0.6 + COALESCE(i.quality_score, 0) * 0.4), 3) as avg_quality
               FROM shoots s
               JOIN images i ON i.shoot_id = s.id
               LEFT JOIN clients c ON s.client_id = c.id
               WHERE i.content_ready = TRUE
               GROUP BY s.id
               HAVING total_social_ready > 0
                  AND pct_posted < 50
                  AND unused_count >= ?
               ORDER BY unused_count DESC""",
            (min_unused,),
        ).fetchall()

    return [dict(r) for r in rows]


def get_repurpose_summary() -> dict:
    """
    High-level summary of repurposing opportunities:
    - Total unused social-ready images across all shoots
    - Breakdown by genre
    - Top 5 shoots with most unused content
    """
    opportunities = get_repurpose_opportunities(min_unused=1)

    total_unused = sum(r["unused_count"] for r in opportunities)
    total_shoots = len(opportunities)

    # By genre
    by_genre: dict = {}
    for r in opportunities:
        genre = r.get("genre") or "unknown"
        if genre not in by_genre:
            by_genre[genre] = {"shoot_count": 0, "unused_images": 0}
        by_genre[genre]["shoot_count"] += 1
        by_genre[genre]["unused_images"] += r["unused_count"]

    by_genre_list = sorted(
        [{"genre": k, **v} for k, v in by_genre.items()],
        key=lambda x: x["unused_images"],
        reverse=True,
    )

    return {
        "total_unused_images": total_unused,
        "shoots_with_opportunity": total_shoots,
        "by_genre": by_genre_list,
        "top_opportunities": opportunities[:5],
    }


def get_repurpose_for_shoot(shoot_id: int) -> Optional[dict]:
    """
    Get unused content details for a specific shoot.
    Returns list of unposted content-ready images.
    """
    with get_db() as conn:
        shoot = conn.execute(
            """SELECT s.*, c.name as client_name
               FROM shoots s LEFT JOIN clients c ON s.client_id = c.id
               WHERE s.id = ?""",
            (shoot_id,),
        ).fetchone()

        if not shoot:
            return None

        unposted_images = conn.execute(
            """SELECT id, file_path, file_name, genre, mood, lighting, subject_type,
                      tags, color_palette, setting, nima_composite, quality_score,
                      caption_draft, content_ready, portfolio_worthy
               FROM images
               WHERE shoot_id = ? AND content_ready = TRUE AND posted_at IS NULL
               ORDER BY COALESCE(nima_composite, 0) * 0.6 + COALESCE(quality_score, 0) * 0.4 DESC""",
            (shoot_id,),
        ).fetchall()

    return {
        "shoot": dict(shoot),
        "unposted_images": [dict(r) for r in unposted_images],
        "count": len(unposted_images),
    }
