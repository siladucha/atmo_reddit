# Implementation Plan: Avatar Analysis

## Overview

Two-phase implementation of LLM-based behavioral profiling for Reddit avatars. Phase 1 delivers the core analysis pipeline (blocks pilot). Phase 2 adds the learning loop (additive, non-blocking). Tasks are ordered for incremental delivery with property-based tests interspersed close to the code they validate.

## Tasks

- [x] 1. Phase 1 — Schemas and core interfaces
  - [x] 1.1 Create Pydantic request/response schemas
    - Create `app/schemas/avatar_analysis.py`
    - Define `ProfileAnalyticsInput`, `AvatarAnalysisRequest` (with `check_sufficient_data` validator), `BasicInfo`, `BehaviorMetrics`, `Topics`, `SpeechPatterns`, `BehavioralProfile`, `AnalysisErrorResponse`
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.3_

  - [x]* 1.2 Write property tests for schema validation (Properties 1, 2)
    - **Property 1: Valid input always produces schema-valid output** — generate random valid `AvatarAnalysisRequest` instances, verify `BehavioralProfile.model_validate()` accepts well-formed dicts
    - **Property 2: Invalid input always rejected with field descriptions** — generate requests with missing `reddit_username`, missing `profile_analytics`, or empty comments+posts; verify validation error references specific fields
    - **Validates: Requirements 1.1, 1.2, 1.3, 2.1, 2.3, 6.2, 6.3**

- [x] 2. Phase 1 — AnalysisService with retry/fallback
  - [x] 2.1 Implement AnalysisService core
    - Create `app/services/avatar_analysis.py`
    - Implement `analyze_avatar(db, avatar_id, request)` function
    - Build system + user prompt from request data
    - Call `call_llm_json` with `schema=BehavioralProfile`
    - Implement retry logic: up to 2 retries with exponential backoff (2s, 4s) on transient errors (timeout, rate limit, 5xx, schema validation failure)
    - Implement fallback: one attempt with fallback model after retries exhausted
    - Log each attempt to `AIUsageLog` with `operation="avatar_analysis"` and `avatar_id`
    - Raise `AnalysisError` on total failure with attempt count and last failure reason
    - Read model config from SystemSettings (`avatar_analysis_primary_model`, `avatar_analysis_fallback_model`, `avatar_analysis_max_retries`)
    - _Requirements: 1.1, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 5.1, 5.2, 5.3, 5.4_

  - [x]* 2.2 Write property tests for retry/fallback logic (Properties 3, 4, 5)
    - **Property 3: Transient failures trigger retry with exponential backoff** — mock N transient failures (0-3), verify retry count and delay pattern
    - **Property 4: Exhausted retries trigger exactly one fallback attempt** — mock 3 primary failures, verify exactly 1 fallback call
    - **Property 5: Total failure returns structured error with correct attempt count** — mock all failures, verify error contains attempts=4 and last_failure_reason
    - **Validates: Requirements 2.2, 3.2, 5.1, 5.2, 5.3**

  - [x]* 2.3 Write property test for AIUsageLog entries (Property 6)
    - **Property 6: Every LLM attempt produces an AIUsageLog entry** — run analysis with varying success/failure patterns, verify each LLM call produces exactly one AIUsageLog entry with correct `operation`, `avatar_id`, `model`, and `duration_ms > 0`
    - **Validates: Requirements 4.1, 4.2, 4.3, 5.4**

- [x] 3. Phase 1 — REST endpoint and auth
  - [x] 3.1 Create the analysis REST endpoint
    - Create `app/routes/avatar_analysis.py`
    - Implement `POST /api/avatars/{avatar_id}/analyze` with `response_model=BehavioralProfile`
    - Add JWT auth via `require_superuser` dependency
    - Verify avatar exists (404 if not found)
    - Return 200 on success, 422 on validation error, 502 on total failure
    - Register router in `app/main.py`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x]* 3.2 Write unit tests for the analysis endpoint
    - Test successful analysis returns 200 with valid BehavioralProfile
    - Test missing avatar returns 404
    - Test invalid payload returns 422 with field descriptions
    - Test all-failures returns 502 with structured error
    - Test unauthenticated request returns 401
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [x] 4. Checkpoint — Phase 1 complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Phase 2 — AnalysisEditRecord model and migration
  - [x] 5.1 Create AnalysisEditRecord model and Alembic migration
    - Create `app/models/analysis_edit.py` with `AnalysisEditRecord` (id, avatar_id FK, llm_output JSONB, human_edited JSONB, diff_summary TEXT, created_at)
    - Add composite index `ix_analysis_edit_records_avatar_created` on `(avatar_id, created_at DESC)`
    - Generate Alembic migration
    - _Requirements: 7.1, 7.2_

