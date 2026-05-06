# Implementation Plan: Comment Performance Tracking

## Overview

Implement a periodic monitoring system that fetches Reddit metrics for posted comments, stores time-series snapshots, triggers alerts for problematic comments, and provides aggregation functions for effectiveness analysis. The implementation builds incrementally: data model → Reddit fetcher → service layer → Celery task → configuration seeding → tests.

## Tasks

- [ ] 1. Create PerformanceSnapshot model and Alembic migration
  - [ ] 1.1 Create the PerformanceSnapshot SQLAlchemy model
    - Create `reddit_saas/app/models/performance_snapshot.py` with the PerformanceSnapshot class
    - Include columns: id, comment_draft_id, avatar_id, client_id, score, reply_count, visibility_status, measured_at
    - Add ForeignKey references to comment_drafts, avatars, clients
    - Add relationship to CommentDraft and Avatar
    - Register the model in `reddit_saas/app/models/__init__.py`
    - _Requirements: 2.1, 6.1_

  - [ ] 1.2 Create Alembic migration for performance_snapshots table
    - Generate migration file `add_performance_snapshots_table.py`
    - Create table with all columns, primary key, and foreign keys
    - Add indexes: comment_draft_id, avatar_id, client_id
    - Add composite index on (comment_draft_id, measured_at DESC) for efficient latest-snapshot lookup
    - _Requirements: 2.1, 2.2_

  - [ ]* 1.3 Write unit tests for PerformanceSnapshot model
    - Test model instantiation with valid data
    - Test foreign key relationships resolve correctly
    - Test default values (visibility_status="visible", measured_at=server_default)
    - _Requirements: 2.1_

- [ ] 2. Implement CommentMetrics dataclass and fetch_comment_by_id in reddit.py
  - [ ] 2.1 Add CommentMetrics dataclass and fetch_comment_by_id function
    - Add `CommentMetrics` dataclass to `reddit_saas/app/services/reddit.py` with fields: score, reply_count, visibility_status
    - Implement `fetch_comment_by_id(comment_id: str) -> CommentMetrics | None`
    - Use PRAW to fetch comment by ID
    - Extract score, count direct replies, detect "[removed]"/"[deleted]" body text
    - Handle NotFound → visibility_status="deleted", Forbidden → visibility_status="removed"
    - Handle TooManyRequests → return None (caller retries)
    - Handle ServerError/RequestException → log and re-raise
    - Add structured logging matching existing patterns in reddit.py
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [ ]* 2.2 Write property test for comment metrics extraction
    - **Property 9: Comment metrics extraction**
    - **Validates: Requirements 7.2**

  - [ ]* 2.3 Write unit tests for fetch_comment_by_id
    - Test successful fetch returns correct CommentMetrics
    - Test NotFound maps to visibility_status="deleted"
    - Test Forbidden maps to visibility_status="removed"
    - Test TooManyRequests returns None
    - Test structured logging output format
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [ ] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Implement PerformanceTrackingService
  - [ ] 4.1 Create service file with get_trackable_comments
    - Create `reddit_saas/app/services/performance_tracking.py`
    - Implement `get_trackable_comments(db: Session) -> list[CommentDraft]`
    - Query CommentDraft where status="posted", posted_at within tracking_window_days
    - Exclude comments whose latest PerformanceSnapshot measured_at is less than snapshot_interval_hours ago
    - Read tracking_window_days and snapshot_interval_hours from SystemSettings with defaults
    - _Requirements: 1.1, 1.2, 1.3, 3.1, 3.2, 3.4, 8.2_

  - [ ]* 4.2 Write property test for comment eligibility filtering
    - **Property 1: Comment eligibility filtering**
    - **Validates: Requirements 1.1, 1.2, 1.3, 8.2**

  - [ ] 4.3 Implement create_snapshot method
    - Add `create_snapshot(db: Session, comment: CommentDraft, metrics: CommentMetrics) -> PerformanceSnapshot`
    - Create PerformanceSnapshot record with comment's avatar_id and client_id
    - Update CommentDraft.reddit_score with latest score
    - If visibility_status is "removed" or "deleted": set CommentDraft.is_deleted=True, set deleted_detected_at=now
    - Commit per-comment (individual transaction)
    - _Requirements: 2.1, 2.3, 2.4, 8.3_

  - [ ]* 4.4 Write property test for snapshot creation preserves all metrics
    - **Property 2: Snapshot creation preserves all metrics**
    - **Validates: Requirements 2.1, 6.1**

  - [ ]* 4.5 Write property test for snapshot history accumulation
    - **Property 3: Snapshot history accumulation**
    - **Validates: Requirements 2.2**

  - [ ]* 4.6 Write property test for CommentDraft field synchronization
    - **Property 4: CommentDraft field synchronization**
    - **Validates: Requirements 2.3, 2.4**

  - [ ] 4.7 Implement check_and_emit_alerts method
    - Add `check_and_emit_alerts(db: Session, comment: CommentDraft, snapshot: PerformanceSnapshot) -> list[ActivityEvent]`
    - Check if score < alert_threshold → create ActivityEvent with event_type="comment_alert", downvote warning message
    - Check if visibility changed from "visible" to "removed"/"deleted" → create ActivityEvent with removal message
    - Include avatar_id, comment_id, subreddit, score in event metadata
    - Deduplicate: query ActivityEvent to check if alert already exists for this comment + condition
    - Read alert_threshold from SystemSettings with default -2
    - Wrap in try/except so alert failures never crash the batch
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 3.3_

  - [ ]* 4.8 Write property test for downvote alert triggering
    - **Property 5: Downvote alert triggering**
    - **Validates: Requirements 4.1, 4.3**

  - [ ]* 4.9 Write property test for visibility change alert triggering
    - **Property 6: Visibility change alert triggering**
    - **Validates: Requirements 4.2**

  - [ ]* 4.10 Write property test for alert deduplication
    - **Property 7: Alert deduplication (idempotence)**
    - **Validates: Requirements 4.4**

  - [ ] 4.11 Implement aggregation functions
    - Add `get_effectiveness_by_engagement_mode(db: Session, client_id: UUID, window_days: int) -> list[dict]`
    - Add `get_effectiveness_by_comment_approach(db: Session, client_id: UUID, window_days: int) -> list[dict]`
    - Join PerformanceSnapshot with CommentDraft to group by engagement_mode / comment_approach
    - Compute avg_score, avg_reply_count, removal_rate per group
    - Filter by client_id and time window
    - _Requirements: 6.2, 6.3_

  - [ ]* 4.12 Write property test for aggregation correctness
    - **Property 8: Aggregation correctness**
    - **Validates: Requirements 6.2, 6.3**

