"""Consolidated B2B access control tests.

Tests cover the end-to-end B2B access control scenarios:
1. max_avatars enforcement (client_admin blocked at limit, owner bypasses)
2. client_admin team management (can create client_manager/viewer, cannot create client_admin)
3. client deactivation cascade (client-scoped users blocked when client inactive)
4. Draft approval scoped to own client (client_manager can approve own client's drafts)

Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.6, 7.11, 7.13
"""

import asyncio
import uuid
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.models.user import User
from app.models.user_role import UserRole
from app.services.access_control import check_avatar_limit, can_approve_drafts
from app.services.team_management import validate_team_management


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    role: UserRole,
    client_id: uuid.UUID | None = None,
    is_superuser: bool = False,
    is_active: bool = True,
) -> User:
    """Create a User object for testing."""
    user = User(
        id=uuid.uuid4(),
        email=f"test-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        full_name="Test User",
        is_active=is_active,
        is_superuser=is_superuser,
        role=role.value,
        client_id=client_id or uuid.uuid4(),
    )
    return user


def _make_client(
    client_id: uuid.UUID | None = None,
    max_avatars: int = 3,
    is_active: bool = True,
    draft_approval_enabled: bool = False,
):
    """Create a mock Client with configurable attributes."""
    client = MagicMock()
    client.id = client_id or uuid.uuid4()
    client.max_avatars = max_avatars
    client.is_active = is_active
    client.draft_approval_enabled = draft_approval_enabled
    return client


def _make_mock_db(avatar_count: int):
    """Create a mock DB session that returns a given avatar count."""
    db = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.count.return_value = avatar_count
    return db


# ---------------------------------------------------------------------------
# 1. max_avatars enforcement
# Validates: Requirement 7.6
# ---------------------------------------------------------------------------


class TestMaxAvatarsEnforcement:
    """Test that max_avatars limit is enforced for client-scoped users
    and bypassed for platform admins."""

    def test_client_admin_blocked_at_limit(self):
        """client_admin gets 403 when avatar count equals max_avatars."""
        user = _make_user(UserRole.client_admin)
        client = _make_client(max_avatars=3)
        db = _make_mock_db(avatar_count=3)

        with pytest.raises(HTTPException) as exc_info:
            check_avatar_limit(db, client, user)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Maximum avatars reached for your plan"

    def test_client_admin_blocked_over_limit(self):
        """client_admin gets 403 when avatar count exceeds max_avatars."""
        user = _make_user(UserRole.client_admin)
        client = _make_client(max_avatars=5)
        db = _make_mock_db(avatar_count=7)

        with pytest.raises(HTTPException) as exc_info:
            check_avatar_limit(db, client, user)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Maximum avatars reached for your plan"

    def test_client_admin_allowed_under_limit(self):
        """client_admin can create when under the limit."""
        user = _make_user(UserRole.client_admin)
        client = _make_client(max_avatars=5)
        db = _make_mock_db(avatar_count=2)

        # Should not raise
        check_avatar_limit(db, client, user)

    def test_client_manager_blocked_at_limit(self):
        """client_manager gets 403 when avatar count equals max_avatars."""
        user = _make_user(UserRole.client_manager)
        client = _make_client(max_avatars=3)
        db = _make_mock_db(avatar_count=3)

        with pytest.raises(HTTPException) as exc_info:
            check_avatar_limit(db, client, user)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Maximum avatars reached for your plan"

    def test_owner_bypasses_limit(self):
        """Owner can create avatars regardless of limit."""
        user = _make_user(UserRole.owner, is_superuser=True)
        client = _make_client(max_avatars=3)
        db = _make_mock_db(avatar_count=100)

        # Should not raise — owner bypasses
        check_avatar_limit(db, client, user)

    def test_partner_bypasses_limit(self):
        """Partner can create avatars regardless of limit."""
        user = _make_user(UserRole.partner, is_superuser=True)
        client = _make_client(max_avatars=3)
        db = _make_mock_db(avatar_count=100)

        # Should not raise — partner bypasses
        check_avatar_limit(db, client, user)

    def test_limit_of_one_blocks_second_avatar(self):
        """A plan with max_avatars=1 blocks creation when one exists."""
        user = _make_user(UserRole.client_admin)
        client = _make_client(max_avatars=1)
        db = _make_mock_db(avatar_count=1)

        with pytest.raises(HTTPException) as exc_info:
            check_avatar_limit(db, client, user)
        assert exc_info.value.status_code == 403

    def test_zero_avatars_always_allowed(self):
        """Creation is allowed when client has zero avatars."""
        user = _make_user(UserRole.client_admin)
        client = _make_client(max_avatars=3)
        db = _make_mock_db(avatar_count=0)

        # Should not raise
        check_avatar_limit(db, client, user)


