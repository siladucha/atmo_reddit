# Requirements Document

## Introduction

GEO/AEO Prompt Monitoring system (Milestone 1) for RAMP. This module measures how frequently a client's brand appears in AI-generated responses to buyer-intent prompts across multiple LLM providers (Perplexity Sonar, OpenAI with web search, Gemini). The system stores a library of prompts per client, runs them on a configurable schedule with multiple iterations per execution (3-5 runs for statistical validity), and parses responses for brand mentions, competitor mentions, and Reddit URL citations.

This is a standalone monitoring layer — it observes LLM behavior but does not modify the avatar pipeline. Future milestones will cross-reference Reddit citations with our posted comments (Milestone 2), build client-facing dashboards (Milestone 3), and feed insights back into content strategy (Milestone 4).

Revenue model: $149/month add-on per client. Expected cost at 10 clients: $500-900/month in LLM API fees.

## Glossary

- **Prompt_Library**: The collection of buyer-intent prompts stored per client, used to query external LLMs for brand visibility measurement.
- **Buyer_Intent_Prompt**: A natural-language question that a potential buyer would ask an AI assistant when researching solutions in the client's market (e.g., "What attack surface management platform should a Series B SaaS company use?").
- **Competitor_Entity**: A structured record representing a competitor of a client, consisting of name, domain, and zero or more aliases used for fuzzy matching in LLM responses.
- **Query_Execution**: A single run of a prompt against a specific LLM provider, producing one response document.
- **Execution_Batch**: A scheduled group of query executions for a client — all prompts × all providers × N repetitions (default 3-5 per prompt per provider).
- **Appearance_Rate**: The frequency at which a brand or competitor entity is mentioned across multiple runs of the same prompt, expressed as a percentage (e.g., "brand mentioned in 4 of 5 runs = 80% appearance rate").
- **Brand_Detection_Service**: The service that scans LLM response text for mentions of the client's brand name and competitor entities using string matching and fuzzy matching.
- **Citation_Parser**: The component that extracts source URLs from LLM responses, identifying Reddit URLs and other citation sources.
- **GEO_Query_Runner**: The Celery task responsible for executing prompts against external LLM providers on schedule.
- **Baseline_Run**: The initial full execution of all client prompts on Day 1 of activation, stored as the reference point for measuring improvement over time.
- **GEO_Queue**: A dedicated Celery queue for GEO/AEO query tasks, isolated from the main avatar generation pipeline to prevent resource contention.
- **LLM_Provider**: An external AI service used for prompt execution — specifically Perplexity Sonar (primary), OpenAI with web search (secondary), and Gemini (tertiary).

## Requirements

### Requirement 1: Prompt Library Management

**User Story:** As a client admin, I want to manage a library of buyer-intent prompts for my brand, so that the system can measure how often AI assistants recommend my product.

#### Acceptance Criteria

1. THE Prompt_Library SHALL store prompts in a `geo_prompts` table with fields: `id` (UUID), `client_id` (FK to clients), `prompt_text` (text, max 1000 characters), `category` (string, optional), `is_active` (boolean, default true), `created_at`, `updated_at`, `created_by` (FK to users).
2. WHEN a user creates a prompt, THE Prompt_Library SHALL validate that `prompt_text` is between 10 and 1000 characters and is not a duplicate within the same client.
3. THE Prompt_Library SHALL enforce a maximum of 50 active prompts per client.
4. IF a user attempts to create more than 50 active prompts for a client, THEN THE Prompt_Library SHALL reject the request with a clear message indicating the limit.
5. WHEN a user deactivates a prompt, THE Prompt_Library SHALL set `is_active = false` and retain the prompt record and its historical execution data.
6. THE Prompt_Library SHALL enforce RBAC: owner and partner roles see all clients; client_admin and client_manager see their own client; client_viewer has read-only access; b2c_user has no access to GEO features.

### Requirement 2: Competitor Entity Management

**User Story:** As a client admin, I want to maintain a structured list of competitors with names, domains, and aliases, so that the system can accurately detect competitor mentions in LLM responses.

