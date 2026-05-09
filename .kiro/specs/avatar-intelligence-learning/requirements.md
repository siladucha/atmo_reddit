# Requirements Document

## Introduction

The Avatar Intelligence & Learning System enables avatars to learn from high-performing Reddit commentators ("leaders") in target subreddits, extract their style patterns via LLM analysis, and generate hybrid comments that combine the avatar's established voice with proven engagement patterns. The system includes health monitoring, activity profiling, feedback-driven adaptation, idempotency/deduplication, multi-level caching, and unified rate limiting across all Reddit API consumers.

## Glossary

- **Avatar**: A managed Reddit account (digital asset) used for community engagement on behalf of a client
- **Health_Monitor**: The subsystem responsible for daily avatar health checks including ban and shadowban detection
- **Activity_Profiler**: The subsystem that collects and aggregates an avatar's recent Reddit comment history
- **Leader_Discovery_Engine**: The subsystem that identifies the highest-performing commentator in a target subreddit
- **Pattern_Extractor**: The subsystem that uses LLM analysis (Gemini Flash) to extract style patterns from a leader's top comments
- **Hybrid_Generator**: The subsystem that combines avatar voice profile, leader patterns, and thread context to generate comments (Claude Sonnet)
- **Feedback_Tracker**: The subsystem that monitors posted comment karma at defined intervals and adjusts learning parameters
- **Idempotency_Layer**: The subsystem that prevents duplicate task execution and caches completed results
- **Cache_Manager**: The subsystem managing multi-level cache with different TTLs per data type
- **Rate_Limiter**: The unified subsystem controlling Reddit API request rate across all consumers (manual and automated)
- **Request_Queue**: The priority queue managing both automated and manual operator Reddit API requests
- **Leader**: The Reddit user identified as the best commentator in a target subreddit based on aggregated karma
- **Avatar_Portrait**: An aggregated profile of an avatar's recent activity including per-subreddit statistics
- **Style_Pattern**: A structured representation of a leader's commenting style extracted by LLM analysis
- **Karma_Snapshot**: A recorded karma value for a posted comment at a specific time interval (4h, 24h, 48h)
- **Idempotency_Key**: A composite key (user_id + task_type + target + date) uniquely identifying a task request
- **Force_Refresh**: A manual override that bypasses cache and re-executes a task, subject to cooldown
- **Reddit_App**: An OAuth application registered with Reddit, limited to 55 requests per minute
- **Subreddit_Presence**: The aggregated record of all subreddits where an avatar has posted comments, including per-subreddit metrics (count, karma, last activity)

## Requirements

### Requirement 1: Avatar Health Monitoring

**User Story:** As an operator, I want the system to automatically detect when an avatar is banned or shadowbanned, so that the system stops generating content for compromised accounts and I can take corrective action.

#### Acceptance Criteria

1. WHEN a daily health check is triggered, THE Health_Monitor SHALL verify the avatar's Reddit account status by checking profile accessibility and recent comment visibility
2. WHEN the Health_Monitor detects that an avatar's profile returns a 404 or "suspended" status, THE Health_Monitor SHALL mark the avatar health_status as "banned" and record the detection timestamp
3. WHEN the Health_Monitor detects that an avatar's recent comments have zero visibility to unauthenticated users, THE Health_Monitor SHALL mark the avatar health_status as "shadowbanned" and record the detection timestamp
4. WHEN an avatar is detected as banned or shadowbanned, THE Health_Monitor SHALL set the avatar's is_frozen flag to true with freeze_reason indicating the detected status
5. WHEN an avatar is frozen due to ban detection, THE Health_Monitor SHALL emit an activity_event with event_type "avatar_frozen_ban_detected" including the avatar_id and detected status
6. WHILE an avatar has health_status "banned" or "shadowbanned", THE Hybrid_Generator SHALL exclude that avatar from comment generation
7. THE Health_Monitor SHALL record karma_post and karma_comment values from the Reddit API response during each health check
8. IF the Reddit API returns a rate limit error during health check, THEN THE Health_Monitor SHALL retry after the rate limit window expires using exponential backoff (max 3 retries)

### Requirement 2: Avatar Activity Profiling

