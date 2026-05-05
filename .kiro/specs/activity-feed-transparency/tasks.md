# Implementation Plan: Activity Feed & Client Transparency

## Overview

This plan implements operational transparency for the Reddit Marketing SaaS platform. The work is organized in incremental steps: first the data layer (models + migration), then the service layer, then pipeline instrumentation, then routes and templates, and finally wiring everything together. Each step builds on the previous one and ends with integration into the running system.

## Tasks

- [x] 1. Create new data models and Alembic migration
  - [x] 1.1 Create `app/models/activity_event.py` with the `ActivityEvent` model
    - Define `ActivityEvent` class with fields: `id` (UUID PK), `client_id` (nullable FK to clients), `event_type` (VARCHAR(50), NOT NULL), `message` (TEXT, NOT NULL), `metadata` (JSONB, nullable), `created_at` (TIMESTAMPTZ, server_default=func.now())
    - Use SQLAlchemy 2.0 `mapped_column` style consistent with existing models
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 1.2 Create `app/models/scrape_log.py` with the `ScrapeLog` model
    - Define `ScrapeLog` class with fields: `id` (UUID PK), `client_id` (FK to clients, NOT NULL), `subreddit_name` (VARCHAR(255), NOT NULL), `scraped_at` (TIMESTAMPTZ, server_default=func.now()), `posts_found` (INTEGER, NOT NULL), `posts_new` (INTEGER, NOT NULL), `errors` (TEXT, nullable), `duration_ms` (INTEGER, NOT NULL)
    - Add composite index `ix_scrape_log_client_sub_time` on `(client_id, subreddit_name, scraped_at)`
    - _Requirements: 4.1, 4.2_

  - [x] 1.3 Add `last_scraped_at` column to `ClientSubreddit` model in `app/models/subreddit.py`
    - Add `last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)`
    - _Requirements: 6.1_

  - [x] 1.4 Register new models in `app/models/__init__.py`
    - Import `ActivityEvent` and `ScrapeLog` and add to `__all__`
    - This ensures Alembic's `import *` in `env.py` picks them up
    - _Requirements: 10.1, 10.2_

  - [x] 1.5 Create Alembic migration for `activity_events`, `scrape_log` tables and `last_scraped_at` column
    - Create a single migration file in `reddit_saas/alembic/versions/`
    - Upgrade: create `activity_events` table, create `scrape_log` table with composite index, add `last_scraped_at` to `client_subreddits`
    - Downgrade: drop `activity_events`, drop `scrape_log`, remove `last_scraped_at` from `client_subreddits`
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [ ]* 1.6 Write unit tests for new models (`tests/test_transparency_models.py`)
    - Test `ActivityEvent` creation with all fields, with null `client_id`, with required fields validation
    - Test `ScrapeLog` creation with all fields, with null `errors` (success case), with error message (failure case)
    - Test `ClientSubreddit.last_scraped_at` column exists and accepts datetime values
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 4.1, 6.1_

