# Requirements Document

## Introduction

AI Cost Optimization is a multi-scope feature that addresses both operational cost reduction and cost visibility for RAMP's three stakeholder audiences: Max (technical owner), Tzvi (business partner), and the RAMP Operations Agent (programmatic consumer). The feature covers: GEO batch schedule smoothing to eliminate daily spend spikes, model migration for cost-heavy operations, unit economics calculation for pricing decisions, and a full AI Costs page redesign from flat tables to a hierarchical intelligence dashboard with a companion JSON API for the operations agent.

## Glossary

- **AI_Costs_Page**: The admin page at `/admin/ai-costs` showing LLM spend breakdowns by period, provider, operation, and client.
- **GEO_Batch**: A scheduled execution of GEO/AEO brand visibility monitoring queries against multiple AI providers (Perplexity, Claude, ChatGPT).
- **GEO_Prompt**: A single brand visibility query stored in `geo_prompts` table, belonging to a client.
- **Cost_Smoothing_Scheduler**: The new scheduling logic that distributes GEO prompts across all 7 days of the week instead of concentrating them on Tuesday and Friday.
- **Unit_Economics_Calculator**: A service that computes per-client, per-avatar, and per-draft cost including pipeline operations, GEO share, and infrastructure share.
- **RAMP_Agent_API**: A JSON endpoint exposing the same cost intelligence data available on the AI Costs page for programmatic consumption by the RAMP Operations Agent.
- **Budget_Health_Indicator**: A visual component showing spent vs limit per provider with projected month-end spend.
- **Anomaly_Detector**: Logic that identifies days where cost exceeds 3× the 7-day rolling average and attributes the cause.
- **Provider**: An external LLM service (Anthropic, Google Gemini, Perplexity, OpenAI) with its own billing and rate limits.
- **Pipeline_Stage**: A logical grouping of AI operations (Discovery, Scoring, Content, Hobby, Posts, GEO/AEO, Other).

## Requirements

### Requirement 1: GEO Batch Daily Rotation Schedule

**User Story:** As Max, I want GEO monitoring queries distributed evenly across all 7 days so that daily AI spend stays flat at $2-3/day instead of spiking to $10-17 on batch days.

#### Acceptance Criteria

1. WHEN the Cost_Smoothing_Scheduler runs daily, THE Cost_Smoothing_Scheduler SHALL select a subset of GEO_Prompts for execution such that each prompt executes at least once per 7-day rolling window.
2. THE Cost_Smoothing_Scheduler SHALL distribute prompts so that no single day executes more than `ceil(total_prompts / 7) + 1` prompts per client.
3. WHEN the total number of active GEO_Prompts for a client is N, THE Cost_Smoothing_Scheduler SHALL execute approximately `ceil(N / 7)` prompts per day (approximately 6 prompts per day for the current 40-prompt inventory).
4. THE Cost_Smoothing_Scheduler SHALL replace the existing Tue+Fri 09:30 `run_geo_monitoring_all_clients` beat schedule entry with a daily schedule entry.
5. WHEN a new GEO_Prompt is created mid-week, THE Cost_Smoothing_Scheduler SHALL include the new prompt in the next daily rotation without manual intervention.
6. THE Cost_Smoothing_Scheduler SHALL persist the last execution date per prompt so that prompt freshness (≤7 days since last run) is verifiable.
7. IF a daily GEO batch fails partially (provider timeout or error), THEN THE Cost_Smoothing_Scheduler SHALL prioritize unexecuted prompts from the failed batch in the next day's rotation.

### Requirement 2: Model Cost Migration for Comment Editing

**User Story:** As Max, I want comment editing moved from Claude Sonnet ($15/1M output) to Gemini 2.5 Flash ($0.60/1M output) so that editing costs drop by 25×.

#### Acceptance Criteria

