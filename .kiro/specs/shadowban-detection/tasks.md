# Implementation Plan: Shadowban Detection

## Overview

Implement visibility-based shadowban detection for Reddit avatars. The system adds a Health Checker service that periodically verifies avatar content visibility via unauthenticated Reddit API checks, classifies avatars into a 5-state health model, integrates with the pipeline to skip unhealthy avatars, and surfaces health status in the admin panel.

Implementation language: Python (FastAPI, SQLAlchemy, Celery, PRAW, Hypothesis).

## Tasks

- [x] 1. Data model and schema setup
  - [x] 1.1 Create HealthStatus enum module
    - Create `app/models/health_status.py` with `HealthStatus(str, enum.Enum)` containing ACTIVE, LIMITED, SHADOWBANNED, SUSPENDED, UNKNOWN values
    - _Requirements: 1.1_

  - [x] 1.2 Add health fields to Avatar model
    - Add `health_status` (String(20), default "unknown"), `health_status_changed_at` (DateTime tz, nullable), `health_check_details` (JSONB, nullable), `consecutive_check_failures` (Integer, default 0) to `app/models/avatar.py`
    - Import and reference `HealthStatus` enum for documentation/validation
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 1.3 Create Alembic migration for new Avatar columns
    - Generate migration adding `health_status` VARCHAR(20) DEFAULT 'unknown', `health_status_changed_at` TIMESTAMPTZ NULL, `health_check_details` JSONB NULL, `consecutive_check_failures` INTEGER DEFAULT 0 to `avatars` table
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 1.4 Register health check settings in DEFAULTS
    - Add 8 keys to `app/services/settings.py` DEFAULTS dict under group `"health_check"`: `health_check_interval_hours`, `health_check_min_comments`, `health_check_visibility_threshold`, `health_check_rate_limit_delay_seconds`, `health_check_max_failures_before_unknown`, `health_check_max_failures_before_limited`, `health_check_comment_lookback_days`, `health_check_max_comments_to_sample`
    - _Requirements: 8.1, 8.5_

- [x] 2. Core Health Checker service
  - [x] 2.1 Implement profile accessibility check
    - Create `app/services/health_checker.py` with `check_profile_accessibility(username: str) -> tuple[str | None, str]`
    - Use unauthenticated PRAW redditor lookup; return SUSPENDED on 404/403/is_suspended=true; return None (proceed to visibility check) on 200+active; retain previous status on network/unexpected errors
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 2.2 Implement comment visibility check
    - Add `check_comment_visibility(username: str, max_comments: int, lookback_days: int) -> tuple[int, int]` to health_checker.py
    - Fetch avatar's recent comments from unauthenticated session, count how many are visible vs. total sampled
    - _Requirements: 2.1, 2.2_

  - [x] 2.3 Implement health status classification
    - Add `classify_health_status(visibility_ratio: float, threshold: float) -> str` pure function
    - ratio == 0 → SHADOWBANNED, 0 < ratio < threshold → LIMITED, ratio >= threshold → ACTIVE
    - _Requirements: 2.4, 2.5, 2.6_

  - [ ]* 2.4 Write property test for classification (Property 1)
    - **Property 1: Visibility ratio classification is correct and exhaustive**
    - Test with Hypothesis: for any ratio in [0.0, 1.0] and valid threshold in (0.0, 1.0], classification is deterministic and covers all cases
    - **Validates: Requirements 2.4, 2.5, 2.6**

  - [x] 2.5 Implement single avatar health check orchestrator
    - Add `check_avatar_health(db: Session, avatar: Avatar) -> HealthCheckResult` that orchestrates: profile check → visibility check → classification → failure counter logic → persist results → trigger side effects (freeze + audit)
    - Handle insufficient comments (< min_comments) by retaining previous status
    - Handle API errors by retaining previous status and incrementing consecutive_check_failures
    - Apply failure thresholds: max_failures_before_limited → LIMITED, max_failures_before_unknown → UNKNOWN
    - Reset consecutive_check_failures to 0 on successful check
    - _Requirements: 1.6, 1.7, 2.3, 2.7, 2.8, 3.6_

  - [ ]* 2.6 Write property tests for API error handling and failure thresholds (Properties 3, 4, 5, 6)
    - **Property 3: API errors preserve previous status and increment failures**
    - **Property 4: Consecutive failure thresholds trigger correct transitions**
    - **Property 5: Successful check resets failure counter**
    - **Property 6: Insufficient comments preserves previous status**
    - **Validates: Requirements 1.6, 1.7, 2.3, 2.7, 2.8, 3.6**

  - [ ]* 2.7 Write property test for profile inaccessibility (Property 2)
    - **Property 2: Profile inaccessibility yields SUSPENDED classification**
    - Test with Hypothesis: for any avatar, 404/403/is_suspended=true → SUSPENDED, no visibility check performed
    - **Validates: Requirements 3.2, 3.3, 3.4**

