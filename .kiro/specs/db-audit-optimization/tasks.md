# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Audit Log Gaps in Background Tasks
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate background tasks complete without creating AuditLog entries
  - **Scoped PBT Approach**: Scope the property to the 10 concrete task executions identified in the design
  - Test that `run_full_pipeline_all_clients` creates AuditLog entries with actions `pipeline_run_started` and `pipeline_run_completed` (from Bug Condition in design)
  - Test that `run_hobby_pipeline_all_avatars` creates AuditLog entry with action `hobby_pipeline_run`
  - Test that `scrape_subreddit_shared` creates AuditLog entry with action `scrape_completed` on success and `scrape_failed` on failure
  - Test that `track_karma_all_avatars` creates AuditLog entry with action `karma_tracking_batch_completed`
  - Test that `scan_avatar_presence_task` creates AuditLog entry with action `presence_scan_completed`
  - Test that `snapshot_profile_analytics_all_avatars` creates AuditLog entry with action `profile_analytics_batch_completed`
  - Test that `evaluate_all_avatar_phases` creates AuditLog entry with action `phase_evaluation_completed`
  - Test that `score_threads` batch completion creates AuditLog entry with action `scoring_batch_completed`
  - Use mocked Reddit API (PRAW) and mocked LLM calls to isolate task logic
  - Assert each AuditLog entry contains correct `action`, `entity_type`, and `details` dict with expected keys
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves the bug exists: no AuditLog rows created by these tasks)
  - Document counterexamples found (e.g., "run_full_pipeline_all_clients completes for 3 clients but AuditLog has 0 rows with action='pipeline_run_started'")
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Existing Audit Logging and Query Behavior
  - **IMPORTANT**: Follow observation-first methodology
  - **Part A — Admin CRUD Audit Preservation:**
  - Observe: `services/admin.py` `log_action` calls for create/update/delete clients, avatars, users produce AuditLog entries on unfixed code
  - Observe: `routes/review.py` and `routes/pages.py` review actions (approve/reject/edit) produce AuditLog entries on unfixed code
  - Observe: `services/settings.py`, `services/health_checker.py`, `services/cqs_checker.py` `log_system_action` calls produce AuditLog entries on unfixed code
  - Write property-based test: for all admin CRUD operations (create/update/delete on users, clients, avatars, subreddits, keywords), an AuditLog entry with correct action and entity_type is created
  - Write property-based test: for all review actions, an AuditLog entry is created with user_id and correct action
  - **Part B — Query Semantics Preservation:**
  - Observe: `query_audit_logs` with various filter combinations (user_id, client_id, action, entity_type, date range, search) returns paginated results on unfixed code
  - Write property-based test: for random filter combinations, `query_audit_logs` returns identical results before and after fix
  - **Part C — Existing Index Preservation:**
  - Observe: queries using `ix_scrape_log_client_sub_time`, `ix_subreddit_karma_avatar`, `ix_comment_drafts_client_status` use index scans on unfixed code
  - Write property-based test: existing indexes are still present and used after migration
  - Verify all preservation tests PASS on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

