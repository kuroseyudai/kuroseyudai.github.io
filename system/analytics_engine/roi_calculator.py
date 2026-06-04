from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from system.db import client as db

logger = logging.getLogger(__name__)

GENRE_SCALE_UP_ROI = 50.0
GENRE_HOLD_ROI = 10.0

API_COST_PER_ARTICLE = 0.15


def calculate_article_roi(
    total_revenue: float,
    api_cost: float,
) -> Optional[float]:
    """ROI = (revenue - cost) / cost * 100 as percentage."""
    if api_cost <= 0:
        return None
    return ((total_revenue - api_cost) / api_cost) * 100.0


def update_performance_roi(report_date: Optional[date] = None) -> int:
    """Calculate and store ROI for all performance records on given date."""
    if report_date is None:
        report_date = date.today() - timedelta(days=1)

    date_str = report_date.isoformat()
    rows = db.select_raw(
        "performance",
        columns="article_id,revenue_ad,revenue_aff,api_cost,date",
        gte={"date": date_str},
        lte={"date": date_str},
    )

    updated = 0
    for row in rows:
        revenue_ad = float(row.get("revenue_ad") or 0)
        revenue_aff = float(row.get("revenue_aff") or 0)
        api_cost = float(row.get("api_cost") or API_COST_PER_ARTICLE)
        total_revenue = revenue_ad + revenue_aff

        roi = calculate_article_roi(total_revenue, api_cost)

        db.update(
            "performance",
            {"article_id": row["article_id"], "date": date_str},
            {
                "total_revenue": total_revenue,
                "api_cost": api_cost,
                "roi": roi,
            },
        )
        updated += 1

    logger.info("Updated ROI for %d performance records on %s", updated, date_str)
    return updated


def get_genre_avg_roi(genre: str, days: int = 7) -> Optional[float]:
    """Calculate average ROI across all articles in a genre over the last N days."""
    since_date = (date.today() - timedelta(days=days)).isoformat()

    genre_keywords = db.select_raw("keywords", filters={"genre": genre}, columns="id")
    if not genre_keywords:
        return None

    keyword_ids = {k["id"] for k in genre_keywords}

    genre_articles = db.select_raw("articles", columns="id,keyword_id")
    genre_article_ids = [a["id"] for a in genre_articles if a.get("keyword_id") in keyword_ids]

    if not genre_article_ids:
        return None

    all_roi: list[float] = []
    for article_id in genre_article_ids:
        rows = db.select_raw(
            "performance",
            filters={"article_id": article_id},
            columns="roi",
            gte={"date": since_date},
        )
        rois = [float(r["roi"]) for r in rows if r.get("roi") is not None]
        all_roi.extend(rois)

    if not all_roi:
        return None

    return sum(all_roi) / len(all_roi)


def get_genre_recommendation(avg_roi: Optional[float]) -> str:
    if avg_roi is None:
        return "hold"
    if avg_roi > GENRE_SCALE_UP_ROI:
        return "scale_up"
    elif avg_roi >= GENRE_HOLD_ROI:
        return "hold"
    else:
        return "scale_down"


def aggregate_weekly_genre_roi() -> dict[str, dict]:
    """
    Aggregate ROI by genre for the past week.
    Returns dict of genre -> {avg_roi, recommendation}.
    Used to feed back strategy adjustments to the Research Engine.
    """
    genres_rows = db.select_raw("keywords", columns="genre")
    genres = {r["genre"] for r in genres_rows if r.get("genre")}

    results: dict[str, dict] = {}
    for genre in genres:
        avg_roi = get_genre_avg_roi(genre, days=7)
        recommendation = get_genre_recommendation(avg_roi)
        results[genre] = {
            "avg_roi": avg_roi,
            "recommendation": recommendation,
        }
        logger.info("Genre '%s': avg_roi=%.2f recommendation=%s", genre, avg_roi or 0, recommendation)

    return results


def get_top_performing_articles(limit: int = 10, days: int = 30) -> list[dict]:
    """Return top articles by total revenue over the last N days."""
    since_date = (date.today() - timedelta(days=days)).isoformat()
    rows = db.select_raw(
        "performance",
        columns="article_id,total_revenue,roi,pv,date",
        gte={"date": since_date},
        order_by="total_revenue",
        order_desc=True,
        limit=limit,
    )
    return rows