**User Story:** As an operator, I want the system to build a comprehensive activity profile for each avatar based on its recent Reddit history, so that the generation pipeline has accurate context about the avatar's established presence.

#### Acceptance Criteria

1. WHEN activity profiling is triggered for an avatar, THE Activity_Profiler SHALL collect the last 100 comments from the avatar's Reddit comment history via the Reddit API
2. WHEN comments are collected, THE Activity_Profiler SHALL aggregate them by subreddit, computing per-subreddit metrics: comment count, average karma per comment, average comment length in characters, and most active hours (UTC)
3. THE Activity_Profiler SHALL store the aggregated profile as an Avatar_Portrait in the cache with a 24-hour TTL
4. WHEN the Activity_Profiler cannot retrieve comments due to a private or suspended account, THE Activity_Profiler SHALL return an error status indicating the account is inaccessible and skip profile generation
5. THE Activity_Profiler SHALL complete profiling for a single avatar within 60 seconds under normal API conditions

### Requirement 3: Leader Discovery

**User Story:** As an operator, I want the system to automatically find the best commentator in each target subreddit, so that the avatar can learn from proven engagement patterns.

#### Acceptance Criteria

1. WHEN leader discovery is triggered for a target subreddit, THE Leader_Discovery_Engine SHALL fetch the top 50 posts (by hot ranking) from that subreddit
2. WHEN posts are fetched, THE Leader_Discovery_Engine SHALL collect the top 10 comments (by karma) from each post, yielding up to 500 comment samples
3. THE Leader_Discovery_Engine SHALL aggregate collected comments by author, computing total karma earned and comment count per author
4. THE Leader_Discovery_Engine SHALL rank authors by total karma earned and select the top-ranked author as the leader candidate
5. WHEN a leader candidate is identified, THE Leader_Discovery_Engine SHALL validate that the candidate has at least 5 comments in the sample and an average karma per comment of at least 10
6. IF no candidate meets the validation threshold, THEN THE Leader_Discovery_Engine SHALL select the next-ranked author and repeat validation until a valid leader is found or candidates are exhausted
7. THE Leader_Discovery_Engine SHALL store the discovered leader in the cache with a 14-day TTL keyed by subreddit name
8. WHEN a cached leader exists for a subreddit and the cache has not expired, THE Leader_Discovery_Engine SHALL return the cached leader without re-executing discovery

### Requirement 4: Pattern Extraction

**User Story:** As an operator, I want the system to extract structured style patterns from a leader's top comments using LLM analysis, so that these patterns can inform avatar comment generation.

#### Acceptance Criteria

1. WHEN pattern extraction is triggered for a validated leader, THE Pattern_Extractor SHALL collect the leader's top 10 comments (by karma) from the target subreddit
2. WHEN comments are collected, THE Pattern_Extractor SHALL send them to Gemini Flash with a structured extraction prompt requesting: typical comment length range, common opener types, structural patterns (paragraph count, use of lists, questions), tone markers, and avoided patterns
3. THE Pattern_Extractor SHALL parse the LLM response into a structured Style_Pattern object with fields: length_range_words, opener_types, structure_patterns, tone_markers, and avoided_patterns
4. IF the LLM response does not conform to the expected schema, THEN THE Pattern_Extractor SHALL retry the extraction once with a simplified prompt before returning an error
5. THE Pattern_Extractor SHALL store the extracted Style_Pattern in the cache associated with the leader and subreddit, with a 14-day TTL matching the leader cache
6. THE Pattern_Extractor SHALL complete extraction for a single leader within 30 seconds under normal LLM API conditions

### Requirement 5: Hybrid Comment Generation

**User Story:** As an operator, I want the system to generate comments that combine the avatar's established voice with learned leader patterns and thread context, so that generated comments achieve higher engagement while maintaining avatar authenticity.

#### Acceptance Criteria

