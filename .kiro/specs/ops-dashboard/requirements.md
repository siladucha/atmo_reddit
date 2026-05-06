# Requirements Document

## Introduction

Extended operational dashboard for the ThreddOps Reddit marketing SaaS platform. The dashboard provides a unified view of all system operations: queue health, avatar/account status, subreddit collection metrics, Reddit API health, LLM usage and costs, audit/activity events, and emergency controls. The architecture is subreddit-centric and designed for future AWS migration (PostgreSQL → RDS, Redis → ElastiCache, Docker Compose → ECS/Fargate).

## Glossary

- **Dashboard**: The extended admin panel at `/admin/` providing unified operational visibility
- **Queue_Monitor**: The component that tracks Celery task queue states (pending, running, failed, dead-letter)
- **Avatar_Panel**: The component displaying per-account status, phase, freeze state, limits, and Reddit API errors
- **Scrape_Tracker**: The component tracking subreddit collection freshness, thread counts, errors, and scheduling
- **Reddit_Health_Monitor**: The component displaying Reddit API rate limits, request counts, errors, circuit breaker status, and per-account bans
- **LLM_Usage_Panel**: The component displaying AI/LLM scoring and generation costs, daily budgets, and rejection counts
- **Audit_Log_Viewer**: The component displaying activity events with filtering and search capabilities
- **Emergency_Controls**: The set of administrative actions for immediate system intervention (global shutdown, freeze, blacklist, pause)
- **Circuit_Breaker**: A pattern that stops requests to a failing service after a threshold of consecutive failures, resuming after a cooldown period
- **Dead_Letter_Queue**: A storage location for tasks that have failed all retry attempts
- **Freeze_State**: A per-avatar flag that prevents the avatar from being selected for any pipeline activity
- **Blacklist**: A per-subreddit flag that excludes the subreddit from all scraping and engagement activity
- **Warming_Phase**: The avatar maturity stage (Phase 1: credibility building, Phase 2: content seeding, Phase 3: brand integration)

## Requirements

### Requirement 1: Queue Status Monitoring

**User Story:** As an operator, I want to see the real-time status of all processing queues, so that I can identify bottlenecks and failures before they impact pipeline throughput.

#### Acceptance Criteria

1. THE Queue_Monitor SHALL display task counts grouped by pipeline stage (scraping, scoring, generation, publishing)
2. WHEN the Dashboard loads, THE Queue_Monitor SHALL show the current count of tasks in each state: pending, running, failed, dead-letter
3. THE Queue_Monitor SHALL display a health indicator (ok, warning, critical) for each pipeline stage based on failed and dead-letter task counts
4. WHEN a pipeline stage has more than 5 failed tasks, THE Queue_Monitor SHALL display a warning indicator for that stage
5. WHEN a pipeline stage has more than 0 dead-letter tasks, THE Queue_Monitor SHALL display a critical indicator for that stage
6. THE Queue_Monitor SHALL auto-refresh queue counts every 30 seconds via HTMX polling
7. WHEN a task transitions to the failed state, THE Queue_Monitor SHALL display the failure timestamp and error summary for that task

### Requirement 2: Avatar / Account Status Panel

**User Story:** As an operator, I want to see the detailed status of each Reddit avatar account, so that I can monitor account health and intervene when accounts are at risk.

#### Acceptance Criteria

1. THE Avatar_Panel SHALL display each avatar with: reddit_username, active status, warming_phase, freeze_state, freeze_reason, karma (post and comment), last_health_check timestamp
2. WHILE an avatar is in freeze_state, THE Avatar_Panel SHALL display the freeze reason and the timestamp when the freeze was applied
3. THE Avatar_Panel SHALL display per-avatar rate limit usage and the count of Reddit API errors in the last 24 hours
4. WHEN an avatar's reddit_status is "shadowbanned" or "suspended", THE Avatar_Panel SHALL highlight that avatar row with a critical indicator
5. THE Avatar_Panel SHALL display the last 5 actions performed by each avatar (comment posted, draft generated, health check) with timestamps
6. THE Avatar_Panel SHALL support filtering by: warming_phase, freeze_state, reddit_status, and client assignment
7. THE Avatar_Panel SHALL support sorting by: username, karma, last_health_check, warming_phase

