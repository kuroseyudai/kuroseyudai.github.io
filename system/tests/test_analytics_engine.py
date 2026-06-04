from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from datetime import date

from system.analytics_engine.ab_tester import (
    _chi_square_ctr_test,
    evaluate_ab_test,
)
from system.analytics_engine.roi_calculator import (
    calculate_article_roi,
    get_genre_recommendation,
    aggregate_weekly_genre_roi,
    update_performance_roi,
)


class TestChiSquareTest:
    def test_significant_difference(self):
        # 100 clicks out of 1000 vs 50 clicks out of 1000 - clearly different
        _, p = _chi_square_ctr_test(100, 1000, 50, 1000)
        assert p < 0.05

    def test_no_significant_difference(self):
        # Identical counts should give p=1.0 or NaN, no significance
        _, p = _chi_square_ctr_test(50, 1000, 50, 1000)
        assert p >= 0.05 or p != p  # p >= 0.05 or NaN

    def test_returns_float_tuple(self):
        chi2, p = _chi_square_ctr_test(60, 1000, 40, 1000)
        assert isinstance(chi2, float)
        assert isinstance(p, float)

    def test_zero_clicks_handled(self):
        # Should not raise even with zero clicks
        chi2, p = _chi_square_ctr_test(0, 1000, 10, 1000)
        assert isinstance(p, float)


class TestEvaluateAbTest:
    def _article_row(self):
        return {
            "id": "art-uuid",
            "title_a": "Title Version A",
            "title_b": "Title Version B",
            "wp_post_id": 42,
            "status": "published",
        }

    @patch("system.analytics_engine.ab_tester.db.select")
    @patch("system.analytics_engine.ab_tester.db.select_raw")
    def test_returns_none_when_pv_below_minimum(self, mock_select_raw, mock_select):
        mock_select.return_value = [self._article_row()]
        mock_select_raw.return_value = [{"pv": 100}, {"pv": 50}]  # total 150, below 300

        result = evaluate_ab_test("art-uuid")
        assert result is None

    @patch("system.analytics_engine.ab_tester.db.insert")
    @patch("system.analytics_engine.ab_tester.db.update")
    @patch("system.analytics_engine.ab_tester.WordPressPublisher")
    @patch("system.analytics_engine.ab_tester.db.select")
    @patch("system.analytics_engine.ab_tester.db.select_raw")
    def test_determines_winner_with_sufficient_pv(
        self, mock_select_raw, mock_select, mock_wp, mock_update, mock_insert
    ):
        mock_select.return_value = [self._article_row()]
        mock_select_raw.return_value = [{"pv": 200}, {"pv": 200}]  # total 400 >= 300

        mock_wp_instance = MagicMock()
        mock_wp_instance.update_post_title.return_value = True
        mock_wp.return_value = mock_wp_instance

        result = evaluate_ab_test("art-uuid")

        assert result is not None
        assert "pv_a" in result
        assert "pv_b" in result
        assert "is_significant" in result

    @patch("system.analytics_engine.ab_tester.db.select")
    def test_returns_none_for_unknown_article(self, mock_select):
        mock_select.return_value = []
        result = evaluate_ab_test("nonexistent-id")
        assert result is None


class TestROICalculator:
    def test_positive_roi(self):
        roi = calculate_article_roi(total_revenue=1.0, api_cost=0.5)
        assert roi == pytest.approx(100.0)

    def test_negative_roi(self):
        roi = calculate_article_roi(total_revenue=0.1, api_cost=0.5)
        assert roi == pytest.approx(-80.0)

    def test_zero_revenue_gives_negative_roi(self):
        roi = calculate_article_roi(total_revenue=0.0, api_cost=0.5)
        assert roi == pytest.approx(-100.0)

    def test_returns_none_when_cost_is_zero(self):
        roi = calculate_article_roi(total_revenue=1.0, api_cost=0.0)
        assert roi is None

    def test_returns_none_when_cost_is_negative(self):
        roi = calculate_article_roi(total_revenue=1.0, api_cost=-0.1)
        assert roi is None

    def test_roi_formula(self):
        # (2.0 - 0.5) / 0.5 * 100 = 300.0%
        roi = calculate_article_roi(total_revenue=2.0, api_cost=0.5)
        assert roi == pytest.approx(300.0)


class TestGenreRecommendation:
    def test_scale_up_above_threshold(self):
        assert get_genre_recommendation(60.0) == "scale_up"
        assert get_genre_recommendation(50.1) == "scale_up"

    def test_hold_at_boundary(self):
        assert get_genre_recommendation(50.0) == "hold"
        assert get_genre_recommendation(10.0) == "hold"
        assert get_genre_recommendation(25.0) == "hold"

    def test_scale_down_below_threshold(self):
        assert get_genre_recommendation(9.9) == "scale_down"
        assert get_genre_recommendation(0.0) == "scale_down"
        assert get_genre_recommendation(-10.0) == "scale_down"

    def test_hold_when_roi_is_none(self):
        assert get_genre_recommendation(None) == "hold"


class TestUpdatePerformanceROI:
    @patch("system.analytics_engine.roi_calculator.db.update")
    @patch("system.analytics_engine.roi_calculator.db.select_raw")
    def test_updates_roi_for_all_records(self, mock_select_raw, mock_update):
        mock_select_raw.return_value = [
            {"article_id": "art-1", "revenue_ad": 0.5, "revenue_aff": 0.1, "api_cost": 0.15, "date": "2026-06-03"},
            {"article_id": "art-2", "revenue_ad": 0.2, "revenue_aff": 0.0, "api_cost": 0.15, "date": "2026-06-03"},
        ]

        count = update_performance_roi(report_date=date(2026, 6, 3))
        assert count == 2
        assert mock_update.call_count == 2

    @patch("system.analytics_engine.roi_calculator.db.update")
    @patch("system.analytics_engine.roi_calculator.db.select_raw")
    def test_uses_default_api_cost_when_missing(self, mock_select_raw, mock_update):
        mock_select_raw.return_value = [
            {"article_id": "art-1", "revenue_ad": 1.0, "revenue_aff": 0.0, "api_cost": None, "date": "2026-06-03"},
        ]

        update_performance_roi(report_date=date(2026, 6, 3))

        update_call = mock_update.call_args[0][2]
        # api_cost falls back to API_COST_PER_ARTICLE = 0.15
        assert update_call["api_cost"] == 0.15


class TestAggregateWeeklyGenreROI:
    @patch("system.analytics_engine.roi_calculator.get_genre_avg_roi")
    @patch("system.analytics_engine.roi_calculator.db.select_raw")
    def test_returns_all_genres(self, mock_select_raw, mock_avg_roi):
        mock_select_raw.return_value = [
            {"genre": "technology"},
            {"genre": "finance"},
            {"genre": "health"},
        ]
        mock_avg_roi.side_effect = [75.0, 15.0, 5.0]

        results = aggregate_weekly_genre_roi()

        assert "technology" in results
        assert "finance" in results
        assert "health" in results
        assert results["technology"]["recommendation"] == "scale_up"
        assert results["finance"]["recommendation"] == "hold"
        assert results["health"]["recommendation"] == "scale_down"

    @patch("system.analytics_engine.roi_calculator.db.select_raw")
    def test_returns_empty_when_no_genres(self, mock_select_raw):
        mock_select_raw.return_value = []
        results = aggregate_weekly_genre_roi()
        assert results == {}
