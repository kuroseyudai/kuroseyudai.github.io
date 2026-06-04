from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from system.research_engine.scorer import (
    calculate_score,
    is_score_anomaly,
    get_prev_week_avg_score,
    safe_score,
    get_genre_roi_recommendation,
    aggregate_genre_roi,
    GENRE_RECOMMENDATION_SCALE_UP,
    GENRE_RECOMMENDATION_HOLD,
    GENRE_RECOMMENDATION_SCALE_DOWN,
)


class TestCalculateScore:
    def test_basic_score(self):
        score = calculate_score(1000, 2.0, 0.5)
        assert score == pytest.approx(4000.0)

    def test_score_formula(self):
        # score = volume * cpc * (1/competition)
        assert calculate_score(500, 1.0, 0.25) == pytest.approx(2000.0)

    def test_returns_none_when_volume_missing(self):
        assert calculate_score(None, 2.0, 0.5) is None

    def test_returns_none_when_cpc_missing(self):
        assert calculate_score(1000, None, 0.5) is None

    def test_returns_none_when_competition_missing(self):
        assert calculate_score(1000, 2.0, None) is None

    def test_returns_none_when_competition_zero(self):
        assert calculate_score(1000, 2.0, 0.0) is None

    def test_returns_none_when_all_missing(self):
        assert calculate_score(None, None, None) is None

    def test_high_competition_reduces_score(self):
        low_comp = calculate_score(1000, 2.0, 0.1)
        high_comp = calculate_score(1000, 2.0, 0.9)
        assert low_comp > high_comp


class TestScoreAnomaly:
    @patch("system.research_engine.scorer.db.select_raw")
    def test_no_anomaly_when_insufficient_data(self, mock_select):
        mock_select.return_value = [{"score": 100.0}, {"score": 110.0}]
        assert is_score_anomaly(150.0, "test keyword", "en") is False

    @patch("system.research_engine.scorer.db.select_raw")
    def test_anomaly_detected_when_deviation_exceeds_threshold(self, mock_select):
        mock_select.return_value = [
            {"score": 100.0},
            {"score": 105.0},
            {"score": 98.0},
        ]
        assert is_score_anomaly(500.0, "test keyword", "en") is True

    @patch("system.research_engine.scorer.db.select_raw")
    def test_no_anomaly_for_normal_score(self, mock_select):
        mock_select.return_value = [
            {"score": 100.0},
            {"score": 105.0},
            {"score": 98.0},
        ]
        assert is_score_anomaly(102.0, "test keyword", "en") is False

    @patch("system.research_engine.scorer.db.select_raw")
    def test_no_anomaly_when_avg_is_zero(self, mock_select):
        mock_select.return_value = [
            {"score": 0.0},
            {"score": 0.0},
            {"score": 0.0},
        ]
        assert is_score_anomaly(10.0, "test keyword", "en") is False


class TestSafeScore:
    @patch("system.research_engine.scorer.is_score_anomaly")
    def test_returns_calculated_score_normally(self, mock_anomaly):
        mock_anomaly.return_value = False
        score = safe_score("keyword", "en", 1000, 2.0, 0.5)
        assert score == pytest.approx(4000.0)

    @patch("system.research_engine.scorer.get_prev_week_avg_score")
    @patch("system.research_engine.scorer.is_score_anomaly")
    def test_uses_fallback_on_anomaly(self, mock_anomaly, mock_avg):
        mock_anomaly.return_value = True
        mock_avg.return_value = 200.0
        score = safe_score("keyword", "en", 1000, 2.0, 0.5)
        assert score == pytest.approx(200.0)

    @patch("system.research_engine.scorer.get_prev_week_avg_score")
    @patch("system.research_engine.scorer.is_score_anomaly")
    def test_uses_calculated_score_when_no_fallback(self, mock_anomaly, mock_avg):
        mock_anomaly.return_value = True
        mock_avg.return_value = None
        score = safe_score("keyword", "en", 1000, 2.0, 0.5)
        assert score == pytest.approx(4000.0)

    def test_returns_none_for_missing_inputs(self):
        score = safe_score("keyword", "en", None, None, None)
        assert score is None


class TestGenreRoiRecommendation:
    @patch("system.research_engine.scorer.db.select_raw")
    @patch("system.research_engine.scorer.db.select")
    def test_scale_up_when_roi_exceeds_threshold(self, mock_select, mock_select_raw):
        mock_select.return_value = [{"id": "article-1"}]
        mock_select_raw.side_effect = [
            [{"id": "kw-1"}],
            [{"id": "article-1", "keyword_id": "kw-1"}],
            [{"roi": 75.0}, {"roi": 80.0}],
        ]
        result = get_genre_roi_recommendation("technology")
        assert result == GENRE_RECOMMENDATION_SCALE_UP

    @patch("system.research_engine.scorer.db.select_raw")
    @patch("system.research_engine.scorer.db.select")
    def test_scale_down_when_roi_below_threshold(self, mock_select, mock_select_raw):
        mock_select.return_value = [{"id": "article-1"}]
        mock_select_raw.side_effect = [
            [{"id": "kw-1"}],
            [{"id": "article-1", "keyword_id": "kw-1"}],
            [{"roi": 5.0}, {"roi": 3.0}],
        ]
        result = get_genre_roi_recommendation("technology")
        assert result == GENRE_RECOMMENDATION_SCALE_DOWN

    @patch("system.research_engine.scorer.db.select")
    def test_hold_when_no_articles(self, mock_select):
        mock_select.return_value = []
        result = get_genre_roi_recommendation("technology")
        assert result == GENRE_RECOMMENDATION_HOLD


class TestKeywordDBSave:
    @patch("system.research_engine.keyword_fetcher.db.insert")
    @patch("system.research_engine.keyword_fetcher._get_keyword_metrics")
    @patch("system.research_engine.keyword_fetcher._fetch_trending_for_genre")
    @patch("system.research_engine.keyword_fetcher._build_pytrends")
    def test_stores_keyword_to_db(self, mock_pytrends, mock_trending, mock_metrics, mock_insert):
        from system.research_engine.keyword_fetcher import fetch_and_store_keywords

        mock_trending.return_value = ["test keyword"]
        mock_metrics.return_value = {"search_volume": 1000, "cpc": 1.5, "competition": 0.5}
        mock_insert.return_value = {"id": "uuid-1", "keyword": "test keyword"}

        results = fetch_and_store_keywords(languages=["en"])

        assert mock_insert.called
        call_args = mock_insert.call_args[0]
        assert call_args[0] == "keywords"
        assert "keyword" in call_args[1]
        assert "language" in call_args[1]
        assert "score" in call_args[1]
