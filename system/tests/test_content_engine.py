from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch, call

from system.content_engine.affiliate_linker import (
    insert_affiliate_links,
    _build_amazon_link,
    _build_shareasale_link,
    _find_keyword_positions,
)


class TestAffiliateLinker:
    def test_build_amazon_link(self):
        url = _build_amazon_link("laptop stand", "mysite-20")
        assert "amazon.com" in url
        assert "mysite-20" in url
        assert "laptop+stand" in url

    def test_build_shareasale_link(self):
        url = _build_shareasale_link("123456", "https://example.com", "789")
        assert "shareasale.com" in url
        assert "123456" in url
        assert "789" in url

    def test_find_keyword_positions(self):
        positions = _find_keyword_positions("I have a laptop and another laptop here", "laptop")
        assert len(positions) == 2

    def test_find_keyword_positions_case_insensitive(self):
        positions = _find_keyword_positions("Laptop or LAPTOP", "laptop")
        assert len(positions) == 2

    @patch("system.content_engine.affiliate_linker.settings")
    def test_insert_affiliate_links_with_matching_term(self, mock_settings):
        mock_settings.AMAZON_AFFILIATE_TAG = "test-20"
        mock_settings.SHAREASALE_AFFILIATE_ID = ""
        content = "This article reviews the best laptop for developers."
        result_content, links = insert_affiliate_links(content, "laptop review", "technology", "en")
        assert any(l["type"] == "amazon" for l in links)
        assert '<a href=' in result_content

    @patch("system.content_engine.affiliate_linker.settings")
    def test_no_links_when_no_tag_configured(self, mock_settings):
        mock_settings.AMAZON_AFFILIATE_TAG = ""
        mock_settings.SHAREASALE_AFFILIATE_ID = ""
        content = "This article reviews the best laptop."
        result_content, links = insert_affiliate_links(content, "laptop", "technology", "en")
        assert len(links) == 0

    @patch("system.content_engine.affiliate_linker.settings")
    def test_no_links_when_genre_is_none(self, mock_settings):
        mock_settings.AMAZON_AFFILIATE_TAG = "test-20"
        content = "Some content about laptops"
        result_content, links = insert_affiliate_links(content, "keyword", None, "en")
        assert result_content == content
        assert len(links) == 0

    @patch("system.content_engine.affiliate_linker.settings")
    def test_max_5_links_inserted(self, mock_settings):
        mock_settings.AMAZON_AFFILIATE_TAG = "test-20"
        mock_settings.SHAREASALE_AFFILIATE_ID = ""
        content = "laptop phone tablet headphone keyboard monitor webcam"
        _, links = insert_affiliate_links(content, "tech", "technology", "en")
        assert len(links) <= 5


class TestArticleGenerator:
    MOCK_OUTLINE = json.dumps({
        "title_a": "Best Laptops for 2025",
        "title_b": "Top Laptops to Buy in 2025",
        "sections": ["Introduction", "Best Budget Picks", "Conclusion"],
        "meta_desc_draft": "Discover the best laptops for 2025.",
    })

    MOCK_META = json.dumps({
        "meta_desc": "Discover the best laptops for 2025 in our comprehensive guide.",
        "title_a": "Best Laptops for 2025",
        "title_b": "Top 10 Laptops in 2025",
    })

    @patch("system.content_engine.article_generator.db.update")
    @patch("system.content_engine.article_generator.db.insert")
    @patch("system.content_engine.article_generator.insert_affiliate_links")
    @patch("system.content_engine.article_generator._call_claude")
    def test_generate_article_success(self, mock_claude, mock_affiliate, mock_insert, mock_update):
        mock_claude.side_effect = [
            self.MOCK_OUTLINE,
            "<p>Full article content about laptops.</p>",
            self.MOCK_META,
        ]
        mock_affiliate.return_value = ("<p>Full article content about laptops.</p>", [])
        mock_insert.return_value = {
            "id": "article-uuid",
            "keyword_id": "kw-uuid",
            "language": "en",
        }

        from system.content_engine.article_generator import generate_article
        keyword_row = {
            "id": "kw-uuid",
            "keyword": "best laptops",
            "language": "en",
            "genre": "technology",
        }
        result = generate_article(keyword_row)

        assert result is not None
        assert result["id"] == "article-uuid"
        mock_insert.assert_called_once()
        insert_data = mock_insert.call_args[0][1]
        assert insert_data["language"] == "en"
        assert insert_data["keyword_id"] == "kw-uuid"

    @patch("system.content_engine.article_generator.db.update")
    @patch("system.content_engine.article_generator._call_claude")
    def test_generate_article_claude_failure(self, mock_claude, mock_update):
        mock_claude.side_effect = RuntimeError("Claude API unavailable")

        from system.content_engine.article_generator import generate_article
        keyword_row = {
            "id": "kw-uuid",
            "keyword": "best laptops",
            "language": "en",
            "genre": "technology",
        }
        result = generate_article(keyword_row)

        assert result is None
        mock_update.assert_called_once_with("keywords", {"id": "kw-uuid"}, {"status": "error"})

    @patch("system.content_engine.article_generator._call_claude")
    def test_call_claude_retries_on_rate_limit(self, mock_claude):
        import anthropic as ant
        mock_claude.side_effect = ant.RateLimitError.__new__(ant.RateLimitError)

        with patch("system.content_engine.article_generator.time.sleep"):
            from system.content_engine.article_generator import _call_claude
            with pytest.raises(Exception):
                _call_claude("test prompt")


class TestTranslator:
    @patch("system.content_engine.translator._get_translator")
    def test_translate_text_success(self, mock_get_translator):
        mock_translator = MagicMock()
        mock_result = MagicMock()
        mock_result.text = "翻訳されたテキスト"
        mock_translator.translate_text.return_value = mock_result
        mock_get_translator.return_value = mock_translator

        from system.content_engine.translator import translate_text
        result = translate_text("Hello world", "ja")
        assert result == "翻訳されたテキスト"

    @patch("system.content_engine.translator._get_translator")
    def test_translate_text_returns_none_on_failure(self, mock_get_translator):
        import deepl
        mock_translator = MagicMock()
        mock_translator.translate_text.side_effect = deepl.DeepLException("API error")
        mock_get_translator.return_value = mock_translator

        from system.content_engine.translator import translate_text
        result = translate_text("Hello", "ja")
        assert result is None

    def test_translate_unsupported_language(self):
        from system.content_engine.translator import translate_text
        result = translate_text("Hello", "zh")
        assert result is None

    @patch("system.content_engine.translator.db.update")
    @patch("system.content_engine.translator.translate_text")
    def test_translate_article_publish_english_on_failure(self, mock_translate, mock_update):
        mock_translate.return_value = None

        from system.content_engine.translator import translate_article
        article_row = {
            "id": "art-uuid",
            "keyword_id": "kw-uuid",
            "content": "English content",
            "title_a": "Title A",
            "title_b": "Title B",
            "meta_desc": "Description",
            "language": "en",
            "affiliate_links": "[]",
        }
        result = translate_article(article_row, "ja")
        assert result is None
        mock_update.assert_called_once_with(
            "articles", {"id": "art-uuid"}, {"status": "translation_retry"}
        )
