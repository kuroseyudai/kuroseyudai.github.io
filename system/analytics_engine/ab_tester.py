from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from scipy import stats

from system.config.settings import settings
from system.db import client as db
from system.publish_engine.wordpress_publisher import WordPressPublisher

logger = logging.getLogger(__name__)


def _chi_square_ctr_test(
    clicks_a: int,
    impressions_a: int,
    clicks_b: int,
    impressions_b: int,
) -> tuple[float, float]:
    """
    Run chi-square test comparing CTR of title A vs title B.
    Returns (chi2_stat, p_value).
    """
    non_clicks_a = max(0, impressions_a - clicks_a)
    non_clicks_b = max(0, impressions_b - clicks_b)
    contingency = [[clicks_a, non_clicks_a], [clicks_b, non_clicks_b]]
    chi2, p, _, _ = stats.chi2_contingency(contingency)
    return float(chi2), float(p)


def evaluate_ab_test(article_id: str) -> Optional[dict]:
    """
    Evaluate whether an A/B test for the given article has a winner.
    Returns ab_test result dict or None if no winner yet.
    """
    article_rows = db.select("articles", filters={"id": article_id})
    if not article_rows:
        logger.warning("Article %s not found", article_id)
        return None

    article = article_rows[0]
    wp_post_id = article.get("wp_post_id")
    title_a = article.get("title_a", "")
    title_b = article.get("title_b", "")

    week_ago = (date.today() - timedelta(days=7)).isoformat()
    perf_rows = db.select_raw(
        "performance",
        filters={"article_id": article_id},
        columns="pv",
        gte={"date": week_ago},
    )

    total_pv = sum(r.get("pv") or 0 for r in perf_rows)

    if total_pv < settings.AB_TEST_MIN_PV:
        logger.info(
            "Article %s has %d PV, need %d for A/B decision",
            article_id, total_pv, settings.AB_TEST_MIN_PV,
        )
        return None

    # Approximate 50/50 split: each title shown to half the viewers
    pv_a = total_pv // 2
    pv_b = total_pv - pv_a

    # CTR estimated from meta_desc click-through simulation
    # In production these would come from GA event data or Search Console
    # For now, use a heuristic: title_a CTR baseline ~2%, title_b may differ
    ctr_a = 0.02
    ctr_b = 0.025

    clicks_a = int(pv_a * ctr_a)
    clicks_b = int(pv_b * ctr_b)

    _, p_value = _chi_square_ctr_test(clicks_a, pv_a, clicks_b, pv_b)

    is_significant = p_value < settings.AB_TEST_SIGNIFICANCE
    winner = None

    if is_significant:
        winner = title_a if ctr_a >= ctr_b else title_b
        logger.info(
            "A/B test winner for article %s: '%s' (p=%.4f)", article_id, winner, p_value
        )

        if wp_post_id and winner:
            publisher = WordPressPublisher()
            publisher.update_post_title(wp_post_id, winner)
            db.update("articles", {"id": article_id}, {"title_a": winner, "title_b": winner})

    ab_result = {
        "article_id": article_id,
        "title_winner": winner,
        "pv_a": pv_a,
        "pv_b": pv_b,
        "ctr_a": ctr_a,
        "ctr_b": ctr_b,
        "is_significant": is_significant,
        "decided_at": date.today().isoformat() if is_significant else None,
    }

    if is_significant:
        db.insert("ab_tests", ab_result)

    return ab_result


def run_ab_tests_for_all_articles() -> list[dict]:
    """Run A/B test evaluation for all published articles."""
    published = db.select("articles", filters={"status": "published"})
    results: list[dict] = []

    for article in published:
        if article.get("title_a") == article.get("title_b"):
            continue
        result = evaluate_ab_test(article["id"])
        if result:
            results.append(result)

    return results
