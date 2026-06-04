from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from system.publish_engine.wordpress_publisher import (
    WordPressPublisher,
    publish_article,
    batch_publish,
    retry_failed_publications,
)


class TestWordPressPublisher:
    def _make_publisher(self):
        return WordPressPublisher(
            base_url="https://example.com",
            username="admin",
            app_password="secret",
        )

    @patch("system.publish_engine.wordpress_publisher.requests.post")
    def test_create_post_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": 42, "link": "https://example.com/post"}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        publisher = self._make_publisher()
        result = publisher.create_post("Test Title", "<p>Content</p>")

        assert result is not None
        assert result["id"] == 42
        assert result["link"] == "https://example.com/post"

    @patch("system.publish_engine.wordpress_publisher.requests.post")
    def test_create_post_http_error_returns_none(self, mock_post):
        import requests
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_post.return_value = mock_response
        mock_post.side_effect = requests.HTTPError(response=mock_response)

        publisher = self._make_publisher()
        result = publisher.create_post("Test Title", "<p>Content</p>")
        assert result is None

    @patch("system.publish_engine.wordpress_publisher.requests.post")
    def test_update_post_title(self, mock_post):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        publisher = self._make_publisher()
        result = publisher.update_post_title(42, "New Title")
        assert result is True

    @patch("system.publish_engine.wordpress_publisher.requests.post")
    def test_update_post_title_failure_returns_false(self, mock_post):
        import requests
        mock_post.side_effect = requests.RequestException("connection error")

        publisher = self._make_publisher()
        result = publisher.update_post_title(42, "New Title")
        assert result is False


class TestPublishArticle:
    def _make_article(self, status="draft"):
        return {
            "id": "art-uuid-1",
            "keyword_id": "kw-uuid-1",
            "language": "en",
            "title_a": "Best Laptops 2025",
            "title_b": "Top Laptops in 2025",
            "content": "<p>Content here</p>",
            "meta_desc": "Short description",
            "status": status,
            "wp_post_id": None,
        }

    @patch("system.publish_engine.wordpress_publisher.db.insert")
    @patch("system.publish_engine.wordpress_publisher.db.update")
    def test_publish_article_success(self, mock_update, mock_insert):
        mock_publisher = MagicMock(spec=WordPressPublisher)
        mock_publisher.create_post.return_value = {
            "id": 99,
            "link": "https://example.com/best-laptops-2025",
        }

        result = publish_article(self._make_article(), publisher=mock_publisher)

        assert result is True
        mock_update.assert_called_once()
        update_args = mock_update.call_args[0]
        assert update_args[2]["status"] == "published"
        assert update_args[2]["wp_post_id"] == 99
        mock_insert.assert_called_once()
        insert_args = mock_insert.call_args[0]
        assert insert_args[1]["platform"] == "wordpress"

    @patch("system.publish_engine.wordpress_publisher.db.update")
    def test_publish_article_failure_saves_error_status(self, mock_update):
        mock_publisher = MagicMock(spec=WordPressPublisher)
        mock_publisher.create_post.return_value = None

        result = publish_article(self._make_article(), publisher=mock_publisher)

        assert result is False
        mock_update.assert_called_once_with(
            "articles",
            {"id": "art-uuid-1"},
            {"status": "publish_error"},
        )

    @patch("system.publish_engine.wordpress_publisher.db.insert")
    @patch("system.publish_engine.wordpress_publisher.db.update")
    def test_publish_article_uses_title_b_when_title_a_missing(self, mock_update, mock_insert):
        mock_publisher = MagicMock(spec=WordPressPublisher)
        mock_publisher.create_post.return_value = {"id": 1, "link": "https://example.com"}

        article = self._make_article()
        article["title_a"] = None

        publish_article(article, publisher=mock_publisher)

        call_kwargs = mock_publisher.create_post.call_args[1]
        assert call_kwargs["title"] == "Top Laptops in 2025"


class TestBatchPublish:
    @patch("system.publish_engine.wordpress_publisher.WordPressPublisher")
    @patch("system.publish_engine.wordpress_publisher.db.select_raw")
    def test_batch_publish_publishes_drafts(self, mock_select_raw, mock_wp_class):
        mock_select_raw.return_value = [
            {"id": "art-1", "title_a": "T1", "title_b": "T1b", "content": "C1", "meta_desc": ""},
            {"id": "art-2", "title_a": "T2", "title_b": "T2b", "content": "C2", "meta_desc": ""},
        ]
        mock_publisher = MagicMock()
        mock_publisher.create_post.return_value = {"id": 10, "link": "https://example.com/post"}
        mock_wp_class.return_value = mock_publisher

        with patch("system.publish_engine.wordpress_publisher.db.update"), \
             patch("system.publish_engine.wordpress_publisher.db.insert"):
            published = batch_publish()

        assert len(published) == 2


class TestMediumPublisher:
    @patch("system.publish_engine.medium_publisher.requests.get")
    def test_get_user_id(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": {"id": "medium-user-123"}}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        from system.publish_engine.medium_publisher import MediumPublisher
        publisher = MediumPublisher(integration_token="test-token")
        user_id = publisher.get_user_id()
        assert user_id == "medium-user-123"

    @patch("system.publish_engine.medium_publisher.requests.post")
    @patch("system.publish_engine.medium_publisher.requests.get")
    def test_create_post_success(self, mock_get, mock_post):
        mock_get_resp = MagicMock()
        mock_get_resp.json.return_value = {"data": {"id": "user-123"}}
        mock_get_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_get_resp

        mock_post_resp = MagicMock()
        mock_post_resp.json.return_value = {"data": {"url": "https://medium.com/@user/article"}}
        mock_post_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_post_resp

        from system.publish_engine.medium_publisher import MediumPublisher
        publisher = MediumPublisher(integration_token="test-token")
        result = publisher.create_post("Title", "<p>Content</p>")
        assert result is not None
        assert "url" in result
