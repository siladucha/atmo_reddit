# Implementation Plan: EPG 2.0 — Attention Portfolio Manager

## Overview

Convert the existing EPG thread-selection logic into a multi-stage investment decision engine. The system reframes each avatar's daily publishing program as portfolio allocation — Reddit as attention market, each avatar as an investment fund, each publication as an investment decision. Implementation uses Python 3.11+ / FastAPI / SQLAlchemy 2.0 / Celery + Redis / PostgreSQL 16 with Hypothesis for property-based testing.

## Tasks

- [x] 1. Data models and Alembic migration
  - [x] 1.1 Create SQLAlchemy models for EPG 2.0 tables
    - Create `app/models/opportunity.py` with `Opportunity` model (UUID PK, avatar_id FK, decision_date, thread_id FK, hobby_post_id, subreddit, opportunity_type, six dimension scores with CHECK 0-100, composite_score, expected_return JSONB, status, rejection_reason, actual_karma, actual_removal, outcome_checked_at, created_at)
    - Create `app/models/decision_record.py` with `DecisionRecord` model (UUID PK, avatar_id FK, decision_date, avatar_state JSONB, community_states JSONB, market_state JSONB, client_state JSONB, portfolio_allocation JSONB, budget_available JSONB, budget_consumed JSONB, metrics JSONB, zero_day boolean, created_at, UNIQUE(avatar_id, decision_date))
    - Create `app/models/zero_day_report.py` with `ZeroDayReport` model (UUID PK, avatar_id FK, report_date, reason_code, report_content JSONB, recommendations JSONB, created_at)
    - Create `app/models/performance_metric.py` with `PerformanceMetric` model (UUID PK, avatar_id FK, metric_date, return_on_attention float, risk_adjusted_return float, portfolio_diversification float, decision_accuracy float, opportunity_cost float, zero_day_rate float, actions_taken int, karma_gained int, created_at, UNIQUE(avatar_id, metric_date))
    - Add indexes: (avatar_id, decision_date) on all tables, status index on opportunities, composite index (avatar_id, decision_date, status) on opportunities
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

  - [x] 1.2 Extend Client model with EPG 2.0 fields
    - Add `return_weights` JSONB column (default: `{"karma": 20, "trust": 25, "visibility": 20, "influence": 15, "strategic_value": 20}`)
    - Add `brand_mention_cap` Integer column (nullable)
    - Add `max_comments_per_month` Integer column (nullable)
    - _Requirements: 14.1, 14.2, 4.6, 8.5_

  - [x] 1.3 Create Alembic migration for all EPG 2.0 tables
    - Single migration file `epg2_01_attention_portfolio_tables.py`
    - CREATE TABLE opportunities (with CHECK constraints + indexes)
    - CREATE TABLE decision_records (with UNIQUE constraint + indexes)
    - CREATE TABLE zero_day_reports (with indexes)
    - CREATE TABLE performance_metrics (with UNIQUE constraint + indexes)
    - ALTER TABLE clients ADD COLUMN return_weights, brand_mention_cap, max_comments_per_month
    - Include downgrade operations (DROP TABLEs, DROP COLUMNs)
    - _Requirements: 11.5_

  - [x] 1.4 Register new models in app model imports
    - Add imports to `app/models/__init__.py` or equivalent module registry
    - Ensure models are discoverable by Alembic autogenerate
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

- [x] 2. Checkpoint - Verify migration
  - Ensure migration applies cleanly, all models are importable, ask the user if questions arise.

