"""Grace Period Manager — handles payment failure degradation lifecycle.

Lifecycle:
    active → past_due (payment_failed) → grace period starts
    → grace period expires → suspended (pipeline stops)
    → payment recovered → active (grace cleared)

Grace period logic:
- Default: 7 days from first payment failure
- Repeat offender (previous grace within 60 days): 5 days
- During grace: pipeline continues, client sees warning banner
- After grace expires: status → suspended, pipeline stops

Called by:
- check_grace_periods (Celery Beat task, daily) — checks expirations
- stripe_service._handle_payment_failed — starts grace
- stripe_service._handle_invoice_paid — clears grace on recovery
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.client import Client
from app.models.client_subscription import ClientSubscription
from app.services.billing.state_machine import BillingStateMachine, BillingEvent

logger = get_logger(__name__)


class GracePeriodManager:
    """Manages grace period lifecycle for past_due subscriptions."""

    def check_expired_grace_periods(self, db: Session) -> list[dict]:
        """Find subscriptions where grace period has expired and suspend them.

        Returns list of suspended client_ids with details.
        """
        now = datetime.now(timezone.utc)

        # Find all past_due subscriptions with grace_period_start set
        past_due_subs = (
            db.query(ClientSubscription)
            .filter(
                ClientSubscription.status == "past_due",
                ClientSubscription.grace_period_start.isnot(None),
            )
            .all()
        )

        suspended = []
        for sub in past_due_subs:
            grace_end = sub.grace_period_start + timedelta(days=sub.grace_period_days)
            if now >= grace_end:
                # Grace period expired → suspend
                result = self._suspend_client(db, sub)
                if result:
                    suspended.append(result)

        if suspended:
            db.flush()
            logger.info(
                "GRACE_PERIOD_EXPIRED | suspended=%d clients | ids=%s",
                len(suspended),
                [s["client_id"] for s in suspended],
            )

        return suspended

    def _suspend_client(self, db: Session, subscription: ClientSubscription) -> dict | None:
        """Transition a client from past_due → suspended after grace expiry."""
        client_id = subscription.client_id

        fsm = BillingStateMachine()
        billing_event = BillingEvent(
            event_id=f"grace_expired_{client_id}_{datetime.now(timezone.utc).isoformat()}",
            event_type="grace_period_expired",
            stripe_timestamp=datetime.now(timezone.utc),
            payload={
                "grace_started": subscription.grace_period_start.isoformat() if subscription.grace_period_start else None,
                "grace_days": subscription.grace_period_days,
            },
        )

        result = fsm.transition(db, client_id, "suspended", billing_event)

        if result.success:
            # Record that grace ended (for repeat offender detection)
            subscription.previous_grace_ended_at = datetime.now(timezone.utc)
            subscription.grace_period_start = None

            # Deactivate client (stops pipeline)
            client = db.query(Client).filter(Client.id == client_id).first()
            if client:
                client.is_active = False

            logger.info(
                "GRACE_PERIOD_SUSPEND | client_id=%s | grace_days=%d | now suspended",
                client_id, subscription.grace_period_days,
            )

            return {
                "client_id": str(client_id),
                "grace_days": subscription.grace_period_days,
                "from_state": result.from_state,
                "to_state": result.to_state,
            }

        logger.warning(
            "GRACE_PERIOD_SUSPEND_FAILED | client_id=%s | reason=%s",
            client_id, result.skipped_reason,
        )
        return None

    def get_grace_status(self, db: Session, client_id: UUID) -> dict | None:
        """Get grace period status for a client. Returns None if no active grace."""
        subscription = (
            db.query(ClientSubscription)
            .filter(ClientSubscription.client_id == client_id)
            .first()
        )
        if not subscription or not subscription.grace_period_start:
            return None

        now = datetime.now(timezone.utc)
        grace_end = subscription.grace_period_start + timedelta(days=subscription.grace_period_days)
        days_remaining = max(0, (grace_end - now).days)

        return {
            "status": subscription.status,
            "grace_started": subscription.grace_period_start,
            "grace_days_total": subscription.grace_period_days,
            "days_remaining": days_remaining,
            "expires_at": grace_end,
            "is_expired": now >= grace_end,
        }

    def clear_grace_period(self, db: Session, client_id: UUID) -> None:
        """Clear grace period (called on payment recovery)."""
        subscription = (
            db.query(ClientSubscription)
            .filter(ClientSubscription.client_id == client_id)
            .first()
        )
        if subscription and subscription.grace_period_start:
            subscription.previous_grace_ended_at = datetime.now(timezone.utc)
            subscription.grace_period_start = None
            logger.info("GRACE_PERIOD_CLEARED | client_id=%s", client_id)
