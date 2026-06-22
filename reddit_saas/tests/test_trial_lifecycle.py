"""Tests for Trial Lifecycle State Machine (Task 5).

Tests cover:
  5.1 LifecycleFSM class instantiation
  5.2 VALID_TRANSITIONS map completeness
  5.3 evaluate_state logic
  5.4 All transition rules
  5.5 ActivityEvent emission on state transitions
"""

import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.models.activity_event import ActivityEvent
from app.models.client import Client
from app.models.trial_signal import TrialSignal
from app.services.trial_lifecycle import (
    ENGAGED_SIGNAL_COUNT,
    FORWARD_PROGRESSION,
    HIGH_INTENT_SIGNAL_TYPES,
    INACTIVITY_THRESHOLD_HOURS,
    NEGATIVE_SIGNAL_THRESHOLD,
    ONBOARDING_COMPLETED_TYPE,
    ONBOARDING_STARTED_SIGNAL_TYPES,
    TRIAL_DURATION_DAYS,
    VALID_TRANSITIONS,
    VALUE_REALIZATION_SIGNAL_TYPES,
    LifecycleFSM,
    TrialLifecycleState,
    _state_rank,
    count_negative_signals,
    count_value_realization_signals,
    get_last_signal_time,
    has_any_conversion_signal,
    has_onboarding_started,
    has_signal_type,
)

TZ = ZoneInfo("Asia/Jerusalem")


def _make_signal(
    signal_type: str,
    category: str = "engagement",
    value: dict | None = None,
    created_at: datetime | None = None,
) -> TrialSignal:
    """Helper to create a TrialSignal mock."""
    signal = MagicMock(spec=TrialSignal)
    signal.signal_type = signal_type
    signal.signal_category = category
    signal.signal_value = value
    signal.created_at = created_at or datetime.now(TZ)
    return signal


def _make_client(
    plan_type: str = "trial",
    created_at: datetime | None = None,
    keywords: dict | None = None,
    onboarding_completed_at: datetime | None = None,
) -> Client:
    """Helper to create a Client mock."""
    client = MagicMock(spec=Client)
    client.id = uuid.uuid4()
    client.plan_type = plan_type
    client.created_at = created_at or datetime.now(TZ)
    client.keywords = keywords
    client.onboarding_completed_at = onboarding_completed_at
    return client


class TestValidTransitions:
    """Task 5.2: Verify VALID_TRANSITIONS map."""

    def test_all_9_states_have_entries(self):
        """Every TrialLifecycleState has a key in VALID_TRANSITIONS."""
        for state in TrialLifecycleState:
            assert state in VALID_TRANSITIONS, f"{state} missing"

    def test_converted_is_terminal(self):
        """converted has no valid outgoing transitions."""
        assert VALID_TRANSITIONS[TrialLifecycleState.converted] == set()

    def test_trial_started_transitions(self):
        expected = {
            TrialLifecycleState.onboarding_started,
            TrialLifecycleState.at_risk,
            TrialLifecycleState.expired,
        }
        assert VALID_TRANSITIONS[TrialLifecycleState.trial_started] == expected

    def test_at_risk_can_recover(self):
        """at_risk can transition to engaged, high_intent, expired, converted."""
        targets = VALID_TRANSITIONS[TrialLifecycleState.at_risk]
        assert TrialLifecycleState.engaged in targets
        assert TrialLifecycleState.high_intent in targets
        assert TrialLifecycleState.converted in targets

    def test_expired_can_reactivate(self):
        targets = VALID_TRANSITIONS[TrialLifecycleState.expired]
        assert TrialLifecycleState.reactivated in targets
        assert TrialLifecycleState.converted in targets

    def test_reactivated_transitions(self):
        expected = {
            TrialLifecycleState.engaged,
            TrialLifecycleState.high_intent,
            TrialLifecycleState.converted,
            TrialLifecycleState.expired,
        }
        assert VALID_TRANSITIONS[TrialLifecycleState.reactivated] == expected

    def test_all_target_states_are_valid_lifecycle_states(self):
        """All target states in the map are valid TrialLifecycleState values."""
        for _from, targets in VALID_TRANSITIONS.items():
            for target in targets:
                assert target in TrialLifecycleState