#### Acceptance Criteria

1. THE system SHALL store competitor entities in a `geo_competitors` table with fields: `id` (UUID), `client_id` (FK to clients), `competitor_name` (string, max 255), `competitor_domain` (string, max 255, optional), `aliases` (JSONB array of strings), `is_active` (boolean, default true), `created_at`.
2. WHEN a user creates a competitor entity, THE system SHALL validate that `competitor_name` is non-empty and unique within the same client.
3. THE system SHALL enforce a maximum of 30 active competitor entities per client.
4. IF a user attempts to create more than 30 active competitors for a client, THEN THE system SHALL reject the request with a clear message indicating the limit.
5. WHEN the Brand_Detection_Service scans a response, THE Brand_Detection_Service SHALL match against `competitor_name` and all values in the `aliases` array.
6. THE system SHALL enforce the same RBAC rules as the Prompt_Library for competitor entity access.

### Requirement 3: Scheduled Query Execution

**User Story:** As a system operator, I want client prompts to run against LLM providers on a configurable schedule, so that brand visibility is measured continuously without manual intervention.

#### Acceptance Criteria

1. THE GEO_Query_Runner SHALL execute as a Celery Beat task on the GEO_Queue with a configurable schedule (system setting `geo_execution_schedule`, default: twice weekly — Monday and Thursday at 03:00 Israel time).
2. WHEN the scheduled execution triggers, THE GEO_Query_Runner SHALL process all active clients with `geo_monitoring_enabled = true` and at least one active prompt.
3. FOR EACH active prompt of a client, THE GEO_Query_Runner SHALL execute the prompt against each configured LLM_Provider (Perplexity Sonar, OpenAI with web search, Gemini).
4. FOR EACH prompt-provider combination, THE GEO_Query_Runner SHALL execute the query N times (system setting `geo_runs_per_prompt`, default: 3, range 1-10) to measure appearance rate.
5. THE GEO_Query_Runner SHALL respect per-provider rate limits: Perplexity (20 req/min), OpenAI (60 req/min), Gemini (60 req/min) — configurable via system settings.
6. WHEN a query to an LLM_Provider fails with a transient error (timeout, 429, 500, 502, 503), THE GEO_Query_Runner SHALL retry up to 3 times with exponential backoff (30s × 2^attempt).
7. IF all retries fail for a query, THEN THE GEO_Query_Runner SHALL log the failure, mark the execution as `failed`, and continue processing remaining prompts.
8. THE GEO_Query_Runner SHALL use a dedicated Celery queue named `geo_queries` separate from the default queue used by avatar pipeline tasks.

### Requirement 4: Response Storage

**User Story:** As a system operator, I want full LLM responses stored with structured metadata, so that historical data is available for trend analysis and debugging.

#### Acceptance Criteria

1. THE system SHALL store query results in a `geo_query_results` table with fields: `id` (UUID), `prompt_id` (FK to geo_prompts), `client_id` (FK to clients), `provider` (string: perplexity/openai/gemini), `execution_batch_id` (UUID, groups results from the same scheduled run), `run_number` (integer, 1-based within batch), `response_text` (text, full LLM response), `brand_mentioned` (boolean), `competitors_mentioned` (JSONB array of competitor IDs found), `reddit_urls_found` (JSONB array of extracted Reddit URLs), `citation_sources` (JSONB array of all parsed citation URLs), `response_tokens` (integer), `latency_ms` (integer), `status` (string: success/failed/timeout), `executed_at` (timestamp with timezone), `created_at`.
2. WHEN a query execution succeeds, THE system SHALL populate all metadata fields by running the Brand_Detection_Service and Citation_Parser on the response text before storing.
3. THE system SHALL create a `geo_execution_batches` table with fields: `id` (UUID), `client_id` (FK), `triggered_by` (string: scheduler/manual/onboarding), `started_at`, `completed_at`, `total_queries` (integer), `successful_queries` (integer), `failed_queries` (integer), `status` (string: running/completed/partial/failed).
4. WHEN an Execution_Batch completes, THE system SHALL update its `completed_at`, `successful_queries`, `failed_queries`, and `status` fields.
5. THE system SHALL retain geo_query_results records for a minimum of 365 days.

