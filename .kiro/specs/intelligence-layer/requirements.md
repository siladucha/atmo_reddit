# Requirements Document

## Introduction

The RAMP Intelligence Layer is the analytical brain that transforms raw operational data into actionable insights. Rather than replacing existing data collection systems (ActivityEvent, KarmaSnapshot, PerformanceMetric, DecisionRecord, ScrapeLog, etc.), the Intelligence Layer aggregates, analyzes, and derives higher-order intelligence from data already flowing through the platform.

The system evolves RAMP from answering "What happened?" to answering "What matters?", "What changed?", "What should we do next?", and "What are we missing?"

This spec covers Phase 1 (event collection and metric aggregation), Phase 2 (anomaly detection, trend analysis, and recommendations), and the foundational architecture for Phase 3 (conversational agent and self-improving strategy).

## Glossary

- **Intelligence_Layer**: The analytical subsystem that aggregates existing platform data, detects anomalies, identifies trends, generates strategic observations, and produces actionable recommendations
- **Intelligence_Event**: A structured record capturing a system occurrence relevant to intelligence analysis (extends existing ActivityEvent with intelligence-specific metadata)
- **Anomaly**: A statistically significant deviation from established baseline behavior in any tracked metric
- **Baseline**: A rolling statistical model (mean, standard deviation, trend) computed from historical metric data for a specific dimension
- **Insight**: A higher-order observation derived from one or more anomalies, trends, or pattern correlations, with an explanation of why the observation matters
- **Recommendation**: An actionable suggestion produced by the Intelligence_Layer, including reasoning, confidence level, and expected impact
- **Outcome_Tracker**: The subsystem that links recommendations to user decisions and subsequent results, enabling the learning loop
- **Signal**: A single data point or metric change that contributes to anomaly detection or insight generation
- **Metric_Dimension**: A specific measurable attribute tracked over time (e.g., karma_per_comment, removal_rate, approval_latency, subreddit_engagement_rate)
- **Strategic_Observation**: A synthesized conclusion about platform performance that goes beyond individual metrics (e.g., "Subreddit X produces 3x better engagement than Y for client Z")
- **Avatar_Health_Index**: A composite score representing overall avatar operational health derived from multiple signals (karma trajectory, removal rate, posting frequency, subreddit compatibility)
- **Operator**: A platform user with owner or partner role who manages daily operations
- **Client_Manager**: A platform user with client_manager role who oversees client accounts
## Requirements

### Requirement 1: Intelligence Event Collection

**User Story:** As an operator, I want the platform to continuously collect and store structured intelligence events from all subsystems, so that the Intelligence Layer has comprehensive data for analysis.

#### Acceptance Criteria

1. WHEN a pipeline operation completes (scrape, score, generate, post), THE Intelligence_Layer SHALL record an Intelligence_Event with operation type, duration in milliseconds, input count, output count, and outcome status (one of: success, failure, partial)
2. WHEN a user makes a review decision (approve, reject, edit), THE Intelligence_Layer SHALL record the decision type, latency in seconds from generation to decision, and Levenshtein edit distance when decision type is edit
3. WHEN a karma outcome is observed (via KarmaSnapshot), THE Intelligence_Layer SHALL record the karma delta, time window (4h, 24h, 48h, or 7d), subreddit context, and engagement approach used
4. WHEN an avatar health state changes (freeze, unfreeze, phase change, shadowban detection), THE Intelligence_Layer SHALL record the state transition with trigger reason and up to 10 most recent activity events for that avatar within the preceding 24 hours as preceding signals
5. THE Intelligence_Layer SHALL store all Intelligence_Events in a dedicated table with client_id, avatar_id, event_category, event_type, payload JSONB (maximum 10 KB per event), and created_at timestamp indexed for queries by client_id, event_category, and created_at range
6. IF an Intelligence_Event fails to persist, THEN THE Intelligence_Layer SHALL write a warning to the application log containing the event_type, error description, and timestamp, and continue operation without affecting the source workflow
7. THE Intelligence_Layer SHALL retain Intelligence_Events for 90 days and archive events older than 90 days during the weekly archival task

