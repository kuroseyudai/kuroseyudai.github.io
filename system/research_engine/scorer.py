from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from system.db import client as db

logger = logging.getLogger(__name__)

GENRE_RECOMMENDATION_SCALE_UP = "scale_up"
GENRE_RECOMMENDATION_HOLD = "hold"
GENRE_RECOMMENDATION_SCALE_DOWN = "scale_down"

ROI_SCALE_UP = 50.0
ROI_HOLD = 10.0


def calculate_score(
    search_volume: Optional[int],
    cpc: Optional[float],
    competition: Optional[float],
) -> Optional[float]:
    if search_volume is None or cpc is None or competition is None:
        return None
    if competition <= 0:
        return None
    return search_volume * cpc * (1.0 / competition)


def is_score_anomaly(score: float, keyword: str, language: str) -> bool:
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    rows = db.select_raw(
        "keywords",
        filters={"keyword": keyword, "language": language},
        columns="score",
        gte={"created_at": week_ago},
    )
    scores = [r["score"] for r in rows if r.get("score") is not None]
    if len(scores) < 3:
        return False
    avg = sum(scores) / len(scores)
    if avg == 0:
        return False
    deviation = abs(score - avg) / avg
    return deviation > 2.0


def get_prev_week_avg_score(keyword: str, language: str) -> Optional[float]:
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    two_weeks_ago = (date.today() - timedelta(days=14)).isoformat()
    rows = db.select_raw(
        "keywords",
        filters={"keyword": keyword, "language": language},
        columns="score",
        gte={"created_at": two_weeks_ago},
        lte={"created_at": week_ago},
    )
    scores = [r["score"] for r in rows if r.get("score") is not None]
    if not scores:
        return None
    return sum(scores) / len(scores)


def safe_score(
    keyword: str,
    language: str,
    search_volume: Optional[int],
    cpc: Optional[float],
    competition: Optional[float],
) -> Optional[float]:
    score = calculate_score(search_volume, cpc, competition)
    if score is None:
        return None
    if is_score_anomaly(score, keyword, language):
        fallback = get_prev_week_avg_score(keyword, language)
        if fallback is not None:
            logger.warning(
                "Score anomaly detected for '%s' (%s). Using previous week avg: %.2f",
                keyword, language, fallback,
            )
            return fallback
    return score


def get_genre_roi_recommendation(genre: str) -> str:
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    articles = db.select("articles", columns="id")
    if not articles:
        return GENRE_RECOMMENDATION_HOLD

    article_ids = [a["id"] for a in articles]
    genre_keywords = db.select_raw(
        "keywords",
        filters={"genre": genre},
        columns="id",
    )
    if not genre_keywords:
        return GENRE_RECOMMENDATION_HOLD

    keyword_ids = {k["id"] for k in genre_keywords}
    genre_articles = db.select_raw(
        "articles",
        columns="id,keyword_id",
    )
    genre_article_ids = [
        a["id"] for a in genre_articles if a.get("keyword_id") in keyword_ids
    ]

    if not genre_article_ids:
        return GENRE_RECOMMENDATION_HOLD

    all_roi: list[float] = []
    for article_id in genre_article_ids:
        rows = db.select_raw(
            "performance",
            filters={"article_id": article_id},
            columns="roi",
            gte={"date": week_ago},
        )
        rois = [r["roi"] for r in rows if r.get("roi") is not None]
        all_roi.extend(rois)

    if not all_roi:
        return GENRE_RECOMMENDATION_HOLD

    avg_roi = sum(all_roi) / len(all_roi)

    if avg_roi > ROI_SCALE_UP:
        return GENRE_RECOMMENDATION_SCALE_UP
    elif avg_roi >= ROI_HOLD:
        return GENRE_RECOMMENDATION_HOLD
    else:
        return GENRE_RECOMMENDATION_SCALE_DOWN


def aggregate_genre_roi() -> dict[str, dict[str, float | str]]:
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    genres_rows = db.select_raw("keywords", columns="genre")
    genres = {r["genre"] for r in genres_rows if r.get("genre")}

    results: dict[str, dict[str, float | str]] = {}
    for genre in genres:
        recommendation = get_genre_roi_recommendation(genre)
        results[genre] = {"recommendation": recommendation}

    return results
