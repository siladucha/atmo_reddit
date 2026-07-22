"""Tests for Stripe configuration layer (DB-managed system_settings).

Validates that:
- BillingService.is_configured() reads from DB settings
- get_setting returns the stripe keys correctly
- Missing DB values → is_configured() returns False
- App starts successfully without Stripe keys in DB
- Stripe keys are seeded from env via seed_from_env()
"""

import os
from unittest.mock import patch, MagicMock

import pytest

from app.database import SessionLocal


@pytest.fixture
def db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


class TestStripeDBConfiguration:
    """Tests for Stripe keys stored in system_settings DB table."""

    def test_billing_service_not_configured_when_keys_empty(self, db):
        """BillingService.is_configured() returns False when DB keys are empty."""
        from app.services.billing import BillingService
        from app.services.settings import set_setting

        # Ensure keys are empty in DB
        set_setting(db, "stripe_secret_key", "")
        set_setting(db, "stripe_webhook_secret", "")
        set_setting(db, "stripe_publishable_key", "")

        svc = BillingService(db)
        assert svc.is_configured() is False

    def test_billing_service_not_configured_when_partial_keys(self, db):
        """BillingService.is_configured() returns False when only some keys are set."""
        from app.services.billing import BillingService
        from app.services.settings import set_setting

        # Only secret key set
        set_setting(db, "stripe_secret_key", "sk_test_abc")
        set_setting(db, "stripe_webhook_secret", "")
        set_setting(db, "stripe_publishable_key", "")

        svc = BillingService(db)
        assert svc.is_configured() is False

        # Missing publishable key
        set_setting(db, "stripe_webhook_secret", "whsec_test")
        assert svc.is_configured() is False

    def test_billing_service_configured_when_all_keys_present(self, db):
        """BillingService.is_configured() returns True when all 3 keys are in DB."""
        from app.services.billing import BillingService
        from app.services.settings import set_setting, invalidate_cache

        set_setting(db, "stripe_secret_key", "sk_test_abc123")
        set_setting(db, "stripe_webhook_secret", "whsec_test456")
        set_setting(db, "stripe_publishable_key", "pk_test_xyz789")
        invalidate_cache()

        svc = BillingService(db)
        assert svc.is_configured() is True

    def test_get_setting_returns_stripe_keys(self, db):
        """get_setting reads stripe keys from system_settings table."""
        from app.services.settings import get_setting, set_setting, invalidate_cache

        set_setting(db, "stripe_secret_key", "sk_test_readback")
        invalidate_cache()

        result = get_setting(db, "stripe_secret_key")
        assert result == "sk_test_readback"

    def test_stripe_keys_not_in_bootstrap_keys(self):
        """Stripe keys are NOT in _BOOTSTRAP_KEYS (they come from DB, not env)."""
        from app.config import _BOOTSTRAP_KEYS

        assert "stripe_secret_key" not in _BOOTSTRAP_KEYS
        assert "stripe_webhook_secret" not in _BOOTSTRAP_KEYS
        assert "stripe_publishable_key" not in _BOOTSTRAP_KEYS

    def test_stripe_keys_in_defaults(self):
        """Stripe keys are registered in DEFAULTS for init_defaults/seed_from_env."""
        from app.services.settings import DEFAULTS

        assert "stripe_secret_key" in DEFAULTS
        assert DEFAULTS["stripe_secret_key"]["group"] == "billing"
        assert DEFAULTS["stripe_secret_key"]["secret"] is True

        assert "stripe_webhook_secret" in DEFAULTS
        assert DEFAULTS["stripe_webhook_secret"]["group"] == "billing"
        assert DEFAULTS["stripe_webhook_secret"]["secret"] is True

        assert "stripe_publishable_key" in DEFAULTS
        assert DEFAULTS["stripe_publishable_key"]["group"] == "billing"
        assert DEFAULTS["stripe_publishable_key"]["secret"] is True

    def test_stripe_keys_in_seed_from_env_mapping(self):
        """Stripe keys are in the _ENV_MAP inside seed_from_env for initial seeding."""
        # We verify by checking that seed_from_env references these env vars
        import inspect
        from app.services.settings import seed_from_env

        source = inspect.getsource(seed_from_env)
        assert '"stripe_secret_key": "STRIPE_SECRET_KEY"' in source
        assert '"stripe_webhook_secret": "STRIPE_WEBHOOK_SECRET"' in source
        assert '"stripe_publishable_key": "STRIPE_PUBLISHABLE_KEY"' in source

    def test_app_starts_without_stripe_keys(self):
        """App module imports successfully without Stripe keys in DB."""
        from app.main import app
        assert app is not None

    def test_stripe_dependency_importable(self):
        """stripe package is installed and importable."""
        import stripe
        assert hasattr(stripe, "api_key")

    def test_billing_service_get_stripe_client_sets_api_key(self, db):
        """_get_stripe_client() reads secret key from DB and sets stripe.api_key."""
        from app.services.billing import BillingService
        from app.services.settings import set_setting, invalidate_cache
        import stripe

        set_setting(db, "stripe_secret_key", "sk_test_fromdb")
        invalidate_cache()

        svc = BillingService(db)
        client = svc._get_stripe_client()
        assert client.api_key == "sk_test_fromdb"

    def test_get_config_for_stripe_keys_reads_from_db(self, db):
        """get_config() for stripe keys reads from DB (not bootstrap env)."""
        from app.config import get_config
        from app.services.settings import set_setting, invalidate_cache

        set_setting(db, "stripe_secret_key", "sk_test_viaconfig")
        invalidate_cache()

        result = get_config("stripe_secret_key", db=db)
        assert result == "sk_test_viaconfig"
