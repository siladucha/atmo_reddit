"""Unit tests for client_admin team management scope.

Tests that:
- client_admin can create/edit/deactivate client_manager and client_viewer within own company
- client_admin CANNOT create another client_admin (only owner/partner can)
- client_manager CANNOT manage users at all
- owner/partner can manage any user for any client

Validates: Requirements 7.2, 7.3, 7.4
"""

import uuid

import pytest
from fastapi import HTTPException

from app.models.user import User
from app.models.user_role import UserRole
from app.services.team_management import validate_team_management, validate_user_deactivation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user_obj(
    role: UserRole,
    client_id: uuid.UUID | None = None,
    is_superuser: bool = False,
) -> User:
    """Create a User object (not persisted) for testing."""
    user = User(
        id=uuid.uuid4(),
        email=f"test-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        full_name="Test User",
        is_active=True,
        is_superuser=is_superuser,
        role=role.value,
        client_id=client_id,
    )
    return user


# ---------------------------------------------------------------------------
# Tests: owner/partner can manage any user
# ---------------------------------------------------------------------------


class TestOwnerPartnerCanManageAny:
    """owner can create any role; partner can create roles below themselves."""

    @pytest.mark.parametrize(
        "target_role",
        [
            UserRole.owner,
            UserRole.partner,
            UserRole.client_admin,
            UserRole.client_manager,
            UserRole.client_viewer,
            UserRole.b2c_user,
        ],
    )
    def test_owner_can_create_any_role(self, target_role):
        """owner can create users with any role."""
        requesting_user = _make_user_obj(UserRole.owner)
        target_client_id = uuid.uuid4()

        # Should not raise
        validate_team_management(
            requesting_user=requesting_user,
            target_role=target_role,
            target_client_id=target_client_id,
        )

    @pytest.mark.parametrize(
        "target_role",
        [
            UserRole.qa,
            UserRole.client_admin,
            UserRole.client_manager,
            UserRole.client_viewer,
            UserRole.b2c_user,
        ],
    )
    def test_partner_can_create_lower_roles(self, target_role):
        """partner can create roles below themselves (not owner/partner)."""
        requesting_user = _make_user_obj(UserRole.partner)
        target_client_id = uuid.uuid4()

        # Should not raise
        validate_team_management(
            requesting_user=requesting_user,
            target_role=target_role,
            target_client_id=target_client_id,
        )

    @pytest.mark.parametrize("target_role", [UserRole.owner, UserRole.partner])
    def test_partner_cannot_create_owner_or_partner(self, target_role):
        """partner CANNOT create owner or partner roles."""
        requesting_user = _make_user_obj(UserRole.partner)
        target_client_id = uuid.uuid4()

        with pytest.raises(HTTPException) as exc_info:
            validate_team_management(
                requesting_user=requesting_user,
                target_role=target_role,
                target_client_id=target_client_id,
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.parametrize("requesting_role", [UserRole.owner, UserRole.partner])
    def test_owner_partner_can_manage_cross_company(self, requesting_role):
        """owner/partner can manage users in any company."""
        requesting_user = _make_user_obj(requesting_role, client_id=uuid.uuid4())
        other_client_id = uuid.uuid4()

        # Should not raise even for a different client
        validate_team_management(
            requesting_user=requesting_user,
            target_role=UserRole.client_manager,
            target_client_id=other_client_id,
        )


# ---------------------------------------------------------------------------
# Tests: client_admin can manage team within own company
# ---------------------------------------------------------------------------


class TestClientAdminTeamManagement:
    """client_admin can manage client_manager and client_viewer within own company."""

    def test_client_admin_can_create_client_manager(self):
        """client_admin can create client_manager in own company."""
        company_id = uuid.uuid4()
        requesting_user = _make_user_obj(UserRole.client_admin, client_id=company_id)

        # Should not raise
        validate_team_management(
            requesting_user=requesting_user,
            target_role=UserRole.client_manager,
            target_client_id=company_id,
        )

    def test_client_admin_can_create_client_viewer(self):
        """client_admin can create client_viewer in own company."""
        company_id = uuid.uuid4()
        requesting_user = _make_user_obj(UserRole.client_admin, client_id=company_id)

        # Should not raise
        validate_team_management(
            requesting_user=requesting_user,
            target_role=UserRole.client_viewer,
            target_client_id=company_id,
        )

    def test_client_admin_cannot_create_client_admin(self):
        """client_admin CANNOT create another client_admin."""
        company_id = uuid.uuid4()
        requesting_user = _make_user_obj(UserRole.client_admin, client_id=company_id)

        with pytest.raises(HTTPException) as exc_info:
            validate_team_management(
                requesting_user=requesting_user,
                target_role=UserRole.client_admin,
                target_client_id=company_id,
            )
        assert exc_info.value.status_code == 403
        assert "Access Denied" in exc_info.value.detail

    def test_client_admin_cannot_create_owner(self):
        """client_admin CANNOT create owner role."""
        company_id = uuid.uuid4()
        requesting_user = _make_user_obj(UserRole.client_admin, client_id=company_id)

        with pytest.raises(HTTPException) as exc_info:
            validate_team_management(
                requesting_user=requesting_user,
                target_role=UserRole.owner,
                target_client_id=company_id,
            )
        assert exc_info.value.status_code == 403

    def test_client_admin_cannot_create_partner(self):
        """client_admin CANNOT create partner role."""
        company_id = uuid.uuid4()
        requesting_user = _make_user_obj(UserRole.client_admin, client_id=company_id)

        with pytest.raises(HTTPException) as exc_info:
            validate_team_management(
                requesting_user=requesting_user,
                target_role=UserRole.partner,
                target_client_id=company_id,
            )
        assert exc_info.value.status_code == 403

    def test_client_admin_cannot_manage_other_company(self):
        """client_admin CANNOT manage users in another company."""
        own_company_id = uuid.uuid4()
        other_company_id = uuid.uuid4()
        requesting_user = _make_user_obj(UserRole.client_admin, client_id=own_company_id)

        with pytest.raises(HTTPException) as exc_info:
            validate_team_management(
                requesting_user=requesting_user,
                target_role=UserRole.client_manager,
                target_client_id=other_company_id,
            )
        assert exc_info.value.status_code == 403
        assert "Access Denied" in exc_info.value.detail

    def test_client_admin_can_manage_without_target_client_id(self):
        """client_admin can manage when target_client_id is None (own company implied)."""
        company_id = uuid.uuid4()
        requesting_user = _make_user_obj(UserRole.client_admin, client_id=company_id)

        # Should not raise — target_client_id=None means no cross-company check
        validate_team_management(
            requesting_user=requesting_user,
            target_role=UserRole.client_manager,
            target_client_id=None,
        )


# ---------------------------------------------------------------------------
# Tests: client_manager CANNOT manage users
# ---------------------------------------------------------------------------


class TestClientManagerCannotManage:
    """client_manager CANNOT manage users at all."""

    @pytest.mark.parametrize(
        "target_role",
        [
            UserRole.client_manager,
            UserRole.client_viewer,
            UserRole.client_admin,
            UserRole.b2c_user,
        ],
    )
    def test_client_manager_denied_all_user_management(self, target_role):
        """client_manager is denied for any user management operation."""
        company_id = uuid.uuid4()
        requesting_user = _make_user_obj(UserRole.client_manager, client_id=company_id)

        with pytest.raises(HTTPException) as exc_info:
            validate_team_management(
                requesting_user=requesting_user,
                target_role=target_role,
                target_client_id=company_id,
            )
        assert exc_info.value.status_code == 403
        assert "Access Denied" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Tests: other roles CANNOT manage users
# ---------------------------------------------------------------------------


class TestOtherRolesCannotManage:
    """client_viewer and b2c_user CANNOT manage users."""

    @pytest.mark.parametrize("role", [UserRole.client_viewer, UserRole.b2c_user])
    def test_viewer_and_b2c_denied(self, role):
        """client_viewer and b2c_user are denied user management."""
        company_id = uuid.uuid4()
        requesting_user = _make_user_obj(role, client_id=company_id)

        with pytest.raises(HTTPException) as exc_info:
            validate_team_management(
                requesting_user=requesting_user,
                target_role=UserRole.client_manager,
                target_client_id=company_id,
            )
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Tests: validate_user_deactivation
# ---------------------------------------------------------------------------


class TestValidateUserDeactivation:
    """validate_user_deactivation delegates to validate_team_management."""

    def test_client_admin_can_deactivate_client_manager(self):
        """client_admin can deactivate a client_manager in own company."""
        company_id = uuid.uuid4()
        requesting_user = _make_user_obj(UserRole.client_admin, client_id=company_id)
        target_user = _make_user_obj(UserRole.client_manager, client_id=company_id)

        # Should not raise
        validate_user_deactivation(
            requesting_user=requesting_user,
            target_user=target_user,
        )

    def test_client_admin_cannot_deactivate_client_admin(self):
        """client_admin CANNOT deactivate another client_admin."""
        company_id = uuid.uuid4()
        requesting_user = _make_user_obj(UserRole.client_admin, client_id=company_id)
        target_user = _make_user_obj(UserRole.client_admin, client_id=company_id)

        with pytest.raises(HTTPException) as exc_info:
            validate_user_deactivation(
                requesting_user=requesting_user,
                target_user=target_user,
            )
        assert exc_info.value.status_code == 403

    def test_client_admin_cannot_deactivate_other_company_user(self):
        """client_admin CANNOT deactivate a user from another company."""
        own_company_id = uuid.uuid4()
        other_company_id = uuid.uuid4()
        requesting_user = _make_user_obj(UserRole.client_admin, client_id=own_company_id)
        target_user = _make_user_obj(UserRole.client_manager, client_id=other_company_id)

        with pytest.raises(HTTPException) as exc_info:
            validate_user_deactivation(
                requesting_user=requesting_user,
                target_user=target_user,
            )
        assert exc_info.value.status_code == 403

    def test_client_manager_cannot_deactivate_anyone(self):
        """client_manager CANNOT deactivate any user."""
        company_id = uuid.uuid4()
        requesting_user = _make_user_obj(UserRole.client_manager, client_id=company_id)
        target_user = _make_user_obj(UserRole.client_viewer, client_id=company_id)

        with pytest.raises(HTTPException) as exc_info:
            validate_user_deactivation(
                requesting_user=requesting_user,
                target_user=target_user,
            )
        assert exc_info.value.status_code == 403

    def test_owner_can_deactivate_anyone(self):
        """owner can deactivate any user."""
        requesting_user = _make_user_obj(UserRole.owner)
        target_user = _make_user_obj(UserRole.client_admin, client_id=uuid.uuid4())

        # Should not raise
        validate_user_deactivation(
            requesting_user=requesting_user,
            target_user=target_user,
        )


# ---------------------------------------------------------------------------
# Tests: legacy is_superuser backward compatibility
# ---------------------------------------------------------------------------


class TestLegacySuperuserCompat:
    """Users with is_superuser=True bypass team management checks."""

    def test_legacy_superuser_can_manage_any_role(self):
        """is_superuser=True grants full user management access."""
        requesting_user = _make_user_obj(
            UserRole.client_manager,  # role doesn't matter
            is_superuser=True,
        )

        # Should not raise even for client_admin creation
        validate_team_management(
            requesting_user=requesting_user,
            target_role=UserRole.client_admin,
            target_client_id=uuid.uuid4(),
        )
