# Requirements Document

## Introduction

The Subreddit Risk Profile system provides unified intelligence about subreddit moderation behavior, rule compliance, and avatar-subreddit safety. It builds on existing systems (Emotional Profiles, KarmaSnapshot/deletion detection, Hot Thread Filter) to systematically reduce comment removals by extracting subreddit rules, learning moderation patterns, gating unsafe avatar-subreddit pairings before generation, and presenting actionable intelligence through a dedicated UI page. The goal is fewer demotions, more stable pipeline throughput, and better client outcomes.

## Glossary

- **Rule_Extractor**: The service that fetches subreddit sidebar and wiki content via PRAW and uses an LLM to parse formalized moderation rules
- **Moderation_Profile**: A per-subreddit data structure that aggregates deletion rates, removal patterns, dangerous posting hours, and moderator aggressiveness based on historical KarmaSnapshot data
- **Fitness_Gate**: A pre-generation safety check that evaluates whether a specific avatar is safe to post in a specific subreddit based on karma, account age, posting history, and extracted rules
- **Risk_Score**: A numeric value (0-100) representing the overall risk level of a subreddit for the platform's avatars, updated weekly from real deletion and shadowban data
- **Risk_Profile_Page**: The admin/portal UI page displaying subreddit intelligence including extracted rules, risk score with trend, daily history, avatar compatibility, and moderation pattern insights
- **Dangerous_Hours**: Time windows (in the subreddit's dominant timezone) when moderation activity is highest and removal probability increases
- **Subreddit_Rule**: A single formalized rule extracted from a subreddit's sidebar or wiki (e.g., minimum karma requirement, no self-promotion, required flair)
- **Avatar_Fitness_Score**: A compatibility score (0-100) that evaluates how safe a specific avatar is for posting in a specific subreddit based on current karma, age, and rule compliance
- **Removal_Rate**: The percentage of posted comments that were deleted by moderators within a subreddit over a given time window
- **RAMP_Platform**: The Reddit Marketing Platform system being developed

## Requirements

### Requirement 1: Subreddit Rule Extraction

**User Story:** As a platform operator, I want the system to automatically extract and formalize subreddit moderation rules from sidebar and wiki content, so that avatars can be checked against known restrictions before commenting.

#### Acceptance Criteria

1. WHEN a subreddit has an active ClientSubredditAssignment, THE Rule_Extractor SHALL fetch the subreddit's sidebar description and wiki pages via PRAW
2. WHEN sidebar or wiki content is retrieved, THE Rule_Extractor SHALL send the raw text to an LLM (Gemini Flash) to extract structured rules
3. THE Rule_Extractor SHALL categorize each extracted rule into one of: min_karma, min_account_age, no_self_promo, required_flair, posting_frequency_limit, content_restriction, or other
4. WHEN rule extraction completes, THE Rule_Extractor SHALL store the rules as a JSONB array on the SubredditRiskProfile model with extraction timestamp
5. IF the subreddit sidebar or wiki is empty or inaccessible, THEN THE Rule_Extractor SHALL log an activity event and mark the profile with extraction_status "no_content"
6. IF the LLM returns a malformed response during extraction, THEN THE Rule_Extractor SHALL retry once and log the failure without crashing the batch task
7. THE Rule_Extractor SHALL refresh rules weekly (Sunday 05:00, after emotional profiles complete)
8. FOR ALL valid subreddit sidebar text inputs, extracting rules then formatting rules back to natural language then re-extracting SHALL produce equivalent rule sets (round-trip property)

### Requirement 2: Moderation Pattern Learning

**User Story:** As a platform operator, I want the system to learn subreddit moderation patterns from our avatars' historical posting outcomes, so that the risk profile reflects real-world moderator behavior.

#### Acceptance Criteria

1. WHEN computing the Moderation_Profile, THE RAMP_Platform SHALL aggregate KarmaSnapshot deletion data per subreddit over a rolling 30-day window
2. THE RAMP_Platform SHALL compute the Removal_Rate as the ratio of comments with is_deleted=true to total posted comments per subreddit
3. WHEN at least 10 posted comments exist for a subreddit in the 30-day window, THE RAMP_Platform SHALL compute hourly removal distribution to identify Dangerous_Hours
4. THE RAMP_Platform SHALL compute a moderator aggressiveness level (low, medium, high, extreme) based on Removal_Rate thresholds: low (<10%), medium (10-25%), high (25-50%), extreme (>50%)
5. WHEN fewer than 5 posted comments exist for a subreddit in the 30-day window, THE RAMP_Platform SHALL mark the Moderation_Profile with confidence_level "insufficient_data"
6. THE RAMP_Platform SHALL store typical removal reasons (extracted from patterns: time-of-day, content type, avatar karma level at posting time) in the Moderation_Profile
7. THE RAMP_Platform SHALL recompute Moderation_Profiles weekly (Sunday 05:15, after rule extraction)

### Requirement 3: Avatar-Subreddit Fitness Gate

**User Story:** As a platform operator, I want a pre-generation safety gate that blocks avatar-subreddit pairings that are likely to result in removal, so that LLM tokens are not wasted on comments that will be deleted.

#### Acceptance Criteria

1. WHEN the pipeline selects a thread for comment generation, THE Fitness_Gate SHALL evaluate the assigned avatar against the thread's subreddit risk profile before calling the LLM
2. THE Fitness_Gate SHALL check the avatar's current subreddit karma against the subreddit's extracted min_karma rule
3. THE Fitness_Gate SHALL check the avatar's Reddit account age against the subreddit's extracted min_account_age rule
4. THE Fitness_Gate SHALL check the avatar's posting frequency in the subreddit against extracted posting_frequency_limit rules
5. WHEN any extracted rule check fails, THE Fitness_Gate SHALL block generation and emit an activity event with event_type "fitness_gate_blocked" and the specific rule violation
6. WHEN the subreddit has moderator aggressiveness "extreme" and the avatar has fewer than 50 karma in that subreddit, THE Fitness_Gate SHALL block generation
7. WHILE the current hour is within identified Dangerous_Hours for a subreddit AND the avatar has fewer than 200 karma in that subreddit, THE Fitness_Gate SHALL block generation
8. THE Fitness_Gate SHALL compute an Avatar_Fitness_Score (0-100) for each avatar-subreddit pair and store it on a model accessible to the UI
9. IF no SubredditRiskProfile exists for the target subreddit, THEN THE Fitness_Gate SHALL allow generation (fail-open behavior) and log a warning

### Requirement 4: Dynamic Risk Score Computation

**User Story:** As a platform operator, I want each subreddit to have a dynamic risk score updated weekly from real deletion data, so that I can prioritize safe subreddits and identify deteriorating conditions.

#### Acceptance Criteria

1. THE RAMP_Platform SHALL compute a Risk_Score (0-100) for each subreddit with a SubredditRiskProfile, where 0 represents minimal risk and 100 represents maximum risk
2. THE RAMP_Platform SHALL weight the Risk_Score computation using: Removal_Rate (40%), moderator aggressiveness level (25%), rule strictness count (20%), and historical trend direction (15%)
3. WHEN a subreddit's Risk_Score increases by more than 15 points in a single weekly update, THE RAMP_Platform SHALL emit an activity event with event_type "risk_score_spike" including the subreddit name and delta
4. THE RAMP_Platform SHALL store the previous 12 weeks of Risk_Score values to enable trend visualization
5. THE RAMP_Platform SHALL recompute Risk_Scores weekly (Sunday 05:30, after moderation profile computation)
6. WHEN a subreddit's Risk_Score exceeds 80, THE RAMP_Platform SHALL flag the subreddit as "high_risk" in the Subreddit model

### Requirement 5: Subreddit Risk Profile UI Page

**User Story:** As any authenticated user (admin, client_admin, client_manager, client_viewer), I want to view a Subreddit Risk Profile page showing extracted rules, risk scores, daily history, and recommendations, so that I can understand subreddit safety and make informed decisions.

#### Acceptance Criteria

1. THE Risk_Profile_Page SHALL be accessible to users with roles: owner, partner, client_admin, client_manager, client_viewer, and avatar_manager
2. THE Risk_Profile_Page SHALL display the subreddit's extracted rules as a formatted list with rule category, description, and extraction date
3. THE Risk_Profile_Page SHALL display the current Risk_Score (0-100) with a color-coded badge (green 0-30, yellow 31-60, orange 61-80, red 81-100)
4. THE Risk_Profile_Page SHALL display a Risk_Score trend line showing the past 12 weeks of weekly scores
5. THE Risk_Profile_Page SHALL display a daily history table showing: date, comments posted count, comments survived count, and Removal_Rate per day for the past 30 days
6. THE Risk_Profile_Page SHALL display Avatar_Fitness_Scores for each avatar currently active in that subreddit
7. THE Risk_Profile_Page SHALL display Moderation_Profile insights including Dangerous_Hours and content types that get removed
8. THE Risk_Profile_Page SHALL display AI-generated recommendations (e.g., "avoid posting before 10am", "minimum 100 karma recommended") based on the Moderation_Profile
9. WHEN the user's role is client_admin, client_manager, or client_viewer, THE Risk_Profile_Page SHALL scope the daily history and avatar scores to only avatars assigned to the user's client
10. THE Risk_Profile_Page SHALL use HTMX partials for lazy-loading the daily history and trend chart sections

### Requirement 6: Subreddit Risk Profile Data Model

**User Story:** As a developer, I want a dedicated SubredditRiskProfile model that stores all risk intelligence per subreddit, so that the data is structured and queryable by the UI and pipeline services.

#### Acceptance Criteria

1. THE RAMP_Platform SHALL store SubredditRiskProfile with a one-to-one relationship to the Subreddit model (linked by subreddit_id)
2. THE SubredditRiskProfile model SHALL include fields: risk_score (Integer 0-100), risk_score_history (JSONB array of weekly scores), extracted_rules (JSONB array), moderation_profile (JSONB), dangerous_hours (JSONB array), recommendations (JSONB array), last_rule_extraction_at (DateTime), last_profile_computed_at (DateTime), confidence_level (String), and extraction_status (String)
3. THE RAMP_Platform SHALL store daily posting statistics in a SubredditDailyStats model with fields: subreddit_id, date, comments_posted, comments_survived, removal_rate, computed_at
4. THE RAMP_Platform SHALL store avatar fitness scores in the existing AvatarSubredditCompatibility model by adding a fitness_score (Integer 0-100) field alongside the existing emotional compatibility score
5. THE RAMP_Platform SHALL create database indexes on SubredditRiskProfile.risk_score and SubredditDailyStats(subreddit_id, date) for efficient UI queries

### Requirement 7: Weekly Batch Orchestration

**User Story:** As a platform operator, I want the risk profile computation to run as a weekly Celery Beat task with proper ordering and error resilience, so that it integrates with the existing Sunday maintenance window.

#### Acceptance Criteria

1. THE RAMP_Platform SHALL schedule the full risk profile refresh as a Celery Beat task chain on Sundays: rule extraction at 05:00, moderation profile at 05:15, risk score computation at 05:30
2. WHEN a subreddit's rule extraction fails, THE RAMP_Platform SHALL continue processing the remaining subreddits without aborting the batch
3. THE RAMP_Platform SHALL process subreddits sequentially with a 3-second delay between each to respect Reddit API rate limits
4. THE RAMP_Platform SHALL emit an activity event on batch completion with summary statistics (subreddits processed, rules extracted, profiles computed, failures)
5. IF more than 50% of subreddits fail extraction in a single batch run, THEN THE RAMP_Platform SHALL pause for 120 seconds before continuing (circuit breaker pattern)
6. THE RAMP_Platform SHALL use a distributed lock to prevent concurrent batch executions

### Requirement 8: Integration with Existing Pipeline

**User Story:** As a platform operator, I want the Fitness Gate to integrate with the existing Smart Scoring and EPG pipeline, so that unsafe pairings are blocked before LLM generation without disrupting the established workflow.

#### Acceptance Criteria

1. THE Fitness_Gate SHALL execute after Smart Scoring selects candidate threads and before comment generation is dispatched
2. WHEN the Fitness_Gate blocks a thread for an avatar, THE RAMP_Platform SHALL decrement the avatar's remaining budget for that pipeline run (thread is consumed but not generated)
3. THE Fitness_Gate SHALL log blocked threads in the activity feed with sufficient context for the operator to understand the block reason
4. THE RAMP_Platform SHALL expose a system setting "fitness_gate_enabled" (default: true) to allow disabling the gate without code changes
5. THE Fitness_Gate SHALL add no more than 50ms latency per thread evaluation (fitness check uses only cached/DB data, no external API calls at evaluation time)
