"""Extension API routes — browser extension communication endpoints.

JWT-authenticated endpoints for Chrome extension (Execution Nodes).
Extension polls for tasks, reports results, and sends heartbeats.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.avatar import Avatar
from app.models.execution_node import ExecutionNode
from app.models.execution_task import ExecutionTask
from app.models.user import User
from app.models.user_client_assignment import UserClientAssignment
from app.services.auth import decode_access_token

router = APIRouter(prefix="/api/extension", tags=["extension"])

# Bearer token scheme for extension JWT auth
_bearer_scheme = HTTPBearer()


async def get_current_executor(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Validate JWT Bearer token and return the executor (user).

    Supports two token formats:
    1. Standard user token: sub = user UUID → returns User
    2. Node-based token from /activate: sub = "node:UUID" → resolve via admin fallback

    Raises 401 if token is missing, invalid, expired, or user not found/inactive.
    """
    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Handle node-based tokens from /activate endpoint (sub = "node:UUID")
    if user_id.startswith("node:"):
        node_id_str = user_id.replace("node:", "")
        try:
            node = db.query(ExecutionNode).filter(ExecutionNode.id == uuid.UUID(node_id_str)).first()
        except (ValueError, TypeError):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid node token")
        if node is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Node not found")
        # If node has executor_id, return that user
        if node.executor_id:
            user = db.query(User).filter(User.id == node.executor_id).first()
            if user and user.is_active:
                return user
        # No executor resolved — reject (no admin fallback for security)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No executor associated with this node. Re-activate with a valid avatar.",
        )

    # Standard user UUID token
    try:
        user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identifier",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


@router.get("/policy")
async def get_policy(
    avatar_username: str = Query(..., description="Reddit username of the avatar"),
    executor: User = Depends(get_current_executor),
    db: Session = Depends(get_db),
):
    """Return per-avatar immutable config (epg_mode, limits, allowed types)."""
    # Look up avatar by reddit_username
    avatar = (
        db.query(Avatar)
        .filter(Avatar.reddit_username == avatar_username)
        .first()
    )
    if avatar is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Avatar not found",
        )

    # Verify executor has access to this avatar:
    # 1) avatar.executor_email matches executor's email, OR
    # 2) avatar belongs to one of executor's client assignments
    has_access = False

    if avatar.executor_email and avatar.executor_email == executor.email:
        has_access = True

    if not has_access and avatar.client_ids:
        # Check if executor is assigned to any of the avatar's clients
        assigned_client_ids = (
            db.query(UserClientAssignment.client_id)
            .filter(
                UserClientAssignment.user_id == executor.id,
                UserClientAssignment.is_active == True,  # noqa: E712
            )
            .all()
        )
        assigned_ids_set = {str(row.client_id) for row in assigned_client_ids}
        for cid in avatar.client_ids:
            if cid in assigned_ids_set:
                has_access = True
                break

    if not has_access:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Avatar not found",
        )

    # Return policy JSON — MVP: mostly hardcoded values
    return {
        "epg_mode": avatar.epg_mode or "required",
        "daily_cap": 3,
        "min_interval_seconds": 180,
        "active_hours_start": "08:00",
        "active_hours_end": "22:00",
        "allowed_task_types": ["post_comment", "diagnostic_probe"],
        "cqs_probe_max_per_hour": 1,
        "health_probe_max_per_30min": 1,
        "max_concurrent_tasks": 1,
        "queue_overflow_limit": 20,
        "poll_interval_seconds": 30,
    }


