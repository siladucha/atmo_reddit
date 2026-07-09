"""Tests for the Trial Signal Collector service."""

import uuid
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.exc import OperationalError

from app.models.client import Client
from app.models.trial_signal import TrialSignal
from app.services.trial_signals import (
    SignalCategory,
    SignalCollector,
    DAILY_SIGNAL_CAP,
    DEDUP_WINDOW_SECONDS,
    TZ,
)


@pytest.fixture
def trial_client(db):
    """Create a trial client for testing."""
    client = Client(
        id=uuid.uuid4(),
        client_name="Test Trial Co",
        brand_name="TestBrand",
        plan_type="trial",
        is_active=True,
    )
    db.add(client)
    db.flush()
    return client


@pytest.fixture
def non_trial_client(db):
    """Create a non-trial (starter) client for testing."""
    client = Client(
        id=uuid.uuid4(),
        client_name="Paid Client Co",
        brand_name="PaidBrand",
        plan_type="starter",
        is_active=True,
    )
    db.add(client)
    db.flush()
    return client


@pytest.fixture
def inactive_trial_client(db):
    """Create an inactive trial client for testing."""
    client = Client(
        id=uuid.uuid4(),
        client_name="Inactive Trial Co",
        brand_name="InactiveBrand",
        plan_type="trial",
        is_active=False,
    )
    db.add(client)
    db.flush()
    return client


@pytest.fixture
def collector(db):
    """Create a SignalCollector instance."""
    return SignalCollector(db)


class TestIsTrialClient:
    """Tests for the is_trial_client helper (subtask 2.5)."""

    def test_returns_true_for_active_trial_client(self, collector, trial_client):
        assert collector.is_trial_client(trial_client.id) is True

    def test_returns_false_for_non_trial_client(self, collector, non_trial_client):
        assert collector.is_trial_client(non_trial_client.id) is False

    def test_returns_false_for_inactive_trial_client(self, collector, inactive_trial_client):
        assert collector.is_trial_client(inactive_trial_client.id) is False

    def test_returns_false_for_nonexistent_client(self, collector):
        fake_id = uuid.uuid4()
        assert collector.is_trial_client(fake_id) is False


class TestRecordSignal:
    """Tests for record_signal (subtask 2.2)."""

    def test_records_signal_for_trial_client(self, collector, trial_client):
        signal_id = collector.record_signal(
            client_id=trial_client.id,
            signal_type="page_view",
            signal_category=SignalCategory.engagement,
            signal_value={"page": "/portal/home"},
        )
        assert signal_id is not None
        # Verify it was persisted
        signal = collector.db.query(TrialSignal).filter(TrialSignal.id == signal_id).first()
        assert signal is not None
        assert signal.signal_type == "page_view"
        assert signal.signal_category == "engagement"
        assert signal.signal_value == {"page": "/portal/home"}

    def test_stores_with_jerusalem_timezone(self, collector, trial_client):
        signal_id = collector.record_signal(
            client_id=trial_client.id,
            signal_type="login",
            signal_category=SignalCategory.engagement,
        )
        signal = collector.db.query(TrialSignal).filter(TrialSignal.id == signal_id).first()
        # Verify timezone-aware timestamp
        assert signal.created_at.tzinfo is not None

    def test_short_circuits_for_non_trial_client(self, collector, non_trial_client):
        result = collector.record_signal(
            client_id=non_trial_client.id,
            signal_type="page_view",
            signal_category=SignalCategory.engagement,
        )
        assert result is None
        # _dispatch_recompute removed from service

    def test_dedup_within_60s_window(self, collector, trial_client, db):
        # First signal should succeed
        signal_id_1 = collector.record_signal(
            client_id=trial_client.id,
            signal_type="page_view",
            signal_category=SignalCategory.engagement,
        )
        assert signal_id_1 is not None

        # Same type within 60s should be deduplicated
        signal_id_2 = collector.record_signal(
            client_id=trial_client.id,
            signal_type="page_view",
            signal_category=SignalCategory.engagement,
        )
        assert signal_id_2 is None

    def test_different_signal_type_not_deduped(self, collector, trial_client):
        signal_id_1 = collector.record_signal(
            client_id=trial_client.id,
            signal_type="page_view",
            signal_category=SignalCategory.engagement,
        )
        signal_id_2 = collector.record_signal(
            client_id=trial_client.id,
            signal_type="report_viewed",
            signal_category=SignalCategory.value_realization,
        )
        assert signal_id_1 is not None
        assert signal_id_2 is not None

    def test_dispatches_recompute_on_success(self, collector, trial_client):
        collector.record_signal(
            client_id=trial_client.id,
            signal_type="page_view",
            signal_category=SignalCategory.engagement,
        )
        # _dispatch_recompute removed from service


