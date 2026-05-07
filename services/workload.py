"""
services/workload.py

Post-production workload tracker — pure SQL, no LLM.
Tracks the edit queue: bookings shot but not yet delivered.
"""

from datetime import date, timedelta
from typing import Optional

from core.database import get_db

# Standard delivery windows by genre (in days)
DELIVERY_WINDOWS: dict[str, int] = {
    "wedding":    28,  # 4 weeks
    "portrait":   14,  # 2 weeks
    "boudoir":    14,  # 2 weeks
    "commercial":  7,  # 1 week
    "events":      7,  # 1 week
    "nature":      7,  # 1 week
}
DEFAULT_WINDOW = 14  # fallback for unlisted genres


def get_edit_queue() -> list[dict]:
    """
    Bookings with status='shot' that have not yet been delivered.
    Returns days_since_shoot, client_name, genre, total_images, booking_id.
    """
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                b.id            AS booking_id,
                b.genre,
                b.shoot_date,
                b.status,
                b.package,
                c.name          AS client_name,
                c.email         AS client_email,
                s.id            AS shoot_id,
                s.total_images,
                s.delivered_at,
                CAST(julianday('now') - julianday(b.shoot_date) AS INTEGER) AS days_since_shoot
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            LEFT JOIN shoots s ON s.id = b.shoot_id
            WHERE b.status = 'shot'
              AND (s.delivered_at IS NULL OR s.delivered_at = '')
              AND b.shoot_date IS NOT NULL
            ORDER BY b.shoot_date ASC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_overdue_deliveries() -> list[dict]:
    """
    Bookings where the shoot is past its genre delivery window
    and has not been delivered.
    """
    today = date.today()
    queue = get_edit_queue()
    overdue = []
    for item in queue:
        genre = (item.get("genre") or "").lower()
        window = DELIVERY_WINDOWS.get(genre, DEFAULT_WINDOW)
        days_past = (item.get("days_since_shoot") or 0) - window
        if days_past > 0:
            item["delivery_window_days"] = window
            item["days_overdue"] = days_past
            item["due_date"] = (
                date.fromisoformat(item["shoot_date"]) + timedelta(days=window)
            ).isoformat() if item.get("shoot_date") else None
            overdue.append(item)
    overdue.sort(key=lambda x: x["days_overdue"], reverse=True)
    return overdue


def get_workload_summary() -> dict:
    """
    Summary dict:
    - total_in_queue: number of undelivered shot bookings
    - overdue_count
    - due_this_week: bookings whose deadline falls within next 7 days
    - avg_turnaround_days_by_genre: based on shoots that have been delivered
    """
    queue = get_edit_queue()
    overdue = get_overdue_deliveries()
    today = date.today()
    week_ahead = today + timedelta(days=7)

    due_this_week = []
    for item in queue:
        if not item.get("shoot_date"):
            continue
        genre = (item.get("genre") or "").lower()
        window = DELIVERY_WINDOWS.get(genre, DEFAULT_WINDOW)
        due_date = date.fromisoformat(item["shoot_date"]) + timedelta(days=window)
        if today <= due_date <= week_ahead:
            due_this_week.append(item)

    # Average turnaround for delivered shoots
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                b.genre,
                AVG(
                    CAST(julianday(s.delivered_at) - julianday(b.shoot_date) AS REAL)
                ) AS avg_turnaround_days
            FROM bookings b
            JOIN shoots s ON s.id = b.shoot_id
            WHERE s.delivered_at IS NOT NULL
              AND b.shoot_date IS NOT NULL
              AND b.genre IS NOT NULL
            GROUP BY b.genre
            ORDER BY b.genre
            """
        ).fetchall()
    avg_turnaround = {r["genre"]: round(r["avg_turnaround_days"], 1) for r in rows}

    return {
        "total_in_queue": len(queue),
        "overdue_count": len(overdue),
        "due_this_week": len(due_this_week),
        "due_this_week_bookings": due_this_week,
        "avg_turnaround_days_by_genre": avg_turnaround,
        "delivery_windows_by_genre": DELIVERY_WINDOWS,
    }


def estimate_completion(booking_id: int) -> dict:
    """
    Estimate delivery date for a booking based on genre average turnaround.
    Falls back to the delivery window if no historical data exists.
    """
    with get_db() as conn:
        booking = conn.execute(
            """
            SELECT b.*, c.name AS client_name
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            WHERE b.id = ?
            """,
            (booking_id,),
        ).fetchone()

    if not booking:
        return {"error": f"Booking {booking_id} not found"}

    booking = dict(booking)
    genre = (booking.get("genre") or "").lower()

    # Try historical average
    with get_db() as conn:
        avg = conn.execute(
            """
            SELECT AVG(
                CAST(julianday(s.delivered_at) - julianday(b.shoot_date) AS REAL)
            ) AS avg_days
            FROM bookings b
            JOIN shoots s ON s.id = b.shoot_id
            WHERE s.delivered_at IS NOT NULL
              AND b.shoot_date IS NOT NULL
              AND LOWER(b.genre) = ?
            """,
            (genre,),
        ).fetchone()

    avg_days = avg["avg_days"] if avg and avg["avg_days"] else None
    window_days = DELIVERY_WINDOWS.get(genre, DEFAULT_WINDOW)
    turnaround_days = round(avg_days) if avg_days else window_days

    shoot_date = booking.get("shoot_date")
    estimated_date = None
    if shoot_date:
        estimated_date = (
            date.fromisoformat(shoot_date) + timedelta(days=turnaround_days)
        ).isoformat()

    return {
        "booking_id": booking_id,
        "client_name": booking.get("client_name"),
        "genre": booking.get("genre"),
        "shoot_date": shoot_date,
        "estimated_delivery_date": estimated_date,
        "turnaround_days_used": turnaround_days,
        "based_on": "historical_average" if avg_days else "delivery_window_default",
    }
