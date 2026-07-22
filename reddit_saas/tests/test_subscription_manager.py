"""Tests for SubscriptionManager — webhook event processing.

Validates:
- _resolve_client_from_event finds client by stripe_customer_id
- _map_plan_from_price maps price IDs to plan tiers
- handle_subscription_updated syncs status, plan, billing period
- handle_subscription_deleted cancels subscription
- handle_invoice_paid restores past_due to active and caches invoice
- handle_invoice_payment_failed sets past_due
- handle_trial_will_end emits activity event
- handle_checkout_completed stores Stripe IDs
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.client_invoice import ClientInvoice
from app.models.activity_event import ActivityEvent
from app.services.subscription_manager import SubscriptionManager


@pytest.fixture
def client_with_stripe(db: Session):
    """Create a test client with stripe_customer_id."""
    client = Client(
        id=uuid.uuid4(),
        client_name="Test Corp",
        brand_name="TestBrand",
        stripe_customer_id="cus_test123",
        stripe_subscription_id="sub_test456",
        subscription_status="active",
        plan_type="starter",
        max_avatars=3,
        is_active=True,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


class TestResolveClientFromEvent:
    """Tests for _resolve_client_from_event."""

    def test_resolves_from_object_customer(self, db: Session, client_with_stripe):
        """Finds client when customer ID is in event_data.object.customer."""
        mgr = SubscriptionManager(db)
        event_data = {"object": {"customer": "cus_test123"}}
        result = mgr._resolve_client_from_event(event_data)
        assert result is not None
        assert result.id == client_with_stripe.id

    def test_resolves_from_top_level_customer(self, db: Session, client_with_stripe):
        """Finds client when customer ID is at top level."""
        mgr = SubscriptionManager(db)
        event_data = {"customer": "cus_test123", "subscription": "sub_abc"}
        result = mgr._resolve_client_from_event(event_data)
        assert result is not None
        assert result.id == client_with_stripe.id

    def test_returns_none_for_unknown_customer(self, db: Session, client_with_stripe):
        """Returns None when customer ID doesn't match any client."""
        mgr = SubscriptionManager(db)
        event_data = {"object": {"customer": "cus_unknown"}}
        result = mgr._resolve_client_from_event(event_data)
        assert result is None

    def test_returns_none_for_missing_customer(self, db: Session):
        """Returns None when no customer ID in event data."""
        mgr = SubscriptionManager(db)
        event_data = {"object": {"status": "active"}}
        result = mgr._resolve_client_from_event(event_data)
        assert result is None


class TestMapPlanFromPrice:
    """Tests for _map_plan_from_price."""

    @patch("app.services.subscription_manager.get_setting")
    def test_maps_seed_price(self, mock_get_setting, db: Session):
        """Maps seed price ID correctly."""
        def side_effect(db_arg, key):
            if key == "stripe_price_id_seed":
                return "price_seed_123"
            return ""

        mock_get_setting.side_effect = side_effect
        mgr = SubscriptionManager(db)
        plan, avatars = mgr._map_plan_from_price("price_seed_123")
        assert plan == "seed"
        assert avatars == 1

    @patch("app.services.subscription_manager.get_setting")
    def test_maps_growth_price(self, mock_get_setting, db: Session):
        """Maps growth price ID correctly."""
        def side_effect(db_arg, key):
            if key == "stripe_price_id_growth":
                return "price_growth_789"
            return ""

        mock_get_setting.side_effect = side_effect
        mgr = SubscriptionManager(db)
        plan, avatars = mgr._map_plan_from_price("price_growth_789")
        assert plan == "growth"
        assert avatars == 7

    @patch("app.services.subscription_manager.get_setting")
    def test_maps_scale_price(self, mock_get_setting, db: Session):
        """Maps scale price ID correctly."""
        def side_effect(db_arg, key):
            if key == "stripe_price_id_scale":
                return "price_scale_999"
            return ""

        mock_get_setting.side_effect = side_effect
        mgr = SubscriptionManager(db)
        plan, avatars = mgr._map_plan_from_price("price_scale_999")
        assert plan == "scale"
        assert avatars == 15

    @patch("app.services.subscription_manager.get_setting")
    def test_defaults_to_starter_for_unknown(self, mock_get_setting, db: Session):
        """Returns starter defaults when price ID not found."""
        mock_get_setting.return_value = ""
        mgr = SubscriptionManager(db)
        plan, avatars = mgr._map_plan_from_price("price_unknown")
        assert plan == "starter"
        assert avatars == 3