- [x] 3. Portfolio Manager dataclasses and configuration
  - [x] 3.1 Create portfolio manager configuration dataclasses
    - Create `app/services/portfolio_manager.py` with dataclasses: `AttentionBudget` (max_comments, max_posts, max_total_actions, acceptable_risk_level), `ReturnWeights` (karma, trust, visibility, influence, strategic_value with normalized property), `PortfolioAllocation` (categories dict, preset string, validate method), `PortfolioConfig`
    - Implement `AttentionBudget.from_avatar()` deriving budget from phase (Phase 1: 3/0/40, Phase 2: 7/2/60, Phase 3: 12/3/75)
    - Implement `AttentionBudget.apply_monthly_cap()` reducing daily budget based on remaining monthly allowance / days remaining
    - Implement `ReturnWeights.from_client()` loading custom weights from client.return_weights or defaults
    - Implement `PortfolioAllocation.from_avatar_profile()` with presets: balanced, aggressive_growth, conservative
    - _Requirements: 4.1, 4.2, 4.6, 5.1, 5.2, 14.1, 14.2, 14.5_

  - [ ]* 3.2 Write property tests for budget and allocation dataclasses
    - **Property 7: Budget is a hard ceiling** — verify budget limits are never exceeded
    - **Property 8: Monthly cap reduces effective daily budget** — verify min(phase_daily, ceil(remaining/days)) formula
    - **Property 9: Portfolio allocation percentages sum to 100** — verify all presets and custom allocations
    - **Validates: Requirements 4.4, 4.5, 4.6, 5.1, 5.3**

  - [ ]* 3.3 Write unit tests for portfolio configuration
    - Test Phase 1/2/3 default budgets match specification
    - Test default return weights = 20/25/20/15/20
    - Test allocation presets (balanced/aggressive/conservative) all sum to 100
    - Test monthly cap computation with edge cases (last day of month, 0 remaining)
    - _Requirements: 4.1, 4.2, 14.2_

- [x] 4. Opportunity Engine service
  - [x] 4.1 Implement opportunity scoring functions
    - Create `app/services/opportunity_engine.py`
    - Implement `compute_visibility(thread, sub_size)` → 0-100 (fresher=higher, moderate ups=higher, fewer comments=higher)
    - Implement `compute_competition(thread)` → 0-100 (fewer comments=higher, no top-comment domination=higher)
    - Implement `compute_trust_potential(thread, avatar, thread_score)` → 0-100 (topic alignment, expertise opportunity, discussion depth)
    - Implement `compute_karma_potential(thread, avatar, subreddit_karma_avg)` → 0-100 (historical avg, engagement velocity, position)
    - Implement `compute_strategic_alignment(thread, thread_score, client, avatar)` → 0-100 (ThreadScore.strategic, client keywords, niche relevance)
    - All scores clamped to [0, 100] integers
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6_

  - [x] 4.2 Implement opportunity scanning and deduplication
    - Implement `scan_opportunities(db, avatar, client, plan_date)` → list[Opportunity]
    - Query ThreadScore records tagged "engage" or "monitor" for avatar's assigned subreddits
    - Query HobbySubreddit posts for Phase 1 / hobby allocation
    - Deduplicate: exclude threads where avatar already has draft/posted comment
    - Deduplicate: exclude threads in today's existing non-planned slots
    - Compute composite score as weighted average of 5 dimensions (risk filled later by Risk Engine)
    - Sort by composite desc, cap at 10-50 results
    - Log `market_scarcity` if fewer than 10 scoreable threads found
    - _Requirements: 1.1, 1.7, 1.8_

  - [ ]* 4.3 Write property tests for Opportunity Engine
    - **Property 1: Opportunity scores are bounded** — all six dimensions and composite in [0, 100]
    - **Property 2: Opportunity list is bounded and sorted** — 10-50 items, descending composite
    - **Property 16: Topic saturation reduces visibility** — 5+ threads same topic → -30 visibility
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 8.4**

  - [ ]* 4.4 Write unit tests for Opportunity Engine
    - Test visibility scoring with fresh vs old threads
    - Test competition scoring with empty vs crowded threads
    - Test deduplication excludes existing drafts
    - Test market scarcity logging when < 10 threads
    - _Requirements: 1.2, 1.3, 1.7, 1.8_