- [ ] 3. Fix: Add audit logging to background tasks (10 `log_system_action` calls)

  - [-] 3.1 Add audit logging to orchestrator tasks
    - In `app/tasks/orchestrator.py` → `run_full_pipeline_all_clients`:
      - Add `log_system_action(db, action="pipeline_run_started", entity_type="pipeline", details={"client_count": len(clients)})` before dispatching chains
      - Add `log_system_action(db, action="pipeline_run_completed", entity_type="pipeline", details={"client_count": len(clients), "clients_queued": [client names]})` after the loop
    - In `app/tasks/orchestrator.py` → `run_hobby_pipeline_all_avatars`:
      - Add `log_system_action(db, action="hobby_pipeline_run", entity_type="pipeline", details={"avatar_count": len(avatars)})` after dispatching all chains
    - Wrap `log_system_action` calls in try/except to prevent audit failures from crashing parent task
    - _Bug_Condition: isBugCondition(input) where input.task_name IN ['run_full_pipeline_all_clients', 'run_hobby_pipeline_all_avatars'] AND NOT auditLogEntryCreated_
    - _Expected_Behavior: AuditLog entry created with correct action, entity_type, and details dict_
    - _Preservation: Existing `record_activity_event` calls must remain unchanged_
    - _Requirements: 2.1, 2.2_

  - [~] 3.2 Add audit logging to scraping tasks
    - In `app/tasks/scraping.py` → `scrape_subreddit_shared`:
      - Add `log_system_action(db, action="scrape_completed", entity_type="subreddit", entity_id=subreddit_uuid, details={"subreddit_name": ..., "posts_found": ..., "posts_new": ..., "duration_ms": ...})` on success
      - Add `log_system_action(db, action="scrape_failed", entity_type="subreddit", entity_id=subreddit_uuid, details={"subreddit_name": ..., "error": str(e)})` on failure
    - Wrap in try/except to prevent audit failures from crashing scrape task
    - _Bug_Condition: isBugCondition(input) where input.task_name IN ['scrape_subreddit_shared'] AND NOT auditLogEntryCreated_
    - _Expected_Behavior: AuditLog entry with action='scrape_completed' or 'scrape_failed' including subreddit_name, posts metrics, duration_
    - _Preservation: Existing ScrapeLog and ActivityEvent creation must remain unchanged_
    - _Requirements: 2.3_

  - [~] 3.3 Add audit logging to karma tracking task
    - In `app/tasks/karma_tracking.py` → `track_karma_all_avatars`:
      - Add `log_system_action(db, action="karma_tracking_batch_completed", entity_type="karma", details=total_stats)` after the processing loop
    - Include avatars_checked, significant_changes in details dict
    - Wrap in try/except
    - _Bug_Condition: isBugCondition(input) where input.task_name == 'track_karma_all_avatars' AND NOT auditLogEntryCreated_
    - _Expected_Behavior: AuditLog entry with action='karma_tracking_batch_completed' and details containing avatar count_
    - _Preservation: Existing ActivityEvent calls must remain unchanged_
    - _Requirements: 2.4_

  - [~] 3.4 Add audit logging to presence scanning task
    - In `app/tasks/presence.py` → `scan_avatar_presence_task`:
      - Add `log_system_action(db, action="presence_scan_completed", entity_type="avatar", entity_id=avatar_uuid, details={"avatar_id": ..., "subreddits_found": len(records)})` after successful scan
    - Wrap in try/except
    - _Bug_Condition: isBugCondition(input) where input.task_name == 'scan_avatar_presence_task' AND NOT auditLogEntryCreated_
    - _Expected_Behavior: AuditLog entry with action='presence_scan_completed', entity_id=avatar_uuid, details with subreddits_found_
    - _Preservation: Existing presence service behavior unchanged_
    - _Requirements: 2.5_

  - [~] 3.5 Add audit logging to profile analytics and phase evaluation tasks
    - In `app/tasks/profile_analytics.py` → `snapshot_profile_analytics_all_avatars`:
      - Add `log_system_action(db, action="profile_analytics_batch_completed", entity_type="avatar", details=stats)` after the processing loop
    - In `app/tasks/ai_pipeline.py` → `evaluate_all_avatar_phases`:
      - Add `log_system_action(db, action="phase_evaluation_completed", entity_type="avatar", details={"evaluated": ..., "promoted": ..., "demoted": ..., "errors": ...})` before returning
    - Wrap both in try/except
    - _Bug_Condition: isBugCondition(input) where input.task_name IN ['snapshot_profile_analytics_all_avatars', 'evaluate_all_avatar_phases'] AND NOT auditLogEntryCreated_
    - _Expected_Behavior: AuditLog entries with correct actions and detail dicts containing counts_
    - _Preservation: Existing ActivityEvent and phase change logic unchanged_
    - _Requirements: 2.6, 2.7_

  - [~] 3.6 Add audit logging to scoring batch completion
    - In `app/tasks/ai_pipeline.py` → `score_threads`:
      - Add `log_system_action(db, action="scoring_batch_completed", entity_type="thread", client_id=uuid.UUID(client_id), details={"threads_scored": count, "engage": engage, "monitor": monitor, "skip": skip})` after recording the activity event
    - Wrap in try/except
    - _Bug_Condition: isBugCondition(input) where input.task_name == 'score_threads' AND NOT auditLogEntryCreated_
    - _Expected_Behavior: AuditLog entry with action='scoring_batch_completed', client_id set, details with tag distribution_
    - _Preservation: Existing ActivityEvent and scoring logic unchanged_
    - _Requirements: 2.8_

  - [~] 3.7 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Audit Log Completeness After Fix
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior (each task creates AuditLog entries)
    - When this test passes, it confirms all 10 `log_system_action` calls are working correctly
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms audit gaps are fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_

  - [~] 3.8 Verify preservation tests still pass
    - **Property 2: Preservation** - Existing Audit Logging Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions in existing audit logging or query behavior)
    - Confirm all tests still pass after fix (no regressions)

