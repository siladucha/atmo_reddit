"""Avatar safety and rate limiting service.

Protects avatars from bans by enforcing Reddit-safe behavior patterns.
One banned avatar must never compromise others.
"""

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.avatar import Avatar
from app.models.comment_draft import CommentDraft
from app.models.audit import AuditLog

logger = logging.getLogger(__name__)


# --- Rate Limits ---

# Per avatar, per day
MAX_COMMENTS_PER_DAY = 8          # Reddit flags accounts posting too frequently
MAX_PROFESSIONAL_PER_DAY = 5      # Max brand-related comments
MAX_HOBBY_PER_DAY = 5             # Max hobby/karma comments
MIN_MINUTES_BETWEEN_COMMENTS = 15 # Minimum gap between posts from same avatar
MAX_COMMENTS_PER_SUBREDDIT_DAY = 2  # Don't dominate one subreddit
MAX_LINKS_PER_WEEK = 1            # Links are high-risk
WARMUP_DAYS = 14                  # New accounts: hobby only for 2 weeks
WARMUP_MAX_PER_DAY = 3            # Reduced activity during warmup

# Content rules
MAX_COMMENT_LENGTH = 300          # Characters — long comments look suspicious
BRAND_MENTION_COOLDOWN_HOURS = 72 # Min hours between brand-adjacent comments per avatar
MAX_BRAND_RATIO = 0.3             # Max 30% of comments can be brand-related


class SafetyCheckResult:
    def __init__(self, allowed: bool, reason: str = ""):
        self.allowed = allowed
        self.reason = reason

    def __bool__(self):
        return self.allowed


def check_avatar_can_post(db: Session, avatar: Avatar, comment_type: str = "professional") -> SafetyCheckResult:
    """Run all safety checks before allowing an avatar to post.

    Args:
        db: Database session
        avatar: The avatar attempting to post
        comment_type: 'professional' or 'hobby'

    Returns:
        SafetyCheckResult with allowed=True/False and reason.
    """
    # Check 1: Is avatar active and not shadowbanned?
    if not avatar.active:
        return SafetyCheckResult(False, "Avatar is deactivated")

    if avatar.is_shadowbanned:
        return SafetyCheckResult(False, "Avatar is shadowbanned — do not use")

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Check 2: Warmup period — new accounts can only do hobby
    account_age = (now - avatar.created_at).days if avatar.created_at else 0
    if account_age < WARMUP_DAYS and comment_type == "professional":
        return SafetyCheckResult(False, f"Avatar in warmup ({account_age}/{WARMUP_DAYS} days) — hobby only")

    # Check 3: Daily comment limit
    today_count = (
        db.query(func.count(CommentDraft.id))
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.status.in_(["approved", "posted"]),
            CommentDraft.created_at >= today_start,
        )
        .scalar()
    )

    daily_limit = WARMUP_MAX_PER_DAY if account_age < WARMUP_DAYS else MAX_COMMENTS_PER_DAY
    if today_count >= daily_limit:
        return SafetyCheckResult(False, f"Daily limit reached ({today_count}/{daily_limit})")

    # Check 4: Type-specific daily limit
    type_count = (
        db.query(func.count(CommentDraft.id))
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.type == comment_type,
            CommentDraft.status.in_(["approved", "posted"]),
            CommentDraft.created_at >= today_start,
        )
        .scalar()
    )

    type_limit = MAX_PROFESSIONAL_PER_DAY if comment_type == "professional" else MAX_HOBBY_PER_DAY
    if type_count >= type_limit:
        return SafetyCheckResult(False, f"{comment_type} limit reached ({type_count}/{type_limit})")

    # Check 5: Minimum time between comments
    last_comment = (
        db.query(CommentDraft)
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.status.in_(["approved", "posted"]),
        )
        .order_by(CommentDraft.created_at.desc())
        .first()
    )

    if last_comment and last_comment.created_at:
        minutes_since = (now - last_comment.created_at).total_seconds() / 60
        if minutes_since < MIN_MINUTES_BETWEEN_COMMENTS:
            return SafetyCheckResult(
                False,
                f"Too soon since last comment ({int(minutes_since)}/{MIN_MINUTES_BETWEEN_COMMENTS} min)"
            )

    # Check 6: Brand ratio check
    week_start = now - timedelta(days=7)
    week_total = (
        db.query(func.count(CommentDraft.id))
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.status.in_(["approved", "posted"]),
            CommentDraft.created_at >= week_start,
        )
        .scalar()
    )
    week_professional = (
        db.query(func.count(CommentDraft.id))
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.type == "professional",
            CommentDraft.status.in_(["approved", "posted"]),
            CommentDraft.created_at >= week_start,
        )
        .scalar()
    )

    if week_total > 5 and week_professional / week_total > MAX_BRAND_RATIO:
        return SafetyCheckResult(
            False,
            f"Brand ratio too high ({week_professional}/{week_total} = {week_professional/week_total:.0%}, max {MAX_BRAND_RATIO:.0%})"
        )

    return SafetyCheckResult(True)


