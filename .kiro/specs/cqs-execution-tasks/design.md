# Design: CQS Execution Tasks

## Overview

Adds a periodic CQS check task generator that sends execution task emails to avatar executors, prompting them to post "What is my cqs?" in r/WhatIsMyCQS. This closes the self-healing loop for CQS=lowest avatars (zero EPG budget) and keeps CQS data fresh for all avatars.

The feature reuses the existing ExecutionTask → dispatch_due_email_tasks → email pipeline with a new task_type="cqs_check" and a dedicated Celery Beat schedule entry.

## Architecture

## Components and Interfaces

### 1. CQS Task Generator Service (NEW: `app/services/cqs_task_generator.py`)

**Interface:**
```python
def generate_cqs_check_tasks(db: Session) -> dict:
    """Generate CQS check execution tasks for all eligible avatars.
    
    Returns: {created: int, skipped_frozen: int, skipped_health: int,
              skipped_no_email: int, skipped_pending: int, skipped_interval: int,
              errors: int, duration_ms: int}
    """
```

**Internal helpers:**
- `_get_cqs_check_interval(avatar: Avatar) -> int` — returns 7 or 30 days
- `_has_pending_cqs_task(db: Session, avatar_id: UUID) -> bool`
- `_get_last_cqs_task_date(db: Session, avatar_id: UUID) -> datetime | None`
- `_create_cqs_execution_task(db: Session, avatar: Avatar) -> ExecutionTask`

**Dependencies:** Avatar model, ExecutionTask model, system settings

### 2. Celery Task (NEW: `app/tasks/cqs_tasks.py`)

```python
@shared_task(name="generate_cqs_check_tasks_all_avatars")
def generate_cqs_check_tasks_all_avatars() -> dict:
    """Daily 07:00 Israel — generate CQS check tasks for eligible avatars."""
```

### 3. Beat Schedule (MODIFIED: `app/tasks/worker.py`)

New entry: `"cqs-check-tasks-daily"` → `crontab(hour=7, minute=0)`

### 4. Email Composition (MODIFIED: `app/services/execution_tasks.py`)

Branch in `compose_task_email()` for `task_type == "cqs_check"` with dedicated subject and body template.

### 5. ExecutionTask Model (MODIFIED: `app/models/execution_task.py`)

`epg_slot_id` becomes nullable to support CQS tasks that have no linked EPG slot.

## Data Models

### ExecutionTask Changes

| Field | Current | New | Reason |
|-------|---------|-----|--------|
| `epg_slot_id` | `NOT NULL, UNIQUE` | `NULLABLE, indexed (partial)` | CQS tasks have no slot |
| `task_type` | "comment" / "reply" | + "cqs_check" | New task type |

### New System Setting

| Key | Default | Type |
|-----|---------|------|
| `cqs_check_tasks_enabled` | `"true"` | Kill switch |

### Interval Logic (no new DB fields needed)

Avatar age derived from `avatar.created_at` (DB row creation date, set during onboarding — approximates Reddit account age). If more precision needed, a `reddit_created_utc` field would be required (future enhancement).

## Error Handling

- **Single avatar failure:** Logged, skipped, batch continues. Error count in summary.
- **Email delivery failure:** Standard 3x retry via existing `deliver_execution_task`.
- **Kill switch off:** Task returns immediately with `{"status": "disabled"}`.
- **Avatar frozen between generation and dispatch:** Caught by health gate in `dispatch_due_email_tasks`.
- **Task deadline exceeded (48h):** Expired by `expire_overdue_execution_tasks` at 23:30 daily.
- **DB integrity error on task creation:** Rollback, log, continue batch.

## Correctness Properties

### Property 1: Single Pending Task Per Avatar
At most one pending CQS task per avatar at any time. Enforced by `_has_pending_cqs_task` check before creation.

**Validates: Requirement 5**

### Property 2: Health Exclusion
CQS tasks never created for unhealthy/frozen/shadowbanned avatars. Eligibility query + dispatch health gate (defense in depth).

**Validates: Requirement 4**

### Property 3: Interval Persistence
Interval respected across restarts. Uses `created_at` from DB, not in-memory state.

**Validates: Requirement 3**

### Property 4: Backward Compatibility
Existing EPG task flow unchanged. Migration only relaxes constraints; existing non-null epg_slot_id tasks still work identically.

**Validates: Requirement 11**

### Property 5: Quiet Hours Compliance
CQS tasks use `scheduled_at = 07:05 Israel` — always within active hours.

**Validates: Requirement 6**

## Testing Strategy

1. **Unit tests** for `_get_cqs_check_interval` (age/CQS combinations)
2. **Unit tests** for `generate_cqs_check_tasks` with mocked DB (eligible/ineligible/pending scenarios)
3. **Integration test:** Create avatar with CQS=lowest + verified email → run generator → verify ExecutionTask created with correct fields
4. **Integration test:** Run generator twice in same day → verify no duplicate task
5. **Integration test:** CQS task flows through `dispatch_due_email_tasks` → `compose_task_email` produces correct subject/body
6. **Migration test:** Existing EPG tasks unaffected after migration (nullable epg_slot_id, existing non-null values preserved)