- [x] 5. Risk Engine service
  - [x] 5.1 Implement risk assessment logic
    - Create `app/services/risk_engine.py`
    - Implement `assess_risk(opportunity, avatar, community_state)` → RiskAssessment
    - Compute base_score from: account_age_factor, karma_factor, frequency_factor, moderation_factor, content_type_factor
    - Apply health_modifier: +20 for warned/suspicious avatars (clamped at 100)
    - Apply phase_multiplier: 2.0 for Phase 1 (on sensitivity + frequency factors), 1.0 for Phase 3
    - Add moderation_factor: +30 when 3+ removals in last 30 days for avatar-subreddit pair
    - Set flags: "high_risk" if score > 70, "critical_risk" if score > 90
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6, 8.3_

  - [x] 5.2 Implement risk filtering and historical removal rate
    - Implement `compute_historical_removal_rate(db, avatar_id, subreddit, window_days=90)` → float
    - Implement `filter_by_risk(opportunities, risk_assessments, acceptable_risk_level)` → (viable, rejected_with_reasons)
    - Viable: Risk_Score <= threshold; Rejected: Risk_Score > threshold with reason logged
    - _Requirements: 2.4, 2.5_

  - [ ]* 5.3 Write property tests for Risk Engine
    - **Property 3: Risk score is bounded and phase-weighted** — [0,100], Phase 1 >= Phase 3 for same input
    - **Property 4: Health status adds fixed risk modifier** — warned/suspicious adds exactly +20 (clamped)
    - **Property 5: Risk threshold filtering is sound** — viable all <= threshold, rejected all > threshold
    - **Property 15: Moderation history increases risk** — 3+ removals → +30 points
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.5, 2.6, 8.3**

  - [ ]* 5.4 Write unit tests for Risk Engine
    - Test Phase 1 risk scoring doubles sensitivity/frequency factors
    - Test health_modifier adds exactly 20 for warned avatars
    - Test high_risk flag at score 71, critical_risk at score 91
    - Test filtering partitions correctly at boundary (score == threshold → viable)
    - _Requirements: 2.1, 2.2, 2.3, 2.5, 2.6_

- [x] 6. Return Engine service
  - [x] 6.1 Implement expected return estimation
    - Create `app/services/return_engine.py`
    - Implement `estimate_returns(opportunity, avatar, client, weights, subreddit_karma_multiplier)` → ExpectedReturn
    - Implement `compute_expected_karma(opportunity, avatar, subreddit_avg, multiplier)` → int (regression from historical avg + velocity + position)
    - Compute trust: expertise demonstration + helping + dialogue potential → 0-100
    - Compute visibility: sub size + thread position + cross-post potential → 0-100
    - Compute influence: discussion provocation + authority proximity → 0-100
    - Compute strategic_value: entity linking + phase strategy fit → 0-100
    - Compute composite as normalized weighted sum of 5 dimensions → [0, 100]
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 6.2 Implement karma multiplier with model correction
    - Implement `get_subreddit_karma_multiplier(db, avatar_id, subreddit)` → float
    - Start at 1.0, increase 10% for consistent over-performance (5+ actions actual > 150% predicted)
    - Decrease 10% for consistent under-performance (5+ actions actual < 50% predicted)
    - Clamp to [0.5, 2.0]
    - _Requirements: 9.3_

  - [ ]* 6.3 Write property tests for Return Engine
    - **Property 6: Expected Return dimensions bounded and composite is weighted sum** — karma >= 0, others [0,100], composite = normalized weighted sum
    - **Property 18: Model correction triggers on deviation threshold** — >50% deviation → correction event, 5+ → multiplier ±10%
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 9.2, 9.3**

  - [ ]* 6.4 Write unit tests for Return Engine
    - Test default weights produce expected composite
    - Test custom client weights override defaults
    - Test karma multiplier clamped to [0.5, 2.0]
    - Test multiplier increases after 5 over-performances
    - _Requirements: 3.6, 9.3, 14.1, 14.2_

- [x] 7. Checkpoint - Core engines verified
  - Ensure all tests pass for Opportunity, Risk, and Return engines. Ask the user if questions arise.