- [ ] 4. Fix: Add composite database indexes via Alembic migration

  - [~] 4.1 Create Alembic migration with 4 composite indexes
    - Generate new migration file via `alembic revision --autogenerate -m "add_composite_indexes_audit_presence_karma_scrape"`
    - Add index: `CREATE INDEX ix_avatar_presence_avatar_activity ON avatar_subreddit_presence (avatar_id, last_activity_at DESC NULLS LAST)`
    - Add index: `CREATE INDEX ix_subreddit_karma_avatar_updated ON subreddit_karma (avatar_id, last_updated_at DESC)`
    - Add index: `CREATE INDEX ix_scrape_log_subreddit_scraped ON scrape_log (subreddit_id, scraped_at DESC)`
    - Add index: `CREATE INDEX ix_audit_log_action_created ON audit_log (action, created_at DESC)`
    - Include proper `upgrade()` and `downgrade()` functions (downgrade drops all 4 indexes)
    - _Bug_Condition: isBugCondition(input) where input.type == 'database_query' AND execution_plan == 'Seq Scan' on target tables_
    - _Expected_Behavior: Index Scan used for all 4 query patterns_
    - _Preservation: Existing indexes must not be dropped_
    - _Requirements: 2.9, 2.10, 2.11, 2.12_

  - [~] 4.2 Update model `__table_args__` to keep in sync with migration
    - In `app/models/avatar_subreddit_presence.py`: Add `Index("ix_avatar_presence_avatar_activity", "avatar_id", last_activity_at.desc())` to `__table_args__`
    - In `app/models/subreddit_karma.py`: Add `Index("ix_subreddit_karma_avatar_updated", "avatar_id", last_updated_at.desc())` to `__table_args__`
    - In `app/models/scrape_log.py`: Add `Index("ix_scrape_log_subreddit_scraped", "subreddit_id", scraped_at.desc())` to `__table_args__`
    - In `app/models/audit.py`: Add `Index("ix_audit_log_action_created", "action", created_at.desc())` to `__table_args__`
    - _Preservation: Existing indexes in __table_args__ must remain_
    - _Requirements: 2.9, 2.10, 2.11, 2.12_

  - [~] 4.3 Verify indexes exist and are used
    - Run migration: `alembic upgrade head`
    - Verify all 4 indexes exist via `SELECT indexname FROM pg_indexes WHERE tablename IN ('avatar_subreddit_presence', 'subreddit_karma', 'scrape_log', 'audit_log')`
    - Run `EXPLAIN ANALYZE` on representative queries to confirm Index Scan (not Seq Scan):
      - `SELECT * FROM avatar_subreddit_presence WHERE avatar_id = ? ORDER BY last_activity_at DESC`
      - `SELECT * FROM subreddit_karma WHERE avatar_id = ? ORDER BY last_updated_at DESC`
      - `SELECT * FROM scrape_log WHERE subreddit_id = ? ORDER BY scraped_at DESC`
      - `SELECT * FROM audit_log WHERE action = ? AND created_at BETWEEN ? AND ? ORDER BY created_at DESC`
    - _Requirements: 2.9, 2.10, 2.11, 2.12_

- [~] 5. Checkpoint - Ensure all tests pass
  - Run full test suite: `pytest tests/ -v`
  - Verify bug condition exploration test (task 1) passes
  - Verify preservation tests (task 2) pass
  - Verify no existing tests broken by the changes
  - Verify Alembic migration applies cleanly (`alembic upgrade head` + `alembic downgrade -1` + `alembic upgrade head`)
  - Ask the user if questions arise
