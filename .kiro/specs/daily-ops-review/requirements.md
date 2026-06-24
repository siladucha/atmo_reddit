# Requirements Document

## Introduction

The Daily Operations Review is a structured UI, workflow, and artifact layer that enables a 60-90 minute daily operational ritual for the RAMP platform. Every day, the Platform Owner (Max) and engineer sit down as "operators of the RAMP agent" and systematically answer four questions: What happened in the last 24 hours? Why did it happen? What does this mean for the next 24 hours? What should the system change itself, or what should we change manually?

The Daily Ops Review sits ON TOP of the existing Intelligence Layer (anomaly detection, trends, baselines), Operations Agent (monitoring, alerts, economics), and Ops Command Center (structured logging, billing, queue health). It consumes their data and provides a human-guided workflow interface with 6 structured sections, producing a persistent Daily Intelligence Report artifact stored in the database.

This is NOT the autonomous agent — it is the daily human-machine collaboration ritual that leverages agent outputs to make informed operational decisions.

## Glossary

- **Daily_Review**: A single instance of the 60-90 minute daily operational review session
- **Review_Session**: The runtime state of an in-progress Daily_Review, tracking which sections are completed and storing interim data
- **Intelligence_Report**: The structured output artifact produced by completing a Daily_Review, stored in the database for historical reference
- **Health_Snapshot**: A point-in-time collection of all system health signals gathered at the start of a Daily_Review (uptime, errors, failed jobs, queues, latency, cost, usage, email delivery, LLM failures, rate limits, manual interventions, incidents)
- **Change_Signal**: A detected change in system behavior over the past 24 hours, categorized by type (new error, frequency change, quality degradation, user behavior change, external API change, unexpected pattern)
- **Trend_Item**: An observed directional pattern classified as expected, unexpected, or weak signal
- **Root_Cause_Hypothesis**: A structured hypothesis linking an observation to possible causes with probability assessment and suggested action
- **Forecast_Entry**: A prediction about the next 24 hours for a specific domain, including confidence level and trigger conditions
- **Review_Decision**: A concrete action decision made during the review session (one of: continue, investigate, change), limited to maximum 3 per session
- **Platform_Owner**: Max — the technical co-founder who conducts daily reviews
- **Review_Presenter**: The system-generated presentation layer that aggregates data from Intelligence Layer, Operations Agent, and Ops Command Center into review-ready format
- **Signal_Collector**: The subsystem that gathers all operational signals from the past 24 hours into a structured Health_Snapshot

## Requirements

### Requirement 1: Review Session Lifecycle

**User Story:** As the Platform Owner, I want to start, progress through, and complete a structured daily review session, so that I follow a consistent operational ritual without skipping critical analysis steps.

#### Acceptance Criteria

1. WHEN the Platform Owner navigates to the Daily Review page, THE Review_Session SHALL display a session start control showing the current date and a summary of hours since the last completed review
2. WHEN the Platform Owner starts a new Daily_Review, THE Review_Session SHALL create a session record with status "in_progress", start timestamp, and initialize all 6 sections with status "pending"
3. THE Review_Session SHALL present the 6 sections in fixed order: System Health Snapshot, What Changed, Emerging Trends and Anomalies, Root Cause Hypotheses, Tomorrow Forecast, Decisions
4. WHEN a section is completed (Platform Owner marks it done), THE Review_Session SHALL update the section status to "completed" with a completion timestamp and advance the view to the next section
5. WHEN all 6 sections are marked completed, THE Review_Session SHALL set the session status to "completed", record the end timestamp, and generate the Intelligence_Report artifact
6. IF the Platform Owner navigates away from an in-progress session, THEN THE Review_Session SHALL preserve all entered data and allow resumption from the last completed section
7. THE Review_Session SHALL display elapsed time since session start and estimated remaining time based on target durations per section (10, 15, 20, 15, 15, 5 minutes)

### Requirement 2: System Health Snapshot Collection

**User Story:** As the Platform Owner, I want an automated collection of all operational signals from the past 24 hours presented in a single view, so that I can quickly assess system state without querying multiple dashboards.

#### Acceptance Criteria

