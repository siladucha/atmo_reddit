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

1. WHEN the weekly rule extraction batch runs, THE Rule_Extractor SHALL fetch the sidebar description and the "rules" wiki page (if accessible) via PRAW for each subreddit that has at least one active ClientSubredditAssignment, processing subreddits sequentially with a 3-second delay between each
2. WHEN sidebar or wiki content is retrieved, THE Rule_Extractor SHALL concatenate the text (truncated to 4,000 characters if longer) and send it to Gemini Flash to extract structured rules, where each rule is a JSON object containing: category (String), description (String, max 200 characters), and threshold_value (String or null, e.g. "500" for min_karma)
3. THE Rule_Extractor SHALL categorize each extracted rule into one of: min_karma, min_account_age, no_self_promo, required_flair, posting_frequency_limit, content_restriction, or other
4. WHEN rule extraction completes for a subreddit, THE Rule_Extractor SHALL store the rules as a JSONB array (maximum 20 rules per subreddit) on the SubredditRiskProfile model with extraction timestamp and set extraction_status to "success"
5. IF the subreddit sidebar or wiki is empty or inaccessible (403, 404, timeout, or private subreddit), THEN THE Rule_Extractor SHALL log an activity event and mark the profile with extraction_status "no_content"
6. IF the LLM returns a response that fails Pydantic schema validation, THEN THE Rule_Extractor SHALL retry once after a 5-second delay; IF the retry also fails validation, THEN THE Rule_Extractor SHALL mark the profile with extraction_status "extraction_failed", log an activity event with the validation error, and continue processing the next subreddit without crashing the batch task
7. THE Rule_Extractor SHALL refresh rules weekly (Sunday 05:00 Asia/Jerusalem, after emotional profiles complete at 04:30)
8. WHEN rule extraction produces a result for a subreddit, THE Rule_Extractor SHALL preserve the previous extraction's rules until the new extraction succeeds, ensuring the Fitness Gate always has the most recent valid rule set available

### Requirement 2: Moderation Pattern Learning

**User Story:** As a platform operator, I want the system to learn subreddit moderation patterns from our avatars' historical posting outcomes, so that the risk profile reflects real-world moderator behavior.

#### Acceptance Criteria

1. WHEN computing the Moderation_Profile, THE RAMP_Platform SHALL aggregate KarmaSnapshot deletion data per subreddit over a rolling 30-day window
2. THE RAMP_Platform SHALL compute the Removal_Rate as the ratio of comments with is_deleted=true to total posted comments per subreddit
3. WHEN at least 10 posted comments exist for a subreddit in the 30-day window, THE RAMP_Platform SHALL compute hourly removal distribution and classify any hour with a removal rate exceeding 2x the subreddit's overall Removal_Rate as a Dangerous_Hour
4. THE RAMP_Platform SHALL compute a moderator aggressiveness level (low, medium, high, extreme) based on Removal_Rate thresholds: low (<10%), medium (10-25%), high (25-50%), extreme (>50%)
5. WHEN fewer than 5 posted comments exist for a subreddit in the 30-day window, THE RAMP_Platform SHALL mark the Moderation_Profile with confidence_level "insufficient_data"
6. WHEN between 5 and 9 posted comments exist for a subreddit in the 30-day window, THE RAMP_Platform SHALL mark the Moderation_Profile with confidence_level "low"
7. THE RAMP_Platform SHALL store removal reasons in the Moderation_Profile when a pattern (time-of-day, content type, or avatar karma level at posting time) accounts for at least 30% of total removals in that subreddit
8. THE RAMP_Platform SHALL recompute Moderation_Profiles weekly (Sunday 05:15, after rule extraction)

### Requirement 3: Avatar-Subreddit Fitness Gate

**User Story:** As a platform operator, I want a pre-generation safety gate that blocks avatar-subreddit pairings that are likely to result in removal, so that LLM tokens are not wasted on comments that will be deleted.

#### Acceptance Criteria

