# Database Audit & Index Optimization — Bugfix Design

## Overview

Two related operational issues degrade system reliability and observability:

1. **Audit log gaps** — 7 task/service modules (`orchestrator.py`, `scraping.py`, `karma_tracking.py`, `presence.py`, `profile_analytics.py`, `ai_pipeline.py` phase evaluation, and `scoring.py` via `ai_pipeline.py`) perform significant system operations without emitting `AuditLog` entries via `log_system_action`. The admin audit logs page shows an incomplete picture of background activity.

2. **Missing database indexes** — 4 tables (`avatar_subreddit_presence`, `subreddit_karma`, `scrape_log`, `audit_log`) lack composite indexes for their most common query patterns, causing sequential scans as data grows.

The fix adds `log_system_action` calls at task completion/failure points and creates an Alembic migration with 4 composite indexes.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug — a background task completes without calling `log_system_action`, OR a query hits a table without a covering composite index
- **Property (P)**: The desired behavior — every significant background task emits an `AuditLog` entry, and common query patterns use index scans instead of sequential scans
- **Preservation**: Existing audit logging in `services/admin.py`, `routes/review.py`, `routes/pages.py`, `services/settings.py`, `services/health_checker.py`, `services/cqs_checker.py`, and `routes/admin.py` must remain unchanged. Existing indexes must not be dropped or degraded.
- **`log_system_action`**: Function in `app/services/audit.py` that creates an `AuditLog` entry with `user_id=None` for background/system actions
- **`record_activity_event`**: Function in `app/services/transparency.py` that creates `ActivityEvent` entries (separate from `AuditLog` — both should exist for different purposes)
- **Composite index**: A PostgreSQL index on multiple columns, enabling efficient lookups when queries filter/sort by those columns together

## Bug Details

### Bug Condition

The bug manifests in two forms:

1. **Audit gap**: A background task (orchestrator, scraping, karma tracking, presence scanning, profile analytics, phase evaluation, scoring batch) completes execution without calling `log_system_action`.
2. **Missing index**: A query filters by `avatar_id` + orders by `last_activity_at`/`last_updated_at`, or filters by `subreddit_id` + orders by `scraped_at`, or filters by `action` + `created_at` range — and PostgreSQL performs a sequential scan because no composite index covers the pattern.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type SystemOperation
  OUTPUT: boolean

  -- Audit gap condition
  IF input.type == "task_completion" THEN
    RETURN input.task_name IN [
      'run_full_pipeline_all_clients',
      'run_hobby_pipeline_all_avatars',
      'scrape_subreddit_shared',
      'scrape_professional_subreddits',
      'scrape_hobby_subreddits',
      'track_karma_all_avatars',
      'scan_avatar_presence_task',
      'snapshot_profile_analytics_all_avatars',
      'evaluate_all_avatar_phases',
      'score_threads'  -- batch completion summary
    ]
    AND NOT auditLogEntryCreated(input.task_name, input.execution_id)
  END IF

  -- Missing index condition
  IF input.type == "database_query" THEN
    RETURN (
      (input.table == 'avatar_subreddit_presence'
       AND input.filter_columns CONTAINS 'avatar_id'
       AND input.order_columns INTERSECTS {'last_activity_at', 'total_karma'})
      OR
      (input.table == 'subreddit_karma'
       AND input.filter_columns CONTAINS 'avatar_id'
       AND input.order_columns CONTAINS 'last_updated_at')
      OR
      (input.table == 'scrape_log'
       AND input.filter_columns CONTAINS 'subreddit_id'
       AND input.order_columns CONTAINS 'scraped_at')
      OR
      (input.table == 'audit_log'
       AND input.filter_columns CONTAINS 'action'
       AND input.filter_columns CONTAINS 'created_at'
       AND NOT input.filter_columns CONTAINS 'client_id')
    )
    AND input.execution_plan == 'Seq Scan'
  END IF

  RETURN false
