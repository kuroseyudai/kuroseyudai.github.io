from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import praw
import requests

from system.config.settings import settings
from system.db import client as db

logger = logging.getLogger(__name__)

GENRE_TO_SUBREDDITS: dict[str, list[str]] = {
    "technology": ["technology", "programming", "MachineLearning", "artificial"],
    "finance": ["personalfinance", "investing", "financialindependence", "StockMarket"],
    "health": ["fitness", "nutrition", "HealthyFood", "loseit"],
    "lifestyle": ["LifeProTips", "travel", "homeimprovement", "food"],
}

PINTEREST_API_BASE = "https://api.pinterest.com/v5"


class PinterestPublisher:
    def __init__(self, access_token: Optional[str] = None):
        self.token = access_token or settings.PINTEREST_ACCESS_TOKEN

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _get_board_id(self) -> Optional[str]:
        """Fetch the first available board id for the authenticated user."""
        try:
            resp = requests.get(
                f"{PINTEREST_API_BASE}/boards",
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
            return items[0]["id"] if items else None
        except requests.RequestException as exc:
            logger.error("Failed to fetch Pinterest boards: %s", exc)
            return None

    def create_pin(
        self,
        title: str,
        description: str,
        link: str,
        image_url: Optional[str] = None,
        board_id: Optional[str] = None,
    ) -> Optional[dict]:
        if not self.token:
            logger.info("Pinterest token not configured")
            return None

        if not board_id:
            board_id = self._get_board_id()
        if not board_id:
            logger.error("No Pinterest board found")
            return None

        payload: dict = {
            "board_id": board_id,
            "title": title,
            "description": description,
            "link": link,
            "media_source": {
                "source_type": "image_url",
                "url": image_url or "https://via.placeholder.com/800x600.png",
            },
        }

        try:
            resp = requests.post(
                f"{PINTEREST_API_BASE}/pins",
                json=payload,
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as exc:
            logger.error("Pinterest pin creation failed (HTTP %s): %s", exc.response.status_code, exc)
            return None
        except requests.RequestException as exc:
            logger.error("Pinterest request error: %s", exc)
            return None


class RedditPublisher:
    def __init__(self):
        if not all([settings.REDDIT_CLIENT_ID, settings.REDDIT_CLIENT_SECRET,
                    settings.REDDIT_USERNAME, settings.REDDIT_PASSWORD]):
            self._reddit: Optional[praw.Reddit] = None
            return
        self._reddit = praw.Reddit(
            client_id=settings.REDDIT_CLIENT_ID,
            client_secret=settings.REDDIT_CLIENT_SECRET,
            username=settings.REDDIT_USERNAME,
            password=settings.REDDIT_PASSWORD,
            user_agent="AI Content Bot/1.0",
        )

    def post_to_subreddit(
        self,
        subreddit_name: str,
        title: str,
        url: str,
    ) -> Optional[str]:
        if self._reddit is None:
            logger.info("Reddit credentials not configured")
            return None
        try:
            subreddit = self._reddit.subreddit(subreddit_name)
            submission = subreddit.submit(title=title, url=url)
            return f"https://reddit.com{submission.permalink}"
        except praw.exceptions.PRAWException as exc:
            logger.error("Reddit post to r/%s failed: %s", subreddit_name, exc)
            return None
        except Exception as exc:
            logger.error("Unexpected Reddit error: %s", exc)
            return None


def publish_to_pinterest(
    article_row: dict,
    post_url: str,
    publisher: Optional[PinterestPublisher] = None,
) -> bool:
    if not settings.PINTEREST_ACCESS_TOKEN:
        return False

    article_id = article_row["id"]
    if publisher is None:
        publisher = PinterestPublisher()

    title = article_row.get("title_a") or "Untitled"
    meta_desc = article_row.get("meta_desc", "")[:500]

    result = publisher.create_pin(
        title=title,
        description=meta_desc,
        link=post_url,
    )

    if result is None:
        return False

    pin_url = result.get("id", "")
    db.insert(
        "publications",
        {
            "article_id": article_id,
            "platform": "pinterest",
            "url": f"https://www.pinterest.com/pin/{pin_url}/",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "status": "published",
        },
    )
    logger.info("Published article %s to Pinterest pin=%s", article_id, pin_url)
    return True


def publish_to_reddit(
    article_row: dict,
    post_url: str,
    genre: Optional[str] = None,
    publisher: Optional[RedditPublisher] = None,
) -> list[str]:
    if not all([settings.REDDIT_CLIENT_ID, settings.REDDIT_CLIENT_SECRET]):
        return []

    article_id = article_row["id"]
    if publisher is None:
        publisher = RedditPublisher()

    title = article_row.get("title_a") or "Untitled"
    subreddits = GENRE_TO_SUBREDDITS.get(genre or "", ["blog"])
    posted_urls: list[str] = []

    for subreddit in subreddits[:2]:
        permalink = publisher.post_to_subreddit(subreddit, title, post_url)
        if permalink:
            db.insert(
                "publications",
                {
                    "article_id": article_id,
                    "platform": f"reddit_r_{subreddit}",
                    "url": permalink,
                    "published_at": datetime.now(timezone.utc).isoformat(),
                    "status": "published",
                },
            )
            posted_urls.append(permalink)

    return posted_urls
