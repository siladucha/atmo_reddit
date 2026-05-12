"""Health Checker service for avatar shadowban detection.

Performs visibility-based health checks on Reddit avatars by:
1. Checking profile accessibility (PRAW redditor lookup)
2. Checking comment visibility (unauthenticated session)
3. Classifying health status based on visibility ratio
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import httpx
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from prawcore.exceptions import (
    NotFound,
    Forbidden,
    RequestException,
    ResponseException,
    ServerError,
)

from app.models.avatar import Avatar
from app.models.comment_draft import CommentDraft
from app.models.health_status import HealthStatus
from app.services.reddit import get_reddit_client
from app.services.sanitize import ensure_username_bare
from app.services.settings import get_setting

logger = logging.getLogger(__name__)


@dataclass
class HealthCheckResult:
    """Result of a single avatar health check."""

    avatar_id: uuid.UUID
    username: str
    previous_status: str
    new_status: str
    detection_method: str  # "profile_check" | "visibility_check" | "api_error"
    visibility_ratio: float | None
    comments_sampled: int
    comments_visible: int
    details: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def status_changed(self) -> bool:
        return self.previous_status != self.new_status


class HealthCheckError(Exception):
    """Raised when a health check encounters a network/unexpected error.

    The caller should retain the avatar's previous status and increment
    consecutive_check_failures.
    """

    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message)
        self.original_error = original_error


def check_profile_accessibility(username: str) -> tuple[str | None, str]:
    """Check if an avatar's Reddit profile is accessible.

    Uses an unauthenticated PRAW client to look up the redditor and determine
    whether the account is suspended, banned, or accessible.

    Args:
        username: The Reddit username to check (without u/ prefix).

    Returns:
        A tuple of (status, detection_method):
        - ("suspended", "profile_check") if the profile is inaccessible
          (404, 403, or is_suspended=True)
        - (None, "profile_check") if the profile is accessible and the
          visibility check should proceed

    Raises:
        HealthCheckError: On network errors, timeouts, or unexpected failures.
            The caller should retain the avatar's previous status and increment
            consecutive_check_failures.
    """
    logger.info(
        "REDDIT_API_CALL | action=check_profile_accessibility | username=%s",
        username,
    )
    start_time = time.time()

    try:
        reddit = get_reddit_client()
        redditor = reddit.redditor(ensure_username_bare(username))

        # Access an attribute to trigger the actual API call.
        # Checking is_suspended requires fetching the redditor's data.
        is_suspended = getattr(redditor, "is_suspended", False)

        duration_ms = int((time.time() - start_time) * 1000)

        if is_suspended:
            logger.info(
                "REDDIT_API_RESULT | action=check_profile_accessibility | username=%s | "
                "result=SUSPENDED | reason=is_suspended_flag | duration_ms=%d",
                username, duration_ms,
            )
            return ("suspended", "profile_check")

        # Profile is accessible and account is active
        logger.info(
            "REDDIT_API_RESULT | action=check_profile_accessibility | username=%s | "
            "result=ACCESSIBLE | duration_ms=%d",
            username, duration_ms,
        )
        return (None, "profile_check")

    except NotFound:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(
            "REDDIT_API_RESULT | action=check_profile_accessibility | username=%s | "
            "result=SUSPENDED | reason=404_not_found | duration_ms=%d",
            username, duration_ms,
        )
        return ("suspended", "profile_check")

    except Forbidden:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(
            "REDDIT_API_RESULT | action=check_profile_accessibility | username=%s | "
            "result=SUSPENDED | reason=403_forbidden | duration_ms=%d",
            username, duration_ms,
        )
        return ("suspended", "profile_check")

    except (RequestException, ServerError) as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(
            "REDDIT_API_ERROR | action=check_profile_accessibility | username=%s | "
            "error=%s | duration_ms=%d | details=%s",
            username, type(e).__name__, duration_ms, str(e),
        )
        raise HealthCheckError(
            f"Network/server error checking profile for {username}: {e}",
            original_error=e,
        )

    except ResponseException as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(
            "REDDIT_API_ERROR | action=check_profile_accessibility | username=%s | "
            "error=ResponseException | duration_ms=%d | details=%s",
            username, duration_ms, str(e),
        )
        raise HealthCheckError(
            f"Unexpected response checking profile for {username}: {e}",
            original_error=e,
        )

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.exception(
            "REDDIT_API_ERROR | action=check_profile_accessibility | username=%s | "
            "error=UNEXPECTED | duration_ms=%d",
            username, duration_ms,
        )
        raise HealthCheckError(
            f"Unexpected error checking profile for {username}: {e}",
            original_error=e,
        )


def classify_health_status(
    visibility_ratio: float,
    threshold: float,
) -> str:
    """Classify health status based on visibility ratio.

    Pure function — no side effects, no DB, no API calls.

    Args:
        visibility_ratio: Ratio of visible comments to total sampled (0.0 to 1.0).
        threshold: Visibility threshold above which avatar is classified ACTIVE.

    Returns:
        Health status string matching HealthStatus enum values:
        - "shadowbanned" when ratio == 0
        - "limited" when 0 < ratio < threshold
        - "active" when ratio >= threshold
    """
    if visibility_ratio == 0:
        return HealthStatus.SHADOWBANNED.value
    elif visibility_ratio < threshold:
        return HealthStatus.LIMITED.value
    else:
        return HealthStatus.ACTIVE.value


def _setting_enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _extract_external_status(payload: object) -> str | None:
    """Normalize common external checker responses into a HealthStatus value.

    Supported JSON shapes include:
    - {"status": "shadowbanned" | "suspended" | "active" | "not_shadowbanned"}
    - {"shadowbanned": true, "suspended": false}
    - {"is_shadowbanned": true, "is_suspended": false}

    Text responses are parsed defensively for common phrases.
    """
    if isinstance(payload, dict):
        raw_status = payload.get("status") or payload.get("result") or payload.get("state")
        if isinstance(raw_status, str):
            status = raw_status.strip().lower().replace("-", "_").replace(" ", "_")
            if status in {"shadowbanned", "shadow_banned"}:
                return HealthStatus.SHADOWBANNED.value
            if status in {"suspended", "banned", "not_found"}:
                return HealthStatus.SUSPENDED.value
            if status in {"active", "ok", "not_shadowbanned", "not_shadow_banned", "clear"}:
                return HealthStatus.ACTIVE.value

        if payload.get("shadowbanned") is True or payload.get("is_shadowbanned") is True:
            return HealthStatus.SHADOWBANNED.value
        if payload.get("suspended") is True or payload.get("is_suspended") is True:
            return HealthStatus.SUSPENDED.value
        if payload.get("banned") is True or payload.get("exists") is False:
            return HealthStatus.SUSPENDED.value
        if payload.get("shadowbanned") is False or payload.get("is_shadowbanned") is False:
            return HealthStatus.ACTIVE.value

    text = str(payload).strip().lower()
    if not text:
        return None
    if "not shadow" in text or "not-shadow" in text or "clear" in text:
        return HealthStatus.ACTIVE.value
    if "shadowban" in text or "shadow banned" in text or "shadow-banned" in text:
        return HealthStatus.SHADOWBANNED.value
    if "suspended" in text or "banned" in text or "not found" in text:
        return HealthStatus.SUSPENDED.value
    if "active" in text or "ok" in text:
        return HealthStatus.ACTIVE.value
    return None


def check_external_shadowban(
    db: Session,
    username: str,
) -> tuple[str | None, dict]:
    """Call the configured external shadowban checker.

    Returns (status, details). A None status means the checker is disabled,
    unconfigured, or returned an unrecognized answer; callers should fall back
    to the built-in Reddit visibility checks.
    """
    enabled = _setting_enabled(get_setting(db, "external_shadowban_checker_enabled"))
    template = (get_setting(db, "external_shadowban_checker_url_template") or "").strip()
    if not enabled or not template:
        return None, {"enabled": enabled, "configured": bool(template)}

    try:
        timeout = float(get_setting(db, "external_shadowban_checker_timeout_seconds") or "8")
    except ValueError:
        timeout = 8.0

    safe_username = quote(username.strip().lstrip("u/"), safe="")
    if "{username}" in template:
        url = template.replace("{username}", safe_username)
    else:
        url = template.rstrip("/") + "/" + safe_username

    logger.info(
        "EXTERNAL_SHADOWBAN_CHECK_CALL | username=%s | url_template_configured=%s",
        username,
        bool(template),
    )
    start_time = time.time()

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url)
        duration_ms = int((time.time() - start_time) * 1000)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            payload: object = response.json()
        else:
            try:
                payload = response.json()
            except ValueError:
                payload = response.text[:2000]

        status = _extract_external_status(payload)
        logger.info(
            "EXTERNAL_SHADOWBAN_CHECK_RESULT | username=%s | status=%s | duration_ms=%d",
            username,
            status or "unrecognized",
            duration_ms,
        )
        return status, {
            "enabled": True,
            "configured": True,
            "http_status": response.status_code,
            "duration_ms": duration_ms,
            "classification": status,
        }
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.warning(
            "EXTERNAL_SHADOWBAN_CHECK_ERROR | username=%s | error=%s | duration_ms=%d",
            username,
            type(e).__name__,
            duration_ms,
            exc_info=True,
        )
        return None, {
            "enabled": True,
            "configured": True,
            "duration_ms": duration_ms,
            "error": f"{type(e).__name__}: {str(e)[:200]}",
        }


def flag_pending_drafts_for_avatar(
    db: Session, avatar_id: uuid.UUID, reason: str
) -> int:
    """Flag pending drafts for an avatar whose health status became unhealthy.

    When an avatar transitions to SHADOWBANNED or SUSPENDED, this function
    queries all pending drafts for that avatar and logs a warning for each.
    The count is returned so it can be included in the health check result.

    The operator will see the avatar's health badge in the review queue (task 8.1),
    making it clear that these drafts should not be posted.

    Args:
        db: SQLAlchemy session.
        avatar_id: The UUID of the avatar whose drafts should be flagged.
        reason: The reason for flagging (e.g., "shadowbanned", "suspended").

    Returns:
        The number of pending drafts found for this avatar.
    """
    pending_drafts = (
        db.query(CommentDraft)
        .filter(
            and_(
                CommentDraft.avatar_id == avatar_id,
                CommentDraft.status == "pending",
            )
        )
        .all()
    )

    count = len(pending_drafts)

    if count > 0:
        draft_ids = [str(d.id) for d in pending_drafts]
        logger.warning(
            "PENDING_DRAFTS_FLAGGED | avatar_id=%s | reason=%s | "
            "pending_count=%d | draft_ids=%s",
            avatar_id, reason, count, draft_ids,
        )
    else:
        logger.info(
            "PENDING_DRAFTS_FLAGGED | avatar_id=%s | reason=%s | "
            "pending_count=0 | no_pending_drafts_to_flag",
            avatar_id, reason,
        )

    return count


def check_comment_visibility(
    username: str,
    max_comments: int,
    lookback_days: int,
) -> tuple[int, int]:
    """Fetch avatar's recent comments and check visibility.

    Uses an unauthenticated Reddit client to see which comments
    are visible to the public. The key insight: if a user is shadowbanned,
    their comments will NOT appear when fetched from an unauthenticated session.

    Args:
        username: The Reddit username to check (without u/ prefix).
        max_comments: Maximum number of recent comments to fetch.
        lookback_days: Only consider comments from the last N days.

    Returns:
        A tuple of (total_sampled, visible_count):
        - total_sampled: Number of comments within the lookback period
        - visible_count: Number of those comments that are visible
          (exist and have a body that isn't "[removed]" or "[deleted]")

    Raises:
        HealthCheckError: On network errors, timeouts, or unexpected failures.
            The caller should retain the avatar's previous status and increment
            consecutive_check_failures.
    """
    logger.info(
        "REDDIT_API_CALL | action=check_comment_visibility | username=%s | "
        "max_comments=%d | lookback_days=%d",
        username, max_comments, lookback_days,
    )
    start_time = time.time()

    try:
        reddit = get_reddit_client()
        redditor = reddit.redditor(ensure_username_bare(username))

        # Fetch recent comments from unauthenticated session
        comments = redditor.comments.new(limit=max_comments)

        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

        total_sampled = 0
        visible_count = 0

        for comment in comments:
            # Filter to only comments within the lookback period
            comment_time = datetime.fromtimestamp(
                comment.created_utc, tz=timezone.utc
            )
            if comment_time < cutoff:
                continue

            total_sampled += 1

            # A comment is visible if it exists and has a body
            # that isn't "[removed]" or "[deleted]"
            body = getattr(comment, "body", None)
            if body is not None and body not in ("[removed]", "[deleted]"):
                visible_count += 1

        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(
            "REDDIT_API_RESULT | action=check_comment_visibility | username=%s | "
            "total_sampled=%d | visible_count=%d | duration_ms=%d",
            username, total_sampled, visible_count, duration_ms,
        )
        return (total_sampled, visible_count)

    except NotFound as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(
            "REDDIT_API_ERROR | action=check_comment_visibility | username=%s | "
            "error=NotFound | duration_ms=%d | details=%s",
            username, duration_ms, str(e),
        )
        raise HealthCheckError(
            f"User not found when checking comments for {username}: {e}",
            original_error=e,
        )

    except Forbidden as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(
            "REDDIT_API_ERROR | action=check_comment_visibility | username=%s | "
            "error=Forbidden | duration_ms=%d | details=%s",
            username, duration_ms, str(e),
        )
        raise HealthCheckError(
            f"Access forbidden when checking comments for {username}: {e}",
            original_error=e,
        )

    except (RequestException, ServerError) as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(
            "REDDIT_API_ERROR | action=check_comment_visibility | username=%s | "
            "error=%s | duration_ms=%d | details=%s",
            username, type(e).__name__, duration_ms, str(e),
        )
        raise HealthCheckError(
            f"Network/server error checking comments for {username}: {e}",
            original_error=e,
        )

    except ResponseException as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(
            "REDDIT_API_ERROR | action=check_comment_visibility | username=%s | "
            "error=ResponseException | duration_ms=%d | details=%s",
            username, duration_ms, str(e),
        )
        raise HealthCheckError(
            f"Unexpected response checking comments for {username}: {e}",
            original_error=e,
        )

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.exception(
            "REDDIT_API_ERROR | action=check_comment_visibility | username=%s | "
            "error=UNEXPECTED | duration_ms=%d",
            username, duration_ms,
        )
        raise HealthCheckError(
            f"Unexpected error checking comments for {username}: {e}",
            original_error=e,
        )


def check_avatar_health(db: Session, avatar: Avatar) -> HealthCheckResult:
    """Perform a full health check on a single avatar.

    Algorithm:
    1. Read settings from SystemSetting table
    2. External shadowban checker, if configured
    3. Profile accessibility check (PRAW redditor lookup)
    4. If profile inaccessible → SUSPENDED
    5. If profile accessible → visibility check (fetch recent comments unauthenticated)
    5. If insufficient comments → retain previous status
    6. Classify based on visibility ratio
    7. Handle consecutive failures threshold
    8. Persist results to avatar (auto-freeze + audit log on status change)
    9. Return HealthCheckResult
    """
    start_time = time.time()

    # 1. Read settings
    min_comments = int(get_setting(db, "health_check_min_comments"))
    visibility_threshold = float(get_setting(db, "health_check_visibility_threshold"))
    max_comments_to_sample = int(get_setting(db, "health_check_max_comments_to_sample"))
    comment_lookback_days = int(get_setting(db, "health_check_comment_lookback_days"))
    max_failures_before_limited = int(get_setting(db, "health_check_max_failures_before_limited"))
    max_failures_before_unknown = int(get_setting(db, "health_check_max_failures_before_unknown"))

    previous_status = avatar.health_status or HealthStatus.UNKNOWN.value
    username = avatar.reddit_username

    # Initialize result fields
    new_status = previous_status
    detection_method = "visibility_check"
    visibility_ratio: float | None = None
    comments_sampled = 0
    comments_visible = 0
    error_msg: str | None = None
    external_checker_details: dict | None = None

    try:
        # 2. External checker, if configured. It avoids spending Reddit API
        # budget when Tzvi's checker has a decisive answer.
        external_status, external_checker_details = check_external_shadowban(db, username)

        if external_status is not None:
            new_status = external_status
            detection_method = "external_shadowban_checker"
        else:
            # 3. Profile accessibility check
            profile_status, profile_method = check_profile_accessibility(username)

            if profile_status is not None:
                # 3. Profile inaccessible → SUSPENDED
                new_status = profile_status
                detection_method = profile_method
            else:
                # 4. Profile accessible → visibility check
                total_sampled, visible_count = check_comment_visibility(
                    username, max_comments_to_sample, comment_lookback_days
                )
                comments_sampled = total_sampled
                comments_visible = visible_count

                if total_sampled < min_comments:
                    # 5. Insufficient comments → retain previous status
                    new_status = previous_status
                    detection_method = "visibility_check"
                else:
                    # 6. Classify based on visibility ratio
                    visibility_ratio = visible_count / total_sampled
                    new_status = classify_health_status(visibility_ratio, visibility_threshold)
                    detection_method = "visibility_check"

        # 8. Successful check → reset consecutive_check_failures
        avatar.consecutive_check_failures = 0

    except HealthCheckError as e:
        # 7. API error → retain previous status, increment failures
        error_msg = str(e)
        new_status = previous_status
        detection_method = "api_error"
        avatar.consecutive_check_failures = (avatar.consecutive_check_failures or 0) + 1

        # Apply failure thresholds
        if avatar.consecutive_check_failures >= max_failures_before_unknown:
            new_status = HealthStatus.UNKNOWN.value
        elif avatar.consecutive_check_failures >= max_failures_before_limited:
            new_status = HealthStatus.LIMITED.value

    # 9. Persist results to avatar
    duration_ms = int((time.time() - start_time) * 1000)
    now = datetime.now(timezone.utc)

    # Update health_status (and health_status_changed_at if changed)
    if new_status != previous_status:
        avatar.health_status = new_status
        avatar.health_status_changed_at = now

        # Auto-freeze when status transitions to shadowbanned or suspended
        if new_status in (HealthStatus.SHADOWBANNED.value, HealthStatus.SUSPENDED.value):
            avatar.is_frozen = True
            avatar.freeze_reason = new_status
            avatar.frozen_at = now
            logger.warning(
                "AVATAR_AUTO_FROZEN | username=%s | reason=%s | "
                "previous_status=%s | detection_method=%s",
                username, new_status, previous_status, detection_method,
            )

            # Flag pending drafts for this avatar
            try:
                flagged_count = flag_pending_drafts_for_avatar(db, avatar.id, new_status)
                if flagged_count > 0:
                    logger.warning(
                        "AVATAR_PENDING_DRAFTS_WARNING | username=%s | "
                        "reason=%s | flagged_drafts=%d",
                        username, new_status, flagged_count,
                    )
            except Exception:
                logger.warning(
                    "Failed to flag pending drafts for %s",
                    username,
                    exc_info=True,
                )

    # Always update last_health_check and health_check_details
    avatar.last_health_check = now
    avatar.health_check_details = {
        "checked_at": now.isoformat(),
        "profile_accessible": detection_method != "profile_check",
        "comments_sampled": comments_sampled,
        "comments_visible": comments_visible,
        "visibility_ratio": visibility_ratio,
        "classification": new_status,
        "detection_method": detection_method,
        "duration_ms": duration_ms,
        "error": error_msg,
        "external_checker": external_checker_details,
    }

    db.add(avatar)
    db.commit()

    # Audit log: status change
    if new_status != previous_status:
        try:
            from app.services.audit import log_system_action

            log_system_action(
                db=db,
                action="health_status_changed",
                entity_type="avatar",
                entity_id=avatar.id,
                details={
                    "previous_status": previous_status,
                    "new_status": new_status,
                    "reddit_username": username,
                    "detection_method": detection_method,
                    "external_checker": external_checker_details,
                },
            )
        except Exception:
            logger.warning(
                "Failed to audit log health status change for %s",
                username,
                exc_info=True,
            )

    # 10. Return HealthCheckResult
    result = HealthCheckResult(
        avatar_id=avatar.id,
        username=username,
        previous_status=previous_status,
        new_status=new_status,
        detection_method=detection_method,
        visibility_ratio=visibility_ratio,
        comments_sampled=comments_sampled,
        comments_visible=comments_visible,
        details=avatar.health_check_details,
        error=error_msg,
    )

    logger.info(
        "HEALTH_CHECK_COMPLETE | username=%s | previous=%s | new=%s | "
        "detection_method=%s | visibility_ratio=%s | sampled=%d | visible=%d | "
        "failures=%d | duration_ms=%d",
        username, previous_status, new_status, detection_method,
        visibility_ratio, comments_sampled, comments_visible,
        avatar.consecutive_check_failures, duration_ms,
    )

    return result


def run_health_check_batch(db: Session) -> dict:
    """Run health checks for all eligible avatars.

    Eligible: active=True, is_frozen=False, last_health_check older than
    interval or null.

    Algorithm:
    1. Read settings (interval_hours, rate_limit_delay_seconds)
    2. Query eligible avatars
    3. For each avatar: check health, track results, sleep if batch > 10
    4. Log batch summary
    5. Return summary dict

    Returns:
        Summary dict with counts: checked, changed, errors, duration_ms
    """
    start_time = time.time()

    # 1. Read settings
    interval_hours = int(get_setting(db, "health_check_interval_hours"))
    rate_limit_delay = float(get_setting(db, "health_check_rate_limit_delay_seconds"))

    stale_cutoff = datetime.now(timezone.utc) - timedelta(hours=interval_hours)

    # 2. Query eligible avatars.
    eligible_avatars = db.query(Avatar).filter(
        and_(
            Avatar.active == True,  # noqa: E712
            Avatar.is_frozen == False,  # noqa: E712
            or_(
                Avatar.last_health_check.is_(None),
                Avatar.last_health_check < stale_cutoff,
            ),
        )
    ).all()

    batch_size = len(eligible_avatars)
    checked_count = 0
    changed_count = 0
    error_count = 0

    logger.info(
        "HEALTH_CHECK_BATCH_START | eligible_avatars=%d | interval_hours=%d | "
        "rate_limit_delay=%.1f",
        batch_size, interval_hours, rate_limit_delay,
    )

    # 3. Process each avatar
    for i, avatar in enumerate(eligible_avatars):
        try:
            result = check_avatar_health(db, avatar)
            checked_count += 1
            if result.status_changed:
                changed_count += 1
        except Exception as e:
            error_count += 1
            logger.error(
                "HEALTH_CHECK_BATCH_ERROR | avatar=%s | error=%s | details=%s",
                avatar.reddit_username, type(e).__name__, str(e),
            )

        # Rate limit: sleep between checks if batch > 10
        if batch_size > 10 and i < batch_size - 1:
            time.sleep(rate_limit_delay)

    # 4. Log batch summary
    duration_ms = int((time.time() - start_time) * 1000)

    logger.info(
        "HEALTH_CHECK_BATCH_COMPLETE | checked=%d | changed=%d | errors=%d | "
        "duration_ms=%d | batch_size=%d",
        checked_count, changed_count, error_count, duration_ms, batch_size,
    )

    # 5. Audit log: batch completion
    try:
        from app.services.audit import log_system_action

        log_system_action(
            db=db,
            action="health_check_batch_completed",
            entity_type="avatar",
            details={
                "checked": checked_count,
                "changed": changed_count,
                "errors": error_count,
                "duration_ms": duration_ms,
            },
        )
    except Exception:
        logger.warning(
            "Failed to audit log health check batch completion",
            exc_info=True,
        )

    # 6. Return summary
    summary = {
        "checked": checked_count,
        "changed": changed_count,
        "errors": error_count,
        "duration_ms": duration_ms,
    }

    return summary
