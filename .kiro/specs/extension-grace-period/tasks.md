# Implementation Plan: Extension Grace Period

## Overview

Add a configurable grace period to the Extension API so overdue EPG tasks remain available to executors for a window beyond the original deadline (default 3 hours). A new `grace_period_evaluator` service gates grace-period tasks through three safety checks. The expire service respects the extended deadline, and the API response is enriched with grace-period metadata and ordering.

## Tasks

- [ ] 1. System setting and core evaluator service
  - [ ] 1.1 Add `epg_grace_period_hours` to DEFAULTS in `app/services/settings.py`
    - Add entry in the `email_tasks` group after `epg_slot_window_hours`
    - Value: `"3"`, secret: False, desc: "Grace period hours added to EPG task deadline for extension. Tasks remain available this long past deadline if safety conditions pass. 0 = disabled."
    - _Requirements: 1.1, 1.2, 1.3_

  - [ ] 1.2 Create `app/services/grace_period_evaluator.py`
    - Implement `get_grace_period_hours(db)` — reads setting, returns int (default 3, treat negative as 0)
    - Implement `compute_grace_deadline(task, grace_hours)` — returns `task.deadline + timedelta(hours=grace_hours)`
    - Implement `is_in_grace_period(task, grace_hours, now=None)` — True when `deadline < now < grace_deadline`
    - Implement `evaluate_safety_conditions(db, task, now=None)` — returns `(bool, reason_or_None)`. Checks: thread liveness, dangerous hours, daily budget
    - Implement `grace_period_remaining_minutes(task, grace_hours, now=None)` — returns int minutes remaining
    - _Requirements: 1.1, 1.2, 1.3, 3.1, 3.2, 3.3, 3.4_

  - [ ]* 1.3 Write unit tests for `grace_period_evaluator`
    - `tests/test_grace_period_evaluator.py`
    - Test `get_grace_period_hours`: default when missing, configured value, 0 disables
    - Test `compute_grace_deadline`: correct arithmetic
    - Test `is_in_grace_period`: before deadline=False, in window=True, past grace=False, grace_hours=0=False
    - Test `evaluate_safety_conditions`: mock thread liveness, timing engine, budget checks — verify each exclusion
    - Test `grace_period_remaining_minutes`: correct computation, minimum 0
    - _Requirements: 1.1, 1.2, 1.3, 3.1, 3.2, 3.3, 3.4_

- [ ] 2. Modify expire service to respect grace deadline
  - [ ] 2.1 Update `expire_overdue_tasks()` in `app/services/execution_tasks.py`
    - Import `get_grace_period_hours` from grace_period_evaluator
    - Read `grace_hours` from system settings
    - When `grace_hours > 0`: expire tasks where `deadline < now - timedelta(hours=grace_hours)` (i.e., past grace deadline)
    - When `grace_hours == 0`: preserve original behavior (`deadline < now`)
    - Update log message to include `grace_hours` parameter
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [ ]* 2.2 Write unit tests for modified `expire_overdue_tasks`
    - Test: grace_hours=3, task 1h past deadline → NOT expired
    - Test: grace_hours=3, task 4h past deadline → expired
    - Test: grace_hours=0, task 1min past deadline → expired (original behavior)
    - Test: guard still works — task with submitted_url not expired
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [ ] 3. Checkpoint - Core service layer complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Modify Extension API to include grace-period tasks
  - [ ] 4.1 Update `get_tasks()` in `app/routes/extension_api.py` — query expansion and filtering
    - Import grace_period_evaluator functions
    - Read `grace_hours` and compute `now` at top of handler
    - Expand deadline filter: when `grace_hours > 0`, include tasks where `deadline > now - timedelta(hours=grace_hours)` (captures both on-time and grace-window tasks)
    - After query, partition results: for each task past its original deadline, run `evaluate_safety_conditions` — exclude on failure, include on pass
    - Skip safety re-evaluation for tasks already ASSIGNED to this node (Requirement 6.2)
    - _Requirements: 2.1, 2.2, 3.4, 3.5, 6.2_

  - [ ] 4.2 Update `get_tasks()` response payload — add grace metadata fields
    - For each task in the response, compute and add:
      - `is_grace_period`: bool — True if `task.deadline < now` and within grace window
      - `grace_period_remaining_minutes`: int or None — minutes until grace deadline (None if not in grace)
      - `grace_deadline`: str or None — ISO 8601 timestamp of grace deadline (None if not in grace)
    - For on-time tasks: `is_grace_period=False`, other two fields `None`
    - _Requirements: 2.3, 2.4, 5.1, 5.2_

  - [ ] 4.3 Update `get_tasks()` response ordering
    - Replace current SQL ordering with post-filter sort using sort key: `(bucket, scheduled_at)`
    - Bucket 0: on-time content tasks (not past deadline, not diagnostic)
    - Bucket 1: grace-period content tasks (past deadline, within grace window)
    - Bucket 2: diagnostic tasks (priority == "diagnostic")
    - Within each bucket, order by `scheduled_at` ascending (NULLs last)
    - _Requirements: 5.3_

  - [ ]* 4.4 Write integration tests for grace-period Extension API
    - `tests/test_extension_grace_period.py`
    - Test: task within grace window + all safety pass → included with `is_grace_period=True`
    - Test: task past grace deadline → excluded
    - Test: task within grace + thread dead → excluded
    - Test: task within grace + dangerous hours → excluded
    - Test: task within grace + budget exhausted → excluded
    - Test: grace_hours=0 → task past deadline excluded (disabled behavior)
    - Test: on-time task → `is_grace_period=False`, metadata fields None
    - Test: ordering — on-time before grace before diagnostic
    - Test: ASSIGNED task past deadline → not re-evaluated, still returned
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5, 5.1, 5.2, 5.3, 6.2_

- [ ] 5. Checkpoint - Extension API complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Grace period task lifecycle handling
  - [ ] 6.1 Handle lease expiry re-evaluation in extension lease task
    - In the extension lease expiry logic (likely `app/tasks/extension_tasks.py`), when a grace-period task's lease expires, ensure the task is only re-offered if safety conditions still pass
    - If task was ASSIGNED and lease expired: reset to CREATED, but on next `get_tasks()` call the safety check in step 4.1 will automatically re-evaluate
    - No special code needed if the filtering in 4.1 is correct — verify this is the case and add a comment documenting the behavior
    - _Requirements: 6.1, 6.3_

- [ ] 7. Final checkpoint - All tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- No database migration needed — grace deadline is computed dynamically from `ExecutionTask.deadline` + system setting
- Safety checks reuse existing services: `thread_liveness.check_and_filter_thread`, `timing_engine.is_safe_posting_time`, `epg_executor.get_budget_used_today`
- The grace period evaluator follows the project's service pattern (pure functions, not a class)
- Implementation language: Python (matches existing codebase)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "2.1"] },
    { "id": 2, "tasks": ["2.2", "4.1"] },
    { "id": 3, "tasks": ["4.2", "4.3"] },
    { "id": 4, "tasks": ["4.4", "6.1"] }
  ]
}
```