class TestHelperFunctions:
    """Test standalone helper functions."""

    def test_get_last_signal_time_empty(self):
        assert get_last_signal_time([]) is None

    def test_get_last_signal_time_returns_max(self):
        s1 = _make_signal("a", created_at=datetime(2026, 6, 1, tzinfo=TZ))
        s2 = _make_signal("b", created_at=datetime(2026, 6, 5, tzinfo=TZ))
        s3 = _make_signal("c", created_at=datetime(2026, 6, 3, tzinfo=TZ))
        assert get_last_signal_time([s1, s2, s3]) == datetime(2026, 6, 5, tzinfo=TZ)

    def test_count_negative_signals(self):
        signals = [
            _make_signal("no_activity_72h", "negative"),
            _make_signal("login", "engagement"),
            _make_signal("bounced_email", "negative"),
        ]
        assert count_negative_signals(signals) == 2

    def test_count_value_realization_signals(self):
        signals = [
            _make_signal("report_viewed", "value_realization"),
            _make_signal("discovery_run", "value_realization"),
            _make_signal("login", "engagement"),
            _make_signal("keywords_configured", "intent"),
        ]
        assert count_value_realization_signals(signals) == 3  # report_viewed, discovery_run, keywords_configured

    def test_has_signal_type(self):
        signals = [_make_signal("login"), _make_signal("pricing_viewed")]
        assert has_signal_type(signals, "login")
        assert not has_signal_type(signals, "nonexistent")

    def test_has_any_conversion_signal(self):
        signals = [_make_signal("login"), _make_signal("pricing_viewed")]
        assert has_any_conversion_signal(signals)

    def test_has_onboarding_started(self):
        signals = [_make_signal("onboarding_wizard_opened")]
        assert has_onboarding_started(signals)

    def test_state_rank_forward_progression(self):
        assert _state_rank(TrialLifecycleState.trial_started) == 0
        assert _state_rank(TrialLifecycleState.onboarding_started) == 1
        assert _state_rank(TrialLifecycleState.activated) == 2
        assert _state_rank(TrialLifecycleState.engaged) == 3
        assert _state_rank(TrialLifecycleState.high_intent) == 4
        assert _state_rank(TrialLifecycleState.converted) == 5

    def test_state_rank_non_progression_returns_negative(self):
        assert _state_rank(TrialLifecycleState.at_risk) == -1
        assert _state_rank(TrialLifecycleState.expired) == -1
        assert _state_rank(TrialLifecycleState.reactivated) == -1


