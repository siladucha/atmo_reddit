# EPG Email Task Delivery — Implementation Tasks (v2)

## Task 1: Data Model + Migration

**Status:** not started
**Effort:** 2 hours

### Subtasks
- [ ] Create `app/models/execution_task.py` — ExecutionTask model (all fields from design v2)
- [ ] Create `app/models/delivery_attempt.py` — DeliveryAttempt model
- [ ] Add model imports to `app/models/__init__.py`
- [ ] Create Alembic migration: `alembic revision --autogenerate -m "add_execution_tasks_and_delivery_attempts"`
- [ ] Add DB constraints:
  - UNIQUE(epg_slot_id) on execution_tasks
  - UNIQUE(task_code) on execution_tasks
  - UNIQUE(executor_token) on execution_tasks
  - UNIQUE(task_id, attempt_number) on delivery_attempts
- [ ] Add indexes:
  - ix_execution_tasks_status
  - ix_execution_tasks_executor_status (executor_id, status)
  - ix_execution_tasks_deadline_active (partial: status NOT IN terminal states)
  - ix_execution_tasks_client_created (client_id, created_at)
  - ix_delivery_attempts_task_id
  - ix_delivery_attempts_status_sent (status, sent_at)
- [ ] Run migration locally, verify both tables + constraints
- [ ] Seed system_settings with SMTP config keys (empty values) + feature flags

### Model Notes
- executor_token: UUID4, generated at task creation, never changes
- status_history: JSONB array of {status, at, by} entries
- Future fields (provider_id, cost_per_task, resource_type) present but nullable
- delivery_channel defaults to "email" for MVP

---

## Task 2: SMTP Email Sender (Channel: Email)

**Status:** not started
**Effort:** 1.5 hours

### Subtasks
- [ ] Create `app/services/email_sender.py`
- [ ] Implement `send_email(to, subject, body_html, body_text, headers, reply_to) -> (bool, str|None)`
- [ ] Support STARTTLS (port 587) and SMTP_SSL (port 465)
- [ ] Load SMTP config from system_settings via get_config()
- [ ] Decrypt smtp_password via existing Fernet encryption
- [ ] Add custom headers: X-RAMP-Task-ID, X-RAMP-Task-Code
- [ ] Return (success, message_id) tuple
- [ ] Log every attempt: success/failure + recipient + subject (no body)
- [ ] Handle: connection timeout, auth failure, recipient rejected
- [ ] Test: send test email to verify GoRampIT SMTP connectivity

### Notes
- stdlib only: smtplib, email.mime.multipart, email.mime.text, email.utils
- No new pip dependencies
- Pattern matches existing encryption service usage

---

## Task 3: Execution Task Service (Core Logic)

**Status:** not started
**Effort:** 3 hours

### Subtasks
- [ ] Create `app/services/execution_tasks.py`
- [ ] `generate_task_code(db)` — daily sequential counter: TASK-YYYYMMDD-NNN
- [ ] `create_execution_task(db, epg_slot_id, executor_contact, executor_type)` — idempotent (catches IntegrityError on UNIQUE)
- [ ] `dispatch_delivery(db, task_id, force=False)` — create DeliveryAttempt, check anti-spam, call channel
- [ ] `compose_task_email(task)` — returns (subject, body_text, body_html) from task data
- [ ] `accept_task(db, task_id, executor_token)` — validate token, transition emailed -> accepted
- [ ] `submit_url(db, task_id, executor_token, reddit_url)` — validate token, transition accepted -> submitted
- [ ] `cancel_task(db, task_id, reason)` — soft cancel with reason + timestamp
- [ ] `expire_overdue_tasks(db)` — bulk update past-deadline active tasks -> expired
- [ ] `can_resend(db, task)` — anti-spam check: max_resends + cooldown
- [ ] `get_sla_metrics(db, period_days, executor_id, client_id)` — compute from stored data

### Anti-Spam Logic
```
max_resends = int(get_setting("email_tasks_max_resends") or "3")
cooldown = int(get_setting("email_tasks_cooldown_minutes") or "10")
if task.delivery_count > max_resends: reject
if last_delivered_at + cooldown > now: reject
```

### Status Transition Rules
- generated -> emailed (on successful delivery)
- emailed -> accepted (executor clicks accept via token)
- accepted -> submitted (executor submits URL)
- submitted -> url_verified (Stage 1 passes)
- url_verified -> content_verified -> verified (Stage 2 passes)
- any active -> expired (deadline passed)
- any active -> cancelled (admin cancels)
- any active -> failed (verification hard failure)
- Terminal states (no transitions out): verified, expired, cancelled, failed

