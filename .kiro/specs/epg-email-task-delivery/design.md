# EPG Email Task Delivery — Technical Design (v2)

## Architecture Overview

```
EPG Slot (approved)
    |
    v
ExecutionTask (generated, executor_token assigned)
    |
    v
DeliveryAttempt (channel=email, attempt_number=1)
    |
    v
Celery: deliver_task --> Channel Router --> SMTP / Telegram / Push (future)
    |
    v
Executor receives --> Token link: /tasks/{code}/{token}
    |
    v
Executor accepts (status=accepted) --> Posts on Reddit --> Submits URL
    |
    v
Two-stage verification: url_verified --> content_verified --> verified
    |
    v
Update: draft.status=posted, slot.status=posted, draft.reddit_comment_url
```

### Key Design Decisions

1. **Two tables**: ExecutionTask (the what) + DeliveryAttempt (the how). Task is channel-agnostic; delivery is channel-specific.
2. **executor_token**: UUID4, enables passwordless task interaction. No login required for executors.
3. **Two-stage verification**: URL check first (immediate), content check second (may need Reddit indexing delay).
4. **Anti-spam at DB level**: resend_count + last delivery timestamp, checked before allowing new attempt.
5. **Soft cancel**: cancelled status with reason/timestamp. Never delete.
6. **No full body storage**: payload_hash + body_excerpt (200 chars) + template_version. Full body reconstructable.
7. **DB-level idempotency**: UNIQUE(epg_slot_id) on tasks, UNIQUE(task_id, attempt_number) on delivery attempts.
8. **Reconciliation fallback** (June 24): If executor posts but never submits permalink via action link, `draft_reconciliation.py` (runs every 4h in karma_tracking) auto-detects the posted comment on Reddit and transitions draft to "posted". Three matching passes: exact body (98% confidence), fuzzy body ≥85% overlap, thread+timing (75% confidence).

---

## Data Model

### ExecutionTask (table: `execution_tasks`)

```python
class ExecutionTask(Base):
    __tablename__ = "execution_tasks"

    id: Mapped[uuid.UUID]          # PK
    task_code: Mapped[str]         # UNIQUE, "TASK-20260619-001"
    executor_token: Mapped[uuid.UUID]  # UNIQUE, UUID4 for passwordless access

    # Source references (immutable after creation)
    epg_slot_id: Mapped[uuid.UUID]  # FK -> epg_slots.id, UNIQUE (one task per slot)
    draft_id: Mapped[uuid.UUID]     # FK -> comment_drafts.id
    avatar_id: Mapped[uuid.UUID]    # FK -> avatars.id
    client_id: Mapped[uuid.UUID]    # FK -> clients.id
    thread_id: Mapped[uuid.UUID]    # FK -> reddit_threads.id

    # Executor assignment
    executor_id: Mapped[uuid.UUID | None]  # FK -> users.id (nullable, for registered users)
    executor_contact: Mapped[str]          # email/phone/telegram handle
    executor_type: Mapped[str]             # "admin" | "avatar_owner" | "provider"
    delivery_channel: Mapped[str]          # "email" | "telegram" | "portal_push" (MVP: email)

    # Task content (denormalized snapshot — frozen at creation time)
    task_type: Mapped[str]          # "comment" | "post" | "reply"
    subreddit: Mapped[str]
    thread_url: Mapped[str]
    thread_title: Mapped[str]
    avatar_username: Mapped[str]
    client_name: Mapped[str]
    generated_text: Mapped[str]     # snapshot of draft text
    scheduled_at: Mapped[datetime | None]  # recommended execution time
    deadline: Mapped[datetime]      # must execute before this

    # Status lifecycle
    status: Mapped[str]             # generated|emailed|accepted|submitted|url_verified|content_verified|verified|failed|expired|needs_regeneration|cancelled
    status_changed_at: Mapped[datetime]
    status_history: Mapped[list]    # JSONB: [{"status": "...", "at": "...", "by": "..."}]

    # Delivery tracking (denormalized for quick access)
    latest_delivery_attempt_id: Mapped[uuid.UUID | None]  # FK -> delivery_attempts.id
    delivery_count: Mapped[int]     # total attempts (max 3+1 initial)
    last_delivered_at: Mapped[datetime | None]

    # Verification
    submitted_url: Mapped[str | None]
    verified_at: Mapped[datetime | None]
    verification_result: Mapped[dict | None]  # JSONB: {"stage1": {...}, "stage2": {...}}
    failure_reason: Mapped[str | None]

    # Cancellation (soft delete)
    cancelled_at: Mapped[datetime | None]
    cancel_reason: Mapped[str | None]

    # Timestamps
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    # Future fields (present in schema, nullable, unused in MVP)
    provider_id: Mapped[uuid.UUID | None]   # FK -> providers.id (future)
    cost_per_task: Mapped[float | None]     # Numeric, for payout (future)
    resource_type: Mapped[str | None]       # "owned_avatar" | "managed_avatar" | "provider_avatar" (future)
```