### Requirement 2: Metric Baseline Computation

**User Story:** As an operator, I want the system to automatically compute and maintain statistical baselines for key metrics, so that anomalies can be detected against established norms.

#### Acceptance Criteria

1. THE Intelligence_Layer SHALL compute daily baselines for each Metric_Dimension per avatar, per client, and platform-wide
2. WHEN computing a baseline, THE Intelligence_Layer SHALL use a rolling window of 30 days with exponential decay weighting using a half-life of 7 days (data points 7 days old receive 50% weight, 14 days old receive 25% weight, and so on)
3. THE Intelligence_Layer SHALL track mean, standard deviation, trend direction (one of: "improving", "declining", or "stable"), and trend magnitude (percentage change over the window period) for each Metric_Dimension baseline
4. WHEN fewer than 7 data points exist for a Metric_Dimension within the 30-day window, THE Intelligence_Layer SHALL mark the baseline as "insufficient_data", skip anomaly detection for that dimension, and retain the previous valid baseline if one exists
5. THE Intelligence_Layer SHALL recompute baselines daily via a scheduled task (Celery Beat)
6. THE Intelligence_Layer SHALL store baselines in a dedicated table with entity_type, entity_id, metric_name, window_start, window_end, mean, stddev, trend_direction, trend_magnitude, sample_count, and computed_at
7. IF baseline computation fails for one or more entities, THEN THE Intelligence_Layer SHALL log the failure with entity identifiers and error context, preserve the most recent successfully computed baseline for those entities, and continue processing remaining entities without interruption

### Requirement 3: Anomaly Detection

**User Story:** As an operator, I want the system to automatically detect unusual behavior across avatars, subreddits, and clients, so that I can respond to problems before they escalate.

#### Acceptance Criteria

1. WHEN a new metric value deviates more than 2 standard deviations from the established baseline (computed from the most recent 14 daily data points for that entity and metric), THE Intelligence_Layer SHALL create an Anomaly record with severity "warning" at 2 sigma and "critical" at 3 sigma
2. THE Intelligence_Layer SHALL compute anomaly checks every 4 hours across these dimensions: karma_per_comment, removal_rate, approval_rate, engagement_velocity, posting_frequency, subreddit_response_rate, and review_latency
3. IF fewer than 7 daily data points exist for an entity-metric pair, THEN THE Intelligence_Layer SHALL skip anomaly detection for that pair and not generate an Anomaly record
4. WHEN an anomaly is detected, THE Intelligence_Layer SHALL generate a human-readable explanation of the anomaly including the metric name, observed value, expected range (mean plus or minus 2 standard deviations), and up to 3 contributing factors derived from correlated metric changes in the same entity
5. WHEN multiple anomalies occur for the same entity within a 24-hour window, THE Intelligence_Layer SHALL group related anomalies into an anomaly cluster with a combined severity equal to the highest individual severity in the cluster
6. IF an anomaly persists for more than 3 consecutive daily measurement periods, THEN THE Intelligence_Layer SHALL escalate the anomaly severity by one level (warning to critical), capped at critical as the maximum severity
7. WHEN an anomaly metric value returns within 1 standard deviation of the baseline mean for 2 consecutive measurement periods, THE Intelligence_Layer SHALL mark the anomaly as resolved by setting the resolved_at timestamp
8. THE Intelligence_Layer SHALL store anomalies with entity_type, entity_id, metric_name, observed_value, expected_mean, expected_stddev, deviation_sigma, severity, explanation, cluster_id, detected_at, and resolved_at
### Requirement 4: Trend Analysis

**User Story:** As an operator, I want the system to identify meaningful trends in platform performance, so that I can understand directional changes over time without manually reviewing raw data.

#### Acceptance Criteria

