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
from app.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.logging_config import get_logger
from app.models.execution_task import ExecutionTask

logger = get_logger(__name__)
router = APIRouter(prefix="/tasks", tags=["executor-tasks"])
templates = Jinja2Templates(directory="app/templates")

from app.version import __version__ as app_version
from app.config import get_settings as _get_settings
templates.env.globals["app_version"] = app_version
templates.env.globals["posting_disabled"] = lambda: _get_settings().posting_disabled
templates.env.globals["app_env"] = _get_settings().app_env


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


def _auto_cancel_if_thread_dead(db: Session, task: ExecutionTask) -> str | None:
    """Check if task's thread is locked/removed/archived. If so, auto-cancel and return message.

    Returns user-friendly message if cancelled, None if thread is fine.
    Zero friction: executor sees one message and moves on.
    """
    if task.status in ("verified", "cancelled", "expired"):
        return None  # Already terminal

    if not task.thread_id:
        return None  # Hobby task, no thread to check

    from app.models.thread import RedditThread
    thread = db.query(RedditThread).filter(RedditThread.id == task.thread_id).first()
    if not thread:
        return None

    # Quick check: already known locked
    if thread.is_locked:
        _cancel_task_thread_dead(db, task, "thread_locked")
        return "This thread was locked by moderators. Task cancelled automatically — no action needed."

    # Live check via Reddit API (only if thread is stale)
    from app.services.thread_liveness import is_thread_stale, refresh_thread_locked_status
    if is_thread_stale(thread):
        try:
            is_open = refresh_thread_locked_status(db, thread)
            if not is_open:
                _cancel_task_thread_dead(db, task, "thread_locked_on_view")
                return "This thread was locked by moderators. Task cancelled automatically — no action needed."
        except Exception as e:
            logger.warning("Liveness check failed for task %s: %s", task.task_code, str(e)[:100])
            # Don't block executor on API failure — let them proceed
            return None

    return None


def _cancel_task_thread_dead(db: Session, task: ExecutionTask, reason: str):
    """Cancel task because thread is dead. Minimal side effects."""
    now = datetime.now(timezone.utc)
    task.status = "cancelled"
    task.status_changed_at = now
    task.cancelled_at = now
    task.cancel_reason = f"auto: {reason}"
    history = task.status_history or []
    history.append({"status": "cancelled", "at": now.isoformat(), "by": "system", "reason": reason})
    task.status_history = history
    db.commit()
    logger.info("Auto-cancelled task %s: %s", task.task_code, reason)


@router.get("/{task_code}/{token}", response_class=HTMLResponse)
def view_task(
    request: Request,
    task_code: str,
    token: str,
    db: Session = Depends(get_db),
):
    """View execution task details (no login required)."""
    task = _get_task_by_token(db, task_code, token)

    # Auto-cancel if thread is locked (executor sees clean message, zero friction)
    cancelled_msg = _auto_cancel_if_thread_dead(db, task)
    if cancelled_msg:
        return templates.TemplateResponse(request, "executor_task_view.html", context={
            "request": request,
            "task": task,
            "token": token,
            "now": datetime.now(timezone.utc),
            "message": cancelled_msg,
            "message_type": "info",
        })

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

    # Auto-cancel if thread is locked (executor sees clean message, zero friction)
    cancelled_msg = _auto_cancel_if_thread_dead(db, task)
    if cancelled_msg:
        return templates.TemplateResponse(request, "executor_task_view.html", context={
            "request": request,
            "task": task,
            "token": token,
            "now": datetime.now(timezone.utc),
            "message": cancelled_msg,
            "message_type": "info",
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



@router.post("/{task_code}/{token}/report-blocked", response_class=HTMLResponse)
def report_blocked_route(
    request: Request,
    task_code: str,
    token: str,
    reason: str = Form("thread_locked"),
    db: Session = Depends(get_db),
):
    """Executor reports that posting is not possible (thread locked/removed/etc).

    Transitions task to cancelled with the reported reason.
    This allows executors to resolve stuck tasks without admin intervention.
    """
    task = _get_task_by_token(db, task_code, token)

    if task.status in ("verified", "cancelled", "expired"):
        return templates.TemplateResponse(request, "executor_task_view.html", context={
            "request": request,
            "task": task,
            "token": token,
            "now": datetime.now(timezone.utc),
            "message": f"Task already in terminal state: {task.status}",
            "message_type": "info",
        })

    # Validate reason
    allowed_reasons = ("thread_locked", "thread_removed", "thread_archived", "account_issue", "other")
    if reason not in allowed_reasons:
        reason = "other"

    # Cancel the task
    now = datetime.now(timezone.utc)
    task.status = "cancelled"
    task.status_changed_at = now
    task.cancelled_at = now
    task.cancel_reason = f"executor_report: {reason}"
    history = task.status_history or []
    history.append({"status": "cancelled", "at": now.isoformat(), "by": "executor", "reason": reason})
    task.status_history = history
    db.commit()

    logger.info(
        "Executor reported task %s as blocked: %s (avatar=%s)",
        task.task_code, reason, task.avatar_username,
    )

    return templates.TemplateResponse(request, "executor_task_view.html", context={
        "request": request,
        "task": task,
        "token": token,
        "now": datetime.now(timezone.utc),
        "message": "Task marked as blocked. No further action needed.",
        "message_type": "info",
    })
