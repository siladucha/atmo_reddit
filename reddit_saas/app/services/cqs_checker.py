"""CQS (Contributor Quality Score) checker service.

Checks an avatar's CQS by reading bot replies to their posts in r/WhatIsMyCQS.
The bot (u/CQS_Bot or similar) responds with the CQS level within minutes.

Flow:
1. Look at the avatar's recent submissions in r/WhatIsMyCQS
2. Find the bot's reply containing the CQS level
3. Parse the level from the reply text
4. Update the avatar's cqs_level and cqs_checked_at

Called during "Refresh Reddit Data" if the avatar has a post in r/WhatIsMyCQS.
"""

from app.logging_config import get_logger
import re
import time
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.services.reddit import get_reddit_client
from app.services.sanitize import ensure_username_bare

logger = get_logger(__name__)

# Valid CQS levels as returned by the bot
VALID_CQS_LEVELS = {"lowest", "low", "moderate", "high", "highest"}

# How far back to look for CQS check posts (days)
CQS_POST_LOOKBACK_DAYS = 30

# Regex patterns to extract CQS level from bot reply
# Bot format: "Your current CQS is **HIGH**."
CQS_PATTERNS = [
    # Bot's actual format: "Your current CQS is **HIGH**"
    re.compile(r"your\s+current\s+cqs\s+is\s+\*{0,2}(\w+)\*{0,2}", re.IGNORECASE),
    # Generic: "Your CQS is: High" or "Your CQS is High"
    re.compile(r"(?:your\s+)?cqs\s*(?:is\s*:?|:)\s*\*{0,2}(\w+)\*{0,2}", re.IGNORECASE),
    # Full name: "Your Contributor Quality Score is Moderate"
    re.compile(r"contributor\s+quality\s+score\s*(?:is|:)\s*\*{0,2}(\w+)\*{0,2}", re.IGNORECASE),
]


def _extract_cqs_level(text: str) -> str | None:
    """Extract CQS level from bot reply text.

    Returns normalized lowercase level or None if not found.
    """
    if not text:
        return None

    for pattern in CQS_PATTERNS:
        match = pattern.search(text)
        if match:
            level = match.group(1).lower()
            if level in VALID_CQS_LEVELS:
                return level

    return None


def check_cqs_from_reddit(username: str) -> tuple[str | None, dict]:
    """Check CQS by reading bot replies to user's posts in r/WhatIsMyCQS.

    Args:
        username: Reddit username (without u/ prefix).

    Returns:
        Tuple of (cqs_level, details_dict).
        cqs_level is None if no CQS post found or bot hasn't replied yet.
    """
    logger.info(
        "REDDIT_API_CALL | action=check_cqs | username=u/%s",
        username,
    )
    start_time = time.time()

    try:
        reddit = get_reddit_client()
        redditor = reddit.redditor(ensure_username_bare(username))

        # Look at user's recent submissions
        cutoff = datetime.now(timezone.utc) - timedelta(days=CQS_POST_LOOKBACK_DAYS)
        cqs_post = None

        for submission in redditor.submissions.new(limit=20):
            # Check if it's in r/WhatIsMyCQS (case-insensitive)
            if submission.subreddit.display_name.lower() == "whatismycqs":
                post_time = datetime.fromtimestamp(submission.created_utc, tz=timezone.utc)
                if post_time >= cutoff:
                    cqs_post = submission
                    break  # Take the most recent one

        if not cqs_post:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(
                "REDDIT_API_RESULT | action=check_cqs | username=u/%s | "
                "result=no_post_found | duration_ms=%d",
                username, duration_ms,
            )
            return None, {
                "reason": "no_cqs_post_found",
                "lookback_days": CQS_POST_LOOKBACK_DAYS,
                "duration_ms": duration_ms,
            }

        # Read comments on the post (bot replies)
        cqs_post.comments.replace_more(limit=0)
        cqs_level = None
        bot_reply_text = None

        for comment in cqs_post.comments:
            # The bot is typically not the post author
            if comment.author and comment.author.name != username:
                level = _extract_cqs_level(comment.body)
                if level:
                    cqs_level = level
                    bot_reply_text = comment.body[:500]
                    break

        duration_ms = int((time.time() - start_time) * 1000)

        if cqs_level:
            logger.info(
                "REDDIT_API_RESULT | action=check_cqs | username=u/%s | "
                "result=%s | duration_ms=%d",
                username, cqs_level, duration_ms,
            )
        else:
            logger.info(
                "REDDIT_API_RESULT | action=check_cqs | username=u/%s | "
                "result=no_bot_reply | duration_ms=%d",
                username, duration_ms,
            )

        return cqs_level, {
            "post_id": cqs_post.id,
            "post_created": datetime.fromtimestamp(
                cqs_post.created_utc, tz=timezone.utc
            ).isoformat(),
            "bot_reply_found": cqs_level is not None,
            "bot_reply_text": bot_reply_text,
            "cqs_level": cqs_level,
            "duration_ms": duration_ms,
        }

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.warning(
            "REDDIT_API_ERROR | action=check_cqs | username=u/%s | "
            "error=%s | duration_ms=%d",
            username, type(e).__name__, duration_ms,
            exc_info=True,
        )
        return None, {
            "error": f"{type(e).__name__}: {str(e)[:200]}",
            "duration_ms": duration_ms,
        }