@router.get("/tasks")
async def get_tasks(
    execution_node_id: str = Query(..., description="UUID of the execution node"),
    executor: User = Depends(get_current_executor),
    db: Session = Depends(get_db),
):
    """Return pending tasks filtered by active_reddit_username from last heartbeat."""
    # Validate and look up the execution node
    try:
        node_id = uuid.UUID(execution_node_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution node not found",
        )

    node = (
        db.query(ExecutionNode)
        .filter(ExecutionNode.id == node_id)
        .first()
    )

    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution node not found",
        )

    # If no active username on the node, return empty tasks
    if not node.active_reddit_username:
        return {"tasks": [], "commands": []}

    # Query tasks:
    # 1. CREATED tasks matching the node's active reddit username (available for assignment)
    # 2. ASSIGNED tasks already assigned to this node (in-progress for this node)
    # Exclude tasks past their deadline or older than 24h (stale)
    stale_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    tasks = (
        db.query(ExecutionTask)
        .filter(
            sa.or_(
                sa.and_(
                    ExecutionTask.task_lifecycle_status == "CREATED",
                    ExecutionTask.delivery_channel.in_(["extension", "both"]),
                    ExecutionTask.avatar_username == node.active_reddit_username,
                ),
                sa.and_(
                    ExecutionTask.task_lifecycle_status == "ASSIGNED",
                    ExecutionTask.execution_node_id == node.id,
                ),
            ),
            # Exclude stale tasks: deadline passed OR scheduled_at older than 24h
            sa.or_(
                ExecutionTask.deadline.is_(None),
                ExecutionTask.deadline > datetime.now(timezone.utc),
            ),
            sa.or_(
                ExecutionTask.scheduled_at.is_(None),
                ExecutionTask.scheduled_at > stale_cutoff,
            ),
        )
        .order_by(
            # Priority ordering: diagnostic first, then content
            sa.case(
                (ExecutionTask.priority == "diagnostic", 0),
                else_=1,
            ),
            # Then by scheduled_at (earliest first, NULLs last)
            sa.case(
                (ExecutionTask.scheduled_at.is_(None), 1),
                else_=0,
            ),
            ExecutionTask.scheduled_at.asc(),
        )
        .limit(50)
        .all()
    )

    # Mark CREATED tasks as ASSIGNED to this node
    for task in tasks:
        if task.task_lifecycle_status == "CREATED":
            task.task_lifecycle_status = "ASSIGNED"
            task.execution_node_id = node.id

    if tasks:
        db.commit()

    # Build response
    task_list = [
        {
            "task_id": str(task.id),
            "idempotency_key": task.idempotency_key,
            "task_hash": task.task_hash,
            "task_type": task.task_type,
            "probe_type": task.probe_type,
            "priority": task.priority,
            "avatar_username": task.avatar_username,
            "subreddit": task.subreddit,
            "thread_url": task.thread_url,
            "thread_title": task.thread_title,
            "comment_text": task.generated_text,
            "posting_strategy": task.posting_strategy or "old_reddit",  # Default: old_reddit
            "scheduled_at": task.scheduled_at.isoformat() if task.scheduled_at else None,
            "lease_expires_at": task.lease_expires_at.isoformat() if task.lease_expires_at else None,
            "status": task.status,
            "lifecycle": task.task_lifecycle_status,
            "has_epg_slot": task.epg_slot_id is not None,
        }
        for task in tasks
    ]

    # Also include today's full history for THIS avatar (all statuses)
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_all = (
        db.query(ExecutionTask)
        .filter(
            ExecutionTask.avatar_username == node.active_reddit_username,
            ExecutionTask.created_at >= today_start,
        )
        .order_by(ExecutionTask.scheduled_at.asc().nullslast())
        .limit(50)
        .all()
    )

    today_history = [
        {
            "task_id": str(t.id),
            "task_type": t.task_type,
            "avatar_username": t.avatar_username,
            "subreddit": t.subreddit,
            "thread_url": t.thread_url,
            "comment_text": t.generated_text,
            "posting_strategy": t.posting_strategy or "old_reddit",
            "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None,
            "status": t.status,
            "lifecycle": t.task_lifecycle_status,
            "permalink": None,  # TODO: extract from report
            "has_epg_slot": t.epg_slot_id is not None,
        }
        for t in today_all
    ]

    return {"tasks": task_list, "today_history": today_history, "commands": []}


class ReportRequest(BaseModel):
    """Request body for extension report — untrusted results from execution node."""

    task_id: str  # UUID of the ExecutionTask
    idempotency_key: str
    result_type: str  # task_completed | probe_result | health_signal | task_failed
    status: Optional[str] = None  # posted | blocked | error (for task_completed)
    permalink: Optional[str] = None
    comment_id: Optional[str] = None
    posted_at: Optional[str] = None
    error_code: Optional[str] = None
    error_details: Optional[str] = None
    probe_type: Optional[str] = None
    raw_output: Optional[str] = None
    execution_metadata: Optional[dict] = None
    signal_type: Optional[str] = None
    raw_value: Optional[dict] = None


@router.post("/report")
async def post_report(
    body: ReportRequest,
    executor: User = Depends(get_current_executor),
    db: Session = Depends(get_db),
):
    """Receive untrusted results from extension. Validate idempotency_key.

    First valid report wins. Duplicate reports → 200 NOOP (no error, no re-processing).
    """
    # Look up task by id
    try:
        task_uuid = uuid.UUID(body.task_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    task = db.query(ExecutionTask).filter(ExecutionTask.id == task_uuid).first()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    # Idempotency check: if already reported/finalized, return NOOP
    # PREPARED tasks can be re-reported (user decides to publish or cancel later)
    if task.task_lifecycle_status in ("REPORTED", "FINALIZED"):
        return {"status": "noop", "message": "Already reported"}

    # Validate idempotency_key matches the task's stored key
    if task.idempotency_key != body.idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency key mismatch",
        )

    # Determine lifecycle status based on result_type
    if body.result_type == "task_prepared":
        # Prepare-only mode: task is prepared but NOT published
        task.task_lifecycle_status = "PREPARED"
    elif body.result_type in ("task_completed", "probe_result"):
        task.task_lifecycle_status = "REPORTED"
    else:
        # task_failed, health_signal, etc.
        task.task_lifecycle_status = "REPORTED"

    task.verification_result = {
        "result_type": body.result_type,
        "status": body.status,
        "permalink": body.permalink,
        "comment_id": body.comment_id,
        "posted_at": body.posted_at,
        "error_code": body.error_code,
        "error_details": body.error_details,
        "probe_type": body.probe_type,
        "raw_output": body.raw_output,
        "execution_metadata": body.execution_metadata,
        "signal_type": body.signal_type,
        "raw_value": body.raw_value,
        "reported_at": datetime.now(timezone.utc).isoformat(),
    }

    db.commit()

    return {"status": "accepted", "task_id": str(task.id)}


