"""Core posting service — executes a single automated post for an EPG slot.

Orchestrates the full posting flow:
1. Load slot + avatar + draft + reddit_app
2. Run safety gates
3. Resolve proxy IP + verify subnet consistency
4. Build authenticated PRAW client
5. Submit comment to Reddit
6. Update state (draft, slot, avatar)
7. Record PostingEvent audit record

Usage:
    from app.services.posting import execute_post, PostingRefused

    try:
        event = execute_post(db, epg_slot_id)
    except PostingRefused as e:
        logger.info("Posting refused: %s", e.reason)
"""

import hashlib
from app.logging_config import get_logger
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.comment_draft import CommentDraft
from app.models.epg_slot import EPGSlot
from app.models.posting_event import PostingEvent
from app.models.reddit_app import RedditApp
from app.services.encryption import get_encryptor
from app.services.posting_safety import (
    SafetyResult,
    check_posting_safety,
    hash_proxy_url,
    redact_proxy_url,
)
from app.services.praw_factory import (
    PostingConfigError,
    create_avatar_reddit_client,
    resolve_proxy_ip,
)

logger = get_logger(__name__)


class PostingRefused(Exception):
    """Raised when safety gates refuse a posting attempt."""

    def __init__(self, reason: str, avatar_id: uuid.UUID | None = None):
        self.reason = reason
        self.avatar_id = avatar_id
        super().__init__(reason)