1. WHEN the `llm_generation_model` DB setting governs editing operations, THE AI_Costs_Page SHALL reflect the new model assignment after the `editing` operation is remapped to a cheaper model DB setting.
2. THE system SHALL introduce a new DB setting `llm_editing_model` with default value `gemini/gemini-2.5-flash` to decouple editing model selection from generation model selection.
3. WHEN a comment editing operation is invoked, THE generation service SHALL read the model from `get_config("llm_editing_model")` instead of `get_config("llm_generation_model")`.
4. THE system SHALL add `gemini/gemini-2.5-flash` to the `MODEL_COSTS` dictionary in `ai.py` if not already present.
5. IF the editing model call fails, THEN THE system SHALL follow the standard `MODEL_FALLBACK_CHAIN` for the configured editing model.

### Requirement 3: Model Cost Migration for Persona Selection

**User Story:** As Max, I want persona selection moved from Claude Sonnet to Gemini 2.5 Flash so that avatar routing costs drop by 25×.

#### Acceptance Criteria

1. THE system SHALL introduce a new DB setting `llm_persona_model` with default value `gemini/gemini-2.5-flash` to decouple persona selection model from generation model.
2. WHEN a persona selection operation is invoked, THE generation service SHALL read the model from `get_config("llm_persona_model")` instead of `get_config("llm_generation_model")`.
3. THE system SHALL retain Claude Sonnet for comment generation (`generation` operation) to preserve quality for the quality-critical path.
4. IF the persona model call fails, THEN THE system SHALL follow the standard `MODEL_FALLBACK_CHAIN` for the configured persona model.

### Requirement 4: Evaluate Dropping Claude as GEO Provider

**User Story:** As Max, I want to evaluate whether removing Claude (Anthropic) as a GEO provider is viable given that Perplexity + Gemini provide sufficient visibility data and Claude GEO web search costs $0.08/query (the most expensive provider).

#### Acceptance Criteria

1. THE AI_Costs_Page SHALL display per-provider GEO cost breakdown (Perplexity, Claude, OpenAI, Gemini) so that the cost impact of each GEO provider is visible.
2. WHEN the `geo_provider_anthropic_enabled` system setting is set to `false`, THE GEO batch execution SHALL skip Claude queries without affecting other providers.
3. THE system SHALL log a `geo_provider_disabled` activity event when a GEO provider is toggled off, including provider name and reason.

### Requirement 5: Unit Economics Calculation

**User Story:** As Tzvi, I want to see the AI cost per client with 1, 2, or 3 avatars so that I can make informed pricing decisions.

#### Acceptance Criteria