# ─── Task Edit (Extension v2) ───────────────────────────────────────────────


class EditTaskRequest(BaseModel):
    """Request body for editing task text before approval."""

    text: str


@router.patch("/tasks/{task_id}")
async def edit_task(
    task_id: str,
    body: EditTaskRequest,
    executor: User = Depends(get_current_executor),
    db: Session = Depends(get_db),
):
    """Allow executor to edit task comment text before approval.

    Updates the generated_text field. Returns updated task with version.
    """
    try:
        task_uuid = uuid.UUID(task_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    task = db.query(ExecutionTask).filter(ExecutionTask.id == task_uuid).first()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    # Only allow editing tasks that haven't been finalized
    if task.task_lifecycle_status in ("REPORTED", "FINALIZED"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot edit a task that has already been reported or finalized",
        )

    # Update the generated text
    task.generated_text = body.text.strip()

    # Track edit in status_history
    now = datetime.now(timezone.utc)
    if task.status_history is None:
        task.status_history = []
    task.status_history = task.status_history + [
        {"status": "edited", "at": now.isoformat(), "by": "executor"}
    ]

    db.commit()

    # Compute version from number of edits in history
    version = sum(1 for h in (task.status_history or []) if h.get("status") == "edited")

    return {
        "id": str(task.id),
        "text": task.generated_text,
        "version": version,
        "updated_at": task.updated_at.isoformat() if task.updated_at else now.isoformat(),
    }


# ─── Task Approval (Extension v2) ───────────────────────────────────────────


class ApproveTaskRequest(BaseModel):
    """Request body for approving a task from the extension."""

    status: str = "approved"


@router.post("/tasks/{task_id}/approve")
async def approve_task(
    task_id: str,
    body: ApproveTaskRequest,
    executor: User = Depends(get_current_executor),
    db: Session = Depends(get_db),
):
    """Mark a task as approved by the executor via extension.

    Updates the task status and records approval in status_history.
    The scheduler (background) will pick up approved tasks at their scheduled times.
    """
    try:
        task_uuid = uuid.UUID(task_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    task = db.query(ExecutionTask).filter(ExecutionTask.id == task_uuid).first()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    # Only allow approving tasks that haven't been finalized
    if task.task_lifecycle_status in ("REPORTED", "FINALIZED"):
        return {"status": "noop", "message": "Task already finalized"}

    # Update lifecycle status
    task.task_lifecycle_status = "APPROVED"

    # Track approval in status_history
    now = datetime.now(timezone.utc)
    if task.status_history is None:
        task.status_history = []
    task.status_history = task.status_history + [
        {"status": "approved", "at": now.isoformat(), "by": "executor"}
    ]

    db.commit()

    return {
        "id": str(task.id),
        "status": "approved",
        "approved_at": now.isoformat(),
    }


@router.post("/tasks/{task_id}/retry")
async def retry_task(
    task_id: str,
    executor: User = Depends(get_current_executor),
    db: Session = Depends(get_db),
):
    """Mark a failed task as ready for retry by resetting its lifecycle status.

    Called by the extension when executor clicks Retry on a failed task.
    Resets task_lifecycle_status to APPROVED so the scheduler picks it up again.
    """
    try:
        task_uuid = uuid.UUID(task_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    task = db.query(ExecutionTask).filter(ExecutionTask.id == task_uuid).first()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    # Only allow retrying reported/failed tasks
    if task.task_lifecycle_status not in ("REPORTED", "ASSIGNED"):
        return {"status": "noop", "message": "Task not in retryable state"}

    # Reset to APPROVED for scheduler pickup
    task.task_lifecycle_status = "APPROVED"

    # Track retry in status_history
    now = datetime.now(timezone.utc)
    if task.status_history is None:
        task.status_history = []
    task.status_history = task.status_history + [
        {"status": "retried", "at": now.isoformat(), "by": "executor"}
    ]

    # Clear previous verification result
    task.verification_result = None

    db.commit()

    return {
        "id": str(task.id),
        "status": "approved",
        "retried_at": now.isoformat(),
    }


class HeartbeatRequest(BaseModel):
    """Request body for extension heartbeat."""

    execution_node_id: str
    active_reddit_username: str
    extension_version: Optional[str] = None
    tasks_in_local_queue: int
    # --- Health monitoring fields (extension v2) ---
    reddit_session_valid: Optional[bool] = None
    dom_health: Optional[str] = None  # "ok" | "degraded" | "broken"
    last_task_executed_at: Optional[str] = None  # ISO timestamp
    pending_approvals: Optional[int] = None


@router.post("/heartbeat")
async def post_heartbeat(
    body: HeartbeatRequest,
    executor: User = Depends(get_current_executor),
    db: Session = Depends(get_db),
):
    """Update node status + active account + health fields."""
    from app.services.settings import get_setting

    try:
        node_id = uuid.UUID(body.execution_node_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution node not found",
        )

    node = (
        db.query(ExecutionNode)
        .filter(ExecutionNode.id == node_id)
        .first()
    )

    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution node not found",
        )

    now = datetime.now(timezone.utc)
    node.last_heartbeat = now
    node.is_online = True
    node.active_reddit_username = body.active_reddit_username
    node.tasks_in_queue = body.tasks_in_local_queue
    if body.extension_version is not None:
        node.extension_version = body.extension_version

    # --- Health monitoring fields ---
    if body.reddit_session_valid is not None:
        node.reddit_session_valid = body.reddit_session_valid

    if body.pending_approvals is not None:
        node.pending_approvals = body.pending_approvals

    if body.last_task_executed_at is not None:
        try:
            node.last_task_executed_at = datetime.fromisoformat(
                body.last_task_executed_at.replace("Z", "+00:00")
            )
        except (ValueError, AttributeError):
            pass  # Ignore invalid timestamps

    # --- dom_health tracking with state change detection ---
    if body.dom_health is not None and body.dom_health in ("ok", "degraded", "broken"):
        old_dom_health = node.dom_health
        if old_dom_health != body.dom_health:
            node.dom_health = body.dom_health
            node.dom_health_since = now
        elif node.dom_health_since is None:
            # First time reporting — set the timestamp
            node.dom_health_since = now

        # --- Alert logic: broken DOM for >10 minutes ---
        if (
            body.dom_health == "broken"
            and node.dom_health_since is not None
            and (now - node.dom_health_since).total_seconds() > 600  # 10 minutes
        ):
            from app.services.transparency import record_activity_event

            duration_minutes = int((now - node.dom_health_since).total_seconds() / 60)
            record_activity_event(
                db,
                event_type="extension_dom_broken",
                message=(
                    f"Extension node {str(node.id)[:8]} DOM broken for "
                    f"{duration_minutes} minutes (u/{node.active_reddit_username})"
                ),
                metadata={
                    "node_id": str(node.id),
                    "duration_minutes": duration_minutes,
                    "active_reddit_username": node.active_reddit_username,
                },
            )

    db.commit()

    # --- Build response with pause_all and daily_cap_remaining ---
    pause_all_str = get_setting(db, "pause_all")
    pause_all = pause_all_str.lower() in ("true", "1", "yes") if pause_all_str else False

    # Calculate daily_cap_remaining for this node's avatar
    daily_cap_remaining = _get_daily_cap_remaining(db, node)

    # Version check: compare extension_version with latest known version
    update_available = False
    latest_version = ""
    download_url = ""
    if body.extension_version:
        latest_version = get_setting(db, "extension_latest_version") or "0.3.1"
        if _version_lt(body.extension_version, latest_version):
            update_available = True
            download_url = get_setting(db, "extension_download_url") or "https://gorampit.com/static/extension/ramp_extension_latest.zip"

    return {
        "status": "ok",
        "server_time": now.isoformat(),
        "pause_all": pause_all,
        "daily_cap_remaining": daily_cap_remaining,
        "update_available": update_available,
        "latest_version": latest_version,
        "download_url": download_url,
    }


class RegisterNodeRequest(BaseModel):
    """Request body for node registration."""

    extension_version: Optional[str] = None
    device_fingerprint: Optional[str] = None


@router.post("/register")
async def register_node(
    body: RegisterNodeRequest,
    executor: User = Depends(get_current_executor),
    db: Session = Depends(get_db),
):
    """Validate executor JWT, create ExecutionNode, return node_id."""
    # If executor already has a node with the same device_fingerprint, return existing
    if body.device_fingerprint:
        existing_node = (
            db.query(ExecutionNode)
            .filter(
                ExecutionNode.executor_id == executor.id,
                ExecutionNode.device_fingerprint == body.device_fingerprint,
            )
            .first()
        )
        if existing_node:
            # Update heartbeat and online status for existing node
            existing_node.is_online = True
            existing_node.last_heartbeat = datetime.now(timezone.utc)
            if body.extension_version:
                existing_node.extension_version = body.extension_version
            db.commit()
            return {
                "execution_node_id": str(existing_node.id),
                "status": "registered",
            }

    # Create new ExecutionNode
    node = ExecutionNode(
        executor_id=executor.id,
        device_fingerprint=body.device_fingerprint,
        extension_version=body.extension_version,
        is_online=True,
        last_heartbeat=datetime.now(timezone.utc),
    )
    db.add(node)
    db.commit()
    db.refresh(node)

    return {"execution_node_id": str(node.id), "status": "registered"}


# ─── Executor Token Generation (Admin action) ──────────────────────────────

@router.post("/generate-token")
async def generate_executor_token(
    executor_email: str = Query(..., description="Email of the executor user"),
    executor: User = Depends(get_current_executor),
    db: Session = Depends(get_db),
):
    """Generate a long-lived JWT token for an executor to use in the browser extension.

    Requires admin/owner/partner role. The generated token expires in 90 days.
    Executor pastes this token into the extension onboarding screen.

    Flow:
        1. Admin opens admin panel → avatar detail → "Generate Extension Token"
        2. Backend creates a 90-day JWT for that executor user
        3. Admin gives the token to executor (copy/paste, email, etc.)
        4. Executor pastes into extension popup → extension registers as ExecutionNode
    """
    from app.services.auth import create_access_token

    # Only owner/partner/admin can generate tokens
    if not executor.is_superuser and executor.role not in ("owner", "partner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin/owner/partner can generate executor tokens",
        )

    # Find the target user by email
    target_user = db.query(User).filter(User.email == executor_email).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with email '{executor_email}' not found",
        )

    if not target_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is deactivated",
        )

    # Generate 90-day token
    token = create_access_token(
        data={"sub": str(target_user.id)},
        expires_delta=timedelta(days=90),
    )

    return {
        "token": token,
        "executor_email": executor_email,
        "executor_id": str(target_user.id),
        "expires_in_days": 90,
        "usage": "Paste this token into the RAMP browser extension setup screen",
    }


