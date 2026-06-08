"""Client data isolation helpers for LLM context assembly and pipeline guards.

Provides shared utility functions for verifying that avatars and other
tenant-owned entities are accessible by a given client. Used by the generation
service, persona selection, and query scoping layer.
"""

from app.logging_config import get_logger

from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.avatar_rental import AvatarRental
from app.models.client import Client

logger = get_logger(__name__)


def _avatar_accessible_by_client(db: Session, avatar: Avatar, client: Client) -> bool:
    """Check if an avatar is owned by or actively rented to the client.

    An avatar is accessible if:
    1. The client's ID is present in the avatar's `client_ids` ARRAY (ownership), OR
    2. There is an active, non-expired rental record in `avatar_rentals` linking
       the avatar to the client.

    Args:
        db: SQLAlchemy database session.
        avatar: The Avatar instance to check.
        client: The Client instance requesting access.

    Returns:
        True if the avatar is accessible by the client, False otherwise.
    """
    # Check ownership via client_ids ARRAY
    if avatar.client_ids and str(client.id) in avatar.client_ids:
        return True

    # Check rental via avatar_rentals table (active + not expired)
    rental = db.query(AvatarRental).filter(
        AvatarRental.avatar_id == avatar.id,
        AvatarRental.client_id == client.id,
        AvatarRental.is_active == True,  # noqa: E712
        or_(
            AvatarRental.expires_at == None,  # noqa: E711
            AvatarRental.expires_at > func.now(),
        ),
    ).first()

    return rental is not None
