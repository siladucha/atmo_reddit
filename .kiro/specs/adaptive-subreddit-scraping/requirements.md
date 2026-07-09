# Requirements Document

## Introduction

Adaptive Subreddit Scraping replaces the fixed-interval scraping model with a dynamic scheduler that adjusts per-subreddit scrape frequency based on historical yield, client plan tier, and Reddit API budget constraints. The system learns from recent scrape results (posts_new per scrape) and tunes intervals to maximize content freshness for active subreddits while minimizing wasted API calls on inactive ones.

## Glossary

- **Scheduler**: The adaptive scheduling logic inside `queue_tick` that determines which subreddit to scrape next and computes per-subreddit intervals
- **Yield**: The number of new (previously unseen) posts returned by a single scrape, stored as `posts_new` in `ScrapeLog`
- **Activity_Tier**: A classification of subreddit activity level (hot, moderate, low, dead) derived from rolling average yield over recent scrapes
- **Scrape_Budget**: The maximum number of Reddit API requests per minute allocated to scraping operations, reserving capacity for health checks, karma tracking, and other operations
- **Cooldown_Period**: The minimum time between consecutive scrapes of the same subreddit, dynamically computed by the Scheduler
- **Plan_Tier**: The client subscription level (seed, starter, growth, scale) which influences scrape priority weighting
- **Yield_Window**: The number of recent scrapes used to compute average yield for a subreddit (rolling window)
- **Dead_Streak**: The count of consecutive scrapes returning zero new posts for a subreddit
- **Subreddit_Scrape_Config**: A per-subreddit record storing computed interval, activity tier, yield metrics, and scheduling metadata

## Requirements

### Requirement 1: Activity Tier Classification

**User Story:** As a system operator, I want subreddits automatically classified by activity level, so that scraping frequency adapts to actual posting volume.

#### Acceptance Criteria

1. WHEN the Scheduler computes the activity tier for a subreddit, THE Scheduler SHALL use the average `posts_new` from the last 6 scrapes (Yield_Window) to determine the Activity_Tier
2. WHEN the average yield is greater than 10 posts per scrape, THE Scheduler SHALL classify the subreddit as Activity_Tier "hot"
3. WHEN the average yield is between 3 and 10 posts per scrape (inclusive), THE Scheduler SHALL classify the subreddit as Activity_Tier "moderate"
4. WHEN the average yield is between 1 and 2 posts per scrape (inclusive), THE Scheduler SHALL classify the subreddit as Activity_Tier "low"
5. WHEN the average yield is 0 posts for 3 or more consecutive scrapes (Dead_Streak >= 3), THE Scheduler SHALL classify the subreddit as Activity_Tier "dead"
6. WHEN a subreddit has fewer than 3 entries in ScrapeLog, THE Scheduler SHALL classify the subreddit as Activity_Tier "moderate" (default)

### Requirement 2: Dynamic Interval Computation

**User Story:** As a system operator, I want scrape intervals automatically adjusted per subreddit, so that hot subreddits get fresher data and dead subreddits waste fewer API calls.

#### Acceptance Criteria

1. WHEN a subreddit is classified as Activity_Tier "hot", THE Scheduler SHALL assign a Cooldown_Period of 2 hours
2. WHEN a subreddit is classified as Activity_Tier "moderate", THE Scheduler SHALL assign a Cooldown_Period of 4 hours
3. WHEN a subreddit is classified as Activity_Tier "low", THE Scheduler SHALL assign a Cooldown_Period of 8 hours
4. WHEN a subreddit is classified as Activity_Tier "dead", THE Scheduler SHALL assign a Cooldown_Period of 24 hours
5. WHEN a subreddit transitions from Activity_Tier "dead" back to any other tier (yield > 0 on next scrape), THE Scheduler SHALL recalculate the Cooldown_Period based on the new classification
6. THE Scheduler SHALL store the computed Cooldown_Period on the Subreddit_Scrape_Config record for each subreddit

### Requirement 3: Client Plan Tier Priority Weighting

**User Story:** As a business operator, I want Scale-tier clients to receive faster subreddit refresh, so that higher-paying clients get better content freshness.

#### Acceptance Criteria

1. WHEN computing the effective Cooldown_Period for a subreddit, THE Scheduler SHALL apply a plan tier multiplier to reduce the interval for higher-tier clients
2. WHEN a subreddit is assigned to a client with Plan_Tier "scale", THE Scheduler SHALL multiply the base Cooldown_Period by 0.5 (halving the interval)
3. WHEN a subreddit is assigned to a client with Plan_Tier "growth", THE Scheduler SHALL multiply the base Cooldown_Period by 0.75
4. WHEN a subreddit is assigned to a client with Plan_Tier "starter" or "seed", THE Scheduler SHALL use the base Cooldown_Period without modification (multiplier 1.0)
5. WHEN a subreddit is shared across multiple clients with different Plan_Tiers, THE Scheduler SHALL use the highest-priority (lowest multiplier) Plan_Tier among all active assignments
6. THE Scheduler SHALL enforce a minimum Cooldown_Period of 1 hour regardless of plan tier multiplier

### Requirement 4: Reddit API Budget Management

**User Story:** As a system operator, I want scraping to stay within a safe API budget, so that health checks, karma tracking, CQS, and presence scanning always have API capacity available.

#### Acceptance Criteria

