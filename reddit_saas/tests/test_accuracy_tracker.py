"""Tests for Forecast Accuracy Tracker.

Validates Task 10: Forecast Accuracy Tracking.
Tests record_predictions, evaluate_accuracy, get_accuracy_summary,
and suggest_confidence_adjustment.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.services.forecast.accuracy_tracker import (
    HORIZONS_WEEKS,
    TRACKED_METRICS,
    _check_within_bounds,
    _extract_actual_values,
    evaluate_accuracy,
    get_accuracy_summary,
    record_predictions,
    suggest_confidence_adjustment,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class MockQuery:
    """Minimal mock for SQLAlchemy query chain."""

    def __init__(self, results=None, scalar_value=None):
        self._results = results or []
        self._scalar_value = scalar_value

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._results[0] if self._results else None

    def all(self):
        return self._results

    def scalar(self):
        return self._scalar_value


@pytest.fixture
def sample_forecasted_json():
    """Sample forecasted_json from a report with all needed fields."""
    return {
        "label": "📈 Forecasted Outcomes",
        "visibility_4w": {
            "conservative": 9.5,
            "expected": 12.0,
            "optimistic": 15.5,
            "unit": "%",
            "confidence_level": "68%",
        },
        "visibility_12w": {
            "conservative": 18.0,
            "expected": 25.0,
            "optimistic": 32.0,
            "unit": "%",
            "confidence_level": "68%",
        },
        "visibility_24w": {
            "conservative": 25.0,
            "expected": 35.0,
            "optimistic": 45.0,
            "unit": "%",
            "confidence_level": "68%",
        },
        "per_engine_12w": {
            "perplexity": {"c": 22.0, "e": 30.0, "o": 38.0},
            "chatgpt": {"c": 15.0, "e": 22.0, "o": 29.0},
            "claude": {"c": 10.0, "e": 15.0, "o": 20.0},
        },
        "model_name": "logistic_scurve_v1",
    }


# ---------------------------------------------------------------------------
# Tests: record_predictions
# ---------------------------------------------------------------------------


class TestRecordPredictions:
    """Tests for record_predictions function."""

    def test_empty_forecasted_json_returns_empty(self):
        db = MagicMock()
        result = record_predictions(db, uuid.uuid4(), uuid.uuid4(), {})
        assert result == []

    def test_none_forecasted_json_returns_empty(self):
        db = MagicMock()
        result = record_predictions(db, uuid.uuid4(), uuid.uuid4(), None)
        assert result == []

    def test_creates_entries_for_overall_all_horizons(self, sample_forecasted_json):
        """Should create entries for geo.brand_rate.overall at 4w, 12w, 24w."""
        db = MagicMock()
        # Mock query().filter().first() to return None (no existing entries)
        db.query.return_value.filter.return_value.first.return_value = None

        report_id = uuid.uuid4()
        client_id = uuid.uuid4()

        entries = record_predictions(db, report_id, client_id, sample_forecasted_json)

        # 3 horizons × 3 scenarios for overall = 9
        # + 3 engines × 3 scenarios at 12w = 9
        # Total = 18
        assert len(entries) >= 9  # At least the overall entries

    def test_entry_has_correct_fields(self, sample_forecasted_json):
        """Each entry should have report_id, client_id, metric_id, etc."""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        report_id = uuid.uuid4()
        client_id = uuid.uuid4()

        entries = record_predictions(db, report_id, client_id, sample_forecasted_json)

        for entry in entries:
            assert entry.report_id == report_id
            assert entry.client_id == client_id
            assert entry.metric_id in TRACKED_METRICS
            assert entry.scenario in ["conservative", "expected", "optimistic"]
            assert entry.predicted_value is not None
            assert entry.actual_value is None  # Not yet evaluated
            assert entry.target_date is not None
            assert entry.predicted_at is not None

    def test_target_dates_are_in_future(self, sample_forecasted_json):
        """Target dates should be 4w, 12w, 24w from today."""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        entries = record_predictions(
            db, uuid.uuid4(), uuid.uuid4(), sample_forecasted_json
        )

        today = date.today()
        expected_targets = {
            today + timedelta(weeks=4),
            today + timedelta(weeks=12),
            today + timedelta(weeks=24),
        }

        actual_targets = {e.target_date for e in entries}
        assert actual_targets == expected_targets

    def test_per_engine_predictions_at_12w(self, sample_forecasted_json):
        """Should create per-engine predictions at the 12w horizon."""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        entries = record_predictions(
            db, uuid.uuid4(), uuid.uuid4(), sample_forecasted_json
        )

        # Find per-engine entries
        engine_entries = [
            e for e in entries if e.metric_id != "geo.brand_rate.overall"
        ]
        assert len(engine_entries) > 0

        engine_metrics = {e.metric_id for e in engine_entries}
        assert "geo.brand_rate.perplexity" in engine_metrics
        assert "geo.brand_rate.chatgpt" in engine_metrics
        assert "geo.brand_rate.claude" in engine_metrics

    def test_predicted_values_match_json(self, sample_forecasted_json):
        """Predicted values should match what's in the forecasted_json."""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        entries = record_predictions(
            db, uuid.uuid4(), uuid.uuid4(), sample_forecasted_json
        )

        # Find the expected scenario for overall at 12w
        target_12w = date.today() + timedelta(weeks=12)
        overall_expected_12w = [
            e
            for e in entries
            if e.metric_id == "geo.brand_rate.overall"
            and e.scenario == "expected"
            and e.target_date == target_12w
        ]
        assert len(overall_expected_12w) == 1
        assert float(overall_expected_12w[0].predicted_value) == 25.0