# ---------------------------------------------------------------------------
# 2. client_admin team management scope
# Validates: Requirements 7.2, 7.3, 7.4
# ---------------------------------------------------------------------------


class TestClientAdminTeamManagementScope:
    """Test that client_admin can manage client_manager/viewer within own company,
    cannot create client_admin, and client_manager cannot manage users at all."""

    def test_client_admin_can_create_client_manager(self):
        """client_admin can create client_manager in own company."""
        company_id = uuid.uuid4()
        user = _make_user(UserRole.client_admin, client_id=company_id)

        # Should not raise
        validate_team_management(
            requesting_user=user,
            target_role=UserRole.client_manager,
            target_client_id=company_id,
        )

    def test_client_admin_can_create_client_viewer(self):
        """client_admin can create client_viewer in own company."""
        company_id = uuid.uuid4()
        user = _make_user(UserRole.client_admin, client_id=company_id)

        # Should not raise
        validate_team_management(
            requesting_user=user,
            target_role=UserRole.client_viewer,
            target_client_id=company_id,
        )

    def test_client_admin_cannot_create_client_admin(self):
        """client_admin CANNOT create another client_admin — only owner/partner can."""
        company_id = uuid.uuid4()
        user = _make_user(UserRole.client_admin, client_id=company_id)

        with pytest.raises(HTTPException) as exc_info:
            validate_team_management(
                requesting_user=user,
                target_role=UserRole.client_admin,
                target_client_id=company_id,
            )
        assert exc_info.value.status_code == 403
        assert "Access Denied" in exc_info.value.detail

    def test_client_admin_cannot_create_owner(self):
        """client_admin CANNOT create owner role."""
        company_id = uuid.uuid4()
        user = _make_user(UserRole.client_admin, client_id=company_id)

        with pytest.raises(HTTPException) as exc_info:
            validate_team_management(
                requesting_user=user,
                target_role=UserRole.owner,
                target_client_id=company_id,
            )
        assert exc_info.value.status_code == 403

    def test_client_admin_cannot_manage_other_company(self):
        """client_admin CANNOT manage users in another company."""
        own_company = uuid.uuid4()
        other_company = uuid.uuid4()
        user = _make_user(UserRole.client_admin, client_id=own_company)

        with pytest.raises(HTTPException) as exc_info:
            validate_team_management(
                requesting_user=user,
                target_role=UserRole.client_manager,
                target_client_id=other_company,
            )
        assert exc_info.value.status_code == 403
        assert "Access Denied" in exc_info.value.detail

    def test_client_manager_cannot_manage_users(self):
        """client_manager CANNOT manage users at all."""
        company_id = uuid.uuid4()
        user = _make_user(UserRole.client_manager, client_id=company_id)

        with pytest.raises(HTTPException) as exc_info:
            validate_team_management(
                requesting_user=user,
                target_role=UserRole.client_viewer,
                target_client_id=company_id,
            )
        assert exc_info.value.status_code == 403
        assert "Access Denied" in exc_info.value.detail

    def test_client_viewer_cannot_manage_users(self):
        """client_viewer CANNOT manage users at all."""
        company_id = uuid.uuid4()
        user = _make_user(UserRole.client_viewer, client_id=company_id)

        with pytest.raises(HTTPException) as exc_info:
            validate_team_management(
                requesting_user=user,
                target_role=UserRole.client_viewer,
                target_client_id=company_id,
            )
        assert exc_info.value.status_code == 403

    def test_owner_can_create_client_admin(self):
        """owner CAN create client_admin for any company."""
        user = _make_user(UserRole.owner, is_superuser=True)
        target_company = uuid.uuid4()

        # Should not raise
        validate_team_management(
            requesting_user=user,
            target_role=UserRole.client_admin,
            target_client_id=target_company,
        )

    def test_partner_can_create_client_admin(self):
        """partner CAN create client_admin for any company."""
        user = _make_user(UserRole.partner, is_superuser=True)
        target_company = uuid.uuid4()

        # Should not raise
        validate_team_management(
            requesting_user=user,
            target_role=UserRole.client_admin,
            target_client_id=target_company,
        )


