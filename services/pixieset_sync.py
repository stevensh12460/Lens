"""
services/pixieset_sync.py

Pixieset store sync — tracks catalog counts and unsynced images.
"""

from core.database import get_db
from core.config import settings


def get_sync_status() -> dict:
    """
    Return Pixieset sync status: configured flag, catalog count,
    unsynced image count.
    """
    configured = bool(settings.pixieset_api_key)
    store_url = settings.pixieset_store_url or None

    with get_db() as conn:
        synced = conn.execute(
            "SELECT COUNT(*) FROM images WHERE pixieset_url IS NOT NULL AND pixieset_url != ''"
        ).fetchone()[0]

        unsynced = conn.execute(
            """SELECT COUNT(*) FROM images
               WHERE content_ready = TRUE
                 AND (pixieset_url IS NULL OR pixieset_url = '')"""
        ).fetchone()[0]

    return {
        "configured": configured,
        "store_url": store_url,
        "synced_count": synced,
        "unsynced_count": unsynced,
    }
