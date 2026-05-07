"""
CRM — Self-hosted gallery delivery portal.
No LLM calls. All DB access through core/database.py.
"""
from __future__ import annotations

import random
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional

from core.database import get_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_token(length: int = 32) -> str:
    """Generate a cryptographically secure URL-safe token."""
    return secrets.token_urlsafe(length)


def _generate_pin(length: int = 4) -> str:
    """Generate a numeric PIN of the given length."""
    return "".join(random.choices(string.digits, k=length))


# ---------------------------------------------------------------------------
# Gallery management
# ---------------------------------------------------------------------------

def create_gallery(
    shoot_id: int,
    image_paths: list[str],
    pin: Optional[str] = None,
    expires_days: int = 90,
) -> dict:
    """
    Create a gallery record for a shoot.

    Args:
        shoot_id:     ID of the associated shoot.
        image_paths:  List of file paths to include.
        pin:          4-digit PIN (auto-generated if not provided).
        expires_days: Days until gallery expires (default 90).

    Returns gallery dict including token, pin, and gallery_url path.
    """
    token = _generate_token()
    actual_pin = pin or _generate_pin()
    now = datetime.now()
    expires_at = (now + timedelta(days=expires_days)).isoformat()

    with get_db() as conn:
        # Look up client_id from shoot
        shoot_row = conn.execute(
            "SELECT client_id FROM shoots WHERE id = ?", (shoot_id,)
        ).fetchone()
        client_id = shoot_row["client_id"] if shoot_row else None

        # Insert gallery record
        cursor = conn.execute(
            """INSERT INTO galleries
               (shoot_id, client_id, token, pin, expires_at)
               VALUES (?, ?, ?, ?, ?)""",
            (shoot_id, client_id, token, actual_pin, expires_at),
        )
        gallery_id = cursor.lastrowid

        # Insert gallery_images records
        for path in image_paths:
            conn.execute(
                """INSERT INTO gallery_images (gallery_id, file_path) VALUES (?, ?)""",
                (gallery_id, path),
            )

        # Update shoot's gallery_url
        gallery_url = f"/gallery/{token}"
        conn.execute(
            "UPDATE shoots SET gallery_url = ? WHERE id = ?",
            (gallery_url, shoot_id),
        )

        row = conn.execute(
            "SELECT * FROM galleries WHERE id = ?", (gallery_id,)
        ).fetchone()
        result = dict(row)
        result["image_count"] = len(image_paths)
        result["gallery_url"] = gallery_url
        return result


def get_gallery_by_token(token: str) -> Optional[dict]:
    """Retrieve gallery metadata if the token exists and gallery is active."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM galleries WHERE token = ? AND active = TRUE",
            (token,),
        ).fetchone()
        if not row:
            return None
        gallery = dict(row)

        # Check expiry
        if gallery.get("expires_at"):
            try:
                exp = datetime.fromisoformat(gallery["expires_at"])
                if datetime.now() > exp:
                    return None
            except (ValueError, TypeError):
                pass

        # Update view count and last accessed
        conn.execute(
            """UPDATE galleries
               SET total_views = total_views + 1, last_accessed = ?
               WHERE token = ?""",
            (datetime.now().isoformat(), token),
        )
        return gallery


def verify_gallery_pin(token: str, pin: str) -> bool:
    """Validate the PIN for a gallery. Returns True if correct."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT pin FROM galleries WHERE token = ? AND active = TRUE",
            (token,),
        ).fetchone()
        if not row:
            return False
        return row["pin"] == str(pin)


def get_gallery_images(token: str) -> list[dict]:
    """Return list of image records for a gallery identified by token."""
    with get_db() as conn:
        gallery_row = conn.execute(
            "SELECT id FROM galleries WHERE token = ?", (token,)
        ).fetchone()
        if not gallery_row:
            return []
        rows = conn.execute(
            """SELECT gi.*, i.file_name, i.nima_composite, i.tags
               FROM gallery_images gi
               LEFT JOIN images i ON gi.image_id = i.id
               WHERE gi.gallery_id = ?
               ORDER BY gi.added_at ASC""",
            (gallery_row["id"],),
        ).fetchall()
        return [dict(r) for r in rows]


def record_download(token: str, image_id: int) -> bool:
    """Log a client download event, increment gallery download counter."""
    with get_db() as conn:
        gallery_row = conn.execute(
            "SELECT id FROM galleries WHERE token = ?", (token,)
        ).fetchone()
        if not gallery_row:
            return False
        conn.execute(
            """UPDATE galleries
               SET total_downloads = total_downloads + 1
               WHERE id = ?""",
            (gallery_row["id"],),
        )
    return True


def get_gallery_stats(shoot_id: int) -> Optional[dict]:
    """Return aggregate stats for all galleries associated with a shoot."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT
                   COUNT(*) as gallery_count,
                   SUM(total_views) as total_views,
                   SUM(total_downloads) as total_downloads,
                   MAX(last_accessed) as last_accessed
               FROM galleries WHERE shoot_id = ?""",
            (shoot_id,),
        ).fetchone()
        if not row:
            return None
        stats = dict(row)

        # Count images in the most recent gallery
        gallery_row = conn.execute(
            "SELECT id FROM galleries WHERE shoot_id = ? ORDER BY created_at DESC LIMIT 1",
            (shoot_id,),
        ).fetchone()
        if gallery_row:
            img_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM gallery_images WHERE gallery_id = ?",
                (gallery_row["id"],),
            ).fetchone()
            stats["image_count"] = img_count["cnt"] if img_count else 0
        else:
            stats["image_count"] = 0

        return stats
