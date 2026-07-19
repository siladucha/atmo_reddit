"""Tests for client portal navigation redesign (Tzvi UX spec Jul 2026).

Covers:
- Sidebar has exactly 6 nav items (no Extension as top-level)
- "Run Pipeline" and "Rebuild EPG" buttons removed from EPG page
- "Avatars" renamed to "Voices" in client-facing copy
- Onboarding progress bar shows when setup < 100%
- Help panel button exists (not a link)
- Voice upsell panel present on avatars page
- Settings page includes Integrations link
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
        "client_name": f"NavTest-{uuid.uuid4().hex[:6]}",
        "brand_name": f"Brand-{uuid.uuid4().hex[:6]}",
        "is_active": True,
        "plan_type": "starter",
        "current_onboarding_step": 3,  # Partially complete
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
        email=f"navtest-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        full_name="Nav Test User",
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
    """Create a TestClient authenticated as the given user."""

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
# Tests: Sidebar Navigation
# ---------------------------------------------------------------------------


class TestSidebarNavigation:
    """Sidebar should have 6 items, no Extension as top-level."""

    def test_sidebar_has_six_nav_items(self, db):
        """Sidebar renders with the correct 6 nav labels."""
        client_obj = _make_client(db)
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            resp = tc.get(f"/clients/{client_obj.id}/home")
            assert resp.status_code == 200
            html = resp.text
            # Required nav items present
            assert ">Overview</span>" in html
            assert ">Daily queue</span>" in html
            assert ">Voices</span>" in html
            assert ">Insights</span>" in html
            assert ">AI visibility</span>" in html
            assert ">Settings</span>" in html
            # Extension should NOT be a top-level nav item
            assert "sidebar-nav-item" in html
            # Extension link should not appear between divider and Settings
            # (it was removed as nav item #6)
        finally:
            app.dependency_overrides.clear()

    def test_no_extension_nav_item(self, db):
        """Extension should not appear as a standalone sidebar nav item."""
        client_obj = _make_client(db)
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            resp = tc.get(f"/clients/{client_obj.id}/home")
            html = resp.text
            # There should be no nav item with "Extension" as label
            # The old pattern was: <span ...>Extension</span> inside a sidebar-nav-item link
            assert ">Extension</span>" not in html or "Settings" in html
            # Chrome Extension CTA widget should also be gone
            assert "Chrome Extension" not in html
            assert "Auto-posting setup" not in html
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: Avatars → Voices rename
# ---------------------------------------------------------------------------


class TestVoicesRename:
    """Client-facing pages must use 'Voices' not 'Avatars'."""

    def test_avatars_page_title_says_voices(self, db):
        """Avatars page title should say Voices."""
        client_obj = _make_client(db)
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            resp = tc.get(f"/clients/{client_obj.id}/avatars")
            assert resp.status_code == 200
            html = resp.text
            assert "Voices" in html
            # Should NOT have "Avatars" as a visible heading
            assert ">Avatars<" not in html
        finally:
            app.dependency_overrides.clear()

    def test_home_page_uses_voices_not_avatars(self, db):
        """Home page should reference 'voices' in visible text."""
        client_obj = _make_client(db)
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            resp = tc.get(f"/clients/{client_obj.id}/home")
            html = resp.text
            assert "voice" in html.lower()
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: EPG page — ops buttons removed
# ---------------------------------------------------------------------------


class TestEPGOpsButtonsRemoved:
    """Run Pipeline and Rebuild EPG buttons must not appear in client EPG page."""

    def test_no_run_pipeline_button(self, db):
        """EPG page should not have 'Run Pipeline' button."""
        client_obj = _make_client(db)
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            resp = tc.get(f"/clients/{client_obj.id}/epg")
            assert resp.status_code == 200
            html = resp.text
            assert "Run Pipeline" not in html
            assert "Rebuild EPG" not in html
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: Onboarding Progress Bar
# ---------------------------------------------------------------------------


class TestOnboardingProgressBar:
    """Progress bar shows in sidebar when onboarding < 100%."""

    def test_progress_bar_shows_when_incomplete(self, db):
        """Sidebar shows onboarding progress when step < 6."""
        client_obj = _make_client(db, current_onboarding_step=3)
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            resp = tc.get(f"/clients/{client_obj.id}/home")
            html = resp.text
            assert "Setup progress" in html
            assert "Continue setup" in html
        finally:
            app.dependency_overrides.clear()

    def test_progress_bar_hidden_when_complete(self, db):
        """Sidebar hides onboarding progress when all steps done."""
        from datetime import datetime, timezone
        client_obj = _make_client(
            db,
            current_onboarding_step=6,
            onboarding_completed_at=datetime.now(timezone.utc),
        )
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            resp = tc.get(f"/clients/{client_obj.id}/home")
            html = resp.text
            assert "Setup progress" not in html
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: Help Panel
# ---------------------------------------------------------------------------


class TestHelpPanel:
    """Help button opens a slide-in panel, not a link."""

    def test_help_button_is_button_not_link(self, db):
        """The '?' in topbar should be a button, not an <a> link."""
        client_obj = _make_client(db)
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            resp = tc.get(f"/clients/{client_obj.id}/home")
            html = resp.text
            assert 'id="help-btn"' in html
            assert 'id="help-panel"' in html
            assert "Help and support" in html
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: Voice Upsell Panel
# ---------------------------------------------------------------------------


class TestVoiceUpsell:
    """Voice upsell panel on avatars page."""

    def test_upsell_panel_html_present(self, db):
        """Avatars page should have upsell panel markup."""
        client_obj = _make_client(db, plan_type="starter")
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            resp = tc.get(f"/clients/{client_obj.id}/avatars")
            html = resp.text
            assert "voice-upsell-panel" in html
            assert "Standard voice" in html
            assert "Silver voice" in html
            assert "Gold voice" in html
            assert "Talk to sales" in html
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: Settings page structure
# ---------------------------------------------------------------------------


class TestSettingsPage:
    """Settings page should include Integrations link."""

    def test_settings_has_integrations_link(self, db):
        """Settings page should link to Extension (Integrations)."""
        client_obj = _make_client(db)
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            resp = tc.get(f"/clients/{client_obj.id}/settings")
            assert resp.status_code == 200
            html = resp.text
            assert "Integrations" in html
            assert "Chrome Extension setup" in html
            assert "Users and Access" in html
        finally:
            app.dependency_overrides.clear()
