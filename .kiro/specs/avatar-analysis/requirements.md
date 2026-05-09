# Requirements Document

## Introduction

Avatar Analysis is a two-phase feature that automates behavioral profiling of Reddit avatars using LLM analysis. Phase 1 (Sprint 1, blocks pilot) accepts structured avatar data (comments, posts, metrics) and returns a structured behavioral profile via LLM. Phase 2 (Sprint 2, non-blocking) adds a self-learning loop that stores human edits and injects them as few-shot examples into future analyses, reducing repeated mistakes over time.

## Glossary

- **Analysis_Service**: The backend service responsible for orchestrating avatar analysis requests, calling the LLM, and returning structured results.
- **Avatar_Profile_Analytics**: Structured input data containing an avatar's recent_comments, recent_posts, subreddits, account_age_days, and total_karma.
- **Behavioral_Profile**: The structured JSON output of an analysis containing basic_info, behavior_metrics, topics, speech_patterns, mismatches, and summary.
- **Voice_Profile_MD**: A markdown document describing the intended voice and personality of an avatar (the "legend" against which reality is compared).
- **Learning_Loop_Service**: The service responsible for storing human edits and injecting few-shot examples into subsequent analysis prompts.
- **Edit_Record**: A stored record of a human correction to an LLM-generated Behavioral_Profile, containing avatar_id, timestamp, llm_output, human_edited, and diff_summary.
- **Few_Shot_Example**: A past Edit_Record injected into the analysis prompt to guide the LLM toward previously corrected patterns.
- **LLM_Provider**: The language model backend (GPT-4o-mini or Claude Sonnet) accessed via LiteLLM.

## Requirements

### Requirement 1: Accept Avatar Analysis Request

**User Story:** As an operator, I want to submit avatar data for analysis, so that I can get an automated behavioral profile without manual review.

#### Acceptance Criteria

1. WHEN a valid analysis request containing reddit_username, active status, voice_profile_md, and profile_analytics is received, THE Analysis_Service SHALL initiate LLM-based analysis and return a Behavioral_Profile.
2. WHEN a request is missing required fields (reddit_username or profile_analytics), THE Analysis_Service SHALL return a validation error with a description of the missing fields.
3. WHEN profile_analytics contains empty recent_comments and empty recent_posts, THE Analysis_Service SHALL return an error indicating insufficient data for analysis.

### Requirement 2: Generate Structured Behavioral Profile

**User Story:** As an operator, I want the analysis output in a consistent JSON structure, so that downstream systems can consume it programmatically.

#### Acceptance Criteria

1. WHEN analysis completes successfully, THE Analysis_Service SHALL return a JSON object containing: basic_info (username, account_age, karma_breakdown, active_subreddits), behavior_metrics (posting_frequency, comment_to_post_ratio, engagement_level, peak_activity_hours), topics (primary_topics, secondary_topics, avoided_topics), speech_patterns (avg_comment_length, vocabulary_level, tone, recurring_phrases, emoji_usage, formatting_style), mismatches (list of discrepancies between voice_profile_md and actual behavior), and summary (30-50 word behavioral synopsis).
2. WHEN the LLM returns a response that does not conform to the expected Behavioral_Profile schema, THE Analysis_Service SHALL reject the response and retry the request.
3. THE Analysis_Service SHALL validate the output against a Pydantic schema before returning it to the caller.

### Requirement 3: LLM Integration and Model Selection

**User Story:** As a system administrator, I want to configure which LLM model performs the analysis, so that I can balance cost and quality.

#### Acceptance Criteria

1. THE Analysis_Service SHALL support GPT-4o-mini and Claude Sonnet as configurable LLM_Provider options via system settings.
2. WHEN the configured LLM_Provider is unavailable, THE Analysis_Service SHALL fall back to the alternative provider.
3. THE Analysis_Service SHALL use the existing LiteLLM integration (app/services/ai.py call_llm_json) for all LLM calls.

### Requirement 4: Token and Cost Logging

**User Story:** As a system administrator, I want every analysis call logged with token counts and cost, so that I can monitor spending and optimize model selection.

#### Acceptance Criteria

1. WHEN an analysis call completes (success or failure after retries), THE Analysis_Service SHALL log the operation to AIUsageLog with operation="avatar_analysis", model name, input_tokens, output_tokens, cost_usd, and duration_ms.
2. THE Analysis_Service SHALL record the avatar_id in the AIUsageLog entry for per-avatar cost tracking.
3. WHEN a fallback model is used, THE Analysis_Service SHALL log both the failed attempt and the successful fallback as separate AIUsageLog entries.

