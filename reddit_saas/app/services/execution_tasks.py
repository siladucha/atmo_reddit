"""Execution Task service — core business logic for EPG email task delivery.

Creates tasks from approved EPG slots, dispatches delivery via channels,
handles verification, expiry, and SLA metrics.

Usage:
    from app.services.execution_tasks import create_execution_task, dispatch_delivery
    task = create_execution_task(db, epg_slot_id)
    dispatch_delivery(db, task.id)
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.comment_draft import CommentDraft
from app.models.epg_slot import EPGSlot
from app.models.execution_task import DeliveryAttempt, ExecutionTask
from app.services.email_sender import compute_payload_hash, send_email, send_task_email
from app.services.settings import get_setting, get_setting_int

logger = get_logger(__name__)

TEMPLATE_VERSION = "v1"

# --- State Machine (Audit Patch 5) ---
ALLOWED_TRANSITIONS = {
    "generated": {"emailed", "expired", "cancelled"},
    "emailed": {"accepted", "expired", "cancelled"},
    "accepted": {"submitted", "expired", "cancelled"},
    "submitted": {"url_verified", "failed", "expired", "cancelled"},
    "url_verified": {"content_verified", "verified", "failed", "cancelled"},
    "content_verified": {"verified", "failed", "cancelled"},
    "verified": set(),  # Terminal
    "failed": {"submitted"},  # Allow retry
    "expired": set(),  # Terminal
    "cancelled": set(),  # Terminal
    "needs_regeneration": {"generated"},  # Can restart
}


# ---------------------------------------------------------------------------
# Task Code Generation
# ---------------------------------------------------------------------------

def generate_task_code(db: Session) -> str:
    """Generate next sequential task code: TASK-YYYYMMDD-NNN."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"TASK-{today}-"

    # Count existing tasks for today
    count = (
        db.query(ExecutionTask)
        .filter(ExecutionTask.task_code.like(f"{prefix}%"))
        .count()
    )
    return f"{prefix}{count + 1:03d}"


# ---------------------------------------------------------------------------
# Task Creation (idempotent)
# ---------------------------------------------------------------------------

