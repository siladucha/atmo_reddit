"""Public executor task routes — token-protected, no login required.

These routes allow executors to view, accept, and submit task results
using only the unique executor_token (UUID4) included in their email.

Security:
- Token is UUID4 (122 bits entropy, not guessable)
- Rate limited: handled by global middleware
- Expired/cancelled tasks return appropriate error
- No access to system data beyond the specific task
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.logging_config import get_logger
from app.models.execution_task import ExecutionTask

logger = get_logger(__name__)
router = APIRouter(prefix="/tasks", tags=["executor-tasks"])
templates = Jinja2Templates(directory="app/templates")


def _get_task_by_token(db: Session, task_code: str, token: str) -> ExecutionTask:
    """Resolve task by code + token. Raises appropriate HTTP errors."""
    try:
        token_uuid = uuid.UUID(token)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Not found")

    task = (
        db.query(ExecutionTask)
        .filter(
            ExecutionTask.task_code == task_code,
            ExecutionTask.executor_token == token_uuid,
        )
        .first()
    )

    if not task:
        raise HTTPException(status_code=404, detail="Not found")

    # Expired or cancelled → 410 Gone
    if task.status in ("expired", "cancelled"):
        raise HTTPException(
            status_code=410,
            detail=f"This task is no longer active (status: {task.status})",
        )

    return task


@router.get("/{task_code}/{token}", response_class=HTMLResponse)
def view_task(
    request: Request,
    task_code: str,
    token: str,
    db: Session = Depends(get_db),
):
    """View execution task details (no login required)."""
    task = _get_task_by_token(db, task_code, token)

    return templates.TemplateResponse(request, "executor_task_view.html", context={
        "request": request,
        "task": task,
        "token": token,
        "now": datetime.now(timezone.utc),
    })


@router.post("/{task_code}/{token}/accept", response_class=HTMLResponse)
def accept_task_route(
    request: Request,
    task_code: str,
    token: str,
    db: Session = Depends(get_db),
):
    """Executor accepts the task."""
    task = _get_task_by_token(db, task_code, token)

    if task.status == "verified":
        return templates.TemplateResponse(request, "executor_task_view.html", context={
            "request": request,
            "task": task,
            "token": token,
            "now": datetime.now(timezone.utc),
            "message": "This task is already completed.",
            "message_type": "info",
        })

    if task.status not in ("emailed", "accepted"):
        return templates.TemplateResponse(request, "executor_task_view.html", context={
            "request": request,
            "task": task,
            "token": token,
            "now": datetime.now(timezone.utc),
            "message": f"Cannot accept task in state: {task.status}",
            "message_type": "error",
        })

    # Transition to accepted (idempotent if already accepted)
    if task.status == "emailed":
        now = datetime.now(timezone.utc)
        task.status = "accepted"
        task.status_changed_at = now
        history = task.status_history or []
        history.append({"status": "accepted", "at": now.isoformat(), "by": "executor"})
        task.status_history = history
        db.commit()

    return templates.TemplateResponse(request, "executor_task_view.html", context={
        "request": request,
        "task": task,
        "token": token,
        "now": datetime.now(timezone.utc),
        "message": "Task accepted! Post the comment and submit the URL below.",
        "message_type": "success",
    })


@router.post("/{task_code}/{token}/submit", response_class=HTMLResponse)
def submit_url_route(
    request: Request,
    task_code: str,
    token: str,
    reddit_url: str = Form(...),
    db: Session = Depends(get_db),
):
    """Executor submits Reddit permalink for verification."""
    task = _get_task_by_token(db, task_code, token)

    # Validate URL format
    reddit_url = reddit_url.strip()
    if not reddit_url:
        return templates.TemplateResponse(request, "executor_task_view.html", context={
            "request": request,
            "task": task,
            "token": token,
            "now": datetime.now(timezone.utc),
            "message": "Please provide a Reddit URL.",
            "message_type": "error",
        })

    if "reddit.com" not in reddit_url.lower() and "redd.it" not in reddit_url.lower():
        return templates.TemplateResponse(request, "executor_task_view.html", context={
            "request": request,
            "task": task,
            "token": token,
            "now": datetime.now(timezone.utc),
            "message": "URL must be a Reddit permalink (reddit.com/r/...).",
            "message_type": "error",
        })

    if task.status in ("verified",):
        return templates.TemplateResponse(request, "executor_task_view.html", context={
            "request": request,
            "task": task,
            "token": token,
            "now": datetime.now(timezone.utc),
            "message": "This task is already verified.",
            "message_type": "info",
        })

    if task.status in ("expired", "cancelled"):
        raise HTTPException(status_code=410, detail="Task is no longer active")

    # Auto-accept if still in emailed state
    if task.status == "emailed":
        now = datetime.now(timezone.utc)
        task.status = "accepted"
        task.status_changed_at = now
        history = task.status_history or []
        history.append({"status": "accepted", "at": now.isoformat(), "by": "executor"})
        task.status_history = history
        db.flush()

    # Run verification
    from app.services.task_verification import verify_full
    result = verify_full(db, task.id, reddit_url)

    if result.passed:
        # Reload task after verification updated it
        db.refresh(task)
        return templates.TemplateResponse(request, "executor_task_view.html", context={
            "request": request,
            "task": task,
            "token": token,
            "now": datetime.now(timezone.utc),
            "message": f"Verified! Comment confirmed on Reddit (match: {(result.match_score or 0):.0%}).",
            "message_type": "success",
        })
    else:
        db.refresh(task)
        return templates.TemplateResponse(request, "executor_task_view.html", context={
            "request": request,
            "task": task,
            "token": token,
            "now": datetime.now(timezone.utc),
            "message": f"Verification failed: {result.failure_reason}",
            "message_type": "error",
        })
