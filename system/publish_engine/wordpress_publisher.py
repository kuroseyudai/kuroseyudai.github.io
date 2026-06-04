from __future__ import annotations

import logging
from typing import Optional
from datetime import datetime, timezone

import requests
from requests.auth import HTTPBasicAuth

from system.config.settings import settings
from system.db import client as db

logger = logging.getLogger(__name__)


class WordPressPublisher:
    def __init__(self, base_url: Optional[str] = None, username: Optional[str] = None, app_password: Optional[str] = None):
        self.base_url = (base_url or settings.WP_URL).rstrip("/")
        self.auth = HTTPBasicAuth(
            username or settings.WP_USER,
            app_password or settings.WP_APP_PASSWORD,
        )
        self.api_base = f"{self.base_url}/wp-json/wp/v2"

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json", "Accept": "application/json"}

    def create_post(
        self,
        title: str,
        content: str,
        meta_desc: str = "",
        status: str = "publish",
        categories: Optional[list[int]] = None,
        tags: Optional[list[int]] = None,
        custom_fields: Optional[dict] = None,
    ) -> Optional[dict]:
        payload: dict = {
            "title": title,
            "content": content,
            "status": status,
        }
        if categories:
            payload["categories"] = categories
        if tags:
            payload["tags"] = tags
        if meta_desc:
            payload["excerpt"] = meta_desc
        if custom_fields:
            payload["meta"] = custom_fields

        try:
            resp = requests.post(
                f"{self.api_base}/posts",
                json=payload,
                auth=self.auth,
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as exc:
            logger.error("WordPress post creation failed (HTTP %s): %s", exc.response.status_code, exc)
            return None
        except requests.RequestException as exc:
            logger.error("WordPress request error: %s", exc)
            return None

    def update_post_title(self, post_id: int, title: str) -> bool:
        try:
            resp = requests.post(
                f"{self.api_base}/posts/{post_id}",
                json={"title": title},
                auth=self.auth,
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            return True
        except requests.RequestException as exc:
            logger.error("WordPress update post %d failed: %s", post_id, exc)
            return False

    def get_post(self, post_id: int) -> Optional[dict]:
        try:
            resp = requests.get(
                f"{self.api_base}/posts/{post_id}",
                auth=self.auth,
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.error("WordPress get post %d failed: %s", post_id, exc)
            return None


def publish_article(article_row: dict, publisher: Optional[WordPressPublisher] = None) -> bool:
    """
    Publish an article to WordPress. Sets title_a as the initial title.
    On failure saves error status and marks for retry next day.
    """
    article_id = article_row["id"]

    if publisher is None:
        publisher = WordPressPublisher()

    title = article_row.get("title_a") or article_row.get("title_b") or "Untitled"
    content = article_row.get("content", "")
    meta_desc = article_row.get("meta_desc", "")

    wp_result = publisher.create_post(title=title, content=content, meta_desc=meta_desc)

    if wp_result is None:
        logger.error("Failed to publish article %s to WordPress", article_id)
        db.update("articles", {"id": article_id}, {"status": "publish_error"})
        return False

    wp_post_id = wp_result.get("id")
    post_url = wp_result.get("link", "")

    db.update(
        "articles",
        {"id": article_id},
        {"status": "published", "wp_post_id": wp_post_id},
    )

    db.insert(
        "publications",
        {
            "article_id": article_id,
            "platform": "wordpress",
            "url": post_url,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "status": "published",
        },
    )

    logger.info("Published article %s to WordPress post_id=%s url=%s", article_id, wp_post_id, post_url)
    return True


def retry_failed_publications() -> list[str]:
    """Retry articles that failed to publish yesterday."""
    failed = db.select("articles", filters={"status": "publish_error"})
    publisher = WordPressPublisher()
    retried: list[str] = []

    for article in failed:
        success = publish_article(article, publisher)
        if success:
            retried.append(article["id"])

    return retried


def batch_publish(limit: int = 20) -> list[str]:
    """Publish all draft articles up to limit."""
    drafts = db.select_raw(
        "articles",
        filters={"status": "draft"},
        limit=limit,
        order_by="created_at",
    )
    publisher = WordPressPublisher()
    published: list[str] = []

    for article in drafts:
        success = publish_article(article, publisher)
        if success:
            published.append(article["id"])

    return published
