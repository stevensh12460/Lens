"""
CRM — Booking lifecycle management.
No LLM calls. All DB access through core/database.py.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional

from core.database import get_db

VALID_STATUSES = ("inquiry", "booked", "shot", "editing", "delivered", "complete")


# ---------------------------------------------------------------------------
# Create / Read
# ---------------------------------------------------------------------------

def create_booking(
    client_id: int,
    genre: str,
    shoot_date: str | date,
    package: Optional[str] = None,
    amount: Optional[float] = None,
    source: Optional[str] = None,
    package_tier: Optional[str] = None,
    source_detail: Optional[str] = None,
) -> dict:
    """
    Create a booking AND a matching shoot record atomically.
    Returns the full booking dict (with shoot_id populated).
    """
    shoot_date_str = str(shoot_date)[:10]

    with get_db() as conn:
        # Create linked shoot record
        shoot_cursor = conn.execute(
            """INSERT INTO shoots (client_id, shoot_date, genre)
               VALUES (?, ?, ?)""",
            (client_id, shoot_date_str, genre),
        )
        shoot_id = shoot_cursor.lastrowid

        # Create booking
        booking_cursor = conn.execute(
            """INSERT INTO bookings
               (client_id, shoot_id, genre, shoot_date, package, package_tier,
                amount, source, source_detail, status, booked_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'inquiry', date('now'))""",
            (client_id, shoot_id, genre, shoot_date_str, package,
             package_tier, amount, source, source_detail),
        )
        booking_id = booking_cursor.lastrowid

        # Update client stats
        conn.execute(
            """UPDATE clients SET
               total_bookings = total_bookings + 1,
               total_revenue  = total_revenue  + COALESCE(?, 0),
               last_booked    = date('now'),
               first_booked   = COALESCE(first_booked, date('now'))
               WHERE id = ?""",
            (amount, client_id),
        )

        row = conn.execute(
            """SELECT b.*, c.name as client_name
               FROM bookings b JOIN clients c ON b.client_id = c.id
               WHERE b.id = ?""",
            (booking_id,),
        ).fetchone()
        return dict(row)


def get_booking(booking_id: int) -> Optional[dict]:
    """Return full booking with client name and shoot info joined."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT b.*, c.name as client_name,
                      s.location, s.total_images, s.delivered_at, s.gallery_url
               FROM bookings b
               JOIN clients c ON b.client_id = c.id
               LEFT JOIN shoots s ON b.shoot_id = s.id
               WHERE b.id = ?""",
            (booking_id,),
        ).fetchone()
        return dict(row) if row else None


def get_all_bookings(
    status: Optional[str] = None,
    genre: Optional[str] = None,
) -> list[dict]:
    """Filterable list of all bookings with client name."""
    with get_db() as conn:
        query = (
            "SELECT b.*, c.name as client_name "
            "FROM bookings b JOIN clients c ON b.client_id = c.id WHERE 1=1"
        )
        params: list[Any] = []
        if status:
            query += " AND b.status = ?"
            params.append(status)
        if genre:
            query += " AND b.genre = ?"
            params.append(genre)
        query += " ORDER BY b.shoot_date DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------

def update_booking_status(booking_id: int, status: str) -> dict:
    """Update booking status. Raises ValueError for invalid statuses."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {VALID_STATUSES}")
    with get_db() as conn:
        conn.execute(
            "UPDATE bookings SET status = ? WHERE id = ?",
            (status, booking_id),
        )
        row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        return dict(row) if row else {}


# ---------------------------------------------------------------------------
# Payment / admin flags
# ---------------------------------------------------------------------------

def mark_deposit_paid(booking_id: int) -> dict:
    with get_db() as conn:
        conn.execute(
            "UPDATE bookings SET deposit_paid = TRUE WHERE id = ?", (booking_id,)
        )
        row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        return dict(row) if row else {}


def mark_balance_paid(booking_id: int) -> dict:
    with get_db() as conn:
        conn.execute(
            "UPDATE bookings SET balance_paid = TRUE WHERE id = ?", (booking_id,)
        )
        row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        return dict(row) if row else {}


def mark_contract_signed(booking_id: int) -> dict:
    with get_db() as conn:
        conn.execute(
            "UPDATE bookings SET contract_signed = TRUE WHERE id = ?", (booking_id,)
        )
        row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        return dict(row) if row else {}


def mark_intake_complete(booking_id: int) -> dict:
    with get_db() as conn:
        conn.execute(
            "UPDATE bookings SET intake_complete = TRUE WHERE id = ?", (booking_id,)
        )
        row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        return dict(row) if row else {}


# ---------------------------------------------------------------------------
# Scheduling views
# ---------------------------------------------------------------------------

def get_upcoming_shoots(days: int = 30) -> list[dict]:
    """Shoots in the next N days with client info."""
    today = date.today()
    cutoff = today + timedelta(days=days)
    with get_db() as conn:
        rows = conn.execute(
            """SELECT b.*, c.name as client_name, c.email, c.phone
               FROM bookings b JOIN clients c ON b.client_id = c.id
               WHERE b.shoot_date BETWEEN ? AND ?
               AND b.status NOT IN ('delivered', 'complete')
               ORDER BY b.shoot_date ASC""",
            (str(today), str(cutoff)),
        ).fetchall()
        return [dict(r) for r in rows]


def get_pipeline_summary() -> dict:
    """Count of bookings by status — how many in each stage right now."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as count FROM bookings GROUP BY status"
        ).fetchall()
        summary = {s: 0 for s in VALID_STATUSES}
        for row in rows:
            summary[row["status"]] = row["count"]
        return summary
