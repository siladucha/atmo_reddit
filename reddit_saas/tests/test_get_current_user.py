"""Tests for the get_current_user base permission dependency.

Tests the dependency function directly by simulating request.state
as set by AuthMiddleware.
"""

import asyncio
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.dependencies.permissions import get_current_user
from app.models.user import User
from app.models.user_role import UserRole


def _run(coro):
    """Run an async function synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_user(db: Session, **kwargs) -> User:
    """Helper to create a user with given attributes."""
    defaults = {
        "email": f"test-{uuid.uuid4().hex[:8]}@example.com",
        "hashed_password": "hashed",
        "full_name": "Test User",
        "is_active": True,
        "is_superuser": False,
        "role": UserRole.client_manager.value,
    }
    defaults.update(kwargs)
    user = User(**defaults)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_request(user_id: str | None = None) -> MagicMock:
    """Create a mock Request with user_id in state (as AuthMiddleware sets it)."""
    request = MagicMock()
    if user_id is not None:
        request.state.user_id = user_id
    else:
        # getattr(request.state, "user_id", None) should return None
        type(request.state).user_id = None
    return request


def _make_request_no_state() -> MagicMock:
    """Create a mock Request where user_id attribute doesn't exist on state."""
    request = MagicMock()
    # Make getattr(request.state, "user_id", None) return None
    del request.state.user_id
    return request


class TestGetCurrentUser:
    """Tests for get_current_user dependency."""

    def test_valid_user_returns_user_object(self, db):
        """Active user with valid JWT gets authenticated successfully."""
        user = _make_user(db)
        request = _make_request(str(user.id))

        result = _run(get_current_user(request, db))

        assert result.id == user.id
        assert result.email == user.email

    def test_no_user_id_redirects_to_login(self, db):
        """Request without user_id in state gets 303 redirect to /login."""
        request = _make_request_no_state()

        with pytest.raises(HTTPException) as exc_info:
            _run(get_current_user(request, db))

        assert exc_info.value.status_code == 303
        assert exc_info.value.headers["Location"] == "/login"

    def test_none_user_id_redirects_to_login(self, db):
        """Request with None user_id gets 303 redirect to /login."""
        request = _make_request(None)

        with pytest.raises(HTTPException) as exc_info:
            _run(get_current_user(request, db))

        assert exc_info.value.status_code == 303
        assert exc_info.value.headers["Location"] == "/login"

    def test_invalid_uuid_redirects_to_login(self, db):
        """Request with non-UUID user_id gets 303 redirect to /login."""
        request = _make_request("not-a-valid-uuid")

        with pytest.raises(HTTPException) as exc_info:
            _run(get_current_user(request, db))

        assert exc_info.value.status_code == 303
        assert exc_info.value.headers["Location"] == "/login"

    def test_nonexistent_user_redirects_to_login(self, db):
        """JWT with user_id that doesn't exist in DB gets 303 redirect."""
        fake_id = uuid.uuid4()
        request = _make_request(str(fake_id))

        with pytest.raises(HTTPException) as exc_info:
            _run(get_current_user(request, db))

        assert exc_info.value.status_code == 303
        assert exc_info.value.headers["Location"] == "/login"

    def test_inactive_user_redirects_to_login(self, db):
        """User with is_active=False gets 303 redirect to /login."""
        user = _make_user(db, is_active=False)
        request = _make_request(str(user.id))

        with pytest.raises(HTTPException) as exc_info:
            _run(get_current_user(request, db))

        assert exc_info.value.status_code == 303
        assert exc_info.value.headers["Location"] == "/login"

    def test_superuser_flag_maps_to_owner_when_role_not_set(self, db):
        """User with is_superuser=True and no explicit role gets owner via fallback.

        The user_role property uses is_superuser as a fallback when role is
        not set or invalid. When role IS set, it takes precedence.
        """
        # Case 1: is_superuser=True with no valid role → owner fallback
        user = _make_user(db, is_superuser=True, role="")
        request = _make_request(str(user.id))

        result = _run(get_current_user(request, db))

        assert result.id == user.id
        assert result.user_role == UserRole.owner

    def test_superuser_with_explicit_role_uses_role(self, db):
        """User with is_superuser=True but explicit role uses the role column.

        The role column takes precedence over is_superuser flag.
        get_current_user still authenticates the user (it doesn't filter by role).
        """
        user = _make_user(db, is_superuser=True, role=UserRole.client_manager.value)
        request = _make_request(str(user.id))

        result = _run(get_current_user(request, db))

        assert result.id == user.id
        # Role column takes precedence
        assert result.user_role == UserRole.client_manager
        # But is_superuser is still True (legacy flag preserved)
        assert result.is_superuser is True

    def test_owner_role_user_authenticates(self, db):
        """User with owner role authenticates successfully."""
        user = _make_user(db, role=UserRole.owner.value, is_superuser=True)
        request = _make_request(str(user.id))

        result = _run(get_current_user(request, db))

        assert result.id == user.id
        assert result.user_role == UserRole.owner

    def test_partner_role_user_authenticates(self, db):
        """User with partner role authenticates successfully."""
        user = _make_user(db, role=UserRole.partner.value)
        request = _make_request(str(user.id))

        result = _run(get_current_user(request, db))

        assert result.id == user.id
        assert result.user_role == UserRole.partner

    def test_client_admin_authenticates(self, db):
        """User with client_admin role authenticates successfully."""
        user = _make_user(db, role=UserRole.client_admin.value)
        request = _make_request(str(user.id))

        result = _run(get_current_user(request, db))

        assert result.id == user.id
        assert result.user_role == UserRole.client_admin

    def test_client_viewer_authenticates(self, db):
        """User with client_viewer role authenticates successfully."""
        user = _make_user(db, role=UserRole.client_viewer.value)
        request = _make_request(str(user.id))

        result = _run(get_current_user(request, db))

        assert result.id == user.id
        assert result.user_role == UserRole.client_viewer

    def test_b2c_user_authenticates(self, db):
        """User with b2c_user role authenticates successfully."""
        user = _make_user(db, role=UserRole.b2c_user.value)
        request = _make_request(str(user.id))

        result = _run(get_current_user(request, db))

        assert result.id == user.id
        assert result.user_role == UserRole.b2c_user

    def test_all_roles_authenticate_when_active(self, db):
        """All valid roles can authenticate when user is active."""
        all_roles = [
            UserRole.owner, UserRole.partner, UserRole.qa,
            UserRole.client_admin, UserRole.client_manager,
            UserRole.client_viewer, UserRole.b2c_user,
        ]

        for role in all_roles:
            is_su = role == UserRole.owner
            user = _make_user(db, role=role.value, is_superuser=is_su)
            request = _make_request(str(user.id))

            result = _run(get_current_user(request, db))

            assert result.id == user.id, f"Role {role.value} failed to authenticate"
            assert result.user_role == role
