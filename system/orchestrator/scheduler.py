from __future__ import annotations

import logging
import signal
import sys
from datetime import date, timedelta
from typing import Optional

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, JobExecutionEvent

from system.orchestrator.telegram_notifier import (
    send_alert,
    send_daily_summary,
    send_job_failure,
    send_weekly_roi_report,
)

logger = logging.getLogger(__name__)

scheduler = BlockingScheduler(timezone="UTC")


def _job_listener(event: JobExecutionEvent) -> None:
    if event.exception:
        logger.error("Job '%s' failed: %s", event.job_id, event.exception)
        send_job_failure(event.job_id, str(event.exception))
    else:
        logger.info("Job '%s' completed successfully", event.job_id)


def job_research_engine() -> None:
    """06:00 daily - fetch and score trending keywords."""
    logger.info("Starting Research Engine job")
    from system.research_engine.keyword_fetcher import fetch_and_store_keywords
    results = fetch_and_store_keywords()
    logger.info("Research Engine stored %d keywords", len(results))


def job_content_engine() -> None:
    """07:00 daily - generate articles for top keywords."""
    logger.info("Starting Content Engine job")
    from system.content_engine.article_generator import run_content_engine
    from system.content_engine.translator import translate_pending_articles, retry_failed_translations

    from system.config.settings import settings
    articles = run_content_engine(limit=settings.ARTICLES_PER_DAY)
    logger.info("Generated %d articles", len(articles))

    translated = translate_pending_articles()
    logger.info("Translated %d additional articles", len(translated))

    retried = retry_failed_translations()
    if retried:
        logger.info("Retried %d failed translations", len(retried))


def job_publish_engine() -> None:
    """13:00 daily - batch publish drafted articles."""
    logger.info("Starting Publish Engine job")
    from system.publish_engine.wordpress_publisher import batch_publish, retry_failed_publications

    published = batch_publish()
    logger.info("Published %d articles to WordPress", len(published))

    retried = retry_failed_publications()
    if retried:
        logger.info("Retried %d failed publications", len(retried))


def job_analytics_engine() -> None:
    """00:00 daily - fetch analytics and calculate ROI."""
    logger.info("Starting Analytics Engine job")
    from system.analytics_engine.ga_fetcher import fetch_and_store_daily_pageviews
    from system.analytics_engine.adsense_fetcher import store_daily_adsense
    from system.analytics_engine.ab_tester import run_ab_tests_for_all_articles
    from system.analytics_engine.roi_calculator import update_performance_roi
    from system.db import client as db

    report_date = date.today() - timedelta(days=1)

    pv_count = fetch_and_store_daily_pageviews(report_date)
    store_daily_adsense(report_date)
    update_performance_roi(report_date)
    run_ab_tests_for_all_articles()

    date_str = report_date.isoformat()
    perf_rows = db.select_raw(
        "performance",
        columns="pv,total_revenue",
        gte={"date": date_str},
        lte={"date": date_str},
    )
    total_pv = sum(r.get("pv") or 0 for r in perf_rows)
    total_revenue = sum(float(r.get("total_revenue") or 0) for r in perf_rows)

    article_count = len(db.select("articles", filters={"status": "published"}))
    published_today = len(db.select_raw(
        "publications",
        columns="id",
        gte={"published_at": date_str},
    ))

    send_daily_summary(
        articles_generated=0,
        articles_published=published_today,
        total_revenue=total_revenue,
        total_pv=total_pv,
    )

    logger.info("Analytics job done: pv=%d revenue=%.4f", total_pv, total_revenue)


def job_weekly_roi() -> None:
    """Every Sunday - aggregate genre ROI and adjust strategy."""
    logger.info("Starting Weekly ROI aggregation job")
    from system.analytics_engine.roi_calculator import aggregate_weekly_genre_roi

    results = aggregate_weekly_genre_roi()
    send_weekly_roi_report(results)
    logger.info("Weekly ROI: %s", results)


def _handle_shutdown(signum: int, frame) -> None:
    logger.info("Received signal %d, shutting down scheduler gracefully", signum)
    scheduler.shutdown(wait=False)
    sys.exit(0)


def start() -> None:
    scheduler.add_listener(_job_listener, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)

    scheduler.add_job(job_research_engine, "cron", hour=6, minute=0, id="research_engine")
    scheduler.add_job(job_content_engine, "cron", hour=7, minute=0, id="content_engine")
    scheduler.add_job(job_publish_engine, "cron", hour=13, minute=0, id="publish_engine")
    scheduler.add_job(job_analytics_engine, "cron", hour=0, minute=0, id="analytics_engine")
    scheduler.add_job(
        job_weekly_roi,
        "cron",
        day_of_week="sun",
        hour=1,
        minute=0,
        id="weekly_roi",
    )

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    logger.info("Scheduler started. Jobs: %s", [j.id for j in scheduler.get_jobs()])
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    start()
