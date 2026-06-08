"""Reddit account status service.

Fetches the real status of a Reddit account (existence, suspension, karma,
account age) via PRAW and caches the result on the Avatar model.

Isolated from `services/reddit.py` (scraping) by single-responsibility:
this module only reads account metadata, never scrapes content.
"""

from app.logging_config import get_logger
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

from prawcore.exceptions import NotFound, Forbidden, RequestException, ResponseException
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.avatar import Avatar
from app.services.reddit import get_reddit_client
from app.services.sanitize import ensure_username_bare

logger = get_logger(__name__)


STATUS_ACTIVE = "active"
STATUS_SUSPENDED = "suspended"
STATUS_NOT_FOUND = "not_found"
STATUS_UNKNOWN = "unknown"
STATUS_ERROR = "error"


@dataclass
class RedditAccountStatus:
    """Result of a Reddit account status check."""
    exists: bool
    is_suspended: bool
    comment_karma: int
    post_karma: int
    account_created: datetime | None
    icon_url: str | None
    error: str | None = None

    @property
    def status_label(self) -> str:
        if self.error:
            return STATUS_ERROR
        if not self.exists:
            return STATUS_NOT_FOUND
        if self.is_suspended:
            return STATUS_SUSPENDED
        return STATUS_ACTIVE

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.account_created:
            d["account_created"] = self.account_created.isoformat()
        d["status"] = self.status_label
        return d


def _empty_status(error: str | None = None, exists: bool = False, suspended: bool = False) -> RedditAccountStatus:
    return RedditAccountStatus(
        exists=exists,
        is_suspended=suspended,
        comment_karma=0,
        post_karma=0,
        account_created=None,
        icon_url=None,
        error=error,
    )


def fetch_reddit_status(username: str) -> RedditAccountStatus:
    """Call Reddit API and return a RedditAccountStatus.

    Does NOT touch the database. Pure API wrapper.
    """
    logger.info("REDDIT_API_CALL | action=fetch_user_status | username=u/%s", username)
    start_time = time.time()

    try:
        reddit = get_reddit_client()
        redditor = reddit.redditor(ensure_username_bare(username))

        if getattr(redditor, "is_suspended", False):
            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(
                "REDDIT_API_RESULT | action=fetch_user_status | username=u/%s | "
                "status=suspended | duration_ms=%d",
                username, duration_ms,
            )
            return _empty_status(exists=True, suspended=True)

        created_utc = getattr(redditor, "created_utc", None)
        account_created = (
            datetime.fromtimestamp(created_utc, tz=timezone.utc) if created_utc else None
        )

        icon_url = getattr(redditor, "icon_img", None) or None

        duration_ms = int((time.time() - start_time) * 1000)
        comment_karma = int(getattr(redditor, "comment_karma", 0) or 0)
        post_karma = int(getattr(redditor, "link_karma", 0) or 0)

        logger.info(
            "REDDIT_API_RESULT | action=fetch_user_status | username=u/%s | "
            "status=active | comment_karma=%d | post_karma=%d | "
            "account_age_days=%s | duration_ms=%d",
            username, comment_karma, post_karma,
            (datetime.now(timezone.utc) - account_created).days if account_created else "?",
            duration_ms,
        )

        return RedditAccountStatus(
            exists=True,
            is_suspended=False,
            comment_karma=comment_karma,
            post_karma=post_karma,
            account_created=account_created,
            icon_url=icon_url,
            error=None,
        )

    except NotFound:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.warning(
            "REDDIT_API_RESULT | action=fetch_user_status | username=u/%s | "
            "status=not_found | duration_ms=%d",
            username, duration_ms,
        )
        return _empty_status(exists=False)

    except Forbidden:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.warning(
            "REDDIT_API_RESULT | action=fetch_user_status | username=u/%s | "
            "status=forbidden_suspended | duration_ms=%d",
            username, duration_ms,
        )
        return _empty_status(exists=True, suspended=True)

    except (RequestException, ResponseException) as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(
            "REDDIT_API_ERROR | action=fetch_user_status | username=u/%s | "
            "error=%s | duration_ms=%d | details=%s",
            username, type(exc).__name__, duration_ms, exc,
        )
        return _empty_status(error=f"reddit_api_error: {exc}")

    except Exception as exc:  # pragma: no cover — defensive
        duration_ms = int((time.time() - start_time) * 1000)
        logger.exception(
            "REDDIT_API_ERROR | action=fetch_user_status | username=u/%s | "
            "error=UNEXPECTED | duration_ms=%d",
            username, duration_ms,
        )
        return _empty_status(error=f"unexpected_error: {exc}")


