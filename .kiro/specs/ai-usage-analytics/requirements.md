# Requirements Document

## Introduction

Enhance the existing `/admin/ai-costs` page into a full AI Usage Analytics dashboard. The current page shows basic summary cards (total cost, calls, tokens) and static tables grouped by client, operation, and model — but lacks time-based trends, filtering, performance metrics, and optimization insights. This feature adds time-series breakdowns (daily/weekly/monthly), interactive date-range filtering, per-model latency and efficiency metrics, budget progress visualization, and model configuration visibility — all using the existing `ai_usage_log` table data with no schema changes required.

## Glossary

- **Analytics_Dashboard**: The enhanced admin page at `/admin/ai-costs` providing time-series cost analysis, filtering, and optimization insights.
- **Time_Series_Panel**: A section displaying cost and call volume data aggregated by day, week, or month with visual bar indicators.
- **Date_Range_Filter**: An HTMX-powered filter control allowing the operator to select a predefined time range (today, 7 days, 30 days, 90 days, all time) that applies to all dashboard sections.
- **Budget_Progress_Bar**: A visual indicator showing current month spending relative to the configured monthly budget with color-coded thresholds.
- **Model_Config_Panel**: A read-only section displaying the currently configured AI models, their roles (scoring vs generation), and per-token pricing.
- **Efficiency_Metrics**: Computed statistics including average cost per call, average latency per model, and cost per output token by operation.
- **Cost_Trend_Bar**: A horizontal CSS bar representing a daily or periodic cost value relative to the maximum value in the displayed range, enabling visual comparison without JavaScript charting libraries.

## Requirements

### Requirement 1: Date Range Filtering

**User Story:** As the operator, I want to filter all AI usage data by time period, so that I can analyze costs for specific windows and compare periods.

#### Acceptance Criteria

1. THE Analytics_Dashboard SHALL display a Date_Range_Filter with predefined options: Today, Last 7 Days, Last 30 Days, Last 90 Days, and All Time.
2. WHEN the operator selects a Date_Range_Filter option, THE Analytics_Dashboard SHALL reload all data sections (summary cards, tables, time series) filtered to the selected range via HTMX partial swap.
3. THE Analytics_Dashboard SHALL default the Date_Range_Filter to "Last 30 Days" on initial page load.
4. THE Date_Range_Filter SHALL preserve the selected option visually (active state styling) after selection.

### Requirement 2: Time-Series Cost Breakdown

**User Story:** As the operator, I want to see costs broken down by day and by month, so that I can identify spending trends and anomalies over time.

#### Acceptance Criteria

1. THE Time_Series_Panel SHALL display a daily cost breakdown table showing date, total cost, call count, and a Cost_Trend_Bar for each day within the selected date range.
2. THE Cost_Trend_Bar SHALL render as a horizontal CSS bar whose width is proportional to that day's cost relative to the maximum daily cost in the displayed range.
3. WHEN the selected date range exceeds 30 days, THE Time_Series_Panel SHALL additionally display a monthly aggregation table showing month, total cost, call count, and Cost_Trend_Bar.
4. THE Time_Series_Panel SHALL sort entries in reverse chronological order (most recent first).
5. THE Time_Series_Panel SHALL display a row-level percentage showing each day's cost as a percentage of the total cost in the selected range.

### Requirement 3: Enhanced Summary Cards with Efficiency Metrics

**User Story:** As the operator, I want to see average cost per call and average latency alongside totals, so that I can understand per-unit economics and model performance.

#### Acceptance Criteria

1. THE Analytics_Dashboard SHALL display summary cards for: Total Cost, Total Calls, Average Cost per Call, and Average Latency (ms) — all scoped to the selected date range.
2. THE Average Cost per Call card SHALL compute total_cost divided by total_calls for the selected period.
3. THE Average Latency card SHALL compute the mean of duration_ms across all records in the selected period.
4. THE Analytics_Dashboard SHALL display a secondary row of summary cards showing: Input Tokens (total), Output Tokens (total), and Cost per 1K Output Tokens.
5. THE Cost per 1K Output Tokens card SHALL compute (total_cost / total_output_tokens) * 1000 for the selected period.

### Requirement 4: Budget Progress Visualization

**User Story:** As the operator, I want to see a visual progress bar of current month spending against the budget, so that I can immediately gauge budget health.

#### Acceptance Criteria

1. THE Budget_Progress_Bar SHALL display current month total cost, the configured monthly budget amount, and a percentage value.
2. THE Budget_Progress_Bar SHALL render as a horizontal bar filled proportionally to the percentage of budget consumed.
3. WHEN budget consumption is below 60%, THE Budget_Progress_Bar SHALL use a green color.
4. WHEN budget consumption is between 60% and 80%, THE Budget_Progress_Bar SHALL use an amber color.
5. WHEN budget consumption exceeds 80%, THE Budget_Progress_Bar SHALL use a red color.
6. THE Budget_Progress_Bar SHALL display the remaining budget amount in dollars.

