# Design Document

## Overview

This design implements the Trial Execution Gap fix by introducing an AvatarDraft state machine, async BYOA pipeline via Celery, an ExternalRequestScheduler layer, and a client-active-state invariant. The architecture leverages existing infrastructure (Celery + Redis, PostgreSQL, HTMX polling) without introducing new external dependencies.

## Architecture

### System Flow

1. User submits Reddit username in onboarding Step 5
2. System creates AvatarDraft (status=pending_fetch), enqueues Celery task
3. HTMX polls GET /onboard/step/5/draft-status every 2 seconds
4. Celery worker: FETCH_REDDIT_PROFILE via ExternalRequestScheduler -> stores reddit_snapshot
5. Celery worker: AI_PROFILE_ANALYSIS via ExternalRequestScheduler -> stores ai_analysis
6. Draft transitions to ready_for_review; HTMX poll renders preview card
7. User confirms -> Avatar entity created, client can activate in Step 6
8. Step 6 activation enforces invariant: requires at least 1 active Avatar

### AvatarDraft State Machine

States: pending_fetch -> analyzing -> ready_for_review -> confirmed | rejected
Error states (from pending_fetch or analyzing): fetch_failed, analysis_failed

Terminal states: confirmed, rejected, fetch_failed, analysis_failed
Non-terminal states: pending_fetch, analyzing, ready_for_review

### Onboarding Step Restructure

Current: Step 1 (Profile) -> Step 2 (Problem) -> Step 3 (ICP) -> Step 4 (Voice) -> Step 5 (Keywords+Subs) -> Step 6 (Activate)
New: Step 1 (Profile) -> Step 2 (Problem) -> Step 3 (ICP) -> Step 4 (Voice+Keywords+Subs) -> Step 5 (BYOA Avatar) -> Step 6 (Activate)

## Data Models

### AvatarDraft (new: app/models/avatar_draft.py)

Table: avatar_drafts

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default uuid4 |
| reddit_username | String(20) | NOT NULL |
| client_id | UUID | FK clients.id, NOT NULL |
| created_by_user_id | UUID | FK users.id, NOT NULL |
| status | String(20) | NOT NULL, default "pending_fetch" |
| error_message | Text | nullable |
| reddit_snapshot | JSONB | nullable |
| ai_analysis | JSONB | nullable |
| avatar_id | UUID | FK avatars.id, nullable |
| created_at | DateTime(tz) | server_default=now() |
| updated_at | DateTime(tz) | server_default=now(), onupdate=now() |
| fetch_started_at | DateTime(tz) | nullable |
| fetch_completed_at | DateTime(tz) | nullable |
| analysis_started_at | DateTime(tz) | nullable |
| analysis_completed_at | DateTime(tz) | nullable |
| confirmed_at | DateTime(tz) | nullable |

Index: partial unique on (reddit_username, client_id) WHERE status IN ('pending_fetch', 'analyzing', 'ready_for_review')

### Client Model

No changes. Uses existing is_active + onboarding_completed_at for invariant enforcement.

### Avatar Model

No changes. Created from AvatarDraft data on confirmation.

## Components and Interfaces

### ExternalRequestScheduler (app/services/external_scheduler.py)

Interface:
- acquire(service: str, priority: str) -> bool
- release(service: str) -> None
- wait_for_slot(service: str, priority: str, max_wait: int = 30) -> bool

Config: reddit=30 RPM, ai_llm=60 RPM, global_cap=10.
Priority: user_facing_paid(0), user_facing_trial(1), background_paid(2), background_trial(3).
Implementation: Redis sorted set sliding window + INCR/DECR semaphore.

### BYOA Pipeline Service (app/services/byoa_pipeline.py)

- create_avatar_draft(username, client_id, user_id, db) -> AvatarDraft
- confirm_avatar_draft(draft_id, user_edits, db) -> Avatar
- reject_avatar_draft(draft_id, db) -> None
- cancel_draft(draft_id, db) -> None
- check_trial_avatar_limit(client_id, db) -> tuple[bool, str]

### Avatar Invariant Service (app/services/avatar_invariant.py)

- has_active_avatar(client_id, db) -> bool
- enforce_invariant_on_deactivation(client_id, db) -> None
- enforce_invariant_on_activation(client_id, db) -> None