# ---------------------------------------------------------------------------
# Tests: _extract_actual_values
# ---------------------------------------------------------------------------


class TestExtractActualValues:
    """Tests for _extract_actual_values helper."""

    def test_extracts_tracked_metrics(self):
        """Should extract values for tracked metrics only."""
        snapshot = MagicMock()
        snapshot.metrics_json = [
            {"metric_id": "geo.brand_rate.overall", "value": 0.15},
            {"metric_id": "geo.brand_rate.perplexity", "value": 0.20},
            {"metric_id": "unrelated.metric", "value": 99.0},
        ]

        values = _extract_actual_values(snapshot)

        assert "geo.brand_rate.overall" in values
        assert "geo.brand_rate.perplexity" in values
        assert "unrelated.metric" not in values

    def test_converts_ratio_to_percentage(self):
        """Values stored as ratios (0-1) should be converted to percentage."""
        snapshot = MagicMock()
        snapshot.metrics_json = [
            {"metric_id": "geo.brand_rate.overall", "value": 0.077},
        ]

        values = _extract_actual_values(snapshot)
        assert values["geo.brand_rate.overall"] == pytest.approx(7.7)

    def test_handles_percentage_values(self):
        """Values already as percentage (>1) should pass through."""
        snapshot = MagicMock()
        snapshot.metrics_json = [
            {"metric_id": "geo.brand_rate.overall", "value": 15.5},
        ]

        values = _extract_actual_values(snapshot)
        assert values["geo.brand_rate.overall"] == 15.5

    def test_handles_empty_metrics(self):
        """Empty metrics_json should return empty dict."""
        snapshot = MagicMock()
        snapshot.metrics_json = []
        assert _extract_actual_values(snapshot) == {}

    def test_handles_none_metrics(self):
        """None metrics_json should return empty dict."""
        snapshot = MagicMock()
        snapshot.metrics_json = None
        assert _extract_actual_values(snapshot) == {}


# ---------------------------------------------------------------------------
# Tests: _check_within_bounds
# ---------------------------------------------------------------------------


class TestCheckWithinBounds:
    """Tests for _check_within_bounds helper."""

    def test_within_bounds_returns_true(self):
        """Actual within conservative-optimistic range should return True."""
        db = MagicMock()
        # Mock conservative=10.0, optimistic=30.0
        conservative = MagicMock()
        conservative.scenario = "conservative"
        conservative.predicted_value = Decimal("10.0")
        optimistic = MagicMock()
        optimistic.scenario = "optimistic"
        optimistic.predicted_value = Decimal("30.0")

        db.query.return_value.filter.return_value.all.return_value = [
            conservative,
            optimistic,
        ]

        result = _check_within_bounds(
            db, uuid.uuid4(), "geo.brand_rate.overall", date.today(), 20.0
        )
        assert result is True

    def test_outside_bounds_returns_false(self):
        """Actual outside conservative-optimistic range should return False."""
        db = MagicMock()
        conservative = MagicMock()
        conservative.scenario = "conservative"
        conservative.predicted_value = Decimal("10.0")
        optimistic = MagicMock()
        optimistic.scenario = "optimistic"
        optimistic.predicted_value = Decimal("30.0")

        db.query.return_value.filter.return_value.all.return_value = [
            conservative,
            optimistic,
        ]

        result = _check_within_bounds(
            db, uuid.uuid4(), "geo.brand_rate.overall", date.today(), 35.0
        )
        assert result is False

    def test_missing_scenario_returns_false(self):
        """If either conservative or optimistic is missing, return False."""
        db = MagicMock()
        conservative = MagicMock()
        conservative.scenario = "conservative"
        conservative.predicted_value = Decimal("10.0")

        db.query.return_value.filter.return_value.all.return_value = [conservative]

        result = _check_within_bounds(
            db, uuid.uuid4(), "geo.brand_rate.overall", date.today(), 15.0
        )
        assert result is False

    def test_boundary_value_is_within(self):
        """Value exactly at the boundary should be within bounds."""
        db = MagicMock()
        conservative = MagicMock()
        conservative.scenario = "conservative"
        conservative.predicted_value = Decimal("10.0")
        optimistic = MagicMock()
        optimistic.scenario = "optimistic"
        optimistic.predicted_value = Decimal("30.0")

        db.query.return_value.filter.return_value.all.return_value = [
            conservative,
            optimistic,
        ]

        # Test at lower boundary
        assert (
            _check_within_bounds(
                db, uuid.uuid4(), "geo.brand_rate.overall", date.today(), 10.0
            )
            is True
        )
        # Test at upper boundary
        assert (
            _check_within_bounds(
                db, uuid.uuid4(), "geo.brand_rate.overall", date.today(), 30.0
            )
            is True
        )


