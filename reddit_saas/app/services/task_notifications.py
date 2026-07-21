"""Task notification helpers — called from Celery tasks to emit client notifications.

These functions handle their own DB session (since Celery tasks don't share
the FastAPI request session). They are fire-and-forget (never raise).

Usage in a Celery task:
    from app.services.task_notifications import notify_pipeline_complete
    notify_pipeline_complete(client_id, drafts_count=3)
"""

import uuid
from app.logging_config import get_logger

logger = get_logger(__name__)


def _notify(client_id, type: str, title: str, body: str = None, link: str = None):
    """Internal: create notification with a fresh DB session."""
    try:
        from app.database import SessionLocal
        from app.services.notifications import notify_client

        db = SessionLocal()
        try:
            notify_client(
                db=db,
                client_id=uuid.UUID(str(client_id)),
                type=type,
                title=title,
                body=body,
                link=link,
            )
        finally:
            db.close()
    except Exception as e:
        logger.debug("Task notification failed (non-critical): %s", e)


def notify_pipeline_complete(client_id, drafts_count: int = 0):
    """Pipeline finished — new drafts ready for review."""
    if drafts_count > 0:
        _notify(
            client_id,
            "success",
            f"Pipeline complete: {drafts_count} new draft{'s' if drafts_count != 1 else ''}",
            "New AI-generated comments ready for your review.",
            f"/clients/{client_id}/review",
        )


def notify_epg_rebuilt(client_id, slots_count: int = 0):
    """EPG schedule rebuilt."""
    _notify(
        client_id,
        "info",
        f"Schedule updated: {slots_count} slot{'s' if slots_count != 1 else ''} today",
        None,
        f"/clients/{client_id}/epg",
    )


def notify_draft_posted(client_id, subreddit: str = "", reddit_url: str = None):
    """A comment was posted on Reddit."""
    title = f"Comment posted on r/{subreddit}" if subreddit else "Comment posted"
    _notify(
        client_id,
        "success",
        title,
        None,
        reddit_url or f"/clients/{client_id}/review",
    )


def notify_avatar_frozen(client_id, avatar_name: str, reason: str = ""):
    """Avatar was frozen (health issue)."""
    body = f"Reason: {reason}" if reason else None
    _notify(
        client_id,
        "warning",
        f"Voice {avatar_name} paused",
        body,
        f"/clients/{client_id}/avatars",
    )


def notify_error(client_id, title: str, body: str = None):
    """Generic error notification."""
    _notify(client_id, "error", title, body, None)
