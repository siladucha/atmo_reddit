"""Extension Dispatcher — task creation, assignment, and HMAC signing for browser extension.

Creates ExecutionTask records for the browser extension delivery channel.
Tasks are signed with HMAC-SHA256 to ensure integrity when delivered to
untrusted execution nodes.

Tasks are created in CREATED state and assigned to nodes via assign_task_to_node().
"""

import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import case
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.config import get_config
from app.logging_config import get_logger
from app.models.execution_node import ExecutionNode
from app.models.execution_task import ExecutionTask

logger = get_logger(__name__)


# Default lease duration (configurable via EXTENSION_LEASE_MINUTES env/setting)
DEFAULT_LEASE_MINUTES = 30


def compute_task_hash(
    secret: str,
    idempotency_key: str,
    task_type: str,
    avatar_username: str,
    target: str,
) -> str:
    """Compute HMAC-SHA256 hash for task integrity verification.

    Args:
        secret: HMAC secret key (from EXTENSION_HMAC_SECRET config).
        idempotency_key: Unique key for this task delivery.
        task_type: "post_comment" or "diagnostic_probe".
        avatar_username: Reddit username of the avatar.
        target: thread_url (for post_comment) or probe_type (for diagnostic_probe).

    Returns:
        Hex-encoded HMAC-SHA256 digest.
    """
    message = f"{idempotency_key}:{task_type}:{avatar_username}:{target}"
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def create_extension_task(
    db: Session,
    avatar_id: uuid.UUID,
    task_type: str,
    task_data: dict,
    probe_type: str | None = None,
) -> ExecutionTask:
    """Create an ExecutionTask for delivery via browser extension.

    Creates a task in CREATED state with HMAC signature and idempotency key.
    Does NOT assign to a node — that happens in assign_task_to_node().

    Args:
        db: SQLAlchemy session.
        avatar_id: UUID of the avatar this task is for.
        task_type: "post_comment" or "diagnostic_probe".
        task_data: Dict containing task details:
            - thread_url (str): Reddit thread URL (required for post_comment)
            - comment_text (str): Comment body (required for post_comment)
            - avatar_username (str): Reddit username
            - subreddit (str): Target subreddit
            - thread_title (str): Thread title (optional)
            - scheduled_at (datetime, optional): When to execute
        probe_type: Required for diagnostic_probe tasks
            ("reddit_cqs", "submission_visibility", "profile_check").

    Returns:
        The created ExecutionTask record.

    Raises:
        ValueError: If task_type is invalid or required fields missing.
    """
    if task_type not in ("post_comment", "diagnostic_probe"):
        raise ValueError(f"Invalid task_type: {task_type}. Must be 'post_comment' or 'diagnostic_probe'.")

    if task_type == "diagnostic_probe" and not probe_type:
        raise ValueError("probe_type is required for diagnostic_probe tasks.")

    avatar_username = task_data.get("avatar_username", "")
    if not avatar_username:
        raise ValueError("avatar_username is required in task_data.")

    # Generate unique idempotency key
    idempotency_key = str(uuid.uuid4())

    # Determine target for HMAC (thread_url for posts, probe_type for diagnostics)
    if task_type == "post_comment":
        target = task_data.get("thread_url", "")
        if not target:
            raise ValueError("thread_url is required in task_data for post_comment tasks.")
    else:
        target = probe_type

    # Compute HMAC signature
    hmac_secret = get_config("extension_hmac_secret")
    task_hash = compute_task_hash(
        secret=hmac_secret,
        idempotency_key=idempotency_key,
        task_type=task_type,
        avatar_username=avatar_username,
        target=target,
    )

    # Set lease expiry (now + configurable minutes)
    now = datetime.now(timezone.utc)
    lease_expires_at = now + timedelta(minutes=DEFAULT_LEASE_MINUTES)

    # Determine priority
    priority = "diagnostic" if task_type == "diagnostic_probe" else "content"

    # Create the ExecutionTask record
    task = ExecutionTask(
        avatar_id=avatar_id,
        task_type=task_type,
        probe_type=probe_type,
        priority=priority,
        idempotency_key=idempotency_key,
        task_hash=task_hash,
        lease_expires_at=lease_expires_at,
        task_lifecycle_status="CREATED",
        # Task content from task_data
        avatar_username=avatar_username,
        subreddit=task_data.get("subreddit", ""),
        thread_url=task_data.get("thread_url", ""),
        thread_title=task_data.get("thread_title", ""),
        generated_text=task_data.get("comment_text", ""),
        scheduled_at=task_data.get("scheduled_at"),
        # Extension delivery channel — default to old_reddit (most reliable)
        delivery_channel="extension",
        posting_strategy=task_data.get("posting_strategy", "old_reddit"),
        executor_contact=task_data.get("executor_contact", "extension"),
        # Required fields with defaults
        task_code=f"EXT-{now.strftime('%Y%m%d')}-{idempotency_key[:8].upper()}",
        deadline=lease_expires_at,
        client_id=task_data.get("client_id"),
        client_name=task_data.get("client_name", ""),
    )

    db.add(task)
    db.flush()

    return task


