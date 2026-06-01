# Requirements Document

## Introduction

Quality Sentinel is a unified quality control subsystem for the Reddit Marketing SaaS platform. The platform makes decisions at every pipeline stage (strategy → scoring → EPG selection → generation → posting), but currently has no systematic way to track whether those decisions produce good outcomes or to learn from results. Quality Sentinel closes this feedback loop by tracking post-posting outcomes, computing effectiveness scores for decision combinations, building multi-level trends, alerting operators on degradation, and auto-adapting system behavior based on accumulated data.

The system is delivered in three phases:
- **Phase 1** (before 10 clients): Outcome Tracking + basic trends + alerts
- **Phase 2** (10 clients): Effectiveness scores + auto-adaptation
- **Phase 3** (50 clients): AI root-cause analysis + cross-client learning

This requirements document covers Phase 1 and Phase 2 (the core system). Phase 3 is deferred.

## Glossary

- **Outcome_Tracker**: The subsystem responsible for collecting post-posting karma snapshots, detecting comment removals, and detecting reply engagement
- **Learning_Engine**: The subsystem that computes effectiveness scores for decision combinations and feeds them back into pipeline nodes
- **Trend_Calculator**: The subsystem that computes KPI trends via linear regression at all observation levels
- **Alert_Engine**: The subsystem that evaluates composite risk scores and emits operator alerts when thresholds are breached
- **Dashboard_Renderer**: The admin UI component that displays quality metrics, trends, risk scores, and drill-down views
- **Outcome_Record**: A data record linking a posted comment to its karma snapshots, removal status, and reply count
- **Effectiveness_Score**: A normalized score (0.0–1.0) representing how well a specific decision combination performs
- **Combo_Key**: A unique identifier for a decision combination (e.g., approach×subreddit, avatar×subreddit, timing_bucket×subreddit, strategy_pattern×client)
- **Observation_Level**: One of four aggregation scopes: system, client, subreddit, avatar
- **KPI_Snapshot**: A point-in-time measurement of a key performance indicator at a specific observation level
- **Composite_Risk_Score**: A score from 0 to 100 representing overall health risk for an entity (avatar, client, or system)
- **Timing_Bucket**: A discretized time-of-day range (e.g., 08:00–10:00, 10:00–12:00) used for timing effectiveness analysis
- **Attribution**: The process of mapping an outcome back to all pipeline decisions that contributed to it
- **Learning_Channel**: One of 6 feedback signal types: text edits, rejections, karma outcomes, removals, strategy changes, EPG reassignments
- **Correlation_Alert**: An alert triggered when degradation patterns appear across multiple entities simultaneously

## Requirements

### Requirement 1: Karma Snapshot Collection

**User Story:** As a platform operator, I want the system to automatically check comment karma at defined intervals after posting, so that I can measure the effectiveness of each comment over time.

#### Acceptance Criteria

1. WHEN a CommentDraft transitions to status "posted", THE Outcome_Tracker SHALL schedule karma checks at 4 hours, 24 hours, and 48 hours after the posting timestamp
2. WHEN a scheduled karma check fires, THE Outcome_Tracker SHALL retrieve the current karma score of the posted comment via the Reddit API and store it as a karma snapshot linked to the Outcome_Record
3. IF a karma check fails due to Reddit API error or rate limiting, THEN THE Outcome_Tracker SHALL retry with exponential backoff (max 3 retries) and skip the snapshot if all retries fail
4. WHILE processing karma checks in batch, THE Outcome_Tracker SHALL process comments in priority order: 4h snapshots before 24h snapshots before 48h snapshots
5. THE Outcome_Tracker SHALL batch karma checks into groups of 50 per Celery task execution
6. WHILE the Reddit API rate limit is approached (>50 requests/minute), THE Outcome_Tracker SHALL pause processing and resume in the next cycle

### Requirement 2: Comment Removal Detection

**User Story:** As a platform operator, I want the system to detect when posted comments are removed by moderators, so that I can identify problematic subreddits and approaches.

#### Acceptance Criteria

1. WHEN a scheduled karma check executes, THE Outcome_Tracker SHALL verify whether the comment is still publicly visible on Reddit
2. WHEN a comment is detected as no longer visible, THE Outcome_Tracker SHALL mark the Outcome_Record with removal_detected=true and record the detection timestamp
3. WHEN a removal is detected, THE Outcome_Tracker SHALL record which subreddit and avatar were involved for attribution purposes
4. THE Outcome_Tracker SHALL distinguish between author-deleted comments and moderator-removed comments where the Reddit API provides sufficient information

### Requirement 3: Reply Detection

**User Story:** As a platform operator, I want the system to detect when posted comments receive replies, so that I can measure engagement quality beyond karma.

#### Acceptance Criteria