def update_avatar_cqs_from_reddit(db: Session, avatar: Avatar) -> dict:
    """Check and update avatar's CQS from Reddit.

    Called during "Refresh Reddit Data". Only updates if a valid CQS
    level is found (doesn't clear existing data on failure).

    Returns:
        Dict with check results for logging/display.
    """
    cqs_level, details = check_cqs_from_reddit(avatar.reddit_username)

    if cqs_level:
        previous_level = avatar.cqs_level
        avatar.cqs_level = cqs_level
        avatar.cqs_checked_at = datetime.now(timezone.utc)

        # Auto-freeze if CQS drops to lowest — but only for avatars that
        # already progressed past Phase 1. Fresh avatars (Phase 1) naturally
        # start with CQS lowest and need hobby activity to warm up.
        if cqs_level == "lowest" and not avatar.is_frozen:
            if avatar.warming_phase >= 2:
                avatar.is_frozen = True
                avatar.freeze_reason = "CQS dropped to lowest — account likely flagged as spam"
                avatar.frozen_at = datetime.now(timezone.utc)
                logger.warning(
                    "AVATAR_AUTO_FROZEN_CQS | username=u/%s | cqs_level=lowest | "
                    "previous_level=%s | phase=%d",
                    avatar.reddit_username, previous_level, avatar.warming_phase,
                )
            else:
                logger.info(
                    "CQS_LOWEST_PHASE1_OK | username=u/%s | phase=1 | "
                    "previous_level=%s | action=allow_warming",
                    avatar.reddit_username, previous_level,
                )

        details["previous_level"] = previous_level
        details["updated"] = True

        logger.info(
            "CQS_UPDATED | username=u/%s | previous=%s | new=%s",
            avatar.reddit_username, previous_level, cqs_level,
        )
    else:
        details["updated"] = False

    return details


def run_cqs_check_batch(db: Session) -> dict:
    """Run CQS checks for all eligible avatars.

    Eligible: active=True, is_frozen=False, cqs_checked_at older than
    cqs_check_interval_days or null.

    Only checks avatars that have previously posted in r/WhatIsMyCQS
    (i.e., have a cqs_level already set OR cqs_checked_at is not None),
    OR avatars in Phase 2+ that have never been checked (to catch new
    avatars that should be monitored).

    Returns:
        Summary dict with counts: checked, updated, frozen, errors, skipped, duration_ms
    """
    import time as _time
    from sqlalchemy import or_, and_

    from app.services.settings import get_setting

    start_time = _time.time()

    # Read settings
    try:
        interval_days = int(get_setting(db, "cqs_check_interval_days"))
    except Exception:
        interval_days = 7

    try:
        rate_limit_delay = float(get_setting(db, "cqs_check_rate_limit_delay_seconds"))
    except Exception:
        rate_limit_delay = 3.0

    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=interval_days)

    # Query eligible avatars:
    # - Active, not frozen
    # - Either: never checked CQS, or checked before stale_cutoff
    # - Phase 2+ (Phase 1 avatars naturally have lowest CQS, checking is noise)
    eligible_avatars = (
        db.query(Avatar)
        .filter(
            and_(
                Avatar.active == True,  # noqa: E712
                Avatar.is_frozen == False,  # noqa: E712
                Avatar.warming_phase >= 2,
                or_(
                    Avatar.cqs_checked_at.is_(None),
                    Avatar.cqs_checked_at < stale_cutoff,
                ),
            )
        )
        .all()
    )

    batch_size = len(eligible_avatars)
    checked_count = 0
    updated_count = 0
    frozen_count = 0
    error_count = 0
    skipped_count = 0

    logger.info(
        "CQS_BATCH_START | eligible_avatars=%d | interval_days=%d | "
        "rate_limit_delay=%.1f",
        batch_size, interval_days, rate_limit_delay,
    )

    for i, avatar in enumerate(eligible_avatars):
        try:
            details = update_avatar_cqs_from_reddit(db, avatar)
            checked_count += 1

            if details.get("updated"):
                updated_count += 1
                # Check if avatar was frozen by the update
                if avatar.is_frozen and avatar.freeze_reason and "CQS" in avatar.freeze_reason:
                    frozen_count += 1
            else:
                # No CQS post found — mark as checked to avoid re-checking too soon
                if not avatar.cqs_checked_at:
                    # First time: don't set cqs_checked_at if no post found
                    # (they might post to r/WhatIsMyCQS later)
                    skipped_count += 1
                else:
                    # Already had a check before — update timestamp to avoid
                    # re-checking every run
                    avatar.cqs_checked_at = datetime.now(timezone.utc)

            db.commit()

        except Exception as e:
            error_count += 1
            logger.error(
                "CQS_BATCH_ERROR | avatar=%s | error=%s | details=%s",
                avatar.reddit_username, type(e).__name__, str(e),
            )
            db.rollback()

        # Rate limit: sleep between checks if batch > 5
        if batch_size > 5 and i < batch_size - 1:
            _time.sleep(rate_limit_delay)

    duration_ms = int((_time.time() - start_time) * 1000)

    logger.info(
        "CQS_BATCH_COMPLETE | checked=%d | updated=%d | frozen=%d | "
        "errors=%d | skipped=%d | duration_ms=%d",
        checked_count, updated_count, frozen_count,
        error_count, skipped_count, duration_ms,
    )

    # Audit log
    try:
        from app.services.audit import log_system_action

        log_system_action(
            db=db,
            action="cqs_check_batch_completed",
            entity_type="avatar",
            details={
                "checked": checked_count,
                "updated": updated_count,
                "frozen": frozen_count,
                "errors": error_count,
                "skipped": skipped_count,
                "duration_ms": duration_ms,
            },
        )
    except Exception:
        logger.warning(
            "Failed to audit log CQS batch completion",
            exc_info=True,
        )

    return {
        "checked": checked_count,
        "updated": updated_count,
        "frozen": frozen_count,
        "errors": error_count,
        "skipped": skipped_count,
        "duration_ms": duration_ms,
    }
