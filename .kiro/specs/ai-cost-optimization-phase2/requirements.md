# Requirements Document

## Introduction

AI Cost Optimization Phase 2 continues the cost reduction work started in Phase 1 (July 8, 2026). Phase 1 moved editing+persona to Gemini Flash, disabled Claude GEO, reduced runs_per_prompt 3→1, and established Gemini-only fallbacks — cutting monthly AI cost from ~$120 to ~$10 per client with 1 avatar. Phase 2 targets further reductions through: (1) smoothing GEO monitoring across all 7 days to eliminate cost spikes, (2) redesigning the AI Costs admin page for business-friendly consumption, (3) trimming generation context to reduce Claude Sonnet input tokens by ~33%, (4) enabling Anthropic prompt caching for 90% discount on cached system tokens, (5) batching scoring calls 5:1 to reduce call volume by 80%, and (6) adding a daily cost reconciliation task to detect pricing drift.

## Glossary

- **GEO_Daily_Scheduler**: The new scheduling logic that replaces Tue+Fri batch execution with daily execution of ~1/7 of prompts per day, using deterministic rotation via `prompt.id.int % 7` (UUID integer representation modulo 7, stable across restarts).
- **AI_Costs_Dashboard**: The redesigned admin page at `/admin/ai-costs` targeted at Tzvi (partner role), showing budget bars, unit economics, forecasts, and daily burn charts instead of raw engineering tables.
- **Unit_Economics_Service**: A service (`app/services/unit_economics.py`) that computes $/client/month, $/avatar/month, and $/draft from actual `ai_usage_log` data.
- **Context_Trimmer**: Logic within `generate_comment()` that caps input token consumption by truncating post body, limiting comments, and restricting few-shot examples.
- **Prompt_Cache**: Anthropic's `cache_control: {"type": "ephemeral"}` mechanism that caches system message content across calls, reducing input token cost from $3/1M to $0.30/1M for cached portions.
- **Batch_Scorer**: A modified scoring flow that submits 5 threads per LLM call instead of 1, returning a JSON array of 5 scoring decisions.
- **Cost_Reconciliation_Task**: A daily Celery task that recomputes expected cost from token counts × model rates and compares against logged `cost_usd` values to detect drift.
- **Provider_Budget**: The monthly spending limit per LLM provider (Anthropic $50, Perplexity $20, Gemini $300 credits).
- **Day_Group**: A deterministic assignment of GEO prompts to days of the week, computed as `prompt.id.int % 7` (UUID integer representation) mapping to weekday index 0-6 (Monday-Sunday). Stable across process restarts (does NOT use Python's built-in `hash()`).
- **Burn_Chart**: A stacked area chart showing daily AI cost broken down by operation type, with GEO days visually highlighted.

## Requirements

### Requirement 1: GEO Daily Smoothing

**User Story:** As Max, I want GEO monitoring distributed across all 7 days of the week so that daily AI spend stays flat instead of spiking on Tue+Fri batch days.

#### Acceptance Criteria

1. THE GEO_Daily_Scheduler SHALL replace the existing Tue+Fri `crontab(day_of_week="2,5")` beat schedule entry with a daily `crontab(hour=9, minute=30)` entry.
2. WHEN the GEO_Daily_Scheduler runs via scheduler (`triggered_by="scheduler"`), THE GEO_Daily_Scheduler SHALL select only prompts where `prompt.id.int % 7` equals the current weekday index (Monday=0, Tuesday=1, ..., Sunday=6), using the UUID's 128-bit integer representation (stable across process restarts, NOT Python's built-in `hash()`).
3. WHEN a client has N active GEO_Prompts, THE GEO_Daily_Scheduler SHALL execute exactly the count of prompts whose `id.int % 7` maps to the current weekday for that client.
4. THE GEO_Daily_Scheduler SHALL add a `prompts_override` parameter to `run_geo_batch_for_client()` that accepts an explicit list of prompt IDs to execute instead of all prompts.
5. WHEN `prompts_override` is None or not provided and the run is scheduler-triggered, THE GEO_Daily_Scheduler SHALL apply the daily group filter (hash-based weekday assignment) to select prompts.
6. THE GEO_Daily_Scheduler SHALL introduce a new Celery task `run_geo_monitoring_daily()` that computes the day group and delegates to `run_geo_batch_for_client()` with the filtered prompt list.
7. WHEN a new GEO_Prompt is created, THE GEO_Daily_Scheduler SHALL include the new prompt in rotation on its assigned day (determined by `id.int % 7`) without manual configuration.
8. IF no prompts are assigned to the current day group for a given client, THEN THE GEO_Daily_Scheduler SHALL skip that client for the day without error.
9. WHEN a GEO batch is triggered manually via admin UI (`triggered_by="manual"`), THE GEO_Daily_Scheduler SHALL execute ALL active prompts for that client regardless of day group assignment.