1. WHEN a 24h or 48h karma check executes, THE Outcome_Tracker SHALL count the number of direct replies to the posted comment
2. WHEN replies are detected, THE Outcome_Tracker SHALL store the reply count in the Outcome_Record
3. THE Outcome_Tracker SHALL record whether any reply is from the original thread author (OP engagement signal)

### Requirement 4: Outcome Record Storage

**User Story:** As a platform operator, I want all outcome data stored in a structured format linked to the original draft, so that I can query and analyze decision effectiveness.

#### Acceptance Criteria

1. THE Outcome_Tracker SHALL create one Outcome_Record per posted CommentDraft, linked via foreign key to the draft
2. THE Outcome_Record SHALL store: draft_id, avatar_id, client_id, subreddit_id, posted_at, karma_4h, karma_24h, karma_48h, removal_detected, removal_detected_at, reply_count, has_op_reply, comment_approach, strategy_pattern, timing_bucket, and thread_score_at_selection
3. THE Outcome_Tracker SHALL retain raw Outcome_Records for 90 days, after which records older than 90 days SHALL be deleted by a scheduled cleanup task
4. WHEN an Outcome_Record is deleted during retention cleanup, THE Outcome_Tracker SHALL ensure the record has already been aggregated into effectiveness scores before deletion

### Requirement 5: Effectiveness Score Computation

**User Story:** As a platform operator, I want the system to compute effectiveness scores for every decision combination, so that I can see which approaches work best in which contexts.

#### Acceptance Criteria

1. THE Learning_Engine SHALL compute effectiveness scores for the following combo keys: approach×subreddit, avatar×subreddit, timing_bucket×subreddit, and strategy_pattern×client
2. WHEN a new Outcome_Record receives its 48h karma snapshot (or all available snapshots), THE Learning_Engine SHALL recompute the effectiveness score for all combo keys associated with that outcome
3. THE Learning_Engine SHALL compute effectiveness scores as a normalized value between 0.0 and 1.0, using a formula that weights: karma_48h (primary), removal penalty (strong negative), and reply bonus (moderate positive)
4. THE Learning_Engine SHALL require a minimum of 5 outcomes (n ≥ 5) for a combo key before publishing an effectiveness score
5. WHILE a combo key has fewer than 5 outcomes, THE Learning_Engine SHALL fall back to the parent-level score (e.g., approach across all subreddits instead of approach×specific_subreddit)
6. THE Learning_Engine SHALL update effectiveness scores in-place (upsert), maintaining approximately 12,500 score records at 10 clients

### Requirement 6: Decision Attribution

**User Story:** As a platform operator, I want each outcome attributed back to all pipeline decisions that contributed to it, so that I can identify which pipeline nodes produce good or bad results.

#### Acceptance Criteria

1. WHEN an Outcome_Record is created, THE Learning_Engine SHALL extract and store attribution data: which strategy was active, which scoring decision selected the thread, which EPG slot was used, which comment approach was applied, and which timing bucket the post fell into
2. THE Learning_Engine SHALL compute per-node decision quality metrics: strategy quality (avg karma trend), scoring precision (% positive outcomes among "engage" threads), EPG quality (karma of selected vs. alternative threads), generation quality (edit rate + rejection rate + karma), and posting success (failure rate + timing effectiveness)
3. WHEN computing decision quality for a pipeline node, THE Learning_Engine SHALL use a rolling window of the most recent 30 days of outcomes

### Requirement 7: Auto-Adaptation of System Behavior

**User Story:** As a platform operator, I want the system to automatically prefer high-effectiveness decision combinations in future pipeline runs, so that quality improves over time without manual intervention.

#### Acceptance Criteria

1. WHEN the EPG service selects threads for an avatar, THE Learning_Engine SHALL provide effectiveness weights that bias selection toward subreddit×approach combinations with scores above 0.6
2. WHEN the diversity engine selects a comment approach, THE Learning_Engine SHALL provide effectiveness weights that reduce probability of approaches with scores below 0.3 for the target subreddit
3. WHEN the timing engine assigns a posting slot, THE Learning_Engine SHALL provide effectiveness weights that bias toward timing buckets with scores above 0.5 for the target subreddit
4. IF effectiveness data is unavailable for a combo key (n < 5), THEN THE Learning_Engine SHALL apply no bias (equal weighting) for that decision
5. THE Learning_Engine SHALL expose an auto_adaptation_enabled system setting (default: false) that gates all adaptation behavior

### Requirement 8: KPI Snapshot Collection

**User Story:** As a platform operator, I want the system to collect KPI snapshots at all four observation levels, so that I can track trends over time.

#### Acceptance Criteria