class TestLifecycleFSMEvaluateState:
    """Task 5.3 & 5.4: evaluate_state transition rules."""

    def test_terminal_converted_no_change(self, db):
        """converted state is terminal."""
        fsm = LifecycleFSM(db)
        client = _make_client(plan_type="trial")
        db.query = MagicMock(return_value=MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=client)))))

        result = fsm.evaluate_state(client.id, [], "converted")
        assert result == "converted"

    def test_plan_type_not_trial_converts(self, db):
        """If plan_type changed from trial, state becomes converted."""
        fsm = LifecycleFSM(db)
        client = _make_client(plan_type="starter")
        db.query = MagicMock(return_value=MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=client)))))

        result = fsm.evaluate_state(client.id, [], "engaged")
        assert result == "converted"

    def test_expired_after_14_days(self, db):
        """Trial expires after 14 days."""
        fsm = LifecycleFSM(db)
        client = _make_client(
            created_at=datetime.now(TZ) - timedelta(days=15),
        )
        db.query = MagicMock(return_value=MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=client)))))

        result = fsm.evaluate_state(client.id, [], "engaged")
        assert result == "expired"

    def test_reactivated_after_expiry(self, db):
        """Expired trial reactivates on new signals after expiry."""
        fsm = LifecycleFSM(db)
        created_at = datetime.now(TZ) - timedelta(days=20)
        client = _make_client(created_at=created_at)

        # Signal after expiry
        expiry_time = created_at + timedelta(days=TRIAL_DURATION_DAYS)
        signal = _make_signal("login", created_at=expiry_time + timedelta(hours=1))

        db.query = MagicMock(return_value=MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=client)))))

        result = fsm.evaluate_state(client.id, [signal], "expired")
        assert result == "reactivated"

    def test_at_risk_on_inactivity(self, db):
        """Marks at_risk when no signals in 72h+."""
        fsm = LifecycleFSM(db)
        client = _make_client(created_at=datetime.now(TZ) - timedelta(days=5))

        # Signal 80 hours ago (exceeds 72h threshold)
        old_signal = _make_signal("login", created_at=datetime.now(TZ) - timedelta(hours=80))

        db.query = MagicMock(return_value=MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=client)))))

        result = fsm.evaluate_state(client.id, [old_signal], "engaged")
        assert result == "at_risk"

    def test_at_risk_on_negative_signals(self, db):
        """Marks at_risk when >3 negative signals."""
        fsm = LifecycleFSM(db)
        client = _make_client(created_at=datetime.now(TZ) - timedelta(days=5))

        signals = [
            _make_signal("no_activity_72h", "negative"),
            _make_signal("bounced_email", "negative"),
            _make_signal("multiple_short_sessions", "negative"),
            _make_signal("onboarding_abandoned", "negative"),
        ]

        db.query = MagicMock(return_value=MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=client)))))

        result = fsm.evaluate_state(client.id, signals, "activated")
        assert result == "at_risk"

    def test_trial_started_to_onboarding_started(self, db):
        """Onboarding wizard opened triggers transition."""
        fsm = LifecycleFSM(db)
        client = _make_client(created_at=datetime.now(TZ) - timedelta(days=1))

        signals = [_make_signal("onboarding_wizard_opened", "engagement")]

        db.query = MagicMock(return_value=MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=client)))))

        result = fsm.evaluate_state(client.id, signals, "trial_started")
        assert result == "onboarding_started"

    def test_onboarding_started_to_activated(self, db):
        """Onboarding completed with valid config transitions to activated."""
        fsm = LifecycleFSM(db)
        client = _make_client(
            created_at=datetime.now(TZ) - timedelta(days=2),
            keywords={"high": ["test"]},
            onboarding_completed_at=datetime.now(TZ),
        )

        signals = [
            _make_signal("onboarding_wizard_opened", "engagement"),
            _make_signal("onboarding_completed", "engagement"),
        ]

        db.query = MagicMock(return_value=MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=client)))))

        result = fsm.evaluate_state(client.id, signals, "onboarding_started")
        assert result == "activated"

    def test_activated_to_engaged(self, db):
        """3+ value_realization signals transitions to engaged."""
        fsm = LifecycleFSM(db)
        client = _make_client(
            created_at=datetime.now(TZ) - timedelta(days=3),
            keywords={"high": ["test"]},
            onboarding_completed_at=datetime.now(TZ),
        )

        signals = [
            _make_signal("onboarding_completed", "engagement"),
            _make_signal("report_viewed", "value_realization"),
            _make_signal("discovery_run", "value_realization"),
            _make_signal("landscape_report", "value_realization"),
        ]

        db.query = MagicMock(return_value=MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=client)))))

        result = fsm.evaluate_state(client.id, signals, "activated")
        assert result == "engaged"

    def test_engaged_to_high_intent(self, db):
        """Any conversion signal transitions to high_intent."""
        fsm = LifecycleFSM(db)
        client = _make_client(
            created_at=datetime.now(TZ) - timedelta(days=5),
            keywords={"high": ["test"]},
            onboarding_completed_at=datetime.now(TZ),
        )

        signals = [
            _make_signal("report_viewed", "value_realization"),
            _make_signal("discovery_run", "value_realization"),
            _make_signal("landscape_report", "value_realization"),
            _make_signal("pricing_viewed", "conversion"),
        ]

        db.query = MagicMock(return_value=MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=client)))))

        result = fsm.evaluate_state(client.id, signals, "engaged")
        assert result == "high_intent"

    def test_at_risk_recovery_to_engaged(self, db):
        """Client recovers from at_risk to engaged with positive signals."""
        fsm = LifecycleFSM(db)
        client = _make_client(
            created_at=datetime.now(TZ) - timedelta(days=5),
            keywords={"high": ["test"]},
            onboarding_completed_at=datetime.now(TZ),
        )

        # Recent positive signals + old negatives (>3 negatives but recent activity)
        signals = [
            _make_signal("no_activity_72h", "negative"),
            _make_signal("bounced_email", "negative"),
            _make_signal("multiple_short_sessions", "negative"),
            _make_signal("onboarding_abandoned", "negative"),
            _make_signal("report_viewed", "value_realization"),
            _make_signal("discovery_run", "value_realization"),
            _make_signal("landscape_report", "value_realization"),
        ]

        db.query = MagicMock(return_value=MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=client)))))

        # When at_risk but has 3+ value signals and recent activity
        # Note: at_risk condition also triggers due to >3 negatives,
        # but since current is already at_risk and qualified state is engaged, recovery happens
        result = fsm.evaluate_state(client.id, signals, "at_risk")
        assert result == "engaged"

    def test_forward_skip_no_backward(self, db):
        """State never goes backward (FORWARD-SKIP rule)."""
        fsm = LifecycleFSM(db)
        client = _make_client(
            created_at=datetime.now(TZ) - timedelta(days=5),
            keywords={"high": ["test"]},
            onboarding_completed_at=datetime.now(TZ),
        )

        # Only onboarding signals (would qualify for onboarding_started)
        signals = [_make_signal("onboarding_wizard_opened", "engagement")]

        db.query = MagicMock(return_value=MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=client)))))

        # Current state is engaged (higher rank) -- should NOT go backward
        result = fsm.evaluate_state(client.id, signals, "engaged")
        assert result == "engaged"

    def test_no_signals_stays_trial_started(self, db):
        """No signals keeps trial_started."""
        fsm = LifecycleFSM(db)
        client = _make_client(created_at=datetime.now(TZ) - timedelta(hours=1))

        db.query = MagicMock(return_value=MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=client)))))

        result = fsm.evaluate_state(client.id, [], "trial_started")
        assert result == "trial_started"

    def test_client_not_found_returns_current_state(self, db):
        """If client not found, returns current state unchanged."""
        fsm = LifecycleFSM(db)
        db.query = MagicMock(return_value=MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))))

        result = fsm.evaluate_state(uuid.uuid4(), [], "engaged")
        assert result == "engaged"