def create_execution_task(
    db: Session,
    epg_slot_id: uuid.UUID,
    executor_contact: str | None = None,
    executor_type: str = "admin",
) -> ExecutionTask | None:
    """Create an ExecutionTask from an approved EPG slot.

    Idempotent: if task already exists for this slot (UNIQUE constraint),
    returns the existing task without error.

    Args:
        db: Database session
        epg_slot_id: UUID of the approved EPG slot
        executor_contact: Email/contact for the executor (falls back to default)
        executor_type: Type of executor (admin, avatar_owner, provider)

    Returns:
        ExecutionTask on success, None if slot not found or not approved.
    """
    # Check for existing task (idempotency)
    existing = (
        db.query(ExecutionTask)
        .filter(ExecutionTask.epg_slot_id == epg_slot_id)
        .first()
    )
    if existing:
        logger.debug("Task already exists for slot %s: %s", epg_slot_id, existing.task_code)
        return existing

    # Load slot with relationships
    slot = db.query(EPGSlot).filter(EPGSlot.id == epg_slot_id).first()
    if not slot:
        logger.warning("EPG slot not found: %s", epg_slot_id)
        return None

    if slot.status != "approved":
        logger.warning("EPG slot %s not approved (status=%s)", epg_slot_id, slot.status)
        return None

    # Resolve executor contact — avatar must have a verified email
    avatar_obj = slot.avatar
    if not executor_contact:
        if avatar_obj and avatar_obj.executor_email and avatar_obj.executor_email_verified:
            executor_contact = avatar_obj.executor_email
        else:
            # Extension channel doesn't require email
            channel = getattr(avatar_obj, "delivery_channel", "email") if avatar_obj else "email"
            if channel == "extension":
                # Extension-only: no email needed, use avatar username as contact
                executor_contact = avatar_obj.reddit_username if avatar_obj else None
            else:
                reason = "no executor email" if not (avatar_obj and avatar_obj.executor_email) else "executor email not verified"
                logger.warning(
                    "Skipping email task for slot %s: %s (avatar=%s)",
                    epg_slot_id, reason, avatar_obj.reddit_username if avatar_obj else "?"
                )
                return None

    # Determine delivery channel from avatar setting
    delivery_channel = getattr(avatar_obj, "delivery_channel", "email") if avatar_obj else "email"

    # Resolve related data
    draft = db.query(CommentDraft).filter(CommentDraft.id == slot.draft_id).first() if slot.draft_id else None
    avatar = avatar_obj  # already loaded above
    thread = slot.thread
    client_name = ""
    if slot.client_id:
        from app.models.client import Client
        client = db.query(Client).filter(Client.id == slot.client_id).first()
        client_name = client.client_name if client else ""

    # Compute deadline — soft window end.
    # Default window: 2 hours from scheduled_at (configurable via epg_slot_window_hours).
    # This means executor/extension has a 2-hour window to post, not a pinpoint time.
    window_hours = get_setting_int(db, "epg_slot_window_hours", default=2)
    base_time = slot.scheduled_at or datetime.now(timezone.utc)
    deadline = base_time + timedelta(hours=window_hours)

    # Determine task type
    task_type = "comment"
    if draft and draft.location_depth and draft.location_depth > 0:
        task_type = "reply"

    # Generated text snapshot
    generated_text = ""
    if draft:
        generated_text = draft.edited_draft or draft.ai_draft or ""

    # Thread URL — resolve from thread (professional) or hobby_subreddits (hobby)
    thread_url = ""
    if thread:
        thread_url = thread.url or f"https://reddit.com/r/{thread.subreddit}/comments/{thread.reddit_native_id}"
    elif slot.hobby_post_id:
        try:
            from app.models.hobby import HobbySubreddit
            hobby_post = db.query(HobbySubreddit).filter(HobbySubreddit.id == slot.hobby_post_id).first()
            if hobby_post and hobby_post.url:
                thread_url = hobby_post.url
        except Exception:
            pass
    if not thread_url and slot.subreddit:
        thread_url = f"https://reddit.com/r/{slot.subreddit}"

    # Create task
    task = ExecutionTask(
        id=uuid.uuid4(),
        task_code=generate_task_code(db),
        executor_token=uuid.uuid4(),
        epg_slot_id=epg_slot_id,
        draft_id=slot.draft_id,
        avatar_id=slot.avatar_id,
        client_id=slot.client_id,
        thread_id=slot.thread_id,
        executor_contact=executor_contact,
        executor_type=executor_type,
        delivery_channel=delivery_channel,
        task_type=task_type,
        subreddit=slot.subreddit or (thread.subreddit if thread else ""),
        thread_url=thread_url,
        thread_title=slot.thread_title or (thread.post_title if thread else ""),
        avatar_username=avatar.reddit_username if avatar else "",
        client_name=client_name,
        generated_text=generated_text,
        scheduled_at=slot.scheduled_at,
        deadline=deadline,
        status="generated",
        status_history=[{"status": "generated", "at": datetime.now(timezone.utc).isoformat(), "by": "system"}],
        delivery_count=0,
    )

    # Extension channel: set lifecycle status so extension can poll it immediately
    if delivery_channel in ("extension", "both"):
        task.task_lifecycle_status = "CREATED"
        task.idempotency_key = str(uuid.uuid4())
        task.priority = "content"
        # Default posting strategy: old_reddit (most reliable, no Shadow DOM / reCAPTCHA)
        task.posting_strategy = "old_reddit"

        # SAFETY: Extension tasks MUST have scheduled_at to prevent burst posting.
        # Without scheduled_at, the extension scheduler treats them as "immediate"
        # and fires all tasks back-to-back with only 3-min gaps.
        if task.scheduled_at is None:
            logger.warning(
                "Extension task for slot %s has no scheduled_at — assigning now+30min fallback",
                epg_slot_id,
            )
            task.scheduled_at = datetime.now(timezone.utc) + timedelta(minutes=30)

    # A/B Test: override posting method if avatar in active experiment
    from app.services.settings import get_setting
    ab_test_enabled = get_setting(db, "ab_test_enabled") == "true"
    if ab_test_enabled:
        from app.services.ab_test.posting_router import get_posting_method
        posting_config = get_posting_method(db, slot.avatar_id)
        if posting_config:
            task.delivery_channel = posting_config.delivery_channel
            task.posting_strategy = posting_config.posting_strategy
            # Re-apply extension lifecycle setup if channel changed to extension
            if posting_config.delivery_channel in ("extension", "both"):
                task.task_lifecycle_status = "CREATED"
                if not task.idempotency_key:
                    task.idempotency_key = str(uuid.uuid4())
                task.priority = "content"

    try:
        db.add(task)
        db.commit()
        db.refresh(task)
        logger.info("Created execution task: %s for slot %s", task.task_code, epg_slot_id)
        return task
    except IntegrityError:
        db.rollback()
        # Race condition: another worker created the task. Return existing.
        existing = (
            db.query(ExecutionTask)
            .filter(ExecutionTask.epg_slot_id == epg_slot_id)
            .first()
        )
        return existing