def execute_post(db: Session, epg_slot_id: uuid.UUID) -> PostingEvent:
    """Execute a single automated post for an EPG slot.

    This is the main entry point called by the Celery task.

    Args:
        db: Database session
        epg_slot_id: UUID of the EPG slot to post

    Returns:
        PostingEvent record (success or failure)

    Raises:
        PostingRefused: If safety gates refuse the post (non-retryable)
        PostingConfigError: If avatar configuration is incomplete
    """
    start_time = time.time()
    encryptor = get_encryptor()

    # --- 1. Load entities ---
    slot = db.query(EPGSlot).filter(EPGSlot.id == epg_slot_id).first()
    if not slot:
        raise PostingRefused(f"EPG slot not found: {epg_slot_id}")

    avatar = db.query(Avatar).filter(Avatar.id == slot.avatar_id).first()
    if not avatar:
        raise PostingRefused(f"Avatar not found for slot: {epg_slot_id}", slot.avatar_id)

    draft = db.query(CommentDraft).filter(CommentDraft.id == slot.draft_id).first() if slot.draft_id else None
    if not draft:
        raise PostingRefused(f"Draft not found for slot: {epg_slot_id}", avatar.id)

    reddit_app = db.query(RedditApp).filter(RedditApp.id == avatar.reddit_app_id).first() if avatar.reddit_app_id else None
    if not reddit_app:
        # For password auth MVP, try to find any active app
        reddit_app = db.query(RedditApp).filter(RedditApp.is_active == True).first()
        if not reddit_app:
            raise PostingRefused("No active Reddit app configured", avatar.id)

    # --- 2. Resolve proxy IP ---
    resolved_ip = None
    if avatar.proxy_url_encrypted:
        proxy_url = encryptor.decrypt(avatar.proxy_url_encrypted)
        resolved_ip = resolve_proxy_ip(proxy_url)
        if resolved_ip is None:
            # Proxy unreachable — create failure event and raise for retry
            event = _create_posting_event(
                db, avatar, draft, slot,
                outcome="failure",
                error_message="Proxy unreachable — could not resolve exit IP",
                ip_used=None,
                proxy_url_hash=hash_proxy_url(proxy_url),
                duration_ms=_elapsed_ms(start_time),
            )
            db.commit()
            raise Exception(f"Proxy unreachable for {avatar.reddit_username}")

    # --- 3. Safety gates ---
    safety = check_posting_safety(db, avatar, slot, resolved_ip=resolved_ip)
    if not safety.allowed:
        # Check if this is an IP subnet issue → freeze
        if "subnet" in safety.reason.lower():
            _freeze_avatar(db, avatar, "ip_subnet_changed", safety.reason)

        event = _create_posting_event(
            db, avatar, draft, slot,
            outcome="skipped",
            error_message=f"Safety gate: {safety.reason}",
            ip_used=resolved_ip,
            proxy_url_hash=hash_proxy_url(encryptor.decrypt(avatar.proxy_url_encrypted)) if avatar.proxy_url_encrypted else None,
            duration_ms=_elapsed_ms(start_time),
        )
        db.commit()
        raise PostingRefused(safety.reason, avatar.id)

    # --- 4. Build PRAW client ---
    try:
        reddit = create_avatar_reddit_client(avatar, reddit_app, encryptor)
    except PostingConfigError as e:
        event = _create_posting_event(
            db, avatar, draft, slot,
            outcome="failure",
            error_message=f"Config error: {str(e)}",
            ip_used=resolved_ip,
            duration_ms=_elapsed_ms(start_time),
        )
        db.commit()
        raise

    # --- 5. Submit comment ---
    proxy_url_for_hash = encryptor.decrypt(avatar.proxy_url_encrypted) if avatar.proxy_url_encrypted else ""
    comment_text = draft.edited_draft or draft.ai_draft or ""

    try:
        # Determine reply target based on location_depth
        thread = slot.thread
        if not thread:
            raise PostingRefused(f"Thread not found for slot {epg_slot_id}", avatar.id)

        # Get the Reddit submission
        submission = reddit.submission(id=thread.reddit_id)

        # Post as top-level comment (location_depth 0 or None) or reply to comment
        location_depth = getattr(draft, "location_depth", None) or 0
        if location_depth == 0:
            comment = submission.reply(comment_text)
        else:
            # For nested replies, we'd need the parent comment ID
            # For MVP, default to top-level reply
            comment = submission.reply(comment_text)

        reddit_comment_id = comment.id if comment else None
        reddit_comment_url = f"https://www.reddit.com{comment.permalink}" if comment else None

    except Exception as e:
        # Classify error
        error_str = str(e).lower()
        duration_ms = _elapsed_ms(start_time)

        # Auth errors → freeze, no retry
        if "401" in error_str or "unauthorized" in error_str:
            _freeze_avatar(db, avatar, "auth_error: 401", str(e))
            event = _create_posting_event(
                db, avatar, draft, slot,
                outcome="failure",
                error_message=f"Auth error 401: {str(e)[:500]}",
                ip_used=resolved_ip,
                proxy_url_hash=hash_proxy_url(proxy_url_for_hash),
                duration_ms=duration_ms,
                response_status=401,
            )
            db.commit()
            raise PostingRefused(f"Auth error 401 for {avatar.reddit_username}", avatar.id)

        if "403" in error_str or "forbidden" in error_str:
            _freeze_avatar(db, avatar, "auth_error: 403", str(e))
            event = _create_posting_event(
                db, avatar, draft, slot,
                outcome="failure",
                error_message=f"Auth error 403: {str(e)[:500]}",
                ip_used=resolved_ip,
                proxy_url_hash=hash_proxy_url(proxy_url_for_hash),
                duration_ms=duration_ms,
                response_status=403,
            )
            db.commit()
            raise PostingRefused(f"Auth error 403 for {avatar.reddit_username}", avatar.id)

        if "suspended" in error_str or "banned" in error_str:
            _freeze_avatar(db, avatar, "account_suspended", str(e))
            event = _create_posting_event(
                db, avatar, draft, slot,
                outcome="failure",
                error_message=f"Account suspended: {str(e)[:500]}",
                ip_used=resolved_ip,
                proxy_url_hash=hash_proxy_url(proxy_url_for_hash),
                duration_ms=duration_ms,
            )
            db.commit()
            raise PostingRefused(f"Account suspended: {avatar.reddit_username}", avatar.id)

        # Transient error → increment failures, allow retry
        avatar.consecutive_post_failures = (avatar.consecutive_post_failures or 0) + 1

        # Check consecutive failure threshold (3 in 24h → freeze)
        if avatar.consecutive_post_failures >= 3:
            _freeze_avatar(db, avatar, "consecutive_failures",
                          f"3 consecutive posting failures. Last: {str(e)[:200]}")

        event = _create_posting_event(
            db, avatar, draft, slot,
            outcome="failure",
            error_message=f"Transient error: {str(e)[:500]}",
            ip_used=resolved_ip,
            proxy_url_hash=hash_proxy_url(proxy_url_for_hash),
            duration_ms=duration_ms,
        )
        db.commit()
        # Re-raise for Celery retry
        raise

    # --- 6. Success — update state ---
    duration_ms = _elapsed_ms(start_time)
    now = datetime.now(timezone.utc)

    # Update draft
    draft.status = "posted"
    draft.posted_at = now
    if reddit_comment_url:
        draft.reddit_comment_url = reddit_comment_url

    # Update slot
    slot.status = "posted"
    slot.posted_at = now

    # Update avatar
    avatar.last_posted_at = now
    avatar.last_posted_ip = resolved_ip
    avatar.consecutive_post_failures = 0

    # --- 7. Audit record ---
    event = _create_posting_event(
        db, avatar, draft, slot,
        outcome="success",
        ip_used=resolved_ip,
        proxy_url_hash=hash_proxy_url(proxy_url_for_hash),
        reddit_comment_id=reddit_comment_id,
        reddit_comment_url=reddit_comment_url,
        duration_ms=duration_ms,
    )

    db.commit()

    logger.info(
        "Posted successfully: avatar=%s, thread=%s, comment=%s, duration=%dms",
        avatar.reddit_username,
        thread.reddit_id if thread else "?",
        reddit_comment_id,
        duration_ms,
    )

    return event


