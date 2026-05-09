# Implementation Plan: Avatar Subreddit Presence Map (Phase 1)

## Overview

Implement the Avatar Subreddit Presence Map feature (Requirement 11) as the first deliverable of the Avatar Intelligence & Learning system. This adds a dedicated "Presence" tab to the avatar detail page showing all subreddits where an avatar has commented, with per-subreddit metrics (count, karma, last activity). Includes manual scan trigger, async Celery task, HTMX polling, weekly auto-scan, and staleness detection.

## Tasks

- [x] 1. Database model and migration
  - [x] 1.1 Create `AvatarSubredditPresence` model in `app/models/avatar_subreddit_presence.py`
    - Define SQLAlchemy 2.0 model with: id (UUID PK), avatar_id (FK → avatars.id CASCADE), subreddit_name (VARCHAR 255), comment_count (int), total_karma (int), last_activity_at (TIMESTAMPTZ), created_at, updated_at
    - Add unique constraint on (avatar_id, subreddit_name)
    - Add index on avatar_id
    - Register model in `app/models/__init__.py`
    - _Requirements: 11.1, 11.2_

  - [x] 1.2 Add presence columns to Avatar model
    - Add `presence_last_scanned_at: datetime | None` column to `app/models/avatar.py`
    - Add `presence_scan_status: str | None` column (VARCHAR 20, nullable)
    - _Requirements: 11.5, 11.8_

  - [x] 1.3 Create Alembic migration
    - Generate migration that creates `avatar_subreddit_presence` table with all columns, constraints, and indexes
    - Add `presence_last_scanned_at` and `presence_scan_status` columns to `avatars` table
    - Verify migration runs forward and backward cleanly
    - _Requirements: 11.1, 11.2, 11.5, 11.8_