# ---------------------------------------------------------------------------
# Post Draft Execution Task Creation
# ---------------------------------------------------------------------------

def create_post_execution_task(
    db: Session,
    post_draft_id: uuid.UUID,
) -> ExecutionTask | None:
    """Create an ExecutionTask from an approved PostDraft.

    Unlike comment tasks which are tied to EPG slots, post tasks are created
    directly from approved PostDraft records. The execution task delivers
    the post title + body to the executor for submission to Reddit.

    Idempotent: if task already exists for this post_draft (by thread_url match),
    returns None without error.

    Returns:
        ExecutionTask on success, None if draft not found/not approved or executor not configured.
    """
    from app.models.post_draft import PostDraft
    from app.models.avatar import Avatar

    draft = db.query(PostDraft).filter(PostDraft.id == post_draft_id).first()
    if not draft:
        logger.warning("PostDraft not found: %s", post_draft_id)
        return None

    if draft.status != "approved":
        logger.warning("PostDraft %s not approved (status=%s)", post_draft_id, draft.status)
        return None

    # Check for existing task (idempotency by subreddit + avatar + title)
    existing = (
        db.query(ExecutionTask)
        .filter(
            ExecutionTask.avatar_id == draft.avatar_id,
            ExecutionTask.task_type == "post",
            ExecutionTask.thread_title == (draft.edited_title or draft.ai_title or ""),
            ExecutionTask.status.notin_(["cancelled", "expired", "failed"]),
        )
        .first()
    )
    if existing:
        logger.debug("Post execution task already exists for draft %s: %s", post_draft_id, existing.task_code)
        return existing

    # Load avatar
    avatar = db.query(Avatar).filter(Avatar.id == draft.avatar_id).first()
    if not avatar:
        logger.warning("Avatar not found for PostDraft %s", post_draft_id)
        return None

    # Resolve executor contact
    delivery_channel = getattr(avatar, "delivery_channel", "email") or "email"
    executor_contact = None

    if delivery_channel == "extension":
        executor_contact = avatar.reddit_username
    elif avatar.executor_email and avatar.executor_email_verified:
        executor_contact = avatar.executor_email
    else:
        reason = "no executor email" if not avatar.executor_email else "executor email not verified"
        logger.warning(
            "Skipping post task for draft %s: %s (avatar=%s)",
            post_draft_id, reason, avatar.reddit_username,
        )
        return None

    # Resolve client name
    client_name = ""
    if draft.client_id:
        from app.models.client import Client
        client = db.query(Client).filter(Client.id == draft.client_id).first()
        client_name = client.client_name if client else ""

    # Build task content
    title = draft.edited_title or draft.ai_title or ""
    body = draft.edited_body or draft.ai_body or ""
    generated_text = f"TITLE: {title}\n\n---\n\nBODY:\n{body}"
    thread_url = f"https://old.reddit.com/r/{draft.subreddit}/submit"

    # Compute deadline
    deadline_hours = get_setting_int(db, "email_tasks_deadline_hours", default=4)
    deadline = datetime.now(timezone.utc) + timedelta(hours=deadline_hours)

    # Scheduled_at = 30 min from now (give executor time to see it)
    scheduled_at = datetime.now(timezone.utc) + timedelta(minutes=30)

    task = ExecutionTask(
        id=uuid.uuid4(),
        task_code=generate_task_code(db),
        executor_token=uuid.uuid4(),
        epg_slot_id=None,  # Posts are not EPG-slot-linked
        draft_id=None,  # draft_id FK is for CommentDraft, not PostDraft
        avatar_id=avatar.id,
        client_id=draft.client_id,
        thread_id=None,
        executor_contact=executor_contact,
        executor_type="admin",
        delivery_channel=delivery_channel,
        task_type="post",
        subreddit=draft.subreddit,
        thread_url=thread_url,
        thread_title=title,
        avatar_username=avatar.reddit_username,
        client_name=client_name,
        generated_text=generated_text,
        scheduled_at=scheduled_at,
        deadline=deadline,
        status="generated",
        status_history=[{"status": "generated", "at": datetime.now(timezone.utc).isoformat(), "by": "system"}],
        delivery_count=0,
    )

    # Extension channel setup
    if delivery_channel in ("extension", "both"):
        task.task_lifecycle_status = "CREATED"
        task.idempotency_key = str(uuid.uuid4())
        task.priority = "content"
        task.posting_strategy = "old_reddit"

    try:
        db.add(task)
        db.commit()
        db.refresh(task)
        logger.info("Created post execution task: %s for PostDraft %s (r/%s)", task.task_code, post_draft_id, draft.subreddit)
        return task
    except IntegrityError:
        db.rollback()
        logger.warning("Duplicate post execution task for draft %s", post_draft_id)
        return None


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

