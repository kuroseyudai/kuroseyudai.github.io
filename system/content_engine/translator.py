from __future__ import annotations

import logging
from typing import Optional

import deepl

from system.config.settings import settings
from system.db import client as db

logger = logging.getLogger(__name__)

DEEPL_LANGUAGE_MAP: dict[str, str] = {
    "ja": "JA",
    "es": "ES",
    "pt": "PT-BR",
}

_deepl_client: Optional[deepl.Translator] = None


def _get_translator() -> deepl.Translator:
    global _deepl_client
    if _deepl_client is None:
        _deepl_client = deepl.Translator(settings.DEEPL_API_KEY)
    return _deepl_client


def translate_text(text: str, target_language: str) -> Optional[str]:
    """Translate text to target_language using DeepL. Returns None on failure."""
    deepl_lang = DEEPL_LANGUAGE_MAP.get(target_language)
    if not deepl_lang:
        logger.warning("Unsupported translation target: %s", target_language)
        return None

    try:
        translator = _get_translator()
        result = translator.translate_text(text, target_lang=deepl_lang)
        return result.text
    except deepl.DeepLException as exc:
        logger.error("DeepL translation failed for lang=%s: %s", target_language, exc)
        return None
    except Exception as exc:
        logger.error("Unexpected translation error for lang=%s: %s", target_language, exc)
        return None


def translate_article(article_row: dict, target_language: str) -> Optional[dict]:
    """
    Translate an English article to target_language.
    On failure, logs the error and returns None so the caller can publish English only.
    The original article is marked for translation retry next day.
    """
    article_id = article_row["id"]
    content_en = article_row.get("content", "")
    title_a_en = article_row.get("title_a", "")
    title_b_en = article_row.get("title_b", "")
    meta_desc_en = article_row.get("meta_desc", "")

    logger.info("Translating article %s to %s", article_id, target_language)

    content_translated = translate_text(content_en, target_language)
    if content_translated is None:
        logger.warning(
            "Content translation failed for article %s → %s. Will publish English only.",
            article_id, target_language,
        )
        db.update("articles", {"id": article_id}, {"status": "translation_retry"})
        return None

    title_a_translated = translate_text(title_a_en, target_language) or title_a_en
    title_b_translated = translate_text(title_b_en, target_language) or title_b_en
    meta_desc_translated = translate_text(meta_desc_en, target_language) or meta_desc_en

    from system.db import client as db_client
    translated_row = db_client.insert(
        "articles",
        {
            "keyword_id": article_row.get("keyword_id"),
            "language": target_language,
            "title_a": title_a_translated,
            "title_b": title_b_translated,
            "content": content_translated,
            "meta_desc": meta_desc_translated,
            "affiliate_links": article_row.get("affiliate_links"),
            "status": "draft",
        },
    )

    logger.info(
        "Translated article created id=%s lang=%s", translated_row.get("id"), target_language
    )
    return translated_row


def translate_pending_articles() -> list[dict]:
    """Find English draft articles and translate to all other supported languages."""
    english_articles = db.select("articles", filters={"language": "en", "status": "draft"})
    results: list[dict] = []

    for article in english_articles:
        for lang in ["ja", "es", "pt"]:
            translated = translate_article(article, lang)
            if translated:
                results.append(translated)

    return results


def retry_failed_translations() -> list[dict]:
    """Retry articles that previously failed translation."""
    retry_articles = db.select("articles", filters={"status": "translation_retry"})
    results: list[dict] = []

    for article in retry_articles:
        lang = article.get("language")
        if lang == "en":
            for target_lang in ["ja", "es", "pt"]:
                translated = translate_article(article, target_lang)
                if translated:
                    db.update("articles", {"id": article["id"]}, {"status": "draft"})
                    results.append(translated)
        else:
            translated = translate_article(article, lang)
            if translated:
                results.append(translated)

    return results