1. THE Trend_Calculator SHALL collect daily KPI snapshots at system, client, subreddit, and avatar observation levels
2. THE Trend_Calculator SHALL compute the following KPIs per snapshot: avg_karma, removal_rate, reply_rate, positive_outcome_rate (karma > 0), and volume (number of posts)
3. WHEN collecting daily snapshots, THE Trend_Calculator SHALL execute during off-peak hours (03:00 local time) using a read-only database connection
4. THE Trend_Calculator SHALL retain daily KPI snapshots for 1 year, after which they SHALL be aggregated into monthly summaries and raw daily records deleted
5. THE Trend_Calculator SHALL retain monthly aggregate snapshots indefinitely

### Requirement 9: Trend Calculation

**User Story:** As a platform operator, I want the system to calculate 7-day and 30-day trends for all KPIs, so that I can detect improving or degrading performance.

#### Acceptance Criteria

1. THE Trend_Calculator SHALL compute 7-day and 30-day linear regression slopes for each KPI at each observation level
2. WHEN computing trends, THE Trend_Calculator SHALL require a minimum of 5 data points for 7-day trends and 14 data points for 30-day trends
3. THE Trend_Calculator SHALL classify each trend as: improving (slope > +threshold), stable (slope within ±threshold), or degrading (slope < -threshold)
4. THE Trend_Calculator SHALL store computed trends as pre-calculated values (not computed on dashboard load)

### Requirement 10: Composite Risk Score

**User Story:** As a platform operator, I want a single risk score per avatar, client, and system, so that I can quickly identify entities that need attention.

#### Acceptance Criteria

1. THE Alert_Engine SHALL compute a Composite_Risk_Score (0–100) for each avatar, each client, and the system as a whole
2. THE Alert_Engine SHALL compute the risk score using weighted factors: removal_rate_trend (weight 0.35), karma_trend (weight 0.30), volume_drop (weight 0.20), and consecutive_failures (weight 0.15)
3. WHEN a Composite_Risk_Score exceeds 70, THE Alert_Engine SHALL classify the entity as "at risk"
4. WHEN a Composite_Risk_Score exceeds 85, THE Alert_Engine SHALL classify the entity as "critical"
5. THE Alert_Engine SHALL recompute risk scores daily after trend calculation completes

### Requirement 11: Operator Alerts

**User Story:** As a platform operator, I want to receive alerts when quality metrics degrade, so that I can intervene before problems escalate.

#### Acceptance Criteria

1. WHEN an entity's Composite_Risk_Score transitions from below 70 to at or above 70, THE Alert_Engine SHALL create an alert record with severity "warning"
2. WHEN an entity's Composite_Risk_Score transitions from below 85 to at or above 85, THE Alert_Engine SHALL create an alert record with severity "critical"
3. WHEN 3 or more avatars show degrading karma trends in the same subreddit within a 7-day window, THE Alert_Engine SHALL create a Correlation_Alert indicating potential subreddit hostility
4. THE Alert_Engine SHALL retain alert records for 90 days
5. THE Alert_Engine SHALL not create duplicate alerts for the same entity and condition within a 24-hour window (deduplication)
6. THE Alert_Engine SHALL display unacknowledged alerts in the admin dashboard header as a notification badge

### Requirement 12: Quality Dashboard

**User Story:** As a platform operator, I want a single dashboard screen showing system health, decision quality, trends, and top risks, so that I can monitor quality at a glance.

#### Acceptance Criteria

1. THE Dashboard_Renderer SHALL display a single-page quality overview accessible at /admin/quality
2. THE Dashboard_Renderer SHALL show: system-level Composite_Risk_Score, per-node decision quality bars (strategy, scoring, EPG, generation, posting), sparkline trends for key KPIs (7-day), top 5 entities at risk, and recent learnings (last 10 effectiveness score changes)
3. THE Dashboard_Renderer SHALL support drill-down by observation level: clicking a client shows client-level metrics, clicking a subreddit shows subreddit-level metrics, clicking an avatar shows avatar-level metrics
4. THE Dashboard_Renderer SHALL load all data from pre-computed scores (not real-time aggregation), with page load time under 500ms for 10 clients
5. WHEN the dashboard is loaded, THE Dashboard_Renderer SHALL show data freshness indicators (last computation timestamp) for each section

### Requirement 13: Learning Channel Integration — Rejections

**User Story:** As a platform operator, I want draft rejections to feed back into scoring and EPG quality metrics, so that the system learns from operator decisions.

#### Acceptance Criteria

1. WHEN an operator rejects a draft, THE Learning_Engine SHALL record the rejection as a negative signal for the scoring decision that selected the thread and the EPG slot that included it
2. THE Learning_Engine SHALL compute a rejection_rate metric per subreddit and per avatar, updated on each rejection event
3. WHEN rejection_rate for a subreddit×avatar combination exceeds 50% over the last 20 drafts, THE Learning_Engine SHALL flag the combination for operator review

### Requirement 14: Learning Channel Integration — Karma Outcomes

