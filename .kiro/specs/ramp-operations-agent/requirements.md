# Requirements Document

## Introduction

The RAMP Operations Agent is an autonomous software agent that monitors, manages, and optimizes the entire RAMP platform operations. The Agent acts as a tireless operations engineer — detecting issues before humans notice them, performing routine maintenance autonomously, escalating critical decisions to the platform owner (Max), and providing daily economic intelligence. The Agent integrates with the existing admin panel and operates within a clearly defined authority framework where actions are categorized as autonomous, confirmation-required, or forbidden.

The Agent's value proposition: Max transitions from operator to architect/investor. The Agent handles all routine operations, early warnings, cost optimization, and system health — surfacing only what requires human judgment.

## Glossary

- **RAMP_Agent**: The autonomous operations agent that monitors and manages the RAMP platform
- **Platform_Owner**: Max — the technical co-founder who receives briefings and approves escalated decisions
- **Health_Monitor**: The subsystem that continuously checks infrastructure, pipeline, and avatar health metrics
- **Alert_Engine**: The subsystem that generates, prioritizes, and delivers alerts at different time horizons
- **Economics_Engine**: The subsystem that tracks costs, calculates margins, and suggests optimizations
- **Authority_Framework**: The decision matrix defining what the Agent can do autonomously vs. what requires human approval
- **Briefing_Service**: The subsystem that generates daily/weekly reports for the Platform Owner
- **Action_Executor**: The subsystem that performs autonomous operations (restart, freeze, redistribute, etc.)
- **Metric_Collector**: The subsystem that aggregates real-time metrics from all platform components
- **Escalation**: A notification sent to the Platform Owner when the Agent encounters a situation outside its autonomous authority
- **Silent_Failure**: A system malfunction that produces no errors or alerts but degrades service quality
- **Health_Score**: A composite 0-100 score representing overall platform operational health
- **Cost_Per_Client**: The total operational cost (LLM + infrastructure + proxy) attributable to a single client
- **Margin**: Revenue minus operational cost, expressed as a percentage
- **Drift**: Gradual degradation of a metric over time that individually doesn't trigger alerts but cumulatively indicates a problem

## Requirements

### Requirement 1: System Health Monitoring

**User Story:** As the Platform Owner, I want the Agent to continuously monitor all system components, so that I know the platform is operating correctly without checking it myself.

#### Acceptance Criteria

1. THE RAMP_Agent SHALL collect health metrics from all infrastructure components (PostgreSQL, Redis, Celery workers, Docker containers, disk space, memory, CPU) at intervals no greater than 60 seconds
2. THE RAMP_Agent SHALL collect pipeline metrics (scraping throughput, scoring throughput, generation throughput, review queue depth, posting success rate) at intervals no greater than 5 minutes
3. THE RAMP_Agent SHALL collect avatar health metrics (frozen count, shadowbanned count, CQS scores, karma trends, posting failure rates) at intervals no greater than 15 minutes
4. THE RAMP_Agent SHALL compute a composite Health_Score (0-100) from all collected metrics using a weighted average where infrastructure components contribute 40%, pipeline metrics contribute 35%, and avatar health metrics contribute 25%, updated every 60 seconds
5. WHEN a monitored component fails to respond to 2 consecutive health checks (each with a per-check timeout of 10 seconds), THE RAMP_Agent SHALL mark that component as "degraded" within 120 seconds of the first failed check
6. WHEN a component marked as "degraded" responds successfully to 3 consecutive health checks, THE RAMP_Agent SHALL restore that component's status to "healthy"
7. THE RAMP_Agent SHALL maintain a rolling 7-day history of all collected metrics at raw sample granularity for the most recent 24 hours and at 5-minute aggregated granularity for the remaining 6 days
8. IF the Health_Score drops below 70, THEN THE RAMP_Agent SHALL generate a diagnostic report within 30 seconds that lists: each metric contributing a below-normal value, the metric's current value versus its normal range, and the weighted impact of each degraded metric on the overall Health_Score
9. IF a metric source is unavailable during Health_Score computation, THEN THE RAMP_Agent SHALL use the last known value for up to 5 minutes and assign a score of 0 for that component if the source remains unavailable beyond 5 minutes

### Requirement 2: Infrastructure Monitoring

**User Story:** As the Platform Owner, I want the Agent to watch server resources and database health, so that I never face unexpected downtime.

#### Acceptance Criteria

1. THE RAMP_Agent SHALL collect DigitalOcean droplet metrics (CPU utilization, memory usage, disk usage, network I/O) at intervals no greater than 60 seconds and expose the latest values on the admin health dashboard
2. WHEN disk usage exceeds 80%, THE RAMP_Agent SHALL identify the top 5 largest disk consumers by directory size and present a list of suggested cleanup actions (e.g., log rotation, cache purge, old backup removal)
3. WHEN memory usage exceeds 85% for more than 5 minutes, THE RAMP_Agent SHALL identify the top 5 memory-consuming processes by RSS and log a warning with process name, PID, and memory percentage for each
4. WHEN CPU utilization exceeds 90% for more than 3 minutes, THE RAMP_Agent SHALL log a capacity warning indicating the sustained CPU percentage and the top 3 CPU-consuming processes
5. THE RAMP_Agent SHALL collect PostgreSQL metrics (active connections, connection pool utilization, longest-running queries, table bloat percentage, and replication lag when applicable) at intervals no greater than 60 seconds and expose the latest values on the admin health dashboard
6. THE RAMP_Agent SHALL collect Redis metrics (memory usage, connected clients, eviction rate, keyspace hit ratio) at intervals no greater than 60 seconds and expose the latest values on the admin health dashboard
7. THE RAMP_Agent SHALL collect Celery worker metrics (active tasks, reserved tasks, worker uptime, task failure rate, task duration percentiles p50/p95/p99) at intervals no greater than 60 seconds and expose the latest values on the admin health dashboard
8. WHEN a Celery worker has not sent a heartbeat for 120 seconds, THE RAMP_Agent SHALL mark that worker as "unresponsive" and log a warning with the worker name and last-seen timestamp
9. IF PostgreSQL connection pool utilization exceeds 80%, THEN THE RAMP_Agent SHALL log a capacity warning with current pool usage count, maximum pool size, and percentage utilization
10. IF any monitored metric collection fails for 3 consecutive attempts, THEN THE RAMP_Agent SHALL log an error indicating which metric source is unreachable and mark that source as "degraded" on the admin health dashboard

