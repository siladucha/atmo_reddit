"""Avatar safety and rate limiting service.

Protects avatars from bans by enforcing Reddit-safe behavior patterns.
One banned avatar must never compromise others.
"""

from app.logging_config import get_logger
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.activity_event import ActivityEvent
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.audit import AuditLog
from app.services.phase import PhasePolicy, PhaseEvaluator
from app.services.phase_types import PolicyStatus

logger = get_logger(__name__)


# --- Rate Limits ---
# TODO(pipeline-v2): Replace MAX_COMMENTS_PER_DAY with BudgetEngine.calculate_daily_limit()
# Per avatar, per day
MAX_COMMENTS_PER_DAY = 8          # Fallback until BudgetEngine is implemented (Sprint 3)
MAX_PROFESSIONAL_PER_DAY = 5      # Max brand-related comments
MAX_HOBBY_PER_DAY = 5             # Max hobby/karma comments
MIN_MINUTES_BETWEEN_COMMENTS = 15 # TODO(pipeline-v2): move to system_settings "min_comment_interval_minutes"
MAX_COMMENTS_PER_SUBREDDIT_DAY = 2  # TODO(pipeline-v2): move to system_settings "max_comments_per_sub_per_day"
MAX_LINKS_PER_WEEK = 1            # Links are high-risk

# Content rules
MAX_COMMENT_LENGTH = 500          # Characters — long comments look suspicious
BRAND_MENTION_COOLDOWN_HOURS = 72 # Min hours between brand-adjacent comments per avatar
MAX_BRAND_RATIO = 0.3             # TODO(pipeline-v2): move to system_settings "max_brand_ratio_percent", change to 30-day window


class SafetyCheckResult:
    def __init__(self, allowed: bool, reason: str = ""):
        self.allowed = allowed
        self.reason = reason

    def __bool__(self):
        return self.allowed


