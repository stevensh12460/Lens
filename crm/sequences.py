"""
CRM — Automated follow-up sequences.
No LLM calls. Rule-based triggers only. All DB access through core/database.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from core.database import get_db


# ---------------------------------------------------------------------------
# Sequence definitions
# ---------------------------------------------------------------------------

SEQUENCES: dict[str, dict] = {
    "inquiry_followup": {
        "trigger": "booking created with status=inquiry",
        "steps": [
            {
                "delay_hours": 2,
                "type": "reminder",
                "message": "Send quote to {client_name} for {genre} shoot on {shoot_date}",
            },
            {
                "delay_hours": 48,
                "type": "reminder",
                "message": "Follow up with {client_name} — no response to quote yet",
            },
            {
                "delay_hours": 168,
                "type": "reminder",
                "message": "Final follow up: {client_name} inquiry going cold",
            },
        ],
    },
    "pre_shoot": {
        "trigger": "booking status=booked and shoot_date within 7 days",
        "steps": [
            {
                "delay_days": -7,
                "type": "reminder",
                "message": "Send prep guide to {client_name} for {genre} shoot",
            },
            {
                "delay_days": -2,
                "type": "reminder",
                "message": "Confirm shoot details with {client_name} — location, time, what to wear",
            },
            {
                "delay_days": -1,
                "type": "reminder",
                "message": "Day-before check in: {client_name} shoot tomorrow",
            },
        ],
    },
    "post_shoot": {
        "trigger": "booking status changes to shot",
        "steps": [
            {
                "delay_hours": 24,
                "type": "reminder",
                "message": "Send thank-you message to {client_name}",
            },
            {
                "delay_days": 7,
                "type": "reminder",
                "message": "Gallery delivery due for {client_name} — check edit queue",
            },
            {
                "delay_days": 30,
                "type": "reminder",
                "message": "Check in with {client_name} — request testimonial",
            },
        ],
    },
    "rebooking": {
        "trigger": "booking status=complete and days_since > 180",
        "steps": [
            {
                "delay_days": 0,
                "type": "reminder",
                "message": "Re-booking opportunity: {client_name} last shot 6 months ago",
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_due_at(step: dict, reference_dt: datetime) -> datetime:
    """
    Calculate the absolute due datetime for a step.
    Steps can specify delay_hours (relative to now) or delay_days
    (relative to shoot_date for pre_shoot, or relative to now for others).
    """
    if "delay_hours" in step:
        return reference_dt + timedelta(hours=step["delay_hours"])
    if "delay_days" in step:
        return reference_dt + timedelta(days=step["delay_days"])
    return reference_dt


def _format_message(message: str, context: dict) -> str:
    """Fill in message placeholders safely."""
    try:
        return message.format(**context)
    except KeyError:
        return message


def _get_booking_context(conn, booking_id: int) -> Optional[dict]:
    row = conn.execute(
        """SELECT b.*, c.name as client_name
           FROM bookings b JOIN clients c ON b.client_id = c.id
           WHERE b.id = ?""",
        (booking_id,),
    ).fetchone()
    return dict(row) if row else None


def _already_triggered(conn, booking_id: int, sequence_name: str) -> bool:
    row = conn.execute(
        "SELECT id FROM sequence_reminders WHERE booking_id = ? AND sequence_name = ? LIMIT 1",
        (booking_id, sequence_name),
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def trigger_sequence(booking_id: int, sequence_name: str) -> list[dict]:
    """
    Create all reminder records for a sequence.
    Returns list of created reminder dicts.
    """
    seq = SEQUENCES.get(sequence_name)
    if not seq:
        raise ValueError(f"Unknown sequence: {sequence_name}")

    now = datetime.now()
    created: list[dict] = []

    with get_db() as conn:
        ctx = _get_booking_context(conn, booking_id)
        if not ctx:
            raise ValueError(f"Booking {booking_id} not found")

        # For pre_shoot, anchor to shoot_date; otherwise anchor to now
        if sequence_name == "pre_shoot" and ctx.get("shoot_date"):
            try:
                anchor = datetime.strptime(str(ctx["shoot_date"])[:10], "%Y-%m-%d")
            except ValueError:
                anchor = now
        else:
            anchor = now

        msg_context = {
            "client_name": ctx.get("client_name", ""),
            "genre":        ctx.get("genre", ""),
            "shoot_date":   str(ctx.get("shoot_date", "")),
        }

        for idx, step in enumerate(seq["steps"]):
            due_at = _resolve_due_at(step, anchor)
            message = _format_message(step["message"], msg_context)
            cursor = conn.execute(
                """INSERT INTO sequence_reminders
                   (booking_id, client_id, sequence_name, step_index, due_at, message)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    booking_id,
                    ctx.get("client_id"),
                    sequence_name,
                    idx,
                    due_at.isoformat(),
                    message,
                ),
            )
            created.append({
                "id":            cursor.lastrowid,
                "booking_id":    booking_id,
                "sequence_name": sequence_name,
                "step_index":    idx,
                "due_at":        due_at.isoformat(),
                "message":       message,
                "status":        "pending",
            })

    return created


