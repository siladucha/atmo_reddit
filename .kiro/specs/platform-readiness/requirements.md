# Requirements Document

## Introduction

Platform Readiness addresses three critical subsystems that block production multi-client operation of the Reddit Marketing SaaS platform. The existing trust infrastructure (warming phases, karma tracking, phase escalation) works correctly, but the platform lacks: (1) timing jitter to avoid detectable posting patterns, (2) subreddit intelligence to adapt behavior to community-specific rules and culture, and (3) a context architecture layer that enforces client data isolation and provides structured memory for LLM calls. Without these three blocks, multi-client operation risks cross-client data leakage, Reddit anti-spam detection, and subreddit bans from rule violations.

## Glossary

- **Jitter_Service**: The service responsible for adding bounded randomization to all timing intervals (comment gaps, scraping intervals, posting windows)
- **Subreddit_Intelligence_Service**: The service responsible for fetching, parsing, storing, and refreshing subreddit-specific metadata (rules, flair, moderation strictness, topics)
- **Context_Assembly_Service**: The unified service responsible for composing LLM prompt context from multiple sources while enforcing client isolation boundaries
- **Avatar**: A pre-warmed Reddit account entity with `client_ids` array, voice profile, and warming phase
- **Client**: A business customer entity with brand profile, worldview, keywords, and competitive landscape
- **Subreddit**: A shared registry entity representing a Reddit community
- **Subreddit_Profile**: A stored metadata record containing a subreddit's rules, flair requirements, moderation strictness, culture notes, and trending topics
- **Conversation_Memory**: A per-avatar record of previous comments, threads engaged, and positions taken, scoped by client boundary
- **Client_Boundary**: The isolation constraint ensuring that one client's brand data, worldview, keywords, and strategic context are never included in LLM calls made on behalf of another client
- **Timing_Window**: A bounded range (min, max) from which a randomized delay is sampled for a specific action type
- **Moderation_Strictness**: A categorical assessment (lenient, moderate, strict) of how aggressively a subreddit's moderators enforce rules
- **Safety_Service**: The existing rate-limiting and safety-check service in `services/safety.py`
- **Scoring_Service**: The existing thread scoring service in `services/scoring.py`
- **Generation_Service**: The existing comment/post generation service in `services/generation.py`

## Requirements

### Requirement 1: Comment Timing Jitter

**User Story:** As a platform operator, I want randomized delays between avatar comments, so that posting patterns are unpredictable and resistant to Reddit anti-spam detection.

#### Acceptance Criteria

1. WHEN the Safety_Service checks the minimum time between comments, THE Jitter_Service SHALL compute the effective delay by sampling a random value from a configurable Timing_Window (minimum floor, maximum ceiling) instead of using the fixed `MIN_MINUTES_BETWEEN_COMMENTS` constant
2. THE Jitter_Service SHALL ensure the sampled delay is always greater than or equal to the configured minimum floor (default: 12 minutes)
3. THE Jitter_Service SHALL ensure the sampled delay is always less than or equal to the configured maximum ceiling (default: 45 minutes)
4. WHEN multiple comments are scheduled for the same avatar within a session, THE Jitter_Service SHALL sample an independent random delay for each comment (no repeating pattern)
5. THE Jitter_Service SHALL use a cryptographically secure random source for delay sampling to prevent predictability
6. THE Jitter_Service SHALL produce a deterministic result when provided with an explicit seed parameter (for testing and debugging)

### Requirement 2: Scraping Interval Jitter

**User Story:** As a platform operator, I want randomized scraping intervals per subreddit, so that the platform's access patterns do not form detectable periodic signals.

#### Acceptance Criteria

1. WHEN a scraping task is scheduled for a subreddit, THE Jitter_Service SHALL compute the next scrape time by adding a random offset from a configurable Timing_Window (default: 55–90 minutes) to the last scrape timestamp
2. THE Jitter_Service SHALL vary the offset independently for each subreddit (no global synchronized scraping)
3. WHILE a subreddit has never been scraped, THE Jitter_Service SHALL schedule the first scrape with a random offset between 0 and 5 minutes from task creation (staggered cold start)
4. THE Jitter_Service SHALL log the computed next-scrape timestamp for each subreddit for operational visibility

### Requirement 3: Per-Avatar Daily Activity Jitter

**User Story:** As a platform operator, I want each avatar's daily activity window to vary day-to-day, so that no avatar posts at predictable hours.

#### Acceptance Criteria

