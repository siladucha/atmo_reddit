# Requirements Document

## Introduction

Buyer-Intent Prompt Intelligence Engine — a new module that sits on top of the existing GEO/AEO Prompt Monitoring system. Currently, prompts are created manually by admins. This module automates prompt generation using LLM-based intelligence, taking client metadata (brand, product, category, audience, competitors, use cases) and producing a structured set of buyer-intent prompts that simulate real user research queries across AI assistants.

The generated prompts feed directly into the existing `geo_prompts` table and are executed by the existing `geo_query_runner.py` infrastructure. The module adds: automatic prompt generation pipeline, intent taxonomy with distribution control, AI query rewriting, competitor injection, semantic diversity filtering with rebalancing, Share of Voice metrics, Reddit Influence Score, and periodic prompt refresh rotation.

Revenue impact: Eliminates manual prompt creation bottleneck (currently 30-60 min per client), enables scaling GEO monitoring to all clients automatically, and provides higher-quality prompts that better simulate real buyer behavior.

## Glossary

- **Prompt_Generator**: The service that orchestrates the multi-stage prompt generation pipeline, managing state transitions and inter-stage data contracts.
- **Prompt_Candidate**: The core intermediate data object flowing between pipeline stages — contains prompt text, intent_category, funnel_stage, intent_strength, competitors_injected, entities_expected, embedding vector, and validity_score. Defined as a Pydantic schema shared across all stages.
- **Intent_Taxonomy**: The classification system for generated prompts with five categories: problem, comparison, alternatives, evaluation, and solution — each representing a distinct buyer research pattern.
- **Distribution_Control**: The mechanism that enforces target percentages across intent categories: 30% problem-based, 30% comparison, 20% alternatives, 10% evaluation, 10% solution. Includes a rebalancing step after diversity filtering.
- **AI_Query_Rewriter**: The pipeline stage that transforms raw intent templates into natural AI-native queries — removing marketing tone, brand-first framing, and promotional language.
- **Competitor_Injector**: The pipeline stage that implicitly weaves competitor presence into generated prompts, creating queries where competitor mentions would naturally appear in AI responses. The injector operates only on prompt text — never referencing the client brand in the generated query.
- **Diversity_Filter**: The service that performs semantic deduplication, overlap control, and funnel stage balance (awareness/consideration/decision) on generated prompt sets. Triggers rebalancing when distribution targets are violated.
- **Rebalancer**: The pipeline sub-stage invoked after Diversity Filter when category or funnel distribution falls outside acceptable bounds. Generates targeted replacement prompts for under-represented categories.
- **Share_of_Voice**: An aggregated metric computed as `brand_mentions / (brand_mentions + competitor_mentions + neutral_responses)` across execution results. Uses three-category normalization: brand present, competitor present, neither present.
- **Reddit_Influence_Score**: A metric measuring the frequency of Reddit URL citations in AI responses, computed per prompt and aggregated per client, normalized to a 0-100 scale.
- **Buyer_Intent_Prompt_Set**: The complete collection of generated prompts for a client, stored in `geo_prompts` with generation metadata linking back to the pipeline run.
- **Prompt_Generation_Run**: A single execution of the generation pipeline for a client, producing a new or refreshed set of buyer-intent prompts. Follows a state machine: pending → running → domain_done → intent_done → rewritten → injected → filtered → stored | failed.
- **Client_Metadata**: The structured input data for prompt generation: brand_name, product_description, category, target_audience, competitors, and optional fields (pricing_model, deployment_type, geo_focus, use_cases).
- **Funnel_Stage**: The buyer journey position a prompt targets: awareness (TOFU), consideration (MOFU), or decision (BOFU).
- **Difficulty_Score_Predicted**: A 0-1 heuristic score assigned at generation time based on category type and competitor count — estimates how hard it will be for the brand to appear.
- **Difficulty_Score_Observed**: A 0-1 score computed from actual execution results using exponential moving average — reflects real-world competitive difficulty.
- **Weak_Area**: A category or funnel stage where the client's brand consistently fails to appear in AI responses.
- **Prompt_Refresh_Cycle**: The monthly process of re-generating and rotating prompts to stay current with market changes, new competitors, and evolving buyer language.
- **Generation_Run_State_Machine**: The lifecycle states of a generation run: pending → running → domain_done → intent_done → rewritten → injected → filtered → stored → completed | failed. Each state transition is logged.
- **GEO_Execution_Batch**: The existing `geo_execution_batches` table/model — groups all query results from a single scheduled run per client. Share of Voice and Reddit Influence Score are computed per batch.