1. WHEN the System Health Snapshot section is opened, THE Signal_Collector SHALL gather data from the past 24 hours across these categories: uptime percentage, error count by severity, failed Celery tasks, queue depths (scrape, score, generate, post, review), average task latency per pipeline stage, total AI cost, active user count, email delivery success rate, LLM API failure count, Reddit rate limit events, manual interventions performed, and unresolved incidents
2. THE Signal_Collector SHALL present each signal with its current value, 7-day average, and a delta indicator (better, worse, or stable compared to the 7-day average)
3. THE Signal_Collector SHALL highlight signals that deviate more than 1.5 standard deviations from their 7-day baseline with a visual "attention needed" indicator
4. THE Signal_Collector SHALL compute and display a single summary answer to the question "If nobody looked for 24 hours — would users notice a problem?" as one of: "No — system healthy", "Possibly — degraded signals detected", or "Yes — critical issues present", with supporting evidence
5. WHEN health data for a signal category is unavailable, THE Signal_Collector SHALL display "data unavailable" for that signal and exclude the signal from the overall health assessment calculation
6. THE Signal_Collector SHALL complete data collection within 10 seconds and display a loading state until collection finishes

### Requirement 3: Change Detection and Presentation

**User Story:** As the Platform Owner, I want the system to surface meaningful CHANGES (not just events) from the past 24 hours in a structured format, so that I understand what is different today versus yesterday.

#### Acceptance Criteria

1. WHEN the What Changed section is opened, THE Review_Presenter SHALL query the Intelligence Layer for all anomalies, new error types, frequency changes, and behavior deviations detected in the past 24 hours
2. THE Review_Presenter SHALL categorize each change into one of: new error type, frequency change of known error, quality degradation, user behavior change, external API behavior change, or unexpected pattern
3. THE Review_Presenter SHALL present each Change_Signal in a table with columns: Signal (description), Evidence (supporting data points), Impact (affected scope — avatar, client, or platform-wide), and Confidence (high, medium, or low based on data completeness)
4. THE Review_Presenter SHALL rank changes by impact severity (platform-wide first, then client-level, then avatar-level) and within the same level by confidence descending
5. WHEN no changes are detected, THE Review_Presenter SHALL explicitly display "No significant changes detected in the past 24 hours" rather than showing an empty section
6. THE Review_Presenter SHALL allow the Platform Owner to add manual observations as Change_Signal entries with free-text description and selected category

### Requirement 4: Emerging Trends and Anomalies Analysis

**User Story:** As the Platform Owner, I want trends split into expected, unexpected, and weak signals, so that I can distinguish between normal growth patterns and early warning signs.

#### Acceptance Criteria

1. WHEN the Emerging Trends section is opened, THE Review_Presenter SHALL query the Intelligence Layer for all active trends (7-day and 30-day vectors) and classify each as "expected" (matches forecast or known growth pattern), "unexpected" (no explanation in current context), or "weak signal" (not a problem yet but shows unusual directional change)
2. THE Review_Presenter SHALL display expected trends with their growth metric and whether they track above or below the projected trajectory
3. THE Review_Presenter SHALL display unexpected trends with the metric change, duration of the trend, and a prompt asking "What could explain this?"
4. THE Review_Presenter SHALL display weak signals with the metric, observation period, and a projected future state if the trend continues at the current rate (linear extrapolation over 7 days)
5. THE Review_Presenter SHALL allow the Platform Owner to reclassify any trend (move between expected, unexpected, and weak signal categories) and add a note explaining the reclassification
6. WHEN a weak signal has been flagged for 3 or more consecutive daily reviews without resolution, THE Review_Presenter SHALL visually escalate the signal with a "recurring" badge and the count of consecutive days

### Requirement 5: Root Cause Hypothesis Formation

**User Story:** As the Platform Owner, I want a structured format for forming hypotheses about observed issues without rushing to fix them, so that I make informed decisions based on systematic reasoning rather than gut reactions.

#### Acceptance Criteria

