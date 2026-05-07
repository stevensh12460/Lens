"""
core/instagram.py

Instagram Graph API client for LENS.
Handles media container creation, publishing, and token management.
Requires: INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_ACCOUNT_ID in .env
"""

import logging
from datetime import datetime, timezone

import httpx

from core.config import settings
from core.database import get_db

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v19.0"


class InstagramClient:
    """Instagram Graph API client for publishing images."""

    def __init__(self):
        self.access_token = settings.instagram_access_token
        self.account_id = settings.instagram_account_id
        self._base_url = GRAPH_API_BASE

    def is_configured(self) -> bool:
        """Check if Instagram credentials are present."""
        return bool(self.access_token and self.account_id)

    def _not_configured(self) -> dict:
        return {"error": "Instagram not configured"}

    def _check_token_expiry(self) -> dict | None:
        """
        Check oauth_tokens table for token expiry.
        Returns error dict if expired, None if OK or no record.
        """
        try:
            with get_db() as conn:
                row = conn.execute(
                    "SELECT expires_at FROM oauth_tokens WHERE service = 'instagram'",
                ).fetchone()
            if row and row["expires_at"]:
                expires_at = datetime.fromisoformat(row["expires_at"])
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if expires_at <= datetime.now(timezone.utc):
                    logger.warning("Instagram access token has expired")
                    return {"error": "Instagram token expired", "expires_at": row["expires_at"]}
        except Exception as e:
            logger.debug(f"Could not check token expiry: {e}")
        return None

    async def publish_image(self, image_url: str, caption: str) -> dict:
        """
        Publish an image to Instagram using the two-step container flow.

        Step 1: Create a media container with the image URL and caption.
        Step 2: Publish the container.

        Args:
            image_url: Public URL of the image to post.
            caption: Post caption including hashtags.

        Returns:
            dict with 'id' of the published post, or 'error' on failure.
        """
        if not self.is_configured():
            return self._not_configured()

        token_error = self._check_token_expiry()
        if token_error:
            return token_error

        async with httpx.AsyncClient(timeout=60) as client:
            # Step 1: Create media container
            create_resp = await client.post(
                f"{self._base_url}/{self.account_id}/media",
                params={
                    "image_url": image_url,
                    "caption": caption,
                    "access_token": self.access_token,
                },
            )
            create_data = create_resp.json()

            if "error" in create_data:
                logger.error(f"IG container creation failed: {create_data['error']}")
                return {"error": create_data["error"].get("message", str(create_data["error"]))}

            container_id = create_data.get("id")
            if not container_id:
                return {"error": "No container ID returned from Instagram"}

            # Step 2: Publish the container
            publish_resp = await client.post(
                f"{self._base_url}/{self.account_id}/media_publish",
                params={
                    "creation_id": container_id,
                    "access_token": self.access_token,
                },
            )
            publish_data = publish_resp.json()

            if "error" in publish_data:
                logger.error(f"IG publish failed: {publish_data['error']}")
                return {"error": publish_data["error"].get("message", str(publish_data["error"]))}

            post_id = publish_data.get("id")
            logger.info(f"Published to Instagram: {post_id}")
            return {"id": post_id, "status": "published"}

    async def get_account_info(self) -> dict:
        """
        Fetch basic Instagram account info for verification.

        Returns:
            dict with account fields or 'error'.
        """
        if not self.is_configured():
            return self._not_configured()

        token_error = self._check_token_expiry()
        if token_error:
            return token_error

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self._base_url}/{self.account_id}",
                params={
                    "fields": "id,username,name,media_count,followers_count",
                    "access_token": self.access_token,
                },
            )
            data = resp.json()

            if "error" in data:
                logger.error(f"IG account info failed: {data['error']}")
                return {"error": data["error"].get("message", str(data["error"]))}

            return data


# Module-level singleton
instagram = InstagramClient()