- [x] 2. Service layer — pure logic and data access
  - [x] 2.1 Create `app/services/presence.py` with `aggregate_comments_by_subreddit` function
    - Pure function: takes list of comment dicts (each with `subreddit`, `score`, `created_utc`) and returns list of dicts with `subreddit_name`, `comment_count`, `total_karma`, `last_activity_at`
    - Group by subreddit, compute count, sum karma, find max timestamp per subreddit
    - No side effects, no DB access — pure aggregation logic
    - _Requirements: 11.4_

  - [ ]* 2.2 Write property test for comment aggregation (Property 3)
    - **Property 3: Comment aggregation produces correct subreddit distribution**
    - Use Hypothesis to generate arbitrary lists of comments with varying subreddits, karma values, and timestamps
    - Assert: one entry per unique subreddit, comment_count == count of comments in that subreddit, total_karma == sum of scores, last_activity_at == max timestamp
    - **Validates: Requirements 11.4**

  - [x] 2.3 Implement `is_presence_stale` function in `app/services/presence.py`
    - Takes `last_scanned_at: datetime | None`, returns `True` if None or older than 7 days from now
    - Pure function with clear threshold behavior
    - _Requirements: 11.9_

  - [ ]* 2.4 Write property test for staleness detection (Property 4)
    - **Property 4: Staleness detection respects 7-day threshold**
    - Use Hypothesis to generate arbitrary datetimes; assert `is_presence_stale` returns True iff timestamp is >7 days ago or None
    - **Validates: Requirements 11.9**

  - [x] 2.5 Implement `get_avatar_presence` function in `app/services/presence.py`
    - Query `AvatarSubredditPresence` records for a given avatar_id
    - Accept `sort_by` parameter: "comment_count" (default), "avg_karma", "last_activity_at"
    - Return records sorted descending by the chosen key
    - Compute `avg_karma` as `total_karma / comment_count` (handle division by zero)
    - _Requirements: 11.1, 11.3_

  - [ ]* 2.6 Write property test for presence list sorting (Property 2)
    - **Property 2: Presence list sorting is correct**
    - Use Hypothesis to generate lists of presence records with varying counts/karma/dates
    - Assert: for each valid sort key, returned list is in descending order by that key
    - **Validates: Requirements 11.3**

  - [x] 2.7 Implement `scan_avatar_presence` function in `app/services/presence.py`
    - Fetch avatar's recent comments via PRAW (`redditor.comments.new(limit=100)`)
    - Call `aggregate_comments_by_subreddit` on the raw comment data
    - Upsert results into `avatar_subreddit_presence` table (update existing rows, insert new ones)
    - Update avatar's `presence_last_scanned_at` to now and `presence_scan_status` to "completed"
    - Handle errors: set status to "failed" on exception, preserve existing data
    - _Requirements: 11.4, 11.6, 11.7_

  - [ ]* 2.8 Write unit tests for `scan_avatar_presence`
    - Mock PRAW redditor.comments.new to return test data
    - Verify DB records are created correctly
    - Verify upsert behavior (second scan updates, doesn't duplicate)
    - Verify error handling (PRAW exception → status "failed", existing data preserved)
    - _Requirements: 11.4, 11.6_

- [x] 3. Checkpoint — Core logic verified
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Celery task for async scan
  - [x] 4.1 Create `app/tasks/presence.py` with `scan_avatar_presence_task`
    - Celery task (bind=True, max_retries=3) that calls `scan_avatar_presence` service
    - Set avatar `presence_scan_status` to "running" at start
    - On success: status → "completed"
    - On failure: status → "failed", retry with exponential backoff (60s × 2^attempt)
    - Log start/completion/failure with avatar_id
    - _Requirements: 11.4, 11.5_

  - [x] 4.2 Create `scan_all_avatars_presence_task` in `app/tasks/presence.py`
    - Celery task that queries all active, non-frozen avatars
    - For each avatar, dispatch `scan_avatar_presence_task` (avoid blocking)
    - Log batch summary (count dispatched, any skipped)
    - _Requirements: 11.7_

  - [x] 4.3 Register weekly schedule in Celery Beat config
    - Add `scan_all_avatars_presence` to the periodic task schedule (weekly, e.g., Sunday 02:00 UTC)
    - Ensure it's registered in `app/tasks/worker.py` or scheduler config
    - _Requirements: 11.7_

- [x] 5. API endpoints
  - [x] 5.1 Add `POST /admin/avatars/{id}/scan-presence` endpoint in `app/routes/admin.py`
    - Check avatar exists (404 if not)
    - Idempotency: if `presence_scan_status` is "pending" or "running", return current status without creating new task
    - Set `presence_scan_status` to "pending", dispatch `scan_avatar_presence_task`
    - Return HTMX partial (presence section with "pending" status indicator)
    - Require superuser auth
    - _Requirements: 11.4, 11.5_

  - [x] 5.2 Add `GET /admin/avatars/{id}/presence-partial` endpoint in `app/routes/admin.py`
    - Query presence records via `get_avatar_presence` service
    - Accept `sort_by` query param (default: "comment_count")
    - Compute `is_stale` from `presence_last_scanned_at`
    - Render `partials/avatar_presence.html` template
    - Require superuser auth
    - _Requirements: 11.1, 11.2, 11.3, 11.8, 11.9, 11.10_

  - [x] 5.3 Add `GET /admin/avatars/{id}/presence-data` JSON endpoint in `app/routes/admin.py`
    - Return presence records as JSON array (for future API consumers)
    - Include: subreddit_name, comment_count, avg_karma, total_karma, last_activity_at, reddit_url
    - Accept `sort_by` query param
    - Require superuser auth
    - _Requirements: 11.2, 11.3_

  - [ ]* 5.4 Write property test for presence serialization (Property 1)
    - **Property 1: Presence record contains all required fields**
    - Use Hypothesis to generate valid AvatarSubredditPresence records
    - Assert serialized output contains: subreddit_name, comment_count, avg_karma, last_activity_at, reddit_url (format: `https://reddit.com/r/{name}`)
    - **Validates: Requirements 11.2**

- [x] 6. HTMX partial template
  - [x] 6.1 Create `app/templates/partials/avatar_presence.html`
    - Presence table: subreddit name (linked to Reddit), comment count, avg karma, last activity date
    - Sort controls (buttons for comment_count / avg_karma / last_activity_at) using `hx-get` with `sort_by` param
    - "Scan Subreddit Presence" button: `hx-post` to scan-presence endpoint, shows spinner while pending/running
    - "Last updated" timestamp with stale indicator (amber badge if >7 days)
    - Empty state: "No presence data yet" with prominent "Scan Now" button and explanation text
    - Task status: show "Scanning..." with `hx-trigger="every 3s"` polling while status is pending/running
    - Match existing dark theme (admin_base.html, Tailwind classes consistent with other partials)
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.8, 11.9, 11.10_

- [x] 7. Avatar detail page integration
  - [x] 7.1 Add "Presence" tab to `app/templates/admin_avatar_detail.html`
    - Add new tab button with `data-avatar-detail-tab="presence"` after the "Analytics" tab
    - Add corresponding panel `data-avatar-detail-panel="presence"` with `hx-get` to load presence partial on tab open
    - Use `hx-trigger="intersect once"` or load on tab click (lazy load pattern)
    - _Requirements: 11.1_

  - [x] 7.2 Update `admin_avatar_detail` route to pass presence context
    - Add `presence_stale` flag to template context (computed via `is_presence_stale`)
    - Add `presence_scan_status` to context for initial render
    - No need to pass full presence data (loaded via HTMX partial)
    - _Requirements: 11.8, 11.9_

- [x] 8. Checkpoint — Full feature integration verified
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Integration tests
  - [ ]* 9.1 Write integration tests for presence scan flow
    - Test full flow: POST scan-presence → task executes (mocked PRAW) → DB updated → GET presence-partial returns correct HTML
    - Test idempotency: second POST while scan is running returns existing status
    - Test empty state: GET presence-partial with no data returns empty state HTML
    - Test stale indicator: presence older than 7 days shows amber badge
    - _Requirements: 11.4, 11.5, 11.6, 11.9, 11.10_

  - [ ]* 9.2 Write integration tests for weekly scheduler
    - Test `scan_all_avatars_presence_task` dispatches tasks for active avatars only
    - Test frozen avatars are skipped
    - Test inactive avatars are skipped
    - _Requirements: 11.7_

- [x] 10. Final checkpoint — All tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document using Hypothesis
- Unit tests validate specific examples and edge cases
- The design uses existing Celery infrastructure (not SQS) since the project still has Celery running
- PRAW integration reuses existing `get_reddit_client()` from `app/services/reddit.py`
- All new endpoints require `require_superuser` dependency (existing admin auth pattern)
- HTMX partial follows existing conventions (see `partials/avatar_profile_analytics.html` for similar lazy-load pattern)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3"] },
    { "id": 2, "tasks": ["2.1", "2.3"] },
    { "id": 3, "tasks": ["2.2", "2.4", "2.5"] },
    { "id": 4, "tasks": ["2.6", "2.7"] },
    { "id": 5, "tasks": ["2.8", "4.1"] },
    { "id": 6, "tasks": ["4.2", "4.3", "5.1"] },
    { "id": 7, "tasks": ["5.2", "5.3"] },
    { "id": 8, "tasks": ["5.4", "6.1"] },
    { "id": 9, "tasks": ["7.1", "7.2"] },
    { "id": 10, "tasks": ["9.1", "9.2"] }
  ]
}
```