- [x] 6. Phase 2 — LearningLoopService
  - [x] 6.1 Implement LearningLoopService
    - Create `app/services/learning_loop.py`
    - Implement `store_edit(db, avatar_id, llm_output, human_edited)` — compute diff_summary, reject identical edits with ValueError, store AnalysisEditRecord
    - Implement `get_recent_edits(db, avatar_id, limit=3)` — retrieve N most recent edit records ordered by `created_at DESC`
    - _Requirements: 7.1, 7.3, 9.2, 9.3_

  - [x]* 6.2 Write property tests for edit storage (Properties 7, 8)
    - **Property 7: Storing an edit produces a record with auto-computed diff** — generate pairs of distinct BehavioralProfile dicts, verify `store_edit` creates record with non-empty `diff_summary` and matching `llm_output`/`human_edited`
    - **Property 8: Identical edits are rejected** — generate single BehavioralProfile dict, submit as both original and edited, verify ValueError raised and no record created
    - **Validates: Requirements 7.1, 9.2, 9.3**

  - [x]* 6.3 Write property test for few-shot retrieval (Property 9)
    - **Property 9: Few-shot injection retrieves exactly the N most recent edits** — generate K edit records (K ≥ 0) with configured limit N, verify exactly `min(K, N)` records returned in descending created_at order
    - **Validates: Requirements 8.1, 8.2**

- [x] 7. Phase 2 — Edit submission endpoint
  - [x] 7.1 Create the edit submission REST endpoint
    - Add `POST /api/avatars/{avatar_id}/analysis-edits` to `app/routes/avatar_analysis.py`
    - Define `AnalysisEditSubmission` schema (llm_output, human_edited as dicts)
    - Return 201 on success, 422 if no changes detected
    - Add JWT auth via `require_superuser` dependency
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [x]* 7.2 Write unit tests for the edit submission endpoint
    - Test valid edit returns 201
    - Test identical edit returns 422
    - Test unauthenticated request returns 401
    - Test non-existent avatar returns 404
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

- [x] 8. Phase 2 — Few-shot injection into prompt builder
  - [x] 8.1 Integrate few-shot examples into AnalysisService prompt
    - Modify `analyze_avatar` in `app/services/avatar_analysis.py` to call `get_recent_edits` before building prompt
    - If edit records exist, inject them as few-shot examples in the user prompt (original → corrected → diff_summary format)
    - If no edit records exist, prompt is identical to Phase 1 (no degradation)
    - Log count of injected few-shot examples
    - Read `avatar_analysis_few_shot_limit` from SystemSettings
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 10.1, 10.2, 10.3_

  - [x]* 8.2 Write integration tests for few-shot injection
    - Test analysis without edit records produces same prompt as Phase 1
    - Test analysis with edit records injects correct number of examples
    - Test few-shot limit is respected (max N examples)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 10.2_

- [x] 9. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (9 properties total)
- Unit tests validate specific examples and edge cases
- Phase 1 (tasks 1-4) is self-contained and blocks pilot launch
- Phase 2 (tasks 5-9) is additive and does not modify the Phase 1 contract
- All code uses Python 3.11+ / FastAPI / SQLAlchemy 2.0 / Pydantic v2
- Tests use pytest + hypothesis (already configured in the project)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.1"] },
    { "id": 3, "tasks": ["3.2"] },
    { "id": 4, "tasks": ["5.1"] },
    { "id": 5, "tasks": ["6.1", "7.1"] },
    { "id": 6, "tasks": ["6.2", "6.3", "7.2"] },
    { "id": 7, "tasks": ["8.1"] },
    { "id": 8, "tasks": ["8.2"] }
  ]
}
```