class TestHandleSubscriptionUpdated:
    """Tests for handle_subscription_updated."""

    @patch("app.services.subscription_manager.get_setting")
    def test_updates_status_to_active(self, mock_get_setting, db: Session, client_with_stripe):
        """Sets subscription_status=active from Stripe active status."""
        mock_get_setting.return_value = ""
        client_with_stripe.subscription_status = "trialing"
        db.commit()

        mgr = SubscriptionManager(db)
        event_data = {
            "object": {
                "customer": "cus_test123",
                "status": "active",
                "items": {"data": [{"price": {"id": "price_starter_x"}}]},
                "current_period_start": 1700000000,
                "current_period_end": 1702592000,
            }
        }
        mgr.handle_subscription_updated(event_data)

        db.refresh(client_with_stripe)
        assert client_with_stripe.subscription_status == "active"
        assert client_with_stripe.is_active is True
        assert client_with_stripe.billing_period_start is not None
        assert client_with_stripe.billing_period_end is not None

    @patch("app.services.subscription_manager.get_setting")
    def test_updates_status_to_past_due(self, mock_get_setting, db: Session, client_with_stripe):
        """Sets subscription_status=past_due from Stripe past_due status."""
        mock_get_setting.return_value = ""
        mgr = SubscriptionManager(db)
        event_data = {
            "object": {
                "customer": "cus_test123",
                "status": "past_due",
                "items": {"data": []},
                "current_period_start": 1700000000,
                "current_period_end": 1702592000,
            }
        }
        mgr.handle_subscription_updated(event_data)

        db.refresh(client_with_stripe)
        assert client_with_stripe.subscription_status == "past_due"

    @patch("app.services.subscription_manager.get_setting")
    def test_updates_plan_type_and_max_avatars(self, mock_get_setting, db: Session, client_with_stripe):
        """Updates plan_type and max_avatars from price mapping."""
        def side_effect(db_arg, key):
            if key == "stripe_price_id_growth":
                return "price_growth_abc"
            return ""

        mock_get_setting.side_effect = side_effect
        mgr = SubscriptionManager(db)
        event_data = {
            "object": {
                "customer": "cus_test123",
                "status": "active",
                "items": {"data": [{"price": {"id": "price_growth_abc"}}]},
                "current_period_start": 1700000000,
                "current_period_end": 1702592000,
            }
        }
        mgr.handle_subscription_updated(event_data)

        db.refresh(client_with_stripe)
        assert client_with_stripe.plan_type == "growth"
        assert client_with_stripe.max_avatars == 7


class TestHandleSubscriptionDeleted:
    """Tests for handle_subscription_deleted."""

    def test_sets_canceled_and_inactive(self, db: Session, client_with_stripe):
        """Sets canceled status, is_active=False, and subscription_canceled_at."""
        mgr = SubscriptionManager(db)
        event_data = {"object": {"customer": "cus_test123"}}
        mgr.handle_subscription_deleted(event_data)

        db.refresh(client_with_stripe)
        assert client_with_stripe.subscription_status == "canceled"
        assert client_with_stripe.is_active is False
        assert client_with_stripe.subscription_canceled_at is not None

    def test_emits_activity_event(self, db: Session, client_with_stripe):
        """Emits subscription_canceled activity event."""
        mgr = SubscriptionManager(db)
        event_data = {"object": {"customer": "cus_test123"}}
        mgr.handle_subscription_deleted(event_data)

        event = (
            db.query(ActivityEvent)
            .filter(ActivityEvent.client_id == client_with_stripe.id)
            .filter(ActivityEvent.event_type == "billing")
            .first()
        )
        assert event is not None
        assert "canceled" in event.message.lower()