class TestActivityEventEmission:
    """Task 5.5: ActivityEvent emitted on every state transition."""

    def test_transition_emits_activity_event(self, db):
        """Valid transition emits an ActivityEvent with correct data."""
        fsm = LifecycleFSM(db)
        client = _make_client(created_at=datetime.now(TZ) - timedelta(days=1))

        signals = [_make_signal("onboarding_wizard_opened", "engagement")]

        db.query = MagicMock(return_value=MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=client)))))
        db.add = MagicMock()
        db.flush = MagicMock()

        result = fsm.evaluate_state(client.id, signals, "trial_started")
        assert result == "onboarding_started"

        # Verify db.add was called with an ActivityEvent
        db.add.assert_called_once()
        event = db.add.call_args[0][0]
        assert isinstance(event, ActivityEvent)
        assert event.event_type == "trial_lifecycle_change"
        assert event.client_id == client.id
        assert "trial_started" in event.message
        assert "onboarding_started" in event.message
        assert event.event_metadata["from_state"] == "trial_started"
        assert event.event_metadata["to_state"] == "onboarding_started"

    def test_no_transition_no_event(self, db):
        """When state doesn't change, no ActivityEvent is emitted."""
        fsm = LifecycleFSM(db)
        client = _make_client(created_at=datetime.now(TZ) - timedelta(hours=1))

        db.query = MagicMock(return_value=MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=client)))))
        db.add = MagicMock()

        result = fsm.evaluate_state(client.id, [], "trial_started")
        assert result == "trial_started"
        db.add.assert_not_called()

    def test_invalid_transition_no_event(self, db):
        """Invalid transitions are silently ignored (no event emitted)."""
        mock_db = MagicMock()
        fsm = LifecycleFSM(mock_db)
        # Test _attempt_transition directly with an invalid transition
        result = fsm._attempt_transition(
            uuid.uuid4(),
            TrialLifecycleState.trial_started,
            TrialLifecycleState.high_intent,  # not a valid direct transition
        )
        assert result is False
        mock_db.add.assert_not_called()

    def test_converted_transition_emits_event(self, db):
        """Conversion emits event."""
        fsm = LifecycleFSM(db)
        client = _make_client(plan_type="starter", created_at=datetime.now(TZ) - timedelta(days=5))

        db.query = MagicMock(return_value=MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=client)))))
        db.add = MagicMock()
        db.flush = MagicMock()

        # high_intent -> converted is a valid transition
        result = fsm.evaluate_state(client.id, [], "high_intent")
        assert result == "converted"

        db.add.assert_called_once()
        event = db.add.call_args[0][0]
        assert event.event_metadata["to_state"] == "converted"