- [x] 3. Checkpoint — Core service tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Batch processing and Celery task
  - [x] 4.1 Implement batch health check runner
    - Add `run_health_check_batch(db: Session) -> dict` to health_checker.py
    - Select eligible avatars (active=True, is_frozen=False, last_health_check older than interval or null)
    - Space checks by `health_check_rate_limit_delay_seconds` when batch > 10
    - Isolate per-avatar failures (continue processing remaining avatars on error)
    - Log batch summary: duration, checked count, errors, status changes
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [ ]* 4.2 Write property tests for batch processing (Properties 9, 10)
    - **Property 9: Batch fault isolation** — if avatar K fails, avatars K+1..N still checked
    - **Property 10: Eligible avatar selection respects all filters** — only active, non-frozen, stale avatars selected
    - **Validates: Requirements 4.2, 4.4**

  - [x] 4.3 Create Celery periodic task
    - Create `app/tasks/health_check.py` with `health_check_all_avatars` task (name="health_check_all_avatars", bind=True, max_retries=1)
    - Register in Celery Beat schedule using existing `schedule_avatar_health_hours` setting
    - _Requirements: 4.1_

- [x] 5. Status transition side effects
  - [x] 5.1 Implement auto-freeze on unhealthy status
    - In `check_avatar_health`, when health_status transitions to SHADOWBANNED or SUSPENDED: set `is_frozen=True`, `freeze_reason` to the new status value, `frozen_at` to current UTC timestamp
    - _Requirements: 9.4_

  - [x] 5.2 Implement audit logging for status changes
    - On status change: create audit log entry with action "health_status_changed", entity_type "avatar", entity_id, details containing previous_status, new_status, reddit_username, detection_method
    - On batch completion: create audit log entry with action "health_check_batch_completed", details with checked count, changes, errors
    - Audit failures must not interrupt health check operation (try/except with app logger fallback)
    - _Requirements: 7.1, 7.2, 7.4, 7.5_

  - [ ]* 5.3 Write property test for status transition side effects (Property 8)
    - **Property 8: Status transition triggers freeze and audit log**
    - For any avatar transitioning to SHADOWBANNED/SUSPENDED: is_frozen=True, freeze_reason set, audit log created with correct fields
    - **Validates: Requirements 7.1, 7.4, 9.4**

  - [x] 5.4 Implement pending draft warning flag
    - When health_status transitions to SHADOWBANNED or SUSPENDED, set a warning flag on all pending drafts for that avatar
    - _Requirements: 5.4_

- [x] 6. Pipeline integration
  - [x] 6.1 Update generate_comments avatar filter
    - In `app/tasks/ai_pipeline.py` `generate_comments` task, add `health_status not in ("shadowbanned", "suspended")` to the client_avatars filter (alongside existing `is_frozen` and `is_shadowbanned` checks)
    - Log warning when avatar excluded due to health_status
    - Log warning when all avatars excluded for a client
    - _Requirements: 5.1, 5.2, 5.5, 5.6_

  - [x] 6.2 Update generate_hobby_comments avatar filter
    - In `app/tasks/ai_pipeline.py` `generate_hobby_comments` task, add health_status check after existing is_shadowbanned check
    - _Requirements: 5.3, 9.1, 9.2_

  - [x] 6.3 Update generate_posts avatar filter
    - In `app/tasks/ai_pipeline.py` `generate_posts` task, add health_status filter to client_avatars list comprehension
    - _Requirements: 9.3_

  - [ ]* 6.4 Write property test for pipeline exclusion (Property 7)
    - **Property 7: Unhealthy avatars are excluded from all pipeline activities**
    - For any avatar with SHADOWBANNED/SUSPENDED status: excluded from professional, hobby, and all warming phase activities
    - **Validates: Requirements 5.1, 5.2, 5.3, 9.1, 9.2, 9.3**

