# Implementation Plan: Stale Draft Expiry

## Status: ✅ DEPLOYED to production (July 5, 2026)

Migration `cdu01` applied. Beat task `expire_stale_drafts` running hourly. Kill switch: `draft_expiry_enabled`.

## Overview

Implements an automated hourly Celery Beat task that identifies and expires stale CommentDraft records (approved >48h, pending >72h), cascades status changes to associated EPGSlot and ExecutionTask records, and emits activity events for operator visibility. Uses existing DistributedLock, get_setting(), and record_activity_event() infrastructure.

## Tasks

- [x] 1. Register system settings and integrate worker
  - [x] 1.1 Add draft expiry settings to DEFAULT_SETTINGS in `app/services/settings.py`
    - Add `draft_expiry_approved_hours` (value: "48", group: "pipeline", desc: "Hours before approved drafts are automatically expired")
    - Add `draft_expiry_pending_hours` (value: "72", group: "pipeline", desc: "Hours before pending drafts are automatically expired")
    - Add `draft_expiry_enabled` (value: "true", group: "pipeline", desc: "Kill switch for automatic draft expiry")
    - All three with `secret: False`
    - _Requirements: 7.1, 7.2, 7.3, 7.5_

  - [x] 1.2 Create `app/tasks/draft_expiry.py` with the Celery task shell
    - Import `celery_app` from `app.tasks.worker`
    - Define `@celery_app.task(name="expire_stale_drafts", bind=True)` function
    - Implement lock acquisition (`DistributedLock(key="expire_stale_drafts_lock", ttl=1800)`)
    - Read `draft_expiry_enabled` setting — if `"false"`, release lock, log, return
    - Call `DraftExpiryService().run(db)` inside try/finally (release lock in finally)
    - Log WARNING if lock not acquired
    - _Requirements: 6.1, 6.3, 6.4, 6.5_

  - [x] 1.3 Register the task module and beat schedule in `app/tasks/worker.py`
    - Add `"app.tasks.draft_expiry"` to the `include` list
    - Add beat entry `"expire-stale-drafts": {"task": "expire_stale_drafts", "schedule": crontab(minute=0)}` (every 60 min)
    - _Requirements: 6.1, 6.2_