### Requirement 5: Cost by Client with Time Filtering

**User Story:** As the operator, I want to see per-client cost breakdowns filtered by time period, so that I can identify which clients drive the most AI spending in a given window.

#### Acceptance Criteria

1. THE Analytics_Dashboard SHALL display a "Cost by Client" table filtered by the selected date range showing: client name, call count, total cost, average cost per call, and percentage of total cost.
2. THE "Cost by Client" table SHALL sort clients by total cost descending.
3. THE "Cost by Client" table SHALL include a Cost_Trend_Bar for each client showing relative cost proportion.
4. IF no usage data exists for a client in the selected range, THEN THE table SHALL omit that client from the results.

### Requirement 6: Cost by Operation with Time Filtering

**User Story:** As the operator, I want to see per-operation cost breakdowns filtered by time period, so that I can identify which pipeline phases (scoring, generation, editing) are most expensive and where to optimize.

#### Acceptance Criteria

1. THE Analytics_Dashboard SHALL display a "Cost by Operation" table filtered by the selected date range showing: operation name, call count, total cost, average cost per call, average latency (ms), and percentage of total cost.
2. THE "Cost by Operation" table SHALL sort operations by total cost descending.
3. THE "Cost by Operation" table SHALL include a Cost_Trend_Bar for each operation showing relative cost proportion.
4. THE "Cost by Operation" table SHALL display average input tokens and average output tokens per call for each operation.

### Requirement 7: Cost by Model with Performance Metrics

**User Story:** As the operator, I want to see per-model breakdowns including latency and efficiency, so that I can evaluate whether the current model assignments are cost-effective.

#### Acceptance Criteria

1. THE Analytics_Dashboard SHALL display a "Cost by Model" table filtered by the selected date range showing: model name, call count, total cost, average cost per call, average latency (ms), and average output tokens per call.
2. THE "Cost by Model" table SHALL sort models by total cost descending.
3. THE "Cost by Model" table SHALL display the cost per 1K output tokens for each model.
4. THE "Cost by Model" table SHALL include a Cost_Trend_Bar for each model showing relative cost proportion.

### Requirement 8: Model Configuration Panel

**User Story:** As the operator, I want to see which AI models are currently configured for each pipeline role and their pricing, so that I can understand the cost structure without checking config files.

#### Acceptance Criteria

1. THE Model_Config_Panel SHALL display the currently configured scoring model (from system setting `llm_scoring_model`) with its per-token pricing (input and output cost per 1M tokens).
2. THE Model_Config_Panel SHALL display the currently configured generation model (from system setting `llm_generation_model`) with its per-token pricing (input and output cost per 1M tokens).
3. THE Model_Config_Panel SHALL display the model role assignment: which operations use the scoring model and which use the generation model.
4. THE Model_Config_Panel SHALL source pricing data from the MODEL_COSTS dictionary defined in `app/services/ai.py`.

### Requirement 9: Daily Cost Comparison Indicator

**User Story:** As the operator, I want to see whether today's spending is higher or lower than the recent average, so that I can spot unusual activity quickly.

#### Acceptance Criteria

1. THE Analytics_Dashboard SHALL display a "Today vs Average" indicator showing today's total cost compared to the average daily cost over the last 30 days.
2. WHEN today's cost exceeds the 30-day daily average by more than 50%, THE indicator SHALL display an upward arrow with a red accent.
3. WHEN today's cost is below the 30-day daily average by more than 25%, THE indicator SHALL display a downward arrow with a green accent.
4. WHEN today's cost is within 25% above or 25% below the 30-day daily average, THE indicator SHALL display a neutral horizontal arrow.

### Requirement 10: Page Layout and HTMX Integration

**User Story:** As the operator, I want the analytics dashboard to load quickly and update sections independently, so that I can interact with filters without full page reloads.

#### Acceptance Criteria

1. THE Analytics_Dashboard SHALL use the existing admin_base.html dark theme layout with active_nav set to "ai-costs".
2. THE Analytics_Dashboard SHALL use HTMX hx-get requests with hx-target to swap individual sections when the Date_Range_Filter changes.
3. THE Analytics_Dashboard SHALL organize content in this order: Budget Progress Bar → Date Range Filter → Summary Cards → Today vs Average → Time Series Panel → Cost by Client → Cost by Operation → Cost by Model → Model Config Panel.
4. THE Analytics_Dashboard SHALL use Tailwind CSS utility classes consistent with the existing admin panel styling (bg-dark-steel, border-slate-700, text-gray-300 palette).
5. THE Analytics_Dashboard SHALL render Cost_Trend_Bar elements using pure CSS (Tailwind width utilities or inline style with percentage width) without requiring JavaScript charting libraries.
