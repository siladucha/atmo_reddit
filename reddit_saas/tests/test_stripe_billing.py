"""Tests for Stripe billing integration — routes, webhook, state machine, error handling."""

import json
import time
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from uuid import uuid4

import pytest

from app.models.client import Client
from app.models.client_subscription import ClientSubscription
from app.models.plan_definition import PlanDefinition
from app.models.webhook_event import WebhookEvent
from app.services.billing.state_machine import BillingStateMachine, BillingEvent, VALID_TRANSITIONS
from app.services.billing.grace_period_manager import GracePeriodManager


# ---------------------------------------------------------------------------
# State Machine Unit Tests
# ---------------------------------------------------------------------------


class TestBillingStateMachine:
    """Tests for the deterministic FSM transitions."""

    def test_valid_transitions_map_completeness(self):
        """All states have entries in VALID_TRANSITIONS."""
        expected_states = {"trial", "trial_expired", "active", "past_due", "suspended", "canceled", "archived"}
        assert set(VALID_TRANSITIONS.keys()) == expected_states

    def test_trial_to_active(self, db):
        """Trial → active on checkout_completed."""
        client = _create_test_client(db, plan_type="trial")
        _create_test_subscription(db, client.id, status="trial")

        fsm = BillingStateMachine()
        event = BillingEvent(event_id="evt_test_1", event_type="checkout_completed")
        result = fsm.transition(db, client.id, "active", event)

        assert result.success is True
        assert result.from_state == "trial"
        assert result.to_state == "active"

    def test_active_to_past_due(self, db):
        """Active → past_due on payment_failed."""
        client = _create_test_client(db, plan_type="starter")
        _create_test_subscription(db, client.id, status="active")

        fsm = BillingStateMachine()
        event = BillingEvent(event_id="evt_test_2", event_type="payment_failed")
        result = fsm.transition(db, client.id, "past_due", event)

        assert result.success is True
        assert result.from_state == "active"
        assert result.to_state == "past_due"

    def test_past_due_to_active_recovery(self, db):
        """Past_due → active on payment_recovered."""
        client = _create_test_client(db, plan_type="starter")
        _create_test_subscription(db, client.id, status="past_due")

        fsm = BillingStateMachine()
        event = BillingEvent(event_id="evt_test_3", event_type="payment_recovered")
        result = fsm.transition(db, client.id, "active", event)

        assert result.success is True
        assert result.from_state == "past_due"
        assert result.to_state == "active"

    def test_past_due_to_suspended(self, db):
        """Past_due → suspended on grace_period_expired."""
        client = _create_test_client(db, plan_type="starter")
        _create_test_subscription(db, client.id, status="past_due")

        fsm = BillingStateMachine()
        event = BillingEvent(event_id="evt_test_4", event_type="grace_period_expired")
        result = fsm.transition(db, client.id, "suspended", event)

        assert result.success is True
        assert result.to_state == "suspended"

    def test_invalid_transition_rejected(self, db):
        """Trial → suspended should be rejected (not a valid path)."""
        client = _create_test_client(db, plan_type="trial")
        _create_test_subscription(db, client.id, status="trial")

        fsm = BillingStateMachine()
        event = BillingEvent(event_id="evt_test_5", event_type="bad_event")
        result = fsm.transition(db, client.id, "suspended", event)

        assert result.success is False
        assert result.skipped_reason == "invalid_transition"

    def test_idempotency_duplicate_event(self, db):
        """Same event_id processed twice returns duplicate, no state change."""
        client = _create_test_client(db, plan_type="trial")
        _create_test_subscription(db, client.id, status="trial")

        fsm = BillingStateMachine()
        event = BillingEvent(event_id="evt_dup_1", event_type="checkout_completed")

        # First time
        result1 = fsm.transition(db, client.id, "active", event)
        db.flush()
        assert result1.success is True
        assert result1.to_state == "active"

        # Second time (same event_id)
        result2 = fsm.transition(db, client.id, "active", event)
        assert result2.success is True
        assert result2.skipped_reason == "duplicate"

    def test_no_subscription_record(self, db):
        """Transition fails gracefully when no ClientSubscription exists."""
        client = _create_test_client(db, plan_type="trial")
        # Do NOT create subscription

        fsm = BillingStateMachine()
        event = BillingEvent(event_id="evt_nosub", event_type="checkout_completed")
        result = fsm.transition(db, client.id, "active", event)

        assert result.success is False
        assert result.skipped_reason == "no_subscription_record"

    def test_archived_is_terminal(self, db):
        """Archived state has no valid transitions."""
        assert VALID_TRANSITIONS["archived"] == []


# ---------------------------------------------------------------------------
# Webhook Handler Tests
# ---------------------------------------------------------------------------