### Requirement 2: AI Costs Page Redesign

**User Story:** As Tzvi (partner), I want the AI Costs page to show budget status, unit economics, and cost forecasts in a business-friendly layout so that I can make pricing decisions without reading engineering debug tables.

#### Acceptance Criteria

1. THE AI_Costs_Dashboard SHALL display a hero section with provider budget bars showing: provider name, amount spent this month (2 decimal places), monthly limit (read from system_settings keys `provider_budget_anthropic`, `provider_budget_perplexity`, `provider_budget_gemini` with defaults $50, $20, $300), and percentage fill rounded to 1 decimal place.
2. IF the projected month-end spend exceeds 70% of a provider's monthly limit, THEN THE AI_Costs_Dashboard SHALL display the budget bar in amber; IF the projected month-end spend exceeds 90%, THEN THE AI_Costs_Dashboard SHALL display the budget bar in red, where projected month-end spend is calculated as: (spend so far this month / days elapsed this month) × total days in month.
3. IF fewer than 3 days have elapsed in the current month, THEN THE AI_Costs_Dashboard SHALL display the budget bars without color thresholds and SHALL display the unit economics card with a "Collecting data" indicator instead of computed values.
4. THE AI_Costs_Dashboard SHALL display a Unit Economics card showing: cost per client per month, cost per avatar per month, and cost per draft, each to 4 decimal places, computed from the trailing 30-day `ai_usage_log` data divided by the count of active clients, active avatars, and total drafts generated in that period respectively.
5. THE AI_Costs_Dashboard SHALL display an "At N clients" forecast section showing projected monthly cost at 5, 10, 25, and 50 clients based on the trailing 30-day cost-per-client value from criterion 4.
6. THE AI_Costs_Dashboard SHALL display a daily burn chart (stacked area) covering the trailing 30 days, broken down by operation type (scoring, generation, editing, persona, GEO, hobby, other), with days that have GEO batch executions marked by a vertical line annotation.
7. THE AI_Costs_Dashboard SHALL collapse existing detail tables (per-operation breakdown, per-client breakdown, per-day breakdown) into `<details>` elements that default to closed state.
8. THE AI_Costs_Dashboard SHALL introduce a new service file `app/services/unit_economics.py` that computes all unit economics metrics.
9. THE Unit_Economics_Service SHALL compute cost per draft as: total generation cost in the trailing 30-day period divided by total drafts generated in the same period; IF total drafts generated is zero, THEN THE Unit_Economics_Service SHALL return null for cost per draft.

### Requirement 3: Trim Generation Context

**User Story:** As Max, I want the generation prompt context reduced from ~12K to ~8K input tokens so that Claude Sonnet input costs drop by approximately 33% without significantly degrading comment quality.

#### Acceptance Criteria