## Requirements

### Requirement 1: Client Metadata Storage for Prompt Generation

**User Story:** As a platform admin, I want to store structured client metadata (product description, category, target audience, use cases), so that the prompt generation engine has sufficient context to produce relevant buyer-intent queries.

#### Acceptance Criteria

1. THE Client model SHALL include a `geo_product_description` field (text, max 2000 characters) for storing the client's product value proposition.
2. THE Client model SHALL include a `geo_category` field (string, max 100 characters) for the product market category.
3. THE Client model SHALL include a `geo_target_audience` field (JSONB array of strings) for target buyer personas.
4. THE Client model SHALL include a `geo_use_cases` field (JSONB array of strings, max 20 entries) for specific use cases the product addresses.
5. WHEN a client already has `company_profile`, `competitive_landscape`, or `icp_profiles` populated, THE Prompt_Generator SHALL use those existing fields as supplemental context for prompt generation.
6. THE admin UI SHALL provide a "Prompt Intelligence" configuration section within the GEO page allowing input of geo_product_description, geo_category, geo_target_audience, and geo_use_cases.
7. IF geo_product_description or geo_category is empty for a client, THEN THE Prompt_Generator SHALL refuse to generate prompts and display a message indicating which required fields are missing.

### Requirement 2: Prompt Candidate Data Contract

**User Story:** As a system operator, I want a unified data contract between all pipeline stages, so that each stage produces and consumes a well-defined schema without ambiguity.

#### Acceptance Criteria

1. THE system SHALL define a `PromptCandidate` Pydantic schema as the core intermediate object flowing between all pipeline stages.
2. THE PromptCandidate schema SHALL contain: text (str), intent_category (enum: problem/comparison/alternatives/evaluation/solution), funnel_stage (enum: awareness/consideration/decision), intent_strength (enum: high/mid/low), competitors_injected (list of strings), entities_expected (list of strings), embedding (list of floats, nullable), validity_score (float 0-1, nullable), rejection_reason (str, nullable).
3. EACH pipeline stage SHALL accept a list of PromptCandidate objects as input and return a list of PromptCandidate objects as output.
4. THE PromptCandidate schema SHALL be the single source of truth for inter-stage communication — stages SHALL NOT pass untyped dictionaries or raw strings.
5. WHEN a PromptCandidate fails validation at any stage boundary, THE system SHALL mark it with a rejection_reason and exclude it from further processing without halting the pipeline.

### Requirement 3: Prompt Generation Pipeline Execution

**User Story:** As a platform admin, I want to trigger automatic generation of buyer-intent prompts from client metadata, so that I do not have to manually write each monitoring prompt.

#### Acceptance Criteria

1. THE Prompt_Generator SHALL expose a "Generate Prompts" action in the admin GEO page that triggers the full generation pipeline for a client.
2. WHEN the "Generate Prompts" action is triggered, THE Prompt_Generator SHALL execute a multi-stage pipeline: Domain Understanding → Intent Expansion → AI Query Rewriting → Competitor Injection → Diversity Filter → Rebalancing (conditional).
3. THE Prompt_Generator SHALL produce between 15 and 40 prompts per client per generation run (configurable via system setting `geo_prompt_generation_target_count`, default 25).
4. WHEN the pipeline completes, THE Prompt_Generator SHALL store all generated prompts in the existing `geo_prompts` table with `is_active = true` and a reference to the generation run.
5. THE Prompt_Generator SHALL execute as a Celery task on the `geo_queries` queue to avoid blocking the admin UI.
6. WHEN a generation run starts, THE system SHALL create a `geo_prompt_generation_runs` record and transition through states: pending → running → domain_done → intent_done → rewritten → injected → filtered → stored.
7. IF any stage of the pipeline fails after 2 retries, THEN THE Prompt_Generator SHALL attempt fallback to Gemini Flash model before marking the generation run as failed.
8. IF a pipeline stage fails with no recovery possible, THEN THE system SHALL mark the run as failed at the specific stage, log error details, and preserve any successfully generated candidates up to that point.

