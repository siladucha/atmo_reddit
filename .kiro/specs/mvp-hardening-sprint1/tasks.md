# Implementation Plan: MVP Hardening Sprint 1

## Overview

This plan implements eight workstreams for operational safety, reliability, and quality before the first paid pilot. Tasks follow sprint priority: emergency controls first (Days 1-2), then retry/validation (Day 3), context isolation + E2E test (Day 4), and property-based tests (Day 5). All changes target the existing Python 3.11 / FastAPI / SQLAlchemy 2.0 / Celery stack.

## Tasks

- [x] 1. Avatar Freeze — Model, Migration, and Pipeline Guards
  - [x] 1.1 Add freeze fields to Avatar model and create Alembic migration
    - Add `is_frozen` (Boolean, default False, server_default="false"), `freeze_reason` (Text, nullable), `frozen_at` (DateTime with timezone, nullable) to `app/models/avatar.py`
    - Create Alembic migration `j0k1l2m3n4o5_add_avatar_freeze_fields.py` with upgrade/downgrade
    - _Requirements: 1.1, 1.7_

  - [x] 1.2 Add frozen avatar filtering to `generate_comments` task
    - In `app/tasks/ai_pipeline.py` `generate_comments`, filter out avatars where `a.is_frozen` is True from `client_avatars` list comprehension
    - _Requirements: 1.2_

  - [x] 1.3 Add frozen avatar filtering to `generate_hobby_comments` task
    - In `app/tasks/ai_pipeline.py` `generate_hobby_comments`, add early return if `avatar.is_frozen` is True after fetching the avatar
    - _Requirements: 1.3_

  - [x] 1.4 Add frozen avatar check to `scrape_hobby_subreddits` task
    - In `app/tasks/scraping.py` `scrape_hobby_subreddits`, add early return if `avatar.is_frozen` is True after fetching the avatar
    - _Requirements: 1.4_

  - [ ]* 1.5 Write unit tests for avatar freeze filtering
    - Test that frozen avatars are excluded from `generate_comments` candidate list
    - Test that `generate_hobby_comments` returns 0 for frozen avatar
    - Test that `scrape_hobby_subreddits` returns 0 for frozen avatar
    - _Requirements: 1.2, 1.3, 1.4_

- [x] 2. Global Kill Switches — Settings and Task Guards
  - [x] 2.1 Add `pipeline_enabled` and `generation_enabled` to settings DEFAULTS
    - In `app/services/settings.py`, add `pipeline_enabled` (value "true", group "app") and `generation_enabled` (value "true", group "app") to the `DEFAULTS` dict
    - Add helper functions `is_pipeline_enabled(db)`, `is_generation_enabled(db)`, `is_scrape_enabled(db)` that return bool
    - _Requirements: 2.1, 2.2_

  - [x] 2.2 Add kill switch guards to `score_threads` task
    - In `app/tasks/ai_pipeline.py` `score_threads`, add early return with `logger.info` when `is_pipeline_enabled(db)` is False
    - _Requirements: 2.3_

  - [x] 2.3 Add kill switch guards to `generate_comments` task
    - In `app/tasks/ai_pipeline.py` `generate_comments`, add early return when `is_pipeline_enabled(db)` is False OR `is_generation_enabled(db)` is False
    - _Requirements: 2.4, 2.6_

  - [x] 2.4 Add kill switch guards to `generate_hobby_comments` task
    - In `app/tasks/ai_pipeline.py` `generate_hobby_comments`, add early return when `is_pipeline_enabled(db)` is False OR `is_generation_enabled(db)` is False
    - _Requirements: 2.5, 2.7_

  - [x] 2.5 Add `scrape_enabled` check to `scrape_hobby_subreddits`
    - In `app/tasks/scraping.py` `scrape_hobby_subreddits`, add early return when `is_scrape_enabled(db)` is False, placed before any Reddit API calls
    - _Requirements: 3.1, 3.2_

  - [ ]* 2.6 Write unit tests for kill switch guards
    - Test each task returns 0 immediately when its kill switch is disabled
    - Test that `scrape_hobby_subreddits` respects `scrape_enabled=false`
    - _Requirements: 2.3, 2.4, 2.5, 2.6, 2.7, 3.1, 3.2_

