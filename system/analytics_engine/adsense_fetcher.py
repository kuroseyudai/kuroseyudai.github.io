from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials

from system.config.settings import settings
from system.db import client as db

logger = logging.getLogger(__name__)

ADSENSE_SCOPES = ["https://www.googleapis.com/auth/adsense.readonly"]


def _build_adsense_service():
    """Build AdSense reporting service using application default credentials."""
    return build("adsense", "v2", cache_discovery=False)


def fetch_daily_revenue(report_date: Optional[date] = None) -> Optional[float]:
    """
    Fetch total AdSense revenue for the given date.
    Returns None on failure so the caller can use a fallback.
    """
    if not settings.ADSENSE_PUBLISHER_ID:
        logger.info("AdSense publisher ID not configured")
        return None

    if report_date is None:
        report_date = date.today() - timedelta(days=1)

    date_str = report_date.isoformat()

    try:
        service = _build_adsense_service()
        account_name = f"accounts/{settings.ADSENSE_PUBLISHER_ID}"
        report_body = {
            "startDate": {"year": report_date.year, "month": report_date.month, "day": report_date.day},
            "endDate": {"year": report_date.year, "month": report_date.month, "day": report_date.day},
            "metrics": ["ESTIMATED_EARNINGS"],
        }
        response = (
            service.accounts()
            .reports()
            .generate(account=account_name, **report_body)
            .execute()
        )
        rows = response.get("rows", [])
        if rows:
            return float(rows[0]["cells"][0].get("value", 0))
        return 0.0
    except HttpError as exc:
        logger.error("AdSense API error for date=%s: %s", date_str, exc)
        return None
    except Exception as exc:
        logger.error("Unexpected AdSense error for date=%s: %s", date_str, exc)
        return None


def distribute_revenue_to_articles(
    total_revenue: float,
    report_date: date,
) -> None:
    """
    Distribute total AdSense revenue proportionally across articles by pageview share.
    Updates performance records in DB.
    """
    date_str = report_date.isoformat()
    perf_rows = db.select_raw(
        "performance",
        columns="article_id,pv",
        gte={"date": date_str},
        lte={"date": date_str},
    )

    total_pv = sum(r.get("pv") or 0 for r in perf_rows)
    if total_pv == 0:
        return

    for row in perf_rows:
        pv = row.get("pv") or 0
        if pv == 0:
            continue
        article_revenue = total_revenue * (pv / total_pv)
        db.update(
            "performance",
            {"article_id": row["article_id"], "date": date_str},
            {"revenue_ad": round(article_revenue, 6)},
        )


def store_daily_adsense(report_date: Optional[date] = None) -> bool:
    """Fetch AdSense revenue and distribute to articles. Returns True on success."""
    if report_date is None:
        report_date = date.today() - timedelta(days=1)

    revenue = fetch_daily_revenue(report_date)
    if revenue is None:
        logger.warning("Could not fetch AdSense revenue for %s", report_date)
        return False

    distribute_revenue_to_articles(revenue, report_date)
    logger.info("Distributed AdSense revenue %.4f for %s", revenue, report_date)
    return True