### Requirement 4: Domain Understanding Stage

**User Story:** As a system operator, I want the pipeline to first build a structured understanding of the client's market domain, so that generated prompts reflect real buyer research patterns in that space.

#### Acceptance Criteria

1. WHEN the Domain Understanding stage executes, THE Prompt_Generator SHALL send client metadata (product_description, category, target_audience, competitors, use_cases, plus existing company_profile/competitive_landscape if available) to an LLM with a structured extraction prompt.
2. THE Domain Understanding stage SHALL extract a `DomainContext` Pydantic object containing: core_value_prop (str), primary_category (str), adjacent_categories (list of str), competitive_landscape_summary (str), buyer_pain_points (list of 5-10 strings), buying_triggers (list of strings), and market_language_patterns (list of typical query phrases buyers use in this space).
3. THE Domain Understanding stage SHALL use Claude Sonnet via LiteLLM as primary model, with Gemini Flash as fallback.
4. THE Domain Understanding stage SHALL validate LLM output against the DomainContext Pydantic schema before passing to the next stage.
5. IF the LLM returns malformed output, THEN THE Domain Understanding stage SHALL retry up to 2 times before attempting Gemini Flash fallback, then mark as failed only if all attempts exhausted.
6. THE Domain Understanding stage SHALL store the extracted DomainContext in the generation run record as `domain_context` (JSONB) for debugging and auditability.
7. THE Domain Understanding stage SHALL NOT include the client's brand_name in buyer_pain_points or market_language_patterns — the LLM prompt SHALL instruct extraction of generic category-level patterns.

### Requirement 5: Intent Expansion Stage

**User Story:** As a system operator, I want the pipeline to generate diverse prompt intents across all buyer research patterns, so that the prompt set covers the full buying journey.

#### Acceptance Criteria

1. WHEN the Intent Expansion stage executes, THE Prompt_Generator SHALL generate raw PromptCandidate objects with target distribution: problem (30%), comparison (30%), alternatives (20%), evaluation (10%), and solution (10%).
2. THE Intent Expansion stage SHALL over-generate by 50% above target count (e.g., target 25 → generate 38) to provide buffer for downstream filtering and deduplication.
3. FOR EACH generated PromptCandidate, THE Intent Expansion stage SHALL populate: text, intent_category, funnel_stage, and intent_strength fields.
4. THE Intent Expansion stage SHALL NOT generate any prompt text containing the client's brand_name — the LLM generation prompt SHALL explicitly instruct to avoid the brand and focus on category-level buyer questions.
5. THE Intent Expansion stage SHALL generate at least 2 PromptCandidates per active competitor in the client's competitor list to ensure competitive coverage.
6. THE Intent Expansion stage SHALL consume the DomainContext from the previous stage as the primary input — not raw client metadata.
7. THE Intent Expansion stage SHALL produce intents matching real buyer research patterns: problem-aware queries (how to solve X), comparison queries (differences between tools), alternatives queries (what else exists besides Y), evaluation queries (best tools for use case), and solution queries (how to achieve outcome for persona).

### Requirement 6: AI Query Rewriting Stage

**User Story:** As a system operator, I want raw intents transformed into natural AI-native queries, so that prompts sound like real users asking AI assistants for help.

#### Acceptance Criteria

1. WHEN the AI Query Rewriting stage executes, THE AI_Query_Rewriter SHALL transform each PromptCandidate's text field into a natural language query that mimics how a real buyer would ask an AI assistant.
2. THE AI_Query_Rewriter SHALL enforce zero marketing tone: no superlatives, no brand-first framing, no corporate jargon ("leverage", "synergy", "best-in-class").
3. THE AI_Query_Rewriter SHALL produce queries in first person or neutral research tone (e.g., "I'm evaluating tools for...", "What helps with...").
4. THE AI_Query_Rewriter SHALL vary query structure across the set: direct questions, comparative requests, scenario-based queries, and decision-framing queries.
5. THE AI_Query_Rewriter SHALL validate that rewritten queries are between 20 and 200 characters in length — queries outside bounds are marked with rejection_reason.
6. IF a rewritten query contains the client's brand_name (case-insensitive), THEN THE AI_Query_Rewriter SHALL mark the PromptCandidate with rejection_reason "brand_leak" and attempt one regeneration before excluding it.
7. THE AI_Query_Rewriter SHALL process PromptCandidates in batches of 10 to reduce LLM call overhead while maintaining per-query quality.