- [x] 3. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Admin UI for Emergency Controls
  - [x] 4.1 Add freeze/unfreeze admin endpoints
    - In `app/routes/admin.py`, add `POST /admin/avatars/{avatar_id}/freeze` endpoint that sets `is_frozen=True`, `freeze_reason`, `frozen_at=utcnow()` and logs to audit
    - Add `POST /admin/avatars/{avatar_id}/unfreeze` endpoint that clears frozen state and logs to audit
    - Both endpoints require `require_superuser` dependency
    - _Requirements: 1.5, 1.6, 4.2, 4.3, 4.6_

  - [x] 4.2 Add pipeline controls toggle endpoint
    - In `app/routes/admin.py`, add `POST /admin/settings/pipeline-controls` endpoint that accepts `setting_key` and `setting_value` form params
    - Validate `setting_key` is in `{"pipeline_enabled", "generation_enabled", "scrape_enabled"}`
    - Use `set_setting()` and log to audit with operator's user ID
    - _Requirements: 2.8, 4.5, 4.7_

  - [x] 4.3 Display freeze status on avatar detail template
    - Update the avatar detail admin template to show `is_frozen`, `freeze_reason`, `frozen_at` fields
    - Add "Freeze Avatar" form (reason input + submit) and "Unfreeze Avatar" button
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 4.4 Add Pipeline Controls section to admin dashboard
    - Add a "Pipeline Controls" section showing current values of `pipeline_enabled`, `generation_enabled`, `scrape_enabled`
    - Add toggle controls (HTMX POST to `/admin/settings/pipeline-controls`) for each setting
    - _Requirements: 4.4, 4.5_

  - [ ]* 4.5 Write unit tests for admin emergency endpoints
    - Test freeze endpoint sets correct fields and creates audit log
    - Test unfreeze endpoint clears fields and creates audit log
    - Test pipeline controls endpoint validates allowed keys and creates audit log
    - Test endpoints require superuser access
    - _Requirements: 4.2, 4.3, 4.5, 4.6, 4.7_

- [x] 5. Retry with Exponential Backoff for AI Tasks
  - [x] 5.1 Add retry logic to `score_threads` task
    - Change decorator to `@celery_app.task(name="score_threads", bind=True, max_retries=3)`
    - Wrap main logic in try/except, on failure call `self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))`
    - Log retry attempt at WARNING level with countdown and error details
    - _Requirements: 5.1, 5.6_

  - [x] 5.2 Add retry logic to `generate_comments` task
    - Change decorator to `@celery_app.task(name="generate_comments", bind=True, max_retries=3)`
    - Wrap main logic in try/except, on failure call `self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))`
    - _Requirements: 5.2, 5.6_

  - [x] 5.3 Add retry logic to `generate_hobby_comments` task
    - Change decorator to `@celery_app.task(name="generate_hobby_comments", bind=True, max_retries=3)`
    - Wrap main logic in try/except, on failure call `self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))`
    - _Requirements: 5.3, 5.6_

  - [x] 5.4 Add retry logic to `generate_posts` task
    - Change decorator to `@celery_app.task(name="generate_posts", bind=True, max_retries=3)`
    - Wrap main logic in try/except, on failure call `self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))`
    - _Requirements: 5.4, 5.6_

  - [ ]* 5.5 Write unit tests for retry configuration
    - Verify each AI task has `bind=True` and `max_retries=3`
    - Verify countdown formula produces 60, 120, 240 for retries 0, 1, 2
    - Verify scraping tasks do NOT have retry logic added
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 6. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Structured LLM Output Validation
  - [x] 7.1 Create Pydantic schemas for LLM outputs
    - Create new file `app/schemas/__init__.py` (empty)
    - Create `app/schemas/llm_outputs.py` with `ScoringOutput` model (alert: bool, tag: Literal["engage","monitor","skip"], relevance: int Field(ge=0,le=3), quality: int Field(ge=0,le=3), strategic: int Field(ge=0,le=3), composite: int Field(ge=0,le=9), intent: str, reason: str)
    - Add `CommentOutput` model (comment: str, comment_to: str, location_depth: int Field(ge=0), location_reasoning: str, comment_approach: str, strategic_angle: str)
    - _Requirements: 6.1, 6.2_

  - [x] 7.2 Add `schema` parameter to `call_llm_json` in `app/services/ai.py`
    - Add optional `schema: type[BaseModel] | None = None` parameter to `call_llm_json`
    - After JSON parsing, if `schema` is provided, call `schema.model_validate(data)` and replace `data` with `validated.model_dump()`
    - On `ValidationError`, let it propagate with field-level details
    - _Requirements: 6.3, 6.4_

  - [x] 7.3 Pass `ScoringOutput` schema in scoring service
    - In `app/services/scoring.py` `score_thread_for_client`, pass `schema=ScoringOutput` to `call_llm_json`
    - Add import for `ScoringOutput` from `app.schemas.llm_outputs`
    - _Requirements: 6.5_

  - [x] 7.4 Pass `CommentOutput` schema in generation service
    - In `app/services/generation.py` `generate_comment`, pass `schema=CommentOutput` to `call_llm_json`
    - Add import for `CommentOutput` from `app.schemas.llm_outputs`
    - _Requirements: 6.6_

  - [ ]* 7.5 Write unit tests for schema validation
    - Test that valid ScoringOutput JSON passes validation
    - Test that invalid ScoringOutput (relevance=5, missing tag) raises ValidationError
    - Test that valid CommentOutput JSON passes validation
    - Test that `call_llm_json` with schema rejects malformed LLM output
    - _Requirements: 6.3, 6.4_

