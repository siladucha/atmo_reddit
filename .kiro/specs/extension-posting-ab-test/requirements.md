# Requirements Document

## Introduction

An A/B testing framework to scientifically validate whether the posting method (old.reddit textarea, manual email-instructed, new.reddit chrome.debugger) affects Reddit's trust score for avatar accounts. The experiment assigns avatars to treatment groups, enforces control variables, and produces weekly statistical reports over an 8-week period. The goal is to answer H0: "posting method has no statistically significant effect on avatar health metrics."

## Glossary

- **AB_Test_Framework**: The system component responsible for managing experiment lifecycle, group assignment, control variable enforcement, metric collection, and statistical reporting.
- **Treatment_Group**: A set of avatars assigned to one posting method (old_reddit, manual_email, or new_reddit_debugger) for the duration of the experiment.
- **Control_Variable**: A parameter (daily volume, subreddit risk, content type, account age, content model) held constant across all treatment groups to isolate the independent variable.
- **Health_Metric**: A measurable outcome tracked per avatar per week (removal rate, karma velocity, shadowban events, CQS level, subreddit ban rate, phase speed, account warnings).
- **Experiment_Run**: A single 8-week execution of the A/B test from start to conclusion.
- **Weekly_Report**: A structured statistical summary generated every 7 days comparing treatment groups across all health metrics.
- **Statistical_Significance**: A determination (p < 0.05 via chi-squared or Mann-Whitney U) that observed group differences are unlikely due to chance.
- **Avatar**: A managed Reddit account participating in the RAMP posting pipeline.
- **Posting_Method**: The independent variable — the mechanism by which a comment is submitted to Reddit (old_reddit DOM manipulation, manual human posting, or new_reddit chrome.debugger).

## Requirements

### Requirement 1: Experiment Configuration and Group Assignment

**User Story:** As an operator, I want to configure an A/B test with defined treatment groups and assign avatars to groups, so that I can run a controlled experiment comparing posting methods.

#### Acceptance Criteria

1. THE AB_Test_Framework SHALL allow creation of an Experiment_Run with a name, hypothesis, start date, planned duration in weeks, and a list of Treatment_Group definitions.
2. WHEN an Experiment_Run is created, THE AB_Test_Framework SHALL validate that at least 2 Treatment_Group definitions are provided and each has a distinct posting method identifier (old_reddit, manual_email, or new_reddit_debugger).
3. THE AB_Test_Framework SHALL assign avatars to Treatment_Group records based on operator selection, storing the assignment with avatar_id, group_id, and assignment date.
4. WHEN an avatar is assigned to a Treatment_Group, THE AB_Test_Framework SHALL validate that the avatar meets control variable eligibility criteria (account age within ±2 weeks of group median, CQS not "lowest").
5. IF an avatar becomes ineligible during the experiment (suspended, deactivated), THEN THE AB_Test_Framework SHALL mark the avatar as excluded from analysis and record the exclusion reason and date.
6. THE AB_Test_Framework SHALL prevent an avatar from being assigned to more than one Treatment_Group within the same Experiment_Run.

### Requirement 2: Control Variable Enforcement

**User Story:** As an operator, I want the system to enforce equal conditions across all treatment groups, so that posting method is the only variable that differs.

#### Acceptance Criteria

1. WHILE an Experiment_Run is active, THE AB_Test_Framework SHALL enforce a daily posting volume of exactly 3 comments per avatar across all Treatment_Group records.
2. WHILE an Experiment_Run is active, THE AB_Test_Framework SHALL restrict each avatar to subreddits with risk_score within a configured range (default 0-40) to equalize subreddit risk profile across groups.
3. WHILE an Experiment_Run is active, THE AB_Test_Framework SHALL restrict content generation to hobby/Phase 1 type content for all participating avatars regardless of their current phase.
4. WHILE an Experiment_Run is active, THE AB_Test_Framework SHALL use the same LLM generation model (configured at experiment creation) for all content generated for participating avatars.
5. IF the system detects a control variable violation (avatar posted more than 3 comments in a day, or posted in a subreddit outside the allowed risk range), THEN THE AB_Test_Framework SHALL log the violation as an activity event and flag the affected data point for exclusion from analysis.

### Requirement 3: Posting Method Routing

**User Story:** As an operator, I want each treatment group to use its designated posting method exclusively, so that the experiment isolates the effect of posting method.

#### Acceptance Criteria

1. WHEN a task is created for an avatar in the old_reddit Treatment_Group, THE AB_Test_Framework SHALL set the delivery channel to extension with posting mode "old_reddit" (textarea value assignment + .save button click via old.reddit.com).
2. WHEN a task is created for an avatar in the manual_email Treatment_Group, THE AB_Test_Framework SHALL set the delivery channel to email and generate standard executor instruction emails.
3. WHEN a task is created for an avatar in the new_reddit_debugger Treatment_Group, THE AB_Test_Framework SHALL set the delivery channel to extension with posting mode "new_reddit_debugger" (chrome.debugger trusted clicks via www.reddit.com Shadow DOM).
4. WHILE an Experiment_Run is active, THE AB_Test_Framework SHALL override the avatar's configured delivery_channel with the Treatment_Group posting method for all experiment-related tasks.
5. IF a task fails due to posting method infrastructure issues (DOM change, extension offline), THEN THE AB_Test_Framework SHALL record the failure with method-specific error classification and NOT fall back to an alternative posting method.

### Requirement 4: Health Metric Collection

**User Story:** As an operator, I want the system to collect all relevant health metrics per avatar per week, so that I can compare outcomes across groups.

