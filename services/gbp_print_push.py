"""
Phase 7b — Google Business Profile Print Push
Queues print-worthy images for GBP posting and builds API payloads.
No actual GBP API call yet — OAuth setup required by user.
The gbp_pushed_at column is added by the Phase 7b database migration.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from core.database import get_db

logger = logging.getLogger(__name__)


def get_gbp_queue(limit: int = 10) -> list[dict]:
    """
    Print-worthy images not yet pushed to GBP, ordered by print_score DESC.
    These are ready to queue for Google Business Profile posts.
    """
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, file_name, file_path, print_score, print_tier,
                      print_technique, edition_title, tags, caption_draft,
                      print_location_name, nima_composite
               FROM images
               WHERE print_worthy = 1
                 AND gbp_pushed_at IS NULL
               ORDER BY print_score DESC NULLS LAST
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_gbp_pushed(image_id: int) -> dict:
    """
    Record that an image has been pushed to GBP.
    Sets gbp_pushed_at to the current UTC timestamp.
    Returns the updated fields.
    """
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        conn.execute(
            "UPDATE images SET gbp_pushed_at = ? WHERE id = ?",
            (now, image_id),
        )
        row = conn.execute(
            "SELECT id, file_name, gbp_pushed_at FROM images WHERE id = ?",
            (image_id,),
        ).fetchone()
    return dict(row) if row else {"image_id": image_id, "gbp_pushed_at": now}


def get_gbp_status() -> dict:
    """
    Summary of GBP push activity:
    - last push date
    - images pushed this week
    - images waiting in queue
    """
    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()

    with get_db() as conn:
        last_push_row = conn.execute(
            """SELECT MAX(gbp_pushed_at) AS last_push FROM images
               WHERE gbp_pushed_at IS NOT NULL"""
        ).fetchone()

        pushed_this_week = conn.execute(
            """SELECT COUNT(*) AS cnt FROM images
               WHERE gbp_pushed_at >= ?""",
            (week_ago,),
        ).fetchone()

        queue_count = conn.execute(
            """SELECT COUNT(*) AS cnt FROM images
               WHERE print_worthy = 1 AND gbp_pushed_at IS NULL"""
        ).fetchone()

    return {
        "last_push_date": last_push_row["last_push"] if last_push_row else None,
        "pushed_this_week": pushed_this_week["cnt"] or 0,
        "waiting_in_queue": queue_count["cnt"] or 0,
    }


def prepare_gbp_payload(image_id: int) -> dict:
    """
    Build the GBP API data payload for an image.
    Ready for submission once OAuth is configured.

    Payload structure mirrors the Google Business Profile Media API:
    https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media

    Required OAuth scope: https://www.googleapis.com/auth/business.manage
    """
    with get_db() as conn:
        row = conn.execute(
            """SELECT id, file_path, file_name, caption_draft, tags,
                      print_score, print_tier, print_technique,
                      edition_title, print_location_name,
                      nima_composite, print_worthy, gbp_pushed_at
               FROM images WHERE id = ?""",
            (image_id,),
        ).fetchone()

    if not row:
        return {"error": f"Image {image_id} not found"}

    data = dict(row)

    # Build caption from available data
    caption_parts = []
    if data["caption_draft"]:
        caption_parts.append(data["caption_draft"])
    if data["edition_title"]:
        caption_parts.append(f"Limited Edition: {data['edition_title']}")
    if data["print_location_name"]:
        caption_parts.append(f"Location: {data['print_location_name']}")
    caption_parts.append("#fineart #print #photography")

    # Parse tags
    tags_raw = data["tags"] or ""
    try:
        tags_list = json.loads(tags_raw) if tags_raw.startswith("[") else [t.strip() for t in tags_raw.split(",") if t.strip()]
    except Exception:
        tags_list = []

    technique_label = {
        "rotation": "Long Exposure / Rotation",
        "turntable": "Turntable Technique",
        "orbit": "Orbital Motion",
        "standard": "Fine Art Photography",
    }.get(data["print_technique"] or "standard", "Fine Art Photography")

    return {
        "image_id": image_id,
        "image_path": data["file_path"],
        "media_format": "PHOTO",
        "caption": " | ".join(caption_parts),
        "tags": tags_list,
        "location_name": data["print_location_name"] or "",
        "category": "EXTERIOR",  # GBP media category
        "print_tier": data["print_tier"],
        "technique_label": technique_label,
        "print_score": data["print_score"],
        "already_pushed": bool(data["gbp_pushed_at"]),
        "oauth_required": True,
        "oauth_scope": "https://www.googleapis.com/auth/business.manage",
        "api_endpoint": "POST https://mybusiness.googleapis.com/v4/accounts/{accountId}/locations/{locationId}/media",
        "note": "OAuth not yet configured. Run `lens gbp auth` to set up credentials.",
    }
