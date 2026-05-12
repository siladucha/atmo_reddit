# Requirements Document

## Introduction

The Manual Avatar Pipeline V2 corrects and formalizes the existing manual pipeline tab on the avatar detail page (`/admin/avatars/{id}?tab=pipeline`). The current implementation lacks cross-avatar deduplication, budget visibility, scoring cost awareness, accounting for already-posted comments, and thread freshness filtering. This spec addresses all five gaps while preserving the existing step-by-step flow: Scrape → Score → Select Thread → Generate.

## Glossary

- **Pipeline_Panel**: The HTMX-driven manual pipeline tab on the avatar detail page that provides step-by-step comment generation workflow
- **Avatar**: A managed Reddit account (persona) assigned to one or more clients, operating under warming phase restrictions
- **Client**: A business entity that owns one or more avatars and targets specific subreddits
- **Budget_Dashboard**: The status section at the top of the Pipeline_Panel showing remaining daily capacity for an avatar
- **Safety_Service**: The backend service (`safety.py`) that enforces per-avatar rate limits and content safety rules
- **Phase_Policy**: The backend service (`phase.py`) that determines what content types and subreddits an avatar can access based on its warming phase (1, 2, or 3)
- **Thread_Score**: An AI-generated assessment of a Reddit thread's relevance, quality, and strategic value for a client
- **Cross_Avatar_Deduplication**: The process of excluding threads where any avatar belonging to the same client already has a pending, approved, or posted draft
- **Stale_Thread**: A Reddit thread older than 48 hours from its original post time, considered too old for engagement
- **Budget_Slot**: A single remaining comment opportunity within the avatar's daily safety limits
- **Scoring_Batch**: A group of unscored threads processed together by the AI scoring service

## Requirements

### Requirement 1: Budget Dashboard Visibility

**User Story:** As an admin operator, I want to see the avatar's remaining daily budget prominently before attempting any generation, so that I know upfront whether generation is possible without hitting safety blocks.

#### Acceptance Criteria

1. WHEN the Pipeline_Panel loads, THE Budget_Dashboard SHALL display the number of comments posted today (approved + posted + pending drafts) out of the maximum allowed (MAX_COMMENTS_PER_DAY = 8)
2. WHEN the Pipeline_Panel loads, THE Budget_Dashboard SHALL display the number of professional comments posted today out of the maximum allowed (MAX_PROFESSIONAL_PER_DAY = 5)
3. WHEN the Pipeline_Panel loads, THE Budget_Dashboard SHALL display the number of hobby comments posted today out of the maximum allowed (MAX_HOBBY_PER_DAY = 5)
4. WHEN the Pipeline_Panel loads, THE Budget_Dashboard SHALL display the time remaining until the next comment is allowed based on MIN_MINUTES_BETWEEN_COMMENTS (15 minutes since last posted/approved draft)
5. WHEN the avatar has zero remaining Budget_Slots, THE Budget_Dashboard SHALL display a prominent warning indicating that no more comments can be generated today
6. WHEN the avatar's weekly brand ratio exceeds MAX_BRAND_RATIO (30%), THE Budget_Dashboard SHALL display a warning indicating that brand-related comments are restricted
7. THE Budget_Dashboard SHALL display per-subreddit usage counts for subreddits where the avatar has already posted today (MAX_COMMENTS_PER_SUBREDDIT_DAY = 2)

### Requirement 2: Cross-Avatar Deduplication

**User Story:** As an admin operator, I want the thread list to exclude threads where any other avatar of the same client already has a draft, so that two avatars never comment on the same thread (which looks coordinated and suspicious).

#### Acceptance Criteria

