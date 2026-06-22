"""Admin routes for execution task management.

Provides: task list, detail, resend, verify, cancel, SLA metrics.
All routes require superuser/admin access.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Form, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_superuser
from app.logging_config import get_logger
from app.models.execution_task import ExecutionTask, DeliveryAttempt
from app.models.user import User

logger = get_logger(__name__)
router = APIRouter(prefix="/admin/tasks", tags=["admin-tasks"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def list_tasks(
    request: Request,
    status: str | None = None,
    client_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """List all execution tasks with optional filters."""
    query = db.query(ExecutionTask).order_by(desc(ExecutionTask.created_at))

    if status:
        query = query.filter(ExecutionTask.status == status)
    if client_id:
        try:
            query = query.filter(ExecutionTask.client_id == uuid.UUID(client_id))
        except ValueError:
            pass

    tasks = query.limit(100).all()

    # Status counts for filter badges
    all_tasks = db.query(ExecutionTask).count()
    active_count = db.query(ExecutionTask).filter(
        ExecutionTask.status.in_(("generated", "emailed", "accepted", "submitted", "url_verified"))
    ).count()
    verified_count = db.query(ExecutionTask).filter(ExecutionTask.status == "verified").count()
    expired_count = db.query(ExecutionTask).filter(ExecutionTask.status == "expired").count()

    return templates.TemplateResponse("admin_tasks.html", {
        "request": request,
        "tasks": tasks,
        "current_status": status,
        "all_count": all_tasks,
        "active_count": active_count,
        "verified_count": verified_count,
        "expired_count": expired_count,
        "current_user": current_user,
    })


@router.get("/{task_id}", response_class=HTMLResponse)
def task_detail(
    request: Request,
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """View execution task detail with delivery log."""
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid task ID")

    task = db.query(ExecutionTask).filter(ExecutionTask.id == task_uuid).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    attempts = (
        db.query(DeliveryAttempt)
        .filter(DeliveryAttempt.task_id == task.id)
        .order_by(DeliveryAttempt.attempt_number)
        .all()
    )

    return templates.TemplateResponse("admin_task_detail.html", {
        "request": request,
        "task": task,
        "attempts": attempts,
        "current_user": current_user,
    })


@router.post("/{task_id}/resend", response_class=HTMLResponse)
def resend_task(
    request: Request,
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Resend delivery email for a task (respects anti-spam limits)."""
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid task ID")

    from app.services.execution_tasks import dispatch_delivery, can_resend

    task = db.query(ExecutionTask).filter(ExecutionTask.id == task_uuid).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Check anti-spam
    allowed, reason = can_resend(db, task)
    if not allowed:
        raise HTTPException(status_code=429, detail=reason)

    # Dispatch with force=True (admin override)
    result = dispatch_delivery(db, task_uuid, force=True)
    if result and result.status == "sent":
        return HTMLResponse(
            content='<div class="text-green-600 text-sm font-medium">✓ Email resent successfully</div>',
            status_code=200,
        )
    else:
        error_msg = result.error if result else "Unknown error"
        return HTMLResponse(
            content=f'<div class="text-red-600 text-sm font-medium">✗ Failed: {error_msg}</div>',
            status_code=200,
        )


@router.post("/{task_id}/verify", response_class=HTMLResponse)
def verify_task(
    request: Request,
    task_id: str,
    reddit_url: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Admin submits Reddit URL for verification."""
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid task ID")

    reddit_url = reddit_url.strip()
    if not reddit_url:
        raise HTTPException(status_code=422, detail="Reddit URL is required")

    if "reddit.com" not in reddit_url.lower() and "redd.it" not in reddit_url.lower():
        raise HTTPException(status_code=422, detail="Must be a Reddit URL")

    from app.services.task_verification import verify_full
    result = verify_full(db, task_uuid, reddit_url)

    if result.passed:
        return HTMLResponse(
            content=f'<div class="text-green-600 text-sm font-medium">✓ Verified (match: {(result.match_score or 0):.0%})</div>',
            status_code=200,
        )
    else:
        return HTMLResponse(
            content=f'<div class="text-red-600 text-sm font-medium">✗ {result.failure_reason}</div>',
            status_code=200,
        )


@router.post("/{task_id}/cancel", response_class=HTMLResponse)
def cancel_task_route(
    request: Request,
    task_id: str,
    reason: str = Form(default="Cancelled by admin"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Admin cancels a task with reason."""
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid task ID")

    from app.services.execution_tasks import cancel_task

    task = cancel_task(db, task_uuid, reason)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return HTMLResponse(
        content='<div class="text-gray-500 text-sm font-medium">Task cancelled</div>',
        status_code=200,
    )


@router.get("/metrics", response_class=HTMLResponse)
def task_metrics(
    request: Request,
    period: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """SLA metrics dashboard."""
    from app.services.execution_tasks import get_sla_metrics
    metrics = get_sla_metrics(db, period_days=period)

    return templates.TemplateResponse("admin_task_metrics.html", {
        "request": request,
        "metrics": metrics,
        "period": period,
        "current_user": current_user,
    })
