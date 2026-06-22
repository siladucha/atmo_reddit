# EPG Email Task Delivery — Requirements (v2)

## Overview

RAMP generates actionable EPG tasks and delivers them to human executors via a channel-agnostic delivery system (email MVP, Telegram/Portal/Push later). The executor posts manually on Reddit, then RAMP verifies the outcome via a two-stage process. This creates a minimal human execution layer — the first step toward a resource allocation marketplace.

## Motivation

- Automated posting requires proxies, OAuth, per-avatar credentials — not yet fully operational for all avatars
- Provider/marketplace model requires task delivery to external humans who don't have admin access
- Email is the first delivery channel, but architecture must not be coupled to it
- Creates the execution abstraction layer (EPG as Resource Allocation Engine)

## Actors

- **System (RAMP/EPG)** — generates tasks, delivers via channels, tracks status, verifies outcomes
- **Executor** — receives task (via email/telegram/portal), posts on Reddit manually, submits result URL via token link
- **Admin** — monitors task status, can resend/reassign/expire/cancel tasks, verifies manually

---

## Functional Requirements

### FR-1: Task Generation from EPG Slots

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1.1 | When an EPG slot reaches approved status, system SHALL create an ExecutionTask record | P0 |
| FR-1.2 | ExecutionTask SHALL reference the source EPG slot, draft, avatar, client, and thread | P0 |
| FR-1.3 | ExecutionTask SHALL have a unique human-readable task_code (e.g. TASK-20260619-001) | P0 |
| FR-1.4 | ExecutionTask SHALL have a unique executor_token (UUID4) for passwordless access | P0 |
| FR-1.5 | ExecutionTask SHALL have a deadline (default: scheduled_at + 4 hours) | P1 |
| FR-1.6 | System SHALL NOT create duplicate tasks for the same EPG slot (enforced by DB UNIQUE constraint) | P0 |
| FR-1.7 | ExecutionTask SHALL store executor assignment (executor_id, executor_contact, executor_type) | P0 |

### FR-2: Delivery (Channel-Agnostic)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-2.1 | Each delivery attempt SHALL be recorded in a separate DeliveryAttempt record | P0 |
| FR-2.2 | DeliveryAttempt SHALL store: channel, recipient, status, sent_at, error, provider_message_id | P0 |
| FR-2.3 | MVP channel: email via GoRampIT.com SMTP. Future: telegram, portal_push, whatsapp | P0 |
| FR-2.4 | Email subject SHALL follow format: [RAMP Task] {Client} / {Avatar} / r/{subreddit} / {type} / {time} | P0 |
| FR-2.5 | Email body SHALL include: client name, avatar username, task_code, recommended time, subreddit, thread URL, task type, generated text, risk/priority, deadline, tokenized action link | P0 |
| FR-2.6 | Delivery SHALL be async (Celery task with retry on channel failure) | P0 |
| FR-2.7 | System SHALL NOT store full rendered body. Store: subject, template_version, payload_hash, body_excerpt (first 200 chars) | P0 |
| FR-2.8 | Email SHALL contain X-RAMP-Task-ID header and stable Message-ID for future inbound parsing | P1 |
| FR-2.9 | SMTP credentials SHALL come from DB (system_settings), encrypted via Fernet. Never hardcoded. | P0 |
| FR-2.10 | Idempotency: UNIQUE(task_id, attempt_number) prevents Celery duplicate delivery | P0 |

### FR-3: Anti-Spam Protection

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-3.1 | Maximum resend count per task: 3 (configurable) | P0 |
| FR-3.2 | Minimum cooldown between resends: 10 minutes | P0 |
| FR-3.3 | System SHALL reject resend if cooldown not elapsed | P0 |

### FR-4: Task Status Lifecycle

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-4.1 | Statuses: generated -> emailed -> accepted -> submitted -> url_verified -> content_verified -> verified / failed / expired / needs_regeneration / cancelled | P0 |
| FR-4.2 | Every status transition SHALL record: new_status, changed_at, changed_by (system/admin/executor) | P0 |
| FR-4.3 | Tasks not completed by deadline SHALL transition to expired automatically | P1 |
| FR-4.4 | Admin SHALL be able to cancel a task (cancelled + cancel_reason + cancelled_at). Tasks are NEVER deleted. | P0 |
| FR-4.5 | Executor SHALL be able to accept a task via token link (status -> accepted) | P1 |

### FR-5: Executor Token Access

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-5.1 | Each task SHALL have a unique executor_token (UUID4) | P0 |
| FR-5.2 | Token link format: /tasks/{task_code}/{executor_token} | P0 |
| FR-5.3 | Token link SHALL allow: view task details, accept task, submit Reddit URL — without login | P0 |
| FR-5.4 | Token SHALL be included in every email body as an action link | P0 |
| FR-5.5 | Token access SHALL be rate-limited (10 requests per minute per token) | P1 |

