"""
Phase 7b — Edition Tracker
Limited edition management: creation, sales recording, milestone alerts.
No LLM dependency.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from core.database import get_db

logger = logging.getLogger(__name__)


def create_edition(
    image_id: int,
    title: str,
    edition_size: int,
    tier: str,
    technique: str,
) -> dict:
    """
    Define a limited edition for an image.
    Sets edition_title, edition_size, print_tier, print_technique, print_worthy=True.
    Returns the updated image record fields.
    """
    with get_db() as conn:
        conn.execute(
            """UPDATE images
               SET edition_title  = :title,
                   edition_size   = :edition_size,
                   print_tier     = :tier,
                   print_technique = :technique,
                   print_worthy   = 1
               WHERE id = :image_id""",
            {
                "title": title,
                "edition_size": edition_size,
                "tier": tier,
                "technique": technique,
                "image_id": image_id,
            },
        )
        row = conn.execute(
            """SELECT id, file_name, edition_title, edition_size, editions_sold,
                      print_tier, print_technique, print_worthy
               FROM images WHERE id = ?""",
            (image_id,),
        ).fetchone()
    return dict(row) if row else {}


def record_sale(
    image_id: int,
    size: str,
    paper_type: str,
    sale_price: float,
    lab_cost: float,
    channel: str,
    edition_number: int | None = None,
    buyer_location: str | None = None,
    notes: str | None = None,
) -> dict:
    """
    Record a print sale for an image.
    Inserts a print_sales row and updates aggregates on the image.
    Returns the new sale record.
    """
    margin = round(sale_price - lab_cost, 2) if lab_cost else sale_price

    with get_db() as conn:
        # Get current image data
        img = conn.execute(
            """SELECT editions_sold, edition_size, print_total_revenue,
                      print_times_sold, print_first_sale_at, print_tier
               FROM images WHERE id = ?""",
            (image_id,),
        ).fetchone()

        if not img:
            raise ValueError(f"Image {image_id} not found")

        tier = img["print_tier"] or "standard"
        now = datetime.utcnow().isoformat()

        # Insert sale record
        cur = conn.execute(
            """INSERT INTO print_sales
               (image_id, sale_date, size, paper_type, tier, edition_number,
                sale_price, lab_cost, margin, channel, buyer_location, notes)
               VALUES (:image_id, :sale_date, :size, :paper_type, :tier,
                       :edition_number, :sale_price, :lab_cost, :margin,
                       :channel, :buyer_location, :notes)""",
            {
                "image_id": image_id,
                "sale_date": now,
                "size": size,
                "paper_type": paper_type,
                "tier": tier,
                "edition_number": edition_number,
                "sale_price": sale_price,
                "lab_cost": lab_cost,
                "margin": margin,
                "channel": channel,
                "buyer_location": buyer_location,
                "notes": notes,
            },
        )
        sale_id = cur.lastrowid

        new_editions_sold = (img["editions_sold"] or 0) + 1
        new_revenue = round((img["print_total_revenue"] or 0.0) + sale_price, 2)
        new_times_sold = (img["print_times_sold"] or 0) + 1
        first_sale = img["print_first_sale_at"] or now

        # Check if edition is now retired (fully sold out)
        edition_size = img["edition_size"]
        retired = False
        if edition_size and new_editions_sold >= edition_size:
            retired = True

        conn.execute(
            """UPDATE images
               SET editions_sold       = :editions_sold,
                   print_total_revenue = :revenue,
                   print_times_sold    = :times_sold,
                   print_first_sale_at = :first_sale,
                   edition_retired     = :retired
               WHERE id = :image_id""",
            {
                "editions_sold": new_editions_sold,
                "revenue": new_revenue,
                "times_sold": new_times_sold,
                "first_sale": first_sale,
                "retired": 1 if retired else 0,
                "image_id": image_id,
            },
        )

    return {
        "sale_id": sale_id,
        "image_id": image_id,
        "sale_price": sale_price,
        "lab_cost": lab_cost,
        "margin": margin,
        "channel": channel,
        "edition_number": edition_number,
        "editions_sold": new_editions_sold,
        "edition_retired": retired,
    }


def get_edition_status(image_id: int) -> dict:
    """
    Return edition progress and a suggested action based on sale milestones.
    """
    with get_db() as conn:
        row = conn.execute(
            """SELECT id, file_name, edition_title, edition_size, editions_sold,
                      edition_retired, print_tier, print_total_revenue
               FROM images WHERE id = ?""",
            (image_id,),
        ).fetchone()

    if not row:
        return {"error": f"Image {image_id} not found"}

    data = dict(row)
    edition_size = data["edition_size"] or 0
    editions_sold = data["editions_sold"] or 0

    if edition_size > 0:
        pct_sold = round((editions_sold / edition_size) * 100, 1)
        editions_remaining = edition_size - editions_sold
    else:
        pct_sold = 0.0
        editions_remaining = None

    # Determine suggested action
    suggested_action = None
    if data["edition_retired"]:
        suggested_action = "Edition complete — archive for provenance"
    elif edition_size > 0 and editions_sold >= edition_size:
        suggested_action = "Edition complete — archive for provenance"
    elif edition_size > 0 and pct_sold >= 80:
        suggested_action = f"Publicize scarcity — only {editions_remaining} remaining"
    elif edition_size > 0 and pct_sold >= 50:
        suggested_action = "Consider raising price — edition half sold"

    return {
        "image_id": image_id,
        "file_name": data["file_name"],
        "edition_title": data["edition_title"],
        "edition_size": edition_size,
        "editions_sold": editions_sold,
        "editions_remaining": editions_remaining,
        "pct_sold": pct_sold,
        "edition_retired": bool(data["edition_retired"]),
        "print_tier": data["print_tier"],
        "print_total_revenue": data["print_total_revenue"] or 0.0,
        "suggested_action": suggested_action,
    }


def get_active_editions() -> list[dict]:
    """Return all images with an edition defined that are not yet retired."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, file_name, edition_title, edition_size, editions_sold,
                      print_tier, print_technique, print_total_revenue,
                      print_times_sold, print_score
               FROM images
               WHERE edition_size IS NOT NULL
                 AND (edition_retired = 0 OR edition_retired IS NULL)
               ORDER BY print_score DESC NULLS LAST""",
        ).fetchall()
    return [dict(r) for r in rows]


def get_edition_alerts() -> list[dict]:
    """
    Return editions that have hit 50%, 80%, or 100% sold milestones.
    These are action items for the photographer.
    """
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, file_name, edition_title, edition_size, editions_sold,
                      edition_retired, print_tier, print_total_revenue
               FROM images
               WHERE edition_size IS NOT NULL AND edition_size > 0
               ORDER BY CAST(editions_sold AS REAL) / edition_size DESC""",
        ).fetchall()

    alerts = []
    for row in rows:
        data = dict(row)
        size = data["edition_size"]
        sold = data["editions_sold"] or 0
        if size <= 0:
            continue
        pct = (sold / size) * 100

        if pct >= 100 or data["edition_retired"]:
            level = "sold_out"
            action = "Edition complete — archive for provenance"
        elif pct >= 80:
            level = "near_sold_out"
            action = f"Publicize scarcity — only {size - sold} remaining"
        elif pct >= 50:
            level = "half_sold"
            action = "Consider raising price — edition half sold"
        else:
            continue  # Not at a milestone yet

        alerts.append({
            **data,
            "pct_sold": round(pct, 1),
            "editions_remaining": size - sold,
            "alert_level": level,
            "suggested_action": action,
        })

    return alerts