### Requirement 3: Pipeline Health Monitoring

**User Story:** As the Platform Owner, I want the Agent to ensure every pipeline stage is functioning correctly, so that clients receive their content on schedule.

#### Acceptance Criteria

1. THE RAMP_Agent SHALL track per-stage pipeline metrics over a rolling 1-hour window: scraping (scrapes completed, success rate), scoring (threads scored, percentage tagged "engage"), generation (drafts created, average token count), review (queue depth, age of oldest pending item), posting (posts attempted, success rate)
2. IF a pipeline stage produces zero output for a period exceeding twice its configured cycle time (scraping: 2x scrape_freshness_window_hours, scoring/generation: 12 hours since last scheduled run, posting: 10 minutes since last execute_pending_posts tick), THEN THE RAMP_Agent SHALL flag that stage as "stalled" by recording an activity event with severity "warning" and the affected stage name
3. WHEN the scoring-to-generation ratio drops below 5% (fewer than 5% of scored threads result in "engage") within a single pipeline run for a client, THE RAMP_Agent SHALL flag a potential scoring calibration issue by recording an activity event referencing the affected client
4. WHEN the review queue depth exceeds 50 pending items or the oldest pending item exceeds 24 hours, THE RAMP_Agent SHALL generate a review backlog alert recorded as an activity event with severity "warning"
5. THE RAMP_Agent SHALL track end-to-end pipeline latency (time from thread scrape to comment post) per client, computed as the duration between the thread's scraped_at timestamp and the corresponding draft's posted_at timestamp
6. WHEN posting failure rate exceeds 20% over a 1-hour window, THE RAMP_Agent SHALL flag a posting system degradation by recording an activity event with severity "critical" and the failure count and total attempt count
7. IF any client has received zero new drafts for 48 hours while their pipeline is enabled, THEN THE RAMP_Agent SHALL identify the first stalled or empty stage in that client's pipeline (scraping, scoring, generation) and record a diagnostic activity event specifying the blocked stage name, last successful output timestamp for that stage, and the client identifier

### Requirement 4: Avatar Fleet Monitoring

**User Story:** As the Platform Owner, I want the Agent to watch all avatars and detect degradation early, so that no avatar silently loses effectiveness.

#### Acceptance Criteria

1. THE RAMP_Agent SHALL track per-avatar metrics: daily posts count, karma trend (7-day rolling net karma delta), comment removal rate, CQS score, frozen status, health status, and phase progress
2. IF an avatar's comment removal rate exceeds 30% over a 7-day window with a minimum of 5 posted comments in that window, THEN THE RAMP_Agent SHALL flag that avatar as "at risk" and record the event in the activity log
3. IF an avatar's 7-day rolling net karma delta is negative for 14 consecutive days, THEN THE RAMP_Agent SHALL generate a karma decline alert visible on the admin dashboard
4. IF an avatar has not posted for more than 72 hours while not frozen and not in phase 0, THEN THE RAMP_Agent SHALL flag that avatar as "inactive" on the admin dashboard and record an activity event
5. IF more than 20% of the active avatar fleet (minimum 5 active avatars) is frozen simultaneously, THEN THE RAMP_Agent SHALL escalate to the Platform Owner with a fleet health summary via the admin dashboard alert panel
6. IF an avatar remains in the same warming phase for more than 60 days without a phase override, THEN THE RAMP_Agent SHALL flag that avatar as "phase-stuck" on the admin dashboard
7. WHEN the health checker detects a Reddit suspension or shadowban for an avatar, THE RAMP_Agent SHALL within the same check cycle log the event, freeze the avatar, and create an activity event visible to the Platform Owner
8. THE RAMP_Agent SHALL evaluate all fleet monitoring conditions during the scheduled health check cycles (07:30 and 13:30 daily) and report aggregate fleet status on the admin dashboard

### Requirement 5: Early Warning System

**User Story:** As the Platform Owner, I want tiered alerts at different time horizons, so that I can act on problems before they become critical.

#### Acceptance Criteria

