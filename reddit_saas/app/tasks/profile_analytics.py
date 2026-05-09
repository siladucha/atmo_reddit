"""Scheduled Reddit profile analytics snapshots.

Keeps the avatar Performance tab populated without requiring an operator to
open each avatar card. The job is intentionally stale-only and batch-limited
because every snapshot uses Reddit API calls.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_

from app.database import SessionLocal
from app.models.avatar import Avatar
from app.models.avatar_profile_snapshot import AvatarProfileSnapshot
from app.services.reddit_freshness import (
    profile_analytics_batch_limit,
    profile_analytics_freshness_hours,
)
from app.tasks.worker import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="snapshot_avatar_profile_analytics")
def snapshot_avatar_profile_analytics(avatar_id: str, force: bool = False) -> dict:
    """Fetch and save one avatar profile analytics snapshot."""
    from app.services.reddit_profile_analytics import fetch_and_save, load_latest_snapshot

    db = SessionLocal()
    try:
        avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        if not avatar:
            return {"status": "not_found", "avatar_id": avatar_id}
        if not avatar.active or avatar.is_frozen:
            return {"status": "skipped", "reason": "inactive_or_frozen", "username": avatar.reddit_username}

        if not force:
            latest = load_latest_snapshot(db, avatar.id)
            freshness_hours = profile_analytics_freshness_hours(db)
            if latest and latest.fetched_at:
                checked_at = latest.fetched_at
                if checked_at.tzinfo is None:
                    checked_at = checked_at.replace(tzinfo=timezone.utc)
                if checked_at >= datetime.now(timezone.utc) - timedelta(hours=freshness_hours):
                    return {"status": "skipped", "reason": "fresh_cache", "username": avatar.reddit_username}

        analytics = fetch_and_save(db, avatar.id, avatar.reddit_username)
        db.commit()
        if analytics.error:
            return {"status": "error", "username": avatar.reddit_username, "error": analytics.error}
        return {
            "status": "saved",
            "username": avatar.reddit_username,
            "total_karma": analytics.total_karma,
            "fetched_at": analytics.fetched_at.isoformat(),
        }
    except Exception as exc:
        db.rollback()
        logger.exception("Profile analytics snapshot failed for avatar_id=%s", avatar_id)
        return {"status": "error", "avatar_id": avatar_id, "error": str(exc)}
    finally:
        db.close()


@celery_app.task(name="snapshot_profile_analytics_all_avatars")
def snapshot_profile_analytics_all_avatars(delay_seconds: float = 3.0) -> dict:
    """Refresh stale profile snapshots for active avatars in a bounded batch."""
    from app.services.reddit_profile_analytics import fetch_and_save

    db = SessionLocal()
    stats = {"processed": 0, "saved": 0, "errors": 0, "skipped": 0}
    try:
        freshness_hours = profile_analytics_freshness_hours(db)
        batch_limit = profile_analytics_batch_limit(db)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=freshness_hours)

        latest_snapshot_subq = (
            db.query(
                AvatarProfileSnapshot.avatar_id.label("avatar_id"),
                AvatarProfileSnapshot.fetched_at.label("fetched_at"),
            )
            .distinct(AvatarProfileSnapshot.avatar_id)
            .filter(AvatarProfileSnapshot.error.is_(None))
            .order_by(AvatarProfileSnapshot.avatar_id, AvatarProfileSnapshot.fetched_at.desc())
            .subquery()
        )

        avatars = (
            db.query(Avatar)
            .outerjoin(latest_snapshot_subq, Avatar.id == latest_snapshot_subq.c.avatar_id)
            .filter(
                Avatar.active.is_(True),
                Avatar.is_frozen.is_(False),
                Avatar.health_status.notin_(("shadowbanned", "suspended")),
                or_(
                    latest_snapshot_subq.c.fetched_at.is_(None),
                    latest_snapshot_subq.c.fetched_at < cutoff,
                ),
            )
            .order_by(latest_snapshot_subq.c.fetched_at.asc().nullsfirst(), Avatar.created_at.asc())
            .limit(batch_limit)
            .all()
        )

        logger.info(
            "Profile analytics snapshot: processing %d stale avatars (freshness=%sh, limit=%s)",
            len(avatars),
            freshness_hours,
            batch_limit,
        )

        for avatar in avatars:
            stats["processed"] += 1
            try:
                analytics = fetch_and_save(db, avatar.id, avatar.reddit_username)
                if analytics.error:
                    stats["errors"] += 1
                    logger.warning(
                        "Profile analytics snapshot error for u/%s: %s",
                        avatar.reddit_username,
                        analytics.error,
                    )
                else:
                    stats["saved"] += 1
                db.commit()
            except Exception:
                stats["errors"] += 1
                db.rollback()
                logger.exception("Profile analytics snapshot failed for u/%s", avatar.reddit_username)

            if delay_seconds > 0:
                time.sleep(delay_seconds)

        return stats
    finally:
        db.close()