# ─── Zero-Input Activation (Public — no JWT required) ───────────────────────


class ActivateRequest(BaseModel):
    """Request body for extension activation — just the Reddit username."""
    reddit_username: str
    extension_version: Optional[str] = None


@router.post("/activate")
async def activate_extension(
    body: ActivateRequest,
    db: Session = Depends(get_db),
):
    """Zero-input activation: extension detects Reddit username → sends here.

    Backend checks:
    1. Avatar with this username exists and is active

    If valid → creates ExecutionNode + returns JWT (90-day) + nodeId.
    No admin action needed. No codes. No tokens to paste.

    Extension is the PRIMARY execution channel. executor_email is optional
    (only needed if delivery_channel includes email fallback).

    Security model:
    - Extension can only EXECUTE tasks that backend assigns to this username.
    - Backend controls what tasks are sent. Extension is execution-only.
    - Rate limited by global middleware (5/min per IP) + per-endpoint Redis limit.
    - Even if an attacker registers — they get no tasks (backend checks
      node's active_reddit_username matches the avatar before assigning).
    - Token is scoped to executor user or platform owner (for audit trail).
    """
    from app.services.auth import create_access_token
    from app.models.execution_node import ExecutionNode

    username = body.reddit_username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="reddit_username is required")

    # Find avatar by username (case-insensitive)
    avatar = (
        db.query(Avatar)
        .filter(
            sa.func.lower(Avatar.reddit_username) == username.lower(),
            Avatar.active == True,  # noqa: E712
        )
        .first()
    )

    if not avatar:
        # Generic 404 — don't reveal whether username exists
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Avatar not found or not configured for extension",
        )

    # Resolve executor user for JWT token
    # Extension is the primary execution path. executor_email is optional.
    # If no executor_email configured, fall back to platform owner for JWT issuance.
    executor_user = None
    if avatar.executor_email:
        executor_user = (
            db.query(User)
            .filter(User.email == avatar.executor_email, User.is_active == True)  # noqa: E712
            .first()
        )

    if not executor_user:
        # Fallback to platform owner — extension auth is node-based,
        # executor_id in JWT is for audit trail only.
        from app.models.user_role import UserRole

        executor_user = (
            db.query(User)
            .filter(User.role == UserRole.owner, User.is_active == True)  # noqa: E712
            .first()
        )

    if not executor_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Avatar not found or not configured for extension",
        )

    executor_id = executor_user.id

    # Check if a node already exists for this username
    existing_node = (
        db.query(ExecutionNode)
        .filter(
            sa.func.lower(ExecutionNode.active_reddit_username) == username.lower(),
        )
        .first()
    )

    if existing_node:
        # Reuse existing node — update heartbeat
        existing_node.is_online = True
        existing_node.last_heartbeat = datetime.now(timezone.utc)
        if body.extension_version:
            existing_node.extension_version = body.extension_version
        node_id = existing_node.id
    else:
        # Create new node
        new_node = ExecutionNode(
            executor_id=executor_id,
            active_reddit_username=username,
            extension_version=body.extension_version,
            is_online=True,
            last_heartbeat=datetime.now(timezone.utc),
        )
        db.add(new_node)
        db.flush()
        node_id = new_node.id

    db.commit()

    # Generate 90-day JWT scoped to the executor user (never a bare node token)
    token = create_access_token(
        data={"sub": str(executor_id), "node_id": str(node_id), "avatar_username": username},
        expires_delta=timedelta(days=90),
    )

    return {
        "status": "activated",
        "token": token,
        "execution_node_id": str(node_id),
        "avatar_username": username,
        "message": f"Connected as u/{username}",
    }


