# Requirements Document

## Introduction

This feature addresses the scalability challenge of providing fresh, actionable posting recommendations for a growing avatar fleet. Rather than designing a monolithic system for 100K avatars upfront, the architecture evolves through **four implementation phases**, each building on the previous one and introducing new infrastructure only when the scale demands it.

### Phased Scaling Roadmap

| Phase | Avatars | Subreddits | Key Addition | Infrastructure |
|-------|---------|------------|--------------|----------------|
| **Phase 1 (MVP)** | 100 | 1,000 | Simple queue improvements, daily plans, behavioral fingerprints | Celery + Redis + PostgreSQL (current) |
| **Phase 2** | 500 | 5,000 | Caching layer, batch scrape windows, scrape sharing | + Valkey/Redis cache |
| **Phase 3** | 2,000 | 100,000 | Sharding, multi-token, graceful degradation | + Shard partitioning |
| **Phase 4** | 10,000 | 1,000,000 | Stream processing, event-driven architecture | + Kafka/SQS FIFO |

### Design Principles

1. **Each phase is independently deployable** — Phase 1 ships on the current codebase with zero new infrastructure.
2. **Later phases extend, not replace** — Phase 2 adds caching around Phase 1 logic, not a rewrite.
3. **Scale triggers are explicit** — each phase defines when to transition to the next.
4. **Current system context**: `queue_tick` fires every 60–90s, picks most stale subreddit, 15 RPM Reddit API rate limit, 12h freshness window, Celery + Redis for task queue, PostgreSQL for all data, single Reddit API token.

## Glossary

- **Avatar_Action_Scheduler**: The orchestration service that determines which avatars need attention, what data they need refreshed, and when they should act. In Phase 1, this is a lightweight extension of `queue_tick`.
- **Avatar_Daily_Plan**: A computed schedule for a single avatar's day, containing time slots for posting actions, target subreddits, and content types allowed.
- **Activity_Window**: The time range during which an avatar is "awake" and may post. Derived from the avatar's timezone simulation and behavioral fingerprint.
- **Freshness_Demand**: A request indicating that a specific subreddit's data must be refreshed before a given deadline (the avatar's next posting slot).
- **Demand_Priority_Score**: A numeric score assigned to each Freshness_Demand, computed from: time until deadline, number of avatars waiting on this subreddit, and the avatar's phase urgency.
- **Avatar_Behavioral_Fingerprint**: A set of parameters defining an avatar's posting cadence, preferred times, response latency, and timezone.
- **Posting_Slot**: A specific time window within an avatar's Activity_Window when the avatar should perform a posting action.
- **Phase_Policy**: Content restriction rules per warming phase (Phase 1: max 3 comments/day hobby only; Phase 2: max 10 comments/day; Phase 3: all types with brand ramp-up).
- **Scrape_Sharing_Index**: A Redis-based lookup mapping each subreddit to all avatars that depend on it, enabling a single scrape to satisfy multiple avatars' Freshness_Demands.
- **Subreddit_Activity_Profile**: A statistical model of when a subreddit is most active (post volume by hour-of-day). Cached in Valkey (Phase 2+).
- **Rate_Budget_Allocator**: The component that distributes the global Reddit API rate limit across competing Freshness_Demands based on Demand_Priority_Score.
- **Batch_Scrape_Window**: A time period during which the system concentrates scraping for a cohort of avatars whose Activity_Windows are about to begin.
- **Tiered_Freshness**: A strategy where different data types have different freshness requirements — threads need 4–12h, karma needs 24–48h, activity profiles need 7 days.
- **Avatar_Urgency_Score**: A composite score indicating how urgently an avatar needs fresh data.
- **Karma_Freshness_Record**: Metadata tracking when karma was last verified for a specific avatar-subreddit pair.
- **Degradation_Level**: Progressive service reduction levels (0–3) when demand exceeds capacity.

---

## Phase 1: MVP (100 Avatars, 1,000 Subreddits)

**Goal:** Improve the existing `queue_tick` system with avatar-demand-driven prioritization, daily plans, and behavioral fingerprints. No new infrastructure — runs on current Celery + Redis + PostgreSQL stack.

