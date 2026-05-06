# Requirements Document

## Introduction

This feature introduces subreddit-specific karma tracking for avatars. Currently the system tracks only total Reddit karma (comment + post) at the account level. Operators need visibility into how much karma each avatar has earned in each specific subreddit to make informed decisions about phase eligibility, posting strategy, and avatar health. Subreddit-specific karma enables more granular phase eligibility checks, smarter avatar-to-subreddit assignment, and better operational transparency.

## Glossary

- **Avatar**: A managed Reddit account used for persona-based commenting across subreddits.
- **Subreddit_Karma_Record**: A data record storing the karma an avatar has accumulated in a specific subreddit, including comment karma, post karma, and the timestamp of the last update.
- **Karma_Tracker**: The service component responsible for collecting, computing, and persisting subreddit-specific karma data from Reddit API responses and internal comment performance data.
- **Phase_Evaluator**: The service component that determines whether an avatar meets criteria for promotion to the next warming phase.
- **Avatar_Detail_Page**: The admin panel page displaying comprehensive information about a single avatar, including health, phase progress, and activity history.
- **Review_Queue**: The admin interface where operators approve, reject, or edit AI-generated comment drafts before manual posting.
- **Operations_Dashboard**: The main admin panel page showing system-wide health, client status, and avatar summaries.
- **Karma_Breakdown_Widget**: A UI component that displays per-subreddit karma distribution for an avatar.

## Requirements

### Requirement 1: Subreddit Karma Data Model

**User Story:** As a system administrator, I want the system to store karma per subreddit for each avatar, so that granular karma data is available for display and business logic.

#### Acceptance Criteria

1. THE Subreddit_Karma_Record SHALL store avatar_id, subreddit_name, comment_karma, post_karma, last_updated_at, and comment_count fields.
2. WHEN a Subreddit_Karma_Record is created, THE Karma_Tracker SHALL enforce a unique constraint on the combination of avatar_id and subreddit_name.
3. THE Subreddit_Karma_Record SHALL use Integer type for comment_karma and post_karma with a default value of 0.
4. WHEN a Subreddit_Karma_Record is queried, THE System SHALL support filtering by avatar_id and ordering by total karma (comment_karma + post_karma) descending.

### Requirement 2: Karma Collection from Comment Performance

**User Story:** As a system operator, I want subreddit-specific karma to be updated automatically when comment performance data is available, so that karma records stay current without manual intervention.

#### Acceptance Criteria

1. WHEN a CommentDraft status changes to "posted" and a reddit_score is recorded, THE Karma_Tracker SHALL increment the comment_karma for the corresponding avatar and subreddit combination.
2. WHEN the Karma_Tracker updates a Subreddit_Karma_Record, THE Karma_Tracker SHALL set last_updated_at to the current UTC timestamp.
3. WHEN a CommentDraft has reddit_score recorded and no Subreddit_Karma_Record exists for that avatar-subreddit pair, THE Karma_Tracker SHALL create a new Subreddit_Karma_Record with comment_karma set to the reddit_score value.
4. WHEN the reddit_score of a previously tracked comment changes, THE Karma_Tracker SHALL update the corresponding Subreddit_Karma_Record to reflect the delta.
5. THE Karma_Tracker SHALL increment comment_count by 1 for each posted comment in the subreddit regardless of reddit_score value.

### Requirement 3: Karma Collection from Reddit Status Check

**User Story:** As a system operator, I want the Reddit status check to attempt fetching per-subreddit karma breakdown when available, so that karma records reflect actual Reddit data.

#### Acceptance Criteria

1. WHEN the Reddit status check runs for an avatar, THE Karma_Tracker SHALL attempt to derive per-subreddit karma from the avatar's recent comment history via the Reddit API.
2. IF the Reddit API does not provide per-subreddit karma breakdown, THEN THE Karma_Tracker SHALL fall back to computing subreddit karma from internally tracked comment performance data only.
3. WHEN per-subreddit karma data is successfully fetched from Reddit, THE Karma_Tracker SHALL update all corresponding Subreddit_Karma_Records for that avatar.
4. THE Karma_Tracker SHALL log an ActivityEvent with event_type "karma_sync" after each successful subreddit karma update batch.

### Requirement 4: Display Karma Breakdown on Avatar Detail Page

**User Story:** As an operator, I want to see a per-subreddit karma breakdown on the avatar detail page, so that I can assess avatar strength in each community.

#### Acceptance Criteria

1. WHEN an operator views the Avatar_Detail_Page, THE Karma_Breakdown_Widget SHALL display a table of subreddits with columns: subreddit name, comment karma, post karma, total karma, and comment count.
2. THE Karma_Breakdown_Widget SHALL sort subreddits by total karma descending by default.
3. WHEN an avatar has no Subreddit_Karma_Records, THE Karma_Breakdown_Widget SHALL display a message indicating no per-subreddit karma data is available.
4. THE Karma_Breakdown_Widget SHALL display the last_updated_at timestamp for each subreddit entry as a relative time (e.g., "2h ago", "3d ago").
5. THE Karma_Breakdown_Widget SHALL visually distinguish hobby subreddits from professional subreddits using color coding or labels.

