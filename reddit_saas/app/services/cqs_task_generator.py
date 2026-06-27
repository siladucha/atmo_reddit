"""CQS Check Task Generator -- creates periodic execution tasks for CQS health checks.

When an avatar has no EPG budget (CQS=lowest -> budget=0), the system cannot
generate content tasks and no emails reach the executor. This service breaks
the deadlock by sending CQS check tasks independently of EPG.

Flow:
1. Identify avatars needing a CQS check (interval-based + exclusion rules)
2. Create ExecutionTask(task_type="cqs_check") with instructions to post in r/WhatIsMyCQS
3. Existing dispatch pipeline delivers the email to executor
4. Executor posts -> existing check_cqs_all_avatars reads bot reply -> CQS updates -> EPG resumes

Frequency rules:
- CQS=lowest (any age): every 7 days (recovery mode)
- Account < 90 days (CQS above lowest): every 7 days (young = volatile)
- Account >= 90 days AND CQS above lowest: every 30 days (stable)

Self-Healing Recovery Loop -- Full Timeline (Requirement R9)
============================================================
The self-healing loop recovers avatars restricted by Reddit
(CQS=lowest -> zero EPG budget -> no content generation -> system deadlock).

Timeline for a restricted avatar recovering to normal operations:

  Day 0: Avatar flagged CQS=lowest -> AttentionBudget.from_avatar() returns 0
          -> EPG build skips avatar ("budget_exhausted")
          -> No content tasks or emails generated for this avatar

  Day 0-7: CQS task generator (this service) detects the avatar needs a check
            (interval=7d for CQS=lowest). Creates ExecutionTask(task_type="cqs_check").
            Dispatch pipeline sends email to executor at 07:05 Israel time.

  Day 1-3: Executor posts "What is my cqs?" in r/WhatIsMyCQS.
            Reddit bot replies with current CQS score.

  Next 06:30 run: check_cqs_all_avatars (cqs_checker.py) reads the bot reply.
                  Updates avatar.cqs_level from "lowest" to "low" (or higher).
                  Commits to DB immediately.

  Next 08:15 run: build_and_generate_epg_all_avatars calls build_portfolio().
                  AttentionBudget.from_avatar() now returns budget > 0.
                  EPG generates slots -> LLM creates drafts -> executor receives emails.
                  Normal content pipeline resumes.

  Post-recovery: _get_cqs_check_interval() returns 30d (mature account) or 7d (young).
                 CQS check interval automatically switches from recovery (7d)
                 to stable (30d) because cqs_level is no longer "lowest".

Recovery cadence:
  - Worst case: 7 days to first CQS task + 2-3 days for executor + 1 day for read
    = ~10 days from restriction to recovery
  - Best case: CQS task already pending when restriction detected
    = ~2-3 days from restriction to recovery
"""

import uuid
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.avatar import Avatar
from app.models.execution_task import ExecutionTask
from app.services.execution_tasks import generate_task_code

logger = get_logger(__name__)

# Timezone
ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

# Interval constants (days)
INTERVAL_RECOVERY = 7       # CQS=lowest or young account -- recovery cadence
INTERVAL_STABLE = 30        # Mature account with good CQS -- routine refresh
YOUNG_ACCOUNT_DAYS = 90     # Accounts younger than this get accelerated checks

# Task defaults
CQS_TASK_DEADLINE_HOURS = 48
CQS_SUBREDDIT = "WhatIsMyCQS"
CQS_THREAD_URL = "https://reddit.com/r/WhatIsMyCQS/submit"
CQS_POST_TEXT = "What is my cqs?"