### Requirement 5: Error Handling and Retry Logic

**User Story:** As an operator, I want the system to handle transient LLM failures gracefully, so that a single API timeout does not block the analysis pipeline.

#### Acceptance Criteria

1. WHEN an LLM call fails due to a transient error (timeout, rate limit, 5xx response), THE Analysis_Service SHALL retry the request up to 2 additional times with exponential backoff (base delay 2 seconds).
2. IF all retry attempts fail and a fallback LLM_Provider is configured, THEN THE Analysis_Service SHALL attempt the request once using the fallback provider.
3. IF all attempts (retries + fallback) fail, THEN THE Analysis_Service SHALL return a structured error response containing the failure reason and the number of attempts made.
4. THE Analysis_Service SHALL log each failed attempt with the error type and duration before retrying.

### Requirement 6: API Endpoint

**User Story:** As a developer integrating with the analysis service, I want a clear REST endpoint, so that I can trigger analysis programmatically.

#### Acceptance Criteria

1. THE Analysis_Service SHALL expose a POST endpoint at /api/avatars/{avatar_id}/analyze that accepts the analysis request payload.
2. WHEN analysis completes successfully, THE Analysis_Service SHALL return HTTP 200 with the Behavioral_Profile JSON.
3. WHEN validation fails, THE Analysis_Service SHALL return HTTP 422 with error details.
4. WHEN all analysis attempts fail, THE Analysis_Service SHALL return HTTP 502 with the structured error response.
5. THE Analysis_Service SHALL require authentication (JWT) on the analysis endpoint.

### Requirement 7: Store Human Edits for Learning

**User Story:** As an operator, I want my corrections to analysis results saved, so that the system learns from my edits over time.

#### Acceptance Criteria

1. WHEN a human submits an edited Behavioral_Profile for an avatar, THE Learning_Loop_Service SHALL store an Edit_Record containing avatar_id, timestamp, original llm_output, human_edited version, and a diff_summary describing what changed.
2. THE Learning_Loop_Service SHALL store Edit_Records in a PostgreSQL table (or JSON file for MVP) with the avatar_id indexed for fast retrieval.
3. WHEN an Edit_Record is stored, THE Learning_Loop_Service SHALL log whether the edit was stored successfully.

### Requirement 8: Inject Few-Shot Examples into Analysis Prompt

**User Story:** As an operator, I want the system to use my past corrections when re-analyzing the same avatar, so that it does not repeat the same mistakes.

#### Acceptance Criteria

1. WHEN an analysis request is made for an avatar that has existing Edit_Records, THE Analysis_Service SHALL retrieve the most recent 3 Edit_Records for that avatar.
2. WHEN Edit_Records are available, THE Analysis_Service SHALL inject them into the LLM prompt as few-shot examples showing the original output and the corrected version.
3. WHEN Edit_Records are injected, THE Analysis_Service SHALL log that few-shot examples were used, including the count of examples injected.
4. WHEN no Edit_Records exist for the avatar, THE Analysis_Service SHALL proceed with analysis without few-shot examples.

### Requirement 9: Edit Submission Endpoint

**User Story:** As a developer, I want a clear endpoint to submit human corrections, so that the learning loop can be integrated into the review workflow.

#### Acceptance Criteria

1. THE Learning_Loop_Service SHALL expose a POST endpoint at /api/avatars/{avatar_id}/analysis-edits that accepts the original LLM output and the human-edited version.
2. WHEN a valid edit is submitted, THE Learning_Loop_Service SHALL compute a diff_summary automatically and store the Edit_Record.
3. WHEN the submitted edit is identical to the original output, THE Learning_Loop_Service SHALL return HTTP 422 indicating no changes detected.
4. THE Learning_Loop_Service SHALL require authentication (JWT) on the edit submission endpoint.

### Requirement 10: Phased Delivery

**User Story:** As a project manager, I want the analysis feature delivered in two independent phases, so that the pilot can launch without waiting for the learning loop.

#### Acceptance Criteria

1. THE Analysis_Service SHALL function independently without the Learning_Loop_Service (Requirements 1-6 are self-contained for Sprint 1).
2. WHEN the Learning_Loop_Service is not deployed or has no Edit_Records, THE Analysis_Service SHALL operate identically to the standalone mode (no degradation).
3. THE Learning_Loop_Service (Requirements 7-9) SHALL be deployable as an additive enhancement without modifying the core Analysis_Service contract.