1. THE Alert_Engine SHALL categorize alerts into four time horizons: immediate (respond within 5 minutes), short-term (respond within 1 hour), plannable (respond within 24 hours), trend (respond within 1 week)
2. WHEN an immediate alert is generated, THE Alert_Engine SHALL deliver it via push notification (Telegram) within 30 seconds
3. WHEN a short-term alert is generated with severity "high", THE Alert_Engine SHALL deliver it immediately via Telegram; WHEN a short-term alert is generated with severity below "high", THE Alert_Engine SHALL include it in the next hourly digest
4. WHEN a plannable alert is generated, THE Alert_Engine SHALL include it in the daily briefing
5. WHEN a trend alert is generated, THE Alert_Engine SHALL include it in the weekly report with supporting data visualization
6. THE Alert_Engine SHALL suppress duplicate alerts for the same issue (matched by alert_type and affected entity identifier) within a configurable cooldown period (default: 1 hour for immediate, 4 hours for short-term, 24 hours for plannable)
7. THE Alert_Engine SHALL maintain an alert history with resolution status (open, acknowledged, resolved, false-positive) and retain alert records for a rolling 90-day window
8. IF the same alert fires more than 3 times in 24 hours without resolution, THEN THE Alert_Engine SHALL escalate the alert one level higher in severity (short-term to immediate, plannable to short-term)
9. IF an alert has already been escalated to "immediate" severity, THEN THE Alert_Engine SHALL not escalate further but SHALL add an "escalation ceiling reached" annotation to the alert record
10. IF Telegram delivery fails for an immediate alert, THEN THE Alert_Engine SHALL retry up to 3 times with 30-second intervals, then fall back to email delivery

### Requirement 6: Immediate Alerts (5-Minute Response)

**User Story:** As the Platform Owner, I want to know about critical failures immediately, so that I can prevent data loss or client impact.

#### Acceptance Criteria

1. WHEN the system_heartbeat task has not recorded an activity event for 3 consecutive expected intervals (180 seconds of silence), THE Alert_Engine SHALL generate an alert "Pipeline stopped — all workers down" and deliver it to the configured notification channel within 60 seconds of detection
2. WHEN 3 consecutive PostgreSQL connection attempts fail within a 60-second window, THE Alert_Engine SHALL generate an alert "Database connection lost" and deliver it to the configured notification channel within 60 seconds of detection
3. WHEN 3 consecutive Redis connection attempts fail within a 60-second window, THE Alert_Engine SHALL generate an alert "Cache/lock system down — posting safety compromised" and deliver it to the configured notification channel within 60 seconds of detection
4. WHEN an avatar's health check detects a Reddit account suspension, THE Alert_Engine SHALL generate an alert containing the avatar's reddit_username and the most recent PostingEvent or CommentDraft action associated with that avatar, and deliver it to the configured notification channel within 60 seconds of detection
5. WHEN the server disk usage exceeds 95%, THE Alert_Engine SHALL generate an alert "Disk full — service at risk" and deliver it to the configured notification channel within 60 seconds of detection
6. WHEN automated posting produces 3 or more failures across 2 or more different avatars within a rolling 10-minute window, THE Alert_Engine SHALL generate an alert "Systemic posting failure detected" and deliver it to the configured notification channel within 60 seconds of detection
7. WHILE an alert condition persists, THE Alert_Engine SHALL suppress duplicate alerts for the same condition for a minimum of 30 minutes after the initial alert delivery
8. WHEN an alert is generated, THE Alert_Engine SHALL include a UTC timestamp of detection, the alert severity level "critical", and a machine-readable alert_type identifier in the alert payload

### Requirement 7: Short-Term Alerts (1-Hour Response)

**User Story:** As the Platform Owner, I want to know about fixable problems within an hour, so that I can resolve them before they cascade.

#### Acceptance Criteria

1. WHEN a single avatar has 3 consecutive posting failures, THE Alert_Engine SHALL generate a short-term alert that includes the avatar identifier, the subreddit and thread of each failed attempt, the failure reason per attempt, and the timestamps of the 3 failures
2. WHEN LLM API error rate exceeds 10% over a 30-minute sliding window, THE Alert_Engine SHALL generate a short-term alert "LLM provider degradation"
3. WHEN Reddit API returns rate-limit responses (HTTP 429) more than 5 times in 15 minutes, THE Alert_Engine SHALL generate a short-term alert "Reddit rate limit pressure"
4. WHEN Celery task queue depth exceeds 100 pending tasks, THE Alert_Engine SHALL generate a short-term alert "Task backlog growing"
5. WHEN any single Celery task has been running for more than 10 minutes, THE Alert_Engine SHALL generate a short-term alert "Stuck task detected"
6. WHEN a scheduled pipeline run (08:00 or 14:00 Asia/Jerusalem) does not start within 15 minutes of its scheduled time, THE Alert_Engine SHALL generate a short-term alert "Scheduled pipeline missed"
7. THE Alert_Engine SHALL evaluate all short-term alert conditions at least once every 60 seconds and deliver generated alerts as persistent notifications on the admin dashboard within 30 seconds of detection
8. IF a short-term alert condition remains active, THEN THE Alert_Engine SHALL suppress duplicate alerts for the same condition for a cooldown period of 30 minutes before re-alerting
9. WHEN a short-term alert condition that was previously active is no longer detected, THE Alert_Engine SHALL mark the alert as resolved and record the resolution timestamp

### Requirement 8: Plannable Alerts (24-Hour Response)

**User Story:** As the Platform Owner, I want to know about issues I can plan around, so that I address them during working hours.

#### Acceptance Criteria