1. WHEN assembling the generation prompt, THE Context_Trimmer SHALL truncate `thread.post_body` to a maximum of 500 characters, configurable via the `generation_max_body_chars` system setting (default: 500).
2. WHEN assembling the generation prompt, THE Context_Trimmer SHALL parse `thread.comments_json` from its raw JSON string representation into a list of comment objects, then include only the top 3 comments sorted by `score` field descending; IF comments lack a `score` field or parsing fails, THEN THE Context_Trimmer SHALL take the first 3 elements from the raw string (splitting by comment delimiter).
3. WHEN assembling the generation prompt, THE Context_Trimmer SHALL truncate `voice_profile_md` to a maximum of 500 characters, configurable via the `generation_max_voice_chars` system setting (default: 500).
4. WHEN assembling the generation prompt, THE Context_Trimmer SHALL include a maximum of 3 few-shot examples from the self-learning loop, selecting the 3 most recent examples that match the target subreddit (or most recent overall if fewer than 3 match).
5. THE Context_Trimmer SHALL preserve the full system prompt, strategy context, and placement instructions without truncation.
6. THE Context_Trimmer SHALL apply truncation at the last word boundary before or at the character limit (not mid-word) and append "..." when text is truncated.
7. IF `thread.post_body` is equal to or shorter than the configured maximum, THEN THE Context_Trimmer SHALL include the full body without truncation or ellipsis.
8. WHEN each individual comment from `thread.comments_json` exceeds 300 characters, THE Context_Trimmer SHALL truncate that comment to 300 characters using the same word-boundary truncation rule.

### Requirement 4: Anthropic Prompt Caching

**User Story:** As Max, I want the system prompt and voice profile (~8K tokens) cached across Claude Sonnet calls for the same avatar so that cached input tokens cost $0.30/1M instead of $3.00/1M, saving approximately $5/month per avatar.

#### Acceptance Criteria

1. WHEN `call_llm()` is invoked with a model matching the pattern `anthropic/*`, THE Prompt_Cache SHALL add `cache_control: {"type": "ephemeral"}` to a copy of the first message in the messages array, without mutating the original messages list passed by the caller.
2. WHEN `call_llm()` is invoked with a model that does NOT match `anthropic/*`, THE Prompt_Cache SHALL NOT add `cache_control` to any message.
3. THE Prompt_Cache SHALL set the `cache_control` field using the LiteLLM-supported format: `messages[0]["cache_control"] = {"type": "ephemeral"}`.
4. THE Prompt_Cache SHALL apply caching only to the first message in the messages array (the system message containing system prompt + voice profile). IF Anthropic returns an error indicating the cached content is below the minimum cache block size, THE system SHALL handle it via the retry logic in criterion 6.
5. WHEN prompt caching is active, THE system SHALL log `cache_creation_input_tokens` and `cache_read_input_tokens` from the LLM response usage metadata when the response includes these fields.
6. IF the LLM provider returns an error related to `cache_control` (the error message or type references "cache_control" or "caching"), THEN THE system SHALL retry the call exactly once without `cache_control` and log a warning indicating the cache_control field was stripped.
7. WHEN `cache_read_input_tokens` is present in the response usage metadata and its value is greater than 0, THE system SHALL log the cache hit ratio as `cache_read_input_tokens / (cache_read_input_tokens + cache_creation_input_tokens + prompt_tokens)` for observability.

### Requirement 5: Batch Scoring

**User Story:** As Max, I want scoring to process 5 threads per LLM call instead of 1 so that scoring call volume drops by 80% (from ~600 calls/month/avatar to ~120).

#### Acceptance Criteria

