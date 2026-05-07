"""
services/licensing.py

Commercial license renewal tracker — pure SQL, no LLM.
Manages image licensing records and tracks renewals.
"""

from datetime import date
from typing import Optional

from core.database import get_db


def get_expiring_licenses(days_ahead: int = 60) -> list[dict]:
    """
    Licenses expiring within the next N days.
    Returns client info, image count, and renewal_amount.
    """
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                l.id,
                l.usage_type,
                l.licensed_at,
                l.expires_at,
                l.renewal_amount,
                l.renewal_notified,
                l.notes,
                l.image_ids,
                c.id    AS client_id,
                c.name  AS client_name,
                c.email AS client_email,
                c.phone AS client_phone,
                s.id    AS shoot_id,
                s.genre AS shoot_genre,
                s.shoot_date,
                CAST(julianday(l.expires_at) - julianday('now') AS INTEGER) AS days_until_expiry,
                (
                    SELECT COUNT(*)
                    FROM (
                        SELECT value
                        FROM json_each('["' || replace(replace(l.image_ids, '[', ''), ']', '') || '"]')
                        WHERE l.image_ids IS NOT NULL AND l.image_ids != ''
                    )
                ) AS image_count_approx
            FROM licenses l
            JOIN clients c ON c.id = l.client_id
            LEFT JOIN shoots s ON s.id = l.shoot_id
            WHERE l.expires_at IS NOT NULL
              AND l.expires_at >= date('now')
              AND l.expires_at <= date('now', '+' || ? || ' days')
            ORDER BY l.expires_at ASC
            """,
            (days_ahead,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_expired_licenses() -> list[dict]:
    """
    Already expired licenses, sorted by expiry date DESC (most recently expired first).
    """
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                l.id,
                l.usage_type,
                l.licensed_at,
                l.expires_at,
                l.renewal_amount,
                l.renewal_notified,
                l.notes,
                l.image_ids,
                c.id    AS client_id,
                c.name  AS client_name,
                c.email AS client_email,
                s.id    AS shoot_id,
                s.genre AS shoot_genre,
                CAST(julianday('now') - julianday(l.expires_at) AS INTEGER) AS days_expired
            FROM licenses l
            JOIN clients c ON c.id = l.client_id
            LEFT JOIN shoots s ON s.id = l.shoot_id
            WHERE l.expires_at IS NOT NULL
              AND l.expires_at < date('now')
            ORDER BY l.expires_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def mark_renewal_notified(license_id: int) -> dict:
    """
    Set renewal_notified=TRUE for the given license.
    """
    with get_db() as conn:
        conn.execute(
            "UPDATE licenses SET renewal_notified = TRUE WHERE id = ?",
            (license_id,),
        )
        row = conn.execute(
            "SELECT * FROM licenses WHERE id = ?", (license_id,)
        ).fetchone()
    if not row:
        return {"error": f"License {license_id} not found"}
    return dict(row)


def create_license(
    client_id: int,
    shoot_id: Optional[int],
    image_ids: list[int],
    usage_type: str,
    expires_at: str,
    renewal_amount: float,
    notes: Optional[str] = None,
) -> dict:
    """
    Create a new image license record.
    image_ids: list of image IDs to license.
    expires_at: ISO date string e.g. '2026-12-31'.
    usage_type: e.g. 'commercial_print', 'digital_advertising', 'editorial'.
    """
    import json
    image_ids_str = json.dumps(image_ids)
    today = date.today().isoformat()

    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO licenses
                (client_id, shoot_id, image_ids, usage_type, licensed_at, expires_at, renewal_amount, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (client_id, shoot_id, image_ids_str, usage_type, today, expires_at, renewal_amount, notes),
        )
        license_id = cur.lastrowid
        row = conn.execute(
            """
            SELECT l.*, c.name AS client_name
            FROM licenses l JOIN clients c ON c.id = l.client_id
            WHERE l.id = ?
            """,
            (license_id,),
        ).fetchone()
    return dict(row)


def get_license_revenue_ytd() -> dict:
    """
    Total renewal revenue for licenses this year (based on licensed_at date).
    """
    today = date.today()
    year_start = date(today.year, 1, 1).isoformat()

    with get_db() as conn:
        result = conn.execute(
            """
            SELECT
                COUNT(*) AS license_count,
                COALESCE(SUM(renewal_amount), 0) AS total_renewal_revenue,
                COALESCE(AVG(renewal_amount), 0) AS avg_renewal_amount
            FROM licenses
            WHERE licensed_at >= ?
            """,
            (year_start,),
        ).fetchone()

        # Also get breakdown by usage type
        by_type = conn.execute(
            """
            SELECT
                COALESCE(usage_type, 'unspecified') AS usage_type,
                COUNT(*) AS count,
                COALESCE(SUM(renewal_amount), 0) AS revenue
            FROM licenses
            WHERE licensed_at >= ?
            GROUP BY usage_type
            ORDER BY revenue DESC
            """,
            (year_start,),
        ).fetchall()

        # All-time
        all_time = conn.execute(
            "SELECT COUNT(*) AS total_licenses, COALESCE(SUM(renewal_amount), 0) AS total_revenue FROM licenses"
        ).fetchone()

    return {
        "ytd_year": today.year,
        "ytd_license_count": result["license_count"],
        "ytd_revenue": round(result["total_renewal_revenue"], 2),
        "ytd_avg_renewal": round(result["avg_renewal_amount"], 2),
        "by_usage_type": [dict(r) for r in by_type],
        "all_time_license_count": all_time["total_licenses"],
        "all_time_revenue": round(all_time["total_revenue"], 2),
    }