1. WHEN daily LLM cost exceeds 150% of the 7-day rolling average, THE Alert_Engine SHALL generate a plannable alert "Cost spike detected" with a breakdown by operation type (scoring, generation, persona selection, editing, hobby)
2. WHEN a client's engagement rate (comments posted / threads scored) drops below 3% over a 3-day window, THE Alert_Engine SHALL generate a plannable alert "Client engagement declining" identifying the affected client
3. WHEN the server's weekly backup has not completed for more than 48 hours past its scheduled time, THE Alert_Engine SHALL generate a plannable alert "Backup overdue"
4. WHEN more than 3 avatars enter frozen state in a single calendar day (00:00-23:59 server timezone), THE Alert_Engine SHALL generate a plannable alert "Elevated avatar freeze rate" listing the affected avatars and their freeze reasons
5. WHEN SSL certificate expiration is less than 14 days away, THE Alert_Engine SHALL generate a plannable alert "Certificate renewal needed" indicating the certificate domain and exact expiration date
6. WHEN database storage usage grows by more than 10% in a single week, THE Alert_Engine SHALL generate a plannable alert "Storage growth acceleration" indicating current usage and growth percentage
7. THE Alert_Engine SHALL evaluate all plannable alert conditions at least once every 60 minutes and deliver triggered alerts to the Platform Owner via the admin dashboard notifications panel and email within 30 minutes of detection
8. IF a plannable alert condition remains active, THEN THE Alert_Engine SHALL suppress duplicate alerts for the same condition for a minimum of 24 hours after the initial alert before re-alerting
9. WHEN a plannable alert is generated, THE Alert_Engine SHALL record the alert timestamp, condition type, and payload so that the Platform Owner can review outstanding alerts in a single dashboard view

### Requirement 9: Trend Alerts (Weekly Analysis)

**User Story:** As the Platform Owner, I want to spot gradual degradation early, so that I can fix systemic issues before they impact clients.

#### Acceptance Criteria

1. WHEN the average comment approval rate (approved drafts / total reviewed drafts) declines by more than 10 percentage points when comparing the most recent 7-day window to the preceding 21-day window, and the total reviewed drafts in both windows each exceed 20, THE Alert_Engine SHALL generate a trend alert "Generation quality declining"
2. WHEN the overall platform cost-per-client (total LLM + infrastructure cost divided by active client count) increases by more than 20% comparing the current calendar month-to-date to the previous complete calendar month, and the platform has at least 3 active clients, THE Alert_Engine SHALL generate a trend alert "Unit economics deteriorating"
3. WHEN the average avatar karma growth rate (total karma gained across all active avatars divided by active avatar count, measured as a 30-day delta) declines by more than 30% compared to the previous 30-day period, and at least 5 avatars have karma tracking data in both periods, THE Alert_Engine SHALL generate a trend alert "Avatar authority growth slowing"
4. WHEN the ratio of frozen-to-active avatars increases by at least 5 percentage points week-over-week for 3 consecutive weeks, THE Alert_Engine SHALL generate a trend alert "Fleet attrition accelerating"
5. THE RAMP_Agent SHALL compute weekly trend scores on a 0-100 scale (where 50 represents stable, above 50 represents improvement, below 50 represents degradation) every Sunday at 04:00 (Asia/Jerusalem) for: LLM cost efficiency (cost per approved comment), pipeline throughput (comments posted per day), avatar fleet health (percentage of non-frozen active avatars), and client satisfaction (review approval rate across all clients)
6. IF fewer than 20 data points exist for any trend metric in the analysis window, THEN THE Alert_Engine SHALL skip that trend computation and log an insufficient-data event instead of generating a potentially misleading alert

### Requirement 10: Economic Intelligence

**User Story:** As the Platform Owner, I want to understand the economics of every operation, so that I can optimize margins and make informed pricing decisions.

#### Acceptance Criteria