1. WHEN the Pipeline_Panel loads the thread list, THE Pipeline_Panel SHALL exclude threads where any avatar belonging to the same Client has a CommentDraft with status "pending", "approved", or "posted"
2. WHEN the Pipeline_Panel loads the thread list, THE Pipeline_Panel SHALL display the count of threads excluded due to Cross_Avatar_Deduplication
3. IF a thread is excluded due to Cross_Avatar_Deduplication, THEN THE Pipeline_Panel SHALL indicate which avatar already has a draft for that thread (in a tooltip or collapsed detail)

### Requirement 3: Thread Freshness Filtering

**User Story:** As an admin operator, I want to only see threads that are fresh enough to engage with, so that I do not waste generation tokens on threads that are likely locked, archived, or buried.

#### Acceptance Criteria

1. WHEN the Pipeline_Panel loads the thread list, THE Pipeline_Panel SHALL exclude threads where the original Reddit post time is older than 48 hours
2. WHEN the Pipeline_Panel loads the thread list, THE Pipeline_Panel SHALL display the age of each thread in human-readable format (e.g., "2h ago", "18h ago")
3. THE Pipeline_Panel SHALL sort threads with newer threads appearing higher in the list (within the same score tier)
4. WHEN a thread is between 36 and 48 hours old, THE Pipeline_Panel SHALL display a visual "aging" indicator warning that the thread may soon become stale

### Requirement 4: Scoring Cost Awareness

**User Story:** As an admin operator, I want to see how many threads will be scored and the estimated cost before triggering scoring, so that I can make an informed decision about whether to proceed.

#### Acceptance Criteria

1. WHEN the Pipeline_Panel loads, THE Pipeline_Panel SHALL display the count of unscored threads available for scoring
2. WHEN the unscored thread count is zero, THE Pipeline_Panel SHALL disable the Score button and display "Nothing to score"
3. WHEN the unscored thread count is greater than zero, THE Pipeline_Panel SHALL display the estimated scoring cost (unscored_count × $0.0003) next to the Score button
4. WHEN scoring completes, THE Pipeline_Panel SHALL display the number of threads scored, the number tagged "engage", and the actual duration

### Requirement 5: Phase-Aware Subreddit Filtering

**User Story:** As an admin operator, I want the thread list to only show threads from subreddits that this avatar is allowed to post in based on its warming phase, so that I cannot accidentally generate a comment that violates phase rules.

#### Acceptance Criteria

1. WHILE the avatar is in Phase 1, THE Pipeline_Panel SHALL only display threads from hobby subreddits assigned to the avatar
2. WHILE the avatar is in Phase 2, THE Pipeline_Panel SHALL only display threads from hobby subreddits and business subreddits assigned to the avatar or its client
3. WHILE the avatar is in Phase 3, THE Pipeline_Panel SHALL display threads from all subreddits assigned to the avatar or its client
4. WHILE the avatar is in Phase 1, THE Pipeline_Panel SHALL restrict comment type to "hobby" only (no professional or brand content)
5. THE Pipeline_Panel SHALL display the current phase restrictions as a visible label above the thread list

### Requirement 6: Subreddit Saturation Guard

**User Story:** As an admin operator, I want to see which subreddits are already at their daily limit for this avatar, so that I do not select a thread from a saturated subreddit.

#### Acceptance Criteria

1. WHEN the Pipeline_Panel loads the thread list, THE Pipeline_Panel SHALL visually mark threads from subreddits where the avatar has already posted MAX_COMMENTS_PER_SUBREDDIT_DAY (2) times today
2. WHEN a subreddit is at its daily limit for this avatar, THE Pipeline_Panel SHALL disable the Generate button for threads in that subreddit
3. THE Pipeline_Panel SHALL display the current post count per subreddit for today next to each subreddit badge in the thread list

### Requirement 7: Pre-Generation Safety Validation

**User Story:** As an admin operator, I want the system to validate all safety constraints before starting generation, so that I receive clear feedback about why generation cannot proceed rather than a generic "safety blocked" error after waiting.

#### Acceptance Criteria

