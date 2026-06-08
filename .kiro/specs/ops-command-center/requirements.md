# Requirements Document

## Introduction

The Operations Command Center (OCC) is the operational backbone of the RAMP platform — a unified subsystem that provides structured observability, billing enforcement, outcome tracking, queue health, data lifecycle management, compliance checking, and a machine-readable API surface. The primary consumer is the RAMP AI Operations Assistant agent, which uses the OCC to monitor system state, detect anomalies, enforce business rules, and trigger corrective actions without human intervention.

The OCC consolidates 11 operational gaps into a cohesive system: structured logging, billing/plan enforcement, comment outcome tracking, queue observability, data retention, subreddit rule compliance, pagination, idempotency, budget engine, cross-avatar deduplication, and the Agent API surface that ties everything together.

## Glossary

- **OCC**: Operations Command Center — the unified operational subsystem described in this document
- **Agent**: The RAMP AI Operations Assistant — an autonomous agent that queries OCC endpoints to manage the platform
- **Structured_Log**: A JSON-formatted log entry with consistent fields (timestamp, level, service, trace_id, context) suitable for machine parsing
- **Plan**: A billing tier (Seed/Starter/Growth/Scale/Agency) with defined action limits
- **Action_Limit**: The maximum number of billable operations (comments, posts, scrapes) a client can perform per billing period
- **Usage_Meter**: A counter tracking how many billable actions a client has consumed in the current billing period
- **Karma_Snapshot**: A point-in-time capture of a posted comment's karma score, used to measure engagement outcome
- **Outcome_Signal**: A derived metric (karma delta, removal status) indicating comment quality after posting
- **DLQ**: Dead Letter Queue — a holding area for tasks that have failed maximum retry attempts
- **Stuck_Task**: A Celery task that has been running longer than its expected maximum duration without completing
- **TTL**: Time To Live — the maximum age of a record before it becomes eligible for automated deletion
- **Subreddit_Rules**: The posting rules defined in a subreddit's sidebar, wiki, or rule list that moderators enforce
- **Compliance_Check**: An automated verification that a generated comment does not violate the target subreddit's known rules
- **Idempotency_Key**: A unique identifier attached to a task request that prevents duplicate execution of the same operation
- **Budget_Allocation**: The daily spending limit (in actions) assigned to an avatar, calculated from plan limits and avatar count
- **Thread_Lock**: A record indicating that a specific Reddit thread has been claimed by one avatar, preventing other avatars from commenting on it
- **Cursor_Pagination**: A pagination method using opaque cursor tokens instead of offset/limit, providing stable results during concurrent writes

## Requirements

### Requirement 1: Structured Logging Infrastructure

**User Story:** As the Agent, I want all platform services to emit structured JSON logs with consistent fields, so that I can query, filter, and aggregate operational events programmatically.

#### Acceptance Criteria

1. THE OCC SHALL emit all application logs as JSON objects containing the fields: timestamp (ISO 8601), level, service, trace_id, message, and context (arbitrary key-value metadata).
2. WHEN a FastAPI request is received, THE OCC SHALL generate a unique trace_id and propagate the trace_id through all downstream service calls and Celery tasks spawned by that request.
3. WHEN a Celery task begins execution, THE OCC SHALL attach the originating trace_id to all log entries emitted during task execution.
4. THE OCC SHALL categorize log entries by service domain: scraping, scoring, generation, posting, health, billing, queue, cleanup.
5. IF a log entry cannot be serialized to JSON, THEN THE OCC SHALL emit a fallback plain-text entry with an error marker and the original message content.

### Requirement 2: Log Aggregation and Querying

**User Story:** As the Agent, I want to query logs by time range, service, level, and trace_id, so that I can investigate incidents and correlate events across pipeline stages.

#### Acceptance Criteria

1. THE OCC SHALL store structured log entries in a queryable PostgreSQL table with indexes on timestamp, level, service, and trace_id.
2. WHEN the Agent queries logs with filter parameters (time_range, service, level, trace_id, keyword), THE OCC SHALL return matching entries ordered by timestamp descending.
3. THE OCC SHALL retain log entries for 30 days in the queryable store.
4. WHEN log entries exceed the 30-day retention window, THE OCC SHALL delete expired entries via a daily cleanup job.
5. THE OCC SHALL enforce a maximum of 10,000 log entries per query response, using cursor pagination for larger result sets.