def can_resend(db: Session, task: ExecutionTask) -> tuple[bool, str | None]:
    """Check anti-spam limits before allowing resend.

    Returns (allowed, reason_if_denied).
    """
    max_resends = get_setting_int(db, "email_tasks_max_resends", default=3)
    cooldown_min = get_setting_int(db, "email_tasks_cooldown_minutes", default=10)

    # +1 because delivery_count includes the initial send
    if task.delivery_count > max_resends:
        return False, f"Maximum resends ({max_resends}) reached"

    if task.last_delivered_at:
        elapsed = (datetime.now(timezone.utc) - task.last_delivered_at).total_seconds() / 60
        if elapsed < cooldown_min:
            remaining = int(cooldown_min - elapsed)
            return False, f"Cooldown active: wait {remaining} more minutes"

    # Cannot resend terminal tasks
    if task.status in ("verified", "expired", "failed", "cancelled"):
        return False, f"Task is in terminal state: {task.status}"

    return True, None


def dispatch_delivery(db: Session, task_id: uuid.UUID, force: bool = False) -> DeliveryAttempt | None:
    """Create a DeliveryAttempt and send via the configured channel.

    Args:
        db: Database session
        task_id: ExecutionTask UUID
        force: If True, bypass anti-spam checks (admin override)

    Returns:
        DeliveryAttempt on success, None on failure.
    """
    task = db.query(ExecutionTask).filter(ExecutionTask.id == task_id).first()
    if not task:
        logger.error("ExecutionTask not found: %s", task_id)
        return None

    # Anti-spam check
    if not force:
        allowed, reason = can_resend(db, task)
        if not allowed:
            logger.warning("Delivery blocked for %s: %s", task.task_code, reason)
            return None

    # Compose email
    subject, body_text, body_html = compose_task_email(task)
    payload_hash = compute_payload_hash(body_text)
    attempt_number = task.delivery_count + 1

    # Create delivery attempt (idempotency via UNIQUE constraint)
    attempt = DeliveryAttempt(
        id=uuid.uuid4(),
        task_id=task.id,
        attempt_number=attempt_number,
        channel=task.delivery_channel,
        recipient=task.executor_contact,
        status="pending",
        subject=subject,
        template_version=TEMPLATE_VERSION,
        payload_hash=payload_hash,
        body_excerpt=body_text[:200],
    )

    try:
        db.add(attempt)
        db.flush()
    except IntegrityError:
        db.rollback()
        logger.warning("Duplicate delivery attempt %d for task %s", attempt_number, task.task_code)
        return None

    # Send via channel
    # Extension channel: tasks are picked up by polling — no email needed
    if task.delivery_channel == "extension":
        attempt.status = "delivered"
        attempt.sent_at = datetime.now(timezone.utc)
        attempt.provider_message_id = "extension_poll"

        task.status = "emailed"  # reuse status for compat (means "delivered to executor")
        task.status_changed_at = datetime.now(timezone.utc)
        task.last_delivered_at = datetime.now(timezone.utc)
        task.delivery_count = attempt_number
        task.latest_delivery_attempt_id = attempt.id

        history = task.status_history or []
        history.append({"status": "extension_delivered", "at": datetime.now(timezone.utc).isoformat(), "by": "system"})
        task.status_history = history

        db.commit()
        logger.info("Task %s marked for extension delivery (avatar=%s)", task.task_code, task.avatar_username)
        return attempt

    headers = {
        "X-RAMP-Task-ID": str(task.id),
        "X-RAMP-Task-Code": task.task_code,
    }
    reply_to = f"task+{task.task_code}@gorampit.com"

    success, message_id = send_task_email(
        to=task.executor_contact,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        headers=headers,
        reply_to=reply_to,
    )

    now = datetime.now(timezone.utc)

    if success:
        attempt.status = "sent"
        attempt.sent_at = now
        attempt.provider_message_id = message_id

        task.status = "emailed"
        task.status_changed_at = now
        task.last_delivered_at = now
        task.delivery_count = attempt_number
        task.latest_delivery_attempt_id = attempt.id

        # Append to status history
        history = task.status_history or []
        history.append({"status": "emailed", "at": now.isoformat(), "by": "system"})
        task.status_history = history
    else:
        attempt.status = "failed"
        attempt.error = "SMTP delivery failed"
        task.delivery_count = attempt_number

    db.commit()
    return attempt