### Requirement 5: Frequency-Based Brand Measurement

**User Story:** As a client admin, I want to see how frequently my brand appears across multiple runs of the same prompt, so that I understand my actual appearance rate rather than a binary yes/no.

#### Acceptance Criteria

1. FOR EACH prompt-provider combination within an Execution_Batch, THE system SHALL compute the Appearance_Rate as: `(runs_with_brand_mention / total_successful_runs) × 100`.
2. THE system SHALL store aggregated frequency metrics in a `geo_frequency_metrics` table with fields: `id` (UUID), `execution_batch_id` (FK), `prompt_id` (FK), `client_id` (FK), `provider` (string), `total_runs` (integer), `brand_appearances` (integer), `brand_appearance_rate` (decimal 0-100), `competitor_appearances` (JSONB: {competitor_id: count}), `reddit_citation_count` (integer), `computed_at` (timestamp).
3. WHEN all runs for a prompt-provider combination within a batch complete, THE system SHALL automatically compute and store the frequency metrics.
4. THE system SHALL compute a cross-provider aggregate appearance rate per prompt: average of per-provider rates weighted equally.
5. WHEN the Baseline_Run is stored, THE system SHALL flag its execution_batch as `is_baseline = true` for delta comparison in future milestones.

### Requirement 6: Brand Detection

**User Story:** As a system operator, I want the system to accurately detect brand and competitor mentions in LLM responses, so that appearance rates reflect reality.

#### Acceptance Criteria

1. WHEN the Brand_Detection_Service scans a response for the client brand, THE Brand_Detection_Service SHALL perform case-insensitive substring matching against the client's `brand_name` field.
2. WHEN the Brand_Detection_Service scans a response for competitor mentions, THE Brand_Detection_Service SHALL perform case-insensitive matching against each competitor's `competitor_name` and all entries in the `aliases` array.
3. THE Brand_Detection_Service SHALL apply fuzzy matching (Levenshtein distance ≤ 2) for brand names and competitor names longer than 6 characters to catch common misspellings by LLMs.
4. THE Brand_Detection_Service SHALL NOT match partial words — matches must occur at word boundaries (e.g., "Acme" does not match within "AcmeWidgets" but matches "Acme Corp" and "use Acme for").
5. IF the client's `brand_name` is fewer than 4 characters, THEN THE Brand_Detection_Service SHALL use exact case-insensitive matching only (no fuzzy matching) to avoid false positives.
6. THE Brand_Detection_Service SHALL return structured results: `{brand_found: bool, brand_positions: [int], competitors_found: [{competitor_id, name, positions: [int]}]}`.

### Requirement 7: Reddit URL Extraction

**User Story:** As a system operator, I want Reddit URLs extracted from LLM responses, so that future milestones can cross-reference them against our posted comments.

#### Acceptance Criteria

1. WHEN the Citation_Parser processes an LLM response, THE Citation_Parser SHALL extract all URLs matching the pattern `https://www.reddit.com/*` or `https://reddit.com/*` (including old.reddit.com).
2. THE Citation_Parser SHALL normalize extracted Reddit URLs by removing query parameters and trailing slashes.
3. THE Citation_Parser SHALL categorize extracted Reddit URLs into types: `thread` (matches `/r/{sub}/comments/{id}/`), `comment` (matches `/r/{sub}/comments/{id}/{slug}/{comment_id}/`), or `subreddit` (matches `/r/{sub}/`).
4. THE Citation_Parser SHALL extract all non-Reddit citation URLs and store them in the `citation_sources` field for completeness.
5. WHEN a response from Perplexity Sonar includes inline citations (numbered references with URLs), THE Citation_Parser SHALL parse the citation format and extract the referenced URLs.
6. WHEN a response from OpenAI with web search includes source annotations, THE Citation_Parser SHALL parse the annotation format and extract source URLs.

### Requirement 8: Admin UI for Prompt Library

