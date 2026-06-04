from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import requests

from system.config.settings import settings

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


def _send_message(text: str, chat_id: Optional[str] = None) -> bool:
    token = settings.TELEGRAM_BOT_TOKEN
    target_chat = chat_id or settings.TELEGRAM_CHAT_ID

    if not token or not target_chat:
        logger.warning("Telegram not configured, skipping notification")
        return False

    try:
        resp = requests.post(
            f"{TELEGRAM_API_BASE}/bot{token}/sendMessage",
            json={
                "chat_id": target_chat,
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        logger.error("Telegram send failed: %s", exc)
        return False


def send_alert(message: str) -> bool:
    """Send an error or warning alert via Telegram."""
    text = f"<b>ALERT</b>\n{message}"
    return _send_message(text)


def send_daily_summary(
    articles_generated: int,
    articles_published: int,
    total_revenue: float,
    total_pv: int,
) -> bool:
    text = (
        f"<b>Daily Summary - {date.today().isoformat()}</b>\n"
        f"Articles generated: {articles_generated}\n"
        f"Articles published: {articles_published}\n"
        f"Total PV: {total_pv:,}\n"
        f"Total Revenue: ${total_revenue:.2f}"
    )
    return _send_message(text)


def send_weekly_roi_report(genre_results: dict[str, dict]) -> bool:
    lines = [f"<b>Weekly ROI Report - {date.today().isoformat()}</b>"]
    for genre, data in genre_results.items():
        avg_roi = data.get("avg_roi")
        recommendation = data.get("recommendation", "hold")
        roi_str = f"{avg_roi:.1f}%" if avg_roi is not None else "N/A"
        lines.append(f"  {genre}: ROI={roi_str} → {recommendation.upper()}")
    return _send_message("\n".join(lines))


def send_job_failure(job_name: str, error: str) -> bool:
    text = (
        f"<b>JOB FAILURE</b>\n"
        f"Job: {job_name}\n"
        f"Error: {error}"
    )
    return _send_message(text)
