from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Filter,
    FilterExpression,
    Metric,
    RunReportRequest,
)
from google.oauth2 import service_account

from system.config.settings import settings
from system.db import client as db

logger = logging.getLogger(__name__)

_ga_client: Optional[BetaAnalyticsDataClient] = None


def _get_client() -> BetaAnalyticsDataClient:
    global _ga_client
    if _ga_client is None:
        _ga_client = BetaAnalyticsDataClient()
    return _ga_client


def fetch_article_pageviews(
    article_url: str,
    report_date: Optional[date] = None,
) -> Optional[int]:
    """Fetch pageview count for a specific article URL on a given date."""
    if report_date is None:
        report_date = date.today() - timedelta(days=1)

    date_str = report_date.isoformat()

    try:
        client = _get_client()
        request = RunReportRequest(
            property=f"properties/{settings.GA_PROPERTY_ID}",
            date_ranges=[DateRange(start_date=date_str, end_date=date_str)],
            metrics=[Metric(name="screenPageViews")],
            dimensions=[Dimension(name="pagePath")],
            dimension_filter=FilterExpression(
                filter=Filter(
                    field_name="pagePath",
                    string_filter=Filter.StringFilter(
                        match_type=Filter.StringFilter.MatchType.CONTAINS,
                        value=article_url.split("/")[-1] or article_url,
                    ),
                )
            ),
        )
        response = client.run_report(request)
        total_pv = 0
        for row in response.rows:
            total_pv += int(row.metric_values[0].value)
        return total_pv
    except Exception as exc:
        logger.error("GA fetch failed for url=%s date=%s: %s", article_url, date_str, exc)
        return None


def get_previous_day_pv(article_id: str, report_date: date) -> Optional[int]:
    """Return the PV from the previous day's DB record as fallback."""
    prev_date = (report_date - timedelta(days=1)).isoformat()
    rows = db.select_raw(
        "performance",
        filters={"article_id": article_id},
        columns="pv",
        gte={"date": prev_date},
        lte={"date": prev_date},
    )
    if rows and rows[0].get("pv") is not None:
        return rows[0]["pv"]
    return None


def fetch_and_store_daily_pageviews(report_date: Optional[date] = None) -> int:
    """
    Fetch pageviews for all published articles and store in performance table.
    On failure for a specific article, use previous day's data and send Telegram alert.
    Returns count of records stored.
    """
    from system.orchestrator.telegram_notifier import send_alert

    if report_date is None:
        report_date = date.today() - timedelta(days=1)

    publications = db.select("publications", filters={"platform": "wordpress", "status": "published"})
    stored_count = 0

    for pub in publications:
        article_id = pub["article_id"]
        post_url = pub.get("url", "")

        pv = fetch_article_pageviews(post_url, report_date)

        if pv is None:
            pv = get_previous_day_pv(article_id, report_date)
            if pv is not None:
                logger.warning(
                    "GA fetch failed for article %s, using previous day PV=%d", article_id, pv
                )
                send_alert(
                    f"GA fetch failed for article {article_id}. Using previous day PV={pv}."
                )
            else:
                logger.warning("No fallback PV data for article %s, skipping", article_id)
                continue

        db.upsert(
            "performance",
            {
                "article_id": article_id,
                "date": report_date.isoformat(),
                "pv": pv,
            },
            on_conflict="article_id,date",
        )
        stored_count += 1

    logger.info("Stored pageviews for %d articles on %s", stored_count, report_date)
    return stored_count