**User Story:** As an admin, I want a UI to manage prompts, view execution history, and see brand visibility results, so that I can monitor GEO performance per client.

#### Acceptance Criteria

1. THE admin panel SHALL provide a "GEO Monitoring" section accessible at `/admin/clients/{id}/geo` showing the client's prompt library, competitors, and execution results.
2. WHEN an admin views the prompt library, THE system SHALL display all prompts (active and inactive) with columns: prompt text (truncated to 80 chars), category, status, last executed date, and last brand appearance rate.
3. THE admin UI SHALL provide CRUD operations for prompts: create (form with text + optional category), edit (inline text edit), deactivate/reactivate (toggle), and delete (soft delete via deactivation).
4. THE admin UI SHALL provide CRUD operations for competitor entities: create (form with name + domain + aliases), edit, deactivate/reactivate, and delete (soft delete).
5. WHEN an admin views execution history, THE system SHALL display the 20 most recent Execution_Batches with: date, trigger type, total queries, success rate, and overall brand appearance rate.
6. WHEN an admin clicks an Execution_Batch, THE system SHALL show per-prompt results: prompt text, per-provider appearance rates, competitor appearances, and Reddit citation count.
7. THE admin UI SHALL provide a "Run Now" button that triggers an immediate Execution_Batch for the client (bypassing the schedule).
8. THE admin UI SHALL use HTMX partials consistent with the existing admin panel dark theme.

### Requirement 9: Onboarding Integration

**User Story:** As an admin onboarding a new client, I want to capture buyer-intent prompts during the onboarding wizard, so that monitoring starts immediately after activation.

#### Acceptance Criteria

1. THE onboarding wizard SHALL include a new step "Buyer-Intent Prompts" after the keywords step, allowing the admin to enter 5-20 initial prompts for the client.
2. WHEN the admin enters prompts during onboarding, THE system SHALL validate each prompt (10-1000 characters) and store them in the `geo_prompts` table upon wizard completion.
3. THE onboarding wizard SHALL provide example prompts based on the client's industry and brand name to guide the admin (3-5 auto-suggested examples).
4. THE onboarding wizard step SHALL allow the admin to also enter initial competitor entities (name + domain) with a minimum of 1 competitor required if GEO monitoring is enabled.
5. THE onboarding wizard SHALL include a toggle "Enable GEO Monitoring" (stored as `geo_monitoring_enabled` on the Client model, default: false).
6. IF the admin enables GEO monitoring but enters fewer than 5 prompts, THEN THE system SHALL display a recommendation to add more prompts for statistically meaningful results, but SHALL NOT block completion.

### Requirement 10: Baseline Run at Onboarding

**User Story:** As a system operator, I want a full prompt suite executed automatically on Day 1 of client activation, so that there is a baseline measurement for tracking improvement over time.

#### Acceptance Criteria

1. WHEN a client's `geo_monitoring_enabled` is set to `true` for the first time (either during onboarding or via admin toggle), THE system SHALL automatically dispatch a Baseline_Run Execution_Batch within 5 minutes.
2. THE Baseline_Run SHALL execute all active prompts for the client across all configured providers with the standard number of repetitions (`geo_runs_per_prompt`).
3. WHEN the Baseline_Run completes, THE system SHALL mark the execution batch with `is_baseline = true` and compute all frequency metrics.
4. THE system SHALL allow only one baseline batch per client. IF the admin requests a new baseline (via "Reset Baseline" action), THE system SHALL mark the old baseline as `is_baseline = false` and create a new baseline batch.
5. IF the Baseline_Run partially fails (some queries succeed, some fail), THEN THE system SHALL mark the batch status as `partial` and compute metrics from successful runs only.
6. THE admin UI SHALL display the baseline results prominently on the client's GEO page with a "Baseline" badge and the date it was captured.

### Requirement 11: Cost Isolation and Tracking

**User Story:** As a system operator, I want GEO query costs tracked separately from avatar generation costs, so that I can measure profitability of the GEO add-on independently.

#### Acceptance Criteria

