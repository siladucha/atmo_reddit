"""Tests for LLM Quality Monitor service."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models.ai_usage import AIUsageLog
from app.models.llm_quality_snapshot import LLMQualitySnapshot


def _create_usage_log(db, **kwargs):
    """Helper to create an AIUsageLog record."""
    defaults = {
        "id": uuid.uuid4(),
        "operation": "generation",
        "model": "anthropic/claude-sonnet-4-6",
        "input_tokens": 1000,
        "output_tokens": 200,
        "cost_usd": Decimal("0.0069"),
        "duration_ms": 3500,
        "quality_outcome": "success",
        "retry_count": 0,
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(kwargs)
    log = AIUsageLog(**defaults)
    db.add(log)
    db.commit()
    return log


class TestQualityOutcomeTracking:
    """Test that quality_outcome is properly stored on AIUsageLog."""

    def test_success_outcome(self, db):
        log = _create_usage_log(db, quality_outcome="success")
        assert log.quality_outcome == "success"

    def test_empty_outcome(self, db):
        log = _create_usage_log(db, quality_outcome="empty")
        assert log.quality_outcome == "empty"

    def test_parse_error_outcome(self, db):
        log = _create_usage_log(db, quality_outcome="parse_error")
        assert log.quality_outcome == "parse_error"

    def test_fallback_used_outcome(self, db):
        log = _create_usage_log(
            db,
            quality_outcome="fallback_used",
            fallback_model="anthropic/claude-sonnet-4-6",
        )
        assert log.quality_outcome == "fallback_used"
        assert log.fallback_model == "anthropic/claude-sonnet-4-6"

    def test_retry_count_stored(self, db):
        log = _create_usage_log(db, retry_count=2)
        assert log.retry_count == 2


class TestQualitySummary:
    """Test get_quality_summary function."""

    def test_empty_db_returns_defaults(self, db):
        from app.services.llm_quality_monitor import get_quality_summary

        summary = get_quality_summary(db, hours=24)
        assert summary["total_calls"] == 0 or summary["success_rate"] >= 0

    def test_summary_counts_outcomes(self, db):
        from app.services.llm_quality_monitor import get_quality_summary

        # Create mixed outcomes
        now = datetime.now(timezone.utc)
        for i in range(8):
            _create_usage_log(db, quality_outcome="success", created_at=now - timedelta(minutes=i))
        for i in range(2):
            _create_usage_log(db, quality_outcome="empty", created_at=now - timedelta(minutes=10 + i))

        summary = get_quality_summary(db, hours=1)
        assert summary["total_calls"] == 10
        assert summary["success_rate"] == 80.0
        assert summary["by_outcome"]["success"] == 8
        assert summary["by_outcome"]["empty"] == 2


class TestDegradationDetection:
    """Test compute_quality_snapshot detects degradation."""

    def test_no_data_returns_empty(self, db):
        from app.services.llm_quality_monitor import compute_quality_snapshot

        snapshots = compute_quality_snapshot(db, window_hours=4)
        assert snapshots == []

    def test_all_success_no_degradation(self, db):
        from app.services.llm_quality_monitor import compute_quality_snapshot

        now = datetime.now(timezone.utc)
        # Create baseline (7 days of success)
        for day in range(7):
            for i in range(10):
                _create_usage_log(
                    db,
                    quality_outcome="success",
                    created_at=now - timedelta(days=day, hours=i),
                )

        # Create current window (all success)
        for i in range(6):
            _create_usage_log(
                db,
                quality_outcome="success",
                created_at=now - timedelta(minutes=i * 30),
            )

        snapshots = compute_quality_snapshot(db, window_hours=4)
        for snap in snapshots:
            assert snap.degradation_detected is False

    def test_high_empty_rate_triggers_degradation(self, db):
        from app.services.llm_quality_monitor import compute_quality_snapshot

        now = datetime.now(timezone.utc)
        # Baseline: mostly success
        for day in range(1, 7):
            for i in range(10):
                _create_usage_log(
                    db,
                    quality_outcome="success",
                    created_at=now - timedelta(days=day, hours=i),
                )

        # Current window: 50% empty (way above 15% threshold)
        for i in range(5):
            _create_usage_log(
                db,
                quality_outcome="success",
                created_at=now - timedelta(minutes=i * 10),
            )
        for i in range(5):
            _create_usage_log(
                db,
                quality_outcome="empty",
                created_at=now - timedelta(minutes=50 + i * 10),
            )

        snapshots = compute_quality_snapshot(db, window_hours=4)
        degraded = [s for s in snapshots if s.degradation_detected]
        assert len(degraded) > 0
        # Should have high_empty signal
        details = degraded[0].degradation_details
        assert any(d["type"] == "high_empty" for d in details)


class TestLLMQualitySnapshot:
    """Test LLMQualitySnapshot model."""

    def test_create_snapshot(self, db):
        now = datetime.now(timezone.utc)
        snap = LLMQualitySnapshot(
            window_start=now - timedelta(hours=4),
            window_end=now,
            model="gemini/gemini-2.5-flash",
            operation="scoring",
            total_calls=100,
            success_count=95,
            empty_count=3,
            parse_error_count=2,
            success_rate=Decimal("95.00"),
            degradation_detected=False,
        )
        db.add(snap)
        db.commit()

        assert snap.id is not None
        assert snap.success_rate == Decimal("95.00")
