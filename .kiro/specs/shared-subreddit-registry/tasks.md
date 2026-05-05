# Implementation Plan: Shared Subreddit Registry

## Overview

Refactor the subreddit data model from single-client ownership (`ClientSubreddit`) to a shared registry with many-to-many assignments. Implementation proceeds bottom-up: models → migration → services → tasks → routes → tests → seed data.

## Tasks

- [ ] 1. Create new SQLAlchemy models
  - [ ] 1.1 Create `Subreddit` model in `reddit_saas/app/models/subreddit.py`
    - Define `subreddits` table with id, subreddit_name, is_active, created_at, last_scraped_at
    - Add case-insensitive unique index on `lower(subreddit_name)`
    - Add `assignments` and `threads` relationships
    - _Requirements: 1.1, 1.2, 1.3_

  - [ ] 1.2 Create `ClientSubredditAssignment` model in `reddit_saas/app/models/subreddit.py`
    - Define `client_subreddit_assignments` table with id, client_id, subreddit_id, type, is_active, created_at
    - Add unique constraint on (client_id, subreddit_id)
    - Add `client` and `subreddit` relationships
    - _Requirements: 2.1, 2.2_

  - [ ] 1.3 Create `ThreadScore` model in `reddit_saas/app/models/thread_score.py`
    - Define `thread_scores` table with id, thread_id, client_id, tag, alert, relevance, quality, strategic, composite, intent, scoring_reasoning, scored_at
    - Add unique constraint on (thread_id, client_id)
    - Add index on (client_id, tag)
    - Add `thread` and `client` relationships
    - _Requirements: 4.1, 4.3, 5.3_

  - [ ] 1.4 Update `RedditThread` model in `reddit_saas/app/models/thread.py`
    - Replace `client_id` FK with `subreddit_id` FK referencing `subreddits.id`
    - Remove scoring fields (tag, alert, relevance, quality, strategic, composite, intent, scoring_reasoning)
    - Add `subreddit_rel` and `scores` relationships
    - Keep `subreddit` text field for denormalized display
    - _Requirements: 5.1, 5.2, 5.4_

  - [ ] 1.5 Update `Client` model relationship in `reddit_saas/app/models/client.py`
    - Replace `subreddits` relationship with `subreddit_assignments` pointing to `ClientSubredditAssignment`
    - _Requirements: 2.1_

  - [ ] 1.6 Update `ScrapeLog` model in `reddit_saas/app/models/scrape_log.py`
    - Make `client_id` nullable
    - Add `subreddit_id` FK referencing `subreddits.id`
    - _Requirements: 8.4_

  - [ ] 1.7 Update `reddit_saas/app/models/__init__.py` to export new models
    - Import Subreddit, ClientSubredditAssignment, ThreadScore
    - Keep old ClientSubreddit import for migration compatibility
    - _Requirements: 1.1, 2.1, 4.1_

- [ ] 2. Create Alembic migration
  - [ ] 2.1 Create migration file in `reddit_saas/alembic/versions/`
    - Create `subreddits` table with case-insensitive unique index
    - Create `client_subreddit_assignments` table with composite unique constraint
    - Create `thread_scores` table with composite unique constraint and index
    - _Requirements: 1.1, 1.2, 2.1, 2.2, 4.1_

  - [ ] 2.2 Add data migration logic (populate from existing data)
    - Populate `subreddits` from distinct `lower(subreddit_name)` in `client_subreddits`
    - Populate `client_subreddit_assignments` from `client_subreddits` joined to new `subreddits`
    - Add `subreddit_id` column to `reddit_threads`, populate by matching subreddit name
    - Create missing Subreddit records for orphaned threads (is_active=false)
    - Migrate scoring fields from `reddit_threads` to `thread_scores`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [ ] 2.3 Drop old columns and update constraints
    - Drop `client_id`, `tag`, `alert`, `relevance`, `quality`, `strategic`, `composite`, `intent`, `scoring_reasoning` from `reddit_threads`
    - Make `reddit_threads.subreddit_id` NOT NULL
    - Make `scrape_log.client_id` nullable, add `subreddit_id` FK
    - Drop old unique index `uq_client_subreddits_active_name`
    - _Requirements: 5.1, 5.3, 8.4_

- [ ] 3. Checkpoint
  - Ensure migration applies cleanly against a test database, ask the user if questions arise.