# ---------------------------------------------------------------------------
# 3. Client deactivation cascade
# Validates: Requirements 7.13, 1.8
# ---------------------------------------------------------------------------


class TestClientDeactivationCascade:
    """Test that client-scoped users are blocked when their client is inactive.

    The cascade is implemented in get_current_user (permissions.py):
    - After loading the user, if user.user_role.is_client_scoped and user.client_id,
      it loads the client and checks client.is_active.
    - If client is inactive, raises 403 "Access Denied".
    """

    def _run_get_current_user(self, request, db):
        """Helper to run the async get_current_user in a sync test."""
        from app.dependencies.permissions import get_current_user
        return asyncio.run(get_current_user(request, db))

    def _make_db_with_user_and_client(self, user, client_mock):
        """Create a mock DB that returns user on User query and client_mock on Client query."""
        from app.models.client import Client

        db = MagicMock()
        user_query = MagicMock()
        user_query.filter.return_value = user_query
        user_query.first.return_value = user

        client_query = MagicMock()
        client_query.filter.return_value = client_query
        client_query.first.return_value = client_mock

        def query_side_effect(model):
            if model == User:
                return user_query
            elif model == Client:
                return client_query
            return MagicMock()

        db.query.side_effect = query_side_effect
        return db

    def test_client_scoped_user_blocked_when_client_inactive(self):
        """A client_manager is denied access when their client is deactivated."""
        client_id = uuid.uuid4()
        user = _make_user(UserRole.client_manager, client_id=client_id)
        inactive_client = _make_client(client_id=client_id, is_active=False)

        request = MagicMock()
        request.state.user_id = str(user.id)
        db = self._make_db_with_user_and_client(user, inactive_client)

        with pytest.raises(HTTPException) as exc_info:
            self._run_get_current_user(request, db)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Access Denied"

    def test_client_scoped_user_allowed_when_client_active(self):
        """A client_manager is allowed access when their client is active."""
        client_id = uuid.uuid4()
        user = _make_user(UserRole.client_manager, client_id=client_id)
        active_client = _make_client(client_id=client_id, is_active=True)

        request = MagicMock()
        request.state.user_id = str(user.id)
        db = self._make_db_with_user_and_client(user, active_client)

        result = self._run_get_current_user(request, db)
        assert result == user

    def test_owner_not_affected_by_client_deactivation(self):
        """Owner is not client-scoped, so client deactivation doesn't affect them."""
        user = _make_user(UserRole.owner, is_superuser=True)

        request = MagicMock()
        request.state.user_id = str(user.id)

        db = MagicMock()
        user_query = MagicMock()
        user_query.filter.return_value = user_query
        user_query.first.return_value = user
        db.query.return_value = user_query

        result = self._run_get_current_user(request, db)
        assert result == user

    def test_client_admin_blocked_when_client_inactive(self):
        """A client_admin is denied access when their client is deactivated."""
        client_id = uuid.uuid4()
        user = _make_user(UserRole.client_admin, client_id=client_id)
        inactive_client = _make_client(client_id=client_id, is_active=False)

        request = MagicMock()
        request.state.user_id = str(user.id)
        db = self._make_db_with_user_and_client(user, inactive_client)

        with pytest.raises(HTTPException) as exc_info:
            self._run_get_current_user(request, db)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Access Denied"

    def test_client_viewer_blocked_when_client_inactive(self):
        """A client_viewer is denied access when their client is deactivated."""
        client_id = uuid.uuid4()
        user = _make_user(UserRole.client_viewer, client_id=client_id)
        inactive_client = _make_client(client_id=client_id, is_active=False)

        request = MagicMock()
        request.state.user_id = str(user.id)
        db = self._make_db_with_user_and_client(user, inactive_client)

        with pytest.raises(HTTPException) as exc_info:
            self._run_get_current_user(request, db)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Access Denied"

    def test_client_not_found_treated_as_inactive(self):
        """If client record is not found, user is denied (fail-closed)."""
        client_id = uuid.uuid4()
        user = _make_user(UserRole.client_manager, client_id=client_id)

        request = MagicMock()
        request.state.user_id = str(user.id)
        db = self._make_db_with_user_and_client(user, None)  # Client not found

        with pytest.raises(HTTPException) as exc_info:
            self._run_get_current_user(request, db)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Access Denied"


