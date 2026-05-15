"""Avatar limit enforcement — checks plan-based avatar limits for clients.

Provides `check_avatar_limit()` which verifies that a client has not exceeded
their `max_avatars` plan limit before allowing avatar creation or assignment.

Platform admins (owner/partner) bypass the limit check entirely.
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.client import Client
from app.models.user import User
from app.models.user_role import UserRole

logger = logging.getLogger(__name__)


def count_client_avatars(db: Session, client_id) -> int:
    """Count the number of avatars currently assigned to a client.

    An avatar belongs to a client if str(client_id) is in its client_ids array.
    """
    client_id_str = str(client_id)
    avatars = db.query(Avatar).filter(Avatar.active.is_(True)).all()
    return sum(
        1 for a in avatars
        if a.client_ids and client_id_str in a.client_ids
    )


def check_avatar_limit(
    db: Session,
    client: Client,
    user: Optional[User] = None,
) -> Optional[str]:
    """Check if the client has reached their max_avatars limit.

    Returns None if avatar creation is allowed, or an error message string
    if the limit has been reached.

    Platform admins (owner/partner) bypass the limit check — they can create
    unlimited avatars for any client.

    Args:
        db: SQLAlchemy database session.
        client: The client to check the limit for.
        user: The user performing the action. If None or platform admin,
              the limit check is bypassed.

    Returns:
        None if creation is allowed, or error message string if limit exceeded.
    """
    # Owner/partner bypass — no limit check for platform admins
    if user is not None:
        if user.user_role in (UserRole.owner, UserRole.partner):
            return None
        # Legacy backward compat: is_superuser also bypasses
        if user.is_superuser:
            return None

    # If no user context provided (system/background), bypass the check
    if user is None:
        return None

    # Check the limit
    current_count = count_client_avatars(db, client.id)
    max_allowed = client.max_avatars or 3  # Default to 3 if not set

    if current_count >= max_allowed:
        logger.info(
            "Avatar limit reached | client=%s | current=%d | max=%d | user=%s",
            client.id,
            current_count,
            max_allowed,
            user.id if user else "system",
        )
        return "Maximum avatars reached for your plan"

    return None
