"""Per-subreddit ban detection and management service.

Auto-detects when an avatar is banned/shadowbanned in a specific subreddit
by tracking consecutive deletions in snapshot_comment_outcomes.

Provides:
- get_banned_subreddits(avatar_id) — cached query for pipeline filtering
- check_for_subreddit_ban(db, avatar_id, subreddit, draft_id) — detection logic
- probe_banned_subreddits() — weekly unauthenticated check for auto-unban
- ban_avatar_from_subreddit() / unban_avatar_from_subreddit() — manual ops
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.avatar_subreddit_ban import AvatarSubredditBan
from app.models.comment_draft import CommentDraft
from app.models.karma_snapshot import KarmaSnapshot
from app.services.transparency import record_activity_event

logger = get_logger(__name__)

# Detection thresholds
CONSECUTIVE_DELETIONS_THRESHOLD = 3  # 3 consecutive deleted in same subreddit = ban
DETECTION_WINDOW_HOURS = 168  # Look at last 7 days of data
EARLY_DELETION_MAX_HOURS = 5  # Only count deletions detected within 5h (mod-automod style)

# Probe settings
PROBE_INTERVAL_DAYS = 7  # Re-probe banned subs every 7 days


def get_banned_subreddits(db: Session, avatar_id: uuid.UUID) -> set[str]:
    """Get all subreddits this avatar is currently banned from.

    Returns lowercase subreddit names for easy comparison.
    This is the main query used by pipeline filters.
    """
    rows = (
        db.query(AvatarSubredditBan.subreddit)
        .filter(
            AvatarSubredditBan.avatar_id == avatar_id,
            AvatarSubredditBan.is_active.is_(True),
        )
        .all()
    )
    return {row[0].lower() for row in rows}


def check_for_subreddit_ban(
    db: Session,
    avatar_id: uuid.UUID,
    subreddit: str,
    draft_id: uuid.UUID,
) -> bool:
    """Check if this deletion event should trigger a subreddit ban.

    Called from snapshot_comment_outcomes when a deletion is detected.
    Looks at recent deletion history in the same subreddit for this avatar.

    Returns True if ban was created (new ban detected).
    """
    subreddit_lower = subreddit.lower().strip()
    if not subreddit_lower:
        return False

    # Already banned? Skip.
    existing = (
        db.query(AvatarSubredditBan)
        .filter(
            AvatarSubredditBan.avatar_id == avatar_id,
            sa_func.lower(AvatarSubredditBan.subreddit) == subreddit_lower,
            AvatarSubredditBan.is_active.is_(True),
        )
        .first()
    )
    if existing:
        # Update consecutive count
        existing.consecutive_deletions += 1
        db.flush()
        return False

    # Count recent consecutive deletions in this subreddit
    window_start = datetime.now(timezone.utc) - timedelta(hours=DETECTION_WINDOW_HOURS)

    # Get recent posted drafts in this subreddit for this avatar
    recent_drafts = (
        db.query(CommentDraft)
        .filter(
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.status == "posted",
            CommentDraft.posted_at >= window_start,
            CommentDraft.posted_at.isnot(None),
        )
        .all()
    )

    # Filter to same subreddit (thread.subreddit)
    subreddit_drafts = []
    for d in recent_drafts:
        draft_sub = ""
        if d.thread:
            draft_sub = (getattr(d.thread, "subreddit", "") or "").lower()
        if draft_sub == subreddit_lower:
            subreddit_drafts.append(d)

    if not subreddit_drafts:
        return False

    # Count how many of the most recent N are deleted
    # Sort by posted_at desc (most recent first)
    subreddit_drafts.sort(key=lambda x: x.posted_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    # Check consecutive deletions from most recent
    consecutive = 0
    evidence_ids = []
    for d in subreddit_drafts:
        if getattr(d, "is_deleted", False):
            # Check if deletion was detected early (within EARLY_DELETION_MAX_HOURS)
            # This distinguishes automod/shadowban from late manual moderation
            posted_at = d.posted_at
            deleted_at = getattr(d, "deleted_detected_at", None)
            if posted_at and deleted_at:
                hours_to_delete = (deleted_at - posted_at).total_seconds() / 3600
                if hours_to_delete <= EARLY_DELETION_MAX_HOURS:
                    consecutive += 1
                    evidence_ids.append(str(d.id))
                else:
                    break  # Late deletion = manual moderation, not shadowban
            else:
                consecutive += 1
                evidence_ids.append(str(d.id))
        else:
            break  # Found a non-deleted comment = streak broken

    if consecutive < CONSECUTIVE_DELETIONS_THRESHOLD:
        return False

    # Create ban record
    ban = AvatarSubredditBan(
        avatar_id=avatar_id,
        subreddit=subreddit_lower,
        ban_source="auto_detected",
        consecutive_deletions=consecutive,
        detection_evidence={
            "draft_ids": evidence_ids[:10],
            "trigger_draft_id": str(draft_id),
            "window_hours": DETECTION_WINDOW_HOURS,
            "early_deletion_max_hours": EARLY_DELETION_MAX_HOURS,
        },
    )
    db.add(ban)
    db.flush()

    # Get client_id for activity event
    trigger_draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
    client_id = getattr(trigger_draft, "client_id", None) if trigger_draft else None

    # Emit activity event
    record_activity_event(
        db,
        event_type="subreddit_ban_detected",
        message=(
            f"Subreddit ban detected: avatar in r/{subreddit_lower} — "
            f"{consecutive} consecutive deletions within {EARLY_DELETION_MAX_HOURS}h of posting"
        ),
        client_id=client_id,
        metadata={
            "avatar_id": str(avatar_id),
            "subreddit": subreddit_lower,
            "consecutive_deletions": consecutive,
            "ban_source": "auto_detected",
            "evidence_draft_ids": evidence_ids[:5],
        },
    )

    logger.warning(
        "SUBREDDIT_BAN_DETECTED: avatar_id=%s subreddit=%s consecutive=%d",
        avatar_id, subreddit_lower, consecutive,
    )
    return True


def ban_avatar_from_subreddit(
    db: Session,
    avatar_id: uuid.UUID,
    subreddit: str,
    source: str = "manual",
) -> AvatarSubredditBan:
    """Manually ban an avatar from a subreddit.

    Used by admin UI when operator knows about a ban.
    """
    subreddit_lower = subreddit.lower().strip()

    # Check if already exists
    existing = (
        db.query(AvatarSubredditBan)
        .filter(
            AvatarSubredditBan.avatar_id == avatar_id,
            sa_func.lower(AvatarSubredditBan.subreddit) == subreddit_lower,
        )
        .first()
    )

    if existing:
        if not existing.is_active:
            # Re-activate
            existing.is_active = True
            existing.ban_source = source
            existing.banned_at = datetime.now(timezone.utc)
            existing.unbanned_at = None
            existing.unban_source = None
            db.commit()
        return existing

    ban = AvatarSubredditBan(
        avatar_id=avatar_id,
        subreddit=subreddit_lower,
        ban_source=source,
        detection_evidence={"source": "manual_admin_action"},
    )
    db.add(ban)
    db.commit()

    logger.info("Manual subreddit ban: avatar_id=%s subreddit=%s", avatar_id, subreddit_lower)
    return ban


def unban_avatar_from_subreddit(
    db: Session,
    avatar_id: uuid.UUID,
    subreddit: str,
    source: str = "manual",
) -> bool:
    """Unban an avatar from a subreddit. Returns True if found and unbanned."""
    subreddit_lower = subreddit.lower().strip()

    ban = (
        db.query(AvatarSubredditBan)
        .filter(
            AvatarSubredditBan.avatar_id == avatar_id,
            sa_func.lower(AvatarSubredditBan.subreddit) == subreddit_lower,
            AvatarSubredditBan.is_active.is_(True),
        )
        .first()
    )

    if not ban:
        return False

    ban.is_active = False
    ban.unbanned_at = datetime.now(timezone.utc)
    ban.unban_source = source
    db.commit()

    record_activity_event(
        db,
        event_type="subreddit_ban_lifted",
        message=f"Subreddit ban lifted: avatar in r/{subreddit_lower} (source: {source})",
        metadata={
            "avatar_id": str(avatar_id),
            "subreddit": subreddit_lower,
            "unban_source": source,
        },
    )

    logger.info("Subreddit ban lifted: avatar_id=%s subreddit=%s source=%s", avatar_id, subreddit_lower, source)
    return True


def probe_single_ban(db: Session, ban: AvatarSubredditBan) -> str:
    """Probe a single banned subreddit to check if ban is still active.

    Uses unauthenticated PRAW client to check if the avatar's
    most recent comment in that subreddit is visible to others.

    Returns: "still_banned" | "accessible" | "no_comments" | "error"
    """
    import time
    from app.services.reddit import get_reddit_client

    try:
        # Find the most recent posted comment URL for this avatar in this subreddit
        recent_draft = (
            db.query(CommentDraft)
            .filter(
                CommentDraft.avatar_id == ban.avatar_id,
                CommentDraft.status == "posted",
                CommentDraft.reddit_comment_url.isnot(None),
            )
            .order_by(CommentDraft.posted_at.desc())
            .all()
        )

        # Filter to matching subreddit
        target_draft = None
        for d in recent_draft[:20]:
            draft_sub = ""
            if d.thread:
                draft_sub = (getattr(d.thread, "subreddit", "") or "").lower()
            if draft_sub == ban.subreddit.lower():
                target_draft = d
                break

        if not target_draft:
            ban.last_probe_at = datetime.now(timezone.utc)
            ban.last_probe_result = "no_comments"
            db.commit()
            return "no_comments"

        # Extract comment ID from URL
        from app.tasks.snapshot_outcomes import _extract_comment_id
        comment_id = _extract_comment_id(target_draft.reddit_comment_url)
        if not comment_id:
            ban.last_probe_at = datetime.now(timezone.utc)
            ban.last_probe_result = "error"
            db.commit()
            return "error"

        # Use read-only client (unauthenticated) to check visibility
        reddit = get_reddit_client(caller="subreddit_ban_probe")
        comment = reddit.comment(id=comment_id)

        try:
            comment._fetch()
            # If we can fetch it and body is not [removed]/[deleted], it's visible
            is_removed = comment.body in ("[removed]", "[deleted]") or comment.author is None
        except Exception as e:
            error_str = str(e).lower()
            if "404" in error_str or "not found" in error_str:
                is_removed = True
            else:
                ban.last_probe_at = datetime.now(timezone.utc)
                ban.last_probe_result = "error"
                db.commit()
                return "error"

        time.sleep(2)  # Rate limit

        ban.last_probe_at = datetime.now(timezone.utc)

        if is_removed:
            ban.last_probe_result = "still_banned"
            db.commit()
            return "still_banned"
        else:
            # Comment is visible — ban may have been lifted!
            ban.last_probe_result = "accessible"
            ban.is_active = False
            ban.unbanned_at = datetime.now(timezone.utc)
            ban.unban_source = "probe_check"
            db.commit()

            record_activity_event(
                db,
                event_type="subreddit_ban_lifted",
                message=(
                    f"Subreddit ban auto-lifted via probe: avatar in r/{ban.subreddit} — "
                    f"comment now visible"
                ),
                metadata={
                    "avatar_id": str(ban.avatar_id),
                    "subreddit": ban.subreddit,
                    "unban_source": "probe_check",
                    "probed_comment_id": comment_id,
                },
            )

            logger.info(
                "SUBREDDIT_BAN_LIFTED (probe): avatar_id=%s subreddit=%s",
                ban.avatar_id, ban.subreddit,
            )
            return "accessible"

    except Exception as e:
        logger.error("probe_single_ban error: ban_id=%s error=%s", ban.id, str(e)[:200])
        ban.last_probe_at = datetime.now(timezone.utc)
        ban.last_probe_result = "error"
        db.commit()
        return "error"


def get_bans_due_for_probe(db: Session) -> list[AvatarSubredditBan]:
    """Get active bans that haven't been probed in PROBE_INTERVAL_DAYS."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=PROBE_INTERVAL_DAYS)

    return (
        db.query(AvatarSubredditBan)
        .filter(
            AvatarSubredditBan.is_active.is_(True),
            sa_func.coalesce(AvatarSubredditBan.last_probe_at, datetime(2000, 1, 1, tzinfo=timezone.utc)) < cutoff,
        )
        .all()
    )