1. WHEN the pipeline evaluates an avatar for daily activity, THE Jitter_Service SHALL compute a randomized activity start hour within a configurable range (default: 7:00–11:00 UTC)
2. WHEN the pipeline evaluates an avatar for daily activity, THE Jitter_Service SHALL compute a randomized activity end hour within a configurable range (default: 20:00–23:59 UTC)
3. THE Jitter_Service SHALL ensure the activity window is at least 8 hours wide for any given avatar on any given day
4. WHILE the current time is outside an avatar's computed daily activity window, THE Safety_Service SHALL block comment posting for that avatar with a descriptive reason

### Requirement 4: Subreddit Rule Parsing

**User Story:** As a platform operator, I want the system to automatically fetch and parse subreddit rules, so that generated comments comply with community guidelines.

#### Acceptance Criteria

1. WHEN a subreddit is scraped for the first time, THE Subreddit_Intelligence_Service SHALL fetch the subreddit's sidebar rules and wiki rules via the Reddit API
2. WHEN subreddit rules are fetched, THE Subreddit_Intelligence_Service SHALL parse and store them as structured data in the Subreddit_Profile record
3. THE Subreddit_Intelligence_Service SHALL refresh subreddit rules on a configurable interval (default: every 7 days)
4. IF the Reddit API returns an error or empty rules for a subreddit, THEN THE Subreddit_Intelligence_Service SHALL retain the previously stored rules and log a warning
5. THE Subreddit_Intelligence_Service SHALL extract and store the following from subreddit rules: prohibited content types, required post formats, minimum account age requirements, minimum karma requirements, and link restrictions

### Requirement 5: Moderation Strictness Assessment

**User Story:** As a platform operator, I want the system to assess each subreddit's moderation strictness, so that avatar behavior adapts to avoid bans in heavily moderated communities.

#### Acceptance Criteria

1. WHEN a Subreddit_Profile is created or refreshed, THE Subreddit_Intelligence_Service SHALL compute a Moderation_Strictness level (lenient, moderate, strict) based on the number of rules, rule specificity, and known automod patterns
2. WHILE a subreddit is classified as strict, THE Safety_Service SHALL reduce the per-subreddit daily comment limit for all avatars in that subreddit by 50% (rounded down, minimum 1)
3. WHILE a subreddit is classified as strict, THE Generation_Service SHALL include an explicit instruction in the LLM prompt to avoid any promotional language patterns
4. THE Subreddit_Intelligence_Service SHALL store the Moderation_Strictness value in the Subreddit_Profile and update it on each rule refresh

### Requirement 6: Flair Handling

**User Story:** As a platform operator, I want the system to track subreddit flair requirements, so that posts and comments comply with flair policies and avoid removal.

#### Acceptance Criteria

1. WHEN a Subreddit_Profile is created, THE Subreddit_Intelligence_Service SHALL fetch and store available post flair options for the subreddit
2. WHEN a Subreddit_Profile is created, THE Subreddit_Intelligence_Service SHALL detect whether post flair is required (mandatory) for the subreddit
3. WHEN post flair is required and a post is being drafted, THE Generation_Service SHALL select an appropriate flair from the stored options based on post content
4. THE Subreddit_Intelligence_Service SHALL refresh flair data on the same interval as rule data (default: every 7 days)
5. IF flair options cannot be fetched (private subreddit, API error), THEN THE Subreddit_Intelligence_Service SHALL mark flair status as "unknown" and log a warning

### Requirement 7: Subreddit Topic and Sentiment Tracking

**User Story:** As a platform operator, I want the system to track trending topics and sentiment per subreddit, so that generated comments are contextually relevant to current discussions.

#### Acceptance Criteria

1. WHEN threads are scraped from a subreddit, THE Subreddit_Intelligence_Service SHALL extract and store the top 10 trending topics (keywords/phrases) from the most recent 50 threads
2. WHEN threads are scraped from a subreddit, THE Subreddit_Intelligence_Service SHALL compute and store an overall sentiment indicator (positive, neutral, negative) for the subreddit's recent activity
3. THE Subreddit_Intelligence_Service SHALL update topic and sentiment data on every scrape cycle (not on a separate schedule)
4. WHEN the Context_Assembly_Service builds context for comment generation, THE Context_Assembly_Service SHALL include the target subreddit's current trending topics and sentiment in the LLM prompt

### Requirement 8: Unified Context Assembly

**User Story:** As a platform operator, I want a single service that assembles all LLM prompt context from structured sources, so that context composition is consistent, testable, and auditable across all AI calls.

#### Acceptance Criteria