1. WHEN the pipeline selects a thread for comment generation, THE Fitness_Gate SHALL evaluate the assigned avatar against the thread's subreddit risk profile and produce a pass or block decision before calling the LLM
2. IF the avatar's current subreddit karma (from SubredditKarma.comment_karma) is less than the subreddit's extracted min_karma rule value, THEN THE Fitness_Gate SHALL block generation for that avatar-subreddit pair
3. IF the avatar's Reddit account age (computed as current time minus avatar.reddit_account_created) is less than the subreddit's extracted min_account_age rule value, THEN THE Fitness_Gate SHALL block generation for that avatar-subreddit pair
4. IF the avatar's reddit_account_created field is NULL, THEN THE Fitness_Gate SHALL skip the account age check and treat it as passed
5. IF the avatar's number of posted comments (status="posted") in the subreddit within the posting_frequency_limit's specified time window exceeds the extracted posting_frequency_limit threshold, THEN THE Fitness_Gate SHALL block generation for that avatar-subreddit pair
6. WHEN any extracted rule check fails, THE Fitness_Gate SHALL block generation and emit an activity event with event_type "fitness_gate_blocked" and the specific rule violation
7. WHEN the subreddit has moderator aggressiveness "extreme" and the avatar has fewer than 50 karma in that subreddit, THE Fitness_Gate SHALL block generation
8. WHILE the current hour (in the subreddit's dominant timezone as stored in the SubredditRiskProfile) is within identified Dangerous_Hours for a subreddit AND the avatar has fewer than 200 karma in that subreddit, THE Fitness_Gate SHALL block generation
9. THE Fitness_Gate SHALL compute an Avatar_Fitness_Score (0-100) for each avatar-subreddit pair using weighted factors: rule compliance pass/fail count (40%), karma headroom above min_karma (30%), and account age headroom above min_account_age (30%), and store it on the AvatarSubredditCompatibility model
10. IF no SubredditRiskProfile exists for the target subreddit, THEN THE Fitness_Gate SHALL allow generation (fail-open behavior) and emit an activity event with event_type "fitness_gate_warning" indicating missing risk profile

### Requirement 4: Dynamic Risk Score Computation

**User Story:** As a platform operator, I want each subreddit to have a dynamic risk score updated weekly from real deletion data, so that I can prioritize safe subreddits and identify deteriorating conditions.

#### Acceptance Criteria

1. THE RAMP_Platform SHALL compute a Risk_Score (0-100) for each subreddit with a SubredditRiskProfile, where 0 represents minimal risk and 100 represents maximum risk
2. THE RAMP_Platform SHALL weight the Risk_Score computation using four sub-scores each normalized to 0-100: Removal_Rate mapped linearly (0% removal = 0, 100% removal = 100) at 40% weight, moderator aggressiveness level mapped as (low=10, medium=40, high=70, extreme=100) at 25% weight, rule strictness count mapped as min(extracted_rules_count x 12, 100) at 20% weight, and historical trend direction computed as the slope of the previous 4 weeks of Risk_Scores mapped to 0-100 where positive slope = higher risk at 15% weight
3. WHEN a subreddit's Risk_Score increases by more than 15 points in a single weekly update, THE RAMP_Platform SHALL emit an activity event with event_type "risk_score_spike" including the subreddit name, previous score, new score, and delta
4. THE RAMP_Platform SHALL store the previous 12 weeks of Risk_Score values to enable trend visualization
5. THE RAMP_Platform SHALL recompute Risk_Scores weekly (Sunday 05:30, after moderation profile computation)
6. WHEN a subreddit's Risk_Score exceeds 80 after weekly recomputation, THE RAMP_Platform SHALL flag the subreddit as "high_risk" in the Subreddit model
7. IF the Moderation_Profile for a subreddit has confidence_level "insufficient_data" (fewer than 5 posted comments in the 30-day window), THEN THE RAMP_Platform SHALL assign a Risk_Score of 50 and mark the profile with confidence_level "insufficient_data" until sufficient data accumulates
8. WHEN a subreddit's Risk_Score drops to 80 or below after weekly recomputation AND the subreddit is currently flagged as "high_risk", THE RAMP_Platform SHALL clear the "high_risk" flag from the Subreddit model

### Requirement 5: Subreddit Risk Profile UI Page

**User Story:** As any authenticated user (admin, client_admin, client_manager, client_viewer), I want to view a Subreddit Risk Profile page showing extracted rules, risk scores, daily history, and recommendations, so that I can understand subreddit safety and make informed decisions.

#### Acceptance Criteria

1. THE Risk_Profile_Page SHALL be accessible to users with roles: owner, partner, client_admin, client_manager, client_viewer, and avatar_manager
2. THE Risk_Profile_Page SHALL display the subreddit's extracted rules as a formatted list with rule category, description, and extraction date
3. THE Risk_Profile_Page SHALL display the current Risk_Score (0-100) with a color-coded badge (green 0-30, yellow 31-60, orange 61-80, red 81-100)
4. THE Risk_Profile_Page SHALL display a Risk_Score trend line showing the past 12 weeks of weekly scores, rendering only the available data points when fewer than 12 weeks of history exist
5. THE Risk_Profile_Page SHALL display a daily history table showing: date, comments posted count, comments survived count, and Removal_Rate per day for the past 30 days, displaying rows only for days with at least one posted comment
6. THE Risk_Profile_Page SHALL display Avatar_Fitness_Scores for each avatar that is assigned to the subreddit, not frozen, not in Phase 0 (Mentor), and has warming_phase >= 1
7. THE Risk_Profile_Page SHALL display Moderation_Profile insights including Dangerous_Hours (displayed as hourly time ranges in the subreddit's dominant timezone) and content types that get removed (displayed as a list of content type labels with their removal percentages)
8. THE Risk_Profile_Page SHALL display a maximum of 5 AI-generated recommendations derived from the Moderation_Profile, each consisting of a single actionable sentence
9. WHEN the user's role is client_admin, client_manager, or client_viewer, THE Risk_Profile_Page SHALL scope the daily history and avatar fitness scores to only avatars assigned to the user's client
10. THE Risk_Profile_Page SHALL use HTMX partials for lazy-loading the daily history and trend chart sections, displaying a loading skeleton placeholder until the partial responds
11. IF no SubredditRiskProfile exists for the subreddit or the profile has confidence_level "insufficient_data", THEN THE Risk_Profile_Page SHALL display an informational message indicating that risk data is not yet available and show the next scheduled computation date
12. IF the Moderation_Profile has not been computed yet, THEN THE Risk_Profile_Page SHALL hide the recommendations and Dangerous_Hours sections and display a notice that moderation patterns require at least 5 posted comments before insights are available

### Requirement 6: Subreddit Risk Profile Data Model

**User Story:** As a developer, I want a dedicated SubredditRiskProfile model that stores all risk intelligence per subreddit, so that the data is structured and queryable by the UI and pipeline services.

#### Acceptance Criteria

1. THE RAMP_Platform SHALL store SubredditRiskProfile with a one-to-one relationship to the Subreddit model (linked by subreddit_id foreign key with ON DELETE CASCADE)
2. THE SubredditRiskProfile model SHALL include fields: risk_score (Integer 0-100, CHECK constraint, default 50), risk_score_history (JSONB array of weekly scores, default empty array), extracted_rules (JSONB array, default empty array), moderation_profile (JSONB, default empty object), dangerous_hours (JSONB array, default empty array), recommendations (JSONB array, default empty array), last_rule_extraction_at (DateTime, nullable), last_profile_computed_at (DateTime, nullable), confidence_level (String, one of: "insufficient_data", "low", "medium", "high", default "insufficient_data"), extraction_status (String, one of: "pending", "success", "no_content", "extraction_failed", default "pending"), and dominant_timezone (String, default "UTC")
3. THE RAMP_Platform SHALL store daily posting statistics in a SubredditDailyStats model with fields: subreddit_id (ForeignKey, NOT NULL), date (Date, NOT NULL), comments_posted (Integer, default 0), comments_survived (Integer, default 0), removal_rate (Float, computed as 1 - comments_survived/comments_posted), computed_at (DateTime), with a UNIQUE constraint on (subreddit_id, date)
4. THE RAMP_Platform SHALL store avatar fitness scores in the existing AvatarSubredditCompatibility model by adding a fitness_score (Integer 0-100, nullable) field alongside the existing emotional compatibility score
5. THE RAMP_Platform SHALL create database indexes on SubredditRiskProfile.risk_score, SubredditDailyStats(subreddit_id, date), and SubredditRiskProfile.extraction_status for efficient UI queries and batch processing

### Requirement 7: Weekly Batch Orchestration

**User Story:** As a platform operator, I want the risk profile computation to run as a weekly Celery Beat task with proper ordering and error resilience, so that it integrates with the existing Sunday maintenance window.

#### Acceptance Criteria

1. THE RAMP_Platform SHALL schedule the full risk profile refresh as a Celery Beat task chain on Sundays (Asia/Jerusalem timezone): rule extraction at 05:00, moderation profile at 05:15, risk score computation at 05:30, processing all subreddits that have at least one active ClientSubredditAssignment
2. WHEN a subreddit's rule extraction fails due to any exception (PRAW error, LLM failure, or timeout), THE RAMP_Platform SHALL log the failure as an activity event with the subreddit name and error category, then continue processing the remaining subreddits without aborting the batch
3. THE RAMP_Platform SHALL process subreddits sequentially with a 3-second delay between each to respect Reddit API rate limits
4. WHEN a batch phase (rule extraction, moderation profile, or risk score computation) completes, THE RAMP_Platform SHALL emit an activity event of type "risk_profile_batch" with summary statistics including: subreddits processed count, successful count, failure count, and total duration in seconds
5. IF more than 50% of subreddits fail extraction in a single batch run, THEN THE RAMP_Platform SHALL pause for 120 seconds, then resume processing the remaining subreddits from where it stopped (circuit breaker pattern)
6. THE RAMP_Platform SHALL acquire a distributed lock with key "risk_profile_batch" and TTL of 1800 seconds before starting the batch
7. IF the distributed lock cannot be acquired (another batch instance is already running), THEN THE RAMP_Platform SHALL log a warning activity event and abort the current invocation without processing any subreddits

### Requirement 8: Integration with Existing Pipeline

**User Story:** As a platform operator, I want the Fitness Gate to integrate with the existing Smart Scoring and EPG pipeline, so that unsafe pairings are blocked before LLM generation without disrupting the established workflow.

#### Acceptance Criteria

1. THE Fitness_Gate SHALL execute after Smart Scoring selects candidate threads and before comment generation is dispatched, evaluating each avatar-thread pair in the engage list returned by Smart Scoring
2. WHEN the Fitness_Gate blocks a thread for an avatar, THE RAMP_Platform SHALL decrement the avatar's remaining budget for that pipeline run by 1 (the thread counts as consumed but no draft is generated), and the blocked thread SHALL NOT be re-evaluated in subsequent pipeline runs on the same calendar day
3. WHEN the Fitness_Gate blocks a thread, THE RAMP_Platform SHALL log an ActivityEvent with event_type "fitness_block" containing: avatar username, thread identifier, subreddit name, the rule name that triggered the block, and a human-readable explanation of why the pairing was rejected
4. THE RAMP_Platform SHALL expose a system setting "fitness_gate_enabled" (default: true) to allow disabling the gate without code changes; WHILE "fitness_gate_enabled" is set to false, THE Fitness_Gate SHALL be skipped entirely and all Smart Scoring engage results SHALL pass through to generation unfiltered
5. THE Fitness_Gate SHALL add no more than 50ms latency per thread evaluation (fitness check uses only cached/DB data, no external API calls at evaluation time)
6. IF the Fitness_Gate blocks all engage threads for an avatar in a pipeline run, THEN THE RAMP_Platform SHALL log an ActivityEvent with event_type "fitness_zero_eligible" indicating the avatar had candidates but none passed the fitness check, and the avatar's budget SHALL reflect all blocked threads as consumed