1. THE Intelligence_Layer SHALL compute 7-day and 30-day trend vectors for each Metric_Dimension at avatar, client, and platform levels, where a trend vector consists of direction (positive, negative, or neutral), magnitude (percentage change from window start to window end), and acceleration (difference between current magnitude and prior window magnitude)
2. WHEN a metric shows a consistent directional change (same direction for 5 or more consecutive daily data points), THE Intelligence_Layer SHALL classify the trend as "emerging" with a confidence score computed as (consecutive_same_direction_points / window_length) multiplied by 100, yielding a value between 0 and 100
3. WHEN a metric shows a directional change sustained for 14 or more consecutive days, THE Intelligence_Layer SHALL classify the trend as "established"
4. THE Intelligence_Layer SHALL produce trend summaries that include direction (improving if magnitude > +5 percent, declining if magnitude < -5 percent, or stable if magnitude is between -5 percent and +5 percent inclusive), magnitude (percentage change over window), acceleration (rate of change of rate), and comparison to peer entities (where peers are other entities of the same type within the same client scope, or all clients for platform-level trends)
5. WHEN a declining trend intersects a known risk threshold (defined in system settings per Metric_Dimension, such as karma approaching demotion threshold or removal_rate approaching 15 percent), THE Intelligence_Layer SHALL generate a predictive warning with estimated time to threshold breach computed via linear extrapolation from the current trend magnitude and direction
6. IF fewer than 7 daily data points exist for a Metric_Dimension within the trend window, THEN THE Intelligence_Layer SHALL skip trend computation for that dimension and mark it as "insufficient_data"
7. THE Intelligence_Layer SHALL store trend records with entity_type, entity_id, metric_name, window_days, direction, magnitude_percent, acceleration, classification (emerging, established, or none), confidence_score, and computed_at

### Requirement 5: Strategic Intelligence Observations

**User Story:** As an operator, I want the system to produce strategic observations about which subreddits, topics, personas, and engagement approaches perform best, so that I can make data-driven strategy decisions.

#### Acceptance Criteria

1. THE Intelligence_Layer SHALL produce weekly Strategic_Observations comparing subreddit performance for each client across four dimensions: karma yield (average karma per posted comment), removal rate (percentage of comments removed within 48 hours), engagement depth (average reply_count on avatar comments), and opportunity density (count of opportunities scored above 50 per subreddit in the past 7 days)
2. IF a subreddit has fewer than 5 posted comments for a client in the observation window, THEN THE Intelligence_Layer SHALL exclude that subreddit from comparative observations and mark it as "insufficient_data"
3. THE Intelligence_Layer SHALL identify which engagement approaches (reframe_drop, cynical_deconstruction, the_scar, contrarian, drive_by) produce the highest average karma and lowest removal rate per subreddit, ranking only approaches with 3 or more posted comments in the observation window
4. THE Intelligence_Layer SHALL identify which avatars perform best in which subreddits by ranking avatars on a composite score of average karma per comment and inverse removal rate, including only avatars with 3 or more posted comments per subreddit in the past 30 days
5. WHEN a competitor mention is detected via GEO/AEO monitoring or Discovery Engine, THE Intelligence_Layer SHALL produce an observation comparing client engagement metrics (average karma, removal rate) in the competitor-mentioned subreddit for the 7 days before and 7 days after competitor detection
6. THE Intelligence_Layer SHALL rank ICP pain points by a weighted composite of discussion volume (number of scored threads mentioning the pain point in the past 7 days, weight 40 percent), average opportunity score of related threads (weight 35 percent), and average karma on avatar comments addressing that pain point (weight 25 percent)
7. THE Intelligence_Layer SHALL store Strategic_Observations with observation_type, entity_scope JSONB, finding TEXT, supporting_data JSONB, confidence (0.0 to 1.0), actionability_score (0.0 to 1.0), and generated_at TIMESTAMPTZ

### Requirement 6: Recommendation Engine

**User Story:** As an operator, I want the system to provide actionable recommendations with reasoning, so that I can make informed decisions about strategy changes, avatar management, and resource allocation.

#### Acceptance Criteria