- [x] 2. Implement DraftExpiryService core logic
  - [x] 2.1 Create `app/services/draft_expiry.py` with data classes and service skeleton
    - Define `DraftExpiry`, `BatchResult`, `DraftExpiryResult` dataclasses
    - Create `DraftExpiryService` class with `run(self, db: Session) -> DraftExpiryResult` method
    - In `run()`: read threshold settings via `get_setting_int()`, query stale drafts, process in batches, emit events, log summary
    - Track execution duration in milliseconds
    - _Requirements: 1.1, 2.1, 9.1, 9.4_

  - [x] 2.2 Implement `_query_stale_approved()` method
    - Query `CommentDraft` with `status = 'approved'` and `updated_at < now() - threshold hours`
    - LEFT JOIN `EPGSlot` on `draft_id` — exclude drafts whose slot has `scheduled_at` within next 2 hours
    - Filter: `(es.id IS NULL OR es.scheduled_at IS NULL OR es.scheduled_at > now() + 2 hours)`
    - Order by `updated_at ASC`, limit 500
    - Skip drafts with `client_id IS NULL` (log WARNING for orphaned drafts)
    - _Requirements: 1.1, 1.2_

  - [x] 2.3 Implement `_query_stale_pending()` method
    - Query `CommentDraft` with `status = 'pending'` and `created_at < now() - threshold hours`
    - Order by `created_at ASC`, limit 500
    - Skip drafts with `client_id IS NULL`
    - _Requirements: 2.1_

  - [x] 2.4 Implement `_process_batch()` method
    - Accept list of up to 50 drafts
    - Begin savepoint, process each draft via `_expire_draft()`
    - On success: commit savepoint, return `BatchResult` with expired list
    - On database error: rollback savepoint, log ERROR, return `BatchResult` with error string
    - _Requirements: 1.4, 1.6, 2.3, 2.5_

  - [x] 2.5 Implement `_expire_draft()` method
    - Set `draft.status = 'expired'`
    - Compute `stale_age_hours` (whole hours since `updated_at` for approved, `created_at` for pending)
    - Update `draft.learning_metadata` with expiry info: `{"expiry_reason": "stale_approved"|"stale_pending", "stale_age_hours": N, "expired_at": "ISO8601"}`
    - Merge existing `learning_metadata` (preserve prior keys)
    - Call `_cascade_epg_slot()` and `_cancel_execution_tasks()`
    - Log each expiry at DEBUG level (draft_id, avatar_id, client_id, original_status, age_hours)
    - Return `DraftExpiry` dataclass
    - _Requirements: 1.3, 2.2, 8.4, 9.3_

  - [x] 2.6 Implement `_cascade_epg_slot()` method
    - Query `EPGSlot` where `draft_id = draft.id`
    - If found and status in (`'generated'`, `'approved'`): set status `'expired'`, set `skip_reason = 'draft_stale_expired'`
    - If terminal status (`'posted'`, `'skipped'`, `'expired'`): leave unchanged
    - If not found: proceed without error
    - Return the slot or None
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 2.7 Implement `_cancel_execution_tasks()` method
    - If slot was expired: query `ExecutionTask` where `epg_slot_id = slot.id`
    - For each task with status in (`'generated'`, `'emailed'`, `'accepted'`): set `status = 'cancelled'`, `cancel_reason = 'draft_stale_expired'`, `cancelled_at = now()`
    - If `task_lifecycle_status = 'ASSIGNED'`: also set `task_lifecycle_status = 'CANCELLED'`
    - Terminal statuses (`'submitted'`, `'verified'`, `'expired'`, `'cancelled'`): leave unchanged
    - Return count of cancelled tasks
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

- [x] 3. Implement activity events and logging
  - [x] 3.1 Implement `_emit_activity_events()` method
    - Group expired drafts by `client_id`
    - For each client: call `record_activity_event()` with:
      - `event_type = 'system'`
      - `client_id = client_uuid`
      - `message = "Expired {N} stale draft(s) for {M} avatar(s)"`
      - `metadata = {"action": "stale_draft_expiry", "drafts_expired_count": N, "approved_expired_count": A, "pending_expired_count": P, "tasks_cancelled_count": T, "avatar_ids": [distinct UUID strings]}`
    - Wrap in try/except — on failure log ERROR but do NOT revert committed batches
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 3.2 Implement summary logging in `run()` method
    - At end of run: log INFO with total_expired, approved_expired, pending_expired, tasks_cancelled, per-client counts, duration_ms
    - If total_expired > 50: log WARNING with the count and threshold value
    - If total_expired == 0: log INFO indicating zero drafts expired and duration
    - _Requirements: 9.1, 9.2, 9.4_