1. WHEN the Root Cause Hypotheses section is opened, THE Review_Presenter SHALL pre-populate the section with anomalies and unexpected changes from sections 2 and 3 that have no established explanation
2. FOR EACH unexplained observation, THE Review_Presenter SHALL provide a hypothesis template with fields: Observation (auto-filled from change/trend data), Possible Causes (free-text list), Probability per cause (high, medium, or low), and Recommended Action (one of: monitor, investigate further, immediate fix needed, or defer to next review)
3. THE Review_Presenter SHALL allow the Platform Owner to add new hypotheses not derived from automated detection (observations noticed outside the system)
4. WHEN a hypothesis has "immediate fix needed" as recommended action, THE Review_Session SHALL carry this forward to the Decisions section automatically
5. THE Review_Presenter SHALL display previously unresolved hypotheses from the last 3 daily reviews with their current status and any new evidence that supports or contradicts the hypothesis
6. THE Review_Presenter SHALL allow linking a hypothesis to one or more specific Change_Signals or Trend_Items from the current session as supporting evidence

### Requirement 6: Tomorrow Forecast Generation

**User Story:** As the Platform Owner, I want a structured prediction of what the next 24 hours will look like for each operational domain, so that I can prepare for potential issues proactively.

#### Acceptance Criteria

1. WHEN the Tomorrow Forecast section is opened, THE Review_Presenter SHALL display a forecast table with columns: Domain, Forecast (stable, risk, or growth), Confidence (percentage 0-100), and Trigger (condition that would change the forecast)
2. THE Review_Presenter SHALL pre-populate forecasts for these domains: GEO Monitoring, EPG Email Delivery, Prompt Generation Pipeline, Avatar Fleet Health, Reddit API Stability, LLM Cost Trajectory, and Queue Health
3. THE Review_Presenter SHALL compute initial forecast values using: current trend direction from the Intelligence Layer, active anomalies and their trajectory, scheduled events (deployments, batch tasks), and historical patterns for the same day-of-week
4. THE Review_Presenter SHALL allow the Platform Owner to override any forecast value and add a reason for the override
5. THE Review_Presenter SHALL highlight the key question "What could surprise us tomorrow morning?" and prompt the Platform Owner to document up to 3 specific surprises they want to watch for
6. WHEN a previous day's forecast can be compared against actual outcome, THE Review_Presenter SHALL display forecast accuracy (correct, partially correct, or incorrect) for each domain from yesterday's review

### Requirement 7: Decision Capture and Action Tracking

**User Story:** As the Platform Owner, I want to record maximum 3 concrete decisions per review session with clear action types, so that the review produces actionable output rather than just analysis.

#### Acceptance Criteria

1. WHEN the Decisions section is opened, THE Review_Session SHALL display hypotheses marked "immediate fix needed" and any system-generated recommendations from the Intelligence Layer as decision candidates
2. THE Review_Session SHALL enforce a maximum of 3 decisions per session, requiring the Platform Owner to prioritize when more than 3 candidates exist
3. FOR EACH decision, THE Review_Session SHALL capture: decision type (one of: continue, investigate, change), description (free text), owner (who is responsible), deadline (when it should be completed), and linked observations (references to signals, trends, or hypotheses from the current session)
4. WHEN a decision of type "change" is recorded, THE Review_Session SHALL prompt for the specific change to be made and whether it should be applied manually or queued as an agent action
5. THE Review_Session SHALL display unresolved decisions from previous reviews (last 7 days) with their current status
6. WHEN a decision from a previous review is resolved, THE Review_Session SHALL allow marking it as "done" with an outcome note

### Requirement 8: Intelligence Report Artifact Generation

**User Story:** As the Platform Owner, I want each completed review to produce a structured, queryable Intelligence Report stored in the database, so that I can track operational patterns over weeks and months.

#### Acceptance Criteria

