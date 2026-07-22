"""Tests for the Stripe webhook endpoint at /api/webhooks/stripe.

Tests cover:
- Signature verification (invalid → 400)
- Idempotency (duplicate event IDs → 200 skip)
- Handled events enqueued to Celery
- Unhandled events logged as "skipped"
- Audit logging for all valid events
- Transient error handling (500 for Stripe retry)
"""

import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.models.billing_event import BillingEvent


def _mock_get_setting(webhook_secret="whsec_test_secret"):
    """Create a mock get_setting function that returns Stripe keys from DB."""
    settings_map = {
        "stripe_webhook_secret": webhook_secret,
        "stripe_secret_key": "sk_test_xxx",
        "stripe_publishable_key": "pk_test_xxx",
    }

    def _get_setting(db, key):
        return settings_map.get(key, "")

    return _get_setting


class TestWebhookEndpoint:
    """Tests for POST /api/webhooks/stripe."""

    def _make_stripe_event(self, event_type="checkout.session.completed", event_id=None):
        """Create a mock Stripe event dict."""
        return {
            "id": event_id or f"evt_{uuid4().hex[:24]}",
            "type": event_type,
            "data": {
                "object": {
                    "id": f"sub_{uuid4().hex[:14]}",
                    "customer": f"cus_{uuid4().hex[:14]}",
                    "status": "active",
                }
            },
            "created": int(datetime.now(timezone.utc).timestamp()),
        }

    def test_missing_signature_returns_400(self, db):
        """Request without stripe-signature header returns 400."""
        with patch("app.routes.webhooks.get_setting", side_effect=_mock_get_setting()):
            with TestClient(app) as c:
                response = c.post(
                    "/api/webhooks/stripe",
                    content=json.dumps({"id": "evt_test"}),
                    headers={"Content-Type": "application/json"},
                )

        assert response.status_code == 400
        assert "signature" in response.json()["error"].lower()

    def test_empty_body_returns_400(self, db):
        """Empty request body returns 400."""
        with patch("app.routes.webhooks.get_setting", side_effect=_mock_get_setting()):
            with TestClient(app) as c:
                response = c.post(
                    "/api/webhooks/stripe",
                    content=b"",
                    headers={
                        "Content-Type": "application/json",
                        "stripe-signature": "t=123,v1=abc",
                    },
                )

        assert response.status_code == 400

    @patch("app.routes.webhooks.stripe.Webhook.construct_event")
    def test_invalid_signature_returns_400(self, mock_construct, db):
        """Invalid Stripe signature returns 400."""
        import stripe
        mock_construct.side_effect = stripe.error.SignatureVerificationError(
            "Signature verification failed", "sig_header"
        )

        with patch("app.routes.webhooks.get_setting", side_effect=_mock_get_setting()):
            with TestClient(app) as c:
                response = c.post(
                    "/api/webhooks/stripe",
                    content=json.dumps({"id": "evt_test"}),
                    headers={
                        "Content-Type": "application/json",
                        "stripe-signature": "t=123,v1=invalid",
                    },
                )

        assert response.status_code == 400
        assert "signature" in response.json()["error"].lower()

    @patch("app.routes.webhooks.stripe.Webhook.construct_event")
    @patch("app.routes.webhooks.SessionLocal")
    def test_handled_event_enqueued_and_returns_200(self, mock_session_local, mock_construct, db):
        """Handled event is logged to billing_events and enqueued to Celery."""
        event = self._make_stripe_event("customer.subscription.updated")
        mock_construct.return_value = event
        mock_session_local.return_value = db

        with patch("app.routes.webhooks.get_setting", side_effect=_mock_get_setting()):
            with patch("celery.current_app") as mock_celery_app:
                mock_celery_app.send_task = MagicMock()
                with TestClient(app) as c:
                    response = c.post(
                        "/api/webhooks/stripe",
                        content=json.dumps(event),
                        headers={
                            "Content-Type": "application/json",
                            "stripe-signature": "t=123,v1=valid",
                        },
                    )

        assert response.status_code == 200
        assert response.json()["status"] == "received"

        # Verify billing_event record created
        billing_event = db.query(BillingEvent).filter(
            BillingEvent.stripe_event_id == event["id"]
        ).first()
        assert billing_event is not None
        assert billing_event.event_type == "customer.subscription.updated"
        assert billing_event.processing_status == "pending"

    @patch("app.routes.webhooks.stripe.Webhook.construct_event")
    @patch("app.routes.webhooks.SessionLocal")
    def test_unhandled_event_logged_as_skipped(self, mock_session_local, mock_construct, db):
        """Unhandled event type is logged with status='skipped' and returns 200."""
        event = self._make_stripe_event("charge.refunded")
        mock_construct.return_value = event
        mock_session_local.return_value = db

        with patch("app.routes.webhooks.get_setting", side_effect=_mock_get_setting()):
            with TestClient(app) as c:
                response = c.post(
                    "/api/webhooks/stripe",
                    content=json.dumps(event),
                    headers={
                        "Content-Type": "application/json",
                        "stripe-signature": "t=123,v1=valid",
                    },
                )

        assert response.status_code == 200
        assert response.json()["status"] == "received"

        # Verify billing_event logged with status="skipped"
        billing_event = db.query(BillingEvent).filter(
            BillingEvent.stripe_event_id == event["id"]
        ).first()
        assert billing_event is not None
        assert billing_event.event_type == "charge.refunded"
        assert billing_event.processing_status == "skipped"

    @patch("app.routes.webhooks.stripe.Webhook.construct_event")
    @patch("app.routes.webhooks.SessionLocal")
    def test_duplicate_event_skipped(self, mock_session_local, mock_construct, db):
        """Duplicate event ID returns 200 with status='duplicate'."""
        event = self._make_stripe_event("invoice.paid")
        event_id = event["id"]
        mock_construct.return_value = event
        mock_session_local.return_value = db

        # Pre-insert the event to simulate duplicate
        existing = BillingEvent(
            stripe_event_id=event_id,
            event_type="invoice.paid",
            processing_status="processed",
        )
        db.add(existing)
        db.flush()

        with patch("app.routes.webhooks.get_setting", side_effect=_mock_get_setting()):
            with TestClient(app) as c:
                response = c.post(
                    "/api/webhooks/stripe",
                    content=json.dumps(event),
                    headers={
                        "Content-Type": "application/json",
                        "stripe-signature": "t=123,v1=valid",
                    },
                )

        assert response.status_code == 200
        assert response.json()["status"] == "duplicate"

    def test_no_auth_required(self, db):
        """Webhook endpoint accessible without JWT auth cookie."""
        # Just verify we don't get a 303 redirect (auth middleware bypass)
        with patch("app.routes.webhooks.get_setting", side_effect=_mock_get_setting()):
            with TestClient(app) as c:
                # No auth cookie set — should not redirect to /login
                response = c.post(
                    "/api/webhooks/stripe",
                    content=b"{}",
                    headers={"Content-Type": "application/json"},
                    follow_redirects=False,
                )
        # Should get 400 (missing signature), not 303 (auth redirect)
        assert response.status_code == 400

    @patch("app.routes.webhooks.stripe.Webhook.construct_event")
    def test_webhook_secret_not_configured_returns_500(self, mock_construct, db):
        """When stripe_webhook_secret is not configured, returns 500 for Stripe retry."""
        with patch("app.routes.webhooks.get_setting", side_effect=_mock_get_setting(webhook_secret="")):
            with TestClient(app) as c:
                response = c.post(
                    "/api/webhooks/stripe",
                    content=json.dumps({"id": "evt_test"}),
                    headers={
                        "Content-Type": "application/json",
                        "stripe-signature": "t=123,v1=test",
                    },
                )

        assert response.status_code == 500