- [x] 8. Allocation Engine service
  - [x] 8.1 Implement portfolio allocation algorithm
    - Create `app/services/allocation_engine.py`
    - Implement `allocate_portfolio(opportunities, risk_assessments, expected_returns, budget, allocation, avatar)` → AllocationResult
    - Algorithm: assign opportunities to categories, pick top by risk-adjusted return (composite / risk_score) per category
    - Enforce diversification: no single subreddit > 40% of actions
    - Reallocate empty categories proportionally to others with viable opportunities
    - Apply timing via existing timing_engine (jitter ±30%, min 45 min, active hours 08:00-23:00)
    - Compute Shannon entropy diversification metric
    - Return AllocationResult with selected actions, rejected with reasons, budget consumed/remaining, diversification score, reallocation log
    - _Requirements: 5.1, 5.4, 5.5, 5.6, 5.7_

  - [x] 8.2 Implement diversification enforcement and entropy computation
    - Implement `enforce_subreddit_cap(selected, max_share=0.4)` — drop lowest-return actions from over-represented subreddits
    - Implement `compute_diversification(actions)` → float (Shannon entropy, 0.0 for 0-1 actions, maximal for uniform)
    - _Requirements: 5.6, 5.7_

  - [ ]* 8.3 Write property tests for Allocation Engine
    - **Property 7: Budget is a hard ceiling** — selected actions <= max_total_actions, comments <= max_comments, posts <= max_posts
    - **Property 10: Subreddit diversification cap enforced** — no subreddit > 40% when 2+ subreddits
    - **Property 11: Empty category budget reallocated fully** — total selected = min(budget, viable opportunities)
    - **Property 21: Shannon entropy non-negative and maximal for uniform** — entropy >= 0, max at uniform distribution
    - **Validates: Requirements 4.4, 5.5, 5.6, 5.7**

  - [ ]* 8.4 Write unit tests for Allocation Engine
    - Test greedy selection picks highest risk-adjusted return
    - Test subreddit cap removes lowest-return actions from over-represented sub
    - Test empty category reallocation distributes proportionally
    - Test Shannon entropy = 0 for single-subreddit allocation
    - _Requirements: 5.4, 5.5, 5.6, 5.7_

- [x] 9. Portfolio Manager orchestrator
  - [x] 9.1 Implement build_portfolio main function
    - Implement `build_portfolio(db, avatar, client)` → EPGResult in `app/services/portfolio_manager.py`
    - Pipeline: compute AttentionBudget → run Opportunity Engine → run Risk Engine → run Return Engine → run Allocation Engine
    - Persist: Opportunity records, Decision Record, EPGSlot records
    - If zero actions: generate Zero-Day Report instead
    - Return EPGResult compatible with existing consumers (avatar_id, phase, daily_budget, used_today, remaining, hobby_slots, business_slots, status)
    - Handle errors: partial degradation (default scores for failed dimensions), full fallback to legacy build_daily_epg()
    - Performance target: < 60 seconds per avatar
    - _Requirements: 10.1, 10.5, 6.1_

  - [x] 9.2 Implement Zero-Day Report generation
    - Generate ZeroDayReport when allocation produces zero selected actions
    - Determine reason_code: market_cold, risk_too_high, return_too_low, market_scarcity, avatar_state_unfavorable
    - Build report_content JSONB: summary, opportunities_scanned, avg_risk, highest_return, top_rejections (up to 5)
    - Build recommendations JSONB: 2-5 suggestions from predefined set (add_new_subreddits, adjust_risk_threshold, change_strategy_focus, wait_for_better_timing, review_avatar_health)
    - Persist to zero_day_reports table
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [x] 9.3 Implement Decision Record persistence
    - Create immutable Decision Record for every allocation run
    - Capture avatar_state snapshot: karma, phase, health, days_since_post, posts_today, risk_tolerance
    - Capture community_states: per-subreddit activity_24h, topic_saturation, last_mod_action, trending
    - Capture market_state: trending_topics top 5, avg_competition, temperature (hot/warm/cold)
    - Capture client_state: goals, phase_focus, brand_mentions_remaining, target_niches
    - Store budget_available, budget_consumed, portfolio_allocation, metrics (diversification, risk_adjusted_return, opportunities_scanned)
    - Enforce UNIQUE(avatar_id, decision_date) — handle idempotent re-runs gracefully
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [ ]* 9.4 Write property tests for Portfolio Manager
    - **Property 12: Zero-day report generated when no actions viable** — valid reason_code, 2-5 recommendations, required fields
    - **Property 14: Phase 1 restricts to hobby and caps risk** — all Phase 1 actions are hobby, risk capped at 40
    - **Property 17: Brand budget exhaustion excludes brand content** — no brand actions when cap exhausted
    - **Property 20: Output EPGSlots are interface-compatible** — non-null avatar_id, plan_date, valid slot_type, scheduled_at in active hours, status="planned"
    - **Validates: Requirements 6.1, 6.2, 6.3, 8.1, 8.5, 10.1, 10.5**

  - [ ]* 9.5 Write unit tests for Portfolio Manager
    - Test full pipeline produces EPGSlots for avatar with good opportunities
    - Test zero-day report generated when all opportunities rejected
    - Test decision record captures all required state snapshots
    - Test Phase 1 avatar restricted to hobby subreddits only
    - Test brand exhaustion excludes brand opportunities
    - _Requirements: 6.1, 7.1, 8.1, 8.5, 10.1_

