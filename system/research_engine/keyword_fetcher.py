from __future__ import annotations

import logging
import time
from typing import Optional

from pytrends.request import TrendReq

from system.db import client as db
from system.research_engine.scorer import safe_score

logger = logging.getLogger(__name__)

LANGUAGE_TO_GEO: dict[str, str] = {
    "en": "US",
    "ja": "JP",
    "es": "ES",
    "pt": "BR",
}

LANGUAGE_TO_HL: dict[str, str] = {
    "en": "en-US",
    "ja": "ja-JP",
    "es": "es-ES",
    "pt": "pt-BR",
}

GENRE_SEED_KEYWORDS: dict[str, list[str]] = {
    "technology": ["AI tools", "software review", "tech gadgets", "programming tutorial"],
    "finance": ["personal finance", "investment tips", "crypto trading", "stock market"],
    "health": ["fitness workout", "diet plan", "mental health", "supplements review"],
    "lifestyle": ["home decor", "travel tips", "fashion trends", "cooking recipes"],
}


def _build_pytrends(language: str) -> TrendReq:
    hl = LANGUAGE_TO_HL.get(language, "en-US")
    return TrendReq(hl=hl, tz=0, timeout=(10, 25))


def _fetch_trending_for_genre(
    pytrends: TrendReq,
    seed_keywords: list[str],
    geo: str,
) -> list[str]:
    try:
        pytrends.build_payload(seed_keywords[:5], geo=geo, timeframe="now 7-d")
        related = pytrends.related_queries()
        keywords: list[str] = []
        for kw_data in related.values():
            if kw_data and kw_data.get("top") is not None:
                df = kw_data["top"]
                if df is not None and not df.empty:
                    keywords.extend(df["query"].tolist()[:10])
        return list(set(keywords))
    except Exception as exc:
        logger.warning("Failed to fetch trending keywords: %s", exc)
        return seed_keywords


def _get_keyword_metrics(
    keyword: str,
    language: str,
) -> dict[str, Optional[float]]:
    """Return estimated search_volume, cpc, competition from pytrends interest data."""
    try:
        pytrends = _build_pytrends(language)
        geo = LANGUAGE_TO_GEO.get(language, "US")
        pytrends.build_payload([keyword], geo=geo, timeframe="today 12-m")
        interest_df = pytrends.interest_over_time()
        if interest_df.empty or keyword not in interest_df.columns:
            volume = 100
        else:
            volume = int(interest_df[keyword].mean() * 100)

        # pytrends does not provide CPC/competition; use neutral defaults unless
        # Google Ads API is configured.
        cpc = 0.5
        competition = 0.5
        return {"search_volume": volume, "cpc": cpc, "competition": competition}
    except Exception as exc:
        logger.warning("Failed to get metrics for '%s': %s", keyword, exc)
        return {"search_volume": None, "cpc": None, "competition": None}


def fetch_and_store_keywords(languages: Optional[list[str]] = None) -> list[dict]:
    if languages is None:
        languages = ["en", "ja", "es", "pt"]

    stored: list[dict] = []
    for language in languages:
        geo = LANGUAGE_TO_GEO.get(language, "US")
        pytrends = _build_pytrends(language)

        for genre, seeds in GENRE_SEED_KEYWORDS.items():
            keywords = _fetch_trending_for_genre(pytrends, seeds, geo)
            time.sleep(1)

            for keyword in keywords[:20]:
                metrics = _get_keyword_metrics(keyword, language)
                score = safe_score(
                    keyword=keyword,
                    language=language,
                    search_volume=metrics.get("search_volume"),
                    cpc=metrics.get("cpc"),
                    competition=metrics.get("competition"),
                )
                row = db.insert(
                    "keywords",
                    {
                        "keyword": keyword,
                        "language": language,
                        "search_volume": metrics.get("search_volume"),
                        "cpc": metrics.get("cpc"),
                        "competition": metrics.get("competition"),
                        "score": score,
                        "genre": genre,
                        "status": "pending",
                    },
                )
                stored.append(row)
                logger.info("Stored keyword '%s' (%s) score=%.2f", keyword, language, score or 0)
                time.sleep(0.5)

    return stored


def get_top_keywords(language: str, limit: int = 5) -> list[dict]:
    return db.select_raw(
        "keywords",
        filters={"language": language, "status": "pending"},
        columns="*",
        limit=limit,
        order_by="score",
        order_desc=True,
    )