- [x] 2. Implement transparency service layer (`app/services/transparency.py`)
  - [x] 2.1 Implement `record_activity_event()` function
    - Accept `db: Session`, `event_type: str`, `message: str`, `client_id: uuid.UUID | None`, `metadata: dict | None`
    - Insert an `ActivityEvent` record and commit
    - Return the created `ActivityEvent` instance
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 9.1_

  - [x] 2.2 Implement `get_activity_events()` function
    - Accept `db`, `client_id` (optional), `event_type` (optional), `limit` (default 50), `offset` (default 0)
    - Query `ActivityEvent` with optional filters, order by `created_at DESC`
    - Return `list[dict]` (plain dicts, not ORM objects)
    - _Requirements: 3.1, 3.4, 8.1, 9.1, 9.4_

  - [x] 2.3 Implement `get_pipeline_stats()` function
    - Accept `db`, `client_id`
    - Compute: thread counts (total, last_24h, last_7d), tag distribution (engage, monitor, skip, unscored), draft status breakdown (pending, approved, rejected, posted), AI cost totals (total + by operation)
    - Return a single `dict` with nested structure
    - _Requirements: 7.2, 7.3, 7.4, 7.5, 9.2, 9.4_

  - [x] 2.4 Implement `get_scrape_freshness()` function
    - Accept `db`, `client_id`
    - Query active `ClientSubreddit` records joined with `ScrapeLog` aggregations
    - Return `list[dict]` with `subreddit_name`, `last_scraped_at`, `total_posts_found`, `avg_posts_new`, `is_stale` (True if `last_scraped_at` is None or > 24h ago)
    - _Requirements: 7.6, 9.3, 9.4_

  - [ ]* 2.5 Write property test: Activity event retrieval respects filters and ordering (`tests/test_transparency_service.py`)
    - **Property 1: Activity event retrieval respects all filters and ordering**
    - Generate random ActivityEvent records with varying client_id, event_type, created_at
    - For any combination of filters (client_id, event_type, limit, offset), verify results match all filters, are in reverse chronological order, and result size ≤ limit
    - **Validates: Requirements 1.3, 3.1, 3.4, 8.1, 9.1**

  - [ ]* 2.6 Write property test: Staleness detection is correct (`tests/test_transparency_service.py`)
    - **Property 2: Staleness detection is correct for any timestamp**
    - Generate random last_scraped_at values (including None), verify is_stale=True iff value is None or older than 24h from current UTC
    - **Validates: Requirements 6.3**

  - [ ]* 2.7 Write property test: Thread count temporal consistency (`tests/test_transparency_service.py`)
    - **Property 3: Thread count temporal consistency**
    - Generate random RedditThread records with varying created_at, verify total >= last_7d >= last_24h >= 0
    - **Validates: Requirements 7.2**

  - [ ]* 2.8 Write property test: Tag distribution sums to total (`tests/test_transparency_service.py`)
    - **Property 4: Tag distribution sums to scored total**
    - Generate random threads with tags (engage, monitor, skip, None), verify engage + monitor + skip + unscored = total
    - **Validates: Requirements 7.3**

  - [ ]* 2.9 Write property test: Draft status breakdown sums to total (`tests/test_transparency_service.py`)
    - **Property 5: Draft status breakdown sums to total**
    - Generate random CommentDraft records with statuses, verify sum of all status counts = total drafts
    - **Validates: Requirements 7.4**

  - [ ]* 2.10 Write property test: AI cost aggregation consistency (`tests/test_transparency_service.py`)
    - **Property 6: AI cost aggregation consistency**
    - Generate random AIUsageLog records, verify total cost = sum of per-operation costs
    - **Validates: Requirements 7.5**

  - [ ]* 2.11 Write property test: Scrape freshness aggregation correctness (`tests/test_transparency_service.py`)
    - **Property 7: Scrape freshness aggregation correctness**
    - Generate random ScrapeLog records for a client/subreddit, verify total_posts_found = sum(posts_found) and avg_posts_new = mean(posts_new)
    - **Validates: Requirements 7.6, 9.3**

  - [ ]* 2.12 Write property test: Service functions return plain dicts (`tests/test_transparency_service.py`)
    - **Property 8: Service functions return plain dictionaries**
    - Call get_activity_events, get_pipeline_stats, get_scrape_freshness with random data, verify all returned items are plain dicts
    - **Validates: Requirements 9.4**

- [x] 3. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Instrument pipeline tasks to record activity events and scrape logs
  - [x] 4.1 Instrument `scrape_professional_subreddits` in `app/tasks/scraping.py`
    - Add `time.time()` before/after each subreddit scrape for duration_ms
    - After scraping + dedup: insert `ScrapeLog` record, update `ClientSubreddit.last_scraped_at`, call `record_activity_event(db, "scrape", message, client_id, metadata)`
    - On exception: insert `ScrapeLog` with `errors=str(e)`, `posts_found=0`, `posts_new=0`, create `"system"` activity event
    - Wrap all activity/scrape-log recording in try/except so failures don't crash the pipeline
    - _Requirements: 2.1, 5.1, 5.2, 5.3_

  - [x] 4.2 Instrument `scrape_hobby_subreddits` in `app/tasks/scraping.py`
    - Similar instrumentation as professional scraping but with `client_id=None` (hobby scrapes are avatar-scoped)
    - Record ScrapeLog and activity events for each hobby subreddit
    - _Requirements: 2.1, 5.1, 5.3_

  - [x] 4.3 Instrument `score_threads` in `app/tasks/ai_pipeline.py`
    - After `score_unscored_threads()` returns, query tag distribution for scored threads
    - Call `record_activity_event(db, "score", message, client_id, metadata)` with tag counts
    - On exception: create `"system"` activity event
    - _Requirements: 2.2_

  - [x] 4.4 Instrument `generate_comments` in `app/tasks/ai_pipeline.py`
    - After the generation loop, call `record_activity_event(db, "generate", message, client_id, metadata)` with drafts_generated count
    - On exception: create `"system"` activity event
    - _Requirements: 2.3_

  - [x] 4.5 Instrument review routes in `app/routes/review.py`
    - After each status change (approved/rejected/posted) in `update_comment`, call `record_activity_event(db, "review", message, client_id, metadata)`
    - Include draft_id, thread_title, action, and avatar_username in metadata
    - _Requirements: 2.4_

  - [ ]* 4.6 Write integration tests for pipeline instrumentation (`tests/test_pipeline_instrumentation.py`)
    - Test that `scrape_professional_subreddits` creates ActivityEvent and ScrapeLog records (mock Reddit API)
    - Test that `score_threads` creates an ActivityEvent with tag distribution (mock AI service)
    - Test that `generate_comments` creates an ActivityEvent with drafts count (mock AI service)
    - Test that review status change creates an ActivityEvent
    - Test error resilience: activity event recording failure doesn't crash the pipeline task
    - _Requirements: 11.2_

