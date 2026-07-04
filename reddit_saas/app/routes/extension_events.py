"""Extension Event Stream — ingests execution events from browser extension.

Events are the raw observation stream from the execution runtime.
Backend reconciles events with EPG intent to derive truth.

Extension emits events at every state transition:
  task_started, precheck_passed, navigation_completed, context_verified,
  action_started, action_completed, proof_collected, task_completed, task_failed

Backend stores these as-is and uses them for:
  - Task lifecycle reconciliation (did execution match intent?)
  - Retry decisions (which failure type → which recovery action?)
  - Observability (admin sees full execution trace)
  - Audit trail (what happened, when, in what order)
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.logging_config import get_logger
from app.models.activity_event import ActivityEvent
from app.models.execution_task import ExecutionTask

logger = get_logger(__name__)
router = APIRouter(prefix="/api/extension", tags=["extension-events"])


class ExecutionEvent(BaseModel):
    task_id: str
    event: str
    timestamp: str
    # All other fields are passed through as metadata
    failure_reason: Optional[str] = None
    details: Optional[str] = None
    permalink: Optional[str] = None
    posted_at: Optional[str] = None
    comment_id: Optional[str] = None
    variant: Optional[str] = None
    confidence: Optional[float] = None
    url: Optional[str] = None
    task_type: Optional[str] = None
    thread_url: Optional[str] = None
    status: Optional[str] = None
    action: Optional[str] = None


class EventBatchRequest(BaseModel):
    events: list[ExecutionEvent]


@router.post("/events")
async def ingest_events(
    body: EventBatchRequest,
    db: Session = Depends(get_db),
):
    """Ingest a batch of execution events from the extension.

    Events are stored as ActivityEvents for observability and used
    to reconcile task state with EPG intent.

    Public endpoint (extension sends with its JWT, but we don't enforce
    strict auth here — events are untrusted observations anyway).
    """
    if not body.events:
        return {"accepted": 0}

    accepted = 0
    for ev in body.events:
        try:
            # Resolve task to get client_id for event scoping
            client_id = None
            task_id = None
            try:
                task_id = uuid.UUID(ev.task_id)
                task = db.query(ExecutionTask).filter(ExecutionTask.id == task_id).first()
                if task:
                    client_id = task.client_id
            except (ValueError, TypeError):
                pass

            # Store as activity event
            activity = ActivityEvent(
                id=uuid.uuid4(),
                client_id=client_id,
                event_type=f"ext_{ev.event}",
                message=f"Extension: {ev.event} for task {ev.task_id[:8]}",
                event_metadata={
                    "task_id": ev.task_id,
                    "event": ev.event,
                    "timestamp": ev.timestamp,
                    "failure_reason": ev.failure_reason,
                    "details": ev.details,
                    "permalink": ev.permalink,
                    "posted_at": ev.posted_at,
                    "comment_id": ev.comment_id,
                    "variant": ev.variant,
                    "confidence": ev.confidence,
                    "url": ev.url,
                    "task_type": ev.task_type,
                    "thread_url": ev.thread_url,
                    "status": ev.status,
                    "action": ev.action,
                },
            )
            db.add(activity)

            # ── Reconciliation: update task state based on terminal events ──

            if task and ev.event == "task_completed":
                task.task_lifecycle_status = "FINALIZED"
                if ev.permalink:
                    task.submitted_url = ev.permalink
                    task.status = "verified"
                    task.verified_at = datetime.now(timezone.utc)
                    # Also update the linked draft
                    if task.draft_id:
                        from app.models.comment_draft import CommentDraft
                        draft = db.query(CommentDraft).filter(CommentDraft.id == task.draft_id).first()
                        if draft:
                            draft.status = "posted"
                            draft.posted_at = datetime.now(timezone.utc)
                            draft.reddit_comment_url = ev.permalink
                    # Update EPG slot
                    if task.epg_slot_id:
                        from app.models.epg_slot import EPGSlot
                        slot = db.query(EPGSlot).filter(EPGSlot.id == task.epg_slot_id).first()
                        if slot:
                            slot.status = "posted"
                            slot.posted_at = datetime.now(timezone.utc)

            elif task and ev.event == "task_failed":
                task.task_lifecycle_status = "FAILED"
                task.failure_reason = ev.failure_reason or ev.details

            accepted += 1
        except Exception as e:
            logger.warning("Event ingestion error: %s", str(e)[:200])
            continue

    db.commit()

    logger.info("EXTENSION_EVENTS | accepted=%d of %d", accepted, len(body.events))
    return {"accepted": accepted}


@router.get("/events/latest")
async def get_latest_events(
    avatar_username: str = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """Get latest extension execution events for debugging.

    Returns recent activity events with type ext_* (extension events).
    Optionally filtered by avatar username.
    """
    query = (
        db.query(ActivityEvent)
        .filter(ActivityEvent.event_type.like("ext_%"))
        .order_by(ActivityEvent.created_at.desc())
        .limit(limit)
    )

    if avatar_username:
        query = query.filter(
            ActivityEvent.event_metadata["avatar_username"].astext == avatar_username
        )

    events = query.all()

    return {
        "count": len(events),
        "events": [
            {
                "id": str(e.id),
                "type": e.event_type,
                "message": e.message,
                "metadata": e.event_metadata,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }


@router.get("/tasks/status")
async def get_tasks_status(
    avatar_username: str = None,
    db: Session = Depends(get_db),
):
    """Quick status of recent extension tasks — for agent debugging.

    Shows last 10 tasks with lifecycle status, failure reasons, etc.
    """
    query = db.query(ExecutionTask).filter(
        ExecutionTask.delivery_channel == "extension",
    )
    if avatar_username:
        query = query.filter(ExecutionTask.avatar_username == avatar_username)

    tasks = query.order_by(ExecutionTask.created_at.desc()).limit(10).all()

    return {
        "count": len(tasks),
        "tasks": [
            {
                "task_code": t.task_code,
                "subreddit": t.subreddit,
                "lifecycle": t.task_lifecycle_status,
                "status": t.status,
                "failure_reason": t.failure_reason,
                "thread_url": (t.thread_url or "")[:60],
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "verification_result": t.verification_result,
            }
            for t in tasks
        ],
    }
