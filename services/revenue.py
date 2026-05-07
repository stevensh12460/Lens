"""
services/revenue.py

Revenue analytics service — pure SQL aggregation, no LLM.
- Revenue by genre, by month
- Total YTD
- Busiest months historically
- Projected next 3 months based on booked shoots
"""

from datetime import date
from typing import Optional

from core.database import get_db


def get_revenue_summary() -> dict:
    """
    Full revenue summary:
    - YTD total (balance_paid bookings)
    - All-time total
    - Revenue by genre
    - Revenue by month (last 12 months)
    - Busiest months historically
    - Projected next 3 months
    """
    today = date.today()
    year_start = date(today.year, 1, 1)

    with get_db() as conn:
        # All-time total (paid)
        all_time_total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM bookings WHERE balance_paid = TRUE"
        ).fetchone()[0]

        # YTD total
        ytd_total = conn.execute(
            """SELECT COALESCE(SUM(amount), 0) FROM bookings
               WHERE balance_paid = TRUE AND shoot_date >= ?""",
            (str(year_start),),
        ).fetchone()[0]

        # Revenue by genre (paid + pending separately)
        by_genre = conn.execute(
            """SELECT genre,
                      COUNT(*) as total_bookings,
                      SUM(CASE WHEN balance_paid = TRUE THEN 1 ELSE 0 END) as paid_bookings,
                      COALESCE(SUM(CASE WHEN balance_paid = TRUE THEN amount ELSE 0 END), 0) as paid_revenue,
                      COALESCE(SUM(CASE WHEN balance_paid = FALSE THEN amount ELSE 0 END), 0) as pending_revenue,
                      COALESCE(AVG(CASE WHEN balance_paid = TRUE THEN amount END), 0) as avg_booking_value
               FROM bookings
               WHERE genre IS NOT NULL
               GROUP BY genre
               ORDER BY paid_revenue DESC""",
        ).fetchall()

        # Revenue by month (last 24 months)
        by_month = conn.execute(
            """SELECT strftime('%Y-%m', shoot_date) as month,
                      COUNT(*) as bookings,
                      SUM(CASE WHEN balance_paid = TRUE THEN 1 ELSE 0 END) as paid_bookings,
                      COALESCE(SUM(CASE WHEN balance_paid = TRUE THEN amount ELSE 0 END), 0) as paid_revenue,
                      COALESCE(SUM(CASE WHEN balance_paid = FALSE THEN amount ELSE 0 END), 0) as pending_revenue
               FROM bookings
               WHERE shoot_date >= date('now', '-24 months')
                 AND shoot_date IS NOT NULL
               GROUP BY month
               ORDER BY month DESC""",
        ).fetchall()

        # Historically busiest months (by booking count across all years)
        busy_months = conn.execute(
            """SELECT strftime('%m', shoot_date) as month_num,
                      CASE strftime('%m', shoot_date)
                        WHEN '01' THEN 'January'   WHEN '02' THEN 'February'
                        WHEN '03' THEN 'March'      WHEN '04' THEN 'April'
                        WHEN '05' THEN 'May'        WHEN '06' THEN 'June'
                        WHEN '07' THEN 'July'       WHEN '08' THEN 'August'
                        WHEN '09' THEN 'September'  WHEN '10' THEN 'October'
                        WHEN '11' THEN 'November'   WHEN '12' THEN 'December'
                      END as month_name,
                      COUNT(*) as total_bookings,
                      COALESCE(AVG(amount), 0) as avg_revenue
               FROM bookings
               WHERE shoot_date IS NOT NULL
               GROUP BY month_num
               ORDER BY total_bookings DESC""",
        ).fetchall()

        # Projected next 3 months: booked (deposit paid, not yet shot)
        projection = conn.execute(
            """SELECT strftime('%Y-%m', shoot_date) as month,
                      COUNT(*) as booked_shoots,
                      COALESCE(SUM(amount), 0) as projected_revenue,
                      GROUP_CONCAT(genre) as genres
               FROM bookings
               WHERE shoot_date >= date('now')
                 AND shoot_date <= date('now', '+3 months')
                 AND deposit_paid = TRUE
                 AND status NOT IN ('cancelled', 'refunded')
               GROUP BY month
               ORDER BY month ASC""",
        ).fetchall()

        # Conversion: leads vs. paid
        conversion = conn.execute(
            """SELECT
                  COUNT(*) as total_bookings,
                  SUM(CASE WHEN deposit_paid = TRUE THEN 1 ELSE 0 END) as deposits_paid,
                  SUM(CASE WHEN balance_paid = TRUE THEN 1 ELSE 0 END) as fully_paid,
                  COALESCE(AVG(CASE WHEN balance_paid = TRUE THEN amount END), 0) as avg_paid_booking
               FROM bookings""",
        ).fetchone()

    return {
        "summary": {
            "all_time_revenue": round(all_time_total, 2),
            "ytd_revenue": round(ytd_total, 2),
            "ytd_year": today.year,
        },
        "by_genre": [dict(r) for r in by_genre],
        "by_month": [dict(r) for r in by_month],
        "busiest_months_historically": [dict(r) for r in busy_months],
        "projected_next_3_months": [dict(r) for r in projection],
        "conversion": dict(conversion) if conversion else {},
    }


def get_revenue_by_genre(genre: Optional[str] = None) -> list[dict]:
    """Revenue breakdown for a specific genre or all genres."""
    with get_db() as conn:
        if genre:
            rows = conn.execute(
                """SELECT
                      strftime('%Y-%m', shoot_date) as month,
                      COUNT(*) as bookings,
                      COALESCE(SUM(CASE WHEN balance_paid = TRUE THEN amount ELSE 0 END), 0) as paid_revenue,
                      COALESCE(SUM(CASE WHEN balance_paid = FALSE THEN amount ELSE 0 END), 0) as pending_revenue
                   FROM bookings
                   WHERE genre = ?
                   GROUP BY month ORDER BY month DESC""",
                (genre,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT genre,
                      COUNT(*) as bookings,
                      COALESCE(SUM(CASE WHEN balance_paid = TRUE THEN amount ELSE 0 END), 0) as paid_revenue,
                      COALESCE(AVG(CASE WHEN balance_paid = TRUE THEN amount END), 0) as avg_booking
                   FROM bookings
                   WHERE genre IS NOT NULL
                   GROUP BY genre ORDER BY paid_revenue DESC""",
            ).fetchall()
    return [dict(r) for r in rows]