def check_reddit_status(db: Session, avatar: Avatar) -> RedditAccountStatus:
    """Fetch Reddit status, persist to Avatar, return result.

    On API/network error: leaves cached fields untouched, returns status with
    `error` set. On all other outcomes: updates the cached fields, sets
    `reddit_status_checked_at`, syncs `is_shadowbanned`, and writes an audit
    log entry if shadowban state changed.
    """
    status = fetch_reddit_status(avatar.reddit_username)

    if status.error:
        logger.warning(
            "REDDIT_STATUS_CHECK | username=u/%s | result=error | error=%s",
            avatar.reddit_username, status.error,
        )
        return status

    previous_shadowbanned = avatar.is_shadowbanned
    new_status_label = status.status_label

    avatar.reddit_status = new_status_label
    avatar.reddit_karma_comment = status.comment_karma
    avatar.reddit_karma_post = status.post_karma
    avatar.reddit_account_created = status.account_created
    avatar.reddit_icon_url = status.icon_url
    avatar.reddit_status_checked_at = datetime.now(timezone.utc)

    new_shadowbanned = status.is_suspended
    if new_shadowbanned != previous_shadowbanned:
        avatar.is_shadowbanned = new_shadowbanned
        logger.warning(
            "REDDIT_STATUS_CHANGE | username=u/%s | field=shadowban | "
            "old=%s | new=%s | reddit_status=%s",
            avatar.reddit_username, previous_shadowbanned, new_shadowbanned, new_status_label,
        )
        db.add(AuditLog(
            action="reddit_status_shadowban_changed",
            entity_type="avatar",
            entity_id=avatar.id,
            details={
                "username": avatar.reddit_username,
                "previous_shadowbanned": previous_shadowbanned,
                "new_shadowbanned": new_shadowbanned,
                "reddit_status": new_status_label,
            },
        ))
    else:
        logger.info(
            "REDDIT_STATUS_CHECK | username=u/%s | result=%s | "
            "karma_comment=%d | karma_post=%d",
            avatar.reddit_username, new_status_label,
            status.comment_karma, status.post_karma,
        )

    db.commit()
    db.refresh(avatar)

    # Karma sync — derive per-subreddit karma from the avatar's recent comment
    # history (Req 3). Failures must not block the status check itself.
    try:
        from app.services import karma_tracker

        karma_tracker.sync_avatar_from_reddit(db, avatar)
        db.commit()
    except Exception:
        logger.warning(
            "Subreddit karma sync failed for u/%s", avatar.reddit_username, exc_info=True
        )
        db.rollback()

    # CQS check — read bot reply from r/WhatIsMyCQS if avatar posted there.
    # Failures must not block the status check itself.
    try:
        from app.services.cqs_checker import update_avatar_cqs_from_reddit

        update_avatar_cqs_from_reddit(db, avatar)
        db.commit()
    except Exception:
        logger.warning(
            "CQS check failed for u/%s", avatar.reddit_username, exc_info=True
        )
        db.rollback()

    return status


def check_all_reddit_statuses(
    db: Session,
    avatars: list[Avatar],
    delay_seconds: float = 2.0,
    *,
    force: bool = False,
) -> list[dict]:
    """Check Reddit status for many avatars with rate limiting.

    Sleeps `delay_seconds` between calls (only when there are >10 avatars,
    per spec). Continues on per-avatar errors. Returns a summary list.
    """
    results: list[dict] = []
    apply_delay = len(avatars) > 10

    logger.info(
        "REDDIT_BATCH | action=check_all_statuses | avatar_count=%d | "
        "delay_seconds=%.1f | rate_limiting=%s",
        len(avatars), delay_seconds, apply_delay,
    )

    from app.services.reddit_freshness import is_reddit_status_fresh

    for i, avatar in enumerate(avatars):
        try:
            if not force and is_reddit_status_fresh(db, avatar):
                logger.info(
                    "REDDIT_STATUS_CHECK_SKIPPED | username=u/%s | reason=fresh_cache | checked_at=%s",
                    avatar.reddit_username, avatar.reddit_status_checked_at,
                )
                results.append({
                    "avatar_id": str(avatar.id),
                    "username": avatar.reddit_username,
                    "status": avatar.reddit_status,
                    "error": None,
                    "skipped": "fresh_cache",
                })
            else:
                status = check_reddit_status(db, avatar)
                results.append({
                    "avatar_id": str(avatar.id),
                    "username": avatar.reddit_username,
                    "status": status.status_label,
                    "error": status.error,
                })
        except Exception as exc:  # pragma: no cover — defensive
            logger.exception("Failed status check for u/%s", avatar.reddit_username)
            results.append({
                "avatar_id": str(avatar.id),
                "username": avatar.reddit_username,
                "status": STATUS_ERROR,
                "error": str(exc),
            })

        if apply_delay and i < len(avatars) - 1:
            logger.debug("REDDIT_RATE_LIMIT_SLEEP | seconds=%.1f | progress=%d/%d", delay_seconds, i + 1, len(avatars))
            time.sleep(delay_seconds)

    logger.info(
        "REDDIT_BATCH_DONE | action=check_all_statuses | total=%d | "
        "active=%d | suspended=%d | not_found=%d | errors=%d",
        len(results),
        sum(1 for r in results if r["status"] == STATUS_ACTIVE),
        sum(1 for r in results if r["status"] == STATUS_SUSPENDED),
        sum(1 for r in results if r["status"] == STATUS_NOT_FOUND),
        sum(1 for r in results if r["status"] == STATUS_ERROR),
    )

    return results