1. WHEN an anomaly exceeds a configured severity threshold, a trend persists for 3 or more consecutive data points, or a Strategic_Observation is generated by the analysis pipeline, THE Intelligence_Layer SHALL generate a Recommendation with action_type, target_entity, reasoning (50-2000 characters of prose containing the triggering data point, the inference, and the suggested action), confidence (0-100), expected_impact (a text description of the predicted outcome if the recommendation is followed, 20-500 characters), and urgency (low, medium, high, or critical)
2. THE Intelligence_Layer SHALL produce recommendations of these types: respond (engage with opportunity), ignore (skip signal), monitor (watch without acting), change_strategy (modify approach), expand_monitoring (add subreddit or keyword), reduce_activity (lower posting frequency), adjust_targeting (shift subreddit or topic focus)
3. WHEN generating a Recommendation, THE Intelligence_Layer SHALL include a reasoning field explaining the logic chain from data to suggestion, containing at minimum: the source data point or observation that triggered it, the inference drawn, and the specific action being suggested
4. THE Intelligence_Layer SHALL limit recommendations to a maximum of 10 unresolved (pending or deferred) per client at any time to prevent recommendation fatigue
5. IF the 10-recommendation cap is reached and a new recommendation with higher urgency is warranted, THEN THE Intelligence_Layer SHALL auto-expire the oldest pending recommendation with the lowest urgency to make room for the new one
6. WHEN a user acts on or dismisses a Recommendation, THE Intelligence_Layer SHALL record the decision (accepted, rejected, or deferred) with timestamp and optional operator notes (max 1000 characters)
7. IF a Recommendation remains in pending status for more than 7 days, THEN THE Intelligence_Layer SHALL set its status to expired and emit an activity event indicating the recommendation was not acted upon
8. THE Intelligence_Layer SHALL store Recommendations with recommendation_type, target_entity_type, target_entity_id, reasoning, confidence, expected_impact, urgency, status (pending, accepted, rejected, deferred, or expired), decided_at, decided_by, outcome_id, created_at, and expires_at
### Requirement 7: Learning Loop (Outcome Tracking)

**User Story:** As an operator, I want the system to learn from past recommendations and their outcomes, so that recommendation quality improves over time.

#### Acceptance Criteria

1. WHEN a Recommendation is accepted and the recommended action is executed, THE Intelligence_Layer SHALL begin tracking the outcome by creating an outcome record with observation_start set to the execution timestamp and observation_end set to observation_start plus 7 calendar days
2. WHEN the observation_end timestamp is reached, THE Intelligence_Layer SHALL compute an outcome_score as the average ratio of actual value to expected value across all metrics defined in expected_impact (karma delta, reply count, removal rate), expressed as a float between 0.0 and 2.0 where 1.0 means actual matched expected exactly
3. THE Intelligence_Layer SHALL classify an outcome as success (boolean true) IF outcome_score is greater than or equal to 0.8
4. THE Intelligence_Layer SHALL maintain a recommendation_accuracy metric per recommendation_type, computed as the count of outcomes where success equals true divided by the total count of computed outcomes for that type within a rolling 30-day window, requiring a minimum of 5 computed outcomes before reporting accuracy
5. WHEN recommendation_accuracy for a given type drops below 50 percent over a 30-day window with at least 5 computed outcomes, THE Intelligence_Layer SHALL flag that recommendation type for review and reduce its confidence multiplier by 20 percent, with a minimum floor of 20 percent (the multiplier SHALL NOT be reduced below 0.2)
6. IF actual metrics cannot be retrieved for a tracked outcome before observation_end plus 48 hours (due to content deletion or API failure), THEN THE Intelligence_Layer SHALL mark the outcome as inconclusive and exclude it from the recommendation_accuracy calculation
7. THE Intelligence_Layer SHALL store outcomes with recommendation_id, observation_start, observation_end, expected_metrics JSONB, actual_metrics JSONB, outcome_score (float, nullable), success (boolean, nullable), and computed_at (timestamptz, nullable)

### Requirement 8: Intelligence Dashboard

**User Story:** As an operator, I want a dedicated intelligence dashboard that surfaces anomalies, trends, strategic observations, and recommendations in a single view, so that I can quickly understand the current system intelligence state.