# ---------------------------------------------------------------------------
# Tests: suggest_confidence_adjustment
# ---------------------------------------------------------------------------


class TestSuggestConfidenceAdjustment:
    """Tests for suggest_confidence_adjustment function."""

    def test_insufficient_data_returns_1(self):
        """With fewer than 5 measurements, return 1.0 (no change)."""
        db = MagicMock()
        # First call: measured_count = 3
        db.query.return_value.filter.return_value.scalar.return_value = 3

        result = suggest_confidence_adjustment(db, uuid.uuid4())
        assert result == 1.0

    def test_low_within_rate_widens(self):
        """When within_bounds_rate < 50%, should suggest widening (>1.0)."""
        db = MagicMock()
        # First call: measured_count = 10
        # Second call: within_bounds_count = 3 (30% within rate)
        db.query.return_value.filter.return_value.scalar.side_effect = [10, 3]

        result = suggest_confidence_adjustment(db, uuid.uuid4())
        assert result > 1.0
        assert result <= 1.5  # Capped at 1.5

    def test_high_within_rate_narrows(self):
        """When within_bounds_rate > 90%, should suggest narrowing (<1.0)."""
        db = MagicMock()
        # measured_count = 10, within_bounds_count = 10 (100% within rate)
        db.query.return_value.filter.return_value.scalar.side_effect = [10, 10]

        result = suggest_confidence_adjustment(db, uuid.uuid4())
        assert result < 1.0
        assert result >= 0.7  # Capped at 0.7

    def test_normal_within_rate_no_change(self):
        """When within_bounds_rate is 50-90%, return 1.0."""
        db = MagicMock()
        # measured_count = 10, within_bounds_count = 7 (70% within rate)
        db.query.return_value.filter.return_value.scalar.side_effect = [10, 7]

        result = suggest_confidence_adjustment(db, uuid.uuid4())
        assert result == 1.0

    def test_zero_measurements_returns_1(self):
        """Zero measurements should return 1.0."""
        db = MagicMock()
        db.query.return_value.filter.return_value.scalar.return_value = 0

        result = suggest_confidence_adjustment(db, uuid.uuid4())
        assert result == 1.0


# ---------------------------------------------------------------------------
# Tests: get_accuracy_summary
# ---------------------------------------------------------------------------


class TestGetAccuracySummary:
    """Tests for get_accuracy_summary function."""

    def test_no_predictions_returns_zeros(self):
        """With no predictions, should return empty summary."""
        db = MagicMock()
        db.query.return_value.filter.return_value.scalar.return_value = 0

        result = get_accuracy_summary(db, uuid.uuid4())

        assert result["total_predictions"] == 0
        assert result["measured_count"] == 0
        assert result["within_bounds_rate"] is None
        assert result["avg_error_pp"] is None
        assert result["worst_miss"] is None

    def test_summary_structure_with_data(self):
        """When data exists, all expected keys should be present."""
        db = MagicMock()
        # total = 20, measured = 10, within = 7
        db.query.return_value.filter.return_value.scalar.side_effect = [20, 10, 7, 3.5]

        # Worst miss query
        worst = MagicMock()
        worst.metric_id = "geo.brand_rate.overall"
        worst.error_pp = Decimal("8.5")
        worst.predicted_value = Decimal("25.0")
        worst.actual_value = Decimal("16.5")
        worst.target_date = date(2026, 9, 1)
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = worst

        result = get_accuracy_summary(db, uuid.uuid4())

        assert result["total_predictions"] == 20
        assert result["measured_count"] == 10
        assert result["within_bounds_rate"] == 0.7
        assert result["avg_error_pp"] == 3.5
        assert result["worst_miss"]["metric_id"] == "geo.brand_rate.overall"
        assert result["worst_miss"]["error_pp"] == 8.5