class TestWebhookHandlers:
    """Tests for stripe_service webhook event handlers."""

    def test_handle_checkout_completed(self, db):
        """checkout.session.completed updates plan, stripe IDs, and transitions state."""
        from app.services.stripe_service import _handle_checkout_completed

        client = _create_test_client(db, plan_type="trial")
        _create_test_subscription(db, client.id, status="trial")
        db.flush()

        event = {
            "data": {
                "object": {
                    "customer": "cus_test123",
                    "subscription": "sub_test456",
                    "metadata": {
                        "ramp_client_id": str(client.id),
                        "target_plan": "starter",
                    },
                }
            }
        }
        event_ts = datetime.now(timezone.utc)
        result = _handle_checkout_completed(db, event, "evt_co_1", event_ts)

        assert result["status"] == "processed"
        assert result["plan"] == "starter"

        # Verify DB state
        sub = db.query(ClientSubscription).filter_by(client_id=client.id).first()
        assert sub.stripe_customer_id == "cus_test123"
        assert sub.stripe_subscription_id == "sub_test456"
        assert sub.status == "active"

        refreshed_client = db.query(Client).filter_by(id=client.id).first()
        assert refreshed_client.plan_type == "starter"

    def test_handle_checkout_no_client_id(self, db):
        """checkout.session.completed without ramp_client_id in metadata is skipped."""
        from app.services.stripe_service import _handle_checkout_completed

        event = {
            "data": {
                "object": {
                    "customer": "cus_unknown",
                    "subscription": "sub_unknown",
                    "metadata": {},  # No ramp_client_id
                }
            }
        }
        result = _handle_checkout_completed(db, event, "evt_co_2", datetime.now(timezone.utc))
        assert result["status"] == "skipped"

    def test_handle_payment_failed(self, db):
        """invoice.payment_failed starts grace period."""
        from app.services.stripe_service import _handle_payment_failed

        client = _create_test_client(db, plan_type="starter")
        sub = _create_test_subscription(db, client.id, status="active")
        sub.stripe_subscription_id = "sub_fail_1"
        db.flush()

        event = {
            "data": {
                "object": {
                    "subscription": "sub_fail_1",
                    "id": "in_fail_1",
                    "attempt_count": 1,
                }
            }
        }
        result = _handle_payment_failed(db, event, "evt_pf_1", datetime.now(timezone.utc))

        assert result["status"] == "processed"
        assert result["grace_days"] == 7

        sub_refreshed = db.query(ClientSubscription).filter_by(client_id=client.id).first()
        assert sub_refreshed.status == "past_due"
        assert sub_refreshed.grace_period_start is not None

    def test_handle_payment_failed_already_past_due(self, db):
        """Duplicate payment_failed when already past_due is skipped."""
        from app.services.stripe_service import _handle_payment_failed

        client = _create_test_client(db, plan_type="starter")
        sub = _create_test_subscription(db, client.id, status="past_due")
        sub.stripe_subscription_id = "sub_dup_fail"
        db.flush()

        event = {"data": {"object": {"subscription": "sub_dup_fail", "id": "in_2", "attempt_count": 2}}}
        result = _handle_payment_failed(db, event, "evt_pf_dup", datetime.now(timezone.utc))

        assert result["status"] == "skipped"
        assert "already past_due" in result["reason"]

    def test_handle_invoice_paid_recovery(self, db):
        """invoice.paid when past_due recovers to active."""
        from app.services.stripe_service import _handle_invoice_paid

        client = _create_test_client(db, plan_type="starter")
        sub = _create_test_subscription(db, client.id, status="past_due")
        sub.stripe_subscription_id = "sub_recovery"
        sub.grace_period_start = datetime.now(timezone.utc)
        db.flush()

        event = {
            "data": {
                "object": {
                    "subscription": "sub_recovery",
                    "id": "in_paid_1",
                    "period_start": int(time.time()),
                    "period_end": int(time.time()) + 30 * 86400,
                }
            }
        }
        result = _handle_invoice_paid(db, event, "evt_ip_1", datetime.now(timezone.utc))

        assert result["status"] == "processed"
        assert result["recovered"] is True

        sub_refreshed = db.query(ClientSubscription).filter_by(client_id=client.id).first()
        assert sub_refreshed.status == "active"
        assert sub_refreshed.grace_period_start is None

    def test_handle_subscription_deleted(self, db):
        """customer.subscription.deleted cancels the subscription."""
        from app.services.stripe_service import _handle_subscription_deleted

        client = _create_test_client(db, plan_type="starter")
        sub = _create_test_subscription(db, client.id, status="active")
        sub.stripe_subscription_id = "sub_del_1"
        db.flush()

        event = {"data": {"object": {"id": "sub_del_1"}}}
        result = _handle_subscription_deleted(db, event, "evt_sd_1", datetime.now(timezone.utc))

        assert result["status"] == "processed"

        sub_refreshed = db.query(ClientSubscription).filter_by(client_id=client.id).first()
        assert sub_refreshed.status == "canceled"

    def test_handle_unknown_event_type(self, db):
        """Unknown event types are logged and skipped."""
        from app.services.stripe_service import handle_webhook_event

        event = {
            "id": "evt_unknown_1",
            "type": "payout.created",
            "created": int(time.time()),
            "data": {"object": {}},
        }
        result = handle_webhook_event(db, event)
        assert result["status"] == "skipped_unhandled"

    def test_idempotency_on_webhook(self, db):
        """Duplicate webhook event_id returns duplicate without reprocessing."""
        from app.services.stripe_service import handle_webhook_event

        # Pre-insert a webhook event
        existing = WebhookEvent(
            stripe_event_id="evt_already_processed",
            event_type="checkout.session.completed",
            stripe_timestamp=datetime.now(timezone.utc),
            processing_result="processed",
        )
        db.add(existing)
        db.flush()

        event = {
            "id": "evt_already_processed",
            "type": "checkout.session.completed",
            "created": int(time.time()),
            "data": {"object": {}},
        }
        result = handle_webhook_event(db, event)
        assert result["status"] == "duplicate"


