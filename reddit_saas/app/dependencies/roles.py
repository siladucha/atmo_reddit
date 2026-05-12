"""Role-based access control dependencies.

Provides FastAPI dependencies that check user roles before allowing access.
These complement (and eventually replace) the legacy `require_superuser` dependency.
"""

import uuid
from typing import Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.user_role import UserRole


def _get_authenticated_user(request: Request, db: Session) -> User:
    """Extract and validate the authenticated user from request state."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=303, headers={"Location": "/login"})

    try:
        user_uuid = uuid.UUID(user_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=303, headers={"Location": "/login"})

    user = (
        db.query(User)
        .filter(User.id == user_uuid, User.is_active.is_(True))
        .first()
    )
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})

    return user


def require_role(*allowed_roles: UserRole) -> Callable:
    """Create a dependency that requires the user to have one of the specified roles.

    Usage:
        @router.get("/admin/settings")
        def settings_page(user: User = Depends(require_role(UserRole.owner))):
            ...

        @router.get("/admin/clients")
        def clients_page(user: User = Depends(require_role(UserRole.owner, UserRole.partner))):
            ...
    """

    async def dependency(request: Request, db: Session = Depends(get_db)) -> User:
        user = _get_authenticated_user(request, db)
        user_role = user.user_role

        if user_role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Access Denied")

        return user

    return dependency


# Convenience dependencies for common access patterns

async def require_admin(request: Request, db: Session = Depends(get_db)) -> User:
    """Require owner or partner role (admin panel access)."""
    user = _get_authenticated_user(request, db)
    if not user.user_role.is_admin_level:
        # Legacy fallback: is_superuser still grants admin access
        if not user.is_superuser:
            raise HTTPException(status_code=403, detail="Access Denied")
    return user


async def require_internal(request: Request, db: Session = Depends(get_db)) -> User:
    """Require any internal team role (owner, partner, qa)."""
    user = _get_authenticated_user(request, db)
    if not user.user_role.is_internal:
        if not user.is_superuser:
            raise HTTPException(status_code=403, detail="Access Denied")
    return user


async def require_reviewer(request: Request, db: Session = Depends(get_db)) -> User:
    """Require a role that can approve/reject drafts."""
    user = _get_authenticated_user(request, db)
    if not user.user_role.can_review:
        if not user.is_superuser:
            raise HTTPException(status_code=403, detail="Access Denied")
    return user


async def require_owner(request: Request, db: Session = Depends(get_db)) -> User:
    """Require owner role (system settings, kill switches)."""
    user = _get_authenticated_user(request, db)
    if user.user_role != UserRole.owner:
        if not user.is_superuser:
            raise HTTPException(status_code=403, detail="Access Denied")
    return user