### DeliveryAttempt (table: `delivery_attempts`)

```python
class DeliveryAttempt(Base):
    __tablename__ = "delivery_attempts"

    id: Mapped[uuid.UUID]            # PK
    task_id: Mapped[uuid.UUID]       # FK -> execution_tasks.id
    attempt_number: Mapped[int]      # 1, 2, 3... UNIQUE(task_id, attempt_number)

    # Channel
    channel: Mapped[str]             # "email" | "telegram" | "portal_push"
    recipient: Mapped[str]           # email address / telegram chat_id / user_id

    # Delivery result
    status: Mapped[str]              # "pending" | "sent" | "failed" | "bounced"
    sent_at: Mapped[datetime | None]
    error: Mapped[str | None]        # error message if failed

    # Provider tracking
    provider_message_id: Mapped[str | None]  # SMTP Message-ID / Telegram msg_id
    provider_response: Mapped[str | None]    # raw response snippet

    # Content audit (NOT full body)
    subject: Mapped[str | None]
    template_version: Mapped[str]    # "v1", "v2" etc
    payload_hash: Mapped[str]        # SHA-256 of rendered body
    body_excerpt: Mapped[str | None] # first 200 chars for debugging

    # Timestamps
    created_at: Mapped[datetime]
```

### Indexes

**execution_tasks:**
- `UNIQUE(epg_slot_id)` — one task per slot (idempotency)
- `UNIQUE(task_code)` — human lookup
- `UNIQUE(executor_token)` — token access
- `ix_execution_tasks_status` — status filtering
- `ix_execution_tasks_executor_status` — per-executor queries
- `ix_execution_tasks_deadline_active` — expiry scan (partial: status NOT IN verified, expired, failed, cancelled)
- `ix_execution_tasks_client_created` — client reporting

**delivery_attempts:**
- `UNIQUE(task_id, attempt_number)` — Celery idempotency
- `ix_delivery_attempts_task_id` — per-task lookup
- `ix_delivery_attempts_status_sent` — delivery metrics

---

## SMTP Configuration

### Storage: system_settings table

| Key | Value | Notes |
|-----|-------|-------|
| smtp_host | mail.gorampit.com | |
| smtp_port | 587 | |
| smtp_user | tasks@gorampit.com | |
| smtp_password | (Fernet encrypted) | Same encryption as reddit app passwords |
| smtp_from_email | tasks@gorampit.com | |
| smtp_from_name | RAMP Task System | |
| smtp_use_tls | true | |
| email_tasks_enabled | false | Feature flag (default off) |
| email_tasks_default_recipient | max@gorampit.com | Fallback if no executor assigned |
| email_tasks_max_resends | 3 | Anti-spam |
| email_tasks_cooldown_minutes | 10 | Anti-spam |

---

## Service Layer

### `app/services/email_sender.py` — Channel: Email

```python
def send_email(
    to: str,
    subject: str,
    body_html: str,
    body_text: str,
    headers: dict[str, str] | None = None,
    reply_to: str | None = None,
) -> tuple[bool, str | None]:
    """Send email via SMTP.
    Returns: (success: bool, message_id: str | None)
    """
```

### `app/services/execution_tasks.py` — Core Business Logic

```python
def create_execution_task(db, epg_slot_id, executor_contact=None, executor_type="admin") -> ExecutionTask | None:
    """Create task from approved slot. Idempotent (UNIQUE constraint on epg_slot_id)."""

def dispatch_delivery(db, task_id, force=False) -> DeliveryAttempt | None:
    """Create delivery attempt and dispatch via appropriate channel.
    Respects anti-spam (max_resends, cooldown). force=True bypasses for admin."""

def accept_task(db, task_id, executor_token) -> bool:
    """Executor accepts task via token. Status: emailed -> accepted."""

def submit_url(db, task_id, executor_token, reddit_url) -> ExecutionTask:
    """Executor submits Reddit URL. Status: accepted -> submitted."""

def cancel_task(db, task_id, reason) -> ExecutionTask:
    """Admin cancels task. Status -> cancelled, never deleted."""

def expire_overdue_tasks(db) -> int:
    """Bulk expire tasks past deadline. Called by Celery Beat."""

def get_sla_metrics(db, period_days=30, executor_id=None, client_id=None) -> dict:
    """Compute SLA metrics from stored data."""
```

### `app/services/task_verification.py` — Two-Stage Verification