1. THE Scheduler SHALL limit scraping operations to a maximum of 40 requests per minute (reserving 20 req/min for health checks, karma tracking, CQS, and presence scanning)
2. WHEN the scraping rate limiter count reaches 40 requests in the current 60-second window, THE Scheduler SHALL defer all pending scrape dispatches until the window resets
3. WHEN multiple subreddits are due for scraping simultaneously, THE Scheduler SHALL prioritize by: (a) Plan_Tier priority (highest-tier client first), then (b) staleness (oldest last_scraped_at first)
4. THE Scheduler SHALL track the current scraping request count via Redis sliding window counter (existing ScrapeRateLimiter)
5. IF the system detects a Reddit 429 response, THEN THE Scheduler SHALL activate a 5-minute global scraping backoff (existing behavior preserved)

### Requirement 5: Dead Subreddit Backoff and Pause

**User Story:** As a system operator, I want dead subreddits to back off exponentially and eventually pause, so that API budget is not wasted on subreddits with no activity.

#### Acceptance Criteria

1. WHEN a subreddit has Dead_Streak of 3-5 consecutive zero-yield scrapes, THE Scheduler SHALL assign a Cooldown_Period of 24 hours
2. WHEN a subreddit has Dead_Streak of 6 or more consecutive zero-yield scrapes, THE Scheduler SHALL assign a Cooldown_Period of 48 hours
3. WHEN a subreddit accumulates 7 or more calendar days of consecutive zero-yield scrapes, THE Scheduler SHALL pause scraping for that subreddit and emit an activity event of type "scrape_paused" with metadata including the subreddit name and dead streak count
4. WHILE a subreddit is in paused state, THE Scheduler SHALL skip the subreddit during queue_tick candidate selection
5. WHEN an operator manually unpauses a paused subreddit via the admin UI, THE Scheduler SHALL reset the Dead_Streak to 0 and resume scraping with the default "moderate" Cooldown_Period of 4 hours
6. WHEN a paused subreddit is unpaused, THE Scheduler SHALL emit an activity event of type "scrape_resumed"

### Requirement 6: Yield Metrics Tracking

**User Story:** As a system operator, I want per-subreddit yield metrics visible on the admin dashboard, so that I can monitor scraping efficiency and identify subreddits that need attention.

#### Acceptance Criteria

1. THE Scheduler SHALL store the following metrics on Subreddit_Scrape_Config: current Activity_Tier, current Cooldown_Period (hours), average yield (rolling 6-scrape window), Dead_Streak count, last tier change timestamp, and is_paused flag
2. WHEN a subreddit's Activity_Tier changes, THE Scheduler SHALL record the previous tier and timestamp in a tier_history JSONB field (FIFO, max 10 entries)
3. WHEN the Scheduler computes a new Cooldown_Period, THE Scheduler SHALL emit an activity event of type "scrape_interval_changed" only when the computed interval differs from the previous value
4. THE Scheduler SHALL expose yield metrics via the existing admin subreddit list endpoint, including Activity_Tier badge and current interval display

### Requirement 7: Transition from Fixed Interval

**User Story:** As a system operator, I want the adaptive scheduler to coexist with the existing fixed-interval setting, so that I can enable it gradually without disrupting the current system.

#### Acceptance Criteria

1. THE Scheduler SHALL read a system setting "adaptive_scraping_enabled" (default: "false") to determine whether adaptive scheduling is active
2. WHILE "adaptive_scraping_enabled" is "false", THE Scheduler SHALL use the existing `scrape_freshness_window_hours` setting as a fixed interval for all subreddits (current behavior preserved)
3. WHILE "adaptive_scraping_enabled" is "true", THE Scheduler SHALL use the per-subreddit Cooldown_Period computed from Activity_Tier and Plan_Tier multipliers
4. WHEN "adaptive_scraping_enabled" is toggled from "false" to "true" for the first time, THE Scheduler SHALL initialize Subreddit_Scrape_Config records for all active subreddits with Activity_Tier "moderate" and Cooldown_Period of 4 hours
5. IF Subreddit_Scrape_Config does not exist for a subreddit when adaptive scheduling is enabled, THEN THE Scheduler SHALL create a default record with Activity_Tier "moderate" and Cooldown_Period of 4 hours

### Requirement 8: Queue Tick Integration

**User Story:** As a system operator, I want the adaptive scheduler to work within the existing queue_tick architecture, so that no changes to Celery Beat scheduling or worker dispatch are needed.

#### Acceptance Criteria

1. THE Scheduler SHALL determine subreddit staleness by comparing `Subreddit.last_scraped_at` against the per-subreddit Cooldown_Period (instead of the global `scrape_freshness_window_hours`)
2. WHEN selecting candidates in queue_tick, THE Scheduler SHALL order subreddits by: (a) overdue ratio (time since last scrape / Cooldown_Period) descending, then (b) Plan_Tier priority descending
3. THE Scheduler SHALL dispatch at most 1 subreddit per queue_tick invocation (existing single-dispatch-per-tick model preserved)
4. WHEN a scrape completes, THE Scheduler SHALL update the Subreddit_Scrape_Config with new yield data and recompute Activity_Tier and Cooldown_Period
5. THE Scheduler SHALL compute tier and interval within the queue_tick task without adding new Celery Beat tasks or additional periodic schedules