# --- Private helpers ---


def _create_posting_event(
    db: Session,
    avatar: Avatar,
    draft: CommentDraft | None,
    slot: EPGSlot,
    outcome: str,
    error_message: str | None = None,
    ip_used: str | None = None,
    proxy_url_hash: str | None = None,
    reddit_comment_id: str | None = None,
    reddit_comment_url: str | None = None,
    duration_ms: int | None = None,
    response_status: int | None = None,
    attempt_number: int = 1,
) -> PostingEvent:
    """Create and persist a PostingEvent audit record."""
    event = PostingEvent(
        avatar_id=avatar.id,
        draft_id=draft.id if draft else None,
        epg_slot_id=slot.id,
        outcome=outcome,
        ip_used=ip_used,
        proxy_url_hash=proxy_url_hash,
        user_agent_used=avatar.user_agent_string,
        reddit_comment_id=reddit_comment_id,
        reddit_comment_url=reddit_comment_url,
        response_status=response_status,
        error_message=error_message,
        attempt_number=attempt_number,
        duration_ms=duration_ms,
    )
    db.add(event)
    return event


def _freeze_avatar(db: Session, avatar: Avatar, reason: str, details: str = "") -> None:
    """Freeze an avatar and emit activity event."""
    avatar.is_frozen = True
    avatar.freeze_reason = reason
    avatar.frozen_at = datetime.now(timezone.utc)

    logger.warning(
        "Avatar frozen: %s, reason=%s, details=%s",
        avatar.reddit_username, reason, details[:200]
    )

    # Emit activity event
    try:
        from app.models.activity_event import ActivityEvent
        event = ActivityEvent(
            event_type="avatar_frozen_by_posting",
            client_id=avatar.client_ids[0] if avatar.client_ids else None,
            message=f"Avatar {avatar.reddit_username} frozen by posting service: {reason}",
            event_metadata={
                "avatar_id": str(avatar.id),
                "avatar_username": avatar.reddit_username,
                "freeze_reason": reason,
                "details": details[:500],
            },
        )
        db.add(event)
    except Exception as e:
        logger.error("Failed to emit activity event for avatar freeze: %s", e)


def _elapsed_ms(start_time: float) -> int:
    """Calculate elapsed milliseconds since start_time."""
    return int((time.time() - start_time) * 1000)