#### Acceptance Criteria

1. THE AB_Test_Framework SHALL collect comment removal rate per avatar per week by querying snapshot_comment_outcomes for comments posted during the experiment window and calculating (deleted_count / total_posted_count).
2. THE AB_Test_Framework SHALL collect karma velocity per avatar per week by averaging KarmaSnapshot values at 4h, 24h, and 7d windows for comments posted that week.
3. THE AB_Test_Framework SHALL collect shadowban events per avatar per week by counting health_check detections where is_shadowbanned transitions from false to true.
4. THE AB_Test_Framework SHALL collect CQS level changes per avatar per week by recording the CQS level at week start and week end and flagging any level change (improvement or degradation).
5. THE AB_Test_Framework SHALL collect subreddit ban rate per avatar per week by counting new AvatarSubredditBan records created during that week.
6. THE AB_Test_Framework SHALL collect phase progression speed per avatar by recording the phase at experiment start and tracking days until next phase promotion.
7. THE AB_Test_Framework SHALL collect account warnings and restrictions per avatar per week through health_checker automated detection of new restrictions.

### Requirement 5: Weekly Statistical Reporting

**User Story:** As an operator, I want weekly statistical reports comparing treatment groups, so that I can monitor the experiment and detect significant differences early.

#### Acceptance Criteria

1. WHEN 7 days have elapsed since the last report (or experiment start), THE AB_Test_Framework SHALL generate a Weekly_Report containing per-group aggregates for all Health_Metric types.
2. THE Weekly_Report SHALL include a statistical comparison between each pair of Treatment_Group records using chi-squared test for categorical metrics (shadowban yes/no, CQS change yes/no) and Mann-Whitney U test for continuous metrics (removal rate, karma velocity).
3. THE Weekly_Report SHALL include a p-value and effect size for each metric comparison, and flag any metric where p < 0.05 as statistically significant.
4. THE Weekly_Report SHALL include per-avatar raw data tables (avatar username, group, metric values) for transparency and audit.
5. THE Weekly_Report SHALL include a running cumulative analysis across all weeks completed so far (not just the most recent week in isolation).
6. IF a Weekly_Report detects Statistical_Significance on a primary metric (removal rate or shadowban events) with medium-or-larger effect size for 2 consecutive weeks, THEN THE AB_Test_Framework SHALL emit an alert activity event recommending early experiment termination review.

### Requirement 6: Experiment Lifecycle Management

**User Story:** As an operator, I want to start, pause, resume, and conclude experiments with proper state management, so that I can handle operational needs without corrupting data.

#### Acceptance Criteria

1. THE AB_Test_Framework SHALL support experiment states: draft, active, paused, concluded, and aborted.
2. WHEN an operator transitions an Experiment_Run from draft to active, THE AB_Test_Framework SHALL validate minimum group sizes (at least 5 avatars per group) and record the official start timestamp.
3. WHEN an operator pauses an Experiment_Run, THE AB_Test_Framework SHALL suspend control variable enforcement and posting method overrides, and record the pause timestamp and reason.
4. WHEN an operator resumes a paused Experiment_Run, THE AB_Test_Framework SHALL re-apply control variable enforcement and posting method overrides, and record the resume timestamp.
5. WHEN an operator concludes an Experiment_Run, THE AB_Test_Framework SHALL generate a final summary report with cumulative statistics, effect sizes, confidence intervals, and a determination of whether H0 can be rejected.
6. WHEN an Experiment_Run reaches its planned duration, THE AB_Test_Framework SHALL emit an activity event notifying the operator that the experiment is ready for conclusion.

### Requirement 7: Admin UI for Experiment Management

**User Story:** As an operator, I want an admin interface to create, monitor, and manage experiments, so that I can run A/B tests without modifying code or database records directly.

#### Acceptance Criteria

1. THE AB_Test_Framework SHALL provide an admin page at /admin/ab-tests listing all Experiment_Run records with status badge, group counts, duration, and start date.
2. THE AB_Test_Framework SHALL provide a detail page per Experiment_Run showing Treatment_Group composition, avatar assignments, control variable configuration, and current status.
3. THE AB_Test_Framework SHALL provide an avatar assignment interface that displays eligible avatars (meeting control variable criteria) and allows drag-and-drop or checkbox assignment to groups.
4. THE AB_Test_Framework SHALL provide a metrics dashboard per experiment showing weekly Health_Metric charts with group-colored lines and Statistical_Significance markers.
5. THE AB_Test_Framework SHALL provide action buttons for experiment state transitions (start, pause, resume, conclude, abort) with confirmation dialogs.

### Requirement 8: Data Integrity and Isolation

**User Story:** As an operator, I want experiment data to be isolated and tamper-resistant, so that results are scientifically valid.

#### Acceptance Criteria

1. THE AB_Test_Framework SHALL store all experiment metric snapshots as immutable records (append-only, no updates to historical data points).
2. THE AB_Test_Framework SHALL record the source and timestamp of every Health_Metric data point, enabling full provenance tracing.
3. IF the EPG pipeline or phase evaluator attempts to modify a participating avatar's posting volume or phase during an active experiment, THEN THE AB_Test_Framework SHALL block the modification and log the blocked action.
4. THE AB_Test_Framework SHALL maintain a complete audit log of all experiment configuration changes, state transitions, and operator actions with timestamps and actor identity.
5. WHILE an Experiment_Run is active, THE AB_Test_Framework SHALL prevent deletion or modification of CommentDraft records associated with experiment tasks.
