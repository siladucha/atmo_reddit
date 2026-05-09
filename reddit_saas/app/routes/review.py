import logging
from uuid import UUID
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.dependencies.admin import require_superuser
from app.models.comment_draft import CommentDraft
from app.models.post_draft import PostDraft
from app.models.user import User
from app.services.transparency import record_activity_event
from app.services import audit as audit_service

logger = logging.getLogger(__name__)

router = APIRouter()


class UpdateCommentRequest(BaseModel):
    status: str | None = None  # approved | rejected | posted
    edited_draft: str | None = None

    def validate_status(self) -> None:
        """Raise ValueError if status is not in the allowed whitelist."""
        allowed = {"approved", "rejected", "posted", "pending"}
        if self.status and self.status not in allowed:
            raise ValueError(f"Invalid status: {self.status}")


class UpdatePostRequest(BaseModel):
    status: str | None = None
    edited_title: str | None = None
    edited_body: str | None = None

    def validate_status(self) -> None:
        """Raise ValueError if status is not in the allowed whitelist."""
        allowed = {"approved", "rejected", "posted", "pending"}
        if self.status and self.status not in allowed:
            raise ValueError(f"Invalid status: {self.status}")


@router.get("/comments")
def list_pending_comments(
    status: str = "pending",
    client_id: UUID | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """List comment drafts for review."""
    query = db.query(CommentDraft).filter(CommentDraft.status == status)
    if client_id:
        query = query.filter(CommentDraft.client_id == client_id)
    query = query.order_by(CommentDraft.created_at.desc())
    return query.limit(50).all()


@router.patch("/comments/{comment_id}")
def update_comment(
    comment_id: UUID,
    data: UpdateCommentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Approve, reject, or edit a comment draft."""
    comment = db.query(CommentDraft).filter(CommentDraft.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    # Validate status against whitelist
    try:
        data.validate_status()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Validate edited_draft length
    if data.edited_draft is not None and len(data.edited_draft) > 2000:
        raise HTTPException(status_code=422, detail="Edited draft too long (max 2000 chars)")

    transitioned_to_posted = False
    if data.status:
        old_status = comment.status
        transitioned_to_posted = data.status == "posted" and comment.status != "posted"
        comment.status = data.status
        if data.status == "posted":
            comment.posted_at = datetime.now(timezone.utc)
        elif old_status == "posted" and data.status != "posted":
            # Reverting from posted — clear posted_at
            comment.posted_at = None
    if data.edited_draft is not None:
        comment.edited_draft = data.edited_draft

    db.commit()
    db.refresh(comment)

    # Karma tracking — increment per-subreddit comment_count when transitioning
    # to "posted" (Req 2.5). The reddit_score is typically populated later by
    # an external feedback loop; record_comment_score handles None gracefully.
    if transitioned_to_posted:
        try:
            from app.services import karma_tracker

            thread = comment.thread
            avatar = comment.avatar
            if thread and avatar and thread.subreddit:
                karma_tracker.record_comment_score(
                    db,
                    avatar=avatar,
                    subreddit_name=thread.subreddit,
                    new_score=int(comment.reddit_score or 0),
                    previous_score=None,
                    increment_count=True,
                )
                db.commit()
        except Exception:
            logger.warning(
                "Karma tracking failed for comment %s", comment_id, exc_info=True
            )

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

        # Audit log for review action
        try:
            audit_service.log_action(
                db=db,
                user_id=current_user.id,
                action="status_transition",
                entity_type="comment_draft",
                entity_id=comment.id,
                client_id=comment.client_id,
                details={
                    "old_status": old_status,
                    "new_status": data.status,
                    "avatar_username": comment.avatar.reddit_username if comment.avatar else None,
                    "thread_title": comment.thread.post_title if comment.thread else None,
                },
            )
        except Exception:
            logger.warning("Failed to audit log comment %s", comment_id, exc_info=True)

    # Self-learning loop: capture edit record on approve/reject
    if data.status in ("approved", "rejected"):
        try:
            from app.services.learning import LearningService

            thread = comment.thread
            if thread:
                # Determine learning status based on action and edit state
                if data.status == "rejected":
                    learning_status = "rejected"
                elif comment.edited_draft is None or comment.edited_draft == comment.ai_draft:
                    learning_status = "approved_unchanged"
                else:
                    learning_status = "approved"

                learning_service = LearningService()
                learning_service.capture_edit_record(
                    db=db, draft=comment, thread=thread, status=learning_status
                )
                db.commit()
        except Exception:
            logger.warning(
                "Learning capture failed for comment %s — review unaffected",
                comment_id,
                exc_info=True,
            )

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
    current_user: User = Depends(require_superuser),
):
    """List post drafts for review."""
    query = db.query(PostDraft).filter(PostDraft.status == status)
    if client_id:
        query = query.filter(PostDraft.client_id == client_id)
    query = query.order_by(PostDraft.created_at.desc())
    return query.limit(50).all()


@router.patch("/posts/{post_id}")
def update_post(
    post_id: UUID,
    data: UpdatePostRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Approve, reject, or edit a post draft."""
    post = db.query(PostDraft).filter(PostDraft.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # Validate status against whitelist
    try:
        data.validate_status()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

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

    # Audit log for post review action
    action_taken = data.status or "edit"
    try:
        audit_service.log_action(
            db=db,
            user_id=current_user.id,
            action=action_taken,
            entity_type="post_draft",
            entity_id=post.id,
            client_id=post.client_id,
            details={
                "edited_title": data.edited_title is not None,
                "edited_body": data.edited_body is not None,
            },
        )
    except Exception:
        logger.warning("Failed to audit log post %s", post_id, exc_info=True)

    return post