def get_due_reminders(hours_ahead: int = 24) -> list[dict]:
    """Return reminders due within the next N hours that are still pending."""
    now = datetime.now()
    cutoff = now + timedelta(hours=hours_ahead)
    with get_db() as conn:
        rows = conn.execute(
            """SELECT r.*, c.name as client_name
               FROM sequence_reminders r
               LEFT JOIN clients c ON r.client_id = c.id
               WHERE r.status = 'pending'
               AND r.due_at <= ?
               ORDER BY r.due_at ASC""",
            (cutoff.isoformat(),),
        ).fetchall()
        return [dict(r) for r in rows]


def complete_reminder(reminder_id: int) -> dict:
    """Mark a reminder as done."""
    with get_db() as conn:
        conn.execute(
            """UPDATE sequence_reminders
               SET status = 'completed', completed_at = ?
               WHERE id = ?""",
            (datetime.now().isoformat(), reminder_id),
        )
        row = conn.execute(
            "SELECT * FROM sequence_reminders WHERE id = ?", (reminder_id,)
        ).fetchone()
        return dict(row) if row else {}


def get_reminders_for_booking(booking_id: int) -> list[dict]:
    """Return all reminders for a single booking."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM sequence_reminders WHERE booking_id = ? ORDER BY due_at ASC",
            (booking_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def check_and_trigger_sequences() -> dict[str, int]:
    """
    Scan all active bookings and trigger appropriate sequences based on
    status and date. Skips sequences already triggered for a booking.
    Returns a summary dict of {sequence_name: count_triggered}.
    """
    summary: dict[str, int] = {k: 0 for k in SEQUENCES}
    now = datetime.now()

    with get_db() as conn:
        bookings = conn.execute(
            """SELECT b.*, c.name as client_name
               FROM bookings b JOIN clients c ON b.client_id = c.id"""
        ).fetchall()

    for raw in bookings:
        b = dict(raw)
        booking_id = b["id"]

        with get_db() as conn:
            # inquiry_followup: trigger when status = inquiry
            if b.get("status") == "inquiry":
                if not _already_triggered(conn, booking_id, "inquiry_followup"):
                    try:
                        trigger_sequence(booking_id, "inquiry_followup")
                        summary["inquiry_followup"] += 1
                    except Exception:
                        pass

            # pre_shoot: trigger when booked and shoot_date within 8 days (buffer)
            if b.get("status") == "booked" and b.get("shoot_date"):
                try:
                    shoot_dt = datetime.strptime(str(b["shoot_date"])[:10], "%Y-%m-%d")
                    days_until = (shoot_dt - now).days
                    if 0 <= days_until <= 8:
                        if not _already_triggered(conn, booking_id, "pre_shoot"):
                            trigger_sequence(booking_id, "pre_shoot")
                            summary["pre_shoot"] += 1
                except (ValueError, TypeError):
                    pass

            # post_shoot: trigger when status = shot
            if b.get("status") == "shot":
                if not _already_triggered(conn, booking_id, "post_shoot"):
                    try:
                        trigger_sequence(booking_id, "post_shoot")
                        summary["post_shoot"] += 1
                    except Exception:
                        pass

            # rebooking: trigger when complete and last_booked > 180 days ago
            if b.get("status") == "complete":
                try:
                    last_booked = b.get("last_booked") or b.get("shoot_date")
                    if last_booked:
                        last_dt = datetime.strptime(str(last_booked)[:10], "%Y-%m-%d")
                        if (now - last_dt).days > 180:
                            if not _already_triggered(conn, booking_id, "rebooking"):
                                trigger_sequence(booking_id, "rebooking")
                                summary["rebooking"] += 1
                except (ValueError, TypeError):
                    pass

    return summary
