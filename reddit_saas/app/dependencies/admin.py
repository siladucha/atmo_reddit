"""Admin dependencies — superuser access control for admin routes."""

import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.user_role import UserRole


async def require_superuser(
    request: Request, db: Session = Depends(get_db)
) -> User:
    """Dependency that ensures the current user has admin-level access.

    Accepts: owner, partner roles (or legacy is_superuser=True).
    QA role gets limited admin access via separate dependency.

    Returns the User object for use in route handlers.
    Raises HTTPException(303) redirect to /login if unauthenticated.
    Raises HTTPException(403) if user not found, inactive, or insufficient role.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=303, headers={"Location": "/login"})

    # AuthMiddleware stores user_id as a string (JWT "sub" field).
    # Convert to UUID for the DB query.
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
        raise HTTPException(status_code=403, detail="Access Denied")

    # Accept admin-level roles OR legacy is_superuser flag
    if user.user_role.is_admin_level or user.is_superuser:
        return user

    raise HTTPException(status_code=403, detail="Access Denied")