def _get_cqs_check_interval(avatar: Avatar) -> int:
    """Determine CQS check interval for an avatar (in days).

    Interval logic (self-healing recovery switch):
    - Recovery mode (7 days): CQS=lowest OR account < 90 days old.
      Checked frequently to detect improvement quickly.
    - Stable mode (30 days): Mature account (>=90d) with CQS above "lowest".
      Routine refresh to keep CQS data fresh.

    The switch from 7d -> 30d happens AUTOMATICALLY when:
    1. check_cqs_all_avatars detects CQS improvement (e.g. lowest -> low)
    2. Next time generate_cqs_check_tasks runs, this function returns 30
       (because cqs_level is no longer "lowest" and account is >=90d)
    3. The avatar won't get another CQS task for 30 days (stable cadence)

    This ensures recovered avatars stop getting unnecessary weekly checks.
    """
    # Recovery cadence: CQS=lowest means avatar is restricted, check often
    if getattr(avatar, "cqs_level", None) == "lowest":
        return INTERVAL_RECOVERY

    # Account age -- use created_at as approximation of Reddit account age
    account_age_days = (datetime.now(timezone.utc) - avatar.created_at).days if avatar.created_at else 999
    if account_age_days < YOUNG_ACCOUNT_DAYS:
        return INTERVAL_RECOVERY  # Young accounts are volatile, check weekly

    # Stable cadence: mature account with acceptable CQS
    return INTERVAL_STABLE


def _get_last_cqs_task_date(db: Session, avatar_id: uuid.UUID) -> datetime | None:
    """Get the creation date of the most recent CQS check task for an avatar."""
    result = (
        db.query(func.max(ExecutionTask.created_at))
        .filter(
            ExecutionTask.avatar_id == avatar_id,
            ExecutionTask.task_type == "cqs_check",
        )
        .scalar()
    )
    return result


def _has_pending_cqs_task(db: Session, avatar_id: uuid.UUID) -> bool:
    """Check if a pending (non-terminal) CQS check task exists for this avatar."""
    # All non-terminal statuses: a task is "pending" until it reaches
    # verified, failed, expired, or cancelled.
    pending_statuses = ("generated", "emailed", "accepted", "submitted", "url_verified", "content_verified")
    exists = (
        db.query(ExecutionTask.id)
        .filter(
            ExecutionTask.avatar_id == avatar_id,
            ExecutionTask.task_type == "cqs_check",
            ExecutionTask.status.in_(pending_statuses),
        )
        .first()
    )
    return exists is not None