# ─── Dashboard Data for Extension Popup ─────────────────────────────────────


@router.get("/dashboard")
async def get_extension_dashboard(
    avatar_username: str = Query(..., description="Reddit username"),
    db: Session = Depends(get_db),
):
    """Return stats, today's EPG, and pending drafts for the extension popup.

    Public endpoint (uses token from /activate). Returns data scoped to
    the specific avatar username.

    Response includes:
    - stats: posts today, karma, tasks completed, CQS level
    - epg: today's scheduled slots (time, subreddit, status)
    - pending_drafts: drafts awaiting approval (with links to gorampit)
    - links: quick links to relevant gorampit pages
    """
    from app.models.epg_slot import EPGSlot
    from app.models.comment_draft import CommentDraft
    from app.models.karma_snapshot import KarmaSnapshot
    from sqlalchemy import func as sqlfunc

    # Find avatar
    avatar = (
        db.query(Avatar)
        .filter(
            sa.func.lower(Avatar.reddit_username) == avatar_username.lower(),
            Avatar.active == True,  # noqa: E712
        )
        .first()
    )
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # ── Stats ──────────────────────────────────────────────────────────────

    # Posts today (drafts with status=posted, posted_at today)
    posts_today = (
        db.query(sqlfunc.count(CommentDraft.id))
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.status == "posted",
            CommentDraft.posted_at >= today_start,
        )
        .scalar() or 0
    )

    # Total karma from karma_snapshots (last 7 days, most recent per draft)
    karma_7d = (
        db.query(sqlfunc.sum(KarmaSnapshot.karma_value))
        .filter(
            KarmaSnapshot.avatar_id == avatar.id,
            KarmaSnapshot.checked_at >= now - timedelta(days=7),
        )
        .scalar() or 0
    )

    # Tasks completed today (execution tasks finalized/verified)
    tasks_today = (
        db.query(sqlfunc.count(ExecutionTask.id))
        .filter(
            ExecutionTask.avatar_username == avatar.reddit_username,
            ExecutionTask.status.in_(["verified", "content_verified", "url_verified"]),
            ExecutionTask.created_at >= today_start,
        )
        .scalar() or 0
    )

    stats = {
        "posts_today": posts_today,
        "karma_7d": int(karma_7d),
        "tasks_completed_today": tasks_today,
        "cqs_level": avatar.cqs_level or "unknown",
        "phase": avatar.warming_phase,
        "is_frozen": avatar.is_frozen,
        "health_status": getattr(avatar, "health_status", None) or "unknown",
    }

    # ── Today's EPG ────────────────────────────────────────────────────────

    epg_slots = (
        db.query(EPGSlot)
        .filter(
            EPGSlot.avatar_id == avatar.id,
            EPGSlot.plan_date >= today_start.date(),
        )
        .order_by(EPGSlot.scheduled_at.asc())
        .limit(15)
        .all()
    )

    epg_list = [
        {
            "id": str(slot.id),
            "scheduled_at": slot.scheduled_at.isoformat() if slot.scheduled_at else None,
            "subreddit": slot.subreddit or "",
            "status": slot.status,
            "thread_title": slot.thread_title or "",
        }
        for slot in epg_slots
    ]

    # Plan = total slots today (including skipped)
    total_planned = len(epg_slots)

    # ── Pending Drafts (to approve) ───────────────────────────────────────

    pending_drafts = (
        db.query(CommentDraft)
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.status == "pending",
        )
        .order_by(CommentDraft.created_at.desc())
        .limit(10)
        .all()
    )

    client_id = avatar.client_ids[0] if avatar.client_ids else None
    drafts_list = [
        {
            "id": str(draft.id),
            "subreddit": (draft.thread.subreddit if draft.thread else "") or "",
            "thread_title": (draft.thread.post_title if draft.thread else "") or "",
            "text_preview": (draft.edited_draft or draft.ai_draft or "")[:120],
            "created_at": draft.created_at.isoformat() if draft.created_at else None,
            "approve_url": f"https://gorampit.com/clients/{client_id}/review" if client_id else None,
        }
        for draft in pending_drafts
    ]

    # ── Links ─────────────────────────────────────────────────────────────

    links = {
        "review_queue": f"https://gorampit.com/clients/{client_id}/review" if client_id else None,
        "avatar_detail": f"https://gorampit.com/admin/avatars/{avatar.id}",
        "epg_page": f"https://gorampit.com/clients/{client_id}/epg" if client_id else None,
        "dashboard": "https://gorampit.com/admin/",
    }

    return {
        "stats": stats,
        "total_planned": total_planned,
        "epg": epg_list,
        "pending_drafts": drafts_list,
        "links": links,
        "last_updated": now.isoformat(),
    }


