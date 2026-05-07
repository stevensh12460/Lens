"""
Phase 7b — Print Revenue Analytics
Pure SQL analytics on print_sales and images tables. No LLM.
"""

from __future__ import annotations

import logging
from typing import Any

from core.database import get_db

logger = logging.getLogger(__name__)


def get_revenue_summary() -> dict:
    """
    Overall print revenue summary: totals, averages, and best month.
    """
    with get_db() as conn:
        row = conn.execute(
            """SELECT
                   COUNT(*)                          AS total_sales,
                   COALESCE(SUM(sale_price), 0)      AS total_revenue,
                   COALESCE(AVG(sale_price), 0)      AS avg_sale_price,
                   COALESCE(AVG(margin), 0)          AS avg_margin,
                   COALESCE(AVG(sale_price - lab_cost) / NULLIF(AVG(sale_price), 0) * 100, 0)
                                                     AS avg_margin_pct
               FROM print_sales"""
        ).fetchone()

        best_month_row = conn.execute(
            """SELECT strftime('%Y-%m', sale_date) AS month,
                      SUM(sale_price)              AS month_revenue
               FROM print_sales
               GROUP BY month
               ORDER BY month_revenue DESC
               LIMIT 1"""
        ).fetchone()

    return {
        "total_sales": row["total_sales"] or 0,
        "total_revenue": round(row["total_revenue"] or 0, 2),
        "avg_sale_price": round(row["avg_sale_price"] or 0, 2),
        "avg_margin": round(row["avg_margin"] or 0, 2),
        "avg_margin_pct": round(row["avg_margin_pct"] or 0, 1),
        "best_month": best_month_row["month"] if best_month_row else None,
        "best_month_revenue": round(best_month_row["month_revenue"] or 0, 2) if best_month_row else 0,
    }


