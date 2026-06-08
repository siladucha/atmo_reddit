"""Access control service — conditional permission checks beyond role-based guards.

This module provides business-logic-level access control functions that depend
on both user role AND client configuration flags. These complement the
role-based permission guards in app/dependencies/permissions.py.

Example: client_viewer can approve drafts only if the client has
`draft_approval_enabled=True`.
"""

from __future__ import annotations

from app.logging_config import get_logger
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from fastapi import HTTPException

from app.models.user import User
from app.models.client import Client
from app.models.user_role import UserRole

logger = get_logger(__name__)


def can_approve_drafts(user: User, client: Client) -> bool:
    """Check if a user can approve/reject/edit drafts for the given client.

    Rules:
    - owner, partner, qa, client_admin, client_manager: always True
    - client_viewer: True only if client.draft_approval_enabled is True
    - b2c_user: False (B2C users don't have draft approval access)
    - Any other role: False

    Args:
        user: The authenticated user requesting draft approval access.
        client: The client whose drafts are being accessed.

    Returns:
        True if the user can approve/reject/edit drafts, False otherwise.
    """
    if user.user_role in (
        UserRole.owner,
        UserRole.partner,
        UserRole.qa,
        UserRole.client_admin,
        UserRole.client_manager,
    ):
        return True

    if user.user_role == UserRole.client_viewer:
        return bool(client.draft_approval_enabled)

    return False


def check_avatar_limit(db: Session, client: Client, user: User) -> None:
    """Check if the client has reached their max_avatars limit.

    Platform admins (owner/partner) bypass this check entirely — they can
    create avatars regardless of plan limits.

    For all other roles, counts avatars whose `client_ids` ARRAY contains
    the client's ID and compares against `client.max_avatars`.

    Args:
        db: SQLAlchemy database session.
        client: The client for which the avatar is being created.
        user: The authenticated user performing the creation.

    Raises:
        HTTPException: 403 with detail "Maximum avatars reached for your plan"
                       if the client has reached or exceeded their avatar limit.
    """
    from app.models.avatar import Avatar

    # Owner and partner can override — no limit check for platform admins
    if user.user_role in (UserRole.owner, UserRole.partner):
        return

    # Count avatars currently assigned to this client
    client_id_str = str(client.id)
    current_count = (
        db.query(Avatar)
        .filter(Avatar.client_ids.any(client_id_str))
        .count()
    )

    if current_count >= client.max_avatars:
        raise HTTPException(
            status_code=403,
            detail="Maximum avatars reached for your plan",
        )


def check_b2c_avatar_limit(db: Session, user: User) -> None:
    """Check if a B2C user has reached their single avatar limit.

    B2C users are allowed exactly one avatar. This function should be called
    before avatar creation to enforce the limit.

    If the user is not a b2c_user, this function returns immediately (no-op).
    If the user is a b2c_user and already has an avatar, raises HTTP 403.

    Args:
        db: SQLAlchemy database session.
        user: The authenticated user attempting to create an avatar.

    Raises:
        HTTPException: 403 if the B2C user already has an avatar.
    """
    if user.user_role != UserRole.b2c_user:
        return

    from app.models.avatar import Avatar

    client_id_str = str(user.client_id) if user.client_id else None
    if not client_id_str:
        # B2C user without a client_id — cannot own avatars at all
        raise HTTPException(
            status_code=403,
            detail="B2C users can have only one avatar",
        )

    existing_count = (
        db.query(Avatar)
        .filter(Avatar.client_ids.any(client_id_str))
        .count()
    )

    if existing_count >= 1:
        raise HTTPException(
            status_code=403,
            detail="B2C users can have only one avatar",
        )


def upgrade_b2c_to_b2b(
    db: Session,
    user: User,
    company_name: str,
    brand_name: str,
) -> Client:
    """Upgrade a B2C user to a B2B client_admin with a proper client record.

    This function:
    1. Validates the user currently has the b2c_user role
    2. Creates a new Client record with the provided company/brand names
    3. Finds the user's existing personal avatar and reassigns it to the new client
    4. Updates the user's role to client_admin and sets their client_id

    After upgrade, the user can create up to (client.max_avatars - 1) additional
    avatars since they already have 1 (the converted personal avatar).

    Args:
        db: SQLAlchemy database session.
        user: The User instance to upgrade. Must have role == b2c_user.
        company_name: Name for the new client/company record.
        brand_name: Brand name for the new client record.

    Returns:
        The newly created Client record.

    Raises:
        ValueError: If the user's role is not b2c_user, or if company_name/brand_name
                    are empty.
    """
    from app.models.avatar import Avatar

    # Validate user role
    if user.user_role != UserRole.b2c_user:
        raise ValueError(
            f"Only b2c_user accounts can be upgraded to B2B. "
            f"Current role: {user.user_role.value}"
        )

    # Validate inputs
    if not company_name or not company_name.strip():
        raise ValueError("company_name is required")
    if not brand_name or not brand_name.strip():
        raise ValueError("brand_name is required")

    company_name = company_name.strip()
    brand_name = brand_name.strip()

    # Create a new Client record
    new_client = Client(
        client_name=company_name,
        brand_name=brand_name,
        is_active=True,
        max_avatars=3,  # Default plan allows 3 avatars
        plan_type="starter",
    )
    db.add(new_client)
    db.flush()  # Get the new client.id without committing

    logger.info(
        "B2C_TO_B2B_UPGRADE | user_id=%s | new_client_id=%s | company=%s",
        user.id,
        new_client.id,
        company_name,
    )

    # Find the user's existing personal avatar
    # B2C users have exactly one avatar linked via their client_id
    old_client_id_str = str(user.client_id) if user.client_id else None
    personal_avatar: Avatar | None = None

    if old_client_id_str:
        personal_avatar = (
            db.query(Avatar)
            .filter(Avatar.client_ids.any(old_client_id_str))
            .first()
        )

    # Convert personal avatar to first company avatar
    if personal_avatar:
        new_client_id_str = str(new_client.id)
        # Replace old personal client_id with new company client_id
        updated_client_ids = [
            cid for cid in (personal_avatar.client_ids or [])
            if cid != old_client_id_str
        ]
        updated_client_ids.append(new_client_id_str)
        personal_avatar.client_ids = updated_client_ids

        logger.info(
            "B2C_TO_B2B_UPGRADE | avatar=%s reassigned to client=%s",
            personal_avatar.reddit_username,
            new_client.id,
        )
    else:
        logger.warning(
            "B2C_TO_B2B_UPGRADE | user_id=%s | no personal avatar found",
            user.id,
        )

    # Update user role and client assignment
    user.role = UserRole.client_admin.value
    user.client_id = new_client.id

    db.flush()

    logger.info(
        "B2C_TO_B2B_UPGRADE | complete | user_id=%s | role=%s | client_id=%s",
        user.id,
        user.role,
        user.client_id,
    )

    return new_client
