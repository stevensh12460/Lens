"""
CRM — Client record management.
No LLM calls. All DB access through core/database.py.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional

from core.database import get_db


# ---------------------------------------------------------------------------
# Create / Read / Update
# ---------------------------------------------------------------------------

def create_client(
    name: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    notes: Optional[str] = None,
    referred_by_id: Optional[int] = None,
) -> dict:
    """Insert a new client record and return the full row."""
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO clients (name, email, phone, notes, referred_by)
               VALUES (?, ?, ?, ?, ?)""",
            (name, email, phone, notes, referred_by_id),
        )
        client_id = cursor.lastrowid
        row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
        return dict(row)


def get_client(client_id: int) -> Optional[dict]:
    """Return full client record or None if not found."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
        return dict(row) if row else None


def get_all_clients(active_only: bool = False) -> list[dict]:
    """Return all clients, optionally filtering to those with at least one booking."""
    with get_db() as conn:
        if active_only:
            rows = conn.execute(
                "SELECT * FROM clients WHERE total_bookings > 0 ORDER BY name"
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM clients ORDER BY name").fetchall()
        return [dict(r) for r in rows]


def search_clients(query: str) -> list[dict]:
    """Fuzzy search on name and email fields."""
    pattern = f"%{query}%"
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM clients WHERE name LIKE ? OR email LIKE ? ORDER BY name",
            (pattern, pattern),
        ).fetchall()
        return [dict(r) for r in rows]


def update_client(client_id: int, **kwargs: Any) -> Optional[dict]:
    """Update any subset of client fields. Returns updated record."""
    allowed = {
        "name", "email", "phone", "referred_by", "referred_by_vendor",
        "notes", "preferences", "anniversary", "birthday",
        "first_booked", "last_booked", "total_bookings", "total_revenue",
    }
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return get_client(client_id)

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [client_id]
    with get_db() as conn:
        conn.execute(
            f"UPDATE clients SET {set_clause} WHERE id = ?", values
        )
        row = conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Relationship helpers
# ---------------------------------------------------------------------------

def get_client_shoots(client_id: int) -> list[dict]:
    """Return all shoots for this client ordered newest first."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM shoots WHERE client_id = ? ORDER BY shoot_date DESC",
            (client_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_client_stats(client_id: int) -> dict:
    """
    Returns:
        total_revenue, total_bookings, last_booked, favorite_genre,
        lifetime_value_score (revenue / years as client, floored at 1)
    """
    with get_db() as conn:
        client = conn.execute(
            "SELECT total_revenue, total_bookings, last_booked, first_booked FROM clients WHERE id = ?",
            (client_id,),
        ).fetchone()
        if not client:
            return {}

        # Favorite genre
        genre_row = conn.execute(
            """SELECT genre, COUNT(*) as cnt FROM bookings
               WHERE client_id = ? AND genre IS NOT NULL
               GROUP BY genre ORDER BY cnt DESC LIMIT 1""",
            (client_id,),
        ).fetchone()
        favorite_genre = genre_row["genre"] if genre_row else None

        # Lifetime value score: revenue / max(years_since_first_booked, 1)
        first_booked_str = client["first_booked"]
        if first_booked_str:
            try:
                first_dt = datetime.strptime(first_booked_str[:10], "%Y-%m-%d")
                years = max((datetime.now() - first_dt).days / 365.25, 1)
            except ValueError:
                years = 1
        else:
            years = 1
        ltv = round((client["total_revenue"] or 0) / years, 2)

        return {
            "total_revenue": client["total_revenue"] or 0,
            "total_bookings": client["total_bookings"] or 0,
            "last_booked": client["last_booked"],
            "favorite_genre": favorite_genre,
            "lifetime_value_score": ltv,
        }


def get_top_clients(limit: int = 10) -> list[dict]:
    """Return top clients by total_revenue descending."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM clients ORDER BY total_revenue DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def check_upcoming_dates(days: int = 30) -> list[dict]:
    """
    Return clients whose anniversary or birthday falls within the next N days.
    Useful for re-booking outreach.
    """
    today = date.today()
    results: list[dict] = []
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM clients WHERE anniversary IS NOT NULL OR birthday IS NOT NULL"
        ).fetchall()

    for row in rows:
        client = dict(row)
        for field in ("anniversary", "birthday"):
            raw = client.get(field)
            if not raw:
                continue
            try:
                event_date = datetime.strptime(raw[:10], "%Y-%m-%d").date()
                # Map to this calendar year
                this_year = event_date.replace(year=today.year)
                if this_year < today:
                    this_year = event_date.replace(year=today.year + 1)
                delta = (this_year - today).days
                if 0 <= delta <= days:
                    results.append({
                        **client,
                        "upcoming_event": field,
                        "event_date": str(this_year),
                        "days_away": delta,
                    })
            except (ValueError, OverflowError):
                continue

    results.sort(key=lambda x: x["days_away"])
    return results