### Requirement 3: Subreddit Collection Tracking

**User Story:** As an operator, I want to monitor subreddit scraping activity, so that I can ensure data freshness and identify collection failures.

#### Acceptance Criteria

1. THE Scrape_Tracker SHALL display for each active subreddit: subreddit_name, last_scraped_at, posts_found (last scrape), posts_new (last scrape), errors (last scrape), next scheduled scrape time, blacklist status
2. WHEN a subreddit has not been scraped in more than 24 hours, THE Scrape_Tracker SHALL mark that subreddit as stale with a visual indicator
3. WHEN a subreddit's last scrape resulted in an error, THE Scrape_Tracker SHALL display the error message and highlight the row
4. THE Scrape_Tracker SHALL display aggregate statistics: total active subreddits, stale count, never-scraped count, average scrape duration
5. THE Scrape_Tracker SHALL group subreddits by client assignment and display the client name alongside each subreddit
6. THE Scrape_Tracker SHALL support filtering by: client, stale status, blacklist status, error state
7. WHEN a subreddit is blacklisted, THE Scrape_Tracker SHALL display the blacklist reason and the timestamp when it was blacklisted

### Requirement 4: Reddit API Health Monitoring

**User Story:** As an operator, I want to monitor Reddit API health across all accounts, so that I can detect rate limiting, bans, and service degradation before they halt the pipeline.

#### Acceptance Criteria

1. THE Reddit_Health_Monitor SHALL display global Reddit API metrics: total requests (last hour), error rate percentage, average response time, p95 response time
2. THE Reddit_Health_Monitor SHALL display the current rate limit state: remaining requests, used requests, seconds until reset, usage percentage
3. THE Reddit_Health_Monitor SHALL display a color-coded gauge (green < 60%, yellow 60-80%, red > 80%) for rate limit usage
4. THE Reddit_Health_Monitor SHALL display error counts grouped by type: rate_limited, forbidden, timeout, other
5. WHEN the circuit breaker is open for any account, THE Reddit_Health_Monitor SHALL display the affected account, the trigger reason, and the estimated recovery time
6. THE Reddit_Health_Monitor SHALL display per-avatar Reddit API error counts and ban status for the last 24 hours
7. WHEN the Reddit API error rate exceeds 20%, THE Reddit_Health_Monitor SHALL display a critical status indicator

### Requirement 5: LLM Usage and Cost Tracking

**User Story:** As an operator, I want to monitor LLM usage and costs per client and operation type, so that I can control spending and detect budget overruns.

#### Acceptance Criteria

1. THE LLM_Usage_Panel SHALL display aggregate LLM metrics: total calls, total cost (USD), average latency, error count for the selected time window
2. THE LLM_Usage_Panel SHALL display cost breakdown by operation type: scoring, persona_select, generation, editing
3. THE LLM_Usage_Panel SHALL display cost breakdown by client with each client's total cost and call count
4. THE LLM_Usage_Panel SHALL display cost breakdown by model (Claude Sonnet, Claude Haiku, Gemini Flash)
5. WHEN a client's daily LLM cost exceeds the configured daily budget, THE LLM_Usage_Panel SHALL display a budget exceeded warning for that client
6. THE LLM_Usage_Panel SHALL display the count of LLM requests rejected due to budget limits in the last 24 hours
7. THE LLM_Usage_Panel SHALL support time window selection: last hour, last 24 hours, last 7 days, last 30 days

### Requirement 6: Audit and Activity Event Viewer

**User Story:** As an operator, I want to browse and search the activity event log, so that I can investigate incidents and track system behavior over time.

#### Acceptance Criteria

1. THE Audit_Log_Viewer SHALL display activity events with columns: created_at, event_type, client_id, entity_type, entity_id, message, result/error
2. THE Audit_Log_Viewer SHALL support filtering by: date range, event_type, client_id, entity_type
3. THE Audit_Log_Viewer SHALL support text search across the message and metadata fields
4. THE Audit_Log_Viewer SHALL paginate results with 50 events per page
5. WHEN an event has an error in its metadata, THE Audit_Log_Viewer SHALL highlight that row with an error indicator
6. THE Audit_Log_Viewer SHALL support exporting filtered results as CSV
7. THE Audit_Log_Viewer SHALL display events in reverse chronological order by default

