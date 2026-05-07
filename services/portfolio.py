"""
services/portfolio.py

Portfolio selection service.
- Queries DB for top 20 images per genre ranked by nima_composite + quality_score combined
- Updates portfolio_worthy flag automatically
- Returns ranked list per genre
"""

from typing import Optional

from core.database import get_db
from core.config import settings

# Number of top images to mark portfolio-worthy per genre
PORTFOLIO_TOP_N = 20


def _combined_score(row: dict) -> float:
    """Weighted combined score: 60% nima_composite + 40% quality_score."""
    nima = row.get("nima_composite") or 0.0
    quality = row.get("quality_score") or 0.0
    return (nima * 0.6) + (quality * 0.4)


def update_portfolio_flags() -> dict:
    """
    For each genre, mark the top PORTFOLIO_TOP_N images portfolio_worthy=TRUE
    (by nima_composite + quality_score combined), clear the flag on the rest.
    Returns counts per genre.
    """
    results = {}
    with get_db() as conn:
        genres = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT genre FROM images WHERE genre IS NOT NULL AND pass3_at IS NOT NULL"
            ).fetchall()
        ]

        for genre in genres:
            # Fetch all scored images for this genre
            rows = conn.execute(
                """SELECT id,
                          COALESCE(nima_composite, 0) as nima_composite,
                          COALESCE(quality_score, 0) as quality_score
                   FROM images
                   WHERE genre = ? AND pass3_at IS NOT NULL
                   ORDER BY (COALESCE(nima_composite, 0) * 0.6 + COALESCE(quality_score, 0) * 0.4) DESC""",
                (genre,),
            ).fetchall()

            rows = [dict(r) for r in rows]
            top_ids = [r["id"] for r in rows[:PORTFOLIO_TOP_N]]
            all_ids = [r["id"] for r in rows]

            if top_ids:
                placeholders = ",".join("?" * len(top_ids))
                conn.execute(
                    f"UPDATE images SET portfolio_worthy = TRUE WHERE id IN ({placeholders})",
                    top_ids,
                )

            # Clear flag for images that fell out of top N
            rest_ids = [i for i in all_ids if i not in top_ids]
            if rest_ids:
                placeholders = ",".join("?" * len(rest_ids))
                conn.execute(
                    f"UPDATE images SET portfolio_worthy = FALSE WHERE genre = ? AND id IN ({placeholders})",
                    [genre] + rest_ids,
                )

            results[genre] = {"marked_worthy": len(top_ids), "cleared": len(rest_ids)}

    return results


def get_portfolio_by_genre(genre: str, limit: int = PORTFOLIO_TOP_N) -> list[dict]:
    """
    Return top images for a specific genre, ranked by combined score.
    Also triggers flag update for this genre.
    """
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, file_path, file_name, shoot_id, genre, mood, lighting,
                      subject_type, tags, color_palette, setting,
                      nima_composite, quality_score, portfolio_worthy,
                      content_ready, caption_draft, pass3_at
               FROM images
               WHERE genre = ? AND pass3_at IS NOT NULL
               ORDER BY (COALESCE(nima_composite, 0) * 0.6 + COALESCE(quality_score, 0) * 0.4) DESC
               LIMIT ?""",
            (genre, limit),
        ).fetchall()

        result = []
        for r in rows:
            d = dict(r)
            d["combined_score"] = round(_combined_score(d), 4)
            result.append(d)

    return result


def get_portfolio_all(limit_per_genre: int = PORTFOLIO_TOP_N) -> dict:
    """
    Return top images for every genre, keyed by genre name.
    """
    with get_db() as conn:
        genres = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT genre FROM images WHERE genre IS NOT NULL AND pass3_at IS NOT NULL"
            ).fetchall()
        ]

    portfolio = {}
    for genre in genres:
        portfolio[genre] = get_portfolio_by_genre(genre, limit=limit_per_genre)

    return portfolio


def get_portfolio_summary() -> list[dict]:
    """
    Summary stats: count of portfolio-worthy images and avg combined score per genre.
    """
    with get_db() as conn:
        rows = conn.execute(
            """SELECT genre,
                      COUNT(*) as total_worthy,
                      ROUND(AVG(COALESCE(nima_composite, 0) * 0.6 + COALESCE(quality_score, 0) * 0.4), 4) as avg_combined_score,
                      ROUND(AVG(nima_composite), 4) as avg_nima,
                      ROUND(AVG(quality_score), 4) as avg_quality
               FROM images
               WHERE portfolio_worthy = TRUE
               GROUP BY genre
               ORDER BY total_worthy DESC""",
        ).fetchall()

    return [dict(r) for r in rows]