1. THE Unit_Economics_Calculator SHALL compute monthly cost per client broken down into: pipeline operations (scoring + generation + editing + persona_select + hobby), GEO share (client's prompt count × cost per prompt per month), and infrastructure share (fixed monthly infra cost ÷ active client count).
2. THE Unit_Economics_Calculator SHALL produce cost calculations for three configurations: 1 avatar, 2 avatars, and 3 avatars per client.
3. THE Unit_Economics_Calculator SHALL use actual 30-day cost data from `ai_usage_log` grouped by client and operation to derive per-avatar pipeline cost.
4. WHEN the AI_Costs_Page is loaded, THE AI_Costs_Page SHALL display a Unit Economics table showing $/month per configuration (1/2/3 avatars), $/avatar/month, and $/draft cost.
5. THE Unit_Economics_Calculator SHALL update calculations daily using a rolling 30-day window.
6. THE Unit_Economics_Calculator SHALL include GEO monitoring cost allocated proportionally by client prompt count relative to total system GEO queries.

### Requirement 6: Budget Health Visualization

**User Story:** As Max or Tzvi, I want to see at a glance whether we are within budget for each AI provider so that I can respond before credits run out.

#### Acceptance Criteria

1. THE AI_Costs_Page SHALL display a Budget_Health_Indicator per provider (Anthropic, Google/Gemini, Perplexity, OpenAI) showing: amount spent this month, monthly limit, percentage used, and projected month-end spend.
2. WHEN projected month-end spend exceeds 90% of a provider's monthly limit, THE Budget_Health_Indicator SHALL display a danger state (red visual indicator).
3. WHEN projected month-end spend is between 70% and 90% of a provider's monthly limit, THE Budget_Health_Indicator SHALL display a warning state (amber visual indicator).
4. THE Budget_Health_Indicator SHALL compute projected month-end spend as: `(spend_so_far / days_elapsed_in_month) × days_in_month`.
5. THE system SHALL store per-provider monthly budget limits in `system_settings` (keys: `budget_anthropic`, `budget_gemini`, `budget_perplexity`, `budget_openai`).

### Requirement 7: Cost Breakdown by Pipeline Stage

**User Story:** As Max or Tzvi, I want to see where money goes across pipeline stages so that I can identify the most expensive operations.

#### Acceptance Criteria

1. THE AI_Costs_Page SHALL display a stacked bar chart showing cost distribution across pipeline stages (Discovery, Scoring, Content, Hobby, Posts, GEO/AEO, Onboarding, Trial Intelligence, Subreddit Intel, Other).
2. THE stacked bar chart SHALL be interactive: clicking a stage segment SHALL filter the detail view to show only that stage's operations.
3. THE AI_Costs_Page SHALL show per-provider burn rate as separate cards (Anthropic, Perplexity, Gemini) with: amount spent in selected period, daily average, and trend vs previous period.

### Requirement 8: Anomaly Detection and Highlighting

**User Story:** As Max, I want days with abnormal AI spend highlighted and attributed so that I can quickly identify runaway loops or batch processing issues.

#### Acceptance Criteria

1. THE Anomaly_Detector SHALL flag any day where total cost exceeds 3× the 7-day rolling average as an anomaly.
2. WHEN a day is flagged as an anomaly, THE AI_Costs_Page SHALL highlight that day in the cost timeline with a distinct visual indicator and display the top contributing operation and provider.
3. THE Anomaly_Detector SHALL compute the 7-day rolling average excluding the anomaly day itself to prevent self-inflation.
4. THE Anomaly_Detector SHALL store detected anomalies with: date, total cost, average cost, ratio, top operation, top provider.

### Requirement 9: Hierarchical Page Layout

**User Story:** As Max or Tzvi, I want the AI Costs page to answer "Are we within budget?" in under 5 seconds without scrolling past irrelevant detail.

#### Acceptance Criteria

1. THE AI_Costs_Page SHALL organize content in a hierarchical layout: Hero section (budget health + period cost + daily avg + projection) → Stage breakdown (stacked bar) → Provider detail (per-provider cards) → Drill-down sections (collapsed by default).
2. THE AI_Costs_Page SHALL collapse detailed tables (per-operation, per-client, per-day) into expandable `<details>` sections that default to closed state.
3. THE AI_Costs_Page SHALL retain existing date picker functionality (quick period buttons 7d/30d/90d/All + custom date range from→to).
4. THE AI_Costs_Page SHALL retain existing client filter functionality.
5. THE AI_Costs_Page SHALL display the Unit Economics table in the hero section or immediately below it.

### Requirement 10: RAMP Operations Agent JSON API

**User Story:** As the RAMP Operations Agent, I want a JSON endpoint with cost intelligence so that I can programmatically monitor budget health, detect anomalies, and recommend optimizations.

#### Acceptance Criteria

1. THE RAMP_Agent_API SHALL expose an authenticated JSON endpoint at `/api/admin/ai-costs` returning structured cost data.
2. THE RAMP_Agent_API response SHALL include the following fields: `total_month` (float), `daily_avg` (float), `projected_month` (float), `per_provider` (array of objects with `name`, `spent`, `limit`, `pct` fields), `anomalies` (array of anomaly objects with `date`, `cost`, `avg`, `ratio`, `top_operation`), `unit_economics` (object with `per_client_1av`, `per_client_2av`, `per_client_3av`, `per_avatar`, `per_draft` fields).
3. THE RAMP_Agent_API SHALL require `owner` or `partner` role authentication (same as the AI Costs page).
4. WHEN the RAMP Operations Agent reads the endpoint and detects `per_provider[].pct >= 70`, THE RAMP_Agent_API data SHALL be sufficient for the agent to trigger a budget warning alert.
5. WHEN the RAMP Operations Agent reads the endpoint and detects entries in the `anomalies` array for the current day, THE RAMP_Agent_API data SHALL be sufficient for the agent to trigger an anomaly investigation.
6. THE RAMP_Agent_API SHALL accept optional query parameters `period` (7d, 30d, 90d, all) and `date_from`/`date_to` for date range filtering, matching the page behavior.
