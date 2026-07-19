"""Tests for client portal keyword management (add/remove via UI).

Covers:
- GET /clients/{id}/keywords renders add form for client_admin
- GET /clients/{id}/keywords hides add form for client_viewer
- POST /clients/{id}/actions/keywords/add — success, duplicate, empty
- POST /clients/{id}/actions/keywords/remove — success, nonexistent
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
        "client_name": f"KW-Test-{uuid.uuid4().hex[:6]}",
        "brand_name": f"Brand-{uuid.uuid4().hex[:6]}",
        "is_active": True,
        "keywords": {"high": ["existing keyword"], "medium": [], "low": []},
    }
    defaults.update(kwargs)
    c = Client(**defaults)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_user(db: Session, role: UserRole, client_id=None, **kwargs) -> User:
    defaults = {
        "email": f"kwtest-{uuid.uuid4().hex[:8]}@example.com",
        "hashed_password": "hashed",
        "full_name": "KW Test User",
        "is_active": True,
        "is_superuser": role == UserRole.owner,
        "role": role.value,
        "client_id": client_id,
        "email_verified": True,
    }
    defaults.update(kwargs)
    user = User(**defaults)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _authenticated_client(db: Session, user: User) -> TestClient:
    """Create a TestClient authenticated as the given user."""
    app.dependency_overrides[get_db] = lambda: (yield db).__next__() or db

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
# Tests: Keywords page rendering
# ---------------------------------------------------------------------------


class TestKeywordsPageRendering:
    """Test that the keywords page shows/hides the add form based on role."""

    def test_client_admin_sees_add_form(self, db):
        """client_admin role sees the 'Add Keyword' form."""
        client_obj = _make_client(db)
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            r = tc.get(f"/clients/{client_obj.id}/keywords")
            assert r.status_code == 200
            assert 'name="keyword"' in r.text
            assert 'name="priority"' in r.text
            assert "actions/keywords/add" in r.text
        finally:
            app.dependency_overrides.clear()

    def test_owner_sees_add_form(self, db):
        """owner role sees the 'Add Keyword' form."""
        client_obj = _make_client(db)
        user = _make_user(db, UserRole.owner)
        tc = _authenticated_client(db, user)
        try:
            r = tc.get(f"/clients/{client_obj.id}/keywords")
            assert r.status_code == 200
            assert 'name="keyword"' in r.text
            assert "actions/keywords/add" in r.text
        finally:
            app.dependency_overrides.clear()

    def test_client_viewer_does_not_see_add_form(self, db):
        """client_viewer role does NOT see the add form."""
        client_obj = _make_client(db)
        user = _make_user(db, UserRole.client_viewer, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            r = tc.get(f"/clients/{client_obj.id}/keywords")
            assert r.status_code == 200
            # Form elements should not be present
            assert 'name="keyword"' not in r.text
            assert "actions/keywords/add" not in r.text
            # Existing keyword should still be visible (read-only)
            assert "existing keyword" in r.text
        finally:
            app.dependency_overrides.clear()

    def test_existing_keywords_shown_in_table(self, db):
        """Keywords from client.keywords JSONB appear in the analytics table."""
        client_obj = _make_client(db, keywords={"high": ["loan refinancing"], "medium": ["mortgage"], "low": []})
        user = _make_user(db, UserRole.owner)
        tc = _authenticated_client(db, user)
        try:
            r = tc.get(f"/clients/{client_obj.id}/keywords")
            assert r.status_code == 200
            assert "loan refinancing" in r.text
            assert "mortgage" in r.text
        finally:
            app.dependency_overrides.clear()

    def test_remove_button_visible_for_editable_roles(self, db):
        """client_admin sees the remove button next to keywords."""
        client_obj = _make_client(db)
        user = _make_user(db, UserRole.client_admin, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            r = tc.get(f"/clients/{client_obj.id}/keywords")
            assert r.status_code == 200
            assert "actions/keywords/remove" in r.text
        finally:
            app.dependency_overrides.clear()

    def test_remove_button_hidden_for_viewer(self, db):
        """client_viewer does NOT see the remove button."""
        client_obj = _make_client(db)
        user = _make_user(db, UserRole.client_viewer, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            r = tc.get(f"/clients/{client_obj.id}/keywords")
            assert r.status_code == 200
            assert "actions/keywords/remove" not in r.text
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: Add keyword endpoint
# ---------------------------------------------------------------------------


class TestAddKeyword:
    """Test POST /clients/{id}/actions/keywords/add."""

    def test_add_keyword_success(self, db):
        """Adding a new keyword returns success and persists."""
        client_obj = _make_client(db, keywords={"high": [], "medium": [], "low": []})
        user = _make_user(db, UserRole.owner)
        tc = _authenticated_client(db, user)
        try:
            r = tc.post(
                f"/clients/{client_obj.id}/actions/keywords/add",
                data={"keyword": "loan refinancing", "priority": "high"},
            )
            assert r.status_code == 200
            assert "Keyword added" in r.text

            # Verify persistence
            db.refresh(client_obj)
            assert "loan refinancing" in client_obj.keywords["high"]
        finally:
            app.dependency_overrides.clear()

    def test_add_keyword_duplicate(self, db):
        """Adding a duplicate keyword returns 409."""
        client_obj = _make_client(db, keywords={"high": ["mortgage"], "medium": [], "low": []})
        user = _make_user(db, UserRole.owner)
        tc = _authenticated_client(db, user)
        try:
            r = tc.post(
                f"/clients/{client_obj.id}/actions/keywords/add",
                data={"keyword": "mortgage", "priority": "medium"},
            )
            assert r.status_code == 409
            assert "already exists" in r.text
        finally:
            app.dependency_overrides.clear()

    def test_add_keyword_empty(self, db):
        """Adding an empty keyword returns 422."""
        client_obj = _make_client(db, keywords={"high": [], "medium": [], "low": []})
        user = _make_user(db, UserRole.owner)
        tc = _authenticated_client(db, user)
        try:
            r = tc.post(
                f"/clients/{client_obj.id}/actions/keywords/add",
                data={"keyword": "   ", "priority": "high"},
            )
            assert r.status_code == 422
            assert "cannot be empty" in r.text
        finally:
            app.dependency_overrides.clear()

    def test_add_keyword_invalid_priority(self, db):
        """Invalid priority value returns 422."""
        client_obj = _make_client(db, keywords={"high": [], "medium": [], "low": []})
        user = _make_user(db, UserRole.owner)
        tc = _authenticated_client(db, user)
        try:
            r = tc.post(
                f"/clients/{client_obj.id}/actions/keywords/add",
                data={"keyword": "test", "priority": "critical"},
            )
            assert r.status_code == 422
            assert "Invalid priority" in r.text
        finally:
            app.dependency_overrides.clear()

    def test_add_keyword_viewer_denied(self, db):
        """client_viewer cannot add keywords (403)."""
        client_obj = _make_client(db)
        user = _make_user(db, UserRole.client_viewer, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            r = tc.post(
                f"/clients/{client_obj.id}/actions/keywords/add",
                data={"keyword": "test", "priority": "medium"},
            )
            assert r.status_code == 403
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: Remove keyword endpoint
# ---------------------------------------------------------------------------


class TestRemoveKeyword:
    """Test POST /clients/{id}/actions/keywords/remove."""

    def test_remove_keyword_success(self, db):
        """Removing an existing keyword works."""
        client_obj = _make_client(db, keywords={"high": ["to remove"], "medium": [], "low": []})
        user = _make_user(db, UserRole.owner)
        tc = _authenticated_client(db, user)
        try:
            r = tc.post(
                f"/clients/{client_obj.id}/actions/keywords/remove",
                data={"keyword": "to remove", "priority": "high"},
            )
            assert r.status_code == 200
            assert "Keyword removed" in r.text

            # Verify persistence
            db.refresh(client_obj)
            assert "to remove" not in client_obj.keywords["high"]
        finally:
            app.dependency_overrides.clear()

    def test_remove_nonexistent_keyword(self, db):
        """Removing a keyword that doesn't exist still returns 200 (idempotent)."""
        client_obj = _make_client(db, keywords={"high": ["stays"], "medium": [], "low": []})
        user = _make_user(db, UserRole.owner)
        tc = _authenticated_client(db, user)
        try:
            r = tc.post(
                f"/clients/{client_obj.id}/actions/keywords/remove",
                data={"keyword": "ghost", "priority": "high"},
            )
            assert r.status_code == 200

            # Original keyword still there
            db.refresh(client_obj)
            assert "stays" in client_obj.keywords["high"]
        finally:
            app.dependency_overrides.clear()

    def test_remove_keyword_viewer_denied(self, db):
        """client_viewer cannot remove keywords (403)."""
        client_obj = _make_client(db, keywords={"high": ["protected"], "medium": [], "low": []})
        user = _make_user(db, UserRole.client_viewer, client_id=client_obj.id)
        tc = _authenticated_client(db, user)
        try:
            r = tc.post(
                f"/clients/{client_obj.id}/actions/keywords/remove",
                data={"keyword": "protected", "priority": "high"},
            )
            assert r.status_code == 403

            # Keyword still exists
            db.refresh(client_obj)
            assert "protected" in client_obj.keywords["high"]
        finally:
            app.dependency_overrides.clear()