---

## Task 4: Two-Stage Verification Service

**Status:** not started
**Effort:** 2.5 hours

### Subtasks
- [ ] Create `app/services/task_verification.py`
- [ ] `parse_reddit_url(url)` — extract subreddit + comment_id from various URL formats
  - www.reddit.com/r/{sub}/comments/{post_id}/{slug}/{comment_id}/
  - reddit.com/r/...
  - old.reddit.com/r/...
  - redd.it/{id} (short URLs)
- [ ] `verify_stage1_url(task, reddit_url)` — PRAW fetch, check: exists, accessible, correct subreddit, correct author
- [ ] `verify_stage2_content(task, reddit_url)` — check: text similarity >60%, not [removed], not [deleted]
- [ ] `verify_full(db, task_id, reddit_url)` — orchestrates both stages, updates status chain
- [ ] Text similarity: `difflib.SequenceMatcher` with whitespace normalization
- [ ] Handle Reddit indexing delay: if Stage 2 fails on fresh post, stay url_verified (auto-retry)
- [ ] Update downstream on full verification: draft.status=posted, slot.status=posted, draft.reddit_comment_url

### VerificationResult dataclass
```python
@dataclass
class VerificationResult:
    stage: str          # "url" | "content" | "full"
    passed: bool
    checks: dict        # {"exists": True, "author_match": True, ...}
    match_score: float | None
    failure_reason: str | None
    reddit_comment_url: str | None
```

---

## Task 5: Celery Tasks + Beat Schedule

**Status:** not started
**Effort:** 1.5 hours

### Subtasks
- [ ] Create `app/tasks/execution_tasks.py`
- [ ] `deliver_execution_task(task_id, attempt_number)` — shared_task, bind=True, max_retries=3, countdown=60*2^attempt
- [ ] `expire_overdue_execution_tasks()` — Beat: daily 23:30
- [ ] `retry_content_verification()` — Beat: every 2h, retries tasks stuck at url_verified >1h
- [ ] Register all tasks in `app/tasks/worker.py`
- [ ] Add Beat schedule entries
- [ ] Test: verify retry on SMTP failure, verify expiry logic

### Beat Schedule Additions
| Time | Task | Purpose |
|------|------|---------|
| 23:30 daily | expire_overdue_execution_tasks | Auto-expire past deadline |
| every 2h | retry_content_verification | Retry Stage 2 for url_verified tasks |

---

## Task 6: Approval Hook (EPG -> ExecutionTask)

**Status:** not started
**Effort:** 1 hour

### Subtasks
- [ ] Identify approval points in: `app/routes/review.py`, `app/routes/portal.py`
- [ ] After slot.status = "approved": check email_tasks_enabled setting
- [ ] If enabled: `create_execution_task(db, slot.id)` + `deliver_execution_task.delay(task.id, 1)`
- [ ] Handle coexistence with automated posting:
  - Both can fire for same slot
  - Whichever completes first wins (safety gate in automated posting checks slot.status)
  - expire_overdue_tasks handles the losing path
- [ ] Test: approve slot -> verify task created + email queued

### Coexistence Guard
The automated posting `execute_pending_posts` already checks `slot.status == "approved"`. Once verification marks slot as "posted", automated posting skips it. No additional guard needed.

---

## Task 7: Executor Token Routes (Public)

**Status:** not started
**Effort:** 2 hours

### Subtasks
- [ ] Create `app/routes/executor_tasks.py`
- [ ] GET `/tasks/{task_code}/{token}` — view task details (no login required)
- [ ] POST `/tasks/{task_code}/{token}/accept` — accept task
- [ ] POST `/tasks/{task_code}/{token}/submit` — submit Reddit URL
- [ ] Rate limiting: 10 req/min per token (reuse existing RateLimitMiddleware pattern)
- [ ] Security: validate token matches task, check task not expired/cancelled
- [ ] Return 410 Gone for expired/cancelled tasks
- [ ] Return 404 for invalid token (do not reveal task existence)
- [ ] Create minimal templates: `executor_task_view.html`, `executor_task_submitted.html`
- [ ] Register routes in main.py

### Template Style
- Light theme (extends base.html or standalone minimal)
- Mobile-friendly (executor may be on phone)
- Shows: task details, comment text, thread link, submit form
- No navigation/sidebar (standalone page)

---

## Task 8: Admin UI — Task Management

