"""Permission guards — RBAC dependencies for route protection.

This module provides the base `get_current_user` dependency and role-based
permission guards that enforce access control on every route.

The `get_current_user` dependency is the foundation: it loads the authenticated
user from the JWT cookie, verifies they are active, and returns the User object.
All other permission guards depend on it.

Usage:
    from app.dependencies.permissions import get_current_user, require_platform_admin

    @router.get("/dashboard")
    async def dashboard(user: User = Depends(get_current_user)):
        ...

    @router.get("/admin/settings")
    async def settings(user: User = Depends(require_platform_admin)):
        ...
"""

import logging
import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.client import Client
from app.models.user import User
from app.models.user_role import UserRole

logger = logging.getLogger(__name__)


async def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> User:
    """Base dependency: loads authenticated, active user from JWT.

    Raises 303 redirect to /login if:
    - No JWT token present (user_id not in request.state)
    - JWT token is invalid (user_id cannot be parsed as UUID)
    - User not found in database
    - User is inactive (is_active=False)

    Supports legacy is_superuser flag: users with is_superuser=True
    are treated as having the 'owner' role for backward compatibility.
    """
    # 1. Extract user_id from request state (set by AuthMiddleware)
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=303, headers={"Location": "/login"})

    # 2. Parse user_id as UUID
    try:
        user_uuid = uuid.UUID(user_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=303, headers={"Location": "/login"})

    # 3. Load user from database
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})

    # 4. Check is_active — redirect to /login if inactive
    if not user.is_active:
        logger.warning(
            "RBAC: Inactive user attempted access | user_id=%s | email=%s",
            user.id,
            user.email,
        )
        raise HTTPException(status_code=303, headers={"Location": "/login"})

    # 5. Client deactivation cascade: if the user is client-scoped, check
    # that their client is still active. Deny access immediately if not.
    # This adds ONE DB query only for client-scoped users (not owner/partner).
    if user.user_role.is_client_scoped and user.client_id:
        client = db.query(Client).filter(Client.id == user.client_id).first()
        if not client or not client.is_active:
            logger.warning(
                "RBAC: Client-scoped user denied access — client inactive | "
                "user_id=%s | email=%s | client_id=%s",
                user.id,
                user.email,
                user.client_id,
            )
            raise HTTPException(status_code=403, detail="Access Denied")

    # 6. Legacy is_superuser mapping: the user_role property falls back to
    # owner when is_superuser=True and role is empty/invalid. Log when this
    # fallback is active for visibility during the migration period.
    if user.is_superuser and not user.role:
        logger.debug(
            "RBAC: Legacy is_superuser mapped to owner role | user_id=%s | email=%s",
            user.id,
            user.email,
        )

    return user


async def require_authenticated(user: User = Depends(get_current_user)) -> User:
    """Any active, authenticated user regardless of role.

    Since get_current_user already verifies authentication and is_active,
    this guard simply passes through. Use it to document intent on routes
    that any logged-in user can access.
    """
    return user


async def require_owner(user: User = Depends(get_current_user)) -> User:
    """Only owner role. Raises 403 otherwise.

    Use for system settings, kill switches, and infrastructure controls.
    """
    if user.user_role != UserRole.owner:
        raise HTTPException(status_code=403, detail="Access Denied")
    return user


async def require_platform_admin(user: User = Depends(get_current_user)) -> User:
    """Owner or partner roles. Raises 403 otherwise.

    Also accepts is_superuser=True for backward compatibility with legacy
    accounts that haven't been migrated to explicit roles yet.

    Use for admin panel routes, client management, user management.
    """
    if user.user_role not in (UserRole.owner, UserRole.partner):
        # Legacy backward compat: is_superuser=True also grants platform admin
        if not user.is_superuser:
            raise HTTPException(status_code=403, detail="Access Denied")
    return user


async def require_client_admin(user: User = Depends(get_current_user)) -> User:
    """Only client_admin role (within own company). Raises 403 otherwise.

    Use for team management, avatar deletion, client-level settings.
    """
    if user.user_role != UserRole.client_admin:
        raise HTTPException(status_code=403, detail="Access Denied")
    return user


async def require_client_manager_or_above(
    user: User = Depends(get_current_user),
) -> User:
    """client_admin or client_manager (within own company). Raises 403 otherwise.

    Use for draft approval, subreddit/keyword management, avatar configuration.
    """
    if user.user_role not in (UserRole.client_admin, UserRole.client_manager):
        raise HTTPException(status_code=403, detail="Access Denied")
    return user


def require_client_access(client_id: uuid.UUID):
    """Factory: returns a dependency that verifies the user can access the specified client.

    Access rules:
    - owner/partner: always allowed (platform-wide access)
    - client_admin/client_manager/client_viewer/b2c_user: only if client_id
      matches user.client_id

    Raises 403 "Access Denied" on mismatch. No additional DB queries — uses
    user.client_id from the already-loaded user record.

    Usage:
        @router.get("/clients/{client_id}/drafts")
        async def get_drafts(
            client_id: uuid.UUID,
            user: User = Depends(require_client_access(client_id)),
        ):
            ...
    """

    async def _guard(user: User = Depends(get_current_user)) -> User:
        # Platform-level roles have unrestricted access
        if user.user_role in (UserRole.owner, UserRole.partner):
            return user

        # Legacy backward compat
        if user.is_superuser:
            return user

        # Client-scoped roles must match client_id
        if user.client_id != client_id:
            raise HTTPException(status_code=403, detail="Access Denied")

        return user

    return _guard


async def verify_client_access_from_path(
    request: Request, user: User = Depends(get_current_user)
) -> User:
    """Dependency that validates client_id access from URL path parameters.

    Extracts `client_id` from the request's path parameters and verifies
    the authenticated user has access to that client. This is the path-based
    counterpart to `require_client_access(client_id)` factory.

    Access rules:
    - owner/partner: always allowed (platform-wide access)
    - client_admin/client_manager/client_viewer/b2c_user: only if the path
      client_id matches user.client_id

    If no `client_id` is found in path parameters, the guard passes through
    (the endpoint may not require client scoping).

    Raises 403 "Access Denied" on mismatch. No additional DB queries.
    """
    raw_client_id = request.path_params.get("client_id")
    if raw_client_id is None:
        # No client_id in path — nothing to validate
        return user

    # Parse the client_id from path. If it's not a valid UUID (e.g. "new"
    # in onboarding wizard), skip validation — the endpoint handles it.
    try:
        path_client_id = uuid.UUID(str(raw_client_id))
    except (ValueError, AttributeError):
        return user

    # Platform-level roles have unrestricted access
    if user.user_role in (UserRole.owner, UserRole.partner):
        return user

    # Legacy backward compat
    if user.is_superuser:
        return user

    # Client-scoped roles must match client_id
    if user.client_id != path_client_id:
        raise HTTPException(status_code=403, detail="Access Denied")

    return user


async def require_avatar_manager_or_above(
    user: User = Depends(get_current_user),
) -> User:
    """Owner, partner, or avatar_manager roles. Raises 403 otherwise.

    Use for avatar inventory routes (list unassigned, create new).
    avatar_manager sees only unassigned avatars; owner/partner see all.
    """
    if user.user_role not in (UserRole.owner, UserRole.partner, UserRole.avatar_manager):
        if not user.is_superuser:
            raise HTTPException(status_code=403, detail="Access Denied")
    return user
