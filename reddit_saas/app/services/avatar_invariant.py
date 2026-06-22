"""Avatar Invariant Service — enforces Client ACTIVE => has Avatar constraint.

Enforcement points:
1. step6_activate: block if no avatar
2. Avatar deactivation (freeze/unassign): deactivate client if last avatar removed
3. Avatar assignment (BYOA confirm / admin assign): reactivate client
4. Daily integrity check (Celery Beat): catch edge cases
"""

import uuid

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.avatar import Avatar
from app.models.client import Client

logger = get_logger(__name__)


def has_active_avatar(client_id: uuid.UUID, db: Session) -> bool:
    """Check if client has at least one active, assigned avatar.

    Args:
        client_id: Client UUID
        db: Database session

    Returns:
        True if at least one qualifying Avatar exists
    """
    count = (
        db.query(Avatar)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            Avatar.active.is_(True),
            Avatar.is_frozen.is_(False),  # Frozen avatars can't participate in pipeline
        )
        .count()
    )
    return count > 0


def enforce_invariant_on_deactivation(client_id: uuid.UUID, db: Session) -> None:
    """Called after an avatar is deactivated or unassigned from a client.

    If no active avatars remain, deactivates the client (sets is_active=False).
    This causes all pipeline tasks to skip this client.

    Args:
        client_id: Client UUID
        db: Database session
    """
    if has_active_avatar(client_id, db):
        return  # Still has avatars, nothing to do

    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return

    if client.is_active:
        client.is_active = False
        db.commit()

        logger.warning(
            "INVARIANT_DEACTIVATION | client_id=%s | name=%s | reason=no_active_avatars",
            str(client_id), client.client_name,
        )

        # Emit notification for admin visibility
        try:
            from app.services.transparency import record_activity_event
            record_activity_event(
                db=db,
                client_id=str(client_id),
                event_type="client_paused",
                description=f"Client '{client.client_name}' paused: last avatar deactivated or unassigned",
                details={"reason": "no_active_avatars", "action": "client_deactivated"},
            )
        except Exception as e:
            logger.warning("Failed to record invariant deactivation event: %s", e)


def enforce_invariant_on_activation(client_id: uuid.UUID, db: Session) -> None:
    """Called after an avatar is confirmed/assigned to a client.

    If client was previously deactivated due to zero avatars (has onboarding_completed_at
    but is_active=False), reactivates the client.

    Args:
        client_id: Client UUID
        db: Database session
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return

    # Only reactivate if onboarding was completed but client is currently inactive
    if client.onboarding_completed_at and not client.is_active:
        if has_active_avatar(client_id, db):
            client.is_active = True
            db.commit()

            logger.info(
                "INVARIANT_REACTIVATION | client_id=%s | name=%s | reason=avatar_assigned",
                str(client_id), client.client_name,
            )

            try:
                from app.services.transparency import record_activity_event
                record_activity_event(
                    db=db,
                    client_id=str(client_id),
                    event_type="client_reactivated",
                    description=f"Client '{client.client_name}' reactivated: avatar assigned",
                    details={"reason": "avatar_assigned", "action": "client_reactivated"},
                )
            except Exception as e:
                logger.warning("Failed to record invariant reactivation event: %s", e)


def check_activation_allowed(client_id: uuid.UUID, db: Session) -> tuple[bool, str]:
    """Check if client can be activated (has at least one avatar).

    Used by step6_activate to gate onboarding completion.

    Returns:
        (allowed: bool, error_message: str)
    """
    if has_active_avatar(client_id, db):
        return True, ""
    return False, "At least one confirmed avatar is required to activate your account."
