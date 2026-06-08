"""Team management permission enforcement.

Validates that a requesting user has the authority to create, edit, or
deactivate another user with a given target role and client scope.

Rules:
- owner/partner: can manage any user for any client (including client_admin)
- client_admin: can manage client_manager and client_viewer within own company ONLY
- client_admin CANNOT create/promote to client_admin (only owner/partner can)
- client_manager and below: CANNOT manage users at all
"""

from app.logging_config import get_logger
import uuid

from fastapi import HTTPException

from app.models.user import User
from app.models.user_role import UserRole

logger = get_logger(__name__)

# Roles that a client_admin is allowed to create/edit/deactivate
_CLIENT_ADMIN_MANAGEABLE_ROLES = frozenset({
    UserRole.client_manager,
    UserRole.client_viewer,
})


def validate_team_management(
    requesting_user: User,
    target_role: UserRole,
    target_client_id: uuid.UUID | None = None,
) -> None:
    """Validate that requesting_user can manage a user with target_role at target_client_id.

    This function should be called before any user creation, role change, or
    deactivation operation to enforce team management scope.

    Args:
        requesting_user: The authenticated user performing the action.
        target_role: The role of the user being created/edited/deactivated.
        target_client_id: The client_id of the target user. Required for
            client-scoped operations.

    Raises:
        HTTPException(403): If the requesting user lacks permission.
    """
    role = requesting_user.user_role

    # owner: allow any role creation for any client
    if role == UserRole.owner:
        return

    # partner: can create any role BELOW themselves (not owner, not partner)
    if role == UserRole.partner:
        if target_role in (UserRole.owner, UserRole.partner):
            logger.warning(
                "RBAC: partner attempted to create role=%s | "
                "requesting_user=%s | target_client_id=%s",
                target_role.value,
                requesting_user.id,
                target_client_id,
            )
            raise HTTPException(
                status_code=403,
                detail="Access Denied — partners cannot create owner or partner roles",
            )
        return

    # Legacy backward compat: is_superuser grants platform admin (owner-level)
    if requesting_user.is_superuser:
        return

    # client_admin: can manage team within own company
    if role == UserRole.client_admin:
        # client_admin CANNOT create another client_admin
        if target_role == UserRole.client_admin:
            logger.warning(
                "RBAC: client_admin attempted to create client_admin | "
                "requesting_user=%s | target_client_id=%s",
                requesting_user.id,
                target_client_id,
            )
            raise HTTPException(
                status_code=403,
                detail="Access Denied",
            )

        # client_admin can only manage client_manager and client_viewer
        if target_role not in _CLIENT_ADMIN_MANAGEABLE_ROLES:
            logger.warning(
                "RBAC: client_admin attempted to manage role=%s | "
                "requesting_user=%s | target_client_id=%s",
                target_role.value,
                requesting_user.id,
                target_client_id,
            )
            raise HTTPException(
                status_code=403,
                detail="Access Denied",
            )

        # client_admin can only manage users within own company
        if target_client_id and requesting_user.client_id != target_client_id:
            logger.warning(
                "RBAC: client_admin attempted cross-company user management | "
                "requesting_user=%s | own_client=%s | target_client=%s",
                requesting_user.id,
                requesting_user.client_id,
                target_client_id,
            )
            raise HTTPException(
                status_code=403,
                detail="Access Denied",
            )

        # All checks passed for client_admin
        return

    # All other roles (client_manager, client_viewer, b2c_user, qa): DENY
    logger.warning(
        "RBAC: unauthorized user management attempt | "
        "requesting_user=%s | role=%s | target_role=%s",
        requesting_user.id,
        role.value,
        target_role.value,
    )
    raise HTTPException(
        status_code=403,
        detail="Access Denied",
    )


def validate_user_deactivation(
    requesting_user: User,
    target_user: User,
) -> None:
    """Validate that requesting_user can deactivate/reactivate target_user.

    Args:
        requesting_user: The authenticated user performing the action.
        target_user: The user being deactivated/reactivated.

    Raises:
        HTTPException(403): If the requesting user lacks permission.
    """
    target_role = target_user.user_role

    # Use the same validation logic — deactivation follows the same rules
    validate_team_management(
        requesting_user=requesting_user,
        target_role=target_role,
        target_client_id=target_user.client_id,
    )