**Status:** not started
**Effort:** 2.5 hours

### Subtasks
- [ ] Create `app/routes/admin_tasks.py`
- [ ] GET `/admin/tasks` — list with filters (status, date, executor, client)
- [ ] GET `/admin/tasks/{task_id}` — detail page with delivery log
- [ ] POST `/admin/tasks/{task_id}/resend` — resend delivery (HTMX, anti-spam)
- [ ] POST `/admin/tasks/{task_id}/verify` — submit URL + verify (HTMX)
- [ ] POST `/admin/tasks/{task_id}/cancel` — cancel with reason (HTMX)
- [ ] GET `/admin/tasks/metrics` — SLA metrics dashboard
- [ ] Create templates:
  - `admin_tasks.html` — task list (dark theme, extends admin_base.html)
  - `admin_task_detail.html` — full detail + actions
  - `partials/execution_task_row.html` — HTMX row
  - `partials/delivery_log.html` — delivery attempt history
  - `partials/sla_metrics.html` — metrics cards
- [ ] Add "Execution Tasks" link to admin sidebar navigation
- [ ] Register routes in main.py
- [ ] Status badges: green=verified, blue=emailed/accepted, yellow=submitted/url_verified, red=failed/expired, gray=cancelled

---

## Task 9: Integration Testing + Documentation

**Status:** not started
**Effort:** 2 hours

### Subtasks
- [ ] End-to-end manual test: approve slot -> email arrives -> open token link -> accept -> submit URL -> verified
- [ ] Test SMTP with GoRampIT.com (or fallback SMTP for dev)
- [ ] Test idempotency: approve same slot twice (should return same task)
- [ ] Test Celery duplicate: dispatch same attempt_number twice (DB rejects)
- [ ] Test anti-spam: resend 4 times (4th rejected), resend within cooldown (rejected)
- [ ] Test expiry: create task with past deadline, run expire task
- [ ] Test two-stage verification: URL valid but content not yet indexed
- [ ] Test token security: wrong token returns 404, expired returns 410
- [ ] Test cancellation: cancel task, verify terminal state, verify resend rejected
- [ ] Add SMTP config to deployment docs
- [ ] Add email_tasks_enabled to System Settings admin UI
- [ ] Document token link flow for executors

---

## Implementation Order

```
Task 1 (Model + Migration)
    |
    v
Task 2 (SMTP Sender) ----+----> Task 3 (Core Service)
                          |          |
                          |          v
                          |     Task 4 (Verification)
                          |          |
                          v          v
                     Task 5 (Celery Tasks)
                          |
                          v
                     Task 6 (Approval Hook)
                          |
              +-----------+-----------+
              |                       |
              v                       v
    Task 7 (Token Routes)    Task 8 (Admin UI)
              |                       |
              +-----------+-----------+
                          |
                          v
                     Task 9 (Testing)
```

---

## Total Estimated Effort

| Task | Effort | Dependencies |
|------|--------|-------------|
| 1. Model + Migration | 2h | None |
| 2. SMTP Sender | 1.5h | None |
| 3. Core Service | 3h | Task 1 |
| 4. Verification | 2.5h | Task 1 |
| 5. Celery Tasks | 1.5h | Tasks 2, 3, 4 |
| 6. Approval Hook | 1h | Tasks 3, 5 |
| 7. Token Routes | 2h | Tasks 3, 4 |
| 8. Admin UI | 2.5h | Tasks 3, 4, 5 |
| 9. Testing | 2h | All |
| **Total** | **18 hours** | |

---

## Risks + Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| GoRampIT SMTP not configured | Blocks email delivery | Test early (Task 2). Fallback to any SMTP for dev. |
| Reddit indexing delay on new comments | Stage 2 verification fails | Two-stage design handles this: url_verified + auto-retry every 2h |
| Executor ignores email | Task expires | SLA metrics track accept_rate. Future: Telegram channel. |
| Token link guessed/leaked | Unauthorized task access | UUID4 = 122 bits entropy. Rate limit. No sensitive data beyond task. |
| Anti-spam too strict for ops | Admin can't resend urgently | force=True bypass for admin (separate from executor anti-spam) |
| Race: auto-posting wins before executor | Executor does redundant work | Executor sees slot already posted (token page shows "completed"). No harm. |
| Celery retry creates duplicate DeliveryAttempt | Extra emails sent | UNIQUE(task_id, attempt_number) prevents duplicate INSERT |
| SMTP password rotation | Email stops working | Admin-changeable via System Settings UI (no redeploy) |