### Requirement 3: Alerting and Anomaly Detection

**User Story:** As the Agent, I want to receive structured alert signals when operational metrics deviate from expected thresholds, so that I can take corrective action autonomously.

#### Acceptance Criteria

1. THE OCC SHALL define configurable alert thresholds for: error rate per service (default 5%), task failure rate (default 10%), queue depth (default 100), DLQ depth (default 1), and posting failure rate (default 15%).
2. WHEN a metric exceeds its configured threshold within a 15-minute evaluation window, THE OCC SHALL create an Alert record with fields: alert_type, severity (warning/critical), metric_value, threshold_value, context, created_at.
3. WHILE an alert condition persists, THE OCC SHALL suppress duplicate alerts of the same type for 30 minutes (deduplication window).
4. WHEN an alert condition resolves (metric drops below threshold), THE OCC SHALL mark the alert as resolved with a resolved_at timestamp.
5. THE OCC SHALL expose an endpoint returning all active (unresolved) alerts for the Agent to poll.

### Requirement 4: Stripe Billing Integration

**User Story:** As the platform owner, I want to integrate Stripe for subscription billing and payment processing, so that clients are charged according to their plan tier.

#### Acceptance Criteria

1. THE OCC SHALL map each RAMP plan tier (Seed, Starter, Growth, Scale, Agency) to a Stripe Product with corresponding Price objects.
2. WHEN a new client is onboarded, THE OCC SHALL create a Stripe Customer record linked to the client's RAMP client_id.
3. WHEN a client's plan is activated, THE OCC SHALL create a Stripe Subscription with the corresponding Price and billing_cycle_anchor set to the client's start date.
4. WHEN Stripe sends a webhook event (invoice.paid, invoice.payment_failed, customer.subscription.updated, customer.subscription.deleted), THE OCC SHALL process the event and update the client's billing status in the RAMP database.
5. IF a payment fails after Stripe's retry attempts are exhausted, THEN THE OCC SHALL set the client's billing_status to "past_due" and emit a critical alert.
6. THE OCC SHALL store Stripe customer_id, subscription_id, and current_period_end on the Client model.

### Requirement 5: Plan Action Limits and Usage Metering

**User Story:** As the Agent, I want the platform to enforce plan-specific action limits and track usage in real time, so that clients cannot exceed their subscribed capacity.

#### Acceptance Criteria

