import logging
from uuid import UUID
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models.comment_draft import CommentDraft
from app.models.post_draft import PostDraft
from app.services.transparency import record_activity_event

logger = logging.getLogger(__name__)

router = APIRouter()


class UpdateCommentRequest(BaseModel):
    status: str | None = None  # approved | rejected
    edited_draft: str | None = None


class UpdatePostRequest(BaseModel):
    status: str | None = None
    edited_title: str | None = None
    edited_body: str | None = None


@router.get("/comments")
def list_pending_comments(
    status: str = "pending",
    client_id: UUID | None = None,
    db: Session = Depends(get_db),
):
    """List comment drafts for review."""
    query = db.query(CommentDraft).filter(CommentDraft.status == status)
    if client_id:
        query = query.filter(CommentDraft.client_id == client_id)
    query = query.order_by(CommentDraft.created_at.desc())
    return query.limit(50).all()


@router.patch("/comments/{comment_id}")
def update_comment(comment_id: UUID, data: UpdateCommentRequest, db: Session = Depends(get_db)):
    """Approve, reject, or edit a comment draft."""
    comment = db.query(CommentDraft).filter(CommentDraft.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    if data.status:
        comment.status = data.status
        if data.status == "posted":
            comment.posted_at = datetime.now(timezone.utc)
    if data.edited_draft is not None:
        comment.edited_draft = data.edited_draft

    db.commit()
    db.refresh(comment)

    if data.status:
        try:
            thread_title = comment.thread.post_title if comment.thread else "Unknown"
            avatar_username = comment.avatar.reddit_username if comment.avatar else "Unknown"
            action = data.status
            message = f"Comment {action} for '{thread_title}' by {avatar_username}"
            metadata = {
                "draft_id": str(comment.id),
                "thread_title": thread_title,
                "action": action,
                "avatar_username": avatar_username,
            }
            record_activity_event(db, "review", message, comment.client_id, metadata)
        except Exception:
            logger.warning("Failed to record activity event for comment %s", comment_id, exc_info=True)

    # Piggyback phase evaluation after posting
    if data.status == "posted":
        try:
            from app.services.phase import PhaseEvaluator, PhaseTransitionManager
            from app.services.phase_lock import PhaseTransitionLock
            from app.config import get_settings
            import redis

            avatar = comment.avatar
            if avatar and PhaseEvaluator().should_piggyback(avatar):
                result = PhaseEvaluator().evaluate(db, avatar)
                if result.action == "promote":
                    redis_client = redis.from_url(get_settings().redis_url)
                    lock = PhaseTransitionLock(redis_client)
                    PhaseTransitionManager(lock).promote(db, avatar, result.criteria_values)
                elif result.action == "demote":
                    redis_client = redis.from_url(get_settings().redis_url)
                    lock = PhaseTransitionLock(redis_client)
                    PhaseTransitionManager(lock).demote(db, avatar, result.target_phase, result.trigger_reason)
        except Exception:
            logger.warning("Phase evaluation failed for comment %s", comment_id, exc_info=True)

    return comment


@router.get("/posts")
def list_pending_posts(
    status: str = "pending",
    client_id: UUID | None = None,
    db: Session = Depends(get_db),
):
    """List post drafts for review."""
    query = db.query(PostDraft).filter(PostDraft.status == status)
    if client_id:
        query = query.filter(PostDraft.client_id == client_id)
    query = query.order_by(PostDraft.created_at.desc())
    return query.limit(50).all()


@router.patch("/posts/{post_id}")
def update_post(post_id: UUID, data: UpdatePostRequest, db: Session = Depends(get_db)):
    """Approve, reject, or edit a post draft."""
    post = db.query(PostDraft).filter(PostDraft.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    if data.status:
        post.status = data.status
        if data.status == "posted":
            post.posted_at = datetime.now(timezone.utc)
    if data.edited_title is not None:
        post.edited_title = data.edited_title
    if data.edited_body is not None:
        post.edited_body = data.edited_body

    db.commit()
    db.refresh(post)
    return post