def check_subreddit_limit(db: Session, avatar: Avatar, subreddit: str) -> SafetyCheckResult:
    """Check if avatar has hit the per-subreddit daily limit."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    from app.models.thread import RedditThread

    sub_count = (
        db.query(func.count(CommentDraft.id))
        .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
        .filter(
            CommentDraft.avatar_id == avatar.id,
            RedditThread.subreddit == subreddit,
            CommentDraft.status.in_(["approved", "posted"]),
            CommentDraft.created_at >= today_start,
        )
        .scalar()
    )

    if sub_count >= MAX_COMMENTS_PER_SUBREDDIT_DAY:
        return SafetyCheckResult(
            False,
            f"Subreddit limit for r/{subreddit} ({sub_count}/{MAX_COMMENTS_PER_SUBREDDIT_DAY})"
        )

    return SafetyCheckResult(True)


def check_comment_content(comment_text: str) -> SafetyCheckResult:
    """Validate comment content before approval."""
    if len(comment_text) > MAX_COMMENT_LENGTH:
        return SafetyCheckResult(False, f"Comment too long ({len(comment_text)}/{MAX_COMMENT_LENGTH} chars)")

    # Check for obvious promotional patterns
    promo_signals = [
        "check out", "visit our", "our platform", "our product",
        "sign up", "free trial", "discount code", "use code",
        "link in bio", "dm me", "dm for", "www.", "http://", "https://",
    ]
    lower = comment_text.lower()
    for signal in promo_signals:
        if signal in lower:
            return SafetyCheckResult(False, f"Promotional content detected: '{signal}'")

    return SafetyCheckResult(True)


def log_safety_event(
    db: Session,
    avatar: Avatar,
    action: str,
    details: dict,
) -> None:
    """Log a safety-related event to audit log."""
    log = AuditLog(
        action=f"safety_{action}",
        entity_type="avatar",
        entity_id=avatar.id,
        details=details,
    )
    db.add(log)
    db.commit()


def quarantine_avatar(db: Session, avatar: Avatar, reason: str) -> None:
    """Deactivate an avatar and log the reason."""
    avatar.active = False
    log_safety_event(db, avatar, "quarantine", {"reason": reason})
    db.commit()
    logger.warning(f"Avatar {avatar.reddit_username} quarantined: {reason}")


def get_avatar_health(db: Session, avatar: Avatar) -> dict:
    """Get health metrics for an avatar."""
    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)

    week_comments = (
        db.query(func.count(CommentDraft.id))
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.status.in_(["approved", "posted"]),
            CommentDraft.created_at >= week_start,
        )
        .scalar()
    )

    week_professional = (
        db.query(func.count(CommentDraft.id))
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.type == "professional",
            CommentDraft.status.in_(["approved", "posted"]),
            CommentDraft.created_at >= week_start,
        )
        .scalar()
    )

    brand_ratio = week_professional / week_comments if week_comments > 0 else 0
    account_age = (now - avatar.created_at).days if avatar.created_at else 0

    return {
        "username": avatar.reddit_username,
        "active": avatar.active,
        "shadowbanned": avatar.is_shadowbanned,
        "account_age_days": account_age,
        "in_warmup": account_age < WARMUP_DAYS,
        "karma_comment": avatar.karma_comment,
        "karma_post": avatar.karma_post,
        "week_comments": week_comments,
        "week_professional": week_professional,
        "brand_ratio": round(brand_ratio, 2),
        "brand_ratio_ok": brand_ratio <= MAX_BRAND_RATIO,
        "last_health_check": avatar.last_health_check.isoformat() if avatar.last_health_check else None,
    }