### Requirement 7: Competitor Injection Stage

**User Story:** As a system operator, I want competitors implicitly woven into generated prompts, so that AI responses naturally include competitive comparisons where the brand can appear.

#### Acceptance Criteria

1. WHEN the Competitor Injection stage executes, THE Competitor_Injector SHALL modify at least 40% of PromptCandidates to include implicit competitor presence in the query text.
2. THE Competitor_Injector SHALL use three injection patterns: explicit comparison (X vs Y for use case), implicit context (alternatives to competitor for scenario), and category framing (tools like competitor but for different need).
3. THE Competitor_Injector SHALL distribute competitor references across the client's active competitor list — no single competitor appearing in more than 40% of injected prompts.
4. THE Competitor_Injector SHALL NOT inject more than 2 competitor names into a single prompt to maintain natural query feel.
5. THE Competitor_Injector SHALL update the `competitors_injected` field on modified PromptCandidates with the list of competitor names added.
6. THE Competitor_Injector SHALL update `entities_expected` on each PromptCandidate with the entities (brand, specific competitors) that the prompt is designed to elicit in AI responses.
7. THE Competitor_Injector SHALL NOT reference the client's brand_name in any prompt text — the brand is the entity we expect to appear in responses, never in the query itself.

### Requirement 8: Semantic Diversity Filter and Rebalancing

**User Story:** As a system operator, I want duplicate and semantically overlapping prompts removed with automatic rebalancing when distribution targets are violated, so that the final prompt set is both diverse and well-distributed.

#### Acceptance Criteria

1. WHEN the Diversity Filter stage executes, THE Diversity_Filter SHALL compute embedding vectors for all PromptCandidates using a lightweight embedding model (sentence-transformers or Gemini embedding API).
2. THE Diversity_Filter SHALL remove PromptCandidates where pairwise cosine similarity exceeds 0.85 with any other candidate, keeping the candidate with higher diversity contribution to the overall set.
3. AFTER deduplication, THE Diversity_Filter SHALL check distribution against targets: intent categories within ±10% of (30/30/20/10/10) AND funnel stages at minimum 20% awareness, 30% consideration, 20% decision.
4. IF distribution targets are violated after filtering, THEN THE Rebalancer SHALL trigger a targeted regeneration: identify under-represented categories, invoke Intent Expansion + AI Query Rewriting for only those categories, and merge results back into the set.
5. THE Rebalancer SHALL execute at most 2 regeneration loops before accepting the available distribution and logging the final deviation.
6. THE Diversity_Filter SHALL store embedding vectors on each PromptCandidate for potential future use (similarity search, prompt discovery).
7. THE Diversity_Filter SHALL log: total candidates in, candidates removed (with pairs that triggered removal), final distribution percentages, and whether rebalancing was triggered.

### Requirement 9: Generated Prompt Metadata Storage

**User Story:** As a platform admin, I want each generated prompt to carry rich metadata (category, intent type, funnel stage, difficulty score), so that I can analyze performance across dimensions.

#### Acceptance Criteria

1. THE GeoPrompt model SHALL include an `intent_category` field (string: problem/comparison/alternatives/evaluation/solution, nullable) for generated prompts.
2. THE GeoPrompt model SHALL include an `intent_strength` field (string: high/mid/low, nullable) indicating buying intent level.
3. THE GeoPrompt model SHALL include a `funnel_stage` field (string: awareness/consideration/decision, nullable) indicating buyer journey position.
4. THE GeoPrompt model SHALL include an `entities_expected` field (JSONB array, nullable) listing entities the prompt is designed to surface in AI responses.
5. THE GeoPrompt model SHALL include a `difficulty_score_predicted` field (decimal 0.00-1.00, nullable) assigned at generation time.
6. THE GeoPrompt model SHALL include a `difficulty_score_observed` field (decimal 0.00-1.00, nullable) computed from execution results.
7. THE GeoPrompt model SHALL include a `generation_run_id` field (UUID FK to geo_prompt_generation_runs, nullable) linking to the generation run that created the prompt.
8. THE GeoPrompt model SHALL include a `source` field (string: manual/generated, default "manual") distinguishing human-created prompts from auto-generated ones.

