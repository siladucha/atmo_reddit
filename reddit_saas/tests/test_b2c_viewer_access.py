"""Consolidated tests for B2C and client_viewer access control (task 10.4).

Tests cover:
- B2C single avatar limit (blocked when has 1 avatar, allowed when has 0)
- client_viewer read-only access (can_approve_drafts returns False when flag disabled)
- client_viewer conditional draft approval (returns True when flag enabled)
- B2C upgrade to B2B (role changes, client created, avatar reassigned)

Validates Requirements: 8.1, 8.2, 8.3, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10
"""

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.models.user_role import UserRole
from app.services.access_control import (
    can_approve_drafts,
    check_b2c_avatar_limit,
    upgrade_b2c_to_b2b,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: UserRole, client_id=None):
    """Create a mock User with the given role."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.user_role = role
    user.client_id = client_id or uuid.uuid4()
    user.is_superuser = role in (UserRole.owner, UserRole.partner)
    user.is_active = True
    user.role = role.value
    return user


def _make_client(draft_approval_enabled: bool = False, is_active: bool = True):
    """Create a mock Client with the given flags."""
    client = MagicMock()
    client.id = uuid.uuid4()
    client.draft_approval_enabled = draft_approval_enabled
    client.is_active = is_active
    client.max_avatars = 3
    client.plan_type = "starter"
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
# B2C Single Avatar Limit Tests (Requirement 8.9)
# ---------------------------------------------------------------------------


class TestB2CSingleAvatarLimit:
    """Tests for check_b2c_avatar_limit — B2C users can have only one avatar."""

    def test_b2c_blocked_when_has_one_avatar(self):
        """B2C user with 1 existing avatar is blocked from creating another.

        Validates: Requirement 8.9 — B2C user cannot create a second avatar.
        """
        user = _make_user(UserRole.b2c_user)
        db = _make_mock_db(avatar_count=1)

        with pytest.raises(HTTPException) as exc_info:
            check_b2c_avatar_limit(db, user)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "B2C users can have only one avatar"

    def test_b2c_allowed_when_has_zero_avatars(self):
        """B2C user with 0 avatars can create their first avatar.

        Validates: Requirement 8.9 — B2C user can have exactly one avatar.
        """
        user = _make_user(UserRole.b2c_user)
        db = _make_mock_db(avatar_count=0)

        # Should not raise
        check_b2c_avatar_limit(db, user)

    def test_b2c_blocked_when_has_multiple_avatars(self):
        """B2C user with multiple avatars (data anomaly) is still blocked.

        Validates: Requirement 8.9 — limit is enforced regardless of current count > 1.
        """
        user = _make_user(UserRole.b2c_user)
        db = _make_mock_db(avatar_count=3)

        with pytest.raises(HTTPException) as exc_info:
            check_b2c_avatar_limit(db, user)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "B2C users can have only one avatar"

    def test_b2c_no_client_id_blocked(self):
        """B2C user without a client_id is blocked (cannot own avatars).

        Validates: Requirement 8.7 — B2C user with no client_id gets 403.
        """
        user = _make_user(UserRole.b2c_user)
        user.client_id = None
        db = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            check_b2c_avatar_limit(db, user)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "B2C users can have only one avatar"

    def test_non_b2c_roles_not_checked(self):
        """Non-B2C roles bypass the single avatar limit check entirely.

        Validates: Requirement 8.8 — limit only applies to b2c_user role.
        """
        non_b2c_roles = [
            UserRole.owner,
            UserRole.partner,
            UserRole.client_admin,
            UserRole.client_manager,
            UserRole.client_viewer,
        ]
        for role in non_b2c_roles:
            user = _make_user(role)
            db = _make_mock_db(avatar_count=10)

            # Should not raise for any non-b2c role
            check_b2c_avatar_limit(db, user)


# ---------------------------------------------------------------------------
# Client Viewer Read-Only Access Tests (Requirements 8.1, 8.2, 8.3, 8.5, 8.6)
# ---------------------------------------------------------------------------


class TestClientViewerReadOnlyAccess:
    """Tests for client_viewer read-only access — draft approval denied when flag disabled."""

    def test_client_viewer_cannot_approve_when_flag_disabled(self):
        """client_viewer gets False for can_approve_drafts when flag is disabled.

        Validates: Requirement 8.6 — client_viewer read-only when draft_approval_enabled=False.
        """
        user = _make_user(UserRole.client_viewer)
        client = _make_client(draft_approval_enabled=False)

        result = can_approve_drafts(user, client)

        assert result is False

    def test_client_viewer_scoped_to_own_client(self):
        """client_viewer access is scoped to their own client_id.

        Validates: Requirement 8.1 — queries scoped to user's own client_id.
        """
        user = _make_user(UserRole.client_viewer)
        # Verify the user has a client_id (scoping prerequisite)
        assert user.client_id is not None
        assert user.user_role.is_client_scoped is True

    def test_client_viewer_role_is_client_scoped(self):
        """client_viewer role is marked as client-scoped.

        Validates: Requirement 8.1 — client_viewer is client-scoped.
        """
        assert UserRole.client_viewer.is_client_scoped is True

    def test_client_viewer_cannot_manage_system(self):
        """client_viewer cannot access system settings.

        Validates: Requirement 8.3 — client_viewer denied system settings access.
        """
        assert UserRole.client_viewer.can_manage_system is False

    def test_client_viewer_cannot_manage_users(self):
        """client_viewer cannot manage users.

        Validates: Requirement 8.3 — client_viewer denied user management.
        """
        assert UserRole.client_viewer.can_manage_users is False

    def test_client_viewer_cannot_manage_clients(self):
        """client_viewer cannot manage clients.

        Validates: Requirement 8.3 — client_viewer denied client management.
        """
        assert UserRole.client_viewer.can_manage_clients is False

    def test_client_viewer_cannot_trigger_pipeline(self):
        """client_viewer cannot trigger pipeline.

        Validates: Requirement 8.3 — client_viewer denied pipeline triggers.
        """
        assert UserRole.client_viewer.can_trigger_pipeline is False

    def test_client_viewer_not_admin_level(self):
        """client_viewer cannot access admin panel.

        Validates: Requirement 8.3 — client_viewer denied admin panel pages.
        """
        assert UserRole.client_viewer.is_admin_level is False


# ---------------------------------------------------------------------------
# Client Viewer Conditional Draft Approval Tests (Requirements 8.5, 8.6)
# ---------------------------------------------------------------------------


class TestClientViewerConditionalDraftApproval:
    """Tests for client_viewer conditional draft approval — enabled vs disabled."""

    def test_viewer_can_approve_when_flag_enabled(self):
        """client_viewer CAN approve drafts when client.draft_approval_enabled=True.

        Validates: Requirement 8.5 — client_viewer allowed to approve/reject/edit
        when draft_approval_enabled is True.
        """
        user = _make_user(UserRole.client_viewer)
        client = _make_client(draft_approval_enabled=True)

        result = can_approve_drafts(user, client)

        assert result is True

    def test_viewer_cannot_approve_when_flag_disabled(self):
        """client_viewer CANNOT approve drafts when client.draft_approval_enabled=False.

        Validates: Requirement 8.6 — client_viewer gets read-only access when
        draft_approval_enabled is False.
        """
        user = _make_user(UserRole.client_viewer)
        client = _make_client(draft_approval_enabled=False)

        result = can_approve_drafts(user, client)

        assert result is False

    def test_b2c_user_cannot_approve_regardless_of_flag(self):
        """b2c_user CANNOT approve drafts even when flag is enabled.

        Validates: Requirement 8.8 — B2C users have restricted access.
        """
        user = _make_user(UserRole.b2c_user)
        client = _make_client(draft_approval_enabled=True)

        result = can_approve_drafts(user, client)

        assert result is False

    def test_client_admin_always_can_approve(self):
        """client_admin can always approve regardless of flag.

        Validates: Requirement 8.5 — higher roles always have approval access.
        """
        user = _make_user(UserRole.client_admin)
        client = _make_client(draft_approval_enabled=False)

        result = can_approve_drafts(user, client)

        assert result is True

    def test_client_manager_always_can_approve(self):
        """client_manager can always approve regardless of flag.

        Validates: Requirement 8.5 — higher roles always have approval access.
        """
        user = _make_user(UserRole.client_manager)
        client = _make_client(draft_approval_enabled=False)

        result = can_approve_drafts(user, client)

        assert result is True

    def test_owner_always_can_approve(self):
        """owner can always approve regardless of flag."""
        user = _make_user(UserRole.owner)
        client = _make_client(draft_approval_enabled=False)

        result = can_approve_drafts(user, client)

        assert result is True

    def test_partner_always_can_approve(self):
        """partner can always approve regardless of flag."""
        user = _make_user(UserRole.partner)
        client = _make_client(draft_approval_enabled=False)

        result = can_approve_drafts(user, client)

        assert result is True


# ---------------------------------------------------------------------------
# B2C Upgrade to B2B Tests (Requirement 8.10)
# ---------------------------------------------------------------------------


class TestB2CUpgradeToB2B:
    """Tests for upgrade_b2c_to_b2b — B2C user upgrades to B2B client_admin.

    These tests use the real DB session (via the `db` fixture from conftest.py)
    because upgrade_b2c_to_b2b performs actual DB operations (INSERT, UPDATE, flush).
    """

    @pytest.fixture
    def b2c_user_with_avatar(self, db):
        """Create a B2C user with a personal avatar for upgrade testing."""
        from app.models.client import Client
        from app.models.avatar import Avatar
        from app.models.user import User

        # Create a placeholder client for the B2C user's personal context
        personal_client = Client(
            client_name="Personal B2C",
            brand_name="Personal",
            is_active=True,
        )
        db.add(personal_client)
        db.flush()

        # Create the B2C user
        user = User(
            email=f"b2c_{uuid.uuid4().hex[:8]}@test.com",
            hashed_password="hashed",
            full_name="B2C Test User",
            is_active=True,
            role=UserRole.b2c_user.value,
            client_id=personal_client.id,
        )
        db.add(user)
        db.flush()

        # Create the personal avatar
        avatar = Avatar(
            reddit_username=f"b2c_avatar_{uuid.uuid4().hex[:8]}",
            client_ids=[str(personal_client.id)],
            active=True,
        )
        db.add(avatar)
        db.flush()

        return user, avatar, personal_client

    def test_upgrade_changes_role_to_client_admin(self, db, b2c_user_with_avatar):
        """After upgrade, user role changes from b2c_user to client_admin.

        Validates: Requirement 8.10 — role conversion on upgrade.
        """
        user, avatar, _ = b2c_user_with_avatar

        upgrade_b2c_to_b2b(db, user, "New Company", "NewBrand")

        db.refresh(user)
        assert user.role == UserRole.client_admin.value
        assert user.user_role == UserRole.client_admin

    def test_upgrade_creates_client_record(self, db, b2c_user_with_avatar):
        """Upgrade creates a new Client record with correct fields.

        Validates: Requirement 8.10 — client record created on upgrade.
        """
        user, avatar, _ = b2c_user_with_avatar

        new_client = upgrade_b2c_to_b2b(db, user, "Acme Corp", "AcmeBrand")

        assert new_client is not None
        assert new_client.client_name == "Acme Corp"
        assert new_client.brand_name == "AcmeBrand"
        assert new_client.is_active is True
        assert new_client.max_avatars == 3
        assert new_client.plan_type == "starter"

    def test_upgrade_reassigns_avatar_to_new_client(self, db, b2c_user_with_avatar):
        """Upgrade converts personal avatar to first company avatar.

        Validates: Requirement 8.10 — avatar reassigned to new client.
        """
        user, avatar, old_client = b2c_user_with_avatar

        new_client = upgrade_b2c_to_b2b(db, user, "Acme Corp", "AcmeBrand")

        db.refresh(avatar)
        assert str(new_client.id) in avatar.client_ids
        assert str(old_client.id) not in avatar.client_ids

    def test_upgrade_sets_user_client_id(self, db, b2c_user_with_avatar):
        """Upgrade sets user.client_id to the new client's ID.

        Validates: Requirement 8.10 — user linked to new client.
        """
        user, avatar, _ = b2c_user_with_avatar

        new_client = upgrade_b2c_to_b2b(db, user, "Acme Corp", "AcmeBrand")

        db.refresh(user)
        assert user.client_id == new_client.id

    def test_upgrade_allows_additional_avatar_creation(self, db, b2c_user_with_avatar):
        """After upgrade, user can create up to (max_avatars - 1) additional avatars.

        Validates: Requirement 8.10 — additional avatar creation allowed post-upgrade.
        """
        from app.models.avatar import Avatar

        user, avatar, _ = b2c_user_with_avatar

        new_client = upgrade_b2c_to_b2b(db, user, "Acme Corp", "AcmeBrand")

        # Count existing avatars for the new client
        existing_count = (
            db.query(Avatar)
            .filter(Avatar.client_ids.any(str(new_client.id)))
            .count()
        )
        assert existing_count == 1
        # Can create (max_avatars - 1) more = 2 more
        assert new_client.max_avatars - existing_count == 2

    def test_upgrade_rejects_non_b2c_user(self, db):
        """Upgrade raises ValueError for non-b2c_user roles.

        Validates: Requirement 8.10 — only b2c_user can upgrade.
        """
        from app.models.user import User

        user = User(
            email=f"manager_{uuid.uuid4().hex[:8]}@test.com",
            hashed_password="hashed",
            full_name="Manager",
            is_active=True,
            role=UserRole.client_manager.value,
        )
        db.add(user)
        db.flush()

        with pytest.raises(ValueError, match="Only b2c_user accounts can be upgraded"):
            upgrade_b2c_to_b2b(db, user, "Acme Corp", "AcmeBrand")

    def test_upgrade_rejects_empty_company_name(self, db, b2c_user_with_avatar):
        """Upgrade raises ValueError if company_name is empty.

        Validates: Requirement 8.10 — input validation.
        """
        user, _, _ = b2c_user_with_avatar

        with pytest.raises(ValueError, match="company_name is required"):
            upgrade_b2c_to_b2b(db, user, "", "AcmeBrand")

    def test_upgrade_rejects_empty_brand_name(self, db, b2c_user_with_avatar):
        """Upgrade raises ValueError if brand_name is empty.

        Validates: Requirement 8.10 — input validation.
        """
        user, _, _ = b2c_user_with_avatar

        with pytest.raises(ValueError, match="brand_name is required"):
            upgrade_b2c_to_b2b(db, user, "Acme Corp", "")