# ---------------------------------------------------------------------------
# Grace Period Manager Tests
# ---------------------------------------------------------------------------


class TestGracePeriodManager:
    """Tests for grace period expiry detection and suspension."""

    def test_no_expired_grace_periods(self, db):
        """No past_due subscriptions → no suspensions."""
        mgr = GracePeriodManager()
        result = mgr.check_expired_grace_periods(db)
        assert result == []

    def test_expired_grace_suspends_client(self, db):
        """Past_due with expired grace period → suspended."""
        from datetime import timedelta

        client = _create_test_client(db, plan_type="starter")
        sub = _create_test_subscription(db, client.id, status="past_due")
        # Grace started 10 days ago, only 7 days allowed
        sub.grace_period_start = datetime.now(timezone.utc) - timedelta(days=10)
        sub.grace_period_days = 7
        db.flush()

        mgr = GracePeriodManager()
        result = mgr.check_expired_grace_periods(db)

        assert len(result) == 1
        assert result[0]["client_id"] == str(client.id)
        assert result[0]["to_state"] == "suspended"

        # Verify client deactivated
        refreshed = db.query(Client).filter_by(id=client.id).first()
        assert refreshed.is_active is False

    def test_active_grace_not_suspended(self, db):
        """Past_due with grace still active → not suspended."""
        from datetime import timedelta

        client = _create_test_client(db, plan_type="starter")
        sub = _create_test_subscription(db, client.id, status="past_due")
        # Grace started 3 days ago, 7 days allowed → 4 days remaining
        sub.grace_period_start = datetime.now(timezone.utc) - timedelta(days=3)
        sub.grace_period_days = 7
        db.flush()

        mgr = GracePeriodManager()
        result = mgr.check_expired_grace_periods(db)

        assert result == []

    def test_get_grace_status(self, db):
        """Grace status returns correct remaining days."""
        from datetime import timedelta

        client = _create_test_client(db, plan_type="starter")
        sub = _create_test_subscription(db, client.id, status="past_due")
        sub.grace_period_start = datetime.now(timezone.utc) - timedelta(days=2)
        sub.grace_period_days = 7
        db.flush()

        mgr = GracePeriodManager()
        status = mgr.get_grace_status(db, client.id)

        assert status is not None
        assert status["days_remaining"] in (4, 5)  # depends on time-of-day rounding
        assert status["is_expired"] is False


# ---------------------------------------------------------------------------
# Checkout Route Tests (integration)
# ---------------------------------------------------------------------------


class TestCheckoutRoute:
    """Tests for POST /clients/{id}/checkout error paths."""

    def test_checkout_missing_plan(self, db, admin_client):
        """Missing plan parameter → 400."""
        test_client = _create_test_client(db, plan_type="trial")
        db.commit()

        response = admin_client.post(f"/clients/{test_client.id}/checkout")
        assert response.status_code == 400

    def test_checkout_invalid_plan(self, db, admin_client):
        """Invalid plan name → 400."""
        test_client = _create_test_client(db, plan_type="trial")
        db.commit()

        response = admin_client.post(f"/clients/{test_client.id}/checkout?plan=enterprise")
        assert response.status_code == 400

    def test_checkout_nonexistent_client(self, db, admin_client):
        """Non-existent client_id → 404."""
        fake_id = str(uuid4())
        response = admin_client.post(f"/clients/{fake_id}/checkout?plan=starter")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_test_client(db, plan_type: str = "trial") -> Client:
    """Create a minimal test client."""
    client = Client(
        client_name=f"Test Client {uuid4().hex[:6]}",
        brand_name="TestBrand",
        plan_type=plan_type,
        subscription_status=plan_type if plan_type == "trial" else "active",
        is_active=True,
    )
    db.add(client)
    db.flush()
    return client


def _create_test_subscription(db, client_id, status: str = "trial") -> ClientSubscription:
    """Create a ClientSubscription record for testing."""
    sub = ClientSubscription(
        client_id=client_id,
        status=status,
        monthly_action_counter=0,
    )
    db.add(sub)
    db.flush()
    return sub