# ---------------------------------------------------------------------------
# 4. Draft approval scoped to own client
# Validates: Requirements 7.1, 7.11
# ---------------------------------------------------------------------------


class TestDraftApprovalScopedToOwnClient:
    """Test that draft approval is scoped to the user's own client.

    - client_manager can approve drafts for own client
    - client_admin can approve drafts for own client
    - client_viewer can approve only if draft_approval_enabled=True
    - No user can approve drafts for a different client (enforced by
      require_client_access guard)
    """

    def test_client_manager_can_approve_own_client_drafts(self):
        """client_manager can approve drafts belonging to their own client."""
        client_id = uuid.uuid4()
        user = _make_user(UserRole.client_manager, client_id=client_id)
        client = _make_client(client_id=client_id)

        assert can_approve_drafts(user, client) is True

    def test_client_admin_can_approve_own_client_drafts(self):
        """client_admin can approve drafts belonging to their own client."""
        client_id = uuid.uuid4()
        user = _make_user(UserRole.client_admin, client_id=client_id)
        client = _make_client(client_id=client_id)

        assert can_approve_drafts(user, client) is True

    def test_client_viewer_can_approve_when_enabled(self):
        """client_viewer can approve drafts when draft_approval_enabled=True."""
        client_id = uuid.uuid4()
        user = _make_user(UserRole.client_viewer, client_id=client_id)
        client = _make_client(client_id=client_id, draft_approval_enabled=True)

        assert can_approve_drafts(user, client) is True

    def test_client_viewer_cannot_approve_when_disabled(self):
        """client_viewer cannot approve drafts when draft_approval_enabled=False."""
        client_id = uuid.uuid4()
        user = _make_user(UserRole.client_viewer, client_id=client_id)
        client = _make_client(client_id=client_id, draft_approval_enabled=False)

        assert can_approve_drafts(user, client) is False

    def test_b2c_user_cannot_approve_drafts(self):
        """b2c_user cannot approve drafts regardless of flag."""
        client_id = uuid.uuid4()
        user = _make_user(UserRole.b2c_user, client_id=client_id)
        client = _make_client(client_id=client_id, draft_approval_enabled=True)

        assert can_approve_drafts(user, client) is False

    def test_require_client_access_blocks_cross_client_draft_approval(self):
        """require_client_access blocks a user from approving another client's drafts."""
        from app.dependencies.permissions import require_client_access

        own_client_id = uuid.uuid4()
        other_client_id = uuid.uuid4()
        user = _make_user(UserRole.client_manager, client_id=own_client_id)

        # Create the guard for the other client's ID
        guard = require_client_access(other_client_id)

        # Call the guard directly — it should raise 403
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(guard(user=user))
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Access Denied"

    def test_require_client_access_allows_own_client(self):
        """require_client_access allows a user to access their own client's resources."""
        from app.dependencies.permissions import require_client_access

        own_client_id = uuid.uuid4()
        user = _make_user(UserRole.client_manager, client_id=own_client_id)

        # Create the guard for the user's own client ID
        guard = require_client_access(own_client_id)

        # Call the guard directly — should return the user
        result = asyncio.run(guard(user=user))
        assert result == user

    def test_owner_can_approve_any_client_drafts(self):
        """Owner can access any client's resources via require_client_access."""
        from app.dependencies.permissions import require_client_access

        any_client_id = uuid.uuid4()
        user = _make_user(UserRole.owner, is_superuser=True)

        guard = require_client_access(any_client_id)
        result = asyncio.run(guard(user=user))
        assert result == user

    def test_partner_can_approve_any_client_drafts(self):
        """Partner can access any client's resources via require_client_access."""
        from app.dependencies.permissions import require_client_access

        any_client_id = uuid.uuid4()
        user = _make_user(UserRole.partner, is_superuser=True)

        guard = require_client_access(any_client_id)
        result = asyncio.run(guard(user=user))
        assert result == user