def get_revenue_by_image(limit: int = 10) -> list[dict]:
    """Top-selling images by total print revenue."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT
                   ps.image_id,
                   i.file_name,
                   i.edition_title,
                   i.print_tier,
                   i.print_technique,
                   COUNT(ps.id)            AS sale_count,
                   SUM(ps.sale_price)      AS total_revenue,
                   AVG(ps.margin)          AS avg_margin,
                   AVG(ps.sale_price)      AS avg_price
               FROM print_sales ps
               JOIN images i ON ps.image_id = i.id
               GROUP BY ps.image_id
               ORDER BY total_revenue DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [
        {**dict(r), "total_revenue": round(r["total_revenue"] or 0, 2),
         "avg_margin": round(r["avg_margin"] or 0, 2),
         "avg_price": round(r["avg_price"] or 0, 2)}
        for r in rows
    ]


def get_revenue_by_channel() -> list[dict]:
    """Revenue breakdown by sales channel (pixieset, gallery, art_fair, direct, etc.)."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT
                   COALESCE(channel, 'unknown') AS channel,
                   COUNT(*)                     AS sale_count,
                   SUM(sale_price)              AS total_revenue,
                   AVG(sale_price)              AS avg_price,
                   AVG(margin)                  AS avg_margin
               FROM print_sales
               GROUP BY channel
               ORDER BY total_revenue DESC"""
        ).fetchall()
    return [
        {**dict(r),
         "total_revenue": round(r["total_revenue"] or 0, 2),
         "avg_price": round(r["avg_price"] or 0, 2),
         "avg_margin": round(r["avg_margin"] or 0, 2)}
        for r in rows
    ]


def get_revenue_by_technique() -> list[dict]:
    """Revenue breakdown by print technique (rotation, standard, turntable, orbit)."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT
                   COALESCE(i.print_technique, 'standard') AS technique,
                   COUNT(ps.id)                            AS sale_count,
                   SUM(ps.sale_price)                      AS total_revenue,
                   AVG(ps.sale_price)                      AS avg_price,
                   AVG(ps.margin)                          AS avg_margin
               FROM print_sales ps
               JOIN images i ON ps.image_id = i.id
               GROUP BY technique
               ORDER BY total_revenue DESC"""
        ).fetchall()
    return [
        {**dict(r),
         "total_revenue": round(r["total_revenue"] or 0, 2),
         "avg_price": round(r["avg_price"] or 0, 2),
         "avg_margin": round(r["avg_margin"] or 0, 2)}
        for r in rows
    ]


def get_revenue_by_month(months: int = 12) -> list[dict]:
    """Monthly revenue for the past N months, most recent first."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT
                   strftime('%Y-%m', sale_date) AS month,
                   COUNT(*)                     AS sale_count,
                   SUM(sale_price)              AS total_revenue,
                   AVG(sale_price)              AS avg_price,
                   SUM(margin)                  AS total_margin
               FROM print_sales
               WHERE sale_date >= datetime('now', :offset)
               GROUP BY month
               ORDER BY month DESC""",
            {"offset": f"-{months} months"},
        ).fetchall()
    return [
        {**dict(r),
         "total_revenue": round(r["total_revenue"] or 0, 2),
         "avg_price": round(r["avg_price"] or 0, 2),
         "total_margin": round(r["total_margin"] or 0, 2)}
        for r in rows
    ]


def get_margin_analysis() -> dict:
    """
    Margin analysis: average margin %, best and worst margin images.
    """
    with get_db() as conn:
        avg_row = conn.execute(
            """SELECT
                   AVG(CASE WHEN sale_price > 0
                       THEN (margin / sale_price) * 100 ELSE 0 END) AS avg_margin_pct
               FROM print_sales"""
        ).fetchone()

        best_rows = conn.execute(
            """SELECT
                   ps.image_id,
                   i.file_name,
                   i.edition_title,
                   AVG((ps.margin / NULLIF(ps.sale_price, 0)) * 100) AS avg_margin_pct,
                   SUM(ps.sale_price) AS total_revenue
               FROM print_sales ps
               JOIN images i ON ps.image_id = i.id
               GROUP BY ps.image_id
               ORDER BY avg_margin_pct DESC
               LIMIT 5"""
        ).fetchall()

        worst_rows = conn.execute(
            """SELECT
                   ps.image_id,
                   i.file_name,
                   i.edition_title,
                   AVG((ps.margin / NULLIF(ps.sale_price, 0)) * 100) AS avg_margin_pct,
                   SUM(ps.sale_price) AS total_revenue
               FROM print_sales ps
               JOIN images i ON ps.image_id = i.id
               GROUP BY ps.image_id
               ORDER BY avg_margin_pct ASC
               LIMIT 5"""
        ).fetchall()

    return {
        "avg_margin_pct": round(avg_row["avg_margin_pct"] or 0, 1),
        "best_margin_images": [
            {**dict(r), "avg_margin_pct": round(r["avg_margin_pct"] or 0, 1)}
            for r in best_rows
        ],
        "worst_margin_images": [
            {**dict(r), "avg_margin_pct": round(r["avg_margin_pct"] or 0, 1)}
            for r in worst_rows
        ],
    }


def get_print_dashboard_data() -> dict:
    """
    Combined summary dict for the print business dashboard panel.
    Single call that aggregates all key metrics.
    """
    with get_db() as conn:
        # Print-worthy inventory counts
        inventory = conn.execute(
            """SELECT
                   COUNT(*) FILTER (WHERE print_worthy = 1)          AS total_print_worthy,
                   COUNT(*) FILTER (WHERE print_tier = 'fine_art')   AS fine_art_count,
                   COUNT(*) FILTER (WHERE print_tier = 'standard')   AS standard_count,
                   COUNT(*) FILTER (WHERE edition_size IS NOT NULL
                     AND (edition_retired = 0 OR edition_retired IS NULL)) AS active_editions,
                   COUNT(*) FILTER (WHERE edition_retired = 1)       AS retired_editions
               FROM images"""
        ).fetchone()

        # Recent sales (last 30 days)
        recent = conn.execute(
            """SELECT COUNT(*) AS recent_sales, COALESCE(SUM(sale_price), 0) AS recent_revenue
               FROM print_sales
               WHERE sale_date >= datetime('now', '-30 days')"""
        ).fetchone()

        # All-time totals
        totals = conn.execute(
            """SELECT
                   COUNT(*)                     AS total_sales,
                   COALESCE(SUM(sale_price), 0) AS total_revenue,
                   COALESCE(AVG(margin), 0)     AS avg_margin
               FROM print_sales"""
        ).fetchone()

        # Top technique
        top_technique = conn.execute(
            """SELECT COALESCE(i.print_technique, 'standard') AS technique,
                      SUM(ps.sale_price) AS rev
               FROM print_sales ps JOIN images i ON ps.image_id = i.id
               GROUP BY technique ORDER BY rev DESC LIMIT 1"""
        ).fetchone()

        # Top channel
        top_channel = conn.execute(
            """SELECT COALESCE(channel, 'unknown') AS channel,
                      SUM(sale_price) AS rev
               FROM print_sales GROUP BY channel ORDER BY rev DESC LIMIT 1"""
        ).fetchone()

    return {
        "inventory": {
            "total_print_worthy": inventory["total_print_worthy"] or 0,
            "fine_art_count": inventory["fine_art_count"] or 0,
            "standard_count": inventory["standard_count"] or 0,
            "active_editions": inventory["active_editions"] or 0,
            "retired_editions": inventory["retired_editions"] or 0,
        },
        "last_30_days": {
            "sales": recent["recent_sales"] or 0,
            "revenue": round(recent["recent_revenue"] or 0, 2),
        },
        "all_time": {
            "total_sales": totals["total_sales"] or 0,
            "total_revenue": round(totals["total_revenue"] or 0, 2),
            "avg_margin": round(totals["avg_margin"] or 0, 2),
        },
        "top_technique": top_technique["technique"] if top_technique else None,
        "top_channel": top_channel["channel"] if top_channel else None,
    }