def assign_task_to_node(
    db: Session,
    task_id: uuid.UUID,
    execution_node_id: uuid.UUID,
) -> ExecutionTask:
    """Assign an extension task to an execution node (CREATED → ASSIGNED).

    Validates that:
    - Task exists and is in CREATED state
    - Node exists and is online
    - Node's active_reddit_username matches task's avatar_username

    On success:
    - Sets task_lifecycle_status = "ASSIGNED"
    - Sets execution_node_id
    - Refreshes lease_expires_at (now + 30 minutes)

    Args:
        db: SQLAlchemy session.
        task_id: UUID of the ExecutionTask to assign.
        execution_node_id: UUID of the ExecutionNode to assign to.

    Returns:
        The updated ExecutionTask record.

    Raises:
        ValueError: If task not found, wrong state, node offline, or account mismatch.
    """
    # Fetch task
    task = db.query(ExecutionTask).filter(ExecutionTask.id == task_id).first()
    if not task:
        raise ValueError(f"Task {task_id} not found.")
    if task.task_lifecycle_status != "CREATED":
        raise ValueError(
            f"Task {task_id} is in state '{task.task_lifecycle_status}', "
            f"expected 'CREATED'."
        )

    # Fetch node
    node = db.query(ExecutionNode).filter(ExecutionNode.id == execution_node_id).first()
    if not node:
        raise ValueError(f"Execution node {execution_node_id} not found.")
    if not node.is_online:
        raise ValueError(
            f"Execution node {execution_node_id} is offline. Cannot assign task."
        )

    # Validate account match
    if not node.active_reddit_username:
        raise ValueError(
            f"Execution node {execution_node_id} has no active Reddit username."
        )
    if node.active_reddit_username.lower() != task.avatar_username.lower():
        raise ValueError(
            f"Account mismatch: node has '{node.active_reddit_username}', "
            f"task requires '{task.avatar_username}'."
        )

    # Transition: CREATED → ASSIGNED
    now = datetime.now(timezone.utc)
    task.task_lifecycle_status = "ASSIGNED"
    task.execution_node_id = execution_node_id
    task.lease_expires_at = now + timedelta(minutes=DEFAULT_LEASE_MINUTES)

    db.flush()
    return task


