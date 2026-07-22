"""Tests for AccessGate — subscription-aware platform access control."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.services.access_gate import AccessGate, TRIAL_DURATION_DAYS


def _make_client(
    subscription_status="active",
    plan_type="starter",
    created_at=None,
    subscription_canceled_at=None,
):
    """Helper to create a mock Client with required billing fields."""
    client = MagicMock()
    client.subscription_status = subscription_status
    client.plan_type = plan_type
    client.created_at = created_at or datetime.now(timezone.utc)
    client.subscription_canceled_at = subscription_canceled_at
    return client


class TestCanExecutePipeline:
    """Test pipeline access gating."""

    def test_active_allows_pipeline(self):
        client = _make_client(subscription_status="active")
        assert AccessGate.can_execute_pipeline(client) is True

    def test_trialing_allows_pipeline(self):
        client = _make_client(subscription_status="trialing")
        assert AccessGate.can_execute_pipeline(client) is True

    def test_past_due_blocks_pipeline(self):
        client = _make_client(subscription_status="past_due")
        assert AccessGate.can_execute_pipeline(client) is False

    def test_canceled_blocks_pipeline(self):
        client = _make_client(subscription_status="canceled")
        assert AccessGate.can_execute_pipeline(client) is False

    def test_trial_expired_blocks_pipeline(self):
        client = _make_client(subscription_status="trial_expired")
        assert AccessGate.can_execute_pipeline(client) is False

    def test_legacy_trial_not_expired_allows_pipeline(self):
        """Legacy trial (no Stripe) within 14 days allows pipeline."""
        client = _make_client(
            subscription_status="trial",
            created_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        assert AccessGate.can_execute_pipeline(client) is True

    def test_legacy_trial_expired_blocks_pipeline(self):
        """Legacy trial (no Stripe) past 14 days blocks pipeline."""
        client = _make_client(
            subscription_status="trial",
            created_at=datetime.now(timezone.utc) - timedelta(days=15),
        )
        assert AccessGate.can_execute_pipeline(client) is False

    def test_none_status_treated_as_trial(self):
        """If subscription_status is None, treat as 'trial'."""
        client = _make_client(subscription_status=None)
        client.created_at = datetime.now(timezone.utc) - timedelta(days=5)
        assert AccessGate.can_execute_pipeline(client) is True


class TestCanAccessPortal:
    """Test portal access gating."""

    def test_active_allows_portal(self):
        client = _make_client(subscription_status="active")
        assert AccessGate.can_access_portal(client) is True

    def test_trialing_allows_portal(self):
        client = _make_client(subscription_status="trialing")
        assert AccessGate.can_access_portal(client) is True

    def test_past_due_allows_portal(self):
        client = _make_client(subscription_status="past_due")
        assert AccessGate.can_access_portal(client) is True

    def test_canceled_allows_portal(self):
        client = _make_client(subscription_status="canceled")
        assert AccessGate.can_access_portal(client) is True

    def test_trial_expired_within_grace_allows_portal(self):
        """trial_expired within 30 days grace still allows portal."""
        client = _make_client(
            subscription_status="trial_expired",
            subscription_canceled_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        assert AccessGate.can_access_portal(client) is True

    def test_trial_expired_past_grace_blocks_portal(self):
        """trial_expired past 30 days blocks portal."""
        client = _make_client(
            subscription_status="trial_expired",
            subscription_canceled_at=datetime.now(timezone.utc) - timedelta(days=35),
        )
        assert AccessGate.can_access_portal(client) is False

    def test_trial_expired_no_canceled_at_allows_portal(self):
        """Safety: trial_expired with no subscription_canceled_at allows portal."""
        client = _make_client(
            subscription_status="trial_expired",
            subscription_canceled_at=None,
        )
        assert AccessGate.can_access_portal(client) is True


class TestIsReadOnly:
    """Test read-only grace period detection."""

    def test_active_not_read_only(self):
        client = _make_client(subscription_status="active")
        assert AccessGate.is_read_only(client) is False

    def test_trialing_not_read_only(self):
        client = _make_client(subscription_status="trialing")
        assert AccessGate.is_read_only(client) is False

    def test_past_due_within_grace_is_read_only(self):
        client = _make_client(
            subscription_status="past_due",
            subscription_canceled_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        assert AccessGate.is_read_only(client) is True

    def test_canceled_within_grace_is_read_only(self):
        client = _make_client(
            subscription_status="canceled",
            subscription_canceled_at=datetime.now(timezone.utc) - timedelta(days=20),
        )
        assert AccessGate.is_read_only(client) is True

    def test_canceled_past_grace_not_read_only(self):
        """Past 30-day grace, is_read_only is False (portal blocked entirely)."""
        client = _make_client(
            subscription_status="canceled",
            subscription_canceled_at=datetime.now(timezone.utc) - timedelta(days=35),
        )
        assert AccessGate.is_read_only(client) is False

    def test_past_due_no_canceled_at_is_read_only(self):
        """Safety: past_due with no subscription_canceled_at still counts as read-only."""
        client = _make_client(
            subscription_status="past_due",
            subscription_canceled_at=None,
        )
        assert AccessGate.is_read_only(client) is True


class TestCheckTrialExpiry:
    """Test legacy trial expiry check."""

    def test_non_trial_returns_false(self):
        """Non-trial clients are not affected."""
        client = _make_client(subscription_status="active")
        assert AccessGate.check_trial_expiry(client) is False

    def test_trial_not_expired_returns_false(self):
        """Trial within 14 days is not expired."""
        client = _make_client(
            subscription_status="trial",
            created_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        assert AccessGate.check_trial_expiry(client) is False
        assert client.subscription_status == "trial"

    def test_trial_expired_sets_status_and_returns_true(self):
        """Trial past 14 days sets trial_expired and returns True."""
        client = _make_client(
            subscription_status="trial",
            created_at=datetime.now(timezone.utc) - timedelta(days=15),
        )
        assert AccessGate.check_trial_expiry(client) is True
        assert client.subscription_status == "trial_expired"

    def test_already_trial_expired_returns_true(self):
        """If already trial_expired, returns True without re-checking."""
        client = _make_client(subscription_status="trial_expired")
        assert AccessGate.check_trial_expiry(client) is True

    def test_trialing_stripe_not_affected(self):
        """Stripe 'trialing' is not legacy trial — not affected."""
        client = _make_client(subscription_status="trialing")
        assert AccessGate.check_trial_expiry(client) is False

    def test_trial_boundary_day_14_not_expired(self):
        """Exactly 14 days is NOT expired (> not >=)."""
        client = _make_client(
            subscription_status="trial",
            created_at=datetime.now(timezone.utc) - timedelta(days=14),
        )
        assert AccessGate.check_trial_expiry(client) is False
        assert client.subscription_status == "trial"

    def test_trial_no_created_at_not_expired(self):
        """If created_at is None, treat as not expired (safety)."""
        client = _make_client(subscription_status="trial")
        client.created_at = None
        assert AccessGate.check_trial_expiry(client) is False


class TestConstants:
    """Test class constants are correctly defined."""

    def test_pipeline_blocked_statuses(self):
        assert AccessGate.PIPELINE_BLOCKED == {"past_due", "canceled", "trial_expired"}

    def test_full_access_statuses(self):
        assert AccessGate.FULL_ACCESS == {"active", "trialing"}

    def test_read_only_grace_statuses(self):
        assert AccessGate.READ_ONLY_GRACE == {"past_due", "canceled"}

    def test_grace_period_days(self):
        assert AccessGate.GRACE_PERIOD_DAYS == 30