- [x] 10. Checkpoint - Core portfolio system verified
  - Ensure all tests pass for Allocation Engine and Portfolio Manager. Ask the user if questions arise.

- [x] 11. Integration with existing EPG pipeline
  - [x] 11.1 Implement feature flag and pipeline switch
    - Add `epg2_enabled` system setting (default "true") to settings table via seed or migration
    - Modify `build_and_generate_epg_all_avatars` Celery task to check `epg2_enabled` flag
    - If enabled: call `build_portfolio(db, avatar, client)` instead of `build_daily_epg(db, avatar, client)`
    - If disabled: legacy path unchanged
    - Add system settings: `epg2_min_opportunities`, `epg2_max_opportunities`, `epg2_min_return_threshold`, `epg2_subreddit_max_share`, `epg2_zero_day_alert_threshold`, `epg2_decision_retention_days`
    - _Requirements: 10.5, 10.6_

  - [x] 11.2 Wire EPGSlot creation from allocation results
    - Convert each SelectedAction into an EPGSlot record: avatar_id, plan_date, slot_type (hobby/professional), scheduled_at (from timing_engine), thread_id, subreddit, status="planned"
    - Use existing timing_engine for scheduled_at (jitter ±30%, min 45 min interval, active hours 08:00-23:00, peak hour bias)
    - Respect all existing safety gates in posting_safety.py (no changes needed — downstream compatibility)
    - Update opportunity.status to "selected" for chosen, "rejected" for excluded
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [x] 11.3 Implement state-based decision context
    - Implement community_state gathering: query recent activity per subreddit (posts/24h), topic saturation detection (5+ same-topic in 24h), last mod action against avatar
    - Implement market_state gathering: aggregate trending topics, compute avg competition, classify temperature (hot/warm/cold by opportunity density)
    - Enforce Phase 1 restriction: all opportunities filtered to hobby subreddits, risk_level capped at 40
    - Enforce timing: defer actions if avatar.last_posted_at within 45 minutes (respect timing_engine constraints)
    - Enforce brand budget exhaustion: exclude brand-related content when brand_mentions >= brand_mention_cap
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [ ]* 11.4 Write integration tests for EPG pipeline
    - Test full pipeline from ThreadScores → EPGSlots with feature flag on
    - Test fallback to legacy build_daily_epg when feature flag off
    - Test EPGSlots created by EPG 2.0 are processed by existing execute_pending_posts
    - Test timing_engine integration produces valid scheduled_at values
    - _Requirements: 10.1, 10.4, 10.5, 10.6_

- [x] 12. Karma outcome feedback loop
  - [x] 12.1 Implement karma outcome tracking for opportunities
    - Create Celery task `check_karma_outcomes` scheduled at 4h and 28h after posting
    - When EPGSlot reaches "posted" status, schedule karma checks at 4h, 24h, 48h
    - On check completion: update opportunity record with actual_karma, actual_removal, outcome_checked_at
    - Compute deviation_percentage: ((actual - expected) / expected) × 100
    - Log model_correction_event when |deviation| > 50%
    - _Requirements: 13.1, 13.2, 13.3_

  - [x] 12.2 Implement removal feedback and risk weight adjustment
    - When actual_removal = true: increase moderation_sensitivity risk weight by 5% for avatar-subreddit pair
    - Store adjustment in a configuration structure (JSONB on avatar or separate table)
    - Apply accumulated adjustments in subsequent Risk Engine evaluations
    - _Requirements: 13.6_

  - [ ]* 12.3 Write property tests for feedback loop
    - **Property 18: Model correction triggers on deviation threshold** — >50% deviation → event logged, 5+ consistent → multiplier ±10%
    - **Property 22: Removal feedback increases risk weight** — removal → +5% moderation sensitivity for pair
    - **Validates: Requirements 9.2, 9.3, 13.6**

  - [ ]* 12.4 Write unit tests for feedback loop
    - Test karma check updates opportunity with actual values
    - Test deviation > 50% logs correction event
    - Test 5 over-performances increases multiplier by 10%
    - Test removal increases risk weight by 5% for the subreddit pair
    - _Requirements: 13.1, 13.2, 13.3, 13.6_