- [ ] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Implement Celery task and beat schedule
  - [ ] 6.1 Create fetch_comment_performance Celery task
    - Create `reddit_saas/app/tasks/performance.py`
    - Import celery_app from worker.py
    - Implement `fetch_comment_performance()` task
    - Orchestrate: get_trackable_comments → for each comment: fetch_comment_by_id → create_snapshot → check_and_emit_alerts
    - Add configurable delay between API calls (perf_batch_delay_seconds from SystemSettings, default 2s)
    - Handle rate limit: exponential backoff (2^attempt, max 5 attempts), then abort remaining batch
    - Per-comment error handling: log and skip on failure, continue batch
    - Log batch summary at end: {checked, snapshots_created, alerts_triggered, errors}
    - Return summary dict
    - _Requirements: 1.4, 1.5, 8.1, 8.3, 8.4_

  - [ ] 6.2 Register task in worker.py beat_schedule
    - Add `"app.tasks.performance"` to the `include` list in celery_app configuration
    - Add beat_schedule entry `"fetch-comment-performance"` with schedule matching snapshot_interval (every 6 hours via crontab)
    - _Requirements: 1.4_

  - [ ]* 6.3 Write unit tests for Celery task
    - Test task is registered in celery_app
    - Test task calls service methods in correct order
    - Test rate limit triggers exponential backoff
    - Test per-comment error doesn't abort batch
    - Test batch summary logging
    - _Requirements: 1.4, 1.5, 8.1, 8.4_

- [ ] 7. Seed SystemSettings values
  - [ ] 7.1 Add performance tracking settings to seed data
    - Add seed entries in `reddit_saas/app/seed.py` (or equivalent seed mechanism) for:
      - `perf_tracking_window_days` = "7" (group: "performance")
      - `perf_snapshot_interval_hours` = "6" (group: "performance")
      - `perf_alert_score_threshold` = "-2" (group: "performance")
      - `perf_batch_delay_seconds` = "2" (group: "performance")
    - Include descriptions for each setting
    - _Requirements: 3.1, 3.2, 3.3_

- [ ] 8. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Write integration tests
  - [ ]* 9.1 Write integration test for full batch run
    - Mock PRAW client, create test CommentDrafts with status="posted"
    - Run fetch_comment_performance task
    - Assert PerformanceSnapshot records created
    - Assert CommentDraft fields updated
    - Assert ActivityEvents created for alert conditions
    - Assert batch summary values correct
    - _Requirements: 1.4, 2.1, 2.3, 4.1, 8.3, 8.4_

  - [ ]* 9.2 Write integration test for phase evaluation with snapshot data
    - Create PerformanceSnapshot records with known scores
    - Verify PhaseEvaluator computes correct avg_comment_score from snapshots
    - Verify PhaseEvaluator computes correct comment_survival_rate
    - _Requirements: 5.1, 5.2, 5.3_

- [ ] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The implementation follows the existing project patterns: per-commit transactions (like scraping.py), structured logging, SystemSettings for configuration, ActivityEvent for alerts