#### Acceptance Criteria

1. THE Intelligence_Layer SHALL provide an admin route at /admin/intelligence that displays active anomalies (status = open or acknowledged), current trends (generated within the last 7 days), strategic observations created within the last 14 days, and pending recommendations (status = pending) with a maximum of 25 items per section before pagination
2. WHEN an anomaly has critical severity, THE Intelligence_Layer SHALL display the anomaly in a visually distinct section positioned above all other dashboard sections, separated by severity level (critical, warning, info)
3. THE Intelligence_Layer SHALL support filtering intelligence items by client, avatar, subreddit, time range (date picker with start and end date), and severity level (critical, warning, info), and SHALL display an empty-state message when no items match the applied filters
4. THE Intelligence_Layer SHALL display recommendation accuracy metrics (acceptance rate, rejection rate, and deferral rate as percentages) and learning loop statistics (total corrections captured, active correction patterns count, and average confidence score) in a summary panel
5. WHEN a user clicks on a Recommendation, THE Intelligence_Layer SHALL display the full reasoning chain, supporting data, and related anomalies in an expanded detail view with accept, reject, and defer action buttons
6. WHEN an operator clicks accept, reject, or defer on a recommendation, THE Intelligence_Layer SHALL update the recommendation status to the selected state, record the operator ID and timestamp of the action, and return the operator to the dashboard with the updated recommendation state reflected
7. IF a recommendation action (accept, reject, or defer) fails due to a database or service error, THEN THE Intelligence_Layer SHALL preserve the recommendation in its prior state and display an error message indicating the action could not be completed
8. THE Intelligence_Layer SHALL load dashboard data via HTMX partials for lazy-loading, rendering each section (anomalies, trends, observations, recommendations) as an independent partial consistent with existing admin patterns

### Requirement 9: Avatar Health Index

**User Story:** As an operator, I want a composite health score for each avatar that synthesizes multiple signals into a single actionable metric, so that I can quickly identify avatars that need attention.

#### Acceptance Criteria

1. THE Intelligence_Layer SHALL compute an Avatar_Health_Index (0-100) once per day for each avatar that has at least one posted comment in the last 30 days, combining the following weighted sub-scores each normalized to 0-100: karma trajectory over the last 14 days (25 percent weight), removal rate over the last 30 days (25 percent weight), posting consistency relative to the avatar strategy cadence over the last 7 days (15 percent weight), average subreddit compatibility score across assigned subreddits (20 percent weight), and account age factor where accounts under 30 days score 0 and accounts over 180 days score 100 with linear interpolation between (15 percent weight)
2. WHEN the Avatar_Health_Index drops below 40, THE Intelligence_Layer SHALL generate a Recommendation specifying to reduce daily posting volume by 50 percent and listing the lowest-scoring sub-score component as the investigation target
3. WHEN the Avatar_Health_Index drops below 20, THE Intelligence_Layer SHALL generate a critical alert recommending immediate freeze of the avatar, and THE Intelligence_Layer SHALL NOT generate a duplicate alert if the avatar previous day score was also below 20
4. THE Intelligence_Layer SHALL display the Avatar_Health_Index value and a directional trend indicator (improving, stable, or declining based on 7-day moving average comparison) on the avatar detail page and the intelligence dashboard
5. THE Intelligence_Layer SHALL store daily Avatar_Health_Index values with per-component sub-scores and retain them for 180 days to support trend visualization
### Requirement 10: Intelligence API

**User Story:** As a developer, I want the Intelligence Layer to expose a structured internal API, so that other platform components can query intelligence data programmatically.

#### Acceptance Criteria

