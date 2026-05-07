# Requirements Document

## Introduction

MVP Hardening Sprint 1 addresses P0 blockers before external pilot launches. The sprint focuses on operational safety, context isolation, reliability, AI output quality, and observability. The goal is controlled, observable, human-reviewed workflows — not more automation.

Priority order: Operational safety → Context isolation → Reliability → AI quality → Observability.

## Glossary

- **Avatar**: A Reddit account managed by the platform, used for community engagement on behalf of clients.
- **Pipeline**: The automated sequence of scrape → score → generate → review tasks.
- **System_Settings**: The `system_settings` database table storing key-value configuration pairs, accessed via `settings_service`.
- **AI_Pipeline**: The Celery task module (`ai_pipeline.py`) containing `score_threads`, `generate_comments`, `generate_hobby_comments`, and `generate_posts` tasks.
- **Scraping_Task**: The Celery task `scrape_hobby_subreddits` in `scraping.py`.
- **LLM_Validator**: The validation layer that checks LLM JSON responses against Pydantic schemas before downstream processing.
- **Context_Isolation**: The guarantee that no data from one client leaks into prompts, queries, or outputs for another client.
- **Admin_UI**: The Jinja2 + HTMX admin panel served at `/admin/*` routes.
- **Freeze**: A per-avatar operational state that prevents the avatar from participating in any pipeline activity (scraping, scoring, generation).
- **Kill_Switch**: A global system setting that disables an entire pipeline stage for all clients and avatars.
- **E2E_Test**: An end-to-end integration test that exercises the full onboarding and pipeline flow using mock data.

## Requirements

### Requirement 1: Avatar Freeze

**User Story:** As an operator, I want to freeze individual avatars immediately, so that I can stop a compromised or misbehaving avatar from generating further activity without disabling the entire pipeline.

#### Acceptance Criteria

1. THE Avatar model SHALL include `is_frozen` (Boolean, default false), `freeze_reason` (Text, nullable), and `frozen_at` (DateTime with timezone, nullable) fields.
2. WHEN an avatar is frozen, THE AI_Pipeline SHALL skip that avatar during persona selection in `generate_comments`.
3. WHEN an avatar is frozen, THE AI_Pipeline SHALL skip that avatar in `generate_hobby_comments`.
4. WHEN an avatar is frozen, THE Scraping_Task SHALL skip hobby subreddit scraping for that avatar.
5. WHEN an operator freezes an avatar via Admin_UI, THE System SHALL set `is_frozen=true`, record `freeze_reason`, and set `frozen_at` to the current UTC timestamp.
6. WHEN an operator unfreezes an avatar via Admin_UI, THE System SHALL set `is_frozen=false`, clear `freeze_reason`, and clear `frozen_at`.
7. THE System SHALL provide an Alembic migration that adds `is_frozen`, `freeze_reason`, and `frozen_at` columns to the `avatars` table.

### Requirement 2: Global Kill Switches

**User Story:** As an operator, I want global kill switches for the pipeline and generation stages, so that I can halt all automated activity across all clients in an emergency.

#### Acceptance Criteria

1. THE System_Settings SHALL include a `pipeline_enabled` setting (default "true") in the "app" group.
2. THE System_Settings SHALL include a `generation_enabled` setting (default "true") in the "app" group.
3. WHEN `pipeline_enabled` is "false", THE AI_Pipeline `score_threads` task SHALL return immediately without scoring any threads.
4. WHEN `pipeline_enabled` is "false", THE AI_Pipeline `generate_comments` task SHALL return immediately without generating any comments.
5. WHEN `pipeline_enabled` is "false", THE AI_Pipeline `generate_hobby_comments` task SHALL return immediately without generating any hobby comments.
6. WHEN `generation_enabled` is "false", THE AI_Pipeline `generate_comments` task SHALL return immediately without generating any comments.
7. WHEN `generation_enabled` is "false", THE AI_Pipeline `generate_hobby_comments` task SHALL return immediately without generating any hobby comments.
8. THE Admin_UI SHALL provide controls to toggle `pipeline_enabled` and `generation_enabled` settings.

### Requirement 3: Scrape Enabled Check in Hobby Scraping

**User Story:** As an operator, I want the hobby scraping task to respect the `scrape_enabled` setting, so that pausing scraping halts all scraping activity consistently.

#### Acceptance Criteria

1. WHEN `scrape_enabled` is "false", THE Scraping_Task `scrape_hobby_subreddits` SHALL return immediately without scraping any subreddits.
2. THE Scraping_Task `scrape_hobby_subreddits` SHALL check `scrape_enabled` at the beginning of execution, before any Reddit API calls.

### Requirement 4: Admin UI for Emergency Controls

**User Story:** As an operator, I want a dedicated section in the admin panel to manage avatar freeze states and global pipeline controls, so that I can respond to emergencies without direct database access.

#### Acceptance Criteria

1. THE Admin_UI SHALL display the freeze status (`is_frozen`, `freeze_reason`, `frozen_at`) on the avatar detail page.
2. THE Admin_UI SHALL provide a "Freeze Avatar" action that accepts a reason string and freezes the avatar.
3. THE Admin_UI SHALL provide an "Unfreeze Avatar" action that unfreezes the avatar.
4. THE Admin_UI SHALL display current values of `pipeline_enabled`, `generation_enabled`, and `scrape_enabled` in a "Pipeline Controls" section.
5. THE Admin_UI SHALL provide toggle controls to change `pipeline_enabled`, `generation_enabled`, and `scrape_enabled` settings.
6. WHEN an operator freezes or unfreezes an avatar, THE System SHALL record the action in the audit log with the operator's user ID.
7. WHEN an operator changes a global kill switch setting, THE System SHALL record the action in the audit log with the operator's user ID.