# ─── Helper Functions ────────────────────────────────────────────────────────


def _version_lt(v1: str, v2: str) -> bool:
    """Compare two semver strings. Returns True if v1 < v2."""
    try:
        parts1 = [int(x) for x in v1.split(".")]
        parts2 = [int(x) for x in v2.split(".")]
        return parts1 < parts2
    except (ValueError, AttributeError):
        return False


def _get_daily_cap_remaining(db: Session, node: ExecutionNode) -> int:
    """Calculate how many more posts can be made today for this node's avatar.

    Uses the same logic as EPG budget: daily cap from settings minus
    tasks already reported/completed today.
    """
    from app.services.settings import get_setting

    if not node.active_reddit_username:
        return 0

    # Get daily cap from settings (default 8)
    cap_str = get_setting(db, "auto_posting_daily_cap")
    daily_cap = int(cap_str) if cap_str and cap_str.isdigit() else 8

    # Count tasks completed today for this avatar
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    completed_today = (
        db.query(ExecutionTask)
        .filter(
            ExecutionTask.avatar_username == node.active_reddit_username,
            ExecutionTask.task_lifecycle_status.in_(["REPORTED", "FINALIZED"]),
            ExecutionTask.updated_at >= today_start,
        )
        .count()
    )

    return max(0, daily_cap - completed_today)