### FR-6: Two-Stage Verification

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-6.1 | Stage 1 (URL verification): URL exists, is accessible, correct subreddit, correct author | P0 |
| FR-6.2 | Stage 2 (Content verification): text similarity >60%, not deleted, not removed | P0 |
| FR-6.3 | Stages may run sequentially or together depending on Reddit API availability | P0 |
| FR-6.4 | If Stage 1 passes but Stage 2 fails (e.g. Reddit indexing delay): task stays url_verified, retry content check later | P0 |
| FR-6.5 | On full verification: task -> verified, draft -> posted, EPG slot -> posted, draft.reddit_comment_url updated | P0 |
| FR-6.6 | On failure: task -> failed with failure_reason. Allow retry (admin can re-submit URL). | P0 |
| FR-6.7 | Verification SHALL use existing PRAW read-only flow | P0 |

### FR-7: Admin UI

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-7.1 | Admin SHALL see list of all execution tasks with status, executor, deadline, delivery attempts | P0 |
| FR-7.2 | Admin SHALL be able to resend delivery (within anti-spam limits) | P0 |
| FR-7.3 | Admin SHALL be able to submit verification URL for a task | P0 |
| FR-7.4 | Admin SHALL be able to cancel a task with reason | P0 |
| FR-7.5 | Admin SHALL see delivery attempt log per task | P1 |
| FR-7.6 | Admin SHALL see SLA metrics dashboard (accept_rate, submit_rate, verification_pass_rate, median_execution_time) | P2 |

### FR-8: SLA Metrics

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-8.1 | System SHALL track: task_accept_rate (accepted / emailed) | P1 |
| FR-8.2 | System SHALL track: task_submit_rate (submitted / accepted) | P1 |
| FR-8.3 | System SHALL track: verification_pass_rate (verified / submitted) | P1 |
| FR-8.4 | System SHALL track: median_execution_time (emailed_at -> submitted_at) | P1 |
| FR-8.5 | System SHALL track: email_delivery_success_rate (successful attempts / total attempts) | P1 |
| FR-8.6 | System SHALL track: expired_task_rate (expired / total) | P1 |
| FR-8.7 | Metrics SHALL be computable per executor, per client, per avatar, per time period | P2 |

---

## Non-Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| NFR-1 | Delivery latency: < 30 seconds from task creation to delivery attempt | P1 |
| NFR-2 | SMTP connection SHALL use TLS (STARTTLS or SSL) | P0 |
| NFR-3 | Failed delivery SHALL retry 3x with exponential backoff (60, 120, 240s) | P0 |
| NFR-4 | System SHALL handle channel unavailability gracefully (task stays generated, retry later) | P0 |
| NFR-5 | Feature SHALL be togglable via system setting email_tasks_enabled | P0 |
| NFR-6 | No task records SHALL ever be deleted (soft state: cancelled/expired/failed are terminal) | P0 |
| NFR-7 | executor_token SHALL be cryptographically random (uuid4), not guessable | P0 |

---

## Out of Scope (MVP)

- Inbound email reply parsing
- Provider self-service portal (beyond token link)
- Payout calculation
- Task reassignment to different executor
- Telegram/WhatsApp delivery channels (architecture supports, not implemented)
- Batch digest emails
- Mobile push notifications
- Automated retry of content verification

---

## Future Compatibility (architecture supports now, implements later)

- delivery_channel: email | telegram | portal_push | whatsapp | sms
- executor_type: admin | avatar_owner | provider | client_user
- resource_type: owned_avatar | managed_avatar | provider_avatar
- cost_per_task: Decimal (payout calculation)
- provider_id: FK to future Provider table
- Task reassignment (new executor, new delivery)
- SLA-based executor scoring (reliability ranking)
- EPG resource allocation weights based on executor performance

---

## Acceptance Criteria

1. Approving an EPG slot creates an ExecutionTask with executor_token and all required fields
2. DeliveryAttempt record created, email sent within 30s
3. No duplicate tasks per slot (DB constraint), no duplicate deliveries per attempt_number (DB constraint)
4. Executor can open token link, view task, accept, submit URL — without login
5. Two-stage verification works (url_verified -> content_verified -> verified)
6. Tasks past deadline auto-expire
7. Admin can cancel (soft delete with reason), resend (within anti-spam limits)
8. Anti-spam: max 3 resends, 10 min cooldown enforced
9. Feature disabled by default (opt-in via email_tasks_enabled setting)
10. SLA metrics computable from stored data (no separate aggregation needed for MVP)