### Requirement 10: Difficulty Score — Predicted and Observed

**User Story:** As a platform admin, I want prompts to have both a predicted difficulty (at generation time) and an observed difficulty (from execution data), so that I can compare expectations to reality and identify optimization opportunities.

#### Acceptance Criteria

1. WHEN the Prompt_Generator produces new prompts, THE system SHALL assign `difficulty_score_predicted` using heuristics: comparison category = 0.7 base, alternatives = 0.8, evaluation = 0.6, problem = 0.4, solution = 0.3, adjusted upward by 0.05 per competitor name present in the prompt text.
2. AFTER the first execution of a prompt, THE system SHALL compute `difficulty_score_observed` based on: (1 - brand_appearance_rate) weighted by competitor density in responses.
3. THE system SHALL update `difficulty_score_observed` after each subsequent execution batch using exponential moving average: `new_score = 0.7 × latest_computed + 0.3 × previous_observed`.
4. THE admin GEO page SHALL display both scores side-by-side, allowing admins to identify where predicted and observed diverge (indicating either generation quality issues or market shifts).
5. THE system SHALL flag prompts where `|predicted - observed| > 0.3` as "calibration mismatches" in the admin UI for review.

### Requirement 11: Share of Voice Metric Computation

**User Story:** As a platform admin, I want to see Share of Voice (brand vs competitors) computed from execution results using three-category normalization, so that I can accurately measure competitive positioning in AI responses.

#### Acceptance Criteria

1. WHEN a GEO_Execution_Batch completes, THE system SHALL classify each successful query result into one of three categories: brand_present (brand detected), competitor_present (at least one competitor detected, brand not detected), neutral (neither brand nor any competitor detected).
2. THE system SHALL compute Share_of_Voice using three-category normalization: `brand_present_count / total_successful_runs × 100` (raw brand rate) AND `brand_present_count / (brand_present_count + competitor_present_count) × 100` (competitive share — excludes neutral).
3. THE system SHALL compute Share_of_Voice at three levels: per-prompt, per-intent-category, and per-client aggregate.
4. THE system SHALL store both `share_of_voice_raw` (brand rate) and `share_of_voice_competitive` (excluding neutral) in the `geo_frequency_metrics` table.
5. THE system SHALL compute per-competitor breakdown: for each competitor, the percentage of non-neutral responses where that competitor appears.
6. WHEN Share_of_Voice is computed, THE system SHALL compare against the previous batch and store the delta (change direction and magnitude).
7. THE admin GEO page SHALL display both Share of Voice metrics with trend visualization over the last 10 batches.

### Requirement 12: Reddit Influence Score Computation

**User Story:** As a platform admin, I want a dedicated Reddit Influence Score showing how often Reddit is cited in AI responses to our prompts, so that I can measure the effectiveness of our Reddit presence strategy.

#### Acceptance Criteria

1. WHEN a GEO_Execution_Batch completes, THE system SHALL compute Reddit_Influence_Score as: `(runs_with_reddit_citations / total_successful_runs) × 100` normalized to 0-100.
2. THE system SHALL compute Reddit_Influence_Score at per-prompt and per-client aggregate levels.
3. THE system SHALL store Reddit_Influence_Score in the `geo_frequency_metrics` table by adding a `reddit_influence_score` field (decimal 0-100).
4. THE system SHALL track Reddit citation breakdown: subreddits cited and frequency distribution across those subreddits, stored as JSONB in the metrics record.
5. WHEN Reddit_Influence_Score changes by more than 20 points between consecutive batches, THE system SHALL emit an activity event flagging the significant change.
6. THE admin GEO page SHALL display Reddit Influence Score as a trend line alongside brand appearance rate.

### Requirement 13: Weak Area Detection

