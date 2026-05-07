"""
services/style_tracker.py

Aesthetic evolution analysis — pure SQL using existing image tags.
No new LLM calls; uses the genre/mood/lighting/subject_type/tags columns
already populated by Pass 3 of the pipeline.
"""

import json
from typing import Optional

from core.database import get_db


def _parse_tags(tags_str: Optional[str]) -> list[str]:
    """Parse tags field which may be JSON array or comma-separated string."""
    if not tags_str:
        return []
    tags_str = tags_str.strip()
    if tags_str.startswith("["):
        try:
            return [t.strip().lower() for t in json.loads(tags_str) if t]
        except (json.JSONDecodeError, TypeError):
            pass
    return [t.strip().lower() for t in tags_str.split(",") if t.strip()]


def get_style_evolution() -> list[dict]:
    """
    Groups images by month (using pass3_at), shows dominant genre, mood,
    and lighting per month over time. Reveals how the work has evolved.
    """
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                strftime('%Y-%m', pass3_at) AS month,
                COUNT(*) AS image_count,
                -- Dominant genre (most common)
                (
                    SELECT genre FROM images i2
                    WHERE strftime('%Y-%m', i2.pass3_at) = strftime('%Y-%m', i.pass3_at)
                      AND i2.genre IS NOT NULL
                    GROUP BY genre ORDER BY COUNT(*) DESC LIMIT 1
                ) AS dominant_genre,
                -- Dominant mood
                (
                    SELECT mood FROM images i2
                    WHERE strftime('%Y-%m', i2.pass3_at) = strftime('%Y-%m', i.pass3_at)
                      AND i2.mood IS NOT NULL
                    GROUP BY mood ORDER BY COUNT(*) DESC LIMIT 1
                ) AS dominant_mood,
                -- Dominant lighting
                (
                    SELECT lighting FROM images i2
                    WHERE strftime('%Y-%m', i2.pass3_at) = strftime('%Y-%m', i.pass3_at)
                      AND i2.lighting IS NOT NULL
                    GROUP BY lighting ORDER BY COUNT(*) DESC LIMIT 1
                ) AS dominant_lighting,
                -- Dominant subject type
                (
                    SELECT subject_type FROM images i2
                    WHERE strftime('%Y-%m', i2.pass3_at) = strftime('%Y-%m', i.pass3_at)
                      AND i2.subject_type IS NOT NULL
                    GROUP BY subject_type ORDER BY COUNT(*) DESC LIMIT 1
                ) AS dominant_subject,
                -- Portfolio worthy rate
                ROUND(
                    100.0 * SUM(CASE WHEN portfolio_worthy = TRUE THEN 1 ELSE 0 END) / COUNT(*),
                    1
                ) AS portfolio_worthy_pct,
                AVG(COALESCE(quality_score, nima_composite, 0)) AS avg_quality_score
            FROM images i
            WHERE pass3_at IS NOT NULL
            GROUP BY month
            ORDER BY month ASC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_dominant_aesthetics() -> dict:
    """
    Top 5 mood tags, top 5 lighting types, top 5 subject types across
    the entire tagged library.
    """
    with get_db() as conn:
        # Top moods
        top_moods = conn.execute(
            """
            SELECT mood, COUNT(*) AS count,
                   ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM images WHERE mood IS NOT NULL), 1) AS pct
            FROM images
            WHERE mood IS NOT NULL AND mood != ''
            GROUP BY mood
            ORDER BY count DESC
            LIMIT 5
            """
        ).fetchall()

        # Top lighting types
        top_lighting = conn.execute(
            """
            SELECT lighting, COUNT(*) AS count,
                   ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM images WHERE lighting IS NOT NULL), 1) AS pct
            FROM images
            WHERE lighting IS NOT NULL AND lighting != ''
            GROUP BY lighting
            ORDER BY count DESC
            LIMIT 5
            """
        ).fetchall()

        # Top subject types
        top_subjects = conn.execute(
            """
            SELECT subject_type, COUNT(*) AS count,
                   ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM images WHERE subject_type IS NOT NULL), 1) AS pct
            FROM images
            WHERE subject_type IS NOT NULL AND subject_type != ''
            GROUP BY subject_type
            ORDER BY count DESC
            LIMIT 5
            """
        ).fetchall()

        # Top genres
        top_genres = conn.execute(
            """
            SELECT genre, COUNT(*) AS count,
                   ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM images WHERE genre IS NOT NULL), 1) AS pct
            FROM images
            WHERE genre IS NOT NULL AND genre != ''
            GROUP BY genre
            ORDER BY count DESC
            LIMIT 5
            """
        ).fetchall()

        # Total tagged images
        total_tagged = conn.execute(
            "SELECT COUNT(*) FROM images WHERE pass3_at IS NOT NULL"
        ).fetchone()[0]

        # Portfolio worthy stats
        pw_total = conn.execute(
            "SELECT COUNT(*) FROM images WHERE portfolio_worthy = TRUE"
        ).fetchone()[0]

    return {
        "total_tagged_images": total_tagged,
        "portfolio_worthy_count": pw_total,
        "top_moods": [dict(r) for r in top_moods],
        "top_lighting_types": [dict(r) for r in top_lighting],
        "top_subject_types": [dict(r) for r in top_subjects],
        "top_genres": [dict(r) for r in top_genres],
    }


