# Requirements Document

## Introduction

The Avatar Warming Phases feature replaces the existing binary 14-day warmup check with a formal 3-phase progression model. Each avatar progresses through Phase 1 (Credibility Building), Phase 2 (Content Seeding), and Phase 3 (Brand Integration) based on measurable eligibility criteria including both quantity and quality signals. Phase gates control what content types are permitted, ensuring avatars build authentic credibility before any brand-adjacent activity occurs. The system supports automatic promotion and demotion, on-demand eligibility checks, and a ramp-up period after Phase 3 promotion to prevent sudden brand saturation.

## Glossary

- **Phase_Gate**: A set of eligibility criteria that must all be satisfied before an avatar can transition from one phase to the next
- **Avatar**: A managed Reddit account used for community engagement, tracked in the `avatars` table
- **PhaseEvaluator**: The component responsible for evaluating phase eligibility gate checks (quality metrics, age, karma, activity)
- **PhasePolicy**: The component responsible for determining content restriction rules per phase (what content types and subreddits are allowed)
- **PhaseTransitionManager**: The component responsible for executing phase transitions (promotions, demotions) and recording Phase_Transition_Events
- **Phase_Service**: The logical grouping of PhaseEvaluator, PhasePolicy, and PhaseTransitionManager that together manage the warming phase lifecycle
- **Safety_Service**: The existing service (`app/services/safety.py`) that enforces rate limits and content safety checks before allowing an avatar to post
- **Reddit_Account_Age**: The number of days since the Reddit account was created, derived from `reddit_account_created` field (not `created_at`)
- **Combined_Karma**: The sum of `reddit_karma_comment` and `reddit_karma_post` as reported by the Reddit API
- **Brand_Mention_Level**: The classification tier of brand-related content: `explicit_brand_link` (URL matching client's brand domain), `explicit_brand_name` (string match of brand name in comment text), or `inferred_brand` (AI-classified as brand-adjacent)
- **Activity_Count**: The total number of comments with status "approved" or "posted" attributed to an avatar within a given time window
- **Comment_Survival_Rate**: The percentage of an avatar's comments that have not been deleted by Reddit within a given time window, calculated as (total_posted - deleted) / total_posted
- **Avg_Comment_Score**: The mean upvote score across an avatar's comments within a given time window, as reported by the Reddit API
- **Phase_Transition_Event**: An ActivityEvent record logged when an avatar moves from one phase to another (promotion, demotion, or override)
- **Admin_Override**: A manual action by a superuser to promote or demote an avatar's phase regardless of eligibility criteria
- **Ramp_Up_Period**: The 7-day period after Phase 3 promotion during which brand mention allowances are gradually increased
- **Transition_Lock**: A per-avatar mutex that prevents concurrent phase transitions from racing (e.g., daily batch and on-demand check both trying to promote simultaneously)
- **Policy_Block_Event**: An ActivityEvent record logged when the PhasePolicy blocks a comment, capturing the restriction rule, phase, and brand mention level for operational visibility

## Requirements

### Requirement 1: Phase Model Storage

**User Story:** As a system administrator, I want each avatar to have a persisted warming phase, so that the system can enforce phase-appropriate content restrictions across restarts and deployments.

#### Acceptance Criteria

1. THE Avatar model SHALL store a `warming_phase` field with allowed values of 1, 2, or 3
2. THE Avatar model SHALL store a `phase_changed_at` timestamp recording when the current phase was assigned
3. WHEN a new avatar is created, THE system SHALL assign `warming_phase` = 1 and `phase_changed_at` = current UTC time
4. THE database migration SHALL set `warming_phase` = 1 for all existing avatars that have a Reddit account age below 60 days
5. THE database migration SHALL set `warming_phase` = 2 for all existing avatars that have a Reddit account age of 60 days or more (Phase 3 is only achievable through post-migration evaluation, regardless of karma or other criteria)
6. THE Avatar model SHALL store a `last_phase_evaluated_at` timestamp recording when the PhaseEvaluator last ran eligibility checks for this avatar (used for on-demand evaluation cooldown)

### Requirement 2: Phase 1 Content Restrictions

**User Story:** As a system operator, I want Phase 1 avatars restricted to hobby and general professional subreddits with zero brand mentions, so that new accounts build authentic credibility.

#### Acceptance Criteria

1. WHILE an avatar is in Phase 1, THE PhasePolicy SHALL block all comments of type "professional"
2. WHILE an avatar is in Phase 1, THE PhasePolicy SHALL block all comments targeting subreddits listed in the avatar's `business_subreddits` field
3. WHILE an avatar is in Phase 1, THE PhasePolicy SHALL allow comments of type "hobby" targeting subreddits listed in the avatar's `hobby_subreddits` field
4. WHILE an avatar is in Phase 1, THE PhasePolicy SHALL block any comment containing a Brand_Mention_Level of `explicit_brand_link`, `explicit_brand_name`, or `inferred_brand`
5. WHILE an avatar is in Phase 1, THE PhasePolicy SHALL enforce a maximum of 3 comments per day (warmup rate limit)

### Requirement 3: Phase 2 Content Restrictions

**User Story:** As a system operator, I want Phase 2 avatars to create content and cite external sources without direct brand links or explicit brand names, so that they establish topical authority before brand integration.

#### Acceptance Criteria

1. WHILE an avatar is in Phase 2, THE PhasePolicy SHALL allow comments of type "professional" that do not contain a Brand_Mention_Level of `explicit_brand_link` or `explicit_brand_name`
2. WHILE an avatar is in Phase 2, THE PhasePolicy SHALL allow comments targeting subreddits in both `hobby_subreddits` and `business_subreddits`
3. WHILE an avatar is in Phase 2, THE PhasePolicy SHALL block any comment containing a Brand_Mention_Level of `explicit_brand_link` (URL pointing to the client's brand domain)
4. WHILE an avatar is in Phase 2, THE PhasePolicy SHALL block any comment containing a Brand_Mention_Level of `explicit_brand_name` (string match of brand name)
5. WHILE an avatar is in Phase 2, THE PhasePolicy SHALL flag comments classified as `inferred_brand` with status `requires_review` (human approval required before posting) rather than blocking or auto-approving them
6. WHILE an avatar is in Phase 2, THE PhasePolicy SHALL allow external source citations (URLs not belonging to the client's brand domain)
7. WHILE an avatar is in Phase 2, THE PhasePolicy SHALL enforce the standard daily comment limit (MAX_COMMENTS_PER_DAY)

### Requirement 4: Phase 3 Content Restrictions

**User Story:** As a system operator, I want Phase 3 avatars to integrate brand mentions only when contextually appropriate and within ratio limits, so that brand presence remains natural.

#### Acceptance Criteria

1. WHILE an avatar is in Phase 3, THE PhasePolicy SHALL allow comments of type "professional" including all Brand_Mention_Levels
2. WHILE an avatar is in Phase 3, THE PhasePolicy SHALL enforce the existing MAX_BRAND_RATIO (30% brand-related comments per week) subject to Ramp_Up_Period restrictions
3. WHILE an avatar is in Phase 3, THE PhasePolicy SHALL enforce the existing BRAND_MENTION_COOLDOWN_HOURS (72 hours between brand-adjacent comments)
4. WHILE an avatar is in Phase 3, THE PhasePolicy SHALL allow brand links only when the thread is tagged as "engage" by the scoring pipeline
5. WHILE an avatar is in Phase 3, THE PhasePolicy SHALL enforce the standard daily comment limit (MAX_COMMENTS_PER_DAY)

### Requirement 5: Phase Eligibility Gates

**User Story:** As a system operator, I want clear, measurable criteria governing phase transitions including both quantity and quality signals, so that avatars only advance when they have sufficient credibility and engagement quality.

#### Acceptance Criteria

1. THE PhaseEvaluator SHALL evaluate Phase 1 → Phase 2 eligibility using all of the following criteria: Reddit_Account_Age >= 60 days, Combined_Karma >= 100, Activity_Count >= 20 comments in the last 60 days, and Comment_Survival_Rate >= 80% over the last 60 days
2. THE PhaseEvaluator SHALL evaluate Phase 2 → Phase 3 eligibility using all of the following criteria: Reddit_Account_Age >= 150 days, Combined_Karma >= 500, Activity_Count >= 50 comments in the last 90 days, Comment_Survival_Rate >= 85% over the last 90 days, and Avg_Comment_Score >= 2.0 over the last 90 days
3. WHEN any single eligibility criterion is not met, THE PhaseEvaluator SHALL keep the avatar in its current phase
4. THE PhaseEvaluator SHALL read eligibility thresholds from SystemSetting records with keys prefixed by `phase_gate_` (e.g., `phase_gate_p1_min_karma`, `phase_gate_p1_min_age_days`, `phase_gate_p1_min_activity`, `phase_gate_p1_min_survival_rate`, `phase_gate_p2_min_avg_score`)
5. IF a SystemSetting key for a threshold does not exist, THEN THE PhaseEvaluator SHALL use the hardcoded default values specified in criteria 1 and 2

### Requirement 6: Automatic Phase Promotion

**User Story:** As a system operator, I want avatars to automatically advance to the next phase when all eligibility criteria are met, so that phase progression requires no manual intervention under normal conditions.

#### Acceptance Criteria

1. WHEN the phase eligibility check runs and all criteria for the next phase are satisfied, THE PhaseTransitionManager SHALL update the avatar's `warming_phase` to the next phase value
2. WHEN a phase transition occurs, THE PhaseTransitionManager SHALL update `phase_changed_at` to the current UTC time
3. WHEN a phase transition occurs, THE PhaseTransitionManager SHALL record a Phase_Transition_Event with event_type "phase_promotion" containing the avatar ID, previous phase, new phase, and the criteria values at time of transition
4. THE PhaseEvaluator SHALL evaluate phase eligibility for all active avatars as a scheduled background task (Celery periodic task) running once daily
5. THE PhaseEvaluator SHALL skip phase evaluation for avatars that are inactive or shadowbanned
6. WHEN a comment is successfully posted by an avatar, THE PhaseEvaluator SHALL perform an opportunistic eligibility check for that avatar (on-demand evaluation)
7. WHEN the Safety_Service calls the PhasePolicy for a content restriction check, THE PhaseEvaluator SHALL piggyback an eligibility check if the avatar has not been evaluated in the last 4 hours
8. THE PhaseTransitionManager SHALL acquire a per-avatar transition lock before executing any phase change (promotion, demotion, or override) to prevent race conditions between concurrent on-demand checks and the daily batch task
9. IF the transition lock cannot be acquired within 5 seconds, THE PhaseTransitionManager SHALL skip the transition attempt and log a warning

### Requirement 7: Admin Phase Override

**User Story:** As a system administrator, I want to manually promote or demote an avatar's phase, so that I can handle edge cases where automatic progression is insufficient or incorrect.

#### Acceptance Criteria

1. WHEN an admin submits a phase override request, THE PhaseTransitionManager SHALL update the avatar's `warming_phase` to the specified phase value (1, 2, or 3)
2. WHEN an admin override occurs, THE PhaseTransitionManager SHALL record a Phase_Transition_Event with event_type "phase_override" containing the admin user ID, previous phase, new phase, and the override reason
3. WHEN an admin override occurs, THE PhaseTransitionManager SHALL update `phase_changed_at` to the current UTC time
4. THE admin override endpoint SHALL require superuser authentication (require_superuser dependency)
5. IF the specified phase value is not 1, 2, or 3, THEN THE PhaseTransitionManager SHALL return a validation error

### Requirement 8: Safety Service Integration

**User Story:** As a system operator, I want the existing `check_avatar_can_post()` function to enforce phase-based restrictions, so that all content generation respects the warming phase model without requiring callers to change.

#### Acceptance Criteria

1. WHEN `check_avatar_can_post()` is called, THE Safety_Service SHALL invoke the PhasePolicy to determine phase-based content eligibility before applying existing rate limit checks
2. IF the PhasePolicy returns a restriction for the given comment type and avatar phase, THEN THE Safety_Service SHALL return `SafetyCheckResult(allowed=False)` with a reason describing the phase restriction
3. THE Safety_Service SHALL remove the existing binary `WARMUP_DAYS` check and replace it with the PhasePolicy phase evaluation
4. THE Safety_Service SHALL pass the target subreddit and comment text to the PhasePolicy so that subreddit-level and Brand_Mention_Level restrictions can be evaluated
5. WHEN an avatar is in Phase 3, THE Safety_Service SHALL continue to enforce the existing brand ratio and cooldown checks as additional constraints
6. WHEN the PhasePolicy blocks a comment, THE Safety_Service SHALL log a `policy_block` ActivityEvent containing the avatar ID, phase, comment type, target subreddit, Brand_Mention_Level detected (if any), and the specific restriction rule that triggered the block

### Requirement 9: Admin Phase Visibility

**User Story:** As a system administrator, I want to view each avatar's current phase, progress toward the next phase, and phase transition history, so that I can monitor the warming pipeline.

#### Acceptance Criteria

1. THE admin avatar detail page SHALL display the avatar's current warming phase (1, 2, or 3) with a descriptive label (Credibility Building, Content Seeding, Brand Integration)
2. THE admin avatar detail page SHALL display progress indicators showing current values versus required thresholds for the next phase (karma progress, age progress, activity progress, comment survival rate, average comment score)
3. THE admin avatar detail page SHALL display the phase transition history as a chronological list of Phase_Transition_Events for that avatar (including promotions, demotions, and overrides)
4. THE admin avatar list page SHALL display the current warming phase for each avatar as a badge or column
5. WHEN an avatar meets all criteria for the next phase but has not yet been promoted (pending next evaluation), THE admin page SHALL indicate "eligible for promotion"

### Requirement 10: Phase Eligibility in Avatar Health Endpoint

**User Story:** As an API consumer, I want the avatar health endpoint to include phase information, so that external tools and dashboards can display warming status.

#### Acceptance Criteria

1. THE `get_avatar_health()` function SHALL include `warming_phase` (integer 1-3) in its return dictionary
2. THE `get_avatar_health()` function SHALL include `phase_label` (string: "Credibility Building", "Content Seeding", or "Brand Integration") in its return dictionary
3. THE `get_avatar_health()` function SHALL include `phase_progress` (dictionary with keys for each eligibility criterion showing current value and required threshold, including comment_survival_rate and avg_comment_score) in its return dictionary
4. THE `get_avatar_health()` function SHALL include `phase_eligible_for_next` (boolean indicating whether all next-phase criteria are currently met) in its return dictionary
5. THE `get_avatar_health()` function SHALL replace the existing `in_warmup` boolean field with the phase-based fields

### Requirement 11: Automatic Phase Demotion

**User Story:** As a system operator, I want avatars to be automatically demoted when credibility signals degrade, so that compromised or low-quality accounts do not retain elevated privileges.

#### Acceptance Criteria

1. WHEN a shadowban signal is detected for an avatar (is_shadowbanned becomes True), THE PhaseTransitionManager SHALL demote the avatar to Phase 1 immediately
2. WHEN an avatar's Comment_Survival_Rate drops below 70% over a rolling 7-day window, THE PhaseTransitionManager SHALL demote the avatar by one phase
3. WHEN an avatar's Combined_Karma velocity drops by more than 50% compared to the previous 7-day period (indicating sudden karma loss), THE PhaseTransitionManager SHALL demote the avatar by one phase
4. WHEN an automatic demotion occurs, THE PhaseTransitionManager SHALL record a Phase_Transition_Event with event_type "auto_downgrade" containing the avatar ID, previous phase, new phase, and the trigger reason
5. WHEN an automatic demotion occurs, THE PhaseTransitionManager SHALL update `phase_changed_at` to the current UTC time
6. THE PhaseEvaluator SHALL evaluate demotion triggers during both the daily batch evaluation and on-demand eligibility checks
7. IF an avatar is already in Phase 1, THEN THE PhaseTransitionManager SHALL not demote further but SHALL log the trigger event for monitoring

### Requirement 12: Brand Mention Classification

**User Story:** As a system operator, I want brand mentions classified into explicit levels, so that phase restrictions can be applied with appropriate granularity per phase.

#### Acceptance Criteria

1. THE PhasePolicy SHALL classify brand-related content into three levels: `explicit_brand_link` (URL matching the client's configured brand domain), `explicit_brand_name` (case-insensitive string match of the client's brand name in comment text), and `inferred_brand` (AI-classified as brand-adjacent without explicit brand references)
2. WHEN classifying a comment, THE PhasePolicy SHALL check for `explicit_brand_link` by matching URLs against the client's `brand_domain` configuration field
3. WHEN classifying a comment, THE PhasePolicy SHALL check for `explicit_brand_name` by performing a case-insensitive match of the client's `brand_name` configuration field against the comment text
4. WHEN classifying a comment, THE PhasePolicy SHALL check for `inferred_brand` using the existing content safety classification logic for brand-adjacent content
5. THE PhasePolicy SHALL return the highest-severity Brand_Mention_Level found in a comment (priority order: `explicit_brand_link` > `explicit_brand_name` > `inferred_brand`)
6. IF no brand-related content is detected, THEN THE PhasePolicy SHALL classify the comment as having no Brand_Mention_Level

### Requirement 13: Phase 3 Ramp-Up Period

**User Story:** As a system operator, I want newly promoted Phase 3 avatars to gradually increase brand mention frequency, so that a sudden spike in brand activity does not trigger Reddit's detection systems.

#### Acceptance Criteria

1. WHEN an avatar is promoted to Phase 3, THE PhasePolicy SHALL enforce a 7-day Ramp_Up_Period starting from `phase_changed_at`
2. WHILE an avatar is within the first 72 hours of Phase 3 (days 0-3), THE PhasePolicy SHALL allow a maximum of 1 comment containing any Brand_Mention_Level
3. WHILE an avatar is within days 4-7 of Phase 3, THE PhasePolicy SHALL enforce a maximum brand ratio of 10% (instead of the standard 30%)
4. WHEN the Ramp_Up_Period of 7 days has elapsed since `phase_changed_at`, THE PhasePolicy SHALL enforce the standard MAX_BRAND_RATIO (30%)
5. THE PhasePolicy SHALL calculate Ramp_Up_Period progress using the difference between current UTC time and the avatar's `phase_changed_at` timestamp
6. WHEN an admin overrides an avatar directly to Phase 3, THE PhasePolicy SHALL apply the same Ramp_Up_Period restrictions starting from the override timestamp

### Requirement 14: Phase Service Decomposition

**User Story:** As a developer, I want the phase logic separated into distinct responsibilities, so that the codebase remains maintainable and testable as phase rules grow in complexity.

#### Acceptance Criteria

1. THE Phase_Service SHALL be organized into three logical components: PhaseEvaluator (eligibility gate checks), PhasePolicy (content restriction rules per phase), and PhaseTransitionManager (transition execution and event recording)
2. THE PhaseEvaluator SHALL expose a function to evaluate whether an avatar meets all criteria for the next phase, including both quantity metrics (age, karma, activity count) and quality metrics (comment survival rate, average comment score)
3. THE PhasePolicy SHALL expose a function to determine whether a given comment is allowed for an avatar's current phase, accepting the avatar, comment type, target subreddit, and comment text as inputs
4. THE PhaseTransitionManager SHALL expose functions to execute promotions, demotions, and admin overrides, each recording the appropriate Phase_Transition_Event
5. THE three components MAY be implemented as classes or modules within a single `services/phase.py` file, but SHALL maintain clear separation of concerns with no circular dependencies between them

### Requirement 15: On-Demand Phase Evaluation

**User Story:** As a system operator, I want eligible avatars to be promoted without waiting up to 23 hours for the next daily batch, so that phase transitions happen promptly when criteria are met.

#### Acceptance Criteria

1. WHEN a comment is successfully posted (status changes to "posted"), THE PhaseEvaluator SHALL perform an opportunistic eligibility check for the posting avatar
2. WHEN the Safety_Service invokes the PhasePolicy for a content restriction check, THE PhaseEvaluator SHALL perform a piggyback eligibility check if the avatar has not been evaluated in the last 4 hours
3. THE PhaseEvaluator SHALL store a `last_phase_evaluated_at` timestamp on the avatar to prevent redundant evaluations within the 4-hour cooldown window
4. THE daily batch Celery task SHALL continue to run as a safety net to catch any avatars missed by on-demand checks
5. THE on-demand eligibility check SHALL use the same criteria and logic as the daily batch evaluation (no separate code path)
