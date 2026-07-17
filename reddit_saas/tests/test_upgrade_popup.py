"""Tests for upgrade pricing popup and billing page.

Covers:
- Pricing popup HTML present on client pages (trial clients)
- Billing page does NOT contain hello@gorampit.com
- Billing page contains "see available plans" button
- Upgrade button triggers popup (showPricing function present)
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import get_db
from app.main import app
from app.models.client import Client
from app.models.user import User
from app.models.user_role import UserRole
from app.services.auth import create_access_token


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_client(db: Session, **kwargs) -> Client:
    defaults = {
        "client_name": f"Popup-Test-{uuid.uuid4().hex[:6]}",
        "brand_name": f"Brand-{uuid.uuid4().hex[:6]}",
        "is_active": True,
        "plan_type": "trial",
        "keywords": {"high": ["test"], "medium": [], "low": []},
    }
    defaults.update(kwargs)
    c = Client(**defaults)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_user(db: Session, role: UserRole, client_id=None) -> User:
    user = User(
        email=f"popup-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        full_name="Popup Test User",
        is_active=True,
        is_superuser=role == UserRole.owner,
        role=role.value,
        client_id=client_id,
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _authenticated_client(db: Session, user: User) -> TestClient:
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    token = create_access_token(data={
        "sub": str(user.id),
        "email": user.email,
        "role": user.user_role.value,
        "is_superuser": user.is_superuser,
    })
    tc = TestClient(app)
    tc.cookies.set("access_token", token)
    return tc


# ---------------------------------------------------------------------------
# Tests: Pricing popup on client pages
# ---------------------------------------------------------------------------


class TestPricingPopup:
    """Test pricing popup is present and functional."""

    def test_pricing_popup_html_present_on_client_home(self, db):
        """Client home page includes pricing popup HTML."""
        client_obj = _make_client(db)
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            resp = tc.get(f"/clients/{client_obj.id}/home", follow_redirects=True)
            assert resp.status_code == 200
            assert "pricing-popup" in resp.text
            assert "showPricing" in resp.text
        finally:
            app.dependency_overrides.clear()

    def test_pricing_popup_contains_all_plans(self, db):
        """Popup shows all 4 plan tiers."""
        client_obj = _make_client(db)
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            resp = tc.get(f"/clients/{client_obj.id}/home", follow_redirects=True)
            assert resp.status_code == 200
            assert "$149" in resp.text
            assert "$399" in resp.text
            assert "$799" in resp.text
            assert "$1,499" in resp.text
        finally:
            app.dependency_overrides.clear()

    def test_upgrade_button_calls_show_pricing(self, db):
        """Trial banner Upgrade button triggers showPricing()."""
        client_obj = _make_client(db, plan_type="trial")
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            resp = tc.get(f"/clients/{client_obj.id}/home", follow_redirects=True)
            assert resp.status_code == 200
            assert 'onclick="showPricing()"' in resp.text
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: Billing page
# ---------------------------------------------------------------------------


class TestBillingPage:
    """Test billing page upgrade section."""

    def test_billing_no_hello_gorampit(self, db):
        """Billing page must NOT contain hello@gorampit.com."""
        client_obj = _make_client(db, plan_type="starter")
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            resp = tc.get(f"/clients/{client_obj.id}/billing", follow_redirects=True)
            assert resp.status_code == 200
            assert "hello@gorampit.com" not in resp.text
        finally:
            app.dependency_overrides.clear()

    def test_billing_has_see_plans_button(self, db):
        """Billing page has 'see available plans' button."""
        client_obj = _make_client(db, plan_type="starter")
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            resp = tc.get(f"/clients/{client_obj.id}/billing", follow_redirects=True)
            assert resp.status_code == 200
            assert "see available plans" in resp.text
        finally:
            app.dependency_overrides.clear()

    def test_billing_popup_links_to_tzvi_email(self, db):
        """Plan buttons in popup link to tzvi@gorampit.com."""
        client_obj = _make_client(db)
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            resp = tc.get(f"/clients/{client_obj.id}/billing", follow_redirects=True)
            assert resp.status_code == 200
            assert "tzvi@gorampit.com" in resp.text
        finally:
            app.dependency_overrides.clear()