**User Story:** As a platform admin, I want the system to automatically identify categories and funnel stages where the brand fails to appear, so that I can prioritize content strategy improvements.

#### Acceptance Criteria

1. WHEN a GEO_Execution_Batch completes, THE system SHALL identify Weak Areas: intent categories where brand_appearance_rate is below 20% across all prompts in that category.
2. THE system SHALL identify Weak Areas at the funnel stage level: any stage (awareness/consideration/decision) where brand_appearance_rate is below 25%.
3. THE system SHALL store detected weak areas in the execution batch record as `weak_areas` (JSONB array of objects with dimension, value, appearance_rate, and prompt_count).
4. THE admin GEO page SHALL display weak areas as actionable insights with specific details on which prompts are affected.
5. WHEN a weak area persists across 3 consecutive batches, THE system SHALL flag it as a "persistent gap" and emit an activity event for attention.

### Requirement 14: Periodic Prompt Refresh Cycle

**User Story:** As a system operator, I want prompt sets automatically refreshed monthly, so that monitoring stays current with evolving market language, new competitors, and changing buyer behavior.

#### Acceptance Criteria

1. THE system SHALL support a configurable refresh cycle via system setting `geo_prompt_refresh_interval_days` (default: 30 days).
2. THE system SHALL include a Celery Beat task (`refresh_geo_prompts_due`) running daily at 05:00 that checks all clients for prompt sets exceeding the refresh interval.
3. WHEN a client's generated prompt set age exceeds the refresh interval, THE system SHALL trigger a new Prompt_Generation_Run automatically.
4. WHEN a refresh run generates new prompts, THE system SHALL deactivate prompts from the previous generation (set `is_active = false`) and activate the new set.
5. THE refresh cycle SHALL preserve manually created prompts — only auto-generated prompts (source = "generated") are subject to rotation.
6. THE system SHALL retain deactivated prompt records and their historical execution data for trend comparison.
7. THE admin GEO page SHALL display prompt set age and next scheduled refresh date per client.
8. THE admin SHALL have the ability to manually trigger an early refresh or skip a scheduled refresh for a specific client.

### Requirement 15: Prompt Generation Run History and Audit

**User Story:** As a platform admin, I want to see the history of all prompt generation runs per client with full state machine visibility, so that I can track how prompt sets evolve and debug generation issues.

#### Acceptance Criteria

1. THE system SHALL store generation runs in a `geo_prompt_generation_runs` table with fields: id (UUID), client_id (FK), status (pending/running/domain_done/intent_done/rewritten/injected/filtered/stored/completed/failed), current_stage (string), prompts_generated (integer), prompts_after_filter (integer), domain_context (JSONB), generation_config (JSONB), rejected_prompts (JSONB array of {text, reason}), distribution_final (JSONB), error_details (text, nullable), started_at, completed_at, created_at.
2. THE system SHALL update the generation run record at each state transition with timestamp and stage name.
3. THE admin GEO page SHALL display generation run history: date, status, current stage (if running), prompts generated, prompts after filtering, and link to view details.
4. WHEN a generation run completes, THE system SHALL log it in the `ai_usage_log` table with operation = 'geo_prompt_generation' including total tokens and cost.
5. THE admin SHALL have the ability to view: domain_context, rejected prompts with reasons, and final distribution for any historical generation run.

### Requirement 16: Integration with Existing GEO Execution Infrastructure

**User Story:** As a system operator, I want generated prompts to work seamlessly with the existing execution engine, brand detection, and citation parsing, so that no changes are needed to downstream systems.

#### Acceptance Criteria

1. THE Prompt_Generator SHALL store generated prompts in the existing `geo_prompts` table, ensuring full compatibility with `geo_query_runner.py` (which reads prompt_text, client_id, is_active).
2. THE generated prompts SHALL populate the existing `category` field on GeoPrompt with the intent_category value for backward compatibility with existing UI and queries.
3. WHEN generated prompts are executed by the existing GEO_Query_Runner, THE system SHALL compute Share of Voice and Reddit Influence Score in addition to existing frequency metrics — extending `_compute_frequency_metrics()`.
4. THE Prompt_Generator SHALL respect the existing 50 active prompts per client limit — if the new set plus existing manual prompts would exceed 50, THE system SHALL deactivate oldest generated prompts first.
5. THE system SHALL support a mixed prompt library: both manually created prompts (source = "manual") and auto-generated prompts (source = "generated") active simultaneously.
6. THE admin UI prompt list SHALL visually distinguish between manually created and auto-generated prompts with a badge indicator.