def check_avatar_can_post(
    db: Session,
    avatar: Avatar,
    comment_type: str = "professional",
    target_subreddit: str | None = None,
    comment_text: str | None = None,
    client: Client | None = None,
    thread_tag: str | None = None,
) -> SafetyCheckResult:
    """Run all safety checks before allowing an avatar to post.

    Args:
        db: Database session
        avatar: The avatar attempting to post
        comment_type: 'professional' or 'hobby'
        target_subreddit: Target subreddit name (for phase policy checks)
        comment_text: The comment text (for brand mention detection)
        client: The client associated with this avatar (for brand classification)
        thread_tag: Thread tag ("engage", "monitor", "skip") for Phase 3 link rules

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

    # Check 2: Phase policy — replaces the old binary warmup check
    if target_subreddit is not None and comment_text is not None and client is not None:
        try:
            phase_policy = PhasePolicy()
            policy_result = phase_policy.check_comment_allowed(
                db=db,
                avatar=avatar,
                comment_type=comment_type,
                target_subreddit=target_subreddit,
                comment_text=comment_text,
                client=client,
                thread_tag=thread_tag,
            )

            if policy_result.status == PolicyStatus.blocked:
                # Log policy_block ActivityEvent
                _log_policy_block(
                    db=db,
                    avatar=avatar,
                    comment_type=comment_type,
                    target_subreddit=target_subreddit,
                    policy_result=policy_result,
                )
                return SafetyCheckResult(False, policy_result.reason)

            if policy_result.status == PolicyStatus.requires_review:
                # Log policy_block ActivityEvent for requires_review as well
                _log_policy_block(
                    db=db,
                    avatar=avatar,
                    comment_type=comment_type,
                    target_subreddit=target_subreddit,
                    policy_result=policy_result,
                )
                return SafetyCheckResult(False, f"Requires human review: {policy_result.reason}")
        except Exception as e:
            logger.error(
                f"Phase policy check failed for avatar {avatar.reddit_username} "
                f"in r/{target_subreddit}: {e}"
            )
            # Default to blocking on policy check failure (safe default)
            return SafetyCheckResult(False, f"Phase policy check error: {e}")

    # Piggyback evaluation: check if phase evaluation is due
    evaluator = PhaseEvaluator()
    if evaluator.should_piggyback(avatar):
        try:
            evaluator.evaluate(db, avatar)
        except Exception as e:
            logger.warning("Piggyback phase evaluation failed for %s: %s", avatar.reddit_username, e)

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

    if today_count >= MAX_COMMENTS_PER_DAY:
        return SafetyCheckResult(False, f"Daily limit reached ({today_count}/{MAX_COMMENTS_PER_DAY})")

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

    # Check 6: Brand ratio check (Phase 2+ only — Phase 1 has no brand mentions by design)
    if avatar.warming_phase and avatar.warming_phase >= 2:
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


def _log_policy_block(
    db: Session,
    avatar: Avatar,
    comment_type: str,
    target_subreddit: str,
    policy_result,
) -> None:
    """Log a policy_block ActivityEvent when PhasePolicy blocks or flags a comment."""
    from app.services.phase_types import PolicyResult

    client_id = avatar.client_ids[0] if avatar.client_ids else None
    brand_level = policy_result.brand_mention_level.value if policy_result.brand_mention_level else None

    event = ActivityEvent(
        event_type="policy_block",
        client_id=client_id,
        message=f"Phase {avatar.warming_phase} blocked {comment_type} comment for {avatar.reddit_username}",
        event_metadata={
            "avatar_id": str(avatar.id),
            "phase": avatar.warming_phase,
            "comment_type": comment_type,
            "subreddit": target_subreddit,
            "brand_mention_level": brand_level,
            "restriction_rule": policy_result.reason,
        },
    )
    db.add(event)
    try:
        db.flush()
    except Exception as e:
        logger.warning("Failed to log policy_block event: %s", e)


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
    """Get health metrics for an avatar.

    Returns a dict with health metrics. On DB errors, returns a degraded
    response with available data.
    """
    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)

    try:
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
    except Exception as e:
        logger.error(f"DB error in get_avatar_health for {avatar.reddit_username}: {e}")
        week_comments = 0
        week_professional = 0

    brand_ratio = week_professional / week_comments if week_comments > 0 else 0
    account_age = (now - avatar.created_at).days if avatar.created_at else 0

    checked_at = avatar.reddit_status_checked_at
    reddit_status_stale = bool(checked_at and (now - checked_at) > timedelta(hours=24))
    reddit_status_checked_relative = _format_relative_time(checked_at, now) if checked_at else None

    karma_discrepancy = False
    if avatar.reddit_status == "active" and avatar.karma_comment > 0:
        diff = abs(avatar.reddit_karma_comment - avatar.karma_comment)
        if diff / max(avatar.karma_comment, 1) > 0.1:
            karma_discrepancy = True

    reddit_account_age_days = None
    if avatar.reddit_account_created:
        reddit_account_age_days = (now - avatar.reddit_account_created).days

    # Phase information
    phase_labels = {
        0: "Mentor",
        1: "Credibility Building",
        2: "Content Seeding",
        3: "Brand Integration",
    }

    try:
        evaluator = PhaseEvaluator()
        eligible, criteria_values = evaluator.check_promotion_eligibility(db, avatar)
    except Exception as e:
        logger.warning(f"Phase evaluation failed for {avatar.reddit_username}: {e}")
        eligible = False
        criteria_values = {}

    return {
        "id": str(avatar.id),
        "username": avatar.reddit_username,
        "active": avatar.active,
        "shadowbanned": avatar.is_shadowbanned,
        "account_age_days": account_age,
        "warming_phase": avatar.warming_phase,
        "phase_label": phase_labels.get(avatar.warming_phase, "Unknown"),
        "phase_progress": criteria_values,
        "phase_eligible_for_next": eligible,
        "karma_comment": avatar.karma_comment,
        "karma_post": avatar.karma_post,
        "week_comments": week_comments,
        "week_professional": week_professional,
        "brand_ratio": round(brand_ratio, 2),
        "brand_ratio_ok": brand_ratio <= MAX_BRAND_RATIO,
        "last_health_check": avatar.last_health_check.isoformat() if avatar.last_health_check else None,
        "health_status": avatar.health_status or "unknown",
        "health_color": _health_status_to_color(avatar.health_status),
        "health_check_relative": _format_relative_time(avatar.last_health_check, now) if avatar.last_health_check else "Never checked",
        # Reddit status cache
        "reddit_status": avatar.reddit_status,
        "reddit_karma_comment": avatar.reddit_karma_comment,
        "reddit_karma_post": avatar.reddit_karma_post,
        "reddit_account_created": avatar.reddit_account_created,
        "reddit_account_age_days": reddit_account_age_days,
        "reddit_icon_url": avatar.reddit_icon_url,
        "reddit_status_checked_at": avatar.reddit_status_checked_at,
        "reddit_status_checked_relative": reddit_status_checked_relative,
        "reddit_status_stale": reddit_status_stale,
        "karma_discrepancy": karma_discrepancy,
    }


def _health_status_to_color(health_status: str | None) -> str:
    """Map health_status to a color name for template badges."""
    status = (health_status or "unknown").lower()
    if status == "active":
        return "green"
    elif status == "limited":
        return "yellow"
    elif status in ("shadowbanned", "suspended"):
        return "red"
    return "grey"


def _format_relative_time(when: datetime, now: datetime) -> str:
    """Format `when` as a relative-time string (e.g. '5 min ago')."""
    delta = now - when
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    years = days // 365
    return f"{years}y ago"
