# Requirements Document

## Introduction

EPG 2.0: Attention Portfolio Manager transforms the existing Editorial Program Guide from a content calendar into an attention capital allocation engine. The current EPG treats content as the end goal — selecting threads, generating comments, and scheduling posting. EPG 2.0 reframes the entire pipeline as an investment decision framework where Reddit is an attention market, each avatar is an investment fund, and each publication is an investment decision.

The system manages the full decision-making pipeline: Discovery → Opportunity Evaluation → Risk Assessment → Return Estimation → Portfolio Allocation → Action Selection → Content Generation → Execution → Measurement → Model Correction. Text generation becomes the LAST step, not the first.

Each avatar operates with a daily attention budget (limited posts, comments, minutes) and the EPG's task is NOT to fill those limits, but to allocate them for maximum return at managed risk. The system explicitly tracks what it chose NOT to do and why — absence of action requires more explanation than action itself.

EPG 2.0 builds on the existing EPG infrastructure (EPGSlot model, timing engine, safety gates, automated posting) but replaces the thread-selection logic with a multi-dimensional opportunity evaluation engine that considers avatar state, community state, market state, and client strategic goals.

## Glossary

- **Attention_Portfolio_Manager**: The system module that replaces the current EPG thread-selection logic with opportunity-based investment decision-making for each avatar's daily attention budget.
- **Opportunity**: A detected engagement possibility on Reddit — a thread, a trending topic, a community need — rated by visibility, competition, trust potential, karma potential, risk, and strategic alignment.
- **Opportunity_Score**: A composite rating (0-100) computed from six dimensions: Visibility (0-100), Competition (0-100), Trust_Potential (0-100), Karma_Potential (0-100), Risk (0-100), Strategic_Alignment (0-100).
- **Attention_Budget**: The daily resource envelope for an avatar — maximum posts, maximum comments, maximum minutes of engagement, and acceptable risk level — determined by avatar phase, health, and client constraints.
- **Portfolio_Allocation**: The daily distribution of attention budget across topic categories, expressed as percentages that sum to 100 (e.g., 40% Product Discovery, 30% AI Agents, 20% Startup Funding, 10% Experimental).
- **Risk_Score**: A 0-100 integer assessing the probability of negative outcomes (mod removal, downvotes, shadowban signals, brand promotion accusation) for a given action in a given context.
- **Expected_Return**: A multi-dimensional return estimate for an opportunity: Expected_Karma (integer), Expected_Trust (0-100), Expected_Visibility (0-100), Expected_Influence (0-100), Expected_Strategic_Value (0-100).
- **Avatar_State**: Current condition of an avatar — account age, karma, posting history, warming phase, health status, daily budget remaining, recent activity pattern.
- **Community_State**: Current condition of a target subreddit — activity level, topic saturation, moderation sensitivity, recent mod actions, trending topics, time-of-day pattern.
- **Market_State**: Aggregate Reddit attention market conditions — trending topics across relevant subreddits, competition intensity, topic freshness, seasonal patterns.
- **Client_State**: Client's strategic context — goals, priorities, constraints, phase focus, brand mention budget remaining, target niches.
- **Return_On_Attention**: Performance metric calculated as karma gained divided by actions taken over a time period.
- **Risk_Adjusted_Return**: Performance metric calculated as Return_On_Attention divided by average Risk_Score of actions taken.
- **Zero_Day_Report**: A structured report generated when EPG decides to take zero actions for an avatar on a given day, explaining market conditions, risk factors, and actionable recommendations.
- **Decision_Record**: An immutable log of each allocation decision — what opportunities were evaluated, what was chosen, what was rejected, and the reasoning behind each choice.
- **Opportunity_Engine**: The sub-module that scans the attention market and identifies engagement opportunities for each avatar.
- **Risk_Engine**: The sub-module that evaluates risk for each potential action based on avatar state, community state, and historical patterns.
- **Return_Engine**: The sub-module that estimates expected multi-dimensional returns for each opportunity.
- **Allocation_Engine**: The sub-module that constructs the optimal portfolio of actions given budget constraints, risk tolerance, and strategic alignment.

## Requirements

### Requirement 1: Opportunity Discovery and Scoring