1. THE Intelligence_Layer SHALL provide a service-layer API (Python functions) for: get_anomalies(entity_type, entity_id, severity, time_range), get_trends(entity_type, entity_id, metric_name), get_recommendations(entity_type, entity_id, status), get_health_index(avatar_id), and get_strategic_observations(client_id, observation_type), each returning a list of typed dictionaries (or a single dictionary for get_health_index) suitable for JSON serialization
2. THE Intelligence_Layer SHALL provide FastAPI route endpoints under /api/intelligence/ for external consumption by the Client Portal and Decision Center, returning JSON responses within 2 seconds under normal load (up to 1000 stored intelligence records)
3. WHEN the Decision Center requests insights, THE Intelligence_Layer SHALL return pending recommendations with urgency "high" or "critical" and active anomalies with severity "warning" or "critical" that belong to the requesting user RBAC scope, ordered by creation time descending
4. THE Intelligence_Layer SHALL support pagination on all list endpoints with cursor-based pagination (limit plus after_id pattern) using a default limit of 20 and a maximum limit of 100, returning an empty list when no results match the query
5. IF an API request specifies an entity the requesting user lacks RBAC access to, THEN THE Intelligence_Layer SHALL return a 403 response without leaking entity existence
6. IF an API request specifies an entity_id or avatar_id that does not exist within the user authorized scope, THEN THE Intelligence_Layer SHALL return a 404 response with a generic error message indicating the resource was not found

### Requirement 11: Scheduled Intelligence Tasks

**User Story:** As an operator, I want intelligence computations to run automatically on a schedule without manual intervention, so that insights are always fresh.

#### Acceptance Criteria

1. THE Intelligence_Layer SHALL run baseline recomputation daily at 03:00 via Celery Beat
2. THE Intelligence_Layer SHALL run anomaly detection every 4 hours (aligned with existing karma snapshot schedule)
3. THE Intelligence_Layer SHALL run trend analysis daily at 03:30
4. THE Intelligence_Layer SHALL generate Strategic_Observations weekly on Monday at 04:00
5. THE Intelligence_Layer SHALL process the learning loop (close observation windows older than 7 days, compute outcome scores) daily at 04:00
6. IF a scheduled intelligence task raises an unhandled exception or exceeds a 10-minute execution timeout, THEN THE Intelligence_Layer SHALL emit an ActivityEvent with event_type "intelligence_task_failed" including the task name and error description in event metadata, and retry with exponential backoff (base 60 seconds, multiplier 2x, max 3 retries)
7. IF a scheduled intelligence task fails after exhausting all 3 retry attempts, THEN THE Intelligence_Layer SHALL emit an ActivityEvent with event_type "intelligence_task_exhausted" including the task name and final error, and shall not attempt further retries until the next scheduled run
8. WHILE a scheduled intelligence task is executing, THE Intelligence_Layer SHALL hold a Redis distributed lock for that task name to prevent overlapping concurrent executions of the same task

### Requirement 12: Data Retention and Archival

**User Story:** As an operator, I want intelligence data to be retained long enough for learning but archived to prevent database bloat, so that the system remains performant over time.

#### Acceptance Criteria

1. THE Intelligence_Layer SHALL retain raw Intelligence_Events for 90 days, then archive to the IntelligenceEventSummary table by computing daily aggregates (event count per category and mean of numeric payload values grouped by summary_date, client_id, and event_category) before purging the corresponding raw records
2. THE Intelligence_Layer SHALL retain Anomaly records for 180 days and SHALL automatically delete resolved anomalies (resolved_at IS NOT NULL) older than 90 days during the archival task
3. THE Intelligence_Layer SHALL retain baseline history for 365 days to support year-over-year comparison, deleting MetricBaseline records whose window_end is older than 365 days during the archival task
4. THE Intelligence_Layer SHALL retain Recommendation records and their associated RecommendationOutcome records indefinitely (for learning loop integrity)
5. WHEN archiving Intelligence_Events, THE Intelligence_Layer SHALL process deletions in batches of 1000 records per transaction to avoid lock contention and long-running transactions
6. THE Intelligence_Layer SHALL run archival as a weekly Celery Beat task on Sunday at 02:00
7. IF the archival task fails mid-execution, THEN THE Intelligence_Layer SHALL log the failure with the last successfully processed date, emit an ActivityEvent with event_type "intelligence_archival_failed", and retry with exponential backoff (max 3 retries) without re-deleting records for dates whose summaries were already persisted