- [x] 13. Performance metrics computation
  - [x] 13.1 Implement daily performance metrics Celery task
    - Create `compute_daily_performance_metrics` task (scheduled 01:00 daily)
    - Compute per-avatar: Return_On_Attention (karma_gained / actions_taken), Risk_Adjusted_Return (ROA / avg_risk), Portfolio_Diversification (Shannon entropy), Decision_Accuracy (% positive karma actions), Opportunity_Cost (max(0, highest_rejected - avg_selected)), Zero_Day_Rate (% zero-day in last 30 days)
    - Persist to performance_metrics table
    - _Requirements: 9.1, 13.4, 13.5_

  - [x] 13.2 Implement zero-day rate alert and decision record archival
    - Compute zero_day_rate over last 14 days per avatar
    - If rate > 50%: generate admin dashboard alert (visible in portfolio health panel)
    - If Decision_Accuracy < 50% over 14 days: generate model review alert
    - Implement `archive_old_decision_records` task (01:30 daily): prune records > 90 days (keep metadata, remove full opportunity list)
    - _Requirements: 6.5, 6.6, 9.5, 7.6_

  - [ ]* 13.3 Write property tests for performance metrics
    - **Property 13: Zero-day rate computed correctly** — rate = (zero_day_count / 30) × 100, alert iff 14-day rate > 50%
    - **Property 19: Performance metrics formulas correct** — Decision_Accuracy, Opportunity_Cost, ROA formulas match spec
    - **Validates: Requirements 6.5, 6.6, 9.1, 13.3, 13.4, 13.5**

  - [ ]* 13.4 Write unit tests for performance metrics
    - Test ROA computation with known values
    - Test zero-day rate = 0 for avatar with no zero-day reports
    - Test alert generated at exactly 50% threshold (14-day window)
    - Test archival retains metadata, prunes opportunity details after 90 days
    - _Requirements: 9.1, 6.5, 6.6, 7.6_

- [x] 14. Checkpoint - Full backend pipeline verified
  - Ensure all tests pass, all Celery tasks registered, pipeline runs end-to-end. Ask the user if questions arise.

- [x] 15. Admin UI — Portfolio dashboard
  - [x] 15.1 Create portfolio summary HTMX partial
    - Create `app/templates/partials/portfolio_summary.html`
    - Show: today's Portfolio_Allocation (percentage bars per category), budget utilization (consumed/available), top 3 selected opportunities with scores, portfolio metrics (ROA, Decision_Accuracy, Zero_Day_Rate)
    - Add route `GET /admin/avatars/{id}/portfolio` returning the partial
    - Wire into avatar detail page as a new "Portfolio" tab (HTMX lazy-load)
    - _Requirements: 12.1_

  - [x] 15.2 Create decision record drill-down partial
    - Create `app/templates/partials/portfolio_decision.html`
    - Show: all evaluated opportunities ranked by composite, risk breakdown for top 10, allocation reasoning, excluded opportunities with reasons, full decision chain expandable
    - Add route `GET /admin/avatars/{id}/portfolio/decision/{date}` returning the partial
    - _Requirements: 12.2, 7.5_

  - [x] 15.3 Create zero-day report view partial
    - Create `app/templates/partials/portfolio_zero_day.html`
    - Show: reason_code highlighted, summary, opportunities_scanned, avg_risk, highest_return, top rejections list, actionable recommendations
    - Display prominently when zero-day exists for current day
    - Add route `GET /admin/avatars/{id}/portfolio/zero-day` returning the partial
    - _Requirements: 12.3_

  - [x] 15.4 Create portfolio health system-wide panel
    - Create `app/templates/partials/portfolio_health.html`
    - Show: total actions planned today, total zero-day avatars today, average ROA across all avatars (7-day rolling), avatars with alerts (low accuracy, high zero-day rate)
    - Add route `GET /admin/dashboard/portfolio-health` returning the partial
    - Wire into admin dashboard as a panel (alongside existing topology panel)
    - _Requirements: 12.4_

  - [x] 15.5 Create performance metrics chart partial
    - Create `app/templates/partials/portfolio_metrics.html`
    - Show: ROA trend (7/14/30 days), Risk_Adjusted_Return trend, Diversification score, Decision_Accuracy %, Zero_Day_Rate
    - Add route `GET /admin/avatars/{id}/portfolio/metrics` returning the partial
    - _Requirements: 9.4_