**User Story:** As a platform operator, I want the system to find and rate engagement opportunities rather than just selecting threads, so that each avatar's actions are investment decisions based on multi-dimensional value assessment.

#### Acceptance Criteria

1. WHEN the daily EPG pipeline runs for an avatar, THE Opportunity_Engine SHALL scan all subreddits assigned to that avatar and produce a ranked list of Opportunities, each rated with an Opportunity_Score computed from six dimensions: Visibility (0-100), Competition (0-100), Trust_Potential (0-100), Karma_Potential (0-100), Risk (0-100), and Strategic_Alignment (0-100).
2. THE Opportunity_Engine SHALL compute the Visibility dimension based on thread age (fresher threads score higher), current upvote count (moderate upvotes score higher than zero or very high), comment count (fewer comments indicate more visibility for a new reply), and subreddit subscriber count.
3. THE Opportunity_Engine SHALL compute the Competition dimension based on the number of existing comments, the quality of existing top comments (measured by upvotes), and the presence of other known avatars or competitor accounts in the thread.
4. THE Opportunity_Engine SHALL compute the Trust_Potential dimension based on thread topic alignment with avatar's niche profile, opportunity for demonstrating expertise (technical questions, experience-sharing prompts), and potential for substantive discussion rather than short replies.
5. THE Opportunity_Engine SHALL compute the Karma_Potential dimension based on historical karma returns for similar threads in the same subreddit, thread engagement velocity (upvotes per hour), and position in thread lifecycle (early comments receive more upvotes).
6. THE Opportunity_Engine SHALL compute the Strategic_Alignment dimension based on alignment with client's declared strategic goals, topic relevance to avatar's niche cluster, and contribution to Authority Score progression.
7. THE Opportunity_Engine SHALL produce a minimum of 10 and a maximum of 50 scored Opportunities per avatar per daily run, completing the scan and scoring within 60 seconds per avatar.
8. IF the Opportunity_Engine finds fewer than 10 scoreable threads across all assigned subreddits, THEN THE Opportunity_Engine SHALL log this as a market_scarcity event and proceed with the available opportunities.

### Requirement 2: Risk Assessment Engine

**User Story:** As a platform operator, I want each potential action evaluated for risk before execution, so that avatars avoid actions that could lead to bans, shadowbans, or karma loss.

#### Acceptance Criteria