- [ ] 4. Update service layer
  - [ ] 4.1 Refactor `add_subreddit` in `reddit_saas/app/services/admin.py`
    - Implement get-or-create pattern for Subreddit (case-insensitive lookup)
    - Create ClientSubredditAssignment instead of ClientSubreddit
    - Remove global uniqueness check (allow same subreddit for multiple clients)
    - Handle reactivation of inactive assignments
    - _Requirements: 2.3, 2.4, 7.1, 7.3_

  - [ ] 4.2 Refactor `remove_subreddit` in `reddit_saas/app/services/admin.py`
    - Soft-delete by setting `is_active=False` on ClientSubredditAssignment only
    - Do not modify Subreddit record or other clients' assignments
    - _Requirements: 2.4, 7.4_

  - [ ] 4.3 Add `list_client_subreddits` in `reddit_saas/app/services/admin.py`
    - Query ClientSubredditAssignment joined to Subreddit for a given client_id
    - Return subreddit data with assignment metadata (type, is_active, last_scraped_at)
    - _Requirements: 7.2_

  - [ ] 4.4 Refactor `reddit_saas/app/services/scoring.py`
    - Create `score_thread_for_client` that writes to ThreadScore instead of RedditThread
    - Create `score_unscored_threads_for_client` that finds threads in assigned subreddits lacking a ThreadScore for that client
    - Create `get_client_threads_with_scores` for display queries joining RedditThread + ThreadScore
    - Update `build_scoring_messages` to work with new model (get subreddit from relationship)
    - _Requirements: 4.1, 4.2, 4.3_

- [ ] 5. Refactor scraping tasks
  - [ ] 5.1 Create `scrape_subreddit_shared` task in `reddit_saas/app/tasks/scraping.py`
    - Accept `subreddit_id` (not client_id)
    - Load Subreddit record, scrape posts from Reddit
    - Deduplicate globally by `reddit_native_id` across entire `reddit_threads` table
    - Insert new RedditThread records with `subreddit_id` (no client_id)
    - Update `Subreddit.last_scraped_at`
    - Record ScrapeLog with `subreddit_id` (nullable client_id)
    - _Requirements: 3.1, 3.2, 3.3, 8.3, 8.4, 9.1, 9.2_

  - [ ] 5.2 Refactor `queue_tick` in `reddit_saas/app/tasks/queue_ticker.py`
    - Query `subreddits` table ordered by `last_scraped_at ASC NULLS FIRST`
    - JOIN to `client_subreddit_assignments` (at least one active) and `clients` (is_active=true)
    - Dispatch `scrape_subreddit_shared(subreddit_id)` instead of `scrape_single_subreddit(name, client_id)`
    - _Requirements: 3.1, 3.4, 8.1, 8.2_

- [ ] 6. Update admin routes and templates
  - [ ] 6.1 Update subreddit CRUD routes in `reddit_saas/app/routes/admin.py`
    - Update add/remove/list endpoints to use new service functions
    - Remove global uniqueness error handling from UI
    - Update response serialization to use Subreddit + Assignment data
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [ ] 6.2 Update admin templates for subreddit management
    - Update subreddit list partial to show shared indicator (if subreddit has multiple assignments)
    - Remove "already monitored by another client" error messaging
    - Update thread display to pull scores from ThreadScore instead of RedditThread
    - _Requirements: 7.1, 7.2, 7.3_

- [ ] 7. Update scoring pipeline orchestration
  - [ ] 7.1 Update `score_threads` task in `reddit_saas/app/tasks/ai_pipeline.py`
    - Use `score_unscored_threads_for_client` from updated scoring service
    - Query threads via client's assigned subreddits, check for missing ThreadScore records
    - _Requirements: 4.1, 4.2_