1. WHEN a Daily_Review session is completed (all 6 sections marked done), THE Review_Session SHALL generate an Intelligence_Report record with: date, system_state summary (healthy, degraded, or critical), top 3 events (most impactful changes), top 3 anomalies, top risks for next 24 hours, forecast table, decisions made, and overall confidence (aggregated from forecast confidence values)
2. THE Intelligence_Report SHALL store all structured data as JSONB fields enabling querying by any dimension (date range, system state, risk level, decision type)
3. THE Intelligence_Report SHALL include a human-readable narrative summary (generated from the structured data) of no more than 500 words describing the operational state in prose
4. THE Intelligence_Report SHALL link to the specific anomalies, trends, and recommendations from the Intelligence Layer that were referenced during the review
5. THE Intelligence_Report SHALL be immutable after generation — edits create amendment records linked to the original report rather than modifying the original
6. THE Intelligence_Report SHALL be accessible from the admin dashboard with a historical list view showing date, system state, decision count, and forecast accuracy (compared to the following day's actual state)

### Requirement 9: Data Aggregation from Existing Systems

**User Story:** As the Platform Owner, I want the Daily Review to automatically pull data from the Intelligence Layer, Operations Agent, and Ops Command Center without manual data entry, so that the review focuses on analysis rather than data collection.

#### Acceptance Criteria

1. THE Signal_Collector SHALL query the Intelligence Layer for: active anomalies with severity and explanation, trend vectors at platform and client levels, and pending recommendations with confidence scores
2. THE Signal_Collector SHALL query the Operations Agent data for: Health_Score with component breakdown, active alerts by time horizon (immediate, short-term, plannable, trend), and autonomous actions taken in the past 24 hours
3. THE Signal_Collector SHALL query the Ops Command Center for: structured log summary (error count by service), queue health metrics (DLQ depth, stuck tasks, failure rate), and pipeline stage metrics (throughput, latency, success rate per stage)
4. THE Signal_Collector SHALL query existing models for: ActivityEvent entries in the past 24 hours grouped by event_type, KarmaSnapshot outcomes for comments posted in the past 48 hours, PerformanceMetric daily aggregates for all active avatars, AIUsageLog cost totals grouped by operation type, and PostingEvent success and failure counts
5. IF a data source is unavailable (Intelligence Layer table empty, Agent metrics not computed), THEN THE Signal_Collector SHALL proceed with available data, mark the unavailable source, and include a "data gaps" note in the Health Snapshot
6. THE Signal_Collector SHALL cache aggregated data for the duration of the review session to ensure consistency across all 6 sections

### Requirement 10: Review UI and Navigation

**User Story:** As the Platform Owner, I want a dedicated admin page for the Daily Review with clear section navigation, progress tracking, and the ability to work through sections at my own pace, so that the ritual is efficient and does not feel bureaucratic.

#### Acceptance Criteria

1. THE Review_Session SHALL render on a dedicated page at `/admin/daily-review` accessible only to users with "owner" or "partner" role
2. THE Review_Session SHALL display a left sidebar showing all 6 sections with completion status (pending, in-progress, completed) and time spent per section
3. WHEN a section is selected, THE Review_Session SHALL render the section content in the main area using HTMX partials for lazy-loading data-heavy sections
4. THE Review_Session SHALL auto-save all Platform Owner inputs (notes, hypothesis text, decision descriptions, forecast overrides) within 2 seconds of the last keystroke without requiring manual save actions
5. THE Review_Session SHALL provide a "Quick Review" mode that collapses sections with no detected anomalies or changes to their summary line, allowing the Platform Owner to skip healthy sections and focus on sections with findings
6. THE Review_Session SHALL display the historical list of completed Intelligence Reports on the same page with date, duration, system state, and decision count, accessible via a "History" tab

### Requirement 11: Forecast Accuracy Tracking

**User Story:** As the Platform Owner, I want to see how accurate my previous forecasts were compared to actual outcomes, so that I can calibrate my prediction skills and improve the reliability of daily forecasts over time.

#### Acceptance Criteria

1. WHEN a new Daily_Review is started, THE Review_Presenter SHALL automatically evaluate the previous day's forecast against actual outcomes by comparing each domain's predicted state (stable, risk, growth) to the corresponding metrics from the past 24 hours
2. THE Review_Presenter SHALL classify each forecast as: "correct" (predicted state matches actual), "partially correct" (predicted state direction is right but magnitude differs), or "incorrect" (actual state contradicts prediction)
3. THE Review_Presenter SHALL compute a rolling 7-day and 30-day forecast accuracy percentage (correct forecasts divided by total forecasts) and display the score on the review start screen
4. WHEN a forecast is classified as "incorrect", THE Review_Presenter SHALL display the predicted value, actual value, and the trigger condition that materialized (or failed to materialize)
5. THE Review_Presenter SHALL track forecast accuracy per domain over 30 days to identify which domains the Platform Owner consistently over-estimates or under-estimates risk for

### Requirement 12: Decision Follow-Up and Accountability

**User Story:** As the Platform Owner, I want unresolved decisions from previous reviews to surface automatically in subsequent reviews, so that no decision falls through the cracks and accountability is maintained.

#### Acceptance Criteria

1. WHEN a new Daily_Review session is started, THE Review_Session SHALL display a count of unresolved decisions from the last 7 days as a badge on the Decisions section
2. WHEN the Decisions section is opened, THE Review_Session SHALL display all unresolved decisions from the past 7 days with: original date, decision type, description, owner, deadline, and days overdue (if past deadline)
3. WHEN a decision deadline has passed without resolution, THE Review_Session SHALL highlight the overdue decision with a visual indicator and include the decision owner in the daily review notification
4. THE Review_Session SHALL allow updating decision status to one of: "done" (with outcome note), "deferred" (with new deadline and reason), or "cancelled" (with cancellation reason)
5. THE Review_Session SHALL maintain a decision resolution rate metric (decisions resolved within deadline divided by total decisions) visible on the review history page
6. IF a decision has been deferred more than twice, THEN THE Review_Session SHALL flag the decision with a "blocked" indicator and prompt for identification of the blocking dependency

### Requirement 13: Agent Cost Governance

**User Story:** As the Platform Owner, I want all AI/LLM costs incurred by the RAMP Operations Agent (including Daily Review, hypothesis generation, forecasts, and anomaly analysis) to be tracked, budgeted, and hard-capped at $1/day maximum, so that the agent never becomes a runaway cost center.

#### Acceptance Criteria

1. THE system SHALL track every LLM API call made by the Operations Agent and Daily Review subsystems separately from client pipeline costs, tagged with category "agent_ops" in the AIUsageLog
2. THE system SHALL enforce a hard daily budget ceiling of $1.00 (configurable via system setting `agent_daily_budget_usd`, default "1.00") for all agent-initiated LLM calls, where the budget resets at 00:00 Asia/Jerusalem daily
3. WHEN cumulative agent LLM spend for the current day reaches 80% of the daily budget ($0.80 at default), THE system SHALL emit a warning visible on the Daily Review UI indicating remaining budget and estimated calls available
4. WHEN cumulative agent LLM spend for the current day reaches 100% of the daily budget, THE system SHALL block all further agent-initiated LLM calls for the remainder of the day and fall back to rule-based analysis (pre-computed baselines, SQL-only anomaly detection, template-based summaries) without LLM enhancement
5. THE system SHALL select the cheapest adequate model for each agent task: Gemini Flash for data summarization and signal classification, Claude Haiku for hypothesis generation and narrative summaries — never using Claude Sonnet or GPT-4 class models for agent operations
6. THE system SHALL batch multiple analysis requests into single LLM calls where possible (e.g., all 7 domain forecasts in one prompt rather than 7 separate calls, all change signals classified in one call rather than per-signal)
7. THE system SHALL cache LLM-generated analysis results for the duration of the review session — if the same data is viewed multiple times, no additional LLM calls are made
8. THE system SHALL display on the Daily Review UI: today's agent spend (accumulated), remaining budget, cost breakdown by operation (health summary, change analysis, trend classification, hypothesis generation, forecast, narrative report), and a 7-day spend chart
9. THE system SHALL log each agent LLM call with: timestamp, model used, input_tokens, output_tokens, cost_usd (4 decimal places), operation_type, and session_id (if within a Daily Review)
10. THE system SHALL produce a weekly agent cost summary showing: average daily spend, peak day spend, budget utilization percentage, cost per review session, and model distribution (percentage of calls per model)
11. IF the daily budget is exhausted before the Daily Review session is completed, THEN THE Review_Session SHALL continue in "offline mode" using only pre-aggregated SQL metrics, cached baselines, and template-based formatting — clearly indicating to the Platform Owner which sections lack LLM-enhanced analysis
12. THE system SHALL design all agent operations to target a steady-state cost of $0.30-0.50/day under normal conditions (10 clients, no incidents), reserving the remaining budget headroom for spike days requiring additional analysis