1. WHEN the GEO_Query_Runner makes an LLM API call, THE system SHALL log it in the existing `ai_usage_log` table with `operation = 'geo_query'`.
2. THE AIUsageLog records for GEO queries SHALL include: `client_id`, `model` (provider-specific model name), `input_tokens`, `output_tokens`, `cost_usd`, `duration_ms`, and `triggered_by = 'geo_scheduler'` or `'geo_manual'`.
3. THE admin AI costs dashboard SHALL display GEO query costs as a separate category from avatar operations (scoring, generation, editing, hobby).
4. THE system SHALL compute estimated cost per execution batch and display it in the execution history view.
5. THE system SHALL provide a system setting `geo_monthly_cost_alert_threshold` (decimal, default: 100.00 USD) that triggers a warning in the admin dashboard when monthly GEO costs exceed the threshold.

### Requirement 12: LLM Provider Configuration

**User Story:** As a system operator, I want to configure which LLM providers are used for GEO monitoring and their API parameters, so that I can optimize for cost and coverage.

#### Acceptance Criteria

1. THE system SHALL support three LLM providers for GEO queries: Perplexity Sonar (primary — best Reddit citation visibility), OpenAI with web search (secondary), and Gemini (tertiary).
2. THE system SHALL store provider configuration in system settings: `geo_provider_perplexity_enabled` (bool, default true), `geo_provider_openai_enabled` (bool, default true), `geo_provider_gemini_enabled` (bool, default true).
3. WHEN a provider is disabled via settings, THE GEO_Query_Runner SHALL skip that provider for all clients during execution.
4. THE system SHALL store API keys for GEO providers in system settings (encrypted): `geo_perplexity_api_key`, `geo_openai_api_key`, `geo_gemini_api_key`.
5. THE system SHALL use LiteLLM as the unified interface for calling all three providers, consistent with the existing AI service architecture.
6. WHEN calling Perplexity Sonar, THE GEO_Query_Runner SHALL use the `sonar` model with web search enabled to maximize citation visibility.
7. WHEN calling OpenAI, THE GEO_Query_Runner SHALL use the model with web browsing/search capabilities enabled.
8. WHEN calling Gemini, THE GEO_Query_Runner SHALL use a Gemini model with grounding/search enabled.

### Requirement 13: Rate Limiting per Provider

**User Story:** As a system operator, I want per-provider rate limiting on GEO queries, so that API rate limits are respected and the system does not get throttled.

#### Acceptance Criteria

1. THE GEO_Query_Runner SHALL enforce per-provider rate limits using a Redis sliding window rate limiter (consistent with the existing `rate_limiter.py` service).
2. THE system SHALL provide configurable rate limit settings: `geo_rate_limit_perplexity_rpm` (default 20), `geo_rate_limit_openai_rpm` (default 60), `geo_rate_limit_gemini_rpm` (default 60).
3. WHEN the rate limit for a provider is reached, THE GEO_Query_Runner SHALL delay subsequent queries for that provider until the window resets, rather than failing them.
4. THE GEO_Query_Runner SHALL process providers in parallel (one Celery task group per provider) but respect individual rate limits independently.
5. THE GEO_Query_Runner SHALL log rate limit events as activity events with details on the provider and delay applied.

### Requirement 14: Client Model Extension

**User Story:** As a system operator, I want a per-client toggle for GEO monitoring and a configurable execution schedule, so that GEO is only active for clients who subscribe to the add-on.

#### Acceptance Criteria

1. THE Client model SHALL include a `geo_monitoring_enabled` field (boolean, default false) controlling whether GEO monitoring is active for the client.
2. THE Client model SHALL include a `geo_execution_frequency` field (string, default 'twice_weekly') with allowed values: 'daily', 'twice_weekly', 'weekly'.
3. WHEN `geo_monitoring_enabled` is false for a client, THE GEO_Query_Runner SHALL skip that client entirely during scheduled execution.
4. WHEN a client is deactivated (`is_active = false`), THE GEO_Query_Runner SHALL skip that client regardless of `geo_monitoring_enabled` value.
5. THE admin client detail page SHALL display the GEO monitoring status and provide a toggle to enable/disable it.