- [x] 8. Context Isolation Assertions
  - [x] 8.1 Add runtime assertion to `select_persona`
    - In `app/services/generation.py` `select_persona`, add assertion loop before existing logic: for each avatar, assert `avatar.client_ids and str(client.id) in avatar.client_ids`
    - Include descriptive error message with avatar username and client ID
    - _Requirements: 7.1, 7.7_

  - [x] 8.2 Add runtime assertion to `generate_comment`
    - In `app/services/generation.py` `generate_comment`, add assertion at top: `assert avatar.client_ids and str(client.id) in avatar.client_ids`
    - Include descriptive error message with avatar username and client ID
    - _Requirements: 7.2, 7.5, 7.6_

  - [ ]* 8.3 Write unit tests for context isolation assertions
    - Test that `select_persona` raises AssertionError when avatar doesn't belong to client
    - Test that `generate_comment` raises AssertionError when avatar doesn't belong to client
    - Test that valid client-avatar pairs pass without assertion errors
    - _Requirements: 7.5, 7.6, 7.7_

- [x] 9. End-to-End Onboarding Test
  - [x] 9.1 Create `tests/test_e2e_onboarding.py`
    - Create test file at `reddit_saas/tests/test_e2e_onboarding.py`
    - Implement `test_e2e_onboarding_pipeline` that: creates a Client, assigns a Subreddit, inserts a mock RedditThread, creates an Avatar for the client
    - Mock `call_llm_json` and `call_llm` to return valid scoring/persona/comment/edit responses
    - Invoke scoring pipeline for the client and assert `ThreadScore` record is created
    - Invoke generation pipeline and assert `CommentDraft` record is created
    - Verify the `CommentDraft` appears in review queue query for that client
    - No external services required (mocked LLM, test DB, no Redis/Reddit)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9_

- [x] 10. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Property-Based Tests for Correctness Properties
  - [ ]* 11.1 Write property test for frozen avatar exclusion
    - **Property 1: Frozen avatar exclusion**
    - Create `reddit_saas/tests/test_props_freeze.py`
    - Use Hypothesis to generate lists of avatars with random `is_frozen` states and verify that filtering logic only passes non-frozen avatars
    - `@settings(max_examples=100)`
    - **Validates: Requirements 1.2, 1.3**

  - [ ]* 11.2 Write property test for ScoringOutput round-trip serialization
    - **Property 2: ScoringOutput round-trip serialization**
    - Create `reddit_saas/tests/test_props_schemas.py`
    - Use Hypothesis to generate valid `ScoringOutput` instances (tag ∈ {"engage","monitor","skip"}, relevance ∈ [0,3], quality ∈ [0,3], strategic ∈ [0,3], composite ∈ [0,9])
    - Serialize to JSON, parse back through `ScoringOutput.model_validate_json()`, assert equivalence
    - `@settings(max_examples=100)`
    - **Validates: Requirements 6.7**

  - [ ]* 11.3 Write property test for CommentOutput round-trip serialization
    - **Property 3: CommentOutput round-trip serialization**
    - Add to `reddit_saas/tests/test_props_schemas.py`
    - Use Hypothesis to generate valid `CommentOutput` instances (non-negative location_depth, non-empty strings)
    - Serialize to JSON, parse back through `CommentOutput.model_validate_json()`, assert equivalence
    - `@settings(max_examples=100)`
    - **Validates: Requirements 6.8**

  - [ ]* 11.4 Write property test for schema validation rejecting invalid output
    - **Property 4: Schema validation rejects invalid LLM output**
    - Add to `reddit_saas/tests/test_props_schemas.py`
    - Use Hypothesis to generate JSON objects that violate ScoringOutput constraints (relevance > 3, invalid tag, missing fields)
    - Assert that `ScoringOutput.model_validate(data)` raises `ValidationError`
    - `@settings(max_examples=100)`
    - **Validates: Requirements 6.3, 6.4**

  - [ ]* 11.5 Write property test for client isolation in persona selection
    - **Property 5: Client isolation in persona selection**
    - Create `reddit_saas/tests/test_props_isolation.py`
    - Use Hypothesis to generate sets of avatars with various `client_ids` arrays and a target client ID
    - Assert that `select_persona` raises `AssertionError` when any avatar doesn't contain the client's ID
    - `@settings(max_examples=100)`
    - **Validates: Requirements 7.1, 7.7**

- [x] 12. Final Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP delivery
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation after each major phase
- Property tests validate universal correctness properties defined in the design document
- Unit tests validate specific examples and edge cases
- The E2E test (task 9) uses mocked LLM responses — no external API dependencies
- Retry logic is NOT added to scraping tasks (they are naturally re-scheduled and idempotent)
- Kill switch state is read from DB on every task invocation (no caching) for immediate effect