- [x] 16. Admin UI — Configuration and overrides
  - [x] 16.1 Create return weights configuration form
    - Create `app/templates/partials/client_return_weights.html`
    - HTMX form with 5 integer inputs (karma, trust, visibility, influence, strategic_value)
    - Validation: all non-negative integers, system normalizes to sum=100 during computation
    - Add GET endpoint `GET /admin/clients/{id}/return-weights` returning the form
    - Add POST endpoint `POST /admin/clients/{id}/return-weights` saving weights to client.return_weights
    - Wire into client detail page
    - _Requirements: 14.1, 14.3, 14.4_

  - [x] 16.2 Create portfolio allocation override partial
    - Create `app/templates/partials/portfolio_override.html`
    - Allow operator to manually select/exclude opportunities from today's plan
    - Trigger re-allocation of remaining budget on submit
    - Add POST endpoint `POST /admin/avatars/{id}/portfolio/override`
    - _Requirements: 12.5_

  - [x] 16.3 Add EPG 2.0 system settings to admin settings page
    - Register settings in the `epg` group: epg2_enabled, epg2_min_opportunities, epg2_max_opportunities, epg2_min_return_threshold, epg2_subreddit_max_share, epg2_zero_day_alert_threshold, epg2_decision_retention_days
    - Add validators for each setting (boolean, integer ranges)
    - Ensure settings visible and editable in existing admin system settings page
    - _Requirements: 10.6, 14.5_

- [x] 17. Celery task registration and scheduling
  - [x] 17.1 Register new Celery tasks and Beat schedule
    - Register `check_karma_outcomes` task (scheduled 4h and 28h post EPG run)
    - Register `compute_daily_performance_metrics` task (01:00 daily)
    - Register `archive_old_decision_records` task (01:30 daily)
    - Add all tasks to Celery Beat schedule in worker configuration
    - Ensure tasks are importable and discoverable by worker
    - _Requirements: 9.1, 7.6, 13.1_

- [x] 18. Final checkpoint - Complete system verified
  - Ensure all tests pass, admin UI renders correctly, Celery tasks fire on schedule, feature flag toggle works for instant rollback. Ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties (22 properties from design)
- Unit tests validate specific examples and edge cases
- The feature flag `epg2_enabled` allows instant rollback to legacy EPG without deployment
- All downstream infrastructure (EPGSlot → posting pipeline → safety gates) remains unchanged
- Python 3.11+ with Hypothesis for property-based testing

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "1.4"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "4.1"] },
    { "id": 4, "tasks": ["4.2", "5.1"] },
    { "id": 5, "tasks": ["4.3", "4.4", "5.2"] },
    { "id": 6, "tasks": ["5.3", "5.4", "6.1"] },
    { "id": 7, "tasks": ["6.2"] },
    { "id": 8, "tasks": ["6.3", "6.4", "8.1"] },
    { "id": 9, "tasks": ["8.2"] },
    { "id": 10, "tasks": ["8.3", "8.4", "9.1"] },
    { "id": 11, "tasks": ["9.2", "9.3"] },
    { "id": 12, "tasks": ["9.4", "9.5"] },
    { "id": 13, "tasks": ["11.1", "11.2", "11.3"] },
    { "id": 14, "tasks": ["11.4", "12.1"] },
    { "id": 15, "tasks": ["12.2", "13.1"] },
    { "id": 16, "tasks": ["12.3", "12.4", "13.2"] },
    { "id": 17, "tasks": ["13.3", "13.4"] },
    { "id": 18, "tasks": ["15.1", "15.2", "15.3"] },
    { "id": 19, "tasks": ["15.4", "15.5", "16.1"] },
    { "id": 20, "tasks": ["16.2", "16.3", "17.1"] }
  ]
}
```