1. WHEN hybrid comment generation is triggered for a thread, THE Hybrid_Generator SHALL assemble a prompt containing: the avatar's voice_profile, the leader's extracted Style_Pattern for the thread's subreddit, and the thread context (title, body, top existing comments)
2. THE Hybrid_Generator SHALL send the assembled prompt to Claude Sonnet for comment generation
3. THE Hybrid_Generator SHALL instruct the LLM to prioritize the avatar's voice_profile for personality and tone, while applying the leader's Style_Pattern for structural decisions (length, openers, formatting)
4. WHEN no Style_Pattern exists for the thread's subreddit (leader not yet discovered or extraction failed), THE Hybrid_Generator SHALL generate the comment using only the avatar's voice_profile and thread context without leader patterns
5. THE Hybrid_Generator SHALL validate that the generated comment length falls within the Style_Pattern's length_range_words (with a 20% tolerance) when a pattern is available
6. IF the generated comment exceeds the length tolerance, THEN THE Hybrid_Generator SHALL request a shorter regeneration from the LLM (max 1 retry)

### Requirement 6: Feedback and Adaptation

**User Story:** As an operator, I want the system to track comment performance and automatically adjust learning parameters based on karma outcomes, so that the system continuously improves engagement quality.

#### Acceptance Criteria

1. WHEN a comment is marked as "posted" with a reddit_comment_url, THE Feedback_Tracker SHALL schedule karma snapshots at 4 hours, 24 hours, and 48 hours after posting
2. WHEN a karma snapshot is due, THE Feedback_Tracker SHALL fetch the current karma score for the comment via the Reddit API and store it as a Karma_Snapshot record
3. WHEN the 48-hour snapshot is collected, THE Feedback_Tracker SHALL compare the comment's karma against the avatar's average karma in that subreddit to classify performance as "above_average", "average", or "below_average"
4. WHEN a comment is classified as "above_average", THE Feedback_Tracker SHALL reinforce the Style_Pattern that was used by incrementing a success counter for that pattern-subreddit combination
5. WHEN a comment is classified as "below_average", THE Feedback_Tracker SHALL decrement the confidence score for the Style_Pattern used in that subreddit
6. WHEN an avatar's rolling average karma (last 10 comments) in a subreddit drops below 50% of the subreddit leader's average karma, THE Feedback_Tracker SHALL trigger a new leader discovery for that subreddit to find a potentially better leader to learn from
7. IF a comment is detected as removed (404 or not visible) during any karma snapshot, THEN THE Feedback_Tracker SHALL record the removal, mark the comment as is_deleted, and add the comment's approach to the avatar's failed_patterns for that subreddit

### Requirement 7: Idempotency and Deduplication

**User Story:** As an operator, I want the system to prevent duplicate task execution and return cached results for repeated requests, so that API budget is conserved and the system behaves predictably under repeated triggers.

#### Acceptance Criteria

1. THE Idempotency_Layer SHALL compute an idempotency_key for every manual request as: hash(user_id + task_type + target + date)
2. WHEN a request arrives with an idempotency_key matching a pending or running task, THE Idempotency_Layer SHALL return the existing task status and progress without creating a new task
3. WHEN a request arrives with an idempotency_key matching a completed task within the cache window (60 minutes), THE Idempotency_Layer SHALL return the cached result without re-executing the task
4. WHEN a force_refresh parameter is set to true on a request, THE Idempotency_Layer SHALL bypass the cache and re-execute the task, provided the last force_refresh for that key was more than 10 minutes ago
5. IF a force_refresh is requested within the 10-minute cooldown period, THEN THE Idempotency_Layer SHALL reject the request with an error indicating the remaining cooldown time
6. THE Idempotency_Layer SHALL store task results in Valkey with a 60-minute TTL for the task result cache

### Requirement 8: Multi-Level Caching

**User Story:** As an operator, I want the system to cache expensive computation results at appropriate TTLs per data type, so that redundant API calls and LLM invocations are minimized while data remains fresh enough for effective operation.

#### Acceptance Criteria

1. THE Cache_Manager SHALL cache subreddit leader data with a 14-day TTL in the database (PostgreSQL)
2. THE Cache_Manager SHALL cache Avatar_Portrait data with a 24-hour TTL in Valkey
3. THE Cache_Manager SHALL cache subreddit post listings with a 1-hour TTL in Valkey
4. THE Cache_Manager SHALL cache task execution results with a 60-minute TTL in Valkey
5. WHEN a cache entry is requested and exists within its TTL, THE Cache_Manager SHALL return the cached value without invoking the underlying data source
6. WHEN a cache entry has expired, THE Cache_Manager SHALL transparently trigger re-computation and update the cache with the fresh result
7. THE Cache_Manager SHALL support explicit cache invalidation per key, allowing operators to force refresh specific data without waiting for TTL expiry