1. WHEN scoring threads, THE Batch_Scorer SHALL group candidate threads into batches of up to 5 threads and submit one LLM call per batch, where the batch size is read from the `scoring_batch_size` system setting (default: 5).
2. THE Batch_Scorer SHALL construct a prompt containing the context of all threads in the batch (post title, truncated post body up to 800 characters, truncated comments up to 1500 characters per thread) and request a JSON response conforming to the `BatchScoringOutput` schema containing one scoring decision per thread with fields: `thread_index` (0-based integer matching input order), `tag` (engage/monitor/skip), `composite` (integer 0-9), `alert` (boolean), `relevance` (integer 0-3), `quality` (integer 0-3), `strategic` (integer 0-3), `intent` (string enum), and `reason` (string up to 15 words).
3. WHEN the LLM returns a valid JSON object whose `results` array contains entries with valid `thread_index` values covering all threads in the batch, THE Batch_Scorer SHALL create or update one `ThreadScore` record per thread with the corresponding scoring decision.
4. IF the batch response fails JSON schema validation OR contains fewer valid `thread_index` entries than the number of threads submitted in the batch, THEN THE Batch_Scorer SHALL fall back to scoring each unmatched thread in the failed batch individually via single-thread LLM calls (1 call per thread).
5. WHEN fewer than 5 candidate threads remain in the scoring queue for a given avatar, THE Batch_Scorer SHALL submit a partial batch containing only the remaining 1-4 threads rather than padding with empty entries.
6. THE Batch_Scorer SHALL create one `ThreadScore` record per thread in the batch with fields `tag` (engage/monitor/skip), `composite` (0-9), `alert`, `relevance` (0-3), `quality` (0-3), `strategic` (0-3), `intent`, and `scoring_reasoning`.
7. THE Batch_Scorer SHALL invoke `log_ai_usage()` exactly once per batch LLM call with `operation="scoring_batch"` and the `subreddit_name` field set to `"batch_{N}"` where N is the number of threads in the batch, recording the token counts from the LLM response.
8. THE Batch_Scorer SHALL preserve the existing smart scoring budget logic: only `remaining_budget × 3` threads are scored per avatar per scoring run, with a hard cap of 15 threads maximum regardless of remaining budget.

### Requirement 6: Cost Reconciliation Task

**User Story:** As Max, I want a daily automated check that compares expected cost (computed from token counts × model rates) against logged `cost_usd` so that I detect when LiteLLM's `completion_cost()` is inaccurate or when provider pricing changes.

#### Acceptance Criteria

1. THE Cost_Reconciliation_Task SHALL run daily at 01:00 via Celery Beat.
2. THE Cost_Reconciliation_Task SHALL compute expected cost for the previous 24-hour window (from 01:00 yesterday to 01:00 today, UTC) as: `SUM(input_tokens × model_input_rate + output_tokens × model_output_rate)` per model, using rates from the `MODEL_COSTS` dictionary in `ai.py`.
3. THE Cost_Reconciliation_Task SHALL compare computed expected cost against `SUM(cost_usd)` from `ai_usage_log` grouped by model for the same 24-hour window.
4. IF the absolute delta between expected and logged cost exceeds 5% for any model AND the logged cost for that model exceeds $0.01 in the period, THEN THE Cost_Reconciliation_Task SHALL call `notify_ops()` with level "warning" and category "cost_reconciliation", including the model name, expected cost, logged cost, and delta percentage.
5. THE Cost_Reconciliation_Task SHALL be registered in `beat_app.py` with schedule `crontab(hour=1, minute=5)` (offset from `compute_daily_performance_metrics` at 01:00 to avoid concurrent PG load).
6. THE Cost_Reconciliation_Task SHALL reside in a new file `app/tasks/cost_reconciliation.py`.
7. IF `ai_usage_log` has no records for a model in the 24-hour period, THEN THE Cost_Reconciliation_Task SHALL skip that model without raising an alert.
8. IF a model in `ai_usage_log` does not exist in the `MODEL_COSTS` dictionary, THEN THE Cost_Reconciliation_Task SHALL log a warning with the unknown model name and skip reconciliation for that model.
9. THE Cost_Reconciliation_Task SHALL log a summary of reconciliation results (models checked, deltas found, alerts raised) as an INFO-level log entry.