1. THE Context_Assembly_Service SHALL provide a single entry point for assembling scoring context (replacing inline context building in `build_scoring_messages`)
2. THE Context_Assembly_Service SHALL provide a single entry point for assembling generation context (replacing inline context building in `generate_comment` and `select_persona`)
3. THE Context_Assembly_Service SHALL accept explicit parameters for client, avatar, thread, and subreddit and return a fully composed context object
4. THE Context_Assembly_Service SHALL produce a deterministic output given the same input parameters (for testing and debugging reproducibility)
5. THE Context_Assembly_Service SHALL include subreddit profile data (rules, strictness, trending topics) in the assembled context when available
6. THE Context_Assembly_Service SHALL include avatar conversation memory in the assembled context when available

### Requirement 9: Client Data Isolation in Context Assembly

**User Story:** As a platform operator, I want strict client boundary enforcement during context assembly, so that one client's brand data never leaks into another client's LLM calls.

#### Acceptance Criteria

1. WHEN assembling context for an LLM call, THE Context_Assembly_Service SHALL include brand data (company_profile, company_worldview, company_problem, competitive_landscape, brand_voice, keywords) from exactly one client, identified by the explicit client_id parameter
2. WHEN an avatar has multiple entries in its `client_ids` array, THE Context_Assembly_Service SHALL use only the client_id passed as a parameter and SHALL NOT access data from other clients in the array
3. IF the specified client_id is not present in the avatar's `client_ids` array, THEN THE Context_Assembly_Service SHALL raise a validation error and refuse to assemble context
4. THE Context_Assembly_Service SHALL NOT include any client-specific data in hobby-mode context assembly (hobby comments have no client brand context)
5. THE Context_Assembly_Service SHALL log the client_id used for each context assembly call for audit purposes

### Requirement 10: Avatar Conversation Memory

**User Story:** As a platform operator, I want each avatar to have a memory of its previous comments and positions, so that generated comments maintain consistency and avoid contradictions.

#### Acceptance Criteria

1. WHEN a comment is approved or posted, THE Context_Assembly_Service SHALL store a summary record in the avatar's Conversation_Memory including: subreddit, thread title, comment text, position taken, and timestamp
2. WHEN assembling generation context for an avatar, THE Context_Assembly_Service SHALL include the avatar's last 10 comments in the target subreddit from Conversation_Memory
3. WHEN assembling generation context for an avatar, THE Context_Assembly_Service SHALL include the avatar's last 5 comments across all subreddits (for voice consistency)
4. THE Conversation_Memory SHALL be scoped by client boundary — memory entries created for client A are not visible when assembling context for client B, even for the same avatar
5. THE Context_Assembly_Service SHALL store Conversation_Memory records in PostgreSQL with appropriate indexes for efficient retrieval by avatar_id, client_id, and subreddit

### Requirement 11: Subreddit Knowledge Store

**User Story:** As a platform operator, I want a persistent per-subreddit knowledge store, so that accumulated intelligence about each community is available to all services without redundant API calls.

#### Acceptance Criteria

1. THE Subreddit_Intelligence_Service SHALL store all subreddit metadata (rules, flair, strictness, topics, sentiment) in a dedicated `subreddit_profiles` database table linked to the Subreddit record
2. THE Subreddit_Intelligence_Service SHALL populate the Subreddit_Profile lazily on first scrape of a subreddit (not eagerly for all subreddits)
3. THE Subreddit_Intelligence_Service SHALL track a `last_refreshed_at` timestamp on each Subreddit_Profile record
4. WHEN any service requests subreddit intelligence data, THE Subreddit_Intelligence_Service SHALL return the stored Subreddit_Profile without making a Reddit API call (read from cache)
5. IF a Subreddit_Profile's `last_refreshed_at` is older than the configured refresh interval, THEN THE Subreddit_Intelligence_Service SHALL schedule a background refresh task (non-blocking)

### Requirement 12: Backward Compatibility

**User Story:** As a platform operator, I want the new subsystems to integrate without breaking existing pipeline functionality, so that current operations continue uninterrupted during rollout.

#### Acceptance Criteria

1. THE Jitter_Service SHALL be usable as a drop-in replacement for the fixed `MIN_MINUTES_BETWEEN_COMMENTS` constant without requiring changes to the Safety_Service's public interface
2. THE Context_Assembly_Service SHALL maintain backward compatibility with existing `build_scoring_messages` and `generate_comment` function signatures during a transition period
3. WHILE a subreddit has no Subreddit_Profile record, THE Context_Assembly_Service SHALL assemble context using only the data available today (client + thread + avatar) without errors
4. WHILE a subreddit has no Subreddit_Profile record, THE Safety_Service SHALL apply default rate limits (no strictness-based adjustments)
5. THE Conversation_Memory system SHALL function correctly for avatars with no prior memory records (empty memory produces no errors and no hallucinated history)
6. THE platform SHALL continue to use the existing PhasePolicy and karma tracking systems without modification