# ---------------------------------------------------------------------------
# Email Composition
# ---------------------------------------------------------------------------

CQS_CHECK_EMAIL_TEMPLATE = """RAMP — CQS HEALTH CHECK
========================

Task:     {task_code}
Avatar:   u/{avatar_username}
Action:   Post in r/WhatIsMyCQS

INSTRUCTIONS
------------
1. Log in to Reddit as u/{avatar_username}
2. Go to https://reddit.com/r/WhatIsMyCQS/submit
3. Create a text post with title: "What is my cqs?"
4. Body can be left empty
5. Submit the post
6. Click the action link below to confirm done

ACTION LINK
-----------
{token_link}

WHY THIS TASK?
--------------
Routine health check. Reddit assigns a quality score to every account.
We check periodically to ensure good standing. Takes 30 seconds.

---
Task Code: {task_code}
Deadline: 48 hours
Do not forward this email.
"""


def compose_task_email(task: ExecutionTask) -> tuple[str, str, str | None]:
    """Compose email subject and body for an execution task.

    Returns: (subject, body_text, body_html)
    body_html is None for MVP (plain text only).
    """
    # --- CQS Check Task: dedicated template ---
    # Matches both legacy "cqs_check" and new "diagnostic_probe" with probe_type=reddit_cqs
    if task.task_type == "cqs_check" or (task.task_type == "diagnostic_probe" and task.probe_type == "reddit_cqs"):
        base_url = "https://gorampit.com"
        token_link = f"{base_url}/tasks/{task.task_code}/{task.executor_token}"

        subject = f"[RAMP] CQS Check — u/{task.avatar_username} — {task.task_code}"
        body_text = CQS_CHECK_EMAIL_TEMPLATE.format(
            task_code=task.task_code,
            avatar_username=task.avatar_username,
            token_link=token_link,
        )
        return subject, body_text, None

    # --- Standard content task ---
    # Format deadline time (soft window end)
    deadline_str = task.deadline.strftime("%H:%M") if task.deadline else "N/A"

    # Subject — RAMP Task for <brand>
    subject = f"RAMP Task for {task.client_name}"

    # Token link
    from app.services.settings import get_setting as _gs
    from app.database import SessionLocal
    _db = SessionLocal()
    try:
        app_host = _gs(_db, "app_env")
    finally:
        _db.close()
    base_url = "https://gorampit.com"
    token_link = f"{base_url}/tasks/{task.task_code}/{task.executor_token}"

    # Plain text body
    body_text = f"""RAMP EXECUTION TASK
====================

Task:           {task.task_code}
Client:         {task.client_name}
Avatar:         u/{task.avatar_username}
Subreddit:      r/{task.subreddit} — https://reddit.com/r/{task.subreddit}
Type:           {task.task_type.capitalize()}

THREAD
------
Title:  {task.thread_title}
URL:    {task.thread_url or "See subreddit link above"}

TIMING
------
Post by:     {deadline_str}

COMMENT TO POST
---------------
{task.generated_text}

ACTION LINK
-----------
Accept & submit result:
{token_link}

INSTRUCTIONS
------------
1. Click the action link above to accept the task
2. Log in to Reddit as u/{task.avatar_username}
3. Navigate to the thread URL
4. Post the comment (minor wording adjustments OK)
5. Copy your posted comment permalink
6. Submit the permalink via the action link

---
Task Code: {task.task_code}
Do not forward this email.
"""

    return subject, body_text, None  # No HTML for MVP


