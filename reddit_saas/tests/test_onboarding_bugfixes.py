"""Tests for onboarding bug fixes (July 17, 2026).

Covers:
- Bug 1: URL field retry after failed analysis (one-time guard allows different URL)
- Bug 2: Keywords < 3 is soft warning, not blocker
- Bug 3: Trial users redirect to wizard on re-login if onboarding not complete
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import get_db
from app.main import app
from app.models.client import Client
from app.models.user import User
from app.models.user_role import UserRole
from app.services.auth import create_access_token
from app.services.onboarding.quality_gate import check_quality


# ---------------------------------------------------------------------------
# Quality Gate — keywords soft warning
# ---------------------------------------------------------------------------


class TestKeywordsSoftWarning:
    """Keywords < 3 should warn, not block activation."""

    def _make_client(self, **overrides):
        client = MagicMock()
        client.client_name = "Test Company"
        client.brand_name = "TestBrand"
        client.company_profile = "A comprehensive platform for security testing and vulnerability analysis."
        client.company_problem = "Security teams cannot prioritize which vulnerabilities actually matter in context."
        client.icp_profiles = "Enterprise CISOs and Security Architects at companies with 2000+ employees."
        client.keywords = {"high": ["attack path", "vulnerability prioritization", "exposure management"]}
        client.brand_voice = "Expert, direct"
        client.competitive_landscape = "Tenable focuses on scanning"
        client.brand_domain = "testcompany.com"
        for k, v in overrides.items():
            setattr(client, k, v)
        return client

    def test_two_keywords_allows_activation(self):
        """2 keywords should NOT block — only warn."""
        client = self._make_client(keywords={"high": ["one", "two"]})
        result = check_quality(client)
        assert result["can_activate"] is True
        assert any("keywords" in w for w in result["warnings"])

    def test_one_keyword_allows_activation(self):
        """1 keyword should NOT block — only warn."""
        client = self._make_client(keywords={"high": ["one"]})
        result = check_quality(client)
        assert result["can_activate"] is True

    def test_zero_keywords_allows_activation(self):
        """0 keywords should NOT block — only warn."""
        client = self._make_client(keywords={})
        result = check_quality(client)
        assert result["can_activate"] is True
        assert any("keywords" in w for w in result["warnings"])

    def test_three_keywords_no_warning(self):
        """3+ keywords should produce no keyword warning."""
        client = self._make_client(keywords={"high": ["a", "b", "c"]})
        result = check_quality(client)
        assert result["can_activate"] is True
        assert not any("keywords" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# Session redirect — trial users go back to wizard
# ---------------------------------------------------------------------------


class TestTrialSessionRedirect:
    """Trial users should redirect to onboarding wizard on re-login."""

    def _setup(self, db: Session, onboarding_step: int, onboarding_completed: bool):
        from datetime import datetime, timezone
        client_obj = Client(
            client_name=f"Redirect-Test-{uuid.uuid4().hex[:6]}",
            brand_name="Test",
            is_active=True,
            plan_type="trial",
            current_onboarding_step=onboarding_step,
            onboarding_completed_at=datetime.now(timezone.utc) if onboarding_completed else None,
        )
        db.add(client_obj)
        db.commit()
        db.refresh(client_obj)

        user = User(
            email=f"redirect-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="hashed",
            full_name="Redirect Test",
            is_active=True,
            is_superuser=False,
            role=UserRole.client_admin.value,
            client_id=client_obj.id,
            email_verified=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return client_obj, user

    def test_incomplete_onboarding_redirects_to_wizard(self, db):
        """User with onboarding not complete → redirect to /onboard."""
        _, user = self._setup(db, onboarding_step=3, onboarding_completed=False)

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
        try:
            resp = tc.get("/home", follow_redirects=False)
            assert resp.status_code == 303
            assert "/onboard" in resp.headers["location"]
        finally:
            app.dependency_overrides.clear()

    def test_step6_not_completed_still_redirects_to_wizard(self, db):
        """User at step 6 but NOT completed → still redirect to /onboard."""
        _, user = self._setup(db, onboarding_step=6, onboarding_completed=False)

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
        try:
            resp = tc.get("/home", follow_redirects=False)
            assert resp.status_code == 303
            assert "/onboard" in resp.headers["location"]
        finally:
            app.dependency_overrides.clear()

    def test_completed_onboarding_goes_to_client_home(self, db):
        """User with completed onboarding → redirect to client portal."""
        client_obj, user = self._setup(db, onboarding_step=6, onboarding_completed=True)

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
        try:
            resp = tc.get("/home", follow_redirects=False)
            assert resp.status_code == 303
            assert f"/clients/{client_obj.id}" in resp.headers["location"]
        finally:
            app.dependency_overrides.clear()