- [x] 4. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement batch orchestration and error handling
  - [x] 5.1 Wire batch processing in `run()` with error escalation
    - Combine approved + pending candidates into single list
    - Chunk into batches of 50
    - Process each batch via `_process_batch()`
    - Track batch error count — if >3 failures in single run, log CRITICAL
    - Accumulate results into `DraftExpiryResult`
    - _Requirements: 1.4, 1.6, 2.3, 2.5_

  - [x] 5.2 Write property test for candidate selection correctness (Property 1)
    - **Property 1: Candidate Selection Correctness**
    - Use Hypothesis to generate random CommentDraft records with varying statuses, timestamps, and associated EPGSlots
    - Assert: only drafts with correct status + age > threshold + count ≤ 500 + no execution window protection are returned
    - **Validates: Requirements 1.1, 1.2, 2.1**

  - [x] 5.3 Write property test for status transition integrity (Property 2)
    - **Property 2: Status Transition Integrity**
    - Generate random stale drafts, run expiry, verify: status == 'expired' AND learning_metadata contains stale_age_hours as integer
    - **Validates: Requirements 1.3, 2.2, 8.4**

  - [x] 5.4 Write property test for cascade atomicity (Property 3)
    - **Property 3: Cascade Atomicity**
    - Generate drafts with associated EPGSlots (non-terminal) and ExecutionTasks, run expiry
    - Assert: within same commit, slot.status == 'expired', slot.skip_reason == 'draft_stale_expired', task.status == 'cancelled', task.cancel_reason == 'draft_stale_expired'
    - **Validates: Requirements 3.2, 4.2, 4.5**

  - [x] 5.5 Write property test for terminal state preservation (Property 4)
    - **Property 4: Terminal State Preservation**
    - Generate EPGSlots in terminal states ('posted', 'skipped', 'expired') and ExecutionTasks in terminal states ('submitted', 'verified', 'expired', 'cancelled')
    - Assert: these records are NOT modified by the expiry process
    - **Validates: Requirements 3.3, 4.3**

  - [x] 5.6 Write property test for batch independence (Property 5)
    - **Property 5: Batch Independence and Error Isolation**
    - Generate N drafts across ceil(N/50) batches, inject failure in batch K
    - Assert: batches before K are committed, batch K is rolled back, batches after K still attempted
    - **Validates: Requirements 1.4, 1.6, 2.3, 2.5**

  - [x] 5.7 Write property test for activity event grouping (Property 6)
    - **Property 6: Activity Event Per-Client Grouping**
    - Generate drafts for C distinct clients, run expiry
    - Assert: exactly C activity events emitted with correct metadata structure and message pattern
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.5**

  - [x] 5.8 Write property test for execution window protection (Property 7)
    - **Property 7: Execution Window Protection**
    - Generate approved drafts with EPGSlot.scheduled_at within next 2 hours
    - Assert: these drafts never appear in expiry candidate set regardless of age
    - **Validates: Requirements 1.2**

- [x] 6. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Add UI visibility for expired drafts
  - [x] 7.1 Add amber badge for expired status in `app/templates/admin_review.html`
    - Add condition for `status == 'expired'` rendering amber badge: `bg-amber-100 text-amber-800` (light) / `bg-amber-900/50 text-amber-300` (dark)
    - Display stale age from `learning_metadata.stale_age_hours` when available
    - _Requirements: 8.2, 8.4_

  - [x] 7.2 Add amber badge for expired status in `app/templates/client/review.html`
    - Same amber badge styling as admin template
    - Display stale age from metadata
    - _Requirements: 8.2, 8.4_

  - [x] 7.3 Add 'expired' to status filter dropdown in admin review route (`app/routes/admin.py`)
    - Add `'expired'` option after `'rejected'` in the status filter dropdown
    - Ensure query filters work correctly for expired status
    - _Requirements: 8.3, 8.5_

- [x] 8. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document using Hypothesis
- Unit tests validate specific examples and edge cases
- No database migration is required — `'expired'` is stored in existing VARCHAR(50) status columns
- The service uses existing `get_setting_int()` for safe integer parsing with defaults
- Expiry metadata is merged into the existing `learning_metadata` JSONB field (preserving prior keys like `edit_record_ids`)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3"] },
    { "id": 3, "tasks": ["2.4", "2.5"] },
    { "id": 4, "tasks": ["2.6", "2.7"] },
    { "id": 5, "tasks": ["3.1", "3.2"] },
    { "id": 6, "tasks": ["5.1"] },
    { "id": 7, "tasks": ["5.2", "5.3", "5.4", "5.5", "5.6", "5.7", "5.8"] },
    { "id": 8, "tasks": ["7.1", "7.2", "7.3"] }
  ]
}
```