### Requirement 7: Emergency Controls

**User Story:** As an operator, I want immediate access to emergency controls, so that I can halt dangerous operations within seconds when a risk is detected.

#### Acceptance Criteria

1. THE Emergency_Controls SHALL provide a global publishing shutdown button that prevents all comment and post publishing across all clients
2. WHEN the global publishing shutdown is activated, THE Emergency_Controls SHALL record an audit event with the operator identity and timestamp
3. THE Emergency_Controls SHALL provide a per-avatar freeze action that sets the avatar's freeze_state to true with a required freeze_reason
4. THE Emergency_Controls SHALL provide a per-subreddit blacklist action that sets the subreddit's blacklist status to true with a required reason
5. THE Emergency_Controls SHALL provide a per-client pause action that sets the client's is_active to false, halting all pipeline activity for that client
6. THE Emergency_Controls SHALL provide a stop-LLM-generation action that prevents all new AI scoring and generation tasks from being dispatched
7. WHEN any emergency control is activated, THE Dashboard SHALL display a persistent banner indicating the active emergency state and the operator who activated it
8. THE Emergency_Controls SHALL require a confirmation step before executing any emergency action
9. THE Emergency_Controls SHALL provide a corresponding deactivation action for each emergency control, also requiring confirmation and recording an audit event

### Requirement 8: Dashboard Layout and Navigation

**User Story:** As an operator, I want a well-organized dashboard with clear navigation, so that I can quickly access any operational view without confusion.

#### Acceptance Criteria

1. THE Dashboard SHALL render within the existing admin dark theme (admin_base.html) and follow the established Tailwind CSS styling conventions
2. THE Dashboard SHALL provide a top-level navigation with sections: Overview, Queues, Avatars, Subreddits, Reddit API, LLM Usage, Audit Log, Emergency
3. THE Dashboard SHALL load section content via HTMX partials so that navigation does not trigger full page reloads
4. THE Dashboard SHALL display a global status bar showing: active emergency states, next scheduled pipeline run, count of pending reviews
5. THE Dashboard SHALL be responsive and usable on screens 1024px wide and above
6. WHEN the Dashboard detects a critical condition (circuit breaker open, dead-letter tasks, shadowbanned avatar), THE Dashboard SHALL display a notification badge on the relevant navigation item

### Requirement 9: AWS Migration Readiness

**User Story:** As a developer, I want the dashboard architecture to be portable to AWS managed services, so that future migration requires minimal code changes.

#### Acceptance Criteria

1. THE Dashboard SHALL access all persistent data exclusively through SQLAlchemy ORM queries, enabling PostgreSQL → RDS migration without code changes
2. THE Dashboard SHALL access Celery queue state through the Celery inspection API and Redis connection abstracted via the configured broker URL, enabling Redis → ElastiCache migration without code changes
3. THE Dashboard SHALL structure all background metric collection as Celery tasks, enabling Docker Compose → ECS/Fargate migration without architectural changes
4. THE Dashboard SHALL emit structured log events for all emergency control activations and critical state changes, enabling future CloudWatch integration
5. THE Dashboard SHALL store no local filesystem state; all operational data SHALL reside in PostgreSQL or Redis

### Requirement 10: Real-Time Data Freshness

**User Story:** As an operator, I want dashboard data to refresh automatically, so that I see current system state without manually reloading the page.

#### Acceptance Criteria

1. THE Dashboard SHALL auto-refresh the queue status section every 30 seconds using HTMX polling
2. THE Dashboard SHALL auto-refresh the Reddit API health section every 60 seconds using HTMX polling
3. THE Dashboard SHALL auto-refresh the activity feed section every 60 seconds using HTMX polling
4. THE Dashboard SHALL display a "last updated" timestamp on each auto-refreshing section
5. WHEN a section fails to refresh (network error or server error), THE Dashboard SHALL display a stale-data indicator on that section and retry after 10 seconds