class TestHandleInvoicePaid:
    """Tests for handle_invoice_paid."""

    def test_restores_past_due_to_active(self, db: Session, client_with_stripe):
        """Restores subscription from past_due to active when invoice paid."""
        client_with_stripe.subscription_status = "past_due"
        client_with_stripe.is_active = False
        db.commit()

        mgr = SubscriptionManager(db)
        event_data = {
            "object": {
                "id": "inv_paid_001",
                "customer": "cus_test123",
                "amount_due": 39900,
                "currency": "usd",
                "period_start": 1700000000,
                "period_end": 1702592000,
                "invoice_pdf": "https://stripe.com/invoice.pdf",
                "hosted_invoice_url": "https://stripe.com/invoice",
            }
        }
        mgr.handle_invoice_paid(event_data)

        db.refresh(client_with_stripe)
        assert client_with_stripe.subscription_status == "active"
        assert client_with_stripe.is_active is True

    def test_caches_invoice_data(self, db: Session, client_with_stripe):
        """Caches invoice record in client_invoices table."""
        mgr = SubscriptionManager(db)
        event_data = {
            "object": {
                "id": "inv_cache_001",
                "customer": "cus_test123",
                "amount_due": 14900,
                "currency": "usd",
                "period_start": 1700000000,
                "period_end": 1702592000,
                "invoice_pdf": "https://stripe.com/pdf",
                "hosted_invoice_url": "https://stripe.com/hosted",
            }
        }
        mgr.handle_invoice_paid(event_data)

        invoice = (
            db.query(ClientInvoice)
            .filter(ClientInvoice.stripe_invoice_id == "inv_cache_001")
            .first()
        )
        assert invoice is not None
        assert invoice.amount_cents == 14900
        assert invoice.currency == "usd"
        assert invoice.status == "paid"
        assert invoice.invoice_pdf_url == "https://stripe.com/pdf"

    def test_does_not_duplicate_invoice(self, db: Session, client_with_stripe):
        """Does not create duplicate invoice on re-delivery."""
        mgr = SubscriptionManager(db)
        event_data = {
            "object": {
                "id": "inv_dedup_001",
                "customer": "cus_test123",
                "amount_due": 39900,
                "currency": "usd",
                "period_start": 1700000000,
                "period_end": 1702592000,
            }
        }
        mgr.handle_invoice_paid(event_data)
        mgr.handle_invoice_paid(event_data)

        count = (
            db.query(ClientInvoice)
            .filter(ClientInvoice.stripe_invoice_id == "inv_dedup_001")
            .count()
        )
        assert count == 1


class TestHandleInvoicePaymentFailed:
    """Tests for handle_invoice_payment_failed."""

    def test_sets_past_due(self, db: Session, client_with_stripe):
        """Sets subscription_status=past_due on payment failure."""
        mgr = SubscriptionManager(db)
        event_data = {
            "object": {
                "customer": "cus_test123",
                "subscription": "sub_test456",
            }
        }
        mgr.handle_invoice_payment_failed(event_data)

        db.refresh(client_with_stripe)
        assert client_with_stripe.subscription_status == "past_due"


class TestHandleTrialWillEnd:
    """Tests for handle_trial_will_end."""

    def test_emits_trial_ending_soon_event(self, db: Session, client_with_stripe):
        """Emits trial_ending_soon activity event."""
        client_with_stripe.subscription_status = "trialing"
        db.commit()

        mgr = SubscriptionManager(db)
        event_data = {
            "object": {
                "customer": "cus_test123",
                "trial_end": 1700000000,
            }
        }
        mgr.handle_trial_will_end(event_data)

        event = (
            db.query(ActivityEvent)
            .filter(ActivityEvent.client_id == client_with_stripe.id)
            .filter(ActivityEvent.event_type == "billing")
            .first()
        )
        assert event is not None
        assert "trial" in event.message.lower()
        assert event.event_metadata["action"] == "trial_ending_soon"