def get_genre_distribution_over_time() -> list[dict]:
    """
    Month by month genre breakdown — shows business pivot points.
    """
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                strftime('%Y-%m', pass3_at) AS month,
                genre,
                COUNT(*) AS image_count,
                ROUND(
                    100.0 * COUNT(*) / SUM(COUNT(*)) OVER (
                        PARTITION BY strftime('%Y-%m', pass3_at)
                    ),
                    1
                ) AS pct_of_month
            FROM images
            WHERE pass3_at IS NOT NULL
              AND genre IS NOT NULL
            GROUP BY month, genre
            ORDER BY month ASC, image_count DESC
            """
        ).fetchall()

    # Restructure as month -> [genres]
    months: dict[str, list] = {}
    for r in rows:
        r = dict(r)
        m = r["month"]
        if m not in months:
            months[m] = []
        months[m].append({"genre": r["genre"], "count": r["image_count"], "pct": r["pct_of_month"]})

    return [{"month": m, "genres": genres} for m, genres in sorted(months.items())]


def get_signature_tags() -> dict:
    """
    Tags that appear in portfolio_worthy images at a higher rate than
    non-portfolio images. These are what make the best work distinct.
    """
    with get_db() as conn:
        pw_images = conn.execute(
            "SELECT tags FROM images WHERE portfolio_worthy = TRUE AND tags IS NOT NULL"
        ).fetchall()
        non_pw_images = conn.execute(
            "SELECT tags FROM images WHERE (portfolio_worthy = FALSE OR portfolio_worthy IS NULL) AND tags IS NOT NULL"
        ).fetchall()

        total_pw = conn.execute(
            "SELECT COUNT(*) FROM images WHERE portfolio_worthy = TRUE"
        ).fetchone()[0]
        total_non_pw = conn.execute(
            "SELECT COUNT(*) FROM images WHERE portfolio_worthy = FALSE OR portfolio_worthy IS NULL"
        ).fetchone()[0]

    # Count tag frequencies
    pw_tag_counts: dict[str, int] = {}
    for row in pw_images:
        for tag in _parse_tags(row["tags"]):
            pw_tag_counts[tag] = pw_tag_counts.get(tag, 0) + 1

    non_pw_tag_counts: dict[str, int] = {}
    for row in non_pw_images:
        for tag in _parse_tags(row["tags"]):
            non_pw_tag_counts[tag] = non_pw_tag_counts.get(tag, 0) + 1

    # Calculate lift: (tag_rate_in_pw) / (tag_rate_in_non_pw)
    signature = []
    for tag, pw_count in pw_tag_counts.items():
        if pw_count < 3:  # require at least 3 occurrences to surface
            continue
        pw_rate = pw_count / max(total_pw, 1)
        non_pw_count = non_pw_tag_counts.get(tag, 0)
        non_pw_rate = non_pw_count / max(total_non_pw, 1)
        lift = pw_rate / max(non_pw_rate, 0.0001)
        signature.append({
            "tag": tag,
            "portfolio_worthy_count": pw_count,
            "portfolio_worthy_rate_pct": round(pw_rate * 100, 2),
            "non_portfolio_count": non_pw_count,
            "non_portfolio_rate_pct": round(non_pw_rate * 100, 2),
            "lift": round(lift, 2),
        })

    signature.sort(key=lambda x: x["lift"], reverse=True)

    return {
        "total_portfolio_worthy": total_pw,
        "total_non_portfolio": total_non_pw,
        "signature_tags": signature[:25],  # top 25 by lift
        "explanation": (
            "Lift > 1.0 means the tag appears more often in portfolio-worthy images. "
            "Higher lift = more signature to your best work."
        ),
    }


def compare_periods(
    period1_start: str,
    period1_end: str,
    period2_start: str,
    period2_end: str,
) -> dict:
    """
    Compare aesthetic patterns between two date ranges.
    Dates should be ISO strings e.g. '2024-01-01'.
    """

    def _get_period_stats(start: str, end: str) -> dict:
        with get_db() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM images WHERE pass3_at >= ? AND pass3_at < ?",
                (start, end),
            ).fetchone()[0]

            genres = conn.execute(
                """
                SELECT genre, COUNT(*) AS count
                FROM images
                WHERE pass3_at >= ? AND pass3_at < ? AND genre IS NOT NULL
                GROUP BY genre ORDER BY count DESC LIMIT 5
                """,
                (start, end),
            ).fetchall()

            moods = conn.execute(
                """
                SELECT mood, COUNT(*) AS count
                FROM images
                WHERE pass3_at >= ? AND pass3_at < ? AND mood IS NOT NULL
                GROUP BY mood ORDER BY count DESC LIMIT 5
                """,
                (start, end),
            ).fetchall()

            lighting = conn.execute(
                """
                SELECT lighting, COUNT(*) AS count
                FROM images
                WHERE pass3_at >= ? AND pass3_at < ? AND lighting IS NOT NULL
                GROUP BY lighting ORDER BY count DESC LIMIT 5
                """,
                (start, end),
            ).fetchall()

            pw_count = conn.execute(
                """
                SELECT COUNT(*) FROM images
                WHERE pass3_at >= ? AND pass3_at < ? AND portfolio_worthy = TRUE
                """,
                (start, end),
            ).fetchone()[0]

            avg_q = conn.execute(
                """
                SELECT AVG(COALESCE(quality_score, nima_composite, 0))
                FROM images WHERE pass3_at >= ? AND pass3_at < ?
                """,
                (start, end),
            ).fetchone()[0]

        return {
            "total_images": total,
            "portfolio_worthy": pw_count,
            "portfolio_worthy_pct": round(pw_count / max(total, 1) * 100, 1),
            "avg_quality_score": round(avg_q or 0, 3),
            "top_genres": [dict(r) for r in genres],
            "top_moods": [dict(r) for r in moods],
            "top_lighting": [dict(r) for r in lighting],
        }

    p1 = _get_period_stats(period1_start, period1_end)
    p2 = _get_period_stats(period2_start, period2_end)

    return {
        "period1": {"start": period1_start, "end": period1_end, "stats": p1},
        "period2": {"start": period2_start, "end": period2_end, "stats": p2},
        "delta": {
            "image_count_change": p2["total_images"] - p1["total_images"],
            "portfolio_worthy_pct_change": round(
                p2["portfolio_worthy_pct"] - p1["portfolio_worthy_pct"], 1
            ),
            "avg_quality_change": round(
                (p2["avg_quality_score"] or 0) - (p1["avg_quality_score"] or 0), 3
            ),
        },
    }