def validate_report(
    db: Session,
    task_id: uuid.UUID,
    idempotency_key: str,
    report_data: dict,
) -> ExecutionTask:
    """Validate an extension report and finalize the task (REPORTED → FINALIZED).

    Validates:
    1. Task exists
    2. Task is in REPORTED state (if already FINALIZED → idempotent return)
    3. idempotency_key matches the task's stored key

    On success:
    - Sets task_lifecycle_status = "FINALIZED"
    - Stores report_data in task.verification_result (merges with existing)
    - Flushes session

    Args:
        db: SQLAlchemy session.
        task_id: UUID of the ExecutionTask to validate.
        idempotency_key: The idempotency key from the report (must match task's key).
        report_data: Dict of report results to store in verification_result.

    Returns:
        The updated ExecutionTask record.

    Raises:
        ValueError: If task not found, wrong state (not REPORTED/FINALIZED), or key mismatch.
    """
    # Fetch task
    task = db.query(ExecutionTask).filter(ExecutionTask.id == task_id).first()
    if not task:
        raise ValueError(f"Task {task_id} not found.")

    # Idempotent: if already FINALIZED, return as-is
    if task.task_lifecycle_status == "FINALIZED":
        return task

    # Validate state is REPORTED
    if task.task_lifecycle_status != "REPORTED":
        raise ValueError(
            f"Task {task_id} is in state '{task.task_lifecycle_status}', "
            f"expected 'REPORTED'."
        )

    # Validate idempotency key
    if task.idempotency_key != idempotency_key:
        raise ValueError(
            f"Idempotency key mismatch for task {task_id}."
        )

    # Transition: REPORTED → FINALIZED
    task.task_lifecycle_status = "FINALIZED"

    # Merge report_data into verification_result
    if task.verification_result:
        merged = {**task.verification_result, **report_data}
        task.verification_result = merged
    else:
        task.verification_result = report_data

    db.flush()
    return task


def route_task(
    db: Session,
    task: ExecutionTask,
) -> str:
    """Route a task to extension or determine fallback action.

    Decision logic:
    1. Find an online ExecutionNode where active_reddit_username matches
       task.avatar_username (case-insensitive), is_online=True, and
       last_heartbeat within 30 minutes (stale nodes treated as offline).
    2. If found: assign task to node → return "extension".
    3. If no matching online node and task in CREATED for >30 min: return "email_fallback".
    4. Otherwise: leave task in CREATED state → return "hold".

    Does NOT send email itself — caller handles fallback logic.

    Args:
        db: SQLAlchemy session.
        task: ExecutionTask to route (must be in CREATED state).

    Returns:
        One of: "extension", "hold", "email_fallback".
    """
    now = datetime.now(timezone.utc)
    heartbeat_threshold = now - timedelta(minutes=30)

    # Find an online node with matching Reddit username and fresh heartbeat
    node = (
        db.query(ExecutionNode)
        .filter(
            ExecutionNode.is_online == True,  # noqa: E712
            ExecutionNode.active_reddit_username.isnot(None),
            sa_func.lower(ExecutionNode.active_reddit_username)
            == task.avatar_username.lower(),
            ExecutionNode.last_heartbeat >= heartbeat_threshold,
        )
        .first()
    )

    if node:
        # Online node found — assign task
        assign_task_to_node(db, task.id, node.id)
        return "extension"

    # No matching online node — check how long task has been in CREATED
    if task.task_lifecycle_status == "CREATED" and task.created_at:
        created_threshold = now - timedelta(minutes=30)
        if task.created_at <= created_threshold:
            return "email_fallback"

    return "hold"


def serialize_task_for_extension(task: ExecutionTask) -> dict:
    """Serialize an ExecutionTask into the payload dict delivered to the extension.

    This is the canonical format the extension expects when polling GET /tasks.
    Centralizes serialization so that all callers produce consistent payloads.

    Args:
        task: ExecutionTask ORM instance.

    Returns:
        Dict with all fields the extension needs for execution.
    """
    return {
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
        "scheduled_at": task.scheduled_at.isoformat() if task.scheduled_at else None,
        "lease_expires_at": task.lease_expires_at.isoformat() if task.lease_expires_at else None,
        "posting_strategy": task.posting_strategy or "old_reddit",  # Default: old_reddit
    }


