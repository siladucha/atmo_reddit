"""Trial Lifecycle State Machine.

Finite state machine managing trial lifecycle transitions.
Emits ActivityEvent on every state transition.

Subtasks implemented:
  5.1 LifecycleFSM class
  5.2 VALID_TRANSITIONS map for 9 states
  5.3 evaluate_state(client_id, signals, current_state)
  5.4 All transition rules per design
  5.5 ActivityEvent emission on every state transition
"""

import logging
import uuid
from datetime import datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.activity_event import ActivityEvent
from app.models.client import Client
from app.models.trial_signal import TrialSignal

logger = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Jerusalem")
TRIAL_DURATION_DAYS = 14
INACTIVITY_THRESHOLD_HOURS = 72
NEGATIVE_SIGNAL_THRESHOLD = 3

# Minimum value_realization signals to transition activated -> engaged
ENGAGED_SIGNAL_COUNT = 3

# Signal types that indicate high intent (conversion signals)
HIGH_INTENT_SIGNAL_TYPES: set[str] = {
    "pricing_page_viewed",
    "pricing_viewed",
    "upgrade_screen_opened",
    "upgrade_cta_clicked",
    "support_contacted",
}

# Signal types that count toward value_realization for engaged transition
VALUE_REALIZATION_SIGNAL_TYPES: set[str] = {
    "report_viewed",
    "discovery_run",
    "landscape_report",
    "opportunity_report",
    "high_intent_discovered",
    "strategic_insights",
    "keywords_configured",
    "subreddits_configured",
}

# Signal type for onboarding completed
ONBOARDING_COMPLETED_TYPE = "onboarding_completed"

# Signal types that indicate onboarding wizard was opened/started
ONBOARDING_STARTED_SIGNAL_TYPES: set[str] = {
    "onboarding_step_1",
    "onboarding_step_2",
    "onboarding_step_3",
    "onboarding_step_4",
    "onboarding_step_5",
    "onboarding_step_6",
    "onboarding_started",
    "onboarding_wizard_opened",
}


class TrialLifecycleState(StrEnum):
    trial_started = "trial_started"
    onboarding_started = "onboarding_started"
    activated = "activated"
    engaged = "engaged"
    high_intent = "high_intent"
    at_risk = "at_risk"
    expired = "expired"
    converted = "converted"
    reactivated = "reactivated"


# --------------------------------------------------------------------------
# 5.2 -- Valid state transitions map (from design doc)
# --------------------------------------------------------------------------

VALID_TRANSITIONS: dict[TrialLifecycleState, set[TrialLifecycleState]] = {
    TrialLifecycleState.trial_started: {
        TrialLifecycleState.onboarding_started,
        TrialLifecycleState.at_risk,
        TrialLifecycleState.expired,
    },
    TrialLifecycleState.onboarding_started: {
        TrialLifecycleState.activated,
        TrialLifecycleState.at_risk,
        TrialLifecycleState.expired,
    },
    TrialLifecycleState.activated: {
        TrialLifecycleState.engaged,
        TrialLifecycleState.at_risk,
        TrialLifecycleState.expired,
    },
    TrialLifecycleState.engaged: {
        TrialLifecycleState.high_intent,
        TrialLifecycleState.at_risk,
        TrialLifecycleState.expired,
    },
    TrialLifecycleState.high_intent: {
        TrialLifecycleState.converted,
        TrialLifecycleState.at_risk,
        TrialLifecycleState.expired,
    },
    TrialLifecycleState.at_risk: {
        TrialLifecycleState.engaged,        # re-engagement
        TrialLifecycleState.high_intent,    # sudden intent signal
        TrialLifecycleState.expired,
        TrialLifecycleState.converted,
    },
    TrialLifecycleState.expired: {
        TrialLifecycleState.reactivated,
        TrialLifecycleState.converted,      # late conversion
    },
    TrialLifecycleState.converted: set(),   # terminal -- no transitions out
    TrialLifecycleState.reactivated: {
        TrialLifecycleState.engaged,
        TrialLifecycleState.high_intent,
        TrialLifecycleState.converted,
        TrialLifecycleState.expired,
    },
}

