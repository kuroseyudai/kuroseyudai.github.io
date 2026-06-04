from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import requests

from system.config.settings import settings
from system.db import client as db

logger = logging.getLogger(__name__)

MEDIUM_API_BASE = "https://api.medium.com/v1"


class MediumPublisher:
    def __init__(self, integration_token: Optional[str] = None):
        self.token = integration_token or settings.MEDIUM_INTEGRATION_TOKEN
        self._user_id: Optional[str] = None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def get_user_id(self) -> Optional[str]:
        if self._user_id:
            return self._user_id
        try:
            resp = requests.get(
                f"{MEDIUM_API_BASE}/me",
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            self._user_id = resp.json().get("data", {}).get("id")
            return self._user_id
        except requests.RequestException as exc:
            logger.error("Failed to fetch Medium user id: %s", exc)
            return None

    def create_post(
        self,
        title: str,
        content: str,
        content_format: str = "html",
        publish_status: str = "public",
        tags: Optional[list[str]] = None,
        canonical_url: Optional[str] = None,
    ) -> Optional[dict]:
        user_id = self.get_user_id()
        if not user_id:
            logger.error("Cannot publish to Medium: user ID unavailable")
            return None

        payload: dict = {
            "title": title,
            "contentFormat": content_format,
            "content": f"<h1>{title}</h1>{content}",
            "publishStatus": publish_status,
        }
        if tags:
            payload["tags"] = tags[:5]
        if canonical_url:
            payload["canonicalUrl"] = canonical_url

        try:
            resp = requests.post(
                f"{MEDIUM_API_BASE}/users/{user_id}/posts",
                json=payload,
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json().get("data", {})
        except requests.HTTPError as exc:
            logger.error("Medium post creation failed (HTTP %s): %s", exc.response.status_code, exc)
            return None
        except requests.RequestException as exc:
            logger.error("Medium request error: %s", exc)
            return None


def publish_article_to_medium(
    article_row: dict,
    publisher: Optional[MediumPublisher] = None,
    tags: Optional[list[str]] = None,
) -> bool:
    if not settings.MEDIUM_INTEGRATION_TOKEN:
        logger.info("Medium integration token not configured, skipping")
        return False

    article_id = article_row["id"]
    if publisher is None:
        publisher = MediumPublisher()

    title = article_row.get("title_a") or "Untitled"
    content = article_row.get("content", "")

    result = publisher.create_post(title=title, content=content, tags=tags)

    if result is None:
        logger.error("Failed to publish article %s to Medium", article_id)
        return False

    post_url = result.get("url", "")

    db.insert(
        "publications",
        {
            "article_id": article_id,
            "platform": "medium",
            "url": post_url,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "status": "published",
        },
    )

    logger.info("Published article %s to Medium: %s", article_id, post_url)
    return True