### Requirement 17: Generation Rules Enforcement

**User Story:** As a system operator, I want strict rules enforced during prompt generation, so that generated prompts never violate brand safety or query quality standards.

#### Acceptance Criteria

1. THE Prompt_Generator SHALL reject any PromptCandidate whose text field contains the client's brand_name (case-insensitive substring match).
2. THE Prompt_Generator SHALL reject any PromptCandidate that reads as a marketing question (detected via heuristic patterns: "Why is X the best?", "How does X lead?", superlatives about named products).
3. THE Prompt_Generator SHALL ensure each PromptCandidate contains exactly one primary intent — not multiple questions combined (detected by presence of multiple question marks or conjunction patterns).
4. THE Prompt_Generator SHALL ensure PromptCandidate text is between 20 and 200 characters in length.
5. THE Prompt_Generator SHALL enforce that comparison-category prompts include at least one competitor name or category reference but never the client's brand.
6. THE Prompt_Generator SHALL accumulate all rejected candidates with rejection_reason in the generation run record for quality monitoring.
7. THE system SHALL provide a system setting `geo_generation_quality_threshold` (decimal 0-1, default 0.7) — PromptCandidates with validity_score below this threshold are rejected.

### Requirement 18: Pipeline Failure Strategy

**User Story:** As a system operator, I want the generation pipeline to handle failures gracefully with model fallback, circuit breaking, and partial continuation, so that temporary LLM issues do not completely block prompt generation.

#### Acceptance Criteria

1. FOR EACH LLM-dependent stage (Domain Understanding, Intent Expansion, AI Query Rewriting), THE system SHALL implement a two-tier fallback: primary model (Claude Sonnet) → fallback model (Gemini Flash) → fail.
2. FOR EACH LLM call within a stage, THE system SHALL retry up to 2 times with exponential backoff (10s × 2^attempt) before invoking the fallback model.
3. IF the Intent Expansion or Rewriting stage partially fails (some candidates generated, some failed), THE system SHALL continue with successfully generated candidates rather than aborting the entire pipeline.
4. THE system SHALL implement a cost circuit breaker: if cumulative LLM cost for a single generation run exceeds system setting `geo_generation_max_cost_usd` (default 2.00), THE pipeline SHALL halt and mark the run as failed with reason "cost_limit_exceeded".
5. WHEN a generation run fails, THE system SHALL preserve the state machine position and allow manual retry from the failed stage (not requiring full restart from domain understanding).
6. THE system SHALL log all LLM call attempts (success and failure) with model used, tokens consumed, latency, and cost in the ai_usage_log.

### Requirement 19: Admin UI for Prompt Intelligence

**User Story:** As a platform admin, I want a dedicated Prompt Intelligence section in the GEO admin page, so that I can manage generation, view metrics, and monitor prompt performance.

#### Acceptance Criteria

1. THE admin GEO page SHALL include a "Prompt Intelligence" tab showing: generation status, prompt set age, Share of Voice trend, Reddit Influence Score trend, and weak areas.
2. THE admin UI SHALL provide a "Generate Prompts" button that triggers a new generation run with a loading indicator and result notification via HTMX.
3. THE admin UI SHALL display generated prompts grouped by intent_category with columns: prompt text, funnel stage, intent strength, predicted difficulty, observed difficulty, and last appearance rate.
4. THE admin UI SHALL provide a "Refresh Now" button to trigger an early prompt refresh cycle.
5. THE admin UI SHALL display a Share of Voice chart showing brand vs top 3 competitors over the last 10 execution batches.
6. THE admin UI SHALL display weak area cards with category, funnel stage, appearance rate, and affected prompt count.
7. THE admin UI SHALL display the generation run state machine status when a run is in progress.
8. THE admin UI SHALL use HTMX partials consistent with the existing admin panel dark theme.
9. THE admin UI SHALL display generation run cost (LLM tokens used and estimated USD) for transparency.