```python
@dataclass
class VerificationResult:
    stage: str                   # "url" | "content" | "full"
    passed: bool
    checks: dict[str, bool]
    match_score: float | None
    failure_reason: str | None
    reddit_comment_url: str | None

def verify_stage1_url(task: ExecutionTask, reddit_url: str) -> VerificationResult:
    """Stage 1: URL exists, accessible, correct subreddit, correct author."""

def verify_stage2_content(task: ExecutionTask, reddit_url: str) -> VerificationResult:
    """Stage 2: Text similarity, not deleted, not removed."""

def verify_full(db, task_id, reddit_url: str) -> VerificationResult:
    """Run both stages. Update task status accordingly.
    - Both pass: task -> verified, draft -> posted, slot -> posted
    - Stage 1 passes, Stage 2 fails: task -> url_verified (retry later)
    - Stage 1 fails: task stays submitted, return failure
    """
```

---

## Celery Tasks

### `app/tasks/execution_tasks.py`

```python
@shared_task(name="deliver_execution_task", bind=True, max_retries=3)
def deliver_execution_task(self, task_id: str, attempt_number: int):
    """Deliver task via configured channel. Retry on failure."""
    # countdown = 60 * 2^attempt (60, 120, 240s)

@shared_task(name="expire_overdue_execution_tasks")
def expire_overdue_execution_tasks():
    """Beat: daily 23:30. Expire tasks past deadline."""

@shared_task(name="retry_content_verification")
def retry_content_verification(task_id: str):
    """Retry Stage 2 verification for tasks stuck at url_verified.
    Beat: every 2 hours, checks tasks in url_verified status older than 1h."""
```

### Beat Schedule

```python
"expire_overdue_execution_tasks": {
    "task": "expire_overdue_execution_tasks",
    "schedule": crontab(hour=23, minute=30),
},
"retry_content_verification": {
    "task": "retry_content_verification",
    "schedule": crontab(minute=0, hour="*/2"),  # every 2h
},
```

---

## Executor Token Flow

### Token Link Structure
```
https://gorampit.com/tasks/TASK-20260619-003/a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

### Token Endpoints (public, no auth required)

| Method | Path | Action |
|--------|------|--------|
| GET | /tasks/{task_code}/{token} | View task details (read-only) |
| POST | /tasks/{task_code}/{token}/accept | Accept task (status -> accepted) |
| POST | /tasks/{task_code}/{token}/submit | Submit Reddit URL |

### Security
- Token is UUID4 (122 bits of entropy, not guessable)
- Rate limited: 10 req/min per token (same middleware pattern as auth endpoints)
- Token does NOT grant access to other tasks or system data
- Expired/cancelled tasks return 410 Gone

---

## Email Template

### Subject
```
[RAMP Task] XM Cyber / Hot-Thought2408 / r/cybersecurity / Comment / 18:30
```

### Body (plain text primary, HTML optional)

```
RAMP EXECUTION TASK
====================

Task:           TASK-20260619-003
Client:         XM Cyber
Avatar:         u/Hot-Thought2408
Subreddit:      r/cybersecurity
Type:           Comment (top-level)
Priority:       High

THREAD
------
Title:  "Best practices for lateral movement detection in 2026?"
URL:    https://reddit.com/r/cybersecurity/comments/abc123/...
Score:  47 upvotes | 23 comments

TIMING
------
Post at:   18:30 Israel Time (today)
Deadline:  22:30 Israel Time (today)

COMMENT TO POST
---------------
[generated comment text here]

ACTION LINK
-----------
Accept & submit result:
https://gorampit.com/tasks/TASK-20260619-003/a1b2c3d4-e5f6-...

INSTRUCTIONS
------------
1. Click the action link above to accept the task
2. Log in to Reddit as u/Hot-Thought2408
3. Navigate to the thread URL
4. Post the comment (minor wording adjustments OK)
5. Copy your posted comment permalink
6. Submit the permalink via the action link

---
Task Code: TASK-20260619-003
Do not forward this email.
```

---

## Hook Point: EPG Slot Approval

### Injection Points

1. `app/routes/review.py` — admin approves draft
2. `app/routes/portal.py` — client approves from portal

### Logic (after existing approval code)

```python
from app.services.settings import get_setting

if get_setting(db, "email_tasks_enabled") == "true":
    from app.services.execution_tasks import create_execution_task, dispatch_delivery
    task = create_execution_task(db, slot.id)
    if task and task.status == "generated":
        deliver_execution_task.delay(str(task.id), 1)