def get_pending_tasks_for_node(
    db: Session,
    node: ExecutionNode,
    limit: int = 20,
) -> list[ExecutionTask]:
    """Get pending tasks eligible for assignment to a given execution node.

    Queries tasks that are CREATED and match the node's active_reddit_username.
    Orders by priority (diagnostic first, content second), then by scheduled_at
    ascending (NULLs treated as immediate — sorted first).

    This centralizes the business logic used by the GET /tasks endpoint.

    Args:
        db: SQLAlchemy session.
        node: ExecutionNode instance with active_reddit_username set.
        limit: Maximum number of tasks to return (default 20).

    Returns:
        Ordered list of ExecutionTask records (diagnostic before content,
        earliest scheduled first within same priority).
    """
    if not node.active_reddit_username:
        return []

    # Priority ordering: diagnostic (sort key 0) before content (sort key 1)
    priority_order = case(
        (ExecutionTask.priority == "diagnostic", 0),
        else_=1,
    )

    # NULLs treated as immediate (sort key 0 = first), non-NULL = sort key 1
    null_scheduled_first = case(
        (ExecutionTask.scheduled_at.is_(None), 0),
        else_=1,
    )

    tasks = (
        db.query(ExecutionTask)
        .filter(
            ExecutionTask.task_lifecycle_status == "CREATED",
            sa_func.lower(ExecutionTask.avatar_username)
            == node.active_reddit_username.lower(),
        )
        .order_by(
            priority_order,
            null_scheduled_first,
            ExecutionTask.scheduled_at.asc(),
        )
        .limit(limit)
        .all()
    )

    return tasks


def get_available_tasks_for_node(
    db: Session,
    node_id: uuid.UUID,
) -> list[ExecutionTask]:
    """Get tasks eligible for assignment to a given execution node.

    Returns tasks where:
    - task_lifecycle_status == "CREATED"
    - avatar_username matches node's active_reddit_username (case-insensitive)
    - delivery_channel == "extension"

    Ordered by:
    1. Priority: diagnostic tasks first, then content
    2. scheduled_at ascending (earliest first)

    Args:
        db: SQLAlchemy session.
        node_id: UUID of the execution node.

    Returns:
        List of eligible ExecutionTask records.

    Raises:
        ValueError: If node not found.
    """
    node = db.query(ExecutionNode).filter(ExecutionNode.id == node_id).first()
    if not node:
        raise ValueError(f"Execution node {node_id} not found.")

    if not node.active_reddit_username:
        return []

    # Priority ordering: diagnostic first (via CASE expression)
    priority_order = case(
        (ExecutionTask.priority == "diagnostic", 0),
        else_=1,
    )

    tasks = (
        db.query(ExecutionTask)
        .filter(
            ExecutionTask.task_lifecycle_status == "CREATED",
            ExecutionTask.delivery_channel == "extension",
            sa_func.lower(ExecutionTask.avatar_username)
            == node.active_reddit_username.lower(),
        )
        .order_by(priority_order, ExecutionTask.scheduled_at.asc())
        .all()
    )

    return tasks



def expire_stale_leases(db: Session) -> list[ExecutionTask]:
    """Find ASSIGNED/EXECUTING tasks past their lease and mark them EXPIRED.

    Queries tasks where:
    - task_lifecycle_status IN ("ASSIGNED", "EXECUTING")
    - lease_expires_at < now(UTC)

    For each found task:
    - Sets task_lifecycle_status = "EXPIRED"
    - Clears execution_node_id (releases the node)

    Called by a Celery task every 5 minutes. Expired tasks may be re-created
    (diagnostics) or fall back to email (content).

    Args:
        db: SQLAlchemy session.

    Returns:
        List of tasks that were expired.
    """
    now = datetime.now(timezone.utc)

    stale_tasks = (
        db.query(ExecutionTask)
        .filter(
            ExecutionTask.task_lifecycle_status.in_(["ASSIGNED", "EXECUTING"]),
            ExecutionTask.lease_expires_at < now,
        )
        .all()
    )

    for task in stale_tasks:
        original_status = task.task_lifecycle_status
        task.task_lifecycle_status = "EXPIRED"
        task.execution_node_id = None
        logger.info(
            "Expired stale lease: task_id=%s, original_status=%s, "
            "lease_expired_at=%s",
            task.id,
            original_status,
            task.lease_expires_at,
        )

    if stale_tasks:
        db.commit()

    return stale_tasks