END FUNCTION
```

### Examples

- `run_full_pipeline_all_clients` completes for 3 clients → no `AuditLog` row with action `pipeline_run_completed` exists (only `ActivityEvent` entries exist)
- `scrape_subreddit_shared` scrapes r/cybersecurity successfully → `ScrapeLog` and `ActivityEvent` created, but no `AuditLog` entry
- `track_karma_all_avatars` processes 10 avatars → `ActivityEvent` recorded, but admin audit logs page shows nothing for karma tracking
- Admin opens `/admin/audit-logs` filtered by action=`scrape_completed` and date range → query does `Seq Scan` on `audit_log` because existing index requires `client_id` as leading column
- Avatar detail page loads presence data sorted by `last_activity_at` → `Seq Scan` on `avatar_subreddit_presence` (only single-column `avatar_id` index exists)

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- `log_action` calls in `services/admin.py` for CRUD operations (create/update/delete users, clients, avatars, subreddits, keywords) must continue working identically
- `log_action` calls in `routes/review.py` and `routes/pages.py` for review actions (approve/reject/edit) must continue working identically
- `log_system_action` calls in `services/settings.py`, `services/health_checker.py`, `services/cqs_checker.py`, and `routes/admin.py` must continue working identically
- Existing indexes (`ix_comment_drafts_client_status`, `ix_reddit_threads_subreddit_not_locked`, `ix_thread_scores_client_tag`, `ix_scrape_log_client_sub_time`, `ix_scrape_log_subreddit_name`, `ix_subreddit_karma_avatar`) must not be dropped or degraded
- `query_audit_logs` function must continue returning correct paginated results with the same semantics for all existing filter combinations
- `record_activity_event` calls in tasks must remain unchanged (audit logs supplement, not replace, activity events)

**Scope:**
All inputs that do NOT involve the 7 task modules listed above, and all queries that already have covering indexes, should be completely unaffected by this fix. This includes:
- Manual admin actions (already audited)
- Review actions (already audited)
- Health check state changes (already audited)
- CQS batch checks (already audited)
- Pipeline triggers from admin UI (already audited)

## Hypothesized Root Cause

Based on the bug description, the most likely issues are:

1. **Incremental development without audit coverage**: The task modules were built with `record_activity_event` for the transparency dashboard but `log_system_action` was never added. The audit service was originally designed for admin CRUD actions (user-initiated), and background tasks were added later without updating the audit pattern.

2. **Confusion between ActivityEvent and AuditLog**: Both serve observability but for different audiences. `ActivityEvent` powers the client transparency dashboard and activity feed. `AuditLog` powers the admin audit logs page with filtering/pagination. Tasks emit `ActivityEvent` but not `AuditLog`.

3. **Index design focused on original access patterns**: The `audit_log` composite index `(client_id, action, created_at)` was designed for per-client filtering. System actions (background tasks) have `client_id=NULL`, making this index useless for filtering by action + date range without client context.

4. **Single-column indexes on growing tables**: `avatar_subreddit_presence` and `subreddit_karma` have single-column `avatar_id` indexes. When queries also sort by a timestamp column, PostgreSQL must fetch all rows for the avatar and then sort in memory — acceptable at 5 avatars, problematic at 50+.

## Correctness Properties

Property 1: Bug Condition - Audit Log Completeness

_For any_ background task execution where the task is one of the 7 identified modules (orchestrator, scraping, karma tracking, presence, profile analytics, phase evaluation, scoring batch), the fixed code SHALL create an `AuditLog` entry via `log_system_action` with the appropriate action name, entity_type, and details dict containing execution metrics.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8**

Property 2: Preservation - Existing Audit and Query Behavior

_For any_ operation that is NOT one of the 7 newly-audited task modules, the fixed code SHALL produce exactly the same audit logging behavior as the original code, preserving all existing `log_action` and `log_system_action` calls, and the `query_audit_logs` function SHALL continue to return correct paginated results with identical semantics for all filter combinations.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8**

Property 3: Index Coverage - Query Plan Optimization

_For any_ query that filters `avatar_subreddit_presence` by `avatar_id` with ordering, or filters `subreddit_karma` by `avatar_id` with ordering by `last_updated_at`, or filters `scrape_log` by `subreddit_id` with ordering by `scraped_at`, or filters `audit_log` by `action` + `created_at` range without `client_id`, the database SHALL use an index scan (not sequential scan) as verified by `EXPLAIN ANALYZE`.

**Validates: Requirements 2.9, 2.10, 2.11, 2.12**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `app/tasks/orchestrator.py`

**Function**: `run_full_pipeline_all_clients`

**Specific Changes**:
1. **Add audit log at start**: Call `log_system_action(db, action="pipeline_run_started", entity_type="pipeline", details={"client_count": len(clients)})` before dispatching chains
2. **Add audit log at completion**: Call `log_system_action(db, action="pipeline_run_completed", entity_type="pipeline", details={"client_count": len(clients), "clients_queued": [list of client names]})` after the loop

**File**: `app/tasks/orchestrator.py`

**Function**: `run_hobby_pipeline_all_avatars`

**Specific Changes**:
3. **Add audit log**: Call `log_system_action(db, action="hobby_pipeline_run", entity_type="pipeline", details={"avatar_count": len(avatars)})` after dispatching all chains

**File**: `app/tasks/scraping.py`

**Function**: `scrape_subreddit_shared`

**Specific Changes**:
4. **Add audit log on success**: Call `log_system_action(db, action="scrape_completed", entity_type="subreddit", entity_id=subreddit_uuid, details={"subreddit_name": ..., "posts_found": ..., "posts_new": ..., "duration_ms": ...})`
5. **Add audit log on failure**: Call `log_system_action(db, action="scrape_failed", entity_type="subreddit", entity_id=subreddit_uuid, details={"subreddit_name": ..., "error": ...})`

**File**: `app/tasks/karma_tracking.py`

**Function**: `track_karma_all_avatars`

**Specific Changes**:
6. **Add audit log at completion**: Call `log_system_action(db, action="karma_tracking_batch_completed", entity_type="karma", details=total_stats)` after the processing loop

**File**: `app/tasks/presence.py`

**Function**: `scan_avatar_presence_task`

**Specific Changes**:
7. **Add audit log on completion**: Call `log_system_action(db, action="presence_scan_completed", entity_type="avatar", entity_id=avatar_uuid, details={"avatar_id": ..., "subreddits_found": len(records)})` after successful scan

**File**: `app/tasks/profile_analytics.py`

**Function**: `snapshot_profile_analytics_all_avatars`

**Specific Changes**:
8. **Add audit log at completion**: Call `log_system_action(db, action="profile_analytics_batch_completed", entity_type="avatar", details=stats)` after the processing loop

**File**: `app/tasks/ai_pipeline.py`

**Function**: `evaluate_all_avatar_phases`

**Specific Changes**:
9. **Add audit log at completion**: Call `log_system_action(db, action="phase_evaluation_completed", entity_type="avatar", details={"evaluated": ..., "promoted": ..., "demoted": ..., "errors": ...})` before returning

**File**: `app/tasks/ai_pipeline.py`

**Function**: `score_threads`

**Specific Changes**:
10. **Add audit log on successful scoring batch**: Call `log_system_action(db, action="scoring_batch_completed", entity_type="thread", client_id=uuid.UUID(client_id), details={"threads_scored": count, "engage": engage, "monitor": monitor, "skip": skip})` after recording the activity event

**File**: New Alembic migration

**Specific Changes**:
11. **Add composite index on `avatar_subreddit_presence`**: `CREATE INDEX ix_avatar_presence_avatar_activity ON avatar_subreddit_presence (avatar_id, last_activity_at DESC NULLS LAST)`
12. **Add composite index on `subreddit_karma`**: `CREATE INDEX ix_subreddit_karma_avatar_updated ON subreddit_karma (avatar_id, last_updated_at DESC)`
13. **Add composite index on `scrape_log`**: `CREATE INDEX ix_scrape_log_subreddit_scraped ON scrape_log (subreddit_id, scraped_at DESC)`
14. **Add composite index on `audit_log`**: `CREATE INDEX ix_audit_log_action_created ON audit_log (action, created_at DESC)`

**File**: `app/models/avatar_subreddit_presence.py`

**Specific Changes**:
15. **Add index to `__table_args__`**: Add `Index("ix_avatar_presence_avatar_activity", "avatar_id", last_activity_at.desc())` to keep model in sync with migration

**File**: `app/models/subreddit_karma.py`

**Specific Changes**:
16. **Add index to `__table_args__`**: Add `Index("ix_subreddit_karma_avatar_updated", "avatar_id", last_updated_at.desc())` to keep model in sync with migration

**File**: `app/models/scrape_log.py`

**Specific Changes**:
17. **Add index to `__table_args__`**: Add `Index("ix_scrape_log_subreddit_scraped", "subreddit_id", scraped_at.desc())` to keep model in sync with migration

**File**: `app/models/audit.py`

**Specific Changes**:
18. **Add index to model**: Add `Index("ix_audit_log_action_created", "action", created_at.desc())` via `__table_args__`

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that execute each background task (with mocked Reddit API) and assert that `AuditLog` entries are created. Run these tests on the UNFIXED code to observe failures and confirm the gap.

**Test Cases**:
1. **Orchestrator Pipeline Test**: Call `run_full_pipeline_all_clients` with mocked clients → assert `AuditLog` with action `pipeline_run_started` exists (will fail on unfixed code)
2. **Scraping Audit Test**: Call `scrape_subreddit_shared` with mocked Reddit → assert `AuditLog` with action `scrape_completed` exists (will fail on unfixed code)
3. **Karma Tracking Audit Test**: Call `track_karma_all_avatars` with mocked Reddit → assert `AuditLog` with action `karma_tracking_batch_completed` exists (will fail on unfixed code)
4. **Phase Evaluation Audit Test**: Call `evaluate_all_avatar_phases` with test avatars → assert `AuditLog` with action `phase_evaluation_completed` exists (will fail on unfixed code)
5. **Index Coverage Test**: Run `EXPLAIN ANALYZE` on representative queries → assert plan does NOT contain `Seq Scan` on the 4 target tables (will fail on unfixed code)

**Expected Counterexamples**:
- `AuditLog` table has zero rows with actions matching the background task names
- `EXPLAIN ANALYZE` shows `Seq Scan` on `avatar_subreddit_presence` when filtering by `avatar_id` and ordering by `last_activity_at`
- Possible causes: `log_system_action` simply never called in these code paths; no composite indexes defined

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL task_execution WHERE isBugCondition(task_execution) DO
  result := execute_task_fixed(task_execution)
  ASSERT AuditLog.query(action=expected_action, created_at >= task_start).count() >= 1
  ASSERT AuditLog.latest(action=expected_action).details CONTAINS expected_keys
END FOR

FOR ALL query WHERE isBugCondition(query) DO
  plan := EXPLAIN ANALYZE query
  ASSERT 'Index Scan' IN plan OR 'Index Only Scan' IN plan
  ASSERT 'Seq Scan' NOT IN plan (for the target table)
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL admin_action WHERE NOT isBugCondition(admin_action) DO
  ASSERT log_action_original(admin_action) = log_action_fixed(admin_action)
END FOR

FOR ALL query WHERE NOT isBugCondition(query) DO
  ASSERT query_audit_logs_original(filters) = query_audit_logs_fixed(filters)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many filter combinations for `query_audit_logs` automatically
- It catches edge cases where new indexes might change query plan behavior
- It provides strong guarantees that existing admin CRUD audit logging is unchanged

**Test Plan**: Observe behavior on UNFIXED code first for admin CRUD operations and existing query patterns, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Admin CRUD Audit Preservation**: Verify that creating/updating/deleting clients, avatars, users still produces identical `AuditLog` entries after the fix
2. **Review Action Audit Preservation**: Verify that approve/reject/edit actions still produce identical `AuditLog` entries
3. **Query Semantics Preservation**: Verify that `query_audit_logs` with various filter combinations (user_id, client_id, action, entity_type, date range, search) returns identical results
4. **Existing Index Preservation**: Verify that queries using existing indexes (`ix_scrape_log_client_sub_time`, `ix_subreddit_karma_avatar`) still use those indexes

### Unit Tests

- Test each task function creates the expected `AuditLog` entry with correct action, entity_type, and details
- Test that `log_system_action` failures (e.g., DB connection error) do not crash the parent task (wrapped in try/except)
- Test that the new indexes exist after migration (query `pg_indexes`)
- Test `query_audit_logs` with action filter + date range uses the new index

### Property-Based Tests

- Generate random task execution scenarios (varying client counts, avatar counts, success/failure) and verify audit log entries are always created
- Generate random `query_audit_logs` filter combinations and verify results match between pre-fix and post-fix code
- Generate random `avatar_id` values and verify presence/karma queries use index scans

### Integration Tests

- Run full pipeline cycle (scrape → score → generate) and verify all expected `AuditLog` entries appear in chronological order
- Run `evaluate_all_avatar_phases` with mix of promotable/demotable/stable avatars and verify audit log details contain correct counts
- Load admin audit logs page with various filters and verify response time is acceptable (<500ms) with the new indexes
