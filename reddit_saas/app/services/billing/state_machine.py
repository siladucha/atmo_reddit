"""Billing State Machine — deterministic FSM for billing state transitions.

Pure logic. No Stripe SDK. No external API calls.
All transitions can be invoked programmatically for testing.

State transitions:
    trial → active (checkout completed)
    trial → trial_expired (14 days elapsed)
    trial_expired → active (late payment ≤90d)
    trial_expired → archived (90d no login)
    active → past_due (payment failed)
    active → canceled (subscription deleted)
    past_due → active (payment recovered)
    past_due → suspended (grace period expired)
    suspended → active (payment recovered)
    canceled → archived (period_end reached)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.client import Client
from app.models.client_subscription import ClientSubscription
from app.models.webhook_event import WebhookEvent

logger = get_logger(__name__)


@dataclass
class BillingEvent:
    """Represents a billing event that triggers a state transition."""

    event_id: str  # Stripe event ID or internal ID
    event_type: str  # checkout_completed, payment_failed, payment_recovered, etc.
    stripe_timestamp: datetime | None = None
    payload: dict = field(default_factory=dict)


@dataclass
class TransitionResult:
    """Result of a state transition attempt."""

    success: bool
    from_state: str
    to_state: str | None = None
    skipped_reason: str | None = None  # duplicate, invalid_transition, out_of_order
    side_effects: list[str] = field(default_factory=list)


# Valid state transitions map
VALID_TRANSITIONS: dict[str, list[str]] = {
    "trial": ["active", "trial_expired"],
    "trial_expired": ["active", "archived"],
    "active": ["past_due", "canceled"],
    "past_due": ["active", "suspended"],
    "suspended": ["active"],
    "canceled": ["archived"],
    "archived": [],  # terminal state
}


class BillingStateMachine:
    """Deterministic billing state transitions. No external API calls."""

    def transition(
        self,
        db: Session,
        client_id: UUID,
        to_state: str,
        event: BillingEvent,
    ) -> TransitionResult:
        """Process a billing event and transition client state.

        Idempotent: same event_id processed twice = no change.
        Invalid transitions are rejected and logged.

        Args:
            db: SQLAlchemy session
            client_id: Target client UUID
            to_state: Desired new state
            event: The billing event triggering this transition

        Returns:
            TransitionResult with success/failure and details.
        """
        # 1. Idempotency check
        if event.event_id:
            existing = (
                db.query(WebhookEvent)
                .filter(WebhookEvent.stripe_event_id == event.event_id)
                .first()
            )
            if existing:
                logger.info(
                    "BILLING_FSM_SKIP_DUPLICATE | client_id=%s | event_id=%s",
                    client_id, event.event_id,
                )
                return TransitionResult(
                    success=True,
                    from_state=existing.processing_result,
                    to_state=None,
                    skipped_reason="duplicate",
                )

        # 2. Load current state
        subscription = (
            db.query(ClientSubscription)
            .filter(ClientSubscription.client_id == client_id)
            .first()
        )
        if not subscription:
            logger.error(
                "BILLING_FSM_NO_SUBSCRIPTION | client_id=%s", client_id
            )
            return TransitionResult(
                success=False,
                from_state="unknown",
                skipped_reason="no_subscription_record",
            )

        from_state = subscription.status

        # 3. Validate transition
        valid_targets = VALID_TRANSITIONS.get(from_state, [])
        if to_state not in valid_targets:
            logger.warning(
                "BILLING_FSM_INVALID_TRANSITION | client_id=%s | from=%s | to=%s | event=%s",
                client_id, from_state, to_state, event.event_type,
            )
            return TransitionResult(
                success=False,
                from_state=from_state,
                to_state=to_state,
                skipped_reason="invalid_transition",
            )

        # 4. Execute transition
        subscription.status = to_state
        subscription.updated_at = datetime.now(timezone.utc)

        # Also update denormalized field on client
        client = db.query(Client).filter(Client.id == client_id).first()
        if client:
            client.subscription_status = to_state

        # 5. Emit activity event
        _emit_transition_event(db, client_id, from_state, to_state, event)

        # 6. Log webhook event (if has event_id)
        if event.event_id:
            webhook_log = WebhookEvent(
                stripe_event_id=event.event_id,
                event_type=event.event_type,
                client_id=client_id,
                stripe_timestamp=event.stripe_timestamp or datetime.now(timezone.utc),
                processing_result="processed",
                raw_payload=event.payload if event.payload else None,
            )
            db.add(webhook_log)

        db.flush()

        logger.info(
            "BILLING_FSM_TRANSITION | client_id=%s | %s → %s | event=%s",
            client_id, from_state, to_state, event.event_type,
        )

        return TransitionResult(
            success=True,
            from_state=from_state,
            to_state=to_state,
            side_effects=[f"status: {from_state} → {to_state}"],
        )

    def get_valid_transitions(self, current_state: str) -> list[str]:
        """Return valid target states from current state."""
        return VALID_TRANSITIONS.get(current_state, [])

    def is_valid_transition(self, from_state: str, to_state: str) -> bool:
        """Check if a transition is valid."""
        return to_state in VALID_TRANSITIONS.get(from_state, [])


def _emit_transition_event(
    db: Session,
    client_id: UUID,
    from_state: str,
    to_state: str,
    event: BillingEvent,
) -> None:
    """Emit an ActivityEvent for the state transition."""
    from app.models.activity_event import ActivityEvent

    activity = ActivityEvent(
        client_id=client_id,
        event_type="billing_state_transition",
        details={
            "from_state": from_state,
            "to_state": to_state,
            "trigger_event": event.event_type,
            "event_id": event.event_id,
        },
    )
    db.add(activity)