- [x] 5. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Create templates and routes for activity feed and transparency dashboard
  - [x] 6.1 Create `partials/activity_feed.html` HTMX partial template
    - Render a list of activity events with: relative timestamp, color-coded badge by event_type (scrape=blue, score=purple, generate=green, review=amber, system=red), message text
    - Empty state: "No activity yet. Run the pipeline to see events here."
    - _Requirements: 3.2, 3.5, 8.2_

  - [x] 6.2 Modify `admin_dashboard.html` to include Activity Feed section
    - Add an Activity Feed section below existing stats cards
    - Load via `hx-get="/admin/activity-feed"` with `hx-trigger="load"` for async loading
    - Add optional client filter dropdown that re-fetches the feed partial with `?client_id=...`
    - _Requirements: 3.1, 3.3, 3.4_

  - [x] 6.3 Create `admin_client_transparency.html` template
    - Extend `admin_base.html` with dark theme
    - Sections: header with client name + back link, pipeline statistics cards (thread counts), tag distribution (engage/monitor/skip with counts and percentages), draft status breakdown, AI costs (total + by operation), scrape freshness table (subreddits with last_scraped_at, total posts, avg new, stale indicator), activity history via HTMX partial
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 8.1, 8.2, 8.3_

  - [x] 6.4 Modify `admin_client_detail.html` to add Transparency link
    - Add a "Transparency" button in the header area next to "Onboarding Wizard", pointing to `/admin/clients/{id}/transparency`
    - _Requirements: 7.1_

  - [x] 6.5 Modify `admin_subreddits.html` and `partials/admin_subreddit_row.html` to show `last_scraped_at`
    - Add "Last Scraped" column to the subreddits table header
    - Display `last_scraped_at` as relative time in each row
    - Highlight with amber color if stale (> 24h or null)
    - _Requirements: 6.2, 6.3_

  - [x] 6.6 Add new routes to `app/routes/admin.py`
    - Modify `admin_dashboard` route to include activity events in context
    - Add `GET /admin/activity-feed` route for HTMX partial (dashboard-level, optional client_id filter)
    - Add `GET /admin/clients/{client_id}/transparency` route for client transparency page
    - Add `GET /admin/clients/{client_id}/activity-feed` route for client-scoped HTMX partial
    - All routes use `require_superuser` dependency
    - _Requirements: 3.1, 3.3, 3.4, 7.1, 8.1, 8.3, 9.1, 9.2, 9.3_

  - [ ]* 6.7 Write route integration tests (`tests/test_transparency_routes.py`)
    - Test `GET /admin/clients/{id}/transparency` returns 200 with correct template context
    - Test `GET /admin/activity-feed` returns 200 with event data
    - Test `GET /admin/clients/{id}/activity-feed` returns only events for that client
    - Test `GET /admin/` (dashboard) includes activity feed section in response
    - Test 404 for non-existent client_id on transparency route
    - Test that non-superuser gets 403 on all new routes
    - _Requirements: 11.3, 11.4_

- [x] 7. Final checkpoint — Ensure all tests pass
  - Run the full test suite (existing 93 tests + all new tests) and verify zero failures.
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 10.5, 11.5_

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate the 8 universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- All activity event recording is wrapped in try/except to never crash the pipeline (error handling per design)
- The design specifies Python (SQLAlchemy 2.0, FastAPI, Jinja2, Hypothesis) — no language selection needed
