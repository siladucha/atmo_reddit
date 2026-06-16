"""Notification service — creates notifications and publishes to Redis PubSub.

Usage from Celery tasks:
    from app.services.notifications import notify_client
    notify_client(db, client_id, "success", "Pipeline complete", "3 new drafts ready", "/clients/{id}/review")

Usage from route handlers:
    from app.services.notifications import notify_client
    notify_client(db, client_id, "info", "Draft approved", link=f"/clients/{client_id}/review")
"""

import json
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.notification import Notification

logger = get_logger(__name__)


def notify_client(
    db: Session,
    client_id: uuid.UUID,
    type: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
    user_id: uuid.UUID | None = None,
) -> Notification | None:
    """Create a notification and publish to Redis PubSub for real-time delivery.
    
    Args:
        db: SQLAlchemy session
        client_id: Target client UUID
        type: Notification type (info, success, warning, error)
        title: Short message (max 255 chars)
        body: Optional longer description
        link: Optional URL to navigate to
        user_id: Optional specific user (None = all users of this client)
    
    Returns:
        The created Notification, or None on failure.
    """
    try:
        notif = Notification(
            id=uuid.uuid4(),
            client_id=client_id,
            user_id=user_id,
            type=type,
            title=title[:255],
            body=body[:500] if body else None,
            link=link,
            is_read=False,
        )
        db.add(notif)
        db.commit()
        db.refresh(notif)

        # Publish to Redis PubSub for SSE delivery
        _publish_to_redis(notif)

        return notif
    except Exception as e:
        logger.warning("Failed to create notification: %s", e)
        db.rollback()
        return None


def _publish_to_redis(notif: Notification) -> None:
    """Publish notification to Redis PubSub channel for real-time SSE delivery."""
    try:
        import redis
        from app.config import get_settings
        
        r = redis.from_url(get_settings().redis_url)
        channel = f"notifications:client:{notif.client_id}"
        payload = json.dumps({
            "id": str(notif.id),
            "type": notif.type,
            "title": notif.title,
            "body": notif.body,
            "link": notif.link,
            "created_at": notif.created_at.isoformat() if notif.created_at else None,
        })
        r.publish(channel, payload)
        r.close()
    except Exception as e:
        logger.debug("Redis publish failed (non-critical): %s", e)


def get_unread_count(db: Session, client_id: uuid.UUID) -> int:
    """Get unread notification count for a client."""
    return (
        db.query(Notification)
        .filter(Notification.client_id == client_id, Notification.is_read == False)
        .count()
    )


def get_notifications(
    db: Session, client_id: uuid.UUID, limit: int = 30, include_read: bool = True
) -> list[Notification]:
    """Get recent notifications for a client."""
    query = db.query(Notification).filter(Notification.client_id == client_id)
    if not include_read:
        query = query.filter(Notification.is_read == False)
    return query.order_by(Notification.created_at.desc()).limit(limit).all()


def mark_all_read(db: Session, client_id: uuid.UUID) -> int:
    """Mark all notifications as read for a client. Returns count updated."""
    count = (
        db.query(Notification)
        .filter(Notification.client_id == client_id, Notification.is_read == False)
        .update({"is_read": True})
    )
    db.commit()
    return count


def cleanup_old(db: Session, days: int = 7) -> int:
    """Delete notifications older than N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    count = db.query(Notification).filter(Notification.created_at < cutoff).delete()
    db.commit()
    return count