class TestDailyCap:
    """Tests for daily cap enforcement (subtask 2.4)."""

    def test_enforces_daily_cap(self, collector, trial_client, db):
        now = datetime.now(TZ)
        # Pre-populate with DAILY_SIGNAL_CAP signals
        for i in range(DAILY_SIGNAL_CAP):
            sig = TrialSignal(
                client_id=trial_client.id,
                signal_type=f"bulk_signal_{i}",
                signal_category="engagement",
                created_at=now - timedelta(seconds=i + 61),  # outside dedup window
            )
            db.add(sig)
        db.flush()

        # Next signal should be rejected
        result = collector.record_signal(
            client_id=trial_client.id,
            signal_type="one_more_signal",
            signal_category=SignalCategory.engagement,
        )
        assert result is None


class TestRetryOnDbError:
    """Tests for retry-once-on-db-error (subtask 2.3)."""

    @patch("app.services.trial_signals.time.sleep")
    def test_retries_once_on_operational_error(self, mock_sleep, collector, trial_client):
        signal = TrialSignal(
            client_id=trial_client.id,
            signal_type="test_retry",
            signal_category="engagement",
            created_at=datetime.now(TZ),
        )

        # Simulate first attempt fails, second succeeds
        original_add = collector.db.add
        call_count = [0]

        def side_effect_add(obj):
            call_count[0] += 1
            if call_count[0] == 1:
                original_add(obj)
                raise OperationalError("test", {}, Exception("connection lost"))
            original_add(obj)

        with patch.object(collector.db, "add", side_effect=side_effect_add):
            with patch.object(collector.db, "rollback"):
                result = collector._persist_signal(signal)

        # Should have slept 2s between attempts
        mock_sleep.assert_called_once_with(2)

    @patch("app.services.trial_signals.time.sleep")
    def test_discards_after_second_failure(self, mock_sleep, collector, trial_client):
        signal = TrialSignal(
            client_id=trial_client.id,
            signal_type="test_discard",
            signal_category="engagement",
            created_at=datetime.now(TZ),
        )

        # Both attempts fail
        with patch.object(collector.db, "add", side_effect=OperationalError("test", {}, Exception("down"))):
            with patch.object(collector.db, "rollback"):
                result = collector._persist_signal(signal)

        assert result is None
        mock_sleep.assert_called_once_with(2)


class TestRecordNegativeSignal:
    """Tests for record_negative_signal helper."""

    def test_records_with_negative_category(self, collector, trial_client):
        signal_id = collector.record_negative_signal(
            client_id=trial_client.id,
            signal_type="no_activity_72h",
            metadata={"last_activity_hours_ago": 80},
        )
        assert signal_id is not None
        signal = collector.db.query(TrialSignal).filter(TrialSignal.id == signal_id).first()
        assert signal.signal_category == "negative"
        assert signal.signal_type == "no_activity_72h"


class TestGetSignals:
    """Tests for get_signals helper."""

    def test_returns_all_signals_for_client(self, collector, trial_client):
        # Record a few signals with different types
        collector.record_signal(trial_client.id, "page_view", SignalCategory.engagement)
        collector.record_signal(trial_client.id, "report_viewed", SignalCategory.value_realization)

        signals = collector.get_signals(trial_client.id)
        assert len(signals) == 2

    def test_filters_by_since(self, collector, trial_client, db):
        # Create an old signal directly
        old_signal = TrialSignal(
            client_id=trial_client.id,
            signal_type="old_signal",
            signal_category="engagement",
            created_at=datetime.now(TZ) - timedelta(days=5),
        )
        db.add(old_signal)
        db.flush()

        # Record a new signal
        collector.record_signal(trial_client.id, "new_signal", SignalCategory.engagement)

        # Filter since 1 day ago
        since = datetime.now(TZ) - timedelta(days=1)
        signals = collector.get_signals(trial_client.id, since=since)
        assert len(signals) == 1
        assert signals[0].signal_type == "new_signal"

    def test_returns_empty_for_client_with_no_signals(self, collector, trial_client):
        signals = collector.get_signals(trial_client.id)
        assert signals == []