**User Story:** As a platform operator, I want karma outcomes to be the strongest learning signal, feeding back into all pipeline nodes.

#### Acceptance Criteria

1. WHEN a 48h karma snapshot is recorded, THE Learning_Engine SHALL attribute the outcome to: the strategy that was active, the scoring decision, the EPG selection, the comment approach, and the timing bucket
2. THE Learning_Engine SHALL weight karma outcomes as the primary signal (weight 1.0) compared to rejections (weight 0.5) and removals (weight 0.8) when computing effectiveness scores
3. THE Learning_Engine SHALL distinguish between positive outcomes (karma > 0), neutral outcomes (karma = 0 or 1), and negative outcomes (karma < 0) for trend computation

### Requirement 15: Learning Channel Integration — Removals

**User Story:** As a platform operator, I want comment removals to feed back into safety rules and subreddit risk assessment.

#### Acceptance Criteria

1. WHEN a removal is detected, THE Learning_Engine SHALL increase the risk score for the subreddit where the removal occurred
2. WHEN a removal is detected, THE Learning_Engine SHALL decrease the effectiveness score for the approach×subreddit combination that was used
3. WHEN 3 or more removals occur in the same subreddit within 7 days, THE Learning_Engine SHALL flag the subreddit as "high moderation risk" in the subreddit observation level

### Requirement 16: Learning Channel Integration — Strategy and EPG Changes

**User Story:** As a platform operator, I want operator-initiated strategy changes and EPG reassignments to serve as implicit feedback signals.

#### Acceptance Criteria

1. WHEN an operator changes a client's active strategy, THE Learning_Engine SHALL record the change as a negative signal for the previous strategy pattern
2. WHEN an operator manually reassigns an EPG slot (changes thread or avatar), THE Learning_Engine SHALL record the reassignment as a negative signal for the original selection logic
3. THE Learning_Engine SHALL use strategy and EPG change signals with weight 0.3 (weakest signal) when computing effectiveness scores

### Requirement 17: Stress Resilience

**User Story:** As a platform operator, I want the Quality Sentinel to degrade gracefully under failure conditions, so that the core pipeline is never blocked by quality tracking.

#### Acceptance Criteria

1. IF an outcome check cycle fails entirely, THEN THE Outcome_Tracker SHALL skip the cycle and compute trends from remaining data points without blocking the pipeline
2. WHILE the Reddit API returns rate limit responses (HTTP 429), THE Outcome_Tracker SHALL implement exponential backoff and prioritize fresh posts (4h checks) over older checks (48h)
3. IF the database is under heavy load, THEN THE Trend_Calculator SHALL use a read-only connection and defer computation to the next off-peak window
4. WHILE processing outcomes for more than 100 clients (1500+ posts/day), THE Outcome_Tracker SHALL use batch processing (50 per task) rather than individual processing
5. IF effectiveness data for a combo key has fewer than 5 samples, THEN THE Learning_Engine SHALL fall back to the parent observation level rather than returning no score

### Requirement 18: Storage and Indexing

**User Story:** As a platform operator, I want quality data stored efficiently with proper indexing, so that the system performs well at scale without requiring a separate analytics database.

#### Acceptance Criteria

1. THE Outcome_Tracker SHALL store all data in PostgreSQL without requiring a separate analytics database (sufficient until 100+ clients)
2. THE Outcome_Tracker SHALL maintain indexes on: (entity_type, entity_id, timestamp) for outcome lookups, (kpi_name, timestamp) for trend queries, and (combo_key) for effectiveness score lookups
3. THE Outcome_Tracker SHALL maintain composite indexes optimized for dashboard queries (observation_level + entity_id + date range)
4. THE Outcome_Tracker SHALL consume approximately 22 KB/day of storage at 10 clients (50 bytes/outcome × 150 posts/day × 3 snapshots)
5. THE Learning_Engine SHALL maintain effectiveness scores as approximately 2.5 MB of in-place updated records (12,500 records at 10 clients)

### Requirement 19: Celery Task Scheduling

**User Story:** As a platform operator, I want quality tracking tasks scheduled efficiently alongside existing pipeline tasks, so that system overhead remains minimal.

#### Acceptance Criteria

1. THE Outcome_Tracker SHALL schedule karma check tasks via Celery Beat at 4-hour intervals, processing all pending checks in batch
2. THE Trend_Calculator SHALL schedule daily trend computation at 03:00 local time (Asia/Jerusalem)
3. THE Alert_Engine SHALL schedule risk score computation immediately after trend calculation completes (chained task)
4. THE Outcome_Tracker SHALL add less than 1% CPU overhead to the existing Celery worker (3 additional periodic tasks)
5. THE Outcome_Tracker SHALL consume fewer than 450 Reddit API calls per day at 10 clients (within the existing 60/min rate limit)