1. THE Economics_Engine SHALL calculate Cost_Per_Client daily (by 02:00 local time for the previous day), broken down by: LLM scoring, LLM generation, LLM persona selection, LLM editing, proxy fees, infrastructure share (computed as total fixed infrastructure cost divided equally among active clients for that day), with all cost values stored to 4 decimal places
2. THE Economics_Engine SHALL calculate cost per discovery as the sum of LLM costs for a single "engage" thread: scoring call + persona selection call + comment generation call + comment editing call, attributed to the client who triggered the engagement
3. THE Economics_Engine SHALL calculate cost per avatar per day, broken down by: posting cost (proxy fee per posted comment), content generation cost (all LLM calls where the avatar was selected), health monitoring cost (shadowban check + CQS check + profile analytics snapshot calls attributed to that avatar)
4. THE Economics_Engine SHALL track daily, weekly, and monthly totals for: total LLM spend, total infrastructure spend, total proxy spend, total revenue (derived from each client's plan_type monthly price divided by days in period), gross margin percentage (rounded to 2 decimal places, calculated as (revenue - total costs) / revenue x 100)
5. WHEN a single client's daily cost exceeds 3x the average daily cost across all active clients, THE Economics_Engine SHALL flag that client as "high-cost outlier" and include a breakdown showing: the client's cost per category (scoring, generation, persona, editing, proxy), the average cost per category, and which category contributed the largest absolute deviation
6. THE Economics_Engine SHALL identify the top 3 most expensive operation types each week (where operation type is one of: scoring, persona selection, generation, editing, hobby generation, health checks, proxy posting) ranked by total spend, and for each list the total cost, call count, and cost-per-call for that week
7. THE Economics_Engine SHALL calculate the break-even point per client (minimum monthly revenue to cover that client's variable costs, where variable costs = LLM spend + proxy fees for that client) and update it weekly every Monday by 03:00 local time
8. IF cost data is incomplete for a given day (AIUsageLog records are missing for one or more pipeline runs that executed successfully), THEN THE Economics_Engine SHALL mark that day's calculations as "partial" and include the percentage of expected pipeline runs that have cost records

### Requirement 11: Cost Optimization Suggestions

**User Story:** As the Platform Owner, I want the Agent to proactively suggest cost savings, so that I maintain healthy margins as the platform scales.

#### Acceptance Criteria

1. WHEN an avatar's generated comments have a rejection rate (rejected drafts divided by total drafts) above 50% for 7 consecutive days, THE Economics_Engine SHALL suggest reducing generation frequency for that avatar by 50% of its current allocation
2. WHEN a subreddit produces zero "engage"-tagged threads across all clients for 14 consecutive days, THE Economics_Engine SHALL suggest deactivating that subreddit to save scraping and scoring costs
3. WHEN the Economics_Engine performs its daily cost evaluation, IF a client's trailing-7-day average LLM cost exceeds 40% of their plan's monthly subscription revenue, THEN THE Economics_Engine SHALL flag that client for pricing review
4. WHEN a cheaper LLM model achieves an approval rate within 5 percentage points of the current model on the same task over a minimum of 100 completed drafts within a 14-day window, THE Economics_Engine SHALL suggest the model switch with projected monthly savings in dollars
5. THE Economics_Engine SHALL estimate monthly savings in dollars for each suggested optimization and rank suggestions in descending order by estimated dollar savings
6. THE Economics_Engine SHALL only emit a suggestion when the estimated monthly savings exceeds $5
7. WHEN a new cost optimization suggestion is generated, THE Economics_Engine SHALL surface it on the admin dashboard and record it with a timestamp, affected entity identifier, suggestion type, and estimated monthly savings

### Requirement 12: Autonomous Actions — Service Recovery

**User Story:** As the Platform Owner, I want the Agent to fix common issues autonomously, so that the platform self-heals without waking me up.

#### Acceptance Criteria

1. WHEN the Celery worker fails to respond to a heartbeat check for 120 consecutive seconds and the pipeline has pending tasks, THE Action_Executor SHALL restart the worker process automatically
2. WHEN Redis memory usage exceeds 90%, THE Action_Executor SHALL flush expired keys and task results older than 1 hour
3. WHEN a Docker container exits with a non-zero exit code or terminates without a preceding user-initiated stop command, THE Action_Executor SHALL restart it with the same configuration within 60 seconds
4. WHEN disk usage exceeds 85%, THE Action_Executor SHALL execute log rotation and remove Docker build cache
5. THE Action_Executor SHALL log every autonomous action with: timestamp, trigger condition, action taken, outcome, and rollback plan
6. IF an autonomous recovery action fails twice consecutively, THEN THE Action_Executor SHALL stop retrying and send a notification to the Platform Owner via the configured alerting channel within 30 seconds of the second failure
7. THE Action_Executor SHALL check all recovery trigger conditions (worker heartbeat, Redis memory, container status, disk usage) at intervals no longer than 60 seconds
8. IF disk usage remains above 85% after log rotation and Docker build cache removal, THEN THE Action_Executor SHALL escalate to the Platform Owner via the configured alerting channel indicating insufficient disk space

### Requirement 13: Autonomous Actions — Pipeline Management

**User Story:** As the Platform Owner, I want the Agent to manage routine pipeline adjustments, so that client delivery remains consistent.

#### Acceptance Criteria

1. WHEN the scrape queue has more than 10 subreddits not scraped within 2x their configured scrape_freshness_window_hours, THE Action_Executor SHALL move those subreddits to the front of the scrape priority queue
2. WHEN a single avatar accumulates 3 consecutive posting failures, THE Action_Executor SHALL freeze that avatar with reason "consecutive_failures" and log the freeze action with the 3 failure timestamps
3. WHEN a scheduled pipeline run (08:00 or 14:00) fails due to a transient error (timeout, connection reset, or HTTP 5xx from LLM provider), THE Action_Executor SHALL retry the pipeline run once after a 5-minute delay
4. IF the retry also fails, THEN THE Action_Executor SHALL record the failure and include it in the next short-term alert cycle without further automatic retries
5. WHEN an avatar reaches its daily posting cap before 16:00 local time and approved drafts remain in that client's queue, THE Action_Executor SHALL redistribute up to 3 of those drafts to other eligible avatars assigned to the same client that have remaining daily cap
6. WHEN an avatar's proxy returns 3 or more connection errors within a 1-hour window, THE Action_Executor SHALL set that avatar's posting_mode to "paused" and generate a short-term alert indicating proxy replacement is needed

### Requirement 14: Autonomous Actions — Resource Optimization

**User Story:** As the Platform Owner, I want the Agent to optimize resource usage within safe boundaries, so that the platform runs efficiently.

#### Acceptance Criteria

1. WHEN Celery task queue depth exceeds 50 pending tasks, THE Action_Executor SHALL increase worker concurrency by 1, up to a maximum of 4 concurrent workers (constrained by 4 GB RAM)
2. WHEN all Celery workers have processed zero tasks for more than 30 minutes, THE Action_Executor SHALL decrease worker concurrency by 1, down to a minimum of 1 worker
3. WHEN LLM API latency exceeds 10 seconds average over a 15-minute window, THE Action_Executor SHALL switch to the next model in the MODEL_FALLBACK_CHAIN for the affected operation (scoring or generation)
4. WHEN LLM API latency for the primary model returns below 5 seconds average over a 15-minute window after a fallback switch, THE Action_Executor SHALL revert to the primary model configuration
5. THE Action_Executor SHALL enforce data retention once daily at 02:00: mark activity_events older than 90 days as archived (excluded from queries), and delete reddit_threads records with no associated comment_drafts that are older than 180 days, processing a maximum of 1000 records per execution
6. WHEN a scoring batch produces all "skip" results for a subreddit 3 times consecutively, THE Action_Executor SHALL double the scoring interval for that subreddit (from default 12 hours to 24 hours, capped at a maximum of 72 hours)
7. WHILE system CPU usage exceeds 80% sustained for 10 minutes, THE Action_Executor SHALL skip the following non-critical scheduled tasks until CPU drops below 70%: profile-analytics-snapshots-daily, karma-tracking-4h, repurpose-scrape-weekly, compute-daily-performance-metrics, and continuous-discovery-weekly
8. IF a worker concurrency increase causes system memory usage to exceed 90%, THEN THE Action_Executor SHALL immediately revert the concurrency change and log the rollback

### Requirement 15: Authority Framework

**User Story:** As the Platform Owner, I want clear boundaries on what the Agent can and cannot do, so that I trust it to operate without supervision.

#### Acceptance Criteria

1. THE Authority_Framework SHALL define three permission levels: "autonomous" (no human approval needed), "confirmation_required" (Agent proposes, human approves), "forbidden" (Agent cannot perform)
2. THE Authority_Framework SHALL classify as "autonomous": restart services, freeze unhealthy avatars, rotate logs, flush cache, retry failed tasks, adjust worker concurrency, enforce data retention
3. THE Authority_Framework SHALL classify as "confirmation_required": deactivate a client, unfreeze an avatar, change LLM model selection, modify posting daily caps, change pipeline schedules, add or remove subreddits from a client
4. THE Authority_Framework SHALL classify as "forbidden": delete client data, modify billing/pricing, access encrypted credentials (passwords, tokens), push code changes, modify infrastructure (droplet resize, DNS), create or delete database tables
5. IF the RAMP_Agent attempts to perform a "forbidden" action, THEN THE Authority_Framework SHALL block execution, log the blocked attempt in the audit log, and display an error message indicating the action is forbidden and cannot be performed
6. WHEN the RAMP_Agent proposes a "confirmation_required" action, THE RAMP_Agent SHALL present to the Platform Owner the action name, affected entity, rationale (1-3 sentences explaining why), expected impact (what will change and scope of affected records), and an approve/reject interface
7. THE Authority_Framework SHALL log all autonomous actions and all approval/rejection decisions in the audit log including: timestamp, action name, permission level, affected entity identifier, actor (Agent or Platform Owner), and outcome (executed, approved, rejected, or blocked)
8. IF the Platform Owner does not respond to a "confirmation_required" escalation within 4 hours, THEN THE RAMP_Agent SHALL re-escalate by sending a repeated notification via an additional channel (push notification if original was in-app, or in-app banner if original was push)
9. IF the Platform Owner does not respond to a re-escalated "confirmation_required" action within 8 hours of the original escalation, THEN THE RAMP_Agent SHALL mark the action as "expired", log the expiration in the audit log, and take no further action on that request
10. IF the RAMP_Agent encounters an action not explicitly listed in the "autonomous", "confirmation_required", or "forbidden" classifications, THEN THE Authority_Framework SHALL treat the action as "confirmation_required" by default

### Requirement 16: Daily Briefing

**User Story:** As the Platform Owner, I want a concise daily summary every morning, so that I understand the platform state in 2 minutes.

#### Acceptance Criteria

1. THE Briefing_Service SHALL generate a daily briefing at 08:30 local time (Asia/Jerusalem) and deliver it via Telegram
2. THE Briefing_Service SHALL include in the daily briefing: Health_Score, active clients count, active avatars count, total posts in last 24h, total errors in last 24h, LLM cost in last 24h, revenue-to-cost ratio, and the top risk item ranked by severity where severity is determined by the highest-scoring unresolved issue from: frozen avatars, Health_Score below 70, error rate above 5%, or pending confirmation items older than 12 hours
3. THE Briefing_Service SHALL include a "top 3 actions taken" section listing the 3 autonomous actions from the past 24 hours with the highest operational impact, ranked by: avatar freezes and unfreezes first, then pipeline kill-switch triggers, then phase promotions or demotions, then automated posting completions
4. THE Briefing_Service SHALL include up to 5 pending "confirmation_required" items that await the Platform Owner's decision, ordered by age descending, with a count of any additional items beyond 5
5. WHEN the platform had zero errors, zero frozen avatars, zero failed tasks, and zero pending confirmation_required items in the past 24 hours, THE Briefing_Service SHALL send a shortened "all clear" briefing containing only: Health_Score, active clients count, active avatars count, total posts in last 24h, and LLM cost in last 24h
6. THE Briefing_Service SHALL format the briefing for mobile readability using Telegram markdown, with the full briefing not exceeding 500 words and the "all clear" briefing not exceeding 150 words
7. IF Telegram delivery fails, THEN THE Briefing_Service SHALL retry delivery up to 3 times with 60-second intervals and log a system error event if all retries are exhausted

### Requirement 17: Weekly Report

**User Story:** As the Platform Owner, I want a weekly strategic overview, so that I can make informed decisions about the platform's direction.

#### Acceptance Criteria

1. THE Briefing_Service SHALL generate a weekly report every Sunday at 10:00 local time (Asia/Jerusalem) and store it as a Markdown document accessible from the admin panel
2. THE Briefing_Service SHALL include in the weekly report a week-over-week comparison of the following metrics: threads scraped, threads scored, drafts generated, drafts approved, drafts posted, total AI cost (USD), active avatars count, and frozen avatars count — each shown as current week value, previous week value, and percentage change
3. THE Briefing_Service SHALL classify each metric's week-over-week trend as "improving" (change favourable by more than 5%), "declining" (change unfavourable by more than 5%), or "stable" (change within plus/minus 5%), where favourable means higher for engagement metrics (threads, drafts, posts) and lower for cost metrics
4. THE Briefing_Service SHALL include a cost breakdown showing total AI cost per client for the reporting week, sorted descending by cost
5. THE Briefing_Service SHALL include an avatar fleet status summary showing: count by phase (Mentor, Phase 1, Phase 2, Phase 3), count by health status (active, limited, shadowbanned, suspended), and count of frozen avatars with freeze reasons
6. THE Briefing_Service SHALL include a top 3 and bottom 3 avatars list ranked by number of successfully posted comments (not removed) during the reporting week, showing avatar username, posted count, and removal count
7. THE Briefing_Service SHALL include economic projections: projected monthly AI cost extrapolated from the last 7 days of spending, projected margin based on total client subscription revenue minus projected cost, and client count needed to reach break-even (total cost equals total revenue)
8. THE Briefing_Service SHALL include a "recommendations" section with up to 3 suggested actions, each specifying the action description, the affected metric (cost, engagement, or risk), and the estimated magnitude of improvement (as a percentage or absolute value)
9. THE Briefing_Service SHALL include a scaling readiness assessment identifying the system component (from: database connections, Celery workers, Reddit API rate limits, LLM API budget, avatar capacity) projected to reach its defined capacity threshold first, and the estimated number of additional clients before that threshold is reached based on current per-client resource consumption
10. IF fewer than 14 days of historical data exist at report generation time, THEN THE Briefing_Service SHALL generate the report with available data and include a notice indicating that week-over-week comparisons are unavailable due to insufficient history

### Requirement 18: Notification Delivery

**User Story:** As the Platform Owner, I want notifications via Telegram, so that I can respond from my phone without opening the admin panel.

#### Acceptance Criteria

1. THE RAMP_Agent SHALL deliver all alerts classified as "critical" or "high" severity via Telegram bot message within 60 seconds of the triggering event
2. THE RAMP_Agent SHALL support interactive Telegram commands and respond within 10 seconds: `/status` (current Health_Score and system state), `/cost` (today's total LLM and infrastructure spend in USD), `/fleet` (count of active, frozen, and unhealthy avatars per client), `/approve {id}` (approve pending action by ID), `/reject {id}` (reject pending action by ID)
3. IF the Platform Owner sends an unrecognized command or an invalid argument (non-existent ID, malformed input), THEN THE RAMP_Agent SHALL respond with an error message indicating the issue and listing available commands
4. WHEN the Platform Owner sends `/silence {duration}`, THE RAMP_Agent SHALL suppress alerts classified below "high" severity for the specified duration, where duration is expressed as an integer followed by "m" or "h" (e.g., "30m", "2h"), up to a maximum of 8 hours
5. THE RAMP_Agent SHALL queue undelivered messages and retry delivery up to 3 times with exponential backoff (initial delay 30 seconds, doubling on each retry), and discard messages that remain undeliverable after the final retry while logging the failure
6. IF Telegram delivery fails for more than 30 minutes, THEN THE RAMP_Agent SHALL fall back to email notification and send a Telegram message indicating restored connectivity when Telegram delivery succeeds again
7. WHEN a Telegram command is received, THE RAMP_Agent SHALL verify that the sender's Telegram user ID matches the configured Platform Owner ID before executing the command, and reject unauthorized requests with no information disclosure

### Requirement 19: Admin Panel Integration

**User Story:** As the Platform Owner, I want to see the Agent's activity and insights within the existing admin panel, so that I have a unified operations view.

#### Acceptance Criteria

1. THE RAMP_Agent SHALL expose a dashboard widget on the admin panel showing: current Health_Score, active alerts count, last 5 autonomous actions, today's cost vs. budget, with data refreshed at intervals no greater than 60 seconds
2. THE RAMP_Agent SHALL provide a dedicated `/admin/agent` page with: alert history (rolling 7-day window), action log (rolling 7-day window), economic charts (daily cost and margin for the past 7 days), and metric trend graphs (7-day default, selectable up to 30 days)
3. THE RAMP_Agent SHALL provide a `/admin/agent/health-map` view showing all monitored components with status indicators updated within 60 seconds of the last health check: green (component Health_Score above 80), yellow (Health_Score 50-80), red (Health_Score below 50), or grey (no data received for more than 120 seconds)
4. THE RAMP_Agent SHALL allow the Platform Owner to configure alert thresholds (numeric bounds per metric), notification channel preferences (Telegram, email, or both per severity level), and authority overrides (promote or demote specific action types between autonomous and confirmation_required) from the admin panel, with changes taking effect within 60 seconds of saving
5. IF the Platform Owner enters an invalid configuration value (threshold outside the metric's valid range, or empty required field), THEN THE RAMP_Agent SHALL reject the save and display an error message indicating which field failed validation and the acceptable range
6. THE RAMP_Agent SHALL display autonomous action proposals (confirmation_required) as actionable cards showing: action description, affected component, risk level, and recommended deadline, with approve and reject buttons; proposals not acted upon within 24 hours SHALL be marked as expired and moved to the action log
7. WHEN the Platform Owner approves a confirmation_required proposal, THE RAMP_Agent SHALL execute the proposed action within 60 seconds and display the execution result (success or failure with reason) on the same card

### Requirement 20: Scaling Intelligence

**User Story:** As the Platform Owner, I want the Agent to predict scaling bottlenecks, so that I can prepare infrastructure before problems occur.

#### Acceptance Criteria

1. THE RAMP_Agent SHALL maintain a capacity model that estimates maximum supportable clients given current infrastructure, recalculated weekly every Monday at 03:00 (Asia/Jerusalem), across 5 dimensions: CPU (based on per-client average CPU consumption), memory (based on per-client average memory footprint), database connections (based on per-client average connection usage), Reddit API rate (based on per-client average API calls per minute), and LLM budget (based on per-client average daily LLM cost vs. configured budget ceiling)
2. WHEN current utilization exceeds 70% of estimated capacity on any of the 5 dimensions, THE RAMP_Agent SHALL generate a scaling advisory specifying the affected dimension, current utilization percentage, estimated maximum clients, and recommended action
3. THE RAMP_Agent SHALL project time-to-capacity-limit for each dimension based on client growth rate (computed as change in active client count over the trailing 30 days), expressed as estimated days until 90% capacity is reached
4. THE RAMP_Agent SHALL maintain a scaling playbook as a structured document (stored in the database) with one entry per capacity dimension, each containing: dimension name, current threshold, upgrade action description, estimated cost of upgrade, estimated capacity gain (in additional clients), and link to relevant documentation or provider console
5. WHEN the platform reaches 80% capacity on any critical dimension, THE RAMP_Agent SHALL present the relevant scaling playbook entry as a "confirmation_required" action to the Platform Owner with the estimated cost and capacity gain

### Requirement 21: Silent Failure Detection

**User Story:** As the Platform Owner, I want the Agent to find problems that produce no errors, so that quality doesn't degrade silently over months.

#### Acceptance Criteria

1. WHEN the current week's generation approval rate (count of drafts approved or posted divided by total drafts generated) drops more than 20 percentage points below the 4-week rolling average for the same client, THE RAMP_Agent SHALL flag a "silent quality drift" finding for that client
2. WHEN a subreddit that averaged 3 or more new threads per scrape over its last 10 scrapes returns zero new threads (posts_new = 0) for 3 consecutive scrapes, THE RAMP_Agent SHALL flag a "phantom scraping" finding for that subreddit
3. WHEN the percentage of threads scored as "engage" for a client increases by more than 15 percentage points week-over-week, AND the average karma of that client's posted comments over the same period has not increased, THE RAMP_Agent SHALL flag a "scoring inflation" finding for that client
4. IF the self-learning loop has not captured any new edit records for an avatar for more than 14 days, AND that avatar has had at least 5 drafts reviewed (approved, rejected, or edited) during those 14 days, THEN THE RAMP_Agent SHALL flag a "stale learning" finding for that avatar
5. WHEN an avatar assigned to at least one active client has received no pipeline activity (no scoring, generation, or posting events) for more than 7 days, AND the avatar is not frozen AND its warming_phase is not 0 (Mentor), THE RAMP_Agent SHALL flag an "orphaned avatar" finding for that avatar
6. THE RAMP_Agent SHALL run all silent failure detection checks once per day at a configured time, and IF one or more findings are detected, THEN THE RAMP_Agent SHALL record each finding as an ActivityEvent with category "silent_failure" and include a summary of all findings in the daily operations report visible on the admin dashboard

### Requirement 22: Agent Self-Monitoring

**User Story:** As the Platform Owner, I want the Agent to monitor its own health, so that I know if the Agent itself has a problem.

#### Acceptance Criteria

1. THE RAMP_Agent SHALL emit a heartbeat signal every 60 seconds that records connectivity status for all critical dependencies (database, Redis, task queue) and an overall health status of HEALTHY, DEGRADED, or ERROR
2. IF the RAMP_Agent's heartbeat task execution time exceeds 30 seconds, THEN THE RAMP_Agent SHALL log a self-degradation warning that includes the actual execution duration and the names of any dependency checks that timed out
3. THE RAMP_Agent SHALL track its own resource consumption (resident memory in MB, CPU time per heartbeat cycle in milliseconds) and persist each measurement alongside the heartbeat record
4. IF the RAMP_Agent's average resource consumption over a rolling 7-day window exceeds 150% of the average from the preceding 7-day window, THEN THE RAMP_Agent SHALL emit an activity event of type "agent_resource_alert" containing the current average, the baseline average, and the percentage increase
5. IF no heartbeat record has been written for 5 consecutive minutes, THEN the container orchestrator SHALL restart the RAMP_Agent process automatically
6. IF the RAMP_Agent fails to produce a heartbeat within 3 minutes after a restart, THEN THE system SHALL log a critical alert activity event of type "agent_restart_failed" and cease further automatic restart attempts until manual intervention
7. THE RAMP_Agent SHALL expose a self-diagnostic endpoint that reports: last heartbeat completion timestamp, last heartbeat duration in milliseconds, metrics collection success rate as a percentage over the trailing 24 hours, alert delivery success rate as a percentage over the trailing 24 hours, and action execution success rate as a percentage over the trailing 24 hours