### BYOA Celery Tasks (app/tasks/byoa.py)

- fetch_reddit_profile_for_draft(draft_id): bind=True, max_retries=3
- analyze_reddit_profile_for_draft(draft_id): bind=True, max_retries=3
- check_stale_avatar_drafts(): periodic every 10 min
- check_avatar_invariant(): periodic daily 02:30
- check_onboarding_stall(): periodic hourly

### Onboarding Routes (app/routes/onboarding.py)

New endpoints:
- POST /onboard/step/5/submit-username
- GET /onboard/step/5/draft-status
- POST /onboard/step/5/confirm
- POST /onboard/step/5/reject
- POST /onboard/step/5/retry

### HTMX Templates

- step5.html: username input + byoa-result container
- partials/byoa_progress.html: polling (hx-trigger every 2s, 90s timeout)
- partials/byoa_preview.html: editable card + confirm/reject
- partials/byoa_error.html: error + retry
- partials/byoa_confirmed.html: summary + add another

## Correctness Properties

### Property 1: Active Client Invariant
**Validates: Requirements 5.1, 5.2, 5.3**
Client with is_active=True AND onboarding_completed_at set always has at least one Avatar with active=True and client_id in client_ids. Enforced at activation (step6), deactivation (freeze/unassign), and daily integrity check.

### Property 2: Draft Uniqueness
**Validates: Requirements 1.9**
At most one non-terminal AvatarDraft per (reddit_username, client_id) at any time. Enforced by PostgreSQL partial unique index.

### Property 3: Sequential Processing
**Validates: Requirements 2.6**
FETCH_REDDIT_PROFILE always completes before AI_PROFILE_ANALYSIS for a given draft. Enforced by Celery task chaining (chain to analyze only after fetch stores snapshot).

### Property 4: Trial Bound
**Validates: Requirements 7.1, 7.2, 7.3**
Trial clients have at most 1 non-terminal draft + 1 active avatar combined. Enforced at draft creation time in byoa_pipeline.py.

### Property 5: No Stale Drafts
**Validates: Requirements 1.10**
Drafts stuck in non-terminal state for 60+ minutes are automatically failed. Enforced by check_stale_avatar_drafts periodic task.

### Property 6: Rate Compliance
**Validates: Requirements 3.1, 3.2, 3.3**
Reddit calls respect 30 RPM. LLM calls respect 60 RPM. Global concurrent calls capped at 10. Enforced by ExternalRequestScheduler.

## Error Handling

PRAW Fetch Errors:
- Account not found (prawcore.NotFound): immediate fetch_failed, no retry
- Account suspended: immediate fetch_failed with message
- Rate limited (429): Celery retry, exponential backoff (60, 120, 240s)
- Network timeout: Celery retry
- After 3 retries: fetch_failed + user notification

AI Analysis Errors:
- LLM API error (5xx): Celery retry
- Invalid JSON response: Celery retry
- After 3 retries: analysis_failed + user notification

Stale Draft Timeout:
- Draft in pending_fetch/analyzing for 60+ min: auto-failure + notification

Invariant Violation:
- Runtime (deactivation): immediate client.is_active=False
- Daily check: deactivate + admin notification
- Recovery: automatic reactivation on new avatar assignment

Concurrency Overload:
- Global cap reached: wait_for_slot blocks up to max_wait
- If no slot: Celery retry with countdown=30
- Priority ensures user-facing gets slots first

## Testing Strategy

Unit Tests:
- AvatarDraft state transitions (valid + invalid)
- ExternalRequestScheduler rate limiter (mock Redis)
- Trial limit calculation
- Invariant check queries

Integration Tests:
- Full BYOA: submit -> fetch -> analyze -> confirm -> avatar exists
- Failures: invalid username -> fetch_failed; AI errors -> analysis_failed
- Trial enforcement: second submission rejected; failed allows retry
- Invariant: activation blocked; deactivation pauses; reactivation works
- Stale cleanup: 60-min threshold
- Step merge: voice + keywords save together

Manual QA:
- New trial user walkthrough
- Polling UI (spinner, transition, timeout at 90s)
- Try Different Account flow
- Return to step 5 with existing draft
- Admin onboard still works independently