**Scale trigger to Phase 2:** When avatar count exceeds 100 OR unique subreddits exceed 1,000 OR daily coverage drops below 90%.

### Requirement 1.1: Avatar Daily Plan Generation

**User Story:** As a system operator, I want each avatar to have a computed daily plan specifying when and where to post, so that posting actions are spread naturally across the avatar's activity window.

#### Acceptance Criteria

1. WHEN the daily planning cycle runs, THE Avatar_Action_Scheduler SHALL generate an Avatar_Daily_Plan for each active, non-frozen avatar.
2. THE Avatar_Daily_Plan SHALL contain between 1 and N Posting_Slots, where N equals the avatar's daily comment limit from Phase_Policy (3 for warming Phase 1, 10 for warming Phase 2/3).
3. WHEN generating Posting_Slots, THE Avatar_Action_Scheduler SHALL distribute them across the avatar's Activity_Window with minimum inter-slot gaps of 30 minutes and maximum gaps of 4 hours.
4. WHEN assigning subreddits to Posting_Slots, THE Avatar_Action_Scheduler SHALL select subreddits based on: karma deficit (subreddits where avatar needs more karma), and content type eligibility per Phase_Policy.
5. THE Avatar_Daily_Plan SHALL include a Freshness_Demand for each assigned subreddit, specifying the deadline by which thread data must be refreshed (at least 30 minutes before the Posting_Slot).
6. WHEN an avatar's Activity_Window spans midnight UTC, THE Avatar_Action_Scheduler SHALL handle the wrap-around correctly without splitting or duplicating Posting_Slots.
7. THE Avatar_Action_Scheduler SHALL apply jitter of ±15 minutes to each Posting_Slot to prevent detectable patterns across days.

### Requirement 1.2: Avatar Behavioral Fingerprint

**User Story:** As a system operator, I want each avatar to have a unique behavioral fingerprint that governs its posting cadence, so that posting patterns appear natural and non-uniform across the avatar fleet.

#### Acceptance Criteria

