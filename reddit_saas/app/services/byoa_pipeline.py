"""BYOA Pipeline Service — orchestration for Bring Your Own Avatar flow.

Handles:
- create_avatar_draft: validate + create + enqueue
- confirm_avatar_draft: create Avatar from draft + trigger pipeline
- reject_avatar_draft: mark as rejected
- cancel_draft: cancel in-progress draft
- check_trial_avatar_limit: enforce trial bounds
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.avatar import Avatar
from app.models.avatar_draft import (
    AvatarDraft,
    DRAFT_STATUS_PENDING_FETCH,
    DRAFT_STATUS_READY_FOR_REVIEW,
    DRAFT_STATUS_CONFIRMED,
    DRAFT_STATUS_REJECTED,
    DRAFT_NON_TERMINAL_STATUSES,
)
from app.models.client import Client

logger = get_logger(__name__)


class BYOAError(Exception):
    """Raised when BYOA operation cannot proceed."""
    pass


def create_avatar_draft(
    reddit_username: str,
    client_id: uuid.UUID,
    user_id: uuid.UUID,
    db: Session,
    desired_role: str = "",
) -> AvatarDraft:
    """Create an AvatarDraft and enqueue the fetch task.

    Validates:
    - Username format (strip u/ prefix, max 20 chars)
    - Global Avatar uniqueness (no existing avatar with this username)
    - Trial limit (combined drafts + avatars <= 1 for trial)
    - Client-scoped draft uniqueness (no active draft for same username)

    Args:
        reddit_username: Reddit username (with or without u/ prefix)
        client_id: Client UUID
        user_id: User UUID who initiated
        db: Database session

    Returns:
        Created AvatarDraft entity

    Raises:
        BYOAError: If validation fails
    """
    # Clean username
    username = reddit_username.strip().replace("u/", "").replace("/u/", "").strip()
    if not username:
        raise BYOAError("Please enter a Reddit username")
    if len(username) > 20:
        raise BYOAError("Reddit usernames are maximum 20 characters")

    # Check global Avatar uniqueness
    existing_avatar = db.query(Avatar).filter(Avatar.reddit_username == username).first()
    if existing_avatar:
        if existing_avatar.client_ids and str(client_id) in existing_avatar.client_ids:
            raise BYOAError(f"u/{username} is already assigned to your account")
        else:
            raise BYOAError(f"u/{username} is already in use by another account")

    # Check trial limit
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise BYOAError("Client not found")

    allowed, error_msg = check_trial_avatar_limit(client_id, db)
    if not allowed:
        raise BYOAError(error_msg)

    # Check client-scoped draft uniqueness (no active draft for same username)
    existing_draft = (
        db.query(AvatarDraft)
        .filter(
            AvatarDraft.reddit_username == username,
            AvatarDraft.client_id == client_id,
            AvatarDraft.status.in_(DRAFT_NON_TERMINAL_STATUSES),
        )
        .first()
    )
    if existing_draft:
        raise BYOAError(f"Analysis for u/{username} is already in progress")

    # Create draft (pre-seed desired_role in snapshot for analysis task to pick up)
    draft = AvatarDraft(
        id=uuid.uuid4(),
        reddit_username=username,
        client_id=client_id,
        created_by_user_id=user_id,
        status=DRAFT_STATUS_PENDING_FETCH,
        reddit_snapshot={"_desired_role": desired_role} if desired_role else None,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)

    # Enqueue fetch task
    from app.tasks.byoa import fetch_reddit_profile_for_draft
    fetch_reddit_profile_for_draft.delay(str(draft.id))

    logger.info(
        "BYOA_DRAFT_CREATED | draft_id=%s | username=%s | client_id=%s | user_id=%s",
        str(draft.id), username, str(client_id), str(user_id),
    )
    return draft


def confirm_avatar_draft(
    draft_id: uuid.UUID,
    user_edits: dict,
    db: Session,
) -> Avatar:
    """Confirm an AvatarDraft and create the Avatar entity.

    Args:
        draft_id: AvatarDraft UUID
        user_edits: Dict with user-edited fields:
            display_name, persona_bio, tone_principles, voice_profile_md,
            hill_i_die_on, helpful_mode_topics, constraints,
            hobby_subreddits, business_subreddits
        db: Database session

    Returns:
        Created Avatar entity

    Raises:
        BYOAError: If draft not in ready_for_review state
    """
    draft = db.query(AvatarDraft).filter(AvatarDraft.id == draft_id).first()
    if not draft:
        raise BYOAError("Draft not found")
    if draft.status != DRAFT_STATUS_READY_FOR_REVIEW:
        raise BYOAError(f"Draft is not ready for review (current status: {draft.status})")

    # Extract AI analysis data as defaults
    ai_data = draft.ai_analysis or {}
    voice = ai_data.get("voice_profile", {})
    strategy = ai_data.get("strategy", {})
    subreddits = ai_data.get("subreddits", {})

    # Parse subreddit lists from user edits or AI defaults
    hobby_raw = user_edits.get("hobby_subreddits", "")
    if isinstance(hobby_raw, str):
        hobby_list = [s.strip() for s in hobby_raw.split(",") if s.strip()]
    else:
        hobby_list = hobby_raw or subreddits.get("hobby", [])

    business_raw = user_edits.get("business_subreddits", "")
    if isinstance(business_raw, str):
        business_list = [s.strip() for s in business_raw.split(",") if s.strip()]
    else:
        business_list = business_raw or subreddits.get("business", [])

    # Create Avatar
    avatar = Avatar(
        id=uuid.uuid4(),
        reddit_username=draft.reddit_username,
        display_name=(user_edits.get("display_name") or ai_data.get("display_name", ""))[:100] or None,
        persona_bio=(user_edits.get("persona_bio") or ai_data.get("persona_bio", ""))[:255] or None,
        voice_profile_md=user_edits.get("voice_profile_md") or voice.get("style", "") or None,
        tone_principles=user_edits.get("tone_principles") or voice.get("tone_principles", "") or None,
        speech_patterns=voice.get("speech_patterns") or None,
        hill_i_die_on=user_edits.get("hill_i_die_on") or strategy.get("hill_i_die_on", "") or None,
        helpful_mode_topics=user_edits.get("helpful_mode_topics") or strategy.get("helpful_mode_topics", "") or None,
        constraints=user_edits.get("constraints") or None,
        vocabulary_lean=voice.get("vocabulary_lean") or None,
        hobby_subreddits=hobby_list if hobby_list else None,
        business_subreddits=[{"subreddit": s, "source": "onboarding"} for s in business_list] if business_list else None,
        client_ids=[str(draft.client_id)],
        active=True,
        warming_phase=1,
        health_status="unknown",
        posting_mode="disabled",
        pool="b2b",
    )
    db.add(avatar)
    db.flush()

    # Update draft — single atomic commit for Avatar + Draft state
    draft.status = DRAFT_STATUS_CONFIRMED
    draft.avatar_id = avatar.id
    draft.confirmed_at = datetime.now(timezone.utc)

    try:
        db.commit()
    except Exception as commit_err:
        db.rollback()
        logger.error("BYOA_CONFIRM | commit failed: %s", commit_err)
        raise BYOAError("Failed to save avatar. Please try again.")

    # Post-commit side effects (non-critical — failures logged but don't block)

    # Trigger post-onboarding pipeline
    try:
        from app.tasks.onboarding import run_avatar_onboarding
        run_avatar_onboarding.delay(str(avatar.id), str(draft.client_id))
        logger.info("BYOA post-onboarding pipeline triggered for avatar %s", avatar.reddit_username)
    except Exception as e:
        logger.warning("Failed to trigger post-onboarding pipeline: %s", e)

    # Enforce invariant: reactivate client if needed
    try:
        from app.services.avatar_invariant import enforce_invariant_on_activation
        enforce_invariant_on_activation(draft.client_id, db)
    except Exception as e:
        logger.warning("Invariant enforcement on activation failed: %s", e)

    logger.info(
        "BYOA_CONFIRMED | draft_id=%s | avatar_id=%s | username=%s | client_id=%s",
        str(draft_id), str(avatar.id), avatar.reddit_username, str(draft.client_id),
    )
    return avatar


def reject_avatar_draft(draft_id: uuid.UUID, db: Session) -> None:
    """Reject an AvatarDraft (user wants to try different account).

    Args:
        draft_id: AvatarDraft UUID
        db: Database session

    Raises:
        BYOAError: If draft not in ready_for_review state
    """
    draft = db.query(AvatarDraft).filter(AvatarDraft.id == draft_id).first()
    if not draft:
        raise BYOAError("Draft not found")
    if draft.status != DRAFT_STATUS_READY_FOR_REVIEW:
        raise BYOAError(f"Can only reject drafts in review state (current: {draft.status})")

    draft.status = DRAFT_STATUS_REJECTED
    db.commit()

    logger.info("BYOA_REJECTED | draft_id=%s | username=%s", str(draft_id), draft.reddit_username)


def cancel_draft(draft_id: uuid.UUID, db: Session) -> None:
    """Cancel an in-progress draft (user submitting new username).

    Marks as rejected so uniqueness constraint is freed for new submission.

    Args:
        draft_id: AvatarDraft UUID
        db: Database session
    """
    draft = db.query(AvatarDraft).filter(AvatarDraft.id == draft_id).first()
    if not draft:
        return

    if draft.status in DRAFT_NON_TERMINAL_STATUSES:
        draft.status = DRAFT_STATUS_REJECTED
        draft.error_message = "Cancelled by user (new submission)"
        db.commit()
        logger.info("BYOA_CANCELLED | draft_id=%s | username=%s", str(draft_id), draft.reddit_username)


def check_trial_avatar_limit(client_id: uuid.UUID, db: Session) -> tuple[bool, str]:
    """Check if client can create a new avatar draft.

    For trial clients: max 1 (non-terminal drafts + active avatars combined).
    For paid clients: governed by max_avatars plan field.

    Returns:
        (allowed: bool, error_message: str)
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return False, "Client not found"

    if client.plan_type == "trial":
        # Count non-terminal drafts
        draft_count = (
            db.query(AvatarDraft)
            .filter(
                AvatarDraft.client_id == client_id,
                AvatarDraft.status.in_(DRAFT_NON_TERMINAL_STATUSES),
            )
            .count()
        )

        # Count active avatars
        avatar_count = (
            db.query(Avatar)
            .filter(
                Avatar.client_ids.any(str(client_id)),
                Avatar.active.is_(True),
            )
            .count()
        )

        if (draft_count + avatar_count) >= 1:
            return False, "Trial accounts are limited to 1 avatar. Upgrade your plan to add more."
        return True, ""

    # Paid plans: check max_avatars
    max_avatars = client.max_avatars or 3

    # Count all active avatars
    avatar_count = (
        db.query(Avatar)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            Avatar.active.is_(True),
        )
        .count()
    )

    # Count non-terminal drafts (in-progress)
    draft_count = (
        db.query(AvatarDraft)
        .filter(
            AvatarDraft.client_id == client_id,
            AvatarDraft.status.in_(DRAFT_NON_TERMINAL_STATUSES),
        )
        .count()
    )

    if (avatar_count + draft_count) >= max_avatars:
        return False, f"Your plan allows up to {max_avatars} avatars. Contact support to upgrade."

    return True, ""


def get_active_draft_for_client(client_id: uuid.UUID, db: Session) -> AvatarDraft | None:
    """Get the most recent non-terminal draft for a client.

    Used by the onboarding UI to show existing draft status on page load.
    """
    return (
        db.query(AvatarDraft)
        .filter(
            AvatarDraft.client_id == client_id,
            AvatarDraft.status.in_(DRAFT_NON_TERMINAL_STATUSES),
        )
        .order_by(AvatarDraft.created_at.desc())
        .first()
    )