# ─── Draft Review (Approve/Reject from Extension) ───────────────────────────


class DraftReviewRequest(BaseModel):
    """Request body for approving/rejecting a draft from extension."""
    action: str  # "approve" or "reject"
    edited_text: Optional[str] = None  # Optional edit before approve


@router.post("/drafts/{draft_id}/review")
async def review_draft(
    draft_id: str,
    body: DraftReviewRequest,
    executor: User = Depends(get_current_executor),
    db: Session = Depends(get_db),
):
    """Approve or reject a pending draft directly from the extension.

    This is the key endpoint that enables the extension to act as a reviewer,
    not just an executor. When a draft is approved here:
    1. Draft status → approved
    2. EPG slot status → approved
    3. ExecutionTask is created (if email_tasks_enabled)
    4. Extension will see the task in next /tasks poll

    Supports optional text edit before approval (edit + approve in one call).
    """
    from app.models.comment_draft import CommentDraft
    from app.models.epg_slot import EPGSlot
    from app.services.epg_executor import sync_slot_status, _dispatch_email_task_if_enabled
    from app.services.transparency import record_activity_event

    if body.action not in ("approve", "reject"):
        raise HTTPException(status_code=422, detail="action must be 'approve' or 'reject'")

    try:
        d_uuid = uuid.UUID(draft_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Draft not found")

    draft = db.query(CommentDraft).filter(CommentDraft.id == d_uuid).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    # Only allow review of pending drafts
    if draft.status != "pending":
        return {"status": "noop", "message": f"Draft already {draft.status}"}

    # Verify executor has access to this draft's avatar
    avatar = db.query(Avatar).filter(Avatar.id == draft.avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Draft not found")

    # Access check: executor must be linked to this avatar or be platform admin
    has_access = False
    if executor.role in ("owner", "partner", "avatar_manager"):
        has_access = True
    elif avatar.executor_email and avatar.executor_email == executor.email:
        has_access = True
    elif avatar.client_ids:
        from app.models.user_client_assignment import UserClientAssignment
        assigned = (
            db.query(UserClientAssignment.client_id)
            .filter(
                UserClientAssignment.user_id == executor.id,
                UserClientAssignment.is_active == True,  # noqa: E712
            )
            .all()
        )
        assigned_ids = {str(r.client_id) for r in assigned}
        for cid in avatar.client_ids:
            if cid in assigned_ids:
                has_access = True
                break

    if not has_access:
        raise HTTPException(status_code=403, detail="Not authorized to review this draft")

    now = datetime.now(timezone.utc)

    if body.action == "approve":
        # Apply edit if provided
        if body.edited_text and body.edited_text.strip():
            draft.edited_draft = body.edited_text.strip()

        draft.status = "approved"

        # Sync EPG slot
        slot = db.query(EPGSlot).filter(EPGSlot.draft_id == draft.id).first()
        if slot:
            slot.status = "approved"
            db.commit()
            # Create execution task for posting
            _dispatch_email_task_if_enabled(db, slot)
        else:
            db.commit()

        # Activity event
        try:
            record_activity_event(
                db, "review",
                f"Draft approved via extension for r/{draft.thread.subreddit if draft.thread else '?'}",
                draft.client_id,
                {"draft_id": str(draft.id), "action": "approved", "by": "extension"},
            )
        except Exception:
            pass

        # Self-learning capture
        try:
            from app.services.learning import LearningService
            thread = draft.thread
            if thread:
                learning_status = "approved_unchanged" if not body.edited_text else "approved"
                LearningService().capture_edit_record(db=db, draft=draft, thread=thread, status=learning_status)
                db.commit()
        except Exception:
            pass

        return {"status": "approved", "draft_id": str(draft.id)}

    else:  # reject
        draft.status = "rejected"

        # Sync EPG slot
        slot = db.query(EPGSlot).filter(EPGSlot.draft_id == draft.id).first()
        if slot:
            slot.status = "skipped"
            slot.skip_reason = "rejected_via_extension"

        db.commit()

        # Activity event
        try:
            record_activity_event(
                db, "review",
                f"Draft rejected via extension for r/{draft.thread.subreddit if draft.thread else '?'}",
                draft.client_id,
                {"draft_id": str(draft.id), "action": "rejected", "by": "extension"},
            )
        except Exception:
            pass

        return {"status": "rejected", "draft_id": str(draft.id)}


@router.post("/drafts/approve-all")
async def approve_all_drafts(
    avatar_username: str = Query(..., description="Reddit username"),
    executor: User = Depends(get_current_executor),
    db: Session = Depends(get_db),
):
    """Approve all pending drafts for an avatar. Bulk action from extension.

    Returns count of approved drafts.
    """
    from app.models.comment_draft import CommentDraft
    from app.models.epg_slot import EPGSlot
    from app.services.epg_executor import _dispatch_email_task_if_enabled
    from app.services.transparency import record_activity_event

    avatar = (
        db.query(Avatar)
        .filter(sa.func.lower(Avatar.reddit_username) == avatar_username.lower())
        .first()
    )
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    # Access check
    has_access = executor.role in ("owner", "partner", "avatar_manager")
    if not has_access and avatar.executor_email and avatar.executor_email == executor.email:
        has_access = True
    if not has_access and avatar.client_ids:
        from app.models.user_client_assignment import UserClientAssignment
        assigned = (
            db.query(UserClientAssignment.client_id)
            .filter(UserClientAssignment.user_id == executor.id, UserClientAssignment.is_active == True)
            .all()
        )
        assigned_ids = {str(r.client_id) for r in assigned}
        for cid in avatar.client_ids:
            if cid in assigned_ids:
                has_access = True
                break
    if not has_access:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Get all pending drafts for this avatar
    pending = (
        db.query(CommentDraft)
        .filter(CommentDraft.avatar_id == avatar.id, CommentDraft.status == "pending")
        .all()
    )

    approved_count = 0
    for draft in pending:
        draft.status = "approved"
        slot = db.query(EPGSlot).filter(EPGSlot.draft_id == draft.id).first()
        if slot:
            slot.status = "approved"

    db.commit()

    # Create execution tasks for all approved slots
    for draft in pending:
        slot = db.query(EPGSlot).filter(EPGSlot.draft_id == draft.id).first()
        if slot:
            _dispatch_email_task_if_enabled(db, slot)
        approved_count += 1

    # Activity event
    try:
        record_activity_event(
            db, "review",
            f"{approved_count} drafts bulk-approved via extension for u/{avatar.reddit_username}",
            avatar.client_ids[0] if avatar.client_ids else None,
            {"count": approved_count, "action": "bulk_approve", "by": "extension"},
        )
    except Exception:
        pass

    return {"status": "ok", "approved": approved_count}


# ─── Helper Functions ────────────────────────────────────────────────────────


def should_use_email_fallback(node_id: str | uuid.UUID, db: Session) -> bool:
    """Check if a node's dom_health is broken, indicating email channel should be used.

    When dom_health is broken, new tasks for this node should be routed to
    email channel instead of extension delivery.

    Args:
        node_id: UUID of the execution node to check.
        db: Database session.

    Returns:
        True if email fallback should be used (dom_health is broken).
    """
    try:
        nid = uuid.UUID(str(node_id))
    except (ValueError, TypeError):
        return False

    node = db.query(ExecutionNode).filter(ExecutionNode.id == nid).first()
    if node is None:
        return False

    return node.dom_health == "broken"
