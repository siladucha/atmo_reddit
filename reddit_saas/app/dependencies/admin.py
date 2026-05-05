"""Admin dependencies — superuser access control for admin routes."""

import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User


async def require_superuser(
    request: Request, db: Session = Depends(get_db)
) -> User:
    """Dependency that ensures the current user is an active superuser.

    Returns the User object for use in route handlers.
    Raises HTTPException(303) redirect to /login if unauthenticated.
    Raises HTTPException(403) if user not found, inactive, or not superuser.
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
    if not user or not user.is_superuser:
        raise HTTPException(status_code=403, detail="Access Denied")

    return user
