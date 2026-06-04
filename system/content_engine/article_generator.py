from __future__ import annotations

import json
import logging
import time
from typing import Optional

import anthropic

from system.config.settings import settings
from system.content_engine.affiliate_linker import insert_affiliate_links
from system.db import client as db

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 5.0

_anthropic_client: Optional[anthropic.Anthropic] = None


def _get_client() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=settings.CLAUDE_API_KEY)
    return _anthropic_client


def _call_claude(prompt: str, system: str = "") -> str:
    client = _get_client()
    messages = [{"role": "user", "content": prompt}]
    kwargs: dict = {
        "model": settings.CLAUDE_MODEL,
        "max_tokens": 4096,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(**kwargs)
            return response.content[0].text
        except anthropic.RateLimitError as exc:
            wait = RETRY_DELAY * attempt
            logger.warning("Rate limit on attempt %d/%d, waiting %.1fs: %s", attempt, MAX_RETRIES, wait, exc)
            time.sleep(wait)
        except anthropic.APIStatusError as exc:
            if attempt == MAX_RETRIES:
                raise
            logger.warning("API error on attempt %d/%d: %s", attempt, MAX_RETRIES, exc)
            time.sleep(RETRY_DELAY)
        except Exception as exc:
            if attempt == MAX_RETRIES:
                raise
            logger.warning("Unexpected error on attempt %d/%d: %s", attempt, MAX_RETRIES, exc)
            time.sleep(RETRY_DELAY)

    raise RuntimeError("Claude API call failed after all retries")


def _generate_outline(keyword: str, language: str) -> str:
    prompt = (
        f"Create a detailed article outline for the keyword: '{keyword}'\n"
        f"Language: {language}\n"
        f"Include: title options (A and B for A/B testing), introduction hook, "
        f"5-7 main sections with subsections, conclusion, and meta description.\n"
        f"Format as structured JSON with keys: title_a, title_b, sections (list), meta_desc_draft"
    )
    system = (
        "You are an expert SEO content strategist. "
        "Always respond with valid JSON only, no markdown code fences."
    )
    return _call_claude(prompt, system)


def _generate_full_article(keyword: str, language: str, outline_json: str) -> str:
    prompt = (
        f"Write a comprehensive, SEO-optimized article based on this outline:\n\n"
        f"{outline_json}\n\n"
        f"Keyword: '{keyword}'\n"
        f"Language: {language}\n"
        f"Requirements:\n"
        f"- 1500-2500 words\n"
        f"- Use HTML formatting (h2, h3, p, ul, ol, strong)\n"
        f"- Include the keyword naturally throughout\n"
        f"- Write engaging, helpful content for readers\n"
        f"- Do NOT include the title in the body (it will be added separately)\n"
        f"Return only the HTML article body content."
    )
    system = "You are an expert content writer producing high-quality SEO articles."
    return _call_claude(prompt, system)


def _generate_meta_info(keyword: str, language: str, content: str) -> dict:
    prompt = (
        f"Based on this article about '{keyword}' in {language}, generate:\n"
        f"1. A compelling meta description (120-160 characters)\n"
        f"2. Confirm or improve the A/B title options\n\n"
        f"Article preview: {content[:500]}\n\n"
        f"Respond as JSON with keys: meta_desc, title_a, title_b"
    )
    system = "You are an SEO expert. Respond with valid JSON only, no markdown code fences."
    raw = _call_claude(prompt, system)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        import re
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {"meta_desc": "", "title_a": keyword, "title_b": keyword}


def generate_article(keyword_row: dict) -> Optional[dict]:
    """
    Generate a full article for a keyword row.
    Returns the inserted article row or None on failure.
    """
    keyword = keyword_row["keyword"]
    language = keyword_row["language"]
    keyword_id = keyword_row["id"]
    genre = keyword_row.get("genre")

    logger.info("Generating article for keyword='%s' lang=%s", keyword, language)

    try:
        outline_raw = _generate_outline(keyword, language)
        try:
            outline_data = json.loads(outline_raw)
        except json.JSONDecodeError:
            import re
            match = re.search(r"\{.*\}", outline_raw, re.DOTALL)
            outline_data = json.loads(match.group()) if match else {}

        content = _generate_full_article(keyword, language, outline_raw)

        content, affiliate_links = insert_affiliate_links(content, keyword, genre, language)

        meta_info = _generate_meta_info(keyword, language, content)

        title_a = outline_data.get("title_a") or meta_info.get("title_a") or keyword
        title_b = outline_data.get("title_b") or meta_info.get("title_b") or keyword
        meta_desc = meta_info.get("meta_desc") or outline_data.get("meta_desc_draft") or ""

        article_row = db.insert(
            "articles",
            {
                "keyword_id": keyword_id,
                "language": language,
                "title_a": title_a,
                "title_b": title_b,
                "content": content,
                "meta_desc": meta_desc,
                "affiliate_links": json.dumps(affiliate_links),
                "status": "draft",
            },
        )

        db.update("keywords", {"id": keyword_id}, {"status": "processed"})

        logger.info("Article generated id=%s for keyword='%s'", article_row.get("id"), keyword)
        return article_row

    except Exception as exc:
        logger.error("Failed to generate article for keyword='%s': %s", keyword, exc)
        db.update("keywords", {"id": keyword_id}, {"status": "error"})
        return None


def run_content_engine(limit: int = 5) -> list[dict]:
    """Fetch top pending keywords and generate articles."""
    from system.research_engine.keyword_fetcher import get_top_keywords

    results: list[dict] = []
    for language in settings.SUPPORTED_LANGUAGES:
        keywords = get_top_keywords(language, limit=limit)
        for kw_row in keywords:
            article = generate_article(kw_row)
            if article:
                results.append(article)
    return results