# Forward progression order (for FORWARD-SKIP rule)
FORWARD_PROGRESSION: list[TrialLifecycleState] = [
    TrialLifecycleState.trial_started,
    TrialLifecycleState.onboarding_started,
    TrialLifecycleState.activated,
    TrialLifecycleState.engaged,
    TrialLifecycleState.high_intent,
    TrialLifecycleState.converted,
]


def _state_rank(state: TrialLifecycleState) -> int:
    """Return numeric rank for forward progression comparison."""
    try:
        return FORWARD_PROGRESSION.index(state)
    except ValueError:
        return -1


# --------------------------------------------------------------------------
# Helper functions
# --------------------------------------------------------------------------


def get_last_signal_time(signals: list[TrialSignal]) -> datetime | None:
    """Return the most recent signal timestamp."""
    if not signals:
        return None
    return max(s.created_at for s in signals)


def count_negative_signals(signals: list[TrialSignal]) -> int:
    """Count signals with category='negative'."""
    return sum(1 for s in signals if s.signal_category == "negative")


def count_value_realization_signals(signals: list[TrialSignal]) -> int:
    """Count signals qualifying as value_realization for the engaged transition."""
    return sum(
        1 for s in signals
        if s.signal_type in VALUE_REALIZATION_SIGNAL_TYPES
        or s.signal_category == "value_realization"
    )


def has_signal_type(signals: list[TrialSignal], signal_type: str) -> bool:
    """Check if any signal matches the given type."""
    return any(s.signal_type == signal_type for s in signals)


def has_any_conversion_signal(signals: list[TrialSignal]) -> bool:
    """Check if any signal is a conversion/high-intent type."""
    return any(s.signal_type in HIGH_INTENT_SIGNAL_TYPES for s in signals)


def has_onboarding_started(signals: list[TrialSignal]) -> bool:
    """Check if any onboarding step signal exists."""
    return any(s.signal_type in ONBOARDING_STARTED_SIGNAL_TYPES for s in signals)


# --------------------------------------------------------------------------
# 5.1 -- Lifecycle FSM Class
# --------------------------------------------------------------------------