# ---------------------------------------------------------------------------
# Status Transitions
# ---------------------------------------------------------------------------

def _transition_status(db: Session, task: ExecutionTask, new_status: str, by: str = "system") -> None:
    """Update task status with history tracking and state machine validation."""
    allowed = ALLOWED_TRANSITIONS.get(task.status, set())
    if new_status not in allowed:
        logger.warning(
            "Invalid state transition for %s: %s -> %s (allowed: %s)",
            task.task_code, task.status, new_status, allowed,
        )
        return  # Silently reject invalid transitions

    now = datetime.now(timezone.utc)
    task.status = new_status
    task.status_changed_at = now
    history = task.status_history or []
    history.append({"status": new_status, "at": now.isoformat(), "by": by})
    task.status_history = history


def accept_task(db: Session, task_id: uuid.UUID, executor_token: uuid.UUID) -> ExecutionTask | None:
    """Executor accepts a task via token link."""
    task = (
        db.query(ExecutionTask)
        .filter(ExecutionTask.id == task_id, ExecutionTask.executor_token == executor_token)
        .first()
    )
    if not task:
        return None
    if task.status not in ("emailed",):
        return task  # Already accepted or in later state
    _transition_status(db, task, "accepted", by="executor")
    db.commit()
    return task


def submit_url(db: Session, task_id: uuid.UUID, executor_token: uuid.UUID, reddit_url: str) -> ExecutionTask | None:
    """Executor submits a Reddit URL for verification."""
    task = (
        db.query(ExecutionTask)
        .filter(ExecutionTask.id == task_id, ExecutionTask.executor_token == executor_token)
        .first()
    )
    if not task:
        return None
    if task.status in ("verified", "expired", "cancelled"):
        return task  # Terminal state

    task.submitted_url = reddit_url
    _transition_status(db, task, "submitted", by="executor")
    db.commit()
    return task