class TestHandleCheckoutCompleted:
    """Tests for handle_checkout_completed."""

    def test_stores_stripe_ids_and_sets_trialing(self, db: Session):
        """Stores stripe_customer_id, stripe_subscription_id and sets trialing."""
        client = Client(
            id=uuid.uuid4(),
            client_name="New Corp",
            brand_name="NewBrand",
            subscription_status="trial",
            is_active=True,
        )
        db.add(client)
        db.commit()
        db.refresh(client)

        mgr = SubscriptionManager(db)
        event_data = {
            "object": {
                "customer": "cus_new_checkout",
                "subscription": "sub_new_checkout",
                "metadata": {"client_id": str(client.id)},
            }
        }
        mgr.handle_checkout_completed(event_data)

        db.refresh(client)
        assert client.stripe_customer_id == "cus_new_checkout"
        assert client.stripe_subscription_id == "sub_new_checkout"
        assert client.subscription_status == "trialing"

    def test_resolves_by_existing_customer_id(self, db: Session, client_with_stripe):
        """Resolves client by existing stripe_customer_id if no metadata."""
        mgr = SubscriptionManager(db)
        event_data = {
            "object": {
                "customer": "cus_test123",
                "subscription": "sub_renewed",
                "metadata": {},
            }
        }
        mgr.handle_checkout_completed(event_data)

        db.refresh(client_with_stripe)
        assert client_with_stripe.stripe_subscription_id == "sub_renewed"
        assert client_with_stripe.subscription_status == "trialing"


class TestTrialToPaidTransition:
    """Tests for trial-to-paid transition — task 11.1.

    Validates Requirements: 8.1, 8.2, 8.4
    """

    @patch("app.services.subscription_manager.get_setting")
    @patch("app.services.client_emails.send_trial_to_paid_welcome_email")
    def test_trial_to_active_sends_welcome_email(
        self, mock_welcome_email, mock_get_setting, db: Session, client_with_stripe
    ):
        """When transitioning from trialing to active, sends welcome email (Req 8.4)."""
        mock_get_setting.return_value = ""
        mock_welcome_email.return_value = True

        client_with_stripe.subscription_status = "trialing"
        db.commit()

        mgr = SubscriptionManager(db)
        event_data = {
            "object": {
                "customer": "cus_test123",
                "status": "active",
                "items": {"data": [{"price": {"id": "price_starter_x", "unit_amount": 39900}}]},
                "current_period_start": 1700000000,
                "current_period_end": 1702592000,
            }
        }
        mgr.handle_subscription_updated(event_data)

        db.refresh(client_with_stripe)
        assert client_with_stripe.subscription_status == "active"

        # Welcome email should have been called
        mock_welcome_email.assert_called_once_with(
            client_id=client_with_stripe.id,
            plan_type=client_with_stripe.plan_type,
            amount_cents=39900,
        )

    @patch("app.services.subscription_manager.get_setting")
    @patch("app.services.client_emails.send_trial_to_paid_welcome_email")
    def test_active_to_active_does_not_send_welcome_email(
        self, mock_welcome_email, mock_get_setting, db: Session, client_with_stripe
    ):
        """Welcome email is NOT sent for active→active transitions (plan change)."""
        mock_get_setting.return_value = ""

        # Already active
        client_with_stripe.subscription_status = "active"
        db.commit()

        mgr = SubscriptionManager(db)
        event_data = {
            "object": {
                "customer": "cus_test123",
                "status": "active",
                "items": {"data": [{"price": {"id": "price_growth_x", "unit_amount": 79900}}]},
                "current_period_start": 1700000000,
                "current_period_end": 1702592000,
            }
        }
        mgr.handle_subscription_updated(event_data)

        # Welcome email should NOT have been called (no status change)
        mock_welcome_email.assert_not_called()

    @patch("app.services.subscription_manager.get_setting")
    @patch("app.services.client_emails.send_trial_to_paid_welcome_email")
    def test_welcome_email_failure_does_not_break_subscription_update(
        self, mock_welcome_email, mock_get_setting, db: Session, client_with_stripe
    ):
        """Email failure doesn't break the subscription status update (fire-and-forget)."""
        mock_get_setting.return_value = ""
        mock_welcome_email.side_effect = Exception("SMTP connection failed")

        client_with_stripe.subscription_status = "trialing"
        db.commit()

        mgr = SubscriptionManager(db)
        event_data = {
            "object": {
                "customer": "cus_test123",
                "status": "active",
                "items": {"data": [{"price": {"id": "price_starter_x", "unit_amount": 14900}}]},
                "current_period_start": 1700000000,
                "current_period_end": 1702592000,
            }
        }
        # Should not raise — email failure is caught
        mgr.handle_subscription_updated(event_data)

        db.refresh(client_with_stripe)
        assert client_with_stripe.subscription_status == "active"
        assert client_with_stripe.is_active is True
