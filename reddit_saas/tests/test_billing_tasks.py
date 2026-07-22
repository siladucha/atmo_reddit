"""Tests for billing Celery tasks (process_billing_event + sync_stripe_products)."""

import uuid
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from app.database import SessionLocal


@pytest.fixture
def db():
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def billing_event(db):
    """Create a test billing event in the DB."""
    from app.models.billing_event import BillingEvent

    event = BillingEvent(
        id=uuid.uuid4(),
        stripe_event_id=f"evt_test_{uuid.uuid4().hex[:12]}",
        event_type="customer.subscription.updated",
        client_id=None,
        payload={"object": {"customer": "cus_test123", "status": "active"}},
        processing_status="pending",
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


class TestProcessBillingEvent:
    """Tests for process_billing_event task."""

    def test_event_not_found_returns_error(self):
        """When billing_event_id doesn't exist, returns error status."""
        from app.tasks.billing import process_billing_event

        result = process_billing_event(
            str(uuid.uuid4()),
            "customer.subscription.updated",
            {"object": {"customer": "cus_test"}}
        )
        assert result["status"] == "error"
        assert result["reason"] == "event_not_found"

    def test_processes_subscription_updated(self, db, billing_event):
        """Routes subscription.updated to the correct handler."""
        from app.tasks.billing import process_billing_event
        from app.models.billing_event import BillingEvent

        with patch("app.services.subscription_manager.SubscriptionManager.handle_subscription_updated") as mock_handler:
            result = process_billing_event(
                str(billing_event.id),
                "customer.subscription.updated",
                {"object": {"customer": "cus_test123", "status": "active"}},
            )

        assert result["status"] == "processed"
        assert result["event_type"] == "customer.subscription.updated"
        mock_handler.assert_called_once()

        # Verify DB status updated
        db.expire_all()
        refreshed = db.query(BillingEvent).filter(BillingEvent.id == billing_event.id).first()
        assert refreshed.processing_status == "processed"
        assert refreshed.processed_at is not None

    def test_processes_subscription_deleted(self, db, billing_event):
        """Routes subscription.deleted to the correct handler."""
        from app.tasks.billing import process_billing_event

        billing_event.event_type = "customer.subscription.deleted"
        db.commit()

        with patch("app.services.subscription_manager.SubscriptionManager.handle_subscription_deleted") as mock_handler:
            result = process_billing_event(
                str(billing_event.id),
                "customer.subscription.deleted",
                {"object": {"customer": "cus_test123"}},
            )

        assert result["status"] == "processed"
        mock_handler.assert_called_once()

    def test_processes_invoice_paid(self, db, billing_event):
        """Routes invoice.paid to the correct handler."""
        from app.tasks.billing import process_billing_event

        billing_event.event_type = "invoice.paid"
        db.commit()

        with patch("app.services.subscription_manager.SubscriptionManager.handle_invoice_paid") as mock_handler:
            result = process_billing_event(
                str(billing_event.id),
                "invoice.paid",
                {"object": {"customer": "cus_test123", "id": "in_test"}},
            )

        assert result["status"] == "processed"
        mock_handler.assert_called_once()

    def test_processes_invoice_payment_failed(self, db, billing_event):
        """Routes invoice.payment_failed to the correct handler."""
        from app.tasks.billing import process_billing_event

        billing_event.event_type = "invoice.payment_failed"
        db.commit()

        with patch("app.services.subscription_manager.SubscriptionManager.handle_invoice_payment_failed") as mock_handler:
            result = process_billing_event(
                str(billing_event.id),
                "invoice.payment_failed",
                {"object": {"customer": "cus_test123"}},
            )

        assert result["status"] == "processed"
        mock_handler.assert_called_once()

    def test_processes_trial_will_end(self, db, billing_event):
        """Routes trial_will_end to the correct handler."""
        from app.tasks.billing import process_billing_event

        billing_event.event_type = "customer.subscription.trial_will_end"
        db.commit()

        with patch("app.services.subscription_manager.SubscriptionManager.handle_trial_will_end") as mock_handler:
            result = process_billing_event(
                str(billing_event.id),
                "customer.subscription.trial_will_end",
                {"object": {"customer": "cus_test123", "trial_end": 1700000000}},
            )

        assert result["status"] == "processed"
        mock_handler.assert_called_once()

    def test_processes_checkout_completed(self, db, billing_event):
        """Routes checkout.session.completed to the correct handler."""
        from app.tasks.billing import process_billing_event

        billing_event.event_type = "checkout.session.completed"
        db.commit()

        with patch("app.services.subscription_manager.SubscriptionManager.handle_checkout_completed") as mock_handler:
            result = process_billing_event(
                str(billing_event.id),
                "checkout.session.completed",
                {"object": {"customer": "cus_test123", "subscription": "sub_test"}},
            )

        assert result["status"] == "processed"
        mock_handler.assert_called_once()

    def test_unhandled_event_type_marked_skipped(self, db, billing_event):
        """Unhandled event types get marked as skipped."""
        from app.tasks.billing import process_billing_event
        from app.models.billing_event import BillingEvent

        billing_event.event_type = "customer.created"
        db.commit()

        result = process_billing_event(
            str(billing_event.id),
            "customer.created",
            {"object": {"id": "cus_test123"}},
        )

        assert result["status"] == "skipped"

        db.expire_all()
        refreshed = db.query(BillingEvent).filter(BillingEvent.id == billing_event.id).first()
        assert refreshed.processing_status == "skipped"


class TestSyncStripeProducts:
    """Tests for sync_stripe_products task."""

    def test_skips_when_not_configured(self):
        """Skips product sync when Stripe is not configured."""
        from app.tasks.billing import sync_stripe_products

        with patch("app.services.billing.BillingService.is_configured", return_value=False):
            with patch("app.services.billing.BillingService.ensure_products_exist") as mock_ensure:
                result = sync_stripe_products()

        assert result["status"] == "skipped"
        assert result["reason"] == "stripe_not_configured"
        mock_ensure.assert_not_called()

    def test_syncs_when_configured(self):
        """Calls ensure_products_exist when Stripe is configured."""
        from app.tasks.billing import sync_stripe_products

        with patch("app.services.billing.BillingService.is_configured", return_value=True):
            with patch("app.services.billing.BillingService.ensure_products_exist") as mock_ensure:
                result = sync_stripe_products()

        assert result["status"] == "synced"
        mock_ensure.assert_called_once()

    def test_handles_error_gracefully(self):
        """Returns error status on exception."""
        from app.tasks.billing import sync_stripe_products

        with patch("app.services.billing.BillingService.is_configured", return_value=True):
            with patch("app.services.billing.BillingService.ensure_products_exist", side_effect=Exception("Stripe API down")):
                result = sync_stripe_products()

        assert result["status"] == "error"
        assert "Stripe API down" in result["error"]