def cancel_task(db: Session, task_id: uuid.UUID, reason: str) -> ExecutionTask | None:
    """Admin cancels a task (soft delete — never deleted)."""
    task = db.query(ExecutionTask).filter(ExecutionTask.id == task_id).first()
    if not task:
        return None
    if task.status in ("verified", "cancelled"):
        return task  # Already terminal

    task.cancelled_at = datetime.now(timezone.utc)
    task.cancel_reason = reason
    _transition_status(db, task, "cancelled", by="admin")
    db.commit()
    return task


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------

def expire_overdue_tasks(db: Session) -> int:
    """Transition overdue active tasks to expired. Returns count.

    Uses atomic UPDATE with guard: only expires tasks that have NOT
    had a URL submitted (prevents race with executor submission).
    """
    now = datetime.now(timezone.utc)
    active_statuses = ("generated", "emailed", "accepted")

    # Atomic update — prevents race condition with concurrent submit_url()
    count = (
        db.query(ExecutionTask)
        .filter(
            ExecutionTask.status.in_(active_statuses),
            ExecutionTask.deadline < now,
            ExecutionTask.submitted_url.is_(None),  # Guard: don't expire if URL already submitted
        )
        .update(
            {
                "status": "expired",
                "status_changed_at": now,
            },
            synchronize_session="fetch",
        )
    )

    if count > 0:
        db.commit()
        logger.info("Expired %d overdue execution tasks", count)

    return count


# ---------------------------------------------------------------------------
# SLA Metrics
# ---------------------------------------------------------------------------

def get_sla_metrics(db: Session, period_days: int = 30, executor_id=None, client_id=None) -> dict:
    """Compute SLA metrics from stored execution task data."""
    from sqlalchemy import func as sqlfunc

    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)
    query = db.query(ExecutionTask).filter(ExecutionTask.created_at >= cutoff)

    if executor_id:
        query = query.filter(ExecutionTask.executor_id == executor_id)
    if client_id:
        query = query.filter(ExecutionTask.client_id == client_id)

    tasks = query.all()
    total = len(tasks)

    if total == 0:
        return {
            "period_days": period_days,
            "total_tasks": 0,
            "task_accept_rate": 0,
            "task_submit_rate": 0,
            "verification_pass_rate": 0,
            "median_execution_time_minutes": 0,
            "expired_task_rate": 0,
        }

    emailed = sum(1 for t in tasks if t.status != "generated")
    accepted = sum(1 for t in tasks if t.status not in ("generated", "emailed"))
    submitted = sum(1 for t in tasks if t.submitted_url is not None)
    verified = sum(1 for t in tasks if t.status == "verified")
    expired = sum(1 for t in tasks if t.status == "expired")

    # Median execution time (emailed -> submitted)
    exec_times = []
    for t in tasks:
        if t.submitted_url and t.last_delivered_at and t.status_history:
            # Find submitted timestamp from history
            for entry in (t.status_history or []):
                if entry.get("status") == "submitted" and entry.get("at"):
                    from dateutil.parser import parse as parse_dt
                    submitted_at = parse_dt(entry["at"])
                    delta = (submitted_at - t.last_delivered_at).total_seconds() / 60
                    if delta > 0:
                        exec_times.append(delta)
                    break

    median_exec = 0
    if exec_times:
        exec_times.sort()
        mid = len(exec_times) // 2
        median_exec = exec_times[mid]

    return {
        "period_days": period_days,
        "total_tasks": total,
        "task_accept_rate": round(accepted / max(emailed, 1), 3),
        "task_submit_rate": round(submitted / max(accepted, 1), 3),
        "verification_pass_rate": round(verified / max(submitted, 1), 3),
        "median_execution_time_minutes": round(median_exec, 1),
        "expired_task_rate": round(expired / total, 3),
    }