1. THE Avatar_Behavioral_Fingerprint SHALL define: timezone_offset (UTC offset simulating avatar's location), wake_hour (start of Activity_Window), sleep_hour (end of Activity_Window), peak_activity_hours (1–3 hours of highest posting probability), and response_latency_range (min/max minutes between seeing a thread and commenting).
2. WHEN an avatar is created, THE System SHALL generate a unique Avatar_Behavioral_Fingerprint with randomized parameters within realistic human ranges (wake: 06:00–10:00 local, sleep: 22:00–02:00 local, peak: 2–4 hour window).
3. THE Avatar_Action_Scheduler SHALL weight Posting_Slot placement toward the avatar's peak_activity_hours with 60% probability, distributing remaining slots across the full Activity_Window.
4. WHEN computing inter-slot gaps, THE Avatar_Action_Scheduler SHALL use the avatar's response_latency_range to vary gaps between 45 minutes and 3 hours, following a log-normal distribution.
5. THE Avatar_Behavioral_Fingerprint SHALL be stable across days (same avatar maintains consistent patterns) but allow weekly drift of ±30 minutes on wake/sleep times to simulate natural variation.

### Requirement 1.3: Demand-Driven Scrape Prioritization

**User Story:** As a system operator, I want the scraping queue to prioritize subreddits based on avatar demand rather than simple staleness, so that rate-limited API calls serve the avatars that need data most urgently.

#### Acceptance Criteria

1. WHEN the queue_tick selects the next subreddit to scrape, THE System SHALL rank subreddits by Demand_Priority_Score instead of simple staleness (last_scraped_at ASC).
2. THE Demand_Priority_Score SHALL be computed as: `(number_of_waiting_avatars × 10) + (100 / hours_until_earliest_deadline) + (phase_urgency_bonus)`, where phase_urgency_bonus is 50 for warming Phase 1 avatars and 20 for Phase 2/3.
3. WHEN no avatar has a pending Freshness_Demand for a subreddit, THE System SHALL assign that subreddit a baseline priority equal to its simple staleness score (hours since last scrape).
4. WHEN a single scrape completes, THE System SHALL resolve all Freshness_Demands from all avatars that depend on that subreddit, marking them as satisfied.
5. THE System SHALL ensure that no single subreddit consumes more than 20% of the hourly rate budget (max 3 scrapes/hour for one subreddit at 15 RPM).
6. WHEN the rate budget is exhausted for the current minute, THE System SHALL queue remaining demands for the next available minute without dropping them.

### Requirement 1.4: Avatar Urgency Scoring

**User Story:** As a system operator, I want the system to prioritize data refresh for avatars that need it most urgently, so that avatars close to posting or close to phase promotion get fresh data first.

#### Acceptance Criteria

1. THE Avatar_Urgency_Score SHALL be computed as a weighted sum of: hours_until_next_slot (weight: 40%, inverse — closer = higher), days_since_last_post (weight: 25%, more days = higher urgency), phase_promotion_proximity (weight: 20%, closer to promotion threshold = higher), and karma_deficit_ratio (weight: 15%, larger deficit = higher urgency).
2. WHEN two avatars depend on the same subreddit, THE System SHALL use the higher Avatar_Urgency_Score to set the Demand_Priority_Score for that subreddit.
3. WHEN an avatar has not posted for more than 3 days despite having available Posting_Slots, THE System SHALL boost its Avatar_Urgency_Score by 2x to prevent starvation.
4. THE System SHALL recompute Avatar_Urgency_Scores every 30 minutes to reflect changing conditions.
5. WHEN an avatar is frozen (is_frozen=true), THE System SHALL set its Avatar_Urgency_Score to 0 and exclude it from Freshness_Demand generation.

### Requirement 1.5: Tiered Freshness Strategy

**User Story:** As a system operator, I want different data types to have different freshness requirements, so that the system does not waste API calls refreshing data that changes infrequently.

#### Acceptance Criteria

1. THE System SHALL define three freshness tiers: thread_data (target: 4–12 hours), karma_data (target: 24–48 hours), and activity_profile (target: 7 days).
2. WHEN an avatar's Posting_Slot is within 2 hours, THE Avatar_Action_Scheduler SHALL require thread_data freshness of 4 hours or less for the target subreddit.
3. WHEN an avatar's Posting_Slot is more than 6 hours away, THE Avatar_Action_Scheduler SHALL accept thread_data freshness of up to 12 hours for the target subreddit.
4. WHEN karma_data is stale but thread_data is fresh, THE System SHALL still allow the avatar to proceed with posting using the last known karma value, logging a warning that karma may be outdated.
5. THE System SHALL schedule karma verification during low-demand periods (when fewer than 30% of the rate budget is consumed by thread scraping).

### Requirement 1.6: Basic Observability

**User Story:** As a system operator, I want metrics on the avatar scheduling and data freshness system, so that I can monitor health and identify when to scale to Phase 2.

#### Acceptance Criteria

1. THE System SHALL expose the following metrics via ActivityEvent logging: active_avatars_count, total_freshness_demands_generated, demands_satisfied_last_hour, demands_missed_last_hour, and rate_budget_utilization_percent.
2. WHEN demands_missed_last_hour exceeds 10% of total demands for 3 consecutive hours, THE System SHALL emit a warning ActivityEvent recommending evaluation of Phase 2 transition.
3. THE System SHALL compute a daily coverage metric: percentage of avatars whose ALL Freshness_Demands were satisfied before their Posting_Slots.
4. THE System SHALL log the sharing ratio (avatars satisfied per scrape) as a metric, targeting an average sharing ratio above 2.0 at 100-avatar scale.

---

## Phase 2: Caching Layer (500 Avatars, 5,000 Subreddits)

**Goal:** Add a Valkey/Redis caching layer for subreddit activity profiles, implement batch scrape windows, and introduce the Scrape_Sharing_Index in Redis for efficient demand resolution. Rate_Budget_Allocator with basic fairness.

**Prerequisites:** Phase 1 complete. Valkey/Redis cache deployed (already in target architecture).

**Scale trigger to Phase 3:** When avatar count exceeds 500 OR unique subreddits exceed 5,000 OR single-token rate limit becomes the bottleneck (daily coverage below 85%).

### Requirement 2.1: Subreddit Activity Profiling (Cached)

**User Story:** As a system operator, I want the system to learn when each subreddit is most active and cache this data, so that avatars post during high-engagement windows for maximum karma return.

#### Acceptance Criteria

1. THE System SHALL maintain a Subreddit_Activity_Profile for each subreddit that has been scraped at least 7 times, cached in Valkey with a 7-day TTL.
2. THE Subreddit_Activity_Profile SHALL contain hourly activity scores (0–100) for each hour of the day (24 values), computed from average post volume and comment velocity observed during scrapes.
3. WHEN a scrape completes for a subreddit, THE System SHALL update the Subreddit_Activity_Profile by incorporating the new data point using an exponential moving average with alpha=0.1.
4. WHEN the Avatar_Action_Scheduler assigns a subreddit to a Posting_Slot, THE Avatar_Action_Scheduler SHALL prefer time slots where the Subreddit_Activity_Profile score is above the 60th percentile for that subreddit.
5. IF a subreddit has fewer than 7 scrapes (insufficient data for profiling), THEN THE Avatar_Action_Scheduler SHALL use a default activity profile assuming peak hours of 09:00–12:00 and 17:00–21:00 UTC.

### Requirement 2.2: Scrape Sharing Index in Redis

**User Story:** As a system operator, I want a single subreddit scrape to efficiently satisfy data needs for all avatars that depend on that subreddit, using a Redis-based lookup for fast resolution.

#### Acceptance Criteria

1. THE Scrape_Sharing_Index SHALL maintain a Redis SET per subreddit containing the avatar IDs that have pending Freshness_Demands for it.
2. WHEN a scrape completes for a subreddit, THE System SHALL resolve all Freshness_Demands by reading the Scrape_Sharing_Index SET and marking demands as satisfied for ALL listed avatars.
3. THE Scrape_Sharing_Index SHALL be updated whenever an Avatar_Daily_Plan is generated (SADD avatar to subreddit sets) or when demands expire (SREM avatar from sets).
4. WHEN computing Demand_Priority_Score, THE Rate_Budget_Allocator SHALL use SCARD on the Scrape_Sharing_Index SET as the number_of_waiting_avatars factor.
5. THE System SHALL log the sharing ratio (avatars satisfied per scrape) as a metric, targeting an average sharing ratio above 3.0 at 500-avatar scale.

### Requirement 2.3: Batch Scrape Windows

**User Story:** As a system operator, I want the system to pre-scrape subreddits in batches before cohorts of avatars wake up, so that fresh data is ready when avatars need to act.

#### Acceptance Criteria

1. THE Avatar_Action_Scheduler SHALL group avatars into timezone cohorts based on their Activity_Window start times (rounded to the nearest 2-hour block).
2. THE Batch_Scrape_Window SHALL begin 2 hours before a cohort's Activity_Window starts, concentrating scraping effort on subreddits needed by that cohort.
3. WHEN a Batch_Scrape_Window is active, THE Rate_Budget_Allocator SHALL allocate 70% of the rate budget to subreddits needed by the upcoming cohort and 30% to other demands.
4. WHEN multiple Batch_Scrape_Windows overlap (cohorts in adjacent timezones), THE Rate_Budget_Allocator SHALL merge them and distribute budget proportionally by cohort size.
5. THE System SHALL compute and log the "readiness ratio" for each cohort: percentage of avatars in the cohort whose thread data was refreshed before their first Posting_Slot.

### Requirement 2.4: Rate Budget Allocator with Fairness

**User Story:** As a system operator, I want the system to intelligently allocate the 15 RPM Reddit API budget across 500 avatars with basic fairness guarantees.

#### Acceptance Criteria

1. THE Rate_Budget_Allocator SHALL distribute the global rate limit of 15 RPM (900 requests/hour, 21,600 requests/day) across all pending Freshness_Demands.
2. WHEN the total unique subreddits requiring refresh exceeds the daily capacity, THE Rate_Budget_Allocator SHALL prioritize subreddits with the highest Demand_Priority_Score and defer low-priority subreddits to the next cycle.
3. THE Rate_Budget_Allocator SHALL ensure that no single subreddit consumes more than 15% of the hourly rate budget, preventing a high-demand subreddit from starving others.
4. THE Rate_Budget_Allocator SHALL reserve 10% of the hourly budget (1.5 RPM) for on-demand karma refreshes and health checks.
5. WHEN daily coverage drops below 90%, THE System SHALL emit an alert recommending evaluation of Phase 3 transition (multi-token support).

### Requirement 2.5: Karma Freshness Management

**User Story:** As a system operator, I want the system to track when karma was last verified for each avatar-subreddit pair, so that phase promotion decisions use trustworthy data.

#### Acceptance Criteria

1. THE Karma_Freshness_Record SHALL store: avatar_id, subreddit_name, last_verified_at, verification_source (internal_tracking or reddit_api), confidence_level (high if verified within 24h, medium if 24–72h, low if older).
2. WHEN a comment is posted and its reddit_score is observed, THE System SHALL update the Karma_Freshness_Record for that avatar-subreddit pair with last_verified_at = now and verification_source = internal_tracking.
3. WHEN the Phase_Evaluator checks promotion eligibility, THE Phase_Evaluator SHALL require karma data with confidence_level of "high" or "medium" for all subreddits used in the evaluation.
4. IF karma data has confidence_level "low" for a subreddit needed in phase evaluation, THEN THE System SHALL trigger an on-demand karma refresh before proceeding with evaluation.
5. THE System SHALL batch karma refresh operations during low-demand periods, targeting one full karma refresh cycle per avatar every 48 hours.

---

## Phase 3: Sharding (2,000 Avatars, 100,000 Subreddits)

**Goal:** Partition avatars into cohorts, shard the scrape queue by subreddit hash, add multi-token support, and implement graceful degradation levels.

**Prerequisites:** Phase 2 complete. Multiple Reddit API tokens available.

**Scale trigger to Phase 4:** When avatar count exceeds 2,000 OR subreddits exceed 100K OR event-driven latency requirements emerge (sub-minute freshness needed).

### Requirement 3.1: Avatar Cohort Partitioning

**User Story:** As a system operator, I want avatars partitioned into cohorts so that the scheduler can process them in parallel without contention.

#### Acceptance Criteria

1. THE System SHALL partition avatars into cohorts of 200–500 avatars based on timezone_offset similarity and subreddit overlap.
2. WHEN a new avatar is onboarded, THE System SHALL assign it to the cohort with the highest subreddit overlap (maximizing scrape sharing efficiency).
3. THE Avatar_Action_Scheduler SHALL process cohorts independently, allowing parallel daily plan generation without cross-cohort locking.
4. THE System SHALL rebalance cohorts weekly to account for avatar additions, removals, and subreddit changes.
5. WHEN a cohort's internal sharing ratio drops below 2.0, THE System SHALL split it into two smaller cohorts or merge it with a more compatible cohort.

### Requirement 3.2: Scrape Queue Sharding

**User Story:** As a system operator, I want the scrape queue sharded by subreddit hash so that multiple workers can process scrape demands in parallel without conflicts.

#### Acceptance Criteria

1. THE System SHALL partition subreddits into N shards (configurable, default 8) using consistent hashing on subreddit_name.
2. EACH shard SHALL have its own independent queue and rate budget allocation (total_rpm / N per shard).
3. WHEN a Freshness_Demand is created, THE System SHALL route it to the correct shard based on the target subreddit's hash.
4. THE System SHALL support dynamic shard rebalancing when shards become unevenly loaded (one shard has 2x the demand of the average).
5. WHEN a shard's worker fails, THE System SHALL redistribute that shard's pending demands to adjacent shards within 5 minutes.

### Requirement 3.3: Multi-Token Rate Budget Scaling

**User Story:** As a system operator, I want the system to support multiple Reddit API tokens to scale beyond the 15 RPM limit of a single token.

#### Acceptance Criteria

1. THE System SHALL support configuration of multiple Reddit API tokens, each with its own independent rate limit tracking.
2. WHEN multiple tokens are configured, THE Rate_Budget_Allocator SHALL distribute scrape requests across tokens using weighted round-robin, respecting each token's individual rate limit.
3. THE System SHALL track per-token health (error rate, 429 responses, ban status) and automatically remove unhealthy tokens from the rotation.
4. WHEN a token receives a 429 response, THE System SHALL quarantine that token for 5 minutes and redistribute its budget to remaining healthy tokens.
5. THE System SHALL compute effective_total_rpm as the sum of all healthy tokens' rate limits, and use this value for capacity planning calculations.

### Requirement 3.4: Graceful Degradation

**User Story:** As a system operator, I want the system to degrade gracefully when demand exceeds capacity, so that all avatars receive some service rather than some receiving perfect service and others receiving none.

#### Acceptance Criteria

1. WHEN total Freshness_Demands exceed daily API capacity, THE Rate_Budget_Allocator SHALL implement fair-share allocation ensuring each avatar receives at least one satisfied demand per day.
2. THE System SHALL implement progressive degradation levels: Level 0 (normal, coverage >95%), Level 1 (extended freshness windows +50%, coverage 85–95%), Level 2 (reduced slots to minimum, coverage 70–85%), Level 3 (emergency — alert operators, coverage <70%).
3. WHEN operating in Level 1, THE System SHALL extend freshness windows by 50% (e.g., 4h becomes 6h) to reduce demand without stopping avatar activity.
4. WHEN operating in Level 2, THE Avatar_Action_Scheduler SHALL reduce Posting_Slots per avatar to the minimum (1 per day for warming Phase 1, 3 per day for warming Phase 2/3).
5. WHEN degradation level changes, THE System SHALL log an ActivityEvent with event_type "capacity" and emit an operator alert describing the current level and recommended action.
6. WHEN capacity is restored (coverage returns above 95% for 24 hours), THE System SHALL automatically return to Level 0 operation.

### Requirement 3.5: Scale Capacity Planning

**User Story:** As a system operator, I want the system to report its current capacity utilization and project when additional tokens or Phase 4 infrastructure is needed.

#### Acceptance Criteria

1. THE System SHALL compute and expose a daily capacity report containing: total unique subreddits, total Freshness_Demands generated, demands satisfied, demands missed, average sharing ratio, rate budget utilization percentage, and effective_total_rpm.
2. WHEN rate budget utilization exceeds 85% for 3 consecutive days, THE System SHALL emit a capacity warning recommending additional API tokens.
3. THE System SHALL project the maximum number of avatars supportable at current rate limits, computed as: `(daily_api_calls × average_sharing_ratio) / (average_subreddits_per_avatar × refreshes_per_subreddit_per_day)`.
4. WHEN a new batch of avatars is onboarded, THE System SHALL simulate the impact on coverage metrics before activating them, warning if coverage would drop below 90%.
5. THE capacity report SHALL include a breakdown by shard showing which shards are under-served.

---

## Phase 4: Stream Processing (10,000 Avatars, 1,000,000 Subreddits)

**Goal:** Event-driven architecture replacing polling. Kafka/SQS FIFO for ordering. Real-time urgency recomputation. Full observability dashboard.

**Prerequisites:** Phase 3 complete. Kafka or SQS FIFO deployed. Dedicated observability infrastructure.

### Requirement 4.1: Event-Driven Freshness Computation

**User Story:** As a system operator, I want freshness demands recomputed in real-time as events occur (scrape completes, avatar posts, karma changes), rather than on a polling schedule.

#### Acceptance Criteria

1. WHEN a scrape completes, THE System SHALL emit a "scrape_completed" event to the event stream, triggering immediate demand resolution for all dependent avatars.
2. WHEN an avatar posts successfully, THE System SHALL emit a "post_completed" event, triggering recomputation of that avatar's remaining daily plan and urgency score.
3. WHEN karma data is updated, THE System SHALL emit a "karma_updated" event, triggering re-evaluation of phase promotion eligibility for the affected avatar.
4. THE System SHALL process events with end-to-end latency of less than 5 seconds from event emission to demand state update.
5. THE System SHALL guarantee exactly-once processing of events using SQS FIFO deduplication or Kafka consumer group offsets.

### Requirement 4.2: Real-Time Urgency Recomputation

**User Story:** As a system operator, I want avatar urgency scores recomputed continuously as conditions change, rather than on a fixed 30-minute cycle.

#### Acceptance Criteria

1. WHEN any event affects an avatar's urgency factors (slot approaching, post completed, karma changed), THE System SHALL recompute that avatar's Avatar_Urgency_Score within 10 seconds.
2. THE System SHALL maintain a priority queue of avatars sorted by urgency, updated incrementally as scores change.
3. WHEN an avatar's urgency score crosses a threshold (enters top 10% of all avatars), THE System SHALL immediately evaluate whether its Freshness_Demands can be expedited.
4. THE System SHALL support processing urgency recomputations for 10,000 avatars with a throughput of at least 1,000 recomputations per second.

### Requirement 4.3: Full Observability Dashboard

**User Story:** As a system operator, I want a comprehensive real-time dashboard showing system health, capacity, and per-avatar status at 10K scale.

#### Acceptance Criteria

1. THE System SHALL expose real-time metrics: active_avatars_count, total_freshness_demands, demands_satisfied_last_hour, demands_missed_last_hour, average_demand_latency_minutes, rate_budget_utilization_percent, degradation_level, events_processed_per_second.
2. THE System SHALL expose per-cohort metrics: cohort_size, cohort_readiness_ratio, cohort_average_slots_filled, cohort_shard_distribution.
3. THE System SHALL expose per-subreddit metrics: demand_count, sharing_ratio, average_scrape_interval_hours, activity_profile_confidence.
4. WHEN average_demand_latency exceeds 60 minutes, THE System SHALL emit a warning indicating that avatars are waiting too long for fresh data.
5. THE System SHALL maintain a 30-day rolling history of all metrics for trend analysis and capacity forecasting.
6. THE System SHALL expose an admin dashboard page showing: current degradation level, top 10 highest-demand subreddits, top 10 most-urgent avatars, rate budget allocation breakdown, and event processing lag.

### Requirement 4.4: Ordered Event Processing

**User Story:** As a system operator, I want events processed in causal order per avatar, so that race conditions do not corrupt avatar state.

#### Acceptance Criteria

1. THE System SHALL use SQS FIFO message groups (keyed by avatar_id) or Kafka partitions (keyed by avatar_id) to guarantee per-avatar event ordering.
2. WHEN multiple events arrive for the same avatar within a 1-second window, THE System SHALL process them sequentially in emission order.
3. THE System SHALL handle out-of-order events for DIFFERENT avatars in parallel, achieving horizontal scalability.
4. IF an event fails processing, THEN THE System SHALL retry it up to 3 times with exponential backoff before routing to a dead-letter queue.
5. THE System SHALL expose event processing lag (time between event emission and processing completion) as a metric, with an alert threshold of 30 seconds.

---

## Cross-Phase Requirements

These requirements apply across all phases and should be implemented incrementally.

### Requirement C.1: Phase Transition Safeguards

**User Story:** As a system operator, I want clear signals when the system needs to transition to the next phase, so that scaling decisions are data-driven.

#### Acceptance Criteria

1. THE System SHALL monitor phase transition triggers continuously: avatar count, subreddit count, daily coverage percentage, and rate budget utilization.
2. WHEN any phase transition trigger is met, THE System SHALL emit an ActivityEvent with event_type "scale_warning" containing the trigger details and recommended next phase.
3. THE System SHALL NOT automatically transition between phases — transitions require explicit operator action.
4. WHEN operating above a phase's designed capacity for more than 7 days, THE System SHALL emit a daily warning with projected degradation timeline.

### Requirement C.2: Backward Compatibility

**User Story:** As a system operator, I want each phase to maintain backward compatibility with the previous phase's data and APIs, so that transitions are non-disruptive.

#### Acceptance Criteria

1. WHEN Phase 2 is deployed, THE System SHALL continue to function correctly if the Valkey cache is unavailable (falling back to Phase 1 behavior).
2. WHEN Phase 3 is deployed, THE System SHALL support running with a single token (falling back to Phase 2 behavior with degraded capacity).
3. THE System SHALL maintain all existing API endpoints and data models across phase transitions, adding new fields as nullable columns.
4. WHEN rolling back from Phase N to Phase N-1, THE System SHALL continue operating with reduced capacity but without data loss or corruption.