1. THE OCC SHALL define action limits per plan tier: Seed (30 comments/month), Starter (60 comments/month), Growth (150 comments + 10 posts/month), Scale (400 actions/month), Agency (custom).
2. WHEN a billable action (comment generation, post creation) is requested, THE OCC SHALL increment the client's usage meter for the current billing period.
3. WHEN a client's usage meter reaches 80% of their plan limit, THE OCC SHALL emit a warning alert.
4. WHEN a client's usage meter reaches 100% of their plan limit, THE OCC SHALL block further billable actions for that client and return a "limit_exceeded" response.
5. WHEN a new billing period begins (determined by Stripe's current_period_start), THE OCC SHALL reset the client's usage meter to zero.
6. THE OCC SHALL expose the current usage count and remaining capacity for each client via the Agent API.

### Requirement 6: Comment Outcome Tracking — Karma Snapshots

**User Story:** As the Agent, I want to track karma changes on posted comments at defined intervals, so that I can measure comment quality and feed outcome data into the learning loop.

#### Acceptance Criteria

1. WHEN a comment is successfully posted, THE OCC SHALL schedule karma snapshot tasks at 4 hours, 24 hours, and 48 hours after posting.
2. WHEN a karma snapshot task executes, THE OCC SHALL fetch the comment's current score via PRAW and store a Karma_Snapshot record (comment_draft_id, snapshot_time, karma_score, upvote_ratio).
3. IF the comment is not found during a karma snapshot (HTTP 404 or PRAW not-found), THEN THE OCC SHALL mark the comment as removed and store a removal_detected_at timestamp.
4. THE OCC SHALL compute karma_delta (48h_score minus 1h_score) for each tracked comment after the 48-hour snapshot completes.
5. THE OCC SHALL expose outcome statistics per avatar and per subreddit: average karma_delta, removal rate, and percentile distribution.

### Requirement 7: Comment Outcome Feedback Loop

**User Story:** As the Agent, I want outcome signals to feed back into the generation pipeline, so that the system learns from real-world comment performance.

#### Acceptance Criteria

1. WHEN a comment's 48-hour karma_delta is below -2 (net downvoted), THE OCC SHALL flag the comment as "underperforming" and record the associated subreddit, approach, and avatar.
2. WHEN a comment is detected as removed, THE OCC SHALL flag the comment as "removed_by_mod" and record the subreddit and content characteristics.
3. THE OCC SHALL aggregate outcome signals into per-avatar quality scores: success_rate (comments with karma_delta > 0 / total tracked) and survival_rate (comments not removed / total tracked).
4. WHEN an avatar's survival_rate drops below 70% over the last 20 tracked comments, THE OCC SHALL emit a warning alert and include the top removal reasons.
5. THE OCC SHALL provide outcome summary data in a format injectable into the generation prompt context (top 3 performing approaches per subreddit, top 3 underperforming patterns to avoid).

### Requirement 8: Queue Observability — DLQ and Failure Metrics

**User Story:** As the Agent, I want visibility into failed tasks, stuck tasks, and dead-letter queue depth, so that I can detect pipeline blockages and trigger recovery actions.

#### Acceptance Criteria

1. THE OCC SHALL maintain a DLQ table storing tasks that have exhausted all retry attempts, with fields: task_id, task_name, args, kwargs, exception_message, failed_at, original_trace_id.
2. WHEN a Celery task exceeds its max_retries, THE OCC SHALL move the task metadata to the DLQ table instead of silently dropping the failure.
3. THE OCC SHALL detect stuck tasks by comparing task start_time against expected_max_duration (configurable per task type, default 300 seconds).
4. WHEN a stuck task is detected, THE OCC SHALL emit a warning alert with task_id, task_name, duration, and worker_id.
5. THE OCC SHALL expose queue health metrics: tasks_completed_last_hour, tasks_failed_last_hour, dlq_depth, stuck_task_count, average_task_duration_ms (grouped by task_name).
6. THE OCC SHALL provide a DLQ replay endpoint allowing the Agent to re-enqueue specific failed tasks by task_id.

### Requirement 9: Data Retention and Automated Cleanup

**User Story:** As the platform owner, I want automated data lifecycle management with configurable TTL policies, so that the database does not grow unbounded and old data is pruned systematically.

#### Acceptance Criteria

1. THE OCC SHALL enforce a 90-day TTL for RedditThread records that have no associated active (pending/approved) comment drafts.
2. THE OCC SHALL enforce a 180-day TTL for CommentDraft records in terminal states (posted, rejected) that have completed outcome tracking.
3. THE OCC SHALL enforce a 30-day TTL for ScrapeLog records.
4. THE OCC SHALL enforce a 30-day TTL for structured log entries in the queryable store.
5. WHEN the daily cleanup job executes, THE OCC SHALL delete eligible records in batches of 1,000 with a 100ms pause between batches to avoid database lock contention.
6. THE OCC SHALL log the count of deleted records per entity type after each cleanup run and expose the last cleanup results via the Agent API.
7. IF a cleanup batch encounters a database error, THEN THE OCC SHALL stop the current batch, log the error, and emit a warning alert.

### Requirement 10: Subreddit Rule Extraction

**User Story:** As the Agent, I want the platform to parse and store subreddit posting rules, so that generated comments can be checked for compliance before submission.

#### Acceptance Criteria

1. WHEN a subreddit is added to the platform or when a periodic refresh triggers (weekly), THE OCC SHALL fetch the subreddit's rules via PRAW (subreddit.rules) and sidebar/wiki content.
2. THE OCC SHALL store extracted rules in a SubredditRule model with fields: subreddit_id, rule_text, rule_category (content_type, formatting, self_promotion, minimum_karma, link_policy, other), extracted_at.
3. THE OCC SHALL use an LLM call (Gemini Flash) to parse unstructured sidebar text into categorized rule records.
4. IF PRAW returns no rules or an error for a subreddit, THEN THE OCC SHALL mark the subreddit as "rules_unknown" and skip compliance checking for that subreddit.
5. THE OCC SHALL store a rules_hash per subreddit and only re-process rules when the hash changes on refresh.

### Requirement 11: Comment Compliance Checking

**User Story:** As the Agent, I want each generated comment to be checked against the target subreddit's rules before entering the review queue, so that rule-violating comments are caught early.

#### Acceptance Criteria

1. WHEN a comment draft is generated, THE OCC SHALL run a compliance check against the target subreddit's stored rules before setting the draft status to "pending".
2. THE OCC SHALL check for: self-promotion violations (brand mention frequency), minimum account age/karma requirements, prohibited content types, link restrictions, and formatting requirements.
3. IF a compliance check detects a violation, THEN THE OCC SHALL mark the draft with compliance_status "failed", attach the violated rule references, and set the draft status to "compliance_blocked".
4. WHILE a subreddit has rules_status "rules_unknown", THE OCC SHALL skip compliance checking and allow drafts to proceed to "pending" status.
5. THE OCC SHALL expose compliance failure statistics per subreddit and per violation category via the Agent API.

### Requirement 12: Cursor-Based Pagination for List Endpoints

**User Story:** As the Agent, I want all list endpoints to support cursor-based pagination with consistent response structure, so that large result sets can be traversed efficiently without offset drift.

#### Acceptance Criteria

1. THE OCC SHALL implement cursor-based pagination on all list endpoints that may return more than 50 items.
2. THE OCC SHALL use opaque cursor tokens encoding the sort key position (not row offset) to provide stable pagination under concurrent writes.
3. WHEN a paginated request includes a cursor parameter, THE OCC SHALL return the next page of results starting after the cursor position.
4. THE OCC SHALL include in every paginated response: items (array), next_cursor (string or null), has_more (boolean), total_count (integer).
5. THE OCC SHALL default page_size to 50 items with a configurable maximum of 200 items per request.

### Requirement 13: Idempotency Keys for Task Execution

**User Story:** As the Agent, I want task submissions to be idempotent, so that network retries and duplicate dispatches do not cause the same operation to execute twice.

#### Acceptance Criteria

1. WHEN a task is dispatched (via Celery or the Agent API), THE OCC SHALL accept an optional idempotency_key parameter.
2. WHEN a task with an idempotency_key is received, THE OCC SHALL check whether a task with the same key has been executed or is currently in-flight within the deduplication window.
3. IF a duplicate idempotency_key is detected for a completed task, THEN THE OCC SHALL return the cached result of the original execution without re-executing.
4. IF a duplicate idempotency_key is detected for an in-flight task, THEN THE OCC SHALL return a "task_in_progress" status with the original task_id.
5. THE OCC SHALL store idempotency records with a 24-hour TTL, after which the same key may be reused.
6. THE OCC SHALL use Redis for idempotency lookups to ensure sub-millisecond check latency.

### Requirement 14: Budget Engine — Daily Action Allocation

**User Story:** As the Agent, I want each avatar to have a smart daily action budget derived from the client's plan limits and avatar count, so that posting activity is distributed evenly across the billing period.

#### Acceptance Criteria

1. THE OCC SHALL calculate daily_budget_per_avatar as: (client_monthly_limit - current_usage) / remaining_days_in_period / active_avatar_count.
2. WHEN the daily budget is recalculated (daily at 00:00 Asia/Jerusalem), THE OCC SHALL store the allocation per avatar with fields: avatar_id, date, daily_limit, used_today.
3. WHEN an avatar's used_today reaches its daily_limit, THE OCC SHALL block further actions for that avatar until the next day.
4. THE OCC SHALL apply a floor of 1 action/day per avatar (never starve an avatar completely) and a ceiling of 3x the average daily rate (prevent burst usage).
5. WHEN a client adds or removes avatars mid-period, THE OCC SHALL recalculate daily budgets for all affected avatars immediately.
6. THE OCC SHALL expose current budget allocation and remaining capacity per avatar via the Agent API.

### Requirement 15: Cross-Avatar Thread Deduplication

**User Story:** As the Agent, I want to prevent multiple avatars owned by the same client from commenting on the same Reddit thread, so that brand presence appears natural and does not trigger moderator suspicion.

#### Acceptance Criteria

1. WHEN the generation pipeline selects a thread for an avatar, THE OCC SHALL check whether any other avatar assigned to the same client has an existing comment draft (pending, approved, or posted) targeting the same thread.
2. IF a thread is already claimed by another avatar of the same client, THEN THE OCC SHALL skip the thread for the current avatar and log a deduplication event.
3. THE OCC SHALL maintain a Thread_Lock index (client_id, thread_id, avatar_id) for efficient deduplication lookups.
4. WHEN a comment draft is rejected or the underlying thread is removed, THE OCC SHALL release the thread lock, making the thread available for other avatars.
5. THE OCC SHALL expose deduplication statistics (threads skipped due to dedup, per client) via the Agent API.

### Requirement 16: Agent API Surface — System State Queries

**User Story:** As the Agent, I want a structured JSON API to query the full operational state of the platform, so that I can make informed decisions about system health and required interventions.

#### Acceptance Criteria

1. THE OCC SHALL expose a GET /api/agent/system-status endpoint returning: pipeline_status (enabled/paused per stage), active_alerts_count, dlq_depth, stuck_tasks_count, pending_review_count, posting_queue_depth.
2. THE OCC SHALL expose a GET /api/agent/clients/{id}/health endpoint returning: usage_current, usage_limit, billing_status, active_avatars, frozen_avatars, avg_karma_delta_7d, removal_rate_7d.
3. THE OCC SHALL expose a GET /api/agent/avatars/{id}/status endpoint returning: health_status, warming_phase, daily_budget_remaining, last_posted_at, karma_trend_7d, survival_rate, is_frozen, freeze_reason.
4. THE OCC SHALL expose a GET /api/agent/pipeline/metrics endpoint returning: scrapes_today, scores_today, generations_today, posts_today, failures_today, avg_latency_per_stage_ms.
5. ALL Agent API endpoints SHALL require authentication with the "owner" or "partner" role and return JSON responses with consistent error schema: {error: string, code: string, details: object}.

### Requirement 17: Agent API Surface — Operational Actions

**User Story:** As the Agent, I want to trigger operational actions via API (pause pipeline, freeze avatar, replay DLQ, trigger cleanup), so that I can respond to anomalies without human intervention.

#### Acceptance Criteria

1. THE OCC SHALL expose a POST /api/agent/pipeline/pause endpoint accepting a stage parameter (scraping/scoring/generation/posting/all) to pause specific pipeline stages.
2. THE OCC SHALL expose a POST /api/agent/pipeline/resume endpoint accepting a stage parameter to resume paused pipeline stages.
3. THE OCC SHALL expose a POST /api/agent/avatars/{id}/freeze endpoint accepting a reason parameter to freeze a specific avatar.
4. THE OCC SHALL expose a POST /api/agent/dlq/replay endpoint accepting task_ids (array) to re-enqueue specific failed tasks.
5. THE OCC SHALL expose a POST /api/agent/cleanup/trigger endpoint to manually trigger the data retention cleanup job outside its daily schedule.
6. ALL operational action endpoints SHALL log an AuditLog entry with actor="agent", action description, and the affected entity identifiers.
7. ALL operational action endpoints SHALL return the result of the action: {success: boolean, action: string, affected_entities: array, timestamp: string}.

### Requirement 18: Agent API Surface — Reports and Summaries

**User Story:** As the Agent, I want to generate structured operational reports covering key metrics for any time window, so that I can provide summaries to the platform owner and identify trends.

#### Acceptance Criteria

1. THE OCC SHALL expose a GET /api/agent/reports/daily-summary endpoint returning: total_actions_today, actions_by_client, top_performing_avatars (by karma_delta), alerts_fired_today, budget_utilization_percentage.
2. THE OCC SHALL expose a GET /api/agent/reports/outcome-analysis endpoint accepting a time_range parameter and returning: avg_karma_delta, removal_rate, top_subreddits_by_performance, underperforming_avatars, compliance_failure_rate.
3. THE OCC SHALL expose a GET /api/agent/reports/cost-analysis endpoint returning: llm_cost_today, llm_cost_mtd, cost_per_client, cost_per_comment, projected_monthly_cost.
4. THE OCC SHALL expose a GET /api/agent/reports/queue-health endpoint returning: tasks_processed_24h, failure_rate, avg_latency_ms, dlq_age_distribution, worker_utilization.
5. ALL report endpoints SHALL accept optional client_id and date_range query parameters for scoped analysis.

