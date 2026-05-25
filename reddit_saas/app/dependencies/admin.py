"""Admin dependencies — superuser access control for admin routes.

This module preserves the `require_superuser` dependency for backward
compatibility. Internally it delegates to `require_platform_admin` from
the new RBAC permissions module.
"""

from fastapi import Depends, HTTPException

from app.dependencies.permissions import get_current_user, require_platform_admin
from app.models.user import User
from app.models.user_role import UserRole


async def require_superuser(
    user: User = Depends(require_platform_admin),
) -> User:
    """Dependency that ensures the current user has admin-level access.

    Delegates to `require_platform_admin` which accepts owner, partner roles
    (or legacy is_superuser=True).

    Returns the User object for use in route handlers.
    Raises HTTPException(303) redirect to /login if unauthenticated/inactive.
    Raises HTTPException(403) if insufficient role.

    This function exists for backward compatibility — all existing admin routes
    use `require_superuser` and continue to work without modification.
    """
    return user


async def require_avatar_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Dependency for avatar management endpoints in admin panel.

    Allows:
    - owner/partner (platform admins) — full avatar access
    - avatar_manager — can view unassigned avatars and create new ones

    Raises 403 for all other roles.
    """
    if user.user_role in (UserRole.owner, UserRole.partner, UserRole.avatar_manager):
        return user
    if user.is_superuser:
        return user
    raise HTTPException(status_code=403, detail="Access Denied")


async def require_user_management_access(
    user: User = Depends(get_current_user),
) -> User:
    """Dependency for user management endpoints.

    Allows:
    - owner/partner (platform admins) — can manage any user
    - client_admin — can manage team within own company (further scoped by
      validate_team_management in the route handler)

    Raises 403 for all other roles.
    """
    if user.user_role in (UserRole.owner, UserRole.partner):
        return user
    if user.is_superuser:
        return user
    if user.user_role == UserRole.client_admin:
        return user
    raise HTTPException(status_code=403, detail="Access Denied")