- [ ] 8. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Property-based tests
  - [ ]* 9.1 Write property test for subreddit name case-insensitive uniqueness
    - **Property 1: Subreddit name case-insensitive uniqueness**
    - Generate random subreddit names with case variations, verify single record stored
    - Test file: `reddit_saas/tests/test_shared_subreddit_properties.py`
    - **Validates: Requirements 1.2, 1.3**

  - [ ]* 9.2 Write property test for assignment uniqueness per client-subreddit pair
    - **Property 2: Assignment uniqueness per client-subreddit pair**
    - Generate random (client, subreddit) pairs, attempt duplicate assignments
    - Test file: `reddit_saas/tests/test_shared_subreddit_properties.py`
    - **Validates: Requirements 2.2**

  - [ ]* 9.3 Write property test for get-or-create with multi-client sharing
    - **Property 3: Get-or-create subreddit with multi-client sharing**
    - Generate sequences of add_subreddit calls with same name, different clients
    - Verify exactly one Subreddit record and one assignment per client
    - Test file: `reddit_saas/tests/test_shared_subreddit_properties.py`
    - **Validates: Requirements 2.3, 7.1**

  - [ ]* 9.4 Write property test for assignment deactivation isolation
    - **Property 4: Assignment deactivation isolation**
    - Generate N clients sharing a subreddit, deactivate one, verify others unchanged
    - Test file: `reddit_saas/tests/test_shared_subreddit_properties.py`
    - **Validates: Requirements 2.4, 7.4**

  - [ ]* 9.5 Write property test for scrape selection by staleness with active filtering
    - **Property 5: Scrape selection by staleness with active filtering**
    - Generate subreddits with varying last_scraped_at, verify ordering and active-only filtering
    - Test file: `reddit_saas/tests/test_shared_subreddit_properties.py`
    - **Validates: Requirements 3.1, 3.4, 8.1, 8.2**

  - [ ]* 9.6 Write property test for per-client scoring completeness
    - **Property 6: Per-client scoring completeness**
    - Generate threads with K active client assignments, verify K ThreadScore records created
    - Test file: `reddit_saas/tests/test_shared_subreddit_properties.py`
    - **Validates: Requirements 4.1, 4.2**

  - [ ]* 9.7 Write property test for client subreddit listing isolation
    - **Property 7: Client subreddit listing isolation**
    - Generate multi-client assignment sets, verify each client sees only their subreddits
    - Test file: `reddit_saas/tests/test_shared_subreddit_properties.py`
    - **Validates: Requirements 7.2**

  - [ ]* 9.8 Write property test for global thread deduplication
    - **Property 8: Global thread deduplication**
    - Generate posts with overlapping reddit_native_ids, verify no duplicates in DB
    - Test file: `reddit_saas/tests/test_shared_subreddit_properties.py`
    - **Validates: Requirements 5.4, 9.1, 9.2**

  - [ ]* 9.9 Write property test for migration subreddit registry completeness
    - **Property 9: Migration subreddit registry completeness**
    - Generate pre-migration data states, verify all subreddit names have registry records
    - Test file: `reddit_saas/tests/test_shared_subreddit_properties.py`
    - **Validates: Requirements 6.1, 6.3, 6.5**

  - [ ]* 9.10 Write property test for migration assignment preservation
    - **Property 10: Migration assignment preservation**
    - Generate client_subreddits rows, verify matching assignments after migration
    - Test file: `reddit_saas/tests/test_shared_subreddit_properties.py`
    - **Validates: Requirements 6.2**

  - [ ]* 9.11 Write property test for migration scoring data preservation
    - **Property 11: Migration scoring data preservation**
    - Generate scored threads, verify thread_scores records with identical values
    - Test file: `reddit_saas/tests/test_shared_subreddit_properties.py`
    - **Validates: Requirements 5.3, 6.4**

- [ ] 10. Unit and integration tests
  - [ ]* 10.1 Write unit tests for admin service (add/remove/list subreddits)
    - Test add_subreddit creates Subreddit + Assignment
    - Test add_subreddit reactivates inactive assignment
    - Test remove_subreddit soft-deletes assignment only
    - Test list_client_subreddits filters by client
    - Test file: `reddit_saas/tests/test_shared_subreddit_unit.py`
    - _Requirements: 2.3, 2.4, 7.1, 7.2, 7.3, 7.4_

  - [ ]* 10.2 Write unit tests for scoring service
    - Test score_thread_for_client creates ThreadScore record
    - Test score_unscored_threads_for_client finds threads via assigned subreddits
    - Test get_client_threads_with_scores returns correct join
    - Test file: `reddit_saas/tests/test_shared_subreddit_unit.py`
    - _Requirements: 4.1, 4.2, 4.3_

  - [ ]* 10.3 Write unit tests for scraping task
    - Test scrape_subreddit_shared deduplicates globally
    - Test scrape_subreddit_shared updates last_scraped_at
    - Test ScrapeLog works with nullable client_id
    - Test file: `reddit_saas/tests/test_shared_subreddit_unit.py`
    - _Requirements: 3.2, 3.3, 8.4, 9.1, 9.2_

  - [ ]* 10.4 Write integration tests for full pipeline flow
    - Test: add subreddit → scrape → score → verify per-client ThreadScore records
    - Test: same subreddit assigned to two clients, scrape once, both get scores
    - Test: queue_tick skips subreddits with no active assignments
    - Test file: `reddit_saas/tests/test_shared_subreddit_integration.py`
    - _Requirements: 3.1, 3.4, 4.1, 4.2, 8.1, 8.2_

- [ ] 11. Update seed data
  - [ ] 11.1 Update `reddit_saas/app/seed.py` to use new models
    - Create Subreddit records for each seeded subreddit name
    - Create ClientSubredditAssignment records instead of ClientSubreddit records
    - Preserve existing seed data (XM Cyber subreddits, NeuroYoga if applicable)
    - _Requirements: 1.1, 2.1, 2.3_

- [ ] 12. Final checkpoint
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The old `ClientSubreddit` model/table is kept temporarily for rollback safety; removal is a follow-up migration
