"""Action executor registry — maps action_type to handler functions.

Each handler receives (db, client_id, user_id, payload) and performs
the business logic that was deferred by the approval_required tier.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session


def _execute_add_subreddit(
    db: Session,
    client_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: dict | None,
) -> None:
    """Execute the add_subreddit action after approval.

    Finds or creates a Subreddit record, then creates a ClientSubredditAssignment
    linking it to the client.
    """
    if not payload or "subreddit_name" not in payload:
        return

    from app.models.subreddit import Subreddit, ClientSubredditAssignment

    subreddit_name = payload["subreddit_name"].strip().removeprefix("r/")
    if not subreddit_name:
        return

    # Find or create the subreddit record (case-insensitive lookup)
    subreddit = (
        db.query(Subreddit)
        .filter(func.lower(Subreddit.subreddit_name) == subreddit_name.lower())
        .first()
    )
    if not subreddit:
        subreddit = Subreddit(subreddit_name=subreddit_name, is_active=True)
        db.add(subreddit)
        db.flush()

    # Check for existing assignment (active or inactive)
    existing = (
        db.query(ClientSubredditAssignment)
        .filter(
            ClientSubredditAssignment.client_id == client_id,
            ClientSubredditAssignment.subreddit_id == subreddit.id,
        )
        .first()
    )

    if existing:
        # Reactivate if inactive
        if not existing.is_active:
            existing.is_active = True
    else:
        # Create new assignment
        assignment = ClientSubredditAssignment(
            client_id=client_id,
            subreddit_id=subreddit.id,
            type=payload.get("type", "professional"),
            is_active=True,
        )
        db.add(assignment)

    db.commit()


def _execute_remove_subreddit(
    db: Session,
    client_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: dict | None,
) -> None:
    """Execute subreddit removal after approval.

    Deactivates the ClientSubredditAssignment (soft-delete).
    """
    if not payload or "subreddit_name" not in payload:
        return

    from app.models.subreddit import Subreddit, ClientSubredditAssignment

    subreddit_name = payload["subreddit_name"].strip().removeprefix("r/")
    if not subreddit_name:
        return

    # Find the subreddit
    subreddit = (
        db.query(Subreddit)
        .filter(func.lower(Subreddit.subreddit_name) == subreddit_name.lower())
        .first()
    )
    if not subreddit:
        return

    # Deactivate the assignment
    assignment = (
        db.query(ClientSubredditAssignment)
        .filter(
            ClientSubredditAssignment.client_id == client_id,
            ClientSubredditAssignment.subreddit_id == subreddit.id,
            ClientSubredditAssignment.is_active == True,  # noqa: E712
        )
        .first()
    )

    if assignment:
        assignment.is_active = False
        db.commit()


def _execute_request_avatar_freeze(
    db: Session,
    client_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: dict | None,
) -> None:
    """Freeze an avatar after approval.

    Sets is_frozen=True with freeze_reason and frozen_at timestamp.
    """
    if not payload or "avatar_id" not in payload:
        return

    from app.models.avatar import Avatar

    try:
        avatar_id = uuid.UUID(str(payload["avatar_id"]))
    except (ValueError, TypeError):
        return

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return

    # Verify the avatar belongs to this client
    if avatar.client_ids and str(client_id) not in avatar.client_ids:
        return

    avatar.is_frozen = True
    avatar.freeze_reason = payload.get("freeze_reason", "Client requested freeze")
    avatar.frozen_at = datetime.now(timezone.utc)
    db.commit()


def _execute_request_avatar_unfreeze(
    db: Session,
    client_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: dict | None,
) -> None:
    """Unfreeze an avatar after approval.

    Sets is_frozen=False and clears freeze_reason.
    """
    if not payload or "avatar_id" not in payload:
        return

    from app.models.avatar import Avatar

    try:
        avatar_id = uuid.UUID(str(payload["avatar_id"]))
    except (ValueError, TypeError):
        return

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return

    # Verify the avatar belongs to this client
    if avatar.client_ids and str(client_id) not in avatar.client_ids:
        return

    avatar.is_frozen = False
    avatar.freeze_reason = None
    avatar.frozen_at = None
    db.commit()


def _execute_change_brand_guardrails(
    db: Session,
    client_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: dict | None,
) -> None:
    """Update brand guardrails after approval.

    Replaces the client's brand_guardrails JSONB field with the new value.
    """
    if not payload or "guardrails" not in payload:
        return

    from sqlalchemy.orm.attributes import flag_modified
    from app.models.client import Client

    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return

    client.brand_guardrails = payload["guardrails"]
    flag_modified(client, "brand_guardrails")
    db.commit()


ACTION_EXECUTORS: dict[str, callable] = {
    "add_subreddit": _execute_add_subreddit,
    "remove_subreddit": _execute_remove_subreddit,
    "request_avatar_freeze": _execute_request_avatar_freeze,
    "request_avatar_unfreeze": _execute_request_avatar_unfreeze,
    "change_brand_guardrails": _execute_change_brand_guardrails,
}