### Requirement 5: Display Subreddit Karma in Avatar List Views

**User Story:** As an operator, I want to see a summary of subreddit karma distribution in avatar list views, so that I can quickly identify avatar strengths across communities.

#### Acceptance Criteria

1. WHEN avatars are displayed in the admin avatars table, THE System SHALL show the top 3 subreddits by karma as a compact summary next to the total karma value.
2. WHEN avatars are displayed in the admin avatars grid (card view), THE System SHALL show the top subreddit name and karma value on each avatar card.
3. WHEN an avatar has no Subreddit_Karma_Records, THE System SHALL display only the total karma without subreddit breakdown.

### Requirement 6: Display Subreddit Karma in Review Queue

**User Story:** As an operator reviewing a comment draft, I want to see the avatar's karma in the target subreddit, so that I can assess whether the avatar has sufficient credibility in that community.

#### Acceptance Criteria

1. WHEN a comment draft is displayed in the Review_Queue, THE System SHALL show the posting avatar's karma in the target subreddit alongside the draft.
2. WHEN the avatar has zero karma in the target subreddit, THE System SHALL display a warning indicator with text "No karma in this subreddit".
3. WHEN the avatar's karma in the target subreddit is below 10, THE System SHALL display a caution indicator with text "Low karma in r/{subreddit_name}".
4. THE System SHALL display the avatar's subreddit-specific karma as "{comment_karma} comment / {post_karma} post" format.

### Requirement 7: Subreddit Karma in Phase Eligibility Evaluation

**User Story:** As a system operator, I want phase eligibility to consider subreddit-specific karma distribution, so that avatars are promoted only when they have demonstrated credibility across multiple communities.

#### Acceptance Criteria

1. WHEN the Phase_Evaluator checks promotion eligibility from Phase 1 to Phase 2, THE Phase_Evaluator SHALL require the avatar to have positive karma in at least 2 distinct subreddits.
2. WHEN the Phase_Evaluator checks promotion eligibility from Phase 2 to Phase 3, THE Phase_Evaluator SHALL require the avatar to have positive karma in at least 3 distinct subreddits, including at least 1 professional subreddit.
3. THE Phase_Evaluator SHALL include subreddit karma distribution in the criteria_values dictionary returned by check_promotion_eligibility.
4. WHEN an avatar does not meet the subreddit karma distribution requirement, THE Phase_Evaluator SHALL report the specific shortfall (e.g., "karma in 1/2 required subreddits").

### Requirement 8: Subreddit Karma in Persona Selection

**User Story:** As a system operator, I want the persona selection logic to consider subreddit-specific karma when choosing which avatar should comment in a thread, so that avatars with established credibility in the target subreddit are preferred.

#### Acceptance Criteria

1. WHEN the generation service selects a persona for a thread, THE System SHALL include the avatar's karma in the target subreddit as a selection factor.
2. WHEN multiple avatars are eligible for a thread, THE System SHALL prefer avatars with higher karma in the target subreddit over avatars with zero karma in that subreddit.
3. THE System SHALL include subreddit_karma in the persona data passed to the LLM persona selection prompt.

### Requirement 9: Subreddit Karma on Operations Dashboard

**User Story:** As an operator, I want the operations dashboard avatar health summary to include subreddit karma distribution alerts, so that I can identify avatars that need karma diversification.

#### Acceptance Criteria

1. WHEN the Operations_Dashboard displays avatar health, THE System SHALL flag avatars that have all karma concentrated in a single subreddit as "low diversity".
2. WHEN an avatar has karma in only 1 subreddit and is in Phase 1 or Phase 2, THE System SHALL display a recommendation to diversify karma across more subreddits.
3. THE Operations_Dashboard SHALL include a "karma diversity" metric in the avatar health summary showing the count of subreddits with positive karma for each avatar.

### Requirement 10: Subreddit Karma on Client Hub Avatar Section

**User Story:** As an operator viewing a client's assigned avatars, I want to see how each avatar's karma is distributed across the client's professional subreddits, so that I can assess coverage and readiness.

#### Acceptance Criteria

1. WHEN avatars are displayed on the client hub page, THE System SHALL show each avatar's karma in the client's assigned professional subreddits.
2. WHEN an avatar has zero karma in one of the client's professional subreddits, THE System SHALL highlight that subreddit as "not warmed" for that avatar.
3. THE System SHALL display a coverage indicator showing what percentage of the client's professional subreddits have positive avatar karma.

### Requirement 11: Subreddit Karma History Tracking

**User Story:** As an operator, I want to see how subreddit-specific karma changes over time, so that I can monitor avatar growth trajectory in each community.

#### Acceptance Criteria

1. WHEN the Karma_Tracker updates a Subreddit_Karma_Record, THE Karma_Tracker SHALL preserve the previous karma value to enable delta computation.
2. THE Avatar_Detail_Page SHALL display the karma change (delta) for each subreddit since the last update.
3. WHEN a subreddit's karma decreases between updates, THE System SHALL display the decrease with a negative indicator and red color.
4. WHEN a subreddit's karma increases between updates, THE System SHALL display the increase with a positive indicator and green color.