### Requirement 9: Rate Limiting and Queue Priority

**User Story:** As an operator, I want all Reddit API calls (both automated pipeline and manual operator requests) to go through a unified rate limiter, so that the system never exceeds Reddit's API limits and avoids account-level throttling or bans.

#### Acceptance Criteria

1. THE Rate_Limiter SHALL enforce a maximum of 55 requests per minute per Reddit_App OAuth token using a sliding window algorithm
2. THE Rate_Limiter SHALL apply to all Reddit API consumers: health checks, activity profiling, leader discovery, karma snapshots, and manual operator requests
3. WHILE the current request count within the sliding window equals or exceeds 55, THE Rate_Limiter SHALL queue incoming requests and process them when capacity becomes available
4. THE Rate_Limiter SHALL distribute available capacity across consumers using a priority-weighted queue where manual operator requests receive higher priority than automated pipeline requests
5. WHEN a request is queued, THE Rate_Limiter SHALL assign an estimated wait time based on current queue depth and processing rate
6. THE Rate_Limiter SHALL limit the number of avatars in active learning per Reddit_App to a maximum of 20 concurrent learning sessions

### Requirement 10: Manual Request Queue

**User Story:** As an operator, I want to submit manual Reddit API requests (profile checks, subreddit analysis) through the same queue as automated requests with higher priority, so that I get faster results while the system maintains rate limit compliance.

#### Acceptance Criteria

1. WHEN an operator submits a manual request, THE Request_Queue SHALL assign it a higher priority than automated pipeline requests
2. WHEN a manual request is queued, THE Request_Queue SHALL return the current queue position and estimated wait time to the operator
3. WHILE a manual request is waiting in the queue, THE Request_Queue SHALL provide updated position and wait time on subsequent status checks
4. WHEN a manual request completes, THE Request_Queue SHALL store the result in the task result cache (60-minute TTL) and notify the operator
5. THE Request_Queue SHALL process manual requests in FIFO order among requests of equal priority
6. IF a manual request fails due to a Reddit API error, THEN THE Request_Queue SHALL retry once with exponential backoff before returning the error to the operator

### Requirement 11: Avatar Subreddit Presence Map

**User Story:** As an operator, I want to see a complete list of all subreddits where an avatar has been active (commented) on the avatar detail page, so that I can understand the avatar's footprint and make informed decisions about subreddit targeting.

#### Acceptance Criteria

1. WHEN the avatar detail page (`/admin/avatars/{id}`) is loaded, THE system SHALL display a "Subreddit Presence" section listing all subreddits where the avatar has posted at least one comment
2. FOR each subreddit in the presence list, THE system SHALL display: subreddit name, total comment count, average karma per comment, last activity date, and a link to the subreddit on Reddit
3. THE subreddit presence list SHALL be sorted by total comment count (descending) by default, with an option to sort by average karma or last activity date
4. WHEN the operator clicks "Scan Subreddit Presence" button on the avatar detail page, THE system SHALL create a manual request task that fetches the avatar's recent comment history from Reddit and extracts the subreddit distribution
5. THE manual scan request SHALL go through the unified Request_Queue with operator priority, and the operator SHALL see the task status (pending/running/completed) inline on the page
6. WHEN the scan task completes, THE system SHALL update the subreddit presence data in the database and refresh the presence section via HTMX without full page reload
7. THE system SHALL also update subreddit presence data automatically during the scheduled Activity_Profiler run (weekly), storing results with a timestamp indicating data freshness
8. THE subreddit presence section SHALL display a "Last updated" timestamp showing when the data was last refreshed (either manually or by scheduler)
9. IF the subreddit presence data is older than 7 days, THE system SHALL display a "stale" indicator next to the timestamp suggesting the operator refresh the data
10. WHEN no subreddit presence data exists for an avatar (never scanned), THE system SHALL display an empty state with a prominent "Scan Now" button and a note explaining that the first scan requires a Reddit API call