### Requirement 5: Retry with Exponential Backoff for AI Tasks

**User Story:** As an operator, I want AI pipeline tasks to retry automatically with exponential backoff on transient failures, so that temporary LLM API outages do not require manual re-triggering.

#### Acceptance Criteria

1. THE AI_Pipeline `score_threads` task SHALL retry up to 3 times on failure with exponential backoff using the formula `countdown = 60 * (2 ** current_retry_attempt)`.
2. THE AI_Pipeline `generate_comments` task SHALL retry up to 3 times on failure with exponential backoff using the formula `countdown = 60 * (2 ** current_retry_attempt)`.
3. THE AI_Pipeline `generate_hobby_comments` task SHALL retry up to 3 times on failure with exponential backoff using the formula `countdown = 60 * (2 ** current_retry_attempt)`.
4. THE AI_Pipeline `generate_posts` task SHALL retry up to 3 times on failure with exponential backoff using the formula `countdown = 60 * (2 ** current_retry_attempt)`.
5. THE System SHALL NOT add retry logic to scraping tasks (`scrape_hobby_subreddits`, `scrape_professional_subreddits`, `scrape_subreddit_shared`) because scraping tasks are naturally re-scheduled and idempotent.
6. WHEN all retry attempts are exhausted, THE AI_Pipeline task SHALL log the final failure and propagate the exception.

### Requirement 6: Structured LLM Output Validation

**User Story:** As a developer, I want LLM JSON responses validated against Pydantic schemas, so that malformed AI output is caught early and does not corrupt downstream data.

#### Acceptance Criteria

1. THE LLM_Validator SHALL define a `ScoringOutput` Pydantic model with fields: `alert` (bool), `tag` (literal "engage"|"monitor"|"skip"), `relevance` (int 0-3), `quality` (int 0-3), `strategic` (int 0-3), `composite` (int 0-9), `intent` (str), `reason` (str).
2. THE LLM_Validator SHALL define a `CommentOutput` Pydantic model with fields: `comment` (str), `comment_to` (str), `location_depth` (int), `location_reasoning` (str), `comment_approach` (str), `strategic_angle` (str).
3. WHEN `call_llm_json` is invoked with a schema parameter, THE AI service SHALL validate the parsed JSON against the provided Pydantic model.
4. IF the LLM response fails schema validation, THEN THE AI service SHALL raise a validation error with details about which fields failed.
5. THE scoring service (`scoring.py`) SHALL pass the `ScoringOutput` schema to `call_llm_json` when scoring threads.
6. THE generation service (`generation.py`) SHALL pass the `CommentOutput` schema to `call_llm_json` when generating comments.
7. FOR ALL valid ScoringOutput objects, serializing to JSON then parsing back through the schema SHALL produce an equivalent object (round-trip property).
8. FOR ALL valid CommentOutput objects, serializing to JSON then parsing back through the schema SHALL produce an equivalent object (round-trip property).

### Requirement 7: Context Isolation Audit

**User Story:** As an operator, I want assurance that no client's data leaks into another client's AI prompts or query results, so that client confidentiality is maintained.

#### Acceptance Criteria

1. THE generation service `select_persona` SHALL filter avatars strictly by `client_ids` containing the current client's ID before passing them to the LLM prompt.
2. THE generation service `generate_comment` SHALL retrieve `prev_comments` only for the same `client_id` as the current generation request.
3. THE scoring service `score_unscored_threads_for_client` SHALL query threads only from subreddits assigned to the current client via `ClientSubredditAssignment`.
4. THE AI_Pipeline `generate_comments` task SHALL filter avatars by `client_ids` containing the target client's ID before processing.
5. WHEN an avatar's `client_ids` does not contain the current client's ID, THE System SHALL raise an assertion error if that avatar is passed to `generate_comment` for that client.
6. THE System SHALL include a runtime assertion in `generate_comment` that verifies the avatar's `client_ids` contains the requesting client's ID.
7. THE System SHALL include a runtime assertion in `select_persona` that verifies all candidate avatars belong to the requesting client.

### Requirement 8: End-to-End Onboarding Test

**User Story:** As a developer, I want an automated end-to-end test covering the full onboarding and pipeline flow, so that regressions in the critical path are caught before deployment.

#### Acceptance Criteria

1. THE E2E_Test SHALL create a new client with required fields (client_name, brand_name).
2. THE E2E_Test SHALL assign a subreddit to the created client.
3. THE E2E_Test SHALL insert a mock Reddit thread associated with the client's assigned subreddit.
4. THE E2E_Test SHALL invoke the scoring pipeline for the client and assert that a `ThreadScore` record is created for the mock thread.
5. THE E2E_Test SHALL invoke the generation pipeline for the client and assert that a `CommentDraft` record is created for the scored thread.
6. THE E2E_Test SHALL verify that the generated `CommentDraft` is visible in the review queue query for that client.
7. THE E2E_Test SHALL use mocked LLM responses to avoid external API dependencies.
8. THE E2E_Test SHALL be located at `tests/test_e2e_onboarding.py`.
9. THE E2E_Test SHALL pass without requiring any external services (Reddit API, LLM API, Redis) beyond the test database.