- [x] 7. Checkpoint — Pipeline integration tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Admin panel health indicators
  - [x] 8.1 Add health status badge to avatar list view
    - Update avatar list template to display color-coded badge: ACTIVE=green, LIMITED=yellow, SHADOWBANNED=red, SUSPENDED=red, UNKNOWN=grey
    - Display relative time since last health check ("2h ago", "Never checked")
    - _Requirements: 6.1, 6.5_

  - [x] 8.2 Add "Attention Required" section to avatar list
    - Display avatars with SHADOWBANNED or SUSPENDED status in a prominent section at top of avatar list
    - Hide section when no avatars need attention
    - _Requirements: 6.3, 6.4_

  - [x] 8.3 Add health summary widget to operations dashboard
    - Add widget showing counts per health_status category (ACTIVE, LIMITED, SHADOWBANNED, SUSPENDED, UNKNOWN)
    - _Requirements: 6.2_

  - [ ]* 8.4 Write property test for health summary consistency (Property 11)
    - **Property 11: Health summary counts are consistent**
    - Sum of all category counts equals total active avatars
    - **Validates: Requirements 6.2**

  - [x] 8.5 Implement "Check Now" endpoint
    - Add `POST /admin/avatars/{avatar_id}/health-check` HTMX endpoint to `app/routes/admin.py`
    - Trigger manual health check, return updated badge partial
    - Create audit log entry with action "health_check_manual" and operator's user_id
    - Handle errors gracefully (display error message, re-enable button)
    - _Requirements: 6.6, 6.7, 7.3_

- [x] 9. Settings validation and admin UI
  - [x] 9.1 Implement health check parameter validation
    - Add validation logic for health check settings: interval_hours >= 1, min_comments >= 1, visibility_threshold 0.0-1.0, rate_limit_delay >= 0, max_failures_before_unknown >= 1, max_failures_before_limited >= 1, comment_lookback_days >= 1, max_comments_to_sample >= 1
    - Reject invalid values with error message, keep previous value
    - _Requirements: 8.4_

  - [ ]* 9.2 Write property test for settings validation (Property 12)
    - **Property 12: Setting validation rejects out-of-range values**
    - For any parameter update with value outside allowed range: rejected, previous value unchanged
    - **Validates: Requirements 8.4**

  - [x] 9.3 Add health check settings section to admin Settings page
    - Display all 8 health check parameters in a "Health Check" group with input fields, current values, and descriptions
    - Ensure runtime reads (not cached across task runs) per Requirement 8.2
    - _Requirements: 8.1, 8.2, 8.3_

- [x] 10. Final checkpoint — Full test suite passes
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (12 properties total)
- Unit tests validate specific examples and edge cases
- The existing `is_shadowbanned` field on Avatar is a legacy boolean; the new `health_status` field supersedes it with richer classification
- Pipeline integration (task 6) replaces the existing `is_shadowbanned` check with the new `health_status` check
- Settings are read at runtime per task execution (not cached across Celery task runs) per Requirement 8.2

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.4"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["2.1", "2.2", "2.3"] },
    { "id": 3, "tasks": ["2.4", "2.5"] },
    { "id": 4, "tasks": ["2.6", "2.7", "4.1"] },
    { "id": 5, "tasks": ["4.2", "4.3", "5.1", "5.2"] },
    { "id": 6, "tasks": ["5.3", "5.4", "6.1", "6.2", "6.3"] },
    { "id": 7, "tasks": ["6.4", "8.1", "8.2", "8.3"] },
    { "id": 8, "tasks": ["8.4", "8.5", "9.1"] },
    { "id": 9, "tasks": ["9.2", "9.3"] }
  ]
}
```