1. WHEN the operator clicks Generate for a thread, THE Pipeline_Panel SHALL validate all safety constraints (daily limit, subreddit limit, time gap, phase rules) before calling the generation service
2. IF any safety constraint fails pre-validation, THEN THE Pipeline_Panel SHALL display a specific, actionable error message identifying which constraint failed and what the current values are
3. IF the MIN_MINUTES_BETWEEN_COMMENTS constraint fails, THEN THE Pipeline_Panel SHALL display the exact time remaining until the next comment is allowed
4. IF the MAX_COMMENTS_PER_SUBREDDIT_DAY constraint fails, THEN THE Pipeline_Panel SHALL identify the subreddit and its current count

### Requirement 8: Scrape Freshness and Rate Limiting

**User Story:** As an admin operator, I want the scrape step to show me which subreddits are already fresh and respect rate limits, so that I do not waste API calls or trigger Reddit rate limiting.

#### Acceptance Criteria

1. WHEN the Pipeline_Panel loads, THE Pipeline_Panel SHALL display the last scrape time for each subreddit
2. WHEN a subreddit was scraped less than 30 minutes ago, THE Pipeline_Panel SHALL mark it as "fresh" and indicate it will be skipped during scraping
3. THE Pipeline_Panel SHALL limit scraping to a maximum of 5 subreddits per request
4. WHEN all subreddits are already fresh (scraped within 30 minutes), THE Pipeline_Panel SHALL disable the Scrape button and display "All subreddits are fresh"
5. WHEN scraping completes, THE Pipeline_Panel SHALL display per-subreddit results including posts found, new posts saved, and duration

### Requirement 9: Today's Activity Summary

**User Story:** As an admin operator, I want to see a summary of what this avatar has already done today (via scheduler or manual pipeline), so that I have full context before generating additional comments.

#### Acceptance Criteria

1. WHEN the Pipeline_Panel loads, THE Budget_Dashboard SHALL display a list of comments generated today with their target subreddit, status (pending/approved/posted), and generation source (scheduler or manual)
2. WHEN the Pipeline_Panel loads, THE Budget_Dashboard SHALL display the timestamp of the most recent comment action for this avatar
3. WHEN comments were generated by the automated scheduler today, THE Budget_Dashboard SHALL clearly distinguish them from manually generated comments

### Requirement 10: Post-Generation Draft Handling

**User Story:** As an admin operator, I want the generated draft to be placed in the review queue with clear attribution, so that the review workflow remains consistent regardless of generation source.

#### Acceptance Criteria

1. WHEN generation completes successfully, THE Pipeline_Panel SHALL display the generated draft text inline with an option to edit before saving
2. WHEN generation completes successfully, THE Pipeline_Panel SHALL save the CommentDraft with status "pending" and source "manual_pipeline"
3. WHEN the operator edits the draft inline, THE Pipeline_Panel SHALL save the edited version and record the edit in the learning loop metadata
4. WHEN generation completes, THE Pipeline_Panel SHALL refresh the Budget_Dashboard to reflect the new comment in today's counts
5. IF generation fails due to an LLM error, THEN THE Pipeline_Panel SHALL display the error with a "Retry" button that does not re-validate safety (since validation already passed)

### Requirement 11: Thread Liveness Pre-Check

**User Story:** As an admin operator, I want the system to verify that a thread is still active on Reddit before generating a comment, so that generation tokens are not wasted on locked or removed threads.

#### Acceptance Criteria

1. WHEN the operator clicks Generate for a thread older than 12 hours, THE Pipeline_Panel SHALL perform a liveness check via the Reddit API before starting generation
2. IF the liveness check detects that the thread is locked, removed, or archived, THEN THE Pipeline_Panel SHALL display a warning and prevent generation
3. IF the liveness check detects a locked thread, THEN THE Pipeline_Panel SHALL update the thread's `is_locked` field in the database and remove it from the displayed list
4. WHEN the liveness check passes, THE Pipeline_Panel SHALL proceed with generation without additional delay