1. WHEN an Opportunity is identified, THE Risk_Engine SHALL compute a Risk_Score (0-100) based on: avatar account age (newer accounts face higher risk), avatar current karma (low karma means less tolerance for mistakes), posting frequency in the last 24 hours (higher frequency increases detection risk), subreddit moderation sensitivity (measured by historical removal rate of avatar's posts in that subreddit), content type risk (brand mentions carry higher risk than neutral expertise), and brand promotion accusation probability.
2. THE Risk_Engine SHALL weight risk factors based on avatar warming phase: Phase 1 avatars SHALL have risk factors weighted 2x compared to Phase 3 avatars for subreddit sensitivity and posting frequency dimensions.
3. WHILE an avatar's health status is "warned" or "suspicious", THE Risk_Engine SHALL add 20 points to the base Risk_Score for all opportunities evaluated for that avatar.
4. THE Risk_Engine SHALL compute a historical_removal_rate for each avatar-subreddit pair based on the ratio of removed posts to total posts in the last 90 days, and SHALL use this rate as input to the subreddit moderation sensitivity factor.
5. IF the computed Risk_Score for an opportunity exceeds the avatar's acceptable risk threshold (defined in Attention_Budget), THEN THE Risk_Engine SHALL exclude that opportunity from the allocation candidate set and log the exclusion reason.
6. THE Risk_Engine SHALL flag any opportunity where the Risk_Score exceeds 70 as "high_risk" and any opportunity where the Risk_Score exceeds 90 as "critical_risk", regardless of the avatar's risk threshold setting.

### Requirement 3: Expected Return Estimation

**User Story:** As a platform operator, I want the system to estimate multi-dimensional returns for each opportunity, so that allocation decisions maximize value across karma, trust, visibility, and strategic positioning.

#### Acceptance Criteria

1. WHEN an Opportunity passes risk assessment, THE Return_Engine SHALL estimate Expected_Return across five dimensions: Expected_Karma (integer, estimated karma gain from the action), Expected_Trust (0-100, contribution to avatar's trust score in the community), Expected_Visibility (0-100, how much the action increases avatar's visibility), Expected_Influence (0-100, potential to provoke discussion or be referenced by others), and Expected_Strategic_Value (0-100, contribution to client's declared strategic goals).
2. THE Return_Engine SHALL compute Expected_Karma using a regression model based on: historical average karma for the avatar in that subreddit, thread engagement velocity, comment position (depth and timing), and avatar's karma trajectory (trending up or down over the last 30 days).
3. THE Return_Engine SHALL compute Expected_Trust based on: whether the opportunity allows demonstrating domain expertise, whether it involves helping another user, potential for substantive multi-turn dialogue, and alignment with avatar's established niche topics.
4. THE Return_Engine SHALL compute Expected_Visibility based on: thread subscriber-to-comment ratio, potential for the comment to be among top-level visible replies, subreddit size, and cross-posting potential.
5. THE Return_Engine SHALL compute Expected_Strategic_Value based on: how well the opportunity supports entity linking with client brand, whether it naturally supports the current phase strategy (hobby in Phase 1, expertise in Phase 2, brand in Phase 3), and proximity to high-authority users in the thread.
6. THE Return_Engine SHALL produce a single composite Expected_Return_Score (0-100) as a weighted sum of the five dimensions, with weights configurable per client via strategy settings (default weights: Karma 20%, Trust 25%, Visibility 20%, Influence 15%, Strategic_Value 20%).

### Requirement 4: Attention Budget Definition and Enforcement

**User Story:** As a platform operator, I want each avatar to have a configurable daily attention budget that constrains total actions, so that the system allocates limited resources optimally rather than filling quotas.

#### Acceptance Criteria

1. THE Attention_Portfolio_Manager SHALL define an Attention_Budget for each avatar daily, comprising: max_posts (integer, 0-5), max_comments (integer, 0-20), max_total_actions (integer, 0-25), and acceptable_risk_level (integer, 0-100 threshold above which opportunities are excluded).
2. THE Attention_Portfolio_Manager SHALL derive default Attention_Budget values from avatar warming phase: Phase 1 budget of max_comments=3, max_posts=0, acceptable_risk_level=40; Phase 2 budget of max_comments=7, max_posts=2, acceptable_risk_level=60; Phase 3 budget of max_comments=12, max_posts=3, acceptable_risk_level=75.
3. WHEN an operator overrides the default Attention_Budget for an avatar, THE Attention_Portfolio_Manager SHALL store the override and use override values instead of phase defaults until the override is removed.
4. THE Attention_Portfolio_Manager SHALL enforce the Attention_Budget as a hard ceiling: no allocation plan SHALL exceed the budget limits regardless of opportunity quality.
5. THE Attention_Portfolio_Manager SHALL track budget consumption throughout the day: WHEN an action is executed (draft posted), THE Attention_Portfolio_Manager SHALL decrement the remaining budget and recalculate allocation if re-planning occurs.
6. IF a client's plan_type imposes action caps (max_comments_per_month from pricing tier), THEN THE Attention_Portfolio_Manager SHALL compute the effective daily budget as the minimum of the avatar's phase budget and the remaining monthly plan allowance divided by remaining days in the billing period.

### Requirement 5: Portfolio Allocation Strategy

**User Story:** As a platform operator, I want the system to distribute attention across topic categories rather than concentrating all actions in one area, so that avatars build diversified authority without over-saturating any single community.

#### Acceptance Criteria

1. WHEN building the daily plan, THE Allocation_Engine SHALL construct a Portfolio_Allocation distributing the avatar's Attention_Budget across topic categories, where each category receives a percentage of the total budget and all percentages sum to 100.
2. THE Allocation_Engine SHALL derive the default Portfolio_Allocation from the avatar's niche profile and client strategy: primary niche receives 40-60%, secondary topics receive 20-30%, and an experimental category receives 5-15% for exploring new opportunities.
3. WHEN an operator defines a custom Portfolio_Allocation for a client, THE Allocation_Engine SHALL use the custom allocation and validate that percentages sum to 100 before accepting the configuration.
4. THE Allocation_Engine SHALL select the highest Expected_Return_Score opportunity within each category to fill that category's budget allocation, subject to Risk_Score constraints.
5. IF a category has zero opportunities that pass risk assessment, THEN THE Allocation_Engine SHALL reallocate that category's budget share proportionally to remaining categories that have viable opportunities, and log the reallocation decision.
6. THE Allocation_Engine SHALL enforce a diversification constraint: no single subreddit SHALL receive more than 40% of the daily action allocation unless the avatar has only one assigned subreddit.
7. THE Allocation_Engine SHALL compute Portfolio_Diversification as a metric: the Shannon entropy of the distribution across subreddits and action types, with higher entropy indicating better diversification.

### Requirement 6: Zero-Day Decision and Reporting

**User Story:** As a platform operator, I want the system to explicitly decide when an avatar should take zero actions and explain why, so that I understand market conditions and can take corrective action.

#### Acceptance Criteria

1. IF the Allocation_Engine determines that all available Opportunities have Risk_Scores exceeding the avatar's acceptable_risk_level, OR all Opportunities have Expected_Return_Score below 20, OR the market_scarcity event was triggered (fewer than 10 scoreable threads), THEN THE Attention_Portfolio_Manager SHALL generate a Zero_Day_Report instead of a daily action plan.
2. THE Zero_Day_Report SHALL contain: the date, avatar name, a summary of why no actions were taken (one of: market_cold, risk_too_high, return_too_low, market_scarcity, avatar_state_unfavorable), the number of opportunities scanned, the average Risk_Score of available opportunities, the highest Expected_Return_Score found, and a list of up to 5 specific reasons why each top opportunity was rejected.
3. THE Zero_Day_Report SHALL include actionable recommendations: at least 2 and at most 5 suggestions chosen from a predefined set — "add_new_subreddits" (when market_scarcity), "adjust_risk_threshold" (when risk_too_high with specific suggested value), "change_strategy_focus" (when return_too_low), "wait_for_better_timing" (when market_cold with estimated recovery), "review_avatar_health" (when avatar_state_unfavorable).
4. THE Attention_Portfolio_Manager SHALL store Zero_Day_Reports in a dedicated table with avatar_id, report_date, reason_code, full report content (JSONB), and recommendations (JSONB array).
5. THE Attention_Portfolio_Manager SHALL compute and track the zero_day_rate metric: the percentage of days in the last 30 days where each avatar produced a Zero_Day_Report instead of an action plan.
6. IF an avatar's zero_day_rate exceeds 50% over the last 14 days, THEN THE Attention_Portfolio_Manager SHALL generate an alert visible in the admin dashboard indicating that the avatar may need strategy reconfiguration or additional subreddit assignments.

### Requirement 7: Decision Record and Audit Trail

**User Story:** As a platform operator, I want every allocation decision fully traced and explainable, so that I can understand why the system chose specific actions and improve the model over time.

#### Acceptance Criteria

1. THE Attention_Portfolio_Manager SHALL create a Decision_Record for every daily allocation run, storing: avatar_id, decision_date, all scored Opportunities (with full Opportunity_Score breakdown), the Portfolio_Allocation applied, the final selected actions (ordered by priority), all rejected opportunities with rejection reasons, the total budget available and total budget consumed, and the computed portfolio metrics.
2. THE Decision_Record SHALL store the Avatar_State snapshot at decision time: current karma, phase, health status, days since last post, posts today count, and risk tolerance.
3. THE Decision_Record SHALL store the Community_State snapshot for each evaluated subreddit: recent activity level (posts/24h), topic saturation assessment, last known moderation action against avatar, and current trending topics.
4. THE Decision_Record SHALL store the Market_State snapshot: top 5 trending topics across all assigned subreddits, average competition score, and overall market temperature (hot/warm/cold classification based on opportunity density).
5. WHEN an operator views the Decision_Record for a specific day, THE Attention_Portfolio_Manager SHALL present the full decision chain: market scan → opportunity scoring → risk assessment → return estimation → portfolio allocation → action selection, with expandable detail at each stage.
6. THE Attention_Portfolio_Manager SHALL retain Decision_Records for 90 days, after which records older than 90 days SHALL be archived (metadata retained, full opportunity list pruned).

### Requirement 8: State-Based Decision Context

**User Story:** As a platform operator, I want the system to factor in avatar state, community state, and market conditions when making allocation decisions, so that actions are contextually appropriate rather than based solely on thread quality.

#### Acceptance Criteria

1. WHILE an avatar is in Phase 1 (warming), THE Allocation_Engine SHALL restrict all opportunities to hobby subreddits and zero-brand-mention topics, and SHALL set the maximum acceptable_risk_level to 40 regardless of any override.
2. WHILE an avatar's last_posted_at is within the last 45 minutes, THE Allocation_Engine SHALL defer any additional actions for that avatar until the minimum interval has elapsed, respecting the existing timing engine constraints.
3. WHEN the Community_State indicates a subreddit has had 3 or more moderator removal actions against the avatar in the last 30 days, THE Risk_Engine SHALL add 30 points to the Risk_Score for all opportunities in that subreddit.
4. WHEN the Market_State indicates topic saturation (more than 5 threads on the same topic in the same subreddit within 24 hours), THE Opportunity_Engine SHALL reduce the Visibility score by 30 points for opportunities on that topic in that subreddit.
5. WHEN the Client_State indicates that the monthly brand mention budget is exhausted (brand mentions this month >= client's configured brand_mention_cap), THE Allocation_Engine SHALL exclude all opportunities that would require brand-related content, restricting to expertise-only and hobby content.
6. THE Attention_Portfolio_Manager SHALL evaluate Avatar_State, Community_State, Market_State, and Client_State as a combined context matrix before scoring any opportunities, ensuring that contextual constraints are applied before individual opportunity evaluation.

### Requirement 9: Performance Metrics and Model Correction

**User Story:** As a platform operator, I want the system to track decision quality metrics and self-correct its models based on actual outcomes, so that allocation accuracy improves over time.

#### Acceptance Criteria

1. THE Attention_Portfolio_Manager SHALL compute and store the following metrics per avatar per rolling 30-day window: Return_On_Attention (total karma gained / total actions taken), Risk_Adjusted_Return (Return_On_Attention / average Risk_Score of executed actions), Portfolio_Diversification (Shannon entropy of action distribution across subreddits and categories), Decision_Accuracy (percentage of actions that produced positive karma return), Opportunity_Cost (estimated return of the highest-scoring rejected opportunity minus actual return of the selected action), and Zero_Day_Rate (percentage of zero-action days).
2. WHEN an action's actual outcome (karma at 24h post-execution) differs from the Expected_Karma by more than 50%, THE Attention_Portfolio_Manager SHALL log a model_correction_event recording: the opportunity details, predicted return, actual return, deviation percentage, and contributing factors.
3. THE Attention_Portfolio_Manager SHALL use model_correction_events to adjust future Expected_Karma predictions: WHEN a subreddit consistently over-performs predictions (actual karma > 150% of predicted for 5 or more actions), THE Return_Engine SHALL increase the karma multiplier for that subreddit by 10%; WHEN a subreddit consistently under-performs (actual karma < 50% of predicted for 5 or more actions), THE Return_Engine SHALL decrease the karma multiplier by 10%.
4. THE Attention_Portfolio_Manager SHALL expose metrics via an admin dashboard panel showing per-avatar: Return_On_Attention trend (7/14/30 days), Risk_Adjusted_Return trend, Portfolio_Diversification score, Decision_Accuracy percentage, and Zero_Day_Rate.
5. IF Decision_Accuracy drops below 50% for an avatar over a 14-day window, THEN THE Attention_Portfolio_Manager SHALL generate an alert in the admin dashboard recommending model review for that avatar.

### Requirement 10: Integration with Existing EPG Infrastructure

**User Story:** As a developer, I want EPG 2.0 to integrate with the existing EPG slot system, timing engine, safety gates, and automated posting infrastructure, so that the new decision layer enhances rather than replaces working execution mechanics.

#### Acceptance Criteria

1. THE Attention_Portfolio_Manager SHALL produce its output as EPGSlot records compatible with the existing EPG execution infrastructure: each selected action creates an EPGSlot with avatar_id, plan_date, slot_type, scheduled_at, thread_id, subreddit, and status "planned".
2. THE Attention_Portfolio_Manager SHALL use the existing timing_engine to assign scheduled_at values to selected actions, preserving jitter (±30%), minimum 45-minute intervals, active hours (08:00-23:00), and peak hour bias.
3. THE Attention_Portfolio_Manager SHALL respect all existing safety gates in posting_safety.py: kill switch, posting_mode, frozen, health, phase exclusion, daily cap, proxy, user-agent, and subnet consistency.
4. WHEN the existing automated posting system (execute_pending_posts Celery task) picks up EPGSlots created by EPG 2.0, THE Attention_Portfolio_Manager SHALL ensure no additional validation is needed — the slots are fully compatible with the existing posting pipeline.
5. THE Attention_Portfolio_Manager SHALL replace the existing `build_daily_epg` function's thread-selection logic while preserving its output interface (EPGResult with slots), ensuring backward compatibility with all EPG consumers (admin UI, posting pipeline, activity events).
6. THE Attention_Portfolio_Manager SHALL integrate with the existing Celery Beat schedule, running at 08:00 and 14:00 (Asia/Jerusalem) as the current pipeline does, with the ability to be triggered manually via the admin "Run Pipeline" button.

### Requirement 11: Opportunity Engine Data Model

**User Story:** As a developer, I want a structured data model for opportunities, decisions, and portfolio metrics, so that the system has reliable persistence and supports analytics queries.

#### Acceptance Criteria

1. THE Attention_Portfolio_Manager SHALL store Opportunities in a PostgreSQL table with columns: id (UUID primary key), avatar_id (FK to avatars), decision_date (date), thread_id (FK to reddit_threads, nullable), subreddit (varchar 255), opportunity_type (enum: comment/post/reply), visibility_score (integer 0-100), competition_score (integer 0-100), trust_potential_score (integer 0-100), karma_potential_score (integer 0-100), risk_score (integer 0-100), strategic_alignment_score (integer 0-100), composite_score (integer 0-100), expected_return (JSONB), status (enum: evaluated/selected/rejected/executed), rejection_reason (text nullable), created_at (timestamptz).
2. THE Attention_Portfolio_Manager SHALL store Decision_Records in a PostgreSQL table with columns: id (UUID primary key), avatar_id (FK to avatars), decision_date (date), avatar_state (JSONB), community_states (JSONB), market_state (JSONB), client_state (JSONB), portfolio_allocation (JSONB), budget_available (JSONB), budget_consumed (JSONB), metrics (JSONB), zero_day (boolean default false), created_at (timestamptz).
3. THE Attention_Portfolio_Manager SHALL store Zero_Day_Reports in a PostgreSQL table with columns: id (UUID primary key), avatar_id (FK to avatars), report_date (date), reason_code (varchar 50), report_content (JSONB), recommendations (JSONB), created_at (timestamptz).
4. THE Attention_Portfolio_Manager SHALL store Performance_Metrics in a PostgreSQL table with columns: id (UUID primary key), avatar_id (FK to avatars), metric_date (date), return_on_attention (float), risk_adjusted_return (float), portfolio_diversification (float), decision_accuracy (float), opportunity_cost (float), zero_day_rate (float), actions_taken (integer), karma_gained (integer), created_at (timestamptz).
5. THE Attention_Portfolio_Manager SHALL create Alembic migrations for all new tables with: indexes on (avatar_id, decision_date) for all tables, index on status for opportunities, and a unique constraint on (avatar_id, decision_date) for Decision_Records to prevent duplicate daily runs.

### Requirement 12: Admin Dashboard — Portfolio View

**User Story:** As a platform operator, I want to see each avatar's attention portfolio in a dashboard, so that I can monitor investment decisions and intervene when needed.

#### Acceptance Criteria

1. THE Attention_Portfolio_Manager SHALL provide an admin dashboard panel showing for each avatar: today's Portfolio_Allocation (pie chart or percentage bars), budget utilization (consumed/available), top 3 selected opportunities with their scores, and portfolio metrics (Return_On_Attention, Decision_Accuracy, Zero_Day_Rate).
2. WHEN the operator clicks on a specific avatar's portfolio view, THE Attention_Portfolio_Manager SHALL display the full Decision_Record for today including: all evaluated opportunities ranked by composite score, risk assessment breakdown for top 10, the allocation reasoning, and any excluded opportunities with reasons.
3. WHEN a Zero_Day_Report exists for the current day, THE Attention_Portfolio_Manager SHALL display it prominently in the avatar's portfolio view with the reason code highlighted and actionable recommendations listed.
4. THE Attention_Portfolio_Manager SHALL provide a "Portfolio Health" summary across all avatars showing: total actions planned today, total zero-day avatars today, average Return_On_Attention across all avatars (7-day rolling), and any avatars with alerts (low Decision_Accuracy or high Zero_Day_Rate).
5. THE Attention_Portfolio_Manager SHALL allow the operator to override the day's allocation for a specific avatar: manually select or exclude opportunities from the plan, triggering re-allocation of the remaining budget.

### Requirement 13: Karma Outcome Feedback Loop

**User Story:** As a platform operator, I want the system to track actual karma outcomes of executed actions, so that the prediction model improves based on real-world results.

#### Acceptance Criteria

1. WHEN an EPGSlot reaches "posted" status, THE Attention_Portfolio_Manager SHALL schedule karma outcome checks at 4 hours, 24 hours, and 48 hours after posting using the existing karma tracking infrastructure.
2. WHEN a karma outcome check completes, THE Attention_Portfolio_Manager SHALL update the corresponding Opportunity record with actual_karma (integer), actual_removal (boolean), and outcome_checked_at (timestamptz).
3. WHEN the 24-hour karma outcome is available, THE Attention_Portfolio_Manager SHALL compare actual_karma to the Expected_Karma from the opportunity's expected_return JSONB and compute deviation_percentage as ((actual - expected) / expected) × 100.
4. THE Attention_Portfolio_Manager SHALL compute Decision_Accuracy for the daily Performance_Metrics record as: count of actions with actual_karma > 0 divided by total actions with outcome data, multiplied by 100.
5. THE Attention_Portfolio_Manager SHALL compute Opportunity_Cost for the daily Performance_Metrics record as: the highest Expected_Return_Score among rejected opportunities minus the average actual return of selected actions, capped at 0 minimum (no negative opportunity cost).
6. IF an action results in removal (actual_removal = true), THEN THE Attention_Portfolio_Manager SHALL increase the Risk_Score weight for the subreddit moderation sensitivity factor by 5% for future evaluations of that avatar-subreddit pair.

### Requirement 14: Configurable Return Weights and Strategy Tuning

**User Story:** As a platform operator, I want to configure how the system weighs different return dimensions per client, so that portfolio allocation aligns with each client's unique strategic objectives.

#### Acceptance Criteria

1. THE Attention_Portfolio_Manager SHALL store return dimension weights as a JSONB configuration on the Client model: karma_weight (0-100), trust_weight (0-100), visibility_weight (0-100), influence_weight (0-100), strategic_value_weight (0-100), where all weights are normalized to sum to 100 during computation.
2. WHEN no custom weights are configured for a client, THE Attention_Portfolio_Manager SHALL use default weights: karma_weight=20, trust_weight=25, visibility_weight=20, influence_weight=15, strategic_value_weight=20.
3. THE Attention_Portfolio_Manager SHALL provide an admin form (HTMX partial) to configure return weights per client, with validation that all five weights are non-negative integers and the system normalizes them to sum to 100 during computation.
4. WHEN the operator updates return weights for a client, THE Attention_Portfolio_Manager SHALL apply the new weights starting from the next daily allocation run (not retroactively).
5. THE Attention_Portfolio_Manager SHALL store Portfolio_Allocation templates as configurable presets: "balanced" (equal distribution), "aggressive_growth" (60% primary, 30% secondary, 10% experimental), "conservative" (40% primary, 40% secondary, 20% safe), allowing operators to assign a preset to an avatar or define custom allocation percentages.