def _create_cqs_execution_task(db: Session, avatar: Avatar) -> ExecutionTask | None:
    """Create a CQS check ExecutionTask for the given avatar.

    Returns the created task, or None on error.
    """
    # Scheduled at 07:05 Israel time (next occurrence)
    now_israel = datetime.now(ISRAEL_TZ)
    scheduled_local = now_israel.replace(hour=7, minute=5, second=0, microsecond=0)

    # If it's already past 07:05 today, schedule for tomorrow 07:05
    if now_israel > scheduled_local:
        scheduled_local = scheduled_local + timedelta(days=1)

    scheduled_utc = scheduled_local.astimezone(timezone.utc)

    # Deadline: scheduled_at + 48 hours
    deadline = scheduled_utc + timedelta(hours=CQS_TASK_DEADLINE_HOURS)

    # Resolve client
    client_id = None
    client_name = ""
    if avatar.client_ids:
        try:
            client_id = uuid.UUID(avatar.client_ids[0])
            from app.models.client import Client
            client = db.query(Client).filter(Client.id == client_id).first()
            client_name = client.client_name if client else ""
        except (ValueError, TypeError, IndexError):
            pass

    task = ExecutionTask(
        id=uuid.uuid4(),
        task_code=generate_task_code(db),
        executor_token=uuid.uuid4(),
        epg_slot_id=None,  # CQS tasks have no EPG slot
        draft_id=None,
        avatar_id=avatar.id,
        client_id=client_id,
        thread_id=None,
        executor_contact=avatar.executor_email,
        executor_type="avatar_owner",
        delivery_channel="email",
        task_type="cqs_check",
        subreddit=CQS_SUBREDDIT,
        thread_url=CQS_THREAD_URL,
        thread_title="CQS Health Check",
        avatar_username=avatar.reddit_username,
        client_name=client_name,
        generated_text=CQS_POST_TEXT,
        scheduled_at=scheduled_utc,
        deadline=deadline,
        status="generated",
        status_history=[{"status": "generated", "at": datetime.now(timezone.utc).isoformat(), "by": "cqs_task_generator"}],
        delivery_count=0,
    )

    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def generate_cqs_check_tasks(db: Session) -> dict:
    """Generate CQS check execution tasks for all eligible avatars.

    This is the "write" side of CQS monitoring. It creates tasks that prompt
    executors to post in r/WhatIsMyCQS. The "read" side (check_cqs_all_avatars
    at 06:30 daily) picks up bot replies and updates avatar.cqs_level.

    Together they form the self-healing loop:
      generate_cqs_check_tasks -> email -> executor posts -> bot replies
      -> check_cqs_all_avatars reads reply -> cqs_level updates
      -> AttentionBudget > 0 -> EPG generates slots -> pipeline resumes

    Eligibility (updated June 27, 2026 — removed is_frozen + health_status filters):
    - active=True
    - executor_email IS NOT NULL AND executor_email_verified=True
    - No pending CQS task exists
    - Last CQS task older than interval (or never created)

    NOTE: Frozen and shadowbanned avatars ARE included. They need CQS checks
    the most — it's the only way to detect recovery and trigger auto-unfreeze.

    Returns: {created: int, skipped_frozen: int, skipped_health: int,
              skipped_no_email: int, skipped_pending: int, skipped_interval: int,
              errors: int, duration_ms: int}
    """
    start_time = time.time()

    # Counters
    created = 0
    skipped_frozen = 0
    skipped_health = 0
    skipped_no_email = 0
    skipped_pending = 0
    skipped_interval = 0
    errors = 0

    # Query all active avatars (frozen check done in loop for accurate counting)
    avatars = (
        db.query(Avatar)
        .filter(
            Avatar.active == True,  # noqa: E712
        )
        .all()
    )

    for avatar in avatars:
        try:
            # NOTE (June 27, 2026): is_frozen and health_status filters REMOVED.
            # Frozen/shadowbanned avatars are exactly the ones that need CQS checks
            # to detect recovery. The deadlock where frozen avatars could never recover
            # (because CQS task was never generated) is now fixed.
            # See: Flaky_Finder_13 incident — CQS improved to LOW but RAMP never saw it.

            # Email requirement (R4.5)
            if not avatar.executor_email or not avatar.executor_email_verified:
                skipped_no_email += 1
                logger.debug(
                    "CQS_TASK_SKIP_NO_EMAIL | avatar=%s",
                    avatar.reddit_username,
                )
                continue

            # Pending task check -- max 1 active CQS task per avatar (R5.1, R5.2)
            if _has_pending_cqs_task(db, avatar.id):
                skipped_pending += 1
                continue

            # Interval check (R3, R5.3)
            interval_days = _get_cqs_check_interval(avatar)
            last_task_date = _get_last_cqs_task_date(db, avatar.id)

            if last_task_date:
                # Ensure timezone-aware comparison
                if last_task_date.tzinfo is None:
                    last_task_date = last_task_date.replace(tzinfo=timezone.utc)
                days_since = (datetime.now(timezone.utc) - last_task_date).days
                if days_since < interval_days:
                    skipped_interval += 1
                    continue

            # Create CQS task
            task = _create_cqs_execution_task(db, avatar)
            if task:
                created += 1
                logger.info(
                    "CQS_TASK_CREATED | avatar=%s | interval=%dd | task=%s",
                    avatar.reddit_username, interval_days, task.task_code,
                )

        except Exception as e:
            errors += 1
            logger.error(
                "CQS_TASK_GENERATOR_ERROR | avatar=%s | error=%s",
                avatar.reddit_username, str(e)[:200],
                exc_info=True,
            )
            db.rollback()

    duration_ms = int((time.time() - start_time) * 1000)

    summary = {
        "created": created,
        "skipped_frozen": skipped_frozen,
        "skipped_health": skipped_health,
        "skipped_no_email": skipped_no_email,
        "skipped_pending": skipped_pending,
        "skipped_interval": skipped_interval,
        "errors": errors,
        "duration_ms": duration_ms,
    }

    logger.info(
        "CQS_TASK_GENERATOR_COMPLETE | created=%d | skipped_frozen=%d | "
        "skipped_health=%d | skipped_no_email=%d | skipped_pending=%d | "
        "skipped_interval=%d | errors=%d | total=%d | duration_ms=%d",
        created, skipped_frozen, skipped_health, skipped_no_email,
        skipped_pending, skipped_interval, errors, len(avatars), duration_ms,
    )

    return summary
