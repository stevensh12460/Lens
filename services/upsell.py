"""
services/upsell.py

Print and product upsell engine — pure SQL, no LLM.
After a shoot is delivered, surfaces portfolio_worthy images for print upsell.

Standard print prices:
  11x14  = $150
  16x20  = $300
  20x30  = $450
"""

from datetime import datetime
from typing import Optional

from core.database import get_db

PRINT_PRICES = {
    "11x14": 150,
    "16x20": 300,
    "20x30": 450,
}

# Recommended print size by image quality score
def _suggest_prints(quality_score: Optional[float]) -> list[dict]:
    score = quality_score or 0
    suggestions = []
    if score >= 0.85:
        suggestions = [
            {"size": "20x30", "price": PRINT_PRICES["20x30"], "notes": "Signature large-format print"},
            {"size": "16x20", "price": PRINT_PRICES["16x20"], "notes": "Wall art"},
            {"size": "11x14", "price": PRINT_PRICES["11x14"], "notes": "Desk/shelf display"},
        ]
    elif score >= 0.70:
        suggestions = [
            {"size": "16x20", "price": PRINT_PRICES["16x20"], "notes": "Wall art"},
            {"size": "11x14", "price": PRINT_PRICES["11x14"], "notes": "Desk/shelf display"},
        ]
    else:
        suggestions = [
            {"size": "11x14", "price": PRINT_PRICES["11x14"], "notes": "Desk/shelf display"},
        ]
    return suggestions


def _ensure_upsell_column() -> None:
    """Add upsell_sent_at to bookings if it doesn't exist."""
    with get_db() as conn:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(bookings)").fetchall()}
        if "upsell_sent_at" not in existing:
            conn.execute("ALTER TABLE bookings ADD COLUMN upsell_sent_at DATETIME")


def get_upsell_opportunities(booking_id: int) -> dict:
    """
    For a delivered booking, find portfolio_worthy images from the linked shoot
    and return with suggested print sizes and estimated revenue.
    """
    _ensure_upsell_column()
    with get_db() as conn:
        booking = conn.execute(
            """
            SELECT b.*, c.name AS client_name, c.email AS client_email
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            WHERE b.id = ?
            """,
            (booking_id,),
        ).fetchone()

        if not booking:
            return {"error": f"Booking {booking_id} not found"}

        booking = dict(booking)

        if not booking.get("shoot_id"):
            return {
                "booking_id": booking_id,
                "client_name": booking.get("client_name"),
                "eligible_images": [],
                "estimated_revenue": 0,
                "message": "No linked shoot found for this booking",
            }

        images = conn.execute(
            """
            SELECT id, file_path, file_name, genre, mood, lighting,
                   quality_score, nima_composite, tags, caption_draft
            FROM images
            WHERE shoot_id = ?
              AND portfolio_worthy = TRUE
            ORDER BY COALESCE(quality_score, nima_composite, 0) DESC
            """,
            (booking["shoot_id"],),
        ).fetchall()

    eligible = []
    total_min_revenue = 0
    total_max_revenue = 0

    for img in images:
        img_dict = dict(img)
        prints = _suggest_prints(img_dict.get("quality_score") or img_dict.get("nima_composite"))
        min_price = prints[-1]["price"] if prints else 0
        max_price = prints[0]["price"] if prints else 0
        total_min_revenue += min_price
        total_max_revenue += max_price
        img_dict["suggested_prints"] = prints
        img_dict["min_print_value"] = min_price
        img_dict["max_print_value"] = max_price
        eligible.append(img_dict)

    return {
        "booking_id": booking_id,
        "client_name": booking.get("client_name"),
        "client_email": booking.get("client_email"),
        "genre": booking.get("genre"),
        "shoot_id": booking.get("shoot_id"),
        "upsell_sent_at": booking.get("upsell_sent_at"),
        "eligible_images_count": len(eligible),
        "eligible_images": eligible,
        "estimated_revenue_min": total_min_revenue,
        "estimated_revenue_max": total_max_revenue,
    }


def get_all_upsell_queue() -> list[dict]:
    """
    All delivered bookings where print upsell hasn't been triggered yet,
    with count of eligible (portfolio_worthy) images per shoot.
    """
    _ensure_upsell_column()
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                b.id            AS booking_id,
                b.genre,
                b.shoot_date,
                b.upsell_sent_at,
                c.name          AS client_name,
                c.email         AS client_email,
                s.id            AS shoot_id,
                s.delivered_at,
                COUNT(i.id)     AS portfolio_worthy_count
            FROM bookings b
            JOIN clients c ON c.id = b.client_id
            JOIN shoots s ON s.id = b.shoot_id
            LEFT JOIN images i ON i.shoot_id = s.id AND i.portfolio_worthy = TRUE
            WHERE (b.status = 'delivered' OR s.delivered_at IS NOT NULL)
              AND (b.upsell_sent_at IS NULL OR b.upsell_sent_at = '')
              AND s.id IS NOT NULL
            GROUP BY b.id
            HAVING portfolio_worthy_count > 0
            ORDER BY s.delivered_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def mark_upsell_sent(booking_id: int) -> dict:
    """
    Mark that the print upsell was offered for this booking.
    Sets upsell_sent_at to now.
    """
    _ensure_upsell_column()
    with get_db() as conn:
        conn.execute(
            "UPDATE bookings SET upsell_sent_at = datetime('now') WHERE id = ?",
            (booking_id,),
        )
        row = conn.execute(
            "SELECT id, upsell_sent_at FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
    if not row:
        return {"error": f"Booking {booking_id} not found"}
    return {"booking_id": row["id"], "upsell_sent_at": row["upsell_sent_at"], "status": "marked"}


def get_upsell_summary() -> dict:
    """
    Total upsell opportunities, potential revenue at standard print prices.
    """
    _ensure_upsell_column()
    queue = get_all_upsell_queue()

    with get_db() as conn:
        # Already sent
        sent_count = conn.execute(
            "SELECT COUNT(*) FROM bookings WHERE upsell_sent_at IS NOT NULL"
        ).fetchone()[0]

        # Total portfolio-worthy images across all shoots
        total_pw = conn.execute(
            "SELECT COUNT(*) FROM images WHERE portfolio_worthy = TRUE"
        ).fetchone()[0]

    total_opportunities = len(queue)
    total_eligible_images = sum(r["portfolio_worthy_count"] for r in queue)

    # Estimate: assume avg print per image = 16x20 price
    avg_price = PRINT_PRICES["16x20"]
    potential_revenue = total_eligible_images * avg_price

    # Better range estimates
    min_revenue = total_eligible_images * PRINT_PRICES["11x14"]
    max_revenue = total_eligible_images * PRINT_PRICES["20x30"]

    return {
        "unsent_opportunities": total_opportunities,
        "upsell_already_sent": sent_count,
        "total_eligible_images": total_eligible_images,
        "total_portfolio_worthy_library": total_pw,
        "estimated_revenue_min": min_revenue,
        "estimated_revenue_max": max_revenue,
        "estimated_revenue_at_16x20": potential_revenue,
        "print_prices": PRINT_PRICES,
        "queue": queue,
    }