class LifecycleFSM:
    """Trial lifecycle state machine.

    Manages state transitions for trial accounts based on signals and client data.
    Emits ActivityEvent (event_type="trial_lifecycle_change") on every state transition.
    """

    def __init__(self, db: Session):
        self.db = db

    # --------------------------------------------------------------------------
    # 5.3 -- evaluate_state(client_id, signals, current_state)
    # --------------------------------------------------------------------------

    def evaluate_state(
        self,
        client_id: uuid.UUID,
        signals: list[TrialSignal],
        current_state: str,
    ) -> str:
        """Evaluate the lifecycle state based on signals and client data.

        Applies transition rules per design and FORWARD-SKIP rule.

        Priority order (highest first):
            1. converted -- if client.plan_type != "trial"
            2. expired -- if 14 days elapsed since client.created_at
            3. reactivated -- if currently expired and new activity after expiry
            4. at_risk -- if no signals in 72h+ OR >3 negative signals
            5. high_intent -- if any conversion category signal present
            6. engaged -- if 3+ value_realization signals (meaningful usage)
            7. activated -- if onboarding_completed signal exists
            8. onboarding_started -- if onboarding wizard opened
            9. trial_started -- default (signup)

        Args:
            client_id: UUID of the trial client.
            signals: All trial signals for the client.
            current_state: Current lifecycle state string.

        Returns:
            New lifecycle state string. Same as current_state if no transition.
        """
        now = datetime.now(TZ)
        current = TrialLifecycleState(current_state) if current_state else TrialLifecycleState.trial_started

        # Load client for plan_type and created_at
        client = self.db.query(Client).filter(Client.id == client_id).first()
        if not client:
            logger.warning("Client %s not found for lifecycle evaluation", client_id)
            return current.value

        # --- Terminal state guard ---
        if current == TrialLifecycleState.converted:
            return current.value

        # --- Priority 1: converted (plan_type changed from "trial") ---
        if client.plan_type and client.plan_type != "trial":
            new_state = TrialLifecycleState.converted
            self._attempt_transition(client_id, current, new_state)
            return new_state.value

        # --- Priority 2: expired (days_elapsed > 14) ---
        days_elapsed = self._days_elapsed(client, now)
        if days_elapsed > TRIAL_DURATION_DAYS:
            # Priority 3: Check for reactivation
            if current == TrialLifecycleState.expired:
                expiry_time = self._get_expiry_time(client)
                signals_after_expiry = [s for s in signals if s.created_at > expiry_time]
                if signals_after_expiry:
                    new_state = TrialLifecycleState.reactivated
                    self._attempt_transition(client_id, current, new_state)
                    return new_state.value
                return current.value

            # Not yet marked expired -> transition to expired
            new_state = TrialLifecycleState.expired
            self._attempt_transition(client_id, current, new_state)
            return new_state.value

        # --- Priority 4: at_risk ---
        is_at_risk = self._check_at_risk(signals, now)

        # --- Determine highest qualifying engagement state ---
        qualified_state = self._determine_highest_engagement(signals, client)

        # --- Apply at_risk logic ---
        if is_at_risk:
            # If recovering from at_risk (new positive signals), move to highest qualifying
            if current == TrialLifecycleState.at_risk and qualified_state != TrialLifecycleState.trial_started:
                new_state = qualified_state
                self._attempt_transition(client_id, current, new_state)
                return new_state.value

            # Mark at_risk if not already
            if current != TrialLifecycleState.at_risk:
                new_state = TrialLifecycleState.at_risk
                self._attempt_transition(client_id, current, new_state)
                return new_state.value

            return current.value

        # --- Apply FORWARD-SKIP rule ---
        new_state = self._apply_forward_skip(current, qualified_state)

        if new_state != current:
            self._attempt_transition(client_id, current, new_state)

        return new_state.value

    # --------------------------------------------------------------------------
    # 5.5 -- Emit ActivityEvent on every state transition
    # --------------------------------------------------------------------------

    def _attempt_transition(
        self,
        client_id: uuid.UUID,
        from_state: TrialLifecycleState,
        to_state: TrialLifecycleState,
    ) -> bool:
        """Attempt a state transition, validating against VALID_TRANSITIONS.

        If valid: emits ActivityEvent and returns True.
        If invalid: logs at debug level and returns False (silently ignored).

        Args:
            client_id: UUID of the trial client.
            from_state: Current state.
            to_state: Target state.

        Returns:
            True if transition was valid and event emitted, False otherwise.
        """
        if from_state == to_state:
            return False

        # Validate transition against VALID_TRANSITIONS map
        valid_targets = VALID_TRANSITIONS.get(from_state, set())
        if to_state not in valid_targets:
            logger.debug(
                "Invalid lifecycle transition for client %s: %s -> %s (not in valid targets: %s)",
                client_id,
                from_state.value,
                to_state.value,
                [s.value for s in valid_targets],
            )
            return False

        # Emit ActivityEvent for valid transition
        self._emit_transition_event(client_id, from_state, to_state)

        logger.info(
            "Trial lifecycle transition for client %s: %s -> %s",
            client_id,
            from_state.value,
            to_state.value,
        )
        return True

    def _emit_transition_event(
        self,
        client_id: uuid.UUID,
        from_state: TrialLifecycleState,
        to_state: TrialLifecycleState,
    ) -> None:
        """Emit an ActivityEvent recording a state transition.

        event_type = "trial_lifecycle_change"
        """
        event = ActivityEvent(
            client_id=client_id,
            event_type="trial_lifecycle_change",
            message=f"Trial lifecycle: {from_state.value} -> {to_state.value}",
            event_metadata={
                "from_state": from_state.value,
                "to_state": to_state.value,
            },
        )
        self.db.add(event)
        try:
            self.db.flush()
        except Exception:
            logger.exception(
                "Failed to emit lifecycle transition event for client %s", client_id
            )

    # --------------------------------------------------------------------------
    # 5.4 -- Transition rule helpers
    # --------------------------------------------------------------------------

    def _determine_highest_engagement(
        self,
        signals: list[TrialSignal],
        client: Client,
    ) -> TrialLifecycleState:
        """Determine the highest qualifying engagement state from signals.

        Transition rules (checked from highest to lowest):
            - high_intent: any conversion category signal present
            - engaged: 3+ value_realization signals (meaningful usage)
            - activated: onboarding_completed signal AND valid config
            - onboarding_started: onboarding wizard opened
            - trial_started: default
        """
        # Check high_intent: any conversion category signal
        if has_any_conversion_signal(signals):
            return TrialLifecycleState.high_intent

        # Check engaged: 3+ value_realization signals
        vr_count = count_value_realization_signals(signals)
        if vr_count >= ENGAGED_SIGNAL_COUNT:
            return TrialLifecycleState.engaged

        # Check activated: onboarding_completed AND valid config
        if has_signal_type(signals, ONBOARDING_COMPLETED_TYPE) and self._is_client_config_valid(client):
            return TrialLifecycleState.activated

        # Check onboarding_started: onboarding wizard opened
        if has_onboarding_started(signals):
            return TrialLifecycleState.onboarding_started

        # Default
        return TrialLifecycleState.trial_started

    def _check_at_risk(self, signals: list[TrialSignal], now: datetime) -> bool:
        """Check if client should be at_risk.

        At risk if:
            - No signals in 72h+ (no_activity_72h)
            - OR >3 negative signals dominate
        """
        # Check inactivity
        last_signal_time = get_last_signal_time(signals)
        if last_signal_time is not None:
            signal_time = last_signal_time
            if signal_time.tzinfo is None:
                signal_time = signal_time.replace(tzinfo=TZ)
            time_since_last = now - signal_time
            if time_since_last > timedelta(hours=INACTIVITY_THRESHOLD_HOURS):
                return True
        elif not signals:
            # No signals at all -- don't mark at_risk for brand new trial
            return False

        # Check negative signal dominance (>3 negatives)
        negative_count = count_negative_signals(signals)
        if negative_count > NEGATIVE_SIGNAL_THRESHOLD:
            return True

        return False

    def _is_client_config_valid(self, client: Client) -> bool:
        """Check if client config is valid (minimum setup complete).

        Valid means:
            - Has keywords configured (non-empty)
            - Has onboarding_completed_at set
        """
        has_keywords = bool(client.keywords)
        has_onboarding = client.onboarding_completed_at is not None
        return has_keywords and has_onboarding

    def _apply_forward_skip(
        self,
        current: TrialLifecycleState,
        qualified: TrialLifecycleState,
    ) -> TrialLifecycleState:
        """Apply the FORWARD-SKIP rule: never go backward.

        Returns the higher of current and qualified states.
        For at_risk or reactivated, allows moving to qualified state.
        """
        current_rank = _state_rank(current)
        qualified_rank = _state_rank(qualified)

        # If current is at_risk or reactivated, allow moving to qualified
        if current in (TrialLifecycleState.at_risk, TrialLifecycleState.reactivated):
            return qualified

        # Forward-skip: only move forward
        if qualified_rank > current_rank:
            return qualified

        return current

    def _days_elapsed(self, client: Client, now: datetime) -> int:
        """Calculate days elapsed since client creation."""
        if not client.created_at:
            return 0
        created = client.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=TZ)
        if now.tzinfo is None:
            now = now.replace(tzinfo=TZ)
        return (now - created).days

    def _get_expiry_time(self, client: Client) -> datetime:
        """Get the datetime when the trial expired (created_at + 14 days)."""
        created = client.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=TZ)
        return created + timedelta(days=TRIAL_DURATION_DAYS)