```

### Coexistence with Automated Posting

Both paths can fire for the same slot:
- `email_tasks_enabled=true` -> creates ExecutionTask + sends email
- `execute_pending_posts` Celery Beat -> attempts automated posting (if proxy configured)

Whichever succeeds first wins:
- If automated posting succeeds: slot.status=posted, draft.status=posted. ExecutionTask auto-expires (deadline check finds slot already posted).
- If executor submits URL first: verification marks posted. Automated posting safety gate sees slot.status=posted, skips.

---

## Admin Routes

### `app/routes/admin_tasks.py`

| Method | Path | Description |
|--------|------|-------------|
| GET | /admin/tasks | Task list (filter: status, date, executor, client) |
| GET | /admin/tasks/{task_id} | Task detail + delivery log + verification form |
| POST | /admin/tasks/{task_id}/resend | Resend delivery (HTMX, anti-spam checked) |
| POST | /admin/tasks/{task_id}/verify | Submit URL + run verification (HTMX) |
| POST | /admin/tasks/{task_id}/cancel | Cancel with reason (HTMX) |
| GET | /admin/tasks/metrics | SLA metrics dashboard |

### `app/routes/executor_tasks.py` (public, token-protected)

| Method | Path | Description |
|--------|------|-------------|
| GET | /tasks/{code}/{token} | View task (no login) |
| POST | /tasks/{code}/{token}/accept | Accept task |
| POST | /tasks/{code}/{token}/submit | Submit Reddit URL |

---

## Anti-Spam Implementation

```python
def can_resend(db, task: ExecutionTask) -> tuple[bool, str | None]:
    """Check anti-spam limits before allowing resend."""
    max_resends = int(get_setting(db, "email_tasks_max_resends") or "3")
    cooldown_min = int(get_setting(db, "email_tasks_cooldown_minutes") or "10")

    if task.delivery_count >= max_resends + 1:  # +1 for initial send
        return False, f"Maximum resends ({max_resends}) reached"

    if task.last_delivered_at:
        elapsed = (now() - task.last_delivered_at).total_seconds() / 60
        if elapsed < cooldown_min:
            return False, f"Cooldown: wait {cooldown_min - int(elapsed)} more minutes"

    return True, None
```

---

## Verification Flow (Two-Stage Detail)

```python
def verify_full(db, task_id, reddit_url):
    task = db.query(ExecutionTask).get(task_id)

    # Stage 1: URL verification
    result1 = verify_stage1_url(task, reddit_url)
    if not result1.passed:
        task.status = "failed"
        task.failure_reason = result1.failure_reason
        return result1

    task.status = "url_verified"
    task.submitted_url = reddit_url

    # Stage 2: Content verification
    result2 = verify_stage2_content(task, reddit_url)
    if not result2.passed:
        # Stay at url_verified — Reddit may need indexing time
        task.status = "url_verified"  # don't regress
        task.verification_result = {"stage1": result1.checks, "stage2": result2.checks}
        return result2  # caller can schedule retry

    # Both stages passed
    task.status = "verified"
    task.verified_at = now()
    task.verification_result = {"stage1": result1.checks, "stage2": result2.checks, "match_score": result2.match_score}

    # Update downstream
    draft = db.query(CommentDraft).get(task.draft_id)
    draft.status = "posted"
    draft.reddit_comment_url = result2.reddit_comment_url
    draft.posted_at = now()

    slot = db.query(EPGSlot).get(task.epg_slot_id)
    slot.status = "posted"
    slot.posted_at = now()

    db.commit()
    return result2
```

---

## SLA Metrics (computed from stored data)

```python
def get_sla_metrics(db, period_days=30, executor_id=None, client_id=None) -> dict:
    """All metrics derived from execution_tasks + delivery_attempts tables.
    No separate aggregation table needed for MVP."""
    return {
        "task_accept_rate": accepted_count / emailed_count,
        "task_submit_rate": submitted_count / accepted_count,
        "verification_pass_rate": verified_count / submitted_count,
        "median_execution_time_minutes": median(submitted_at - emailed_at),
        "email_delivery_success_rate": sent_attempts / total_attempts,
        "expired_task_rate": expired_count / total_count,
        "period_days": period_days,
        "total_tasks": total_count,
    }
```

---

## Dependencies

- **No new pip packages** — stdlib: smtplib, email.mime, difflib, hashlib
- **Existing**: SQLAlchemy, Celery, PRAW (read-only), Fernet encryption
- **Alembic**: single migration (2 new tables)

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| SMTP unreachable | DeliveryAttempt.status=failed, Celery retries 3x. Task stays generated. |
| Duplicate slot approval | UNIQUE(epg_slot_id) returns existing task (no error, idempotent) |
| Celery duplicate delivery | UNIQUE(task_id, attempt_number) rejects duplicate INSERT |
| Invalid executor_token | 404 response, no data exposed |
| Expired token link | 410 Gone response |
| Reddit API timeout during verify | Task stays at current status, admin can retry |
| Stage 2 content not indexed yet | Task stays url_verified, auto-retry in 2h |
| Anti-spam limit hit | 429 response with Retry-After header |
| Cancelled task resend attempt | Rejected (terminal state) |

---

## Migration Plan

Single Alembic migration:
1. Create `execution_tasks` table
2. Create `delivery_attempts` table
3. Add all indexes and constraints
4. Seed system_settings with SMTP config keys (empty values)
