from __future__ import annotations

import re
from typing import Optional

from system.config.settings import settings

AMAZON_PRODUCT_CATEGORIES: dict[str, list[str]] = {
    "technology": ["laptop", "phone", "tablet", "headphone", "keyboard", "mouse", "monitor", "webcam"],
    "health": ["supplement", "protein", "vitamin", "fitness", "yoga", "dumbbell", "treadmill"],
    "lifestyle": ["coffee", "book", "backpack", "camera", "tripod", "planner"],
    "finance": ["book", "calculator", "journal"],
}

SHAREASALE_MERCHANT_IDS: dict[str, str] = {
    "technology": "123456",
    "health": "789012",
    "lifestyle": "345678",
    "finance": "901234",
}


def _build_amazon_link(search_term: str, affiliate_tag: str) -> str:
    encoded = search_term.replace(" ", "+")
    return f"https://www.amazon.com/s?k={encoded}&tag={affiliate_tag}"


def _build_shareasale_link(merchant_id: str, url: str, affiliate_id: str) -> str:
    return (
        f"https://www.shareasale.com/r.cfm"
        f"?b=1&u={affiliate_id}&m={merchant_id}&urllink={url}&afftrack="
    )


def _find_keyword_positions(content: str, keyword: str) -> list[int]:
    pattern = re.compile(re.escape(keyword), re.IGNORECASE)
    return [m.start() for m in pattern.finditer(content)]


def insert_affiliate_links(
    content: str,
    keyword: str,
    genre: Optional[str],
    language: str = "en",
) -> tuple[str, list[dict]]:
    """
    Insert affiliate links into content around matched product keywords.
    Returns modified content and a list of link metadata dicts.
    """
    affiliate_tag = settings.AMAZON_AFFILIATE_TAG
    shareasale_id = settings.SHAREASALE_AFFILIATE_ID
    inserted_links: list[dict] = []

    if not genre:
        return content, inserted_links

    product_terms = AMAZON_PRODUCT_CATEGORIES.get(genre, [])

    for term in product_terms:
        positions = _find_keyword_positions(content, term)
        if not positions:
            continue

        if affiliate_tag:
            amazon_url = _build_amazon_link(term, affiliate_tag)
            link_html = f'<a href="{amazon_url}" target="_blank" rel="nofollow">{term}</a>'
            pattern = re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE)
            new_content, n = pattern.subn(link_html, content, count=1)
            if n > 0:
                content = new_content
                inserted_links.append({"type": "amazon", "term": term, "url": amazon_url})

        merchant_id = SHAREASALE_MERCHANT_IDS.get(genre, "")
        if shareasale_id and merchant_id:
            base_url = f"https://www.amazon.com/s?k={term.replace(' ', '+')}"
            ssa_url = _build_shareasale_link(merchant_id, base_url, shareasale_id)
            inserted_links.append({"type": "shareasale", "term": term, "url": ssa_url})

        if len(inserted_links) >= 5:
            break

    return content, inserted_links
