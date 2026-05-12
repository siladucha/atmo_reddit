# Requirements Document — RAMP Pipeline v2 (Technical FRD)

**Version:** 2.0
**Date:** May 2026
**Type:** Technical (internal development use only)
**Status:** Draft

## Important Note on Operational Heuristics

This document describes the **intended architecture** of RAMP Pipeline v2. Some components are:

- **Planned for future releases** (marked with implementation phase in Appendix A)
- **Operational heuristics** based on available Reddit data, not ground-truth measurements
- **Subject to calibration** as the system accumulates engagement data

Current MVP capabilities are a subset of what is described here. See **Appendix A: Current vs Future** for implementation phasing.

> RAMP is a decision support system, not a fully autonomous AI.
> All final outputs are human-reviewed before posting. All metrics are operational heuristics, not scientific guarantees. Numerical thresholds are calibrated empirically and will be adjusted over time.

## Introduction

RAMP Pipeline v2 adds a strategic intelligence layer and operational safety controls on top of the existing Ori-built core pipeline (scrape → score → persona selection → generation → human review). The enhancement covers three areas: (1) operational guardrails — budget limits, deduplication, freshness checks, rate limiting, and phase-aware filtering; (2) strategic engine — mentor analysis, subreddit analysis, avatar strategy documents, and adaptive correction; (3) reporting and coordination — cross-avatar coordination, brand ratio tracking, and client reports.

The existing core pipeline remains unchanged. Pipeline v2 wraps it with pre-validation gates, enriched scoring signals, strategy-informed generation prompts, and post-execution tracking.

## Glossary

- **Pipeline**: The automated sequence of scrape → score → persona selection → generate → human review.
- **Avatar**: A Reddit account managed by the platform for community engagement on behalf of a client.
- **Client**: A paying customer whose brand is promoted through managed avatars.
- **Budget_Engine**: The service module that calculates and enforces daily comment limits per avatar based on account age, karma, and CQS score.
- **Strategy_Engine**: The service module that generates and maintains avatar strategy documents, mentor analyses, and subreddit analyses.
- **Scoring_Service**: The service that evaluates Reddit threads on relevance, quality, and strategic axes.
- **Generation_Service**: The service that produces comment drafts using LLM with persona and strategy context.
- **Scraping_Service**: The service that fetches Reddit threads from configured subreddits via PRAW.
- **Dedup_Service**: The service that checks whether another avatar of the same client has already commented in a thread.
- **Phase_Gate**: The filter that restricts avatar activity based on the avatar's current warming phase (Phase 1, 2, or 3).
- **Saturation_Guard**: The limiter that caps comments per subreddit per day per client.
- **Cooldown_Service**: The service that enforces minimum time intervals between consecutive comments by the same avatar.
- **Brand_Ratio_Tracker**: The service that monitors the percentage of brand-mentioning comments relative to total comments per avatar.
- **Hill_Tracker**: The service that tracks usage of "Hill I Die On" hooks across avatar comments.
- **Mentor**: A high-performing Reddit user whose commenting style is analyzed to inform avatar strategy.
- **Subreddit_Profile**: An analysis of a subreddit's top comments, culture, tone, and engagement patterns.
- **Strategy_Document**: A per-avatar document containing goals, subreddit priorities, tone guidelines, cadence rules, and hook inventory.
- **Client_Report**: A periodic (weekly/monthly) client-facing document combining raw avatar data from the Admin Layer, AI-generated strategy from the Strategy_Engine, and performance forecasts.
- **Forecast**: A projection subsection within Strategy_Document and Client_Report containing predicted karma, phase transitions, and conversion estimates. **Note:** Forecasts are trend-based heuristics, not guarantees.
- **CQS_Score**: Community Quality Score — Reddit's internal metric reflecting account standing in specific communities. **Note:** Not directly queryable via API; inferred from engagement patterns.
- **Thread_Freshness**: The age of a Reddit thread measured from its creation timestamp.
- **Scrape_Freshness**: The elapsed time since the last successful scrape of a subreddit.
- **Admin_UI**: The Jinja2 + HTMX admin panel served at `/admin/*` routes.
- **Warming_Phase**: The maturity stage of an avatar — Phase 1 (months 1-2), Phase 2 (months 3-4), Phase 3 (month 5+).
- **Heuristic Metric**: An operational estimate based on available data. Not a ground-truth measurement. Subject to calibration.

## Core Concepts: The Unified Workflow

RAMP operates as a closed loop between three layers:

1. **Admin Layer** — Operator views and manages avatar data, monitors activity, reviews drafts.
2. **Strategy Layer** — AI analyzes data and generates strategy documents (goals, priorities, tone).
3. **Reporting Layer** — System exports client-facing reports that combine raw data + strategy + forecast.

### The Loop

```
Admin UI (Raw data + controls)
    → Strategy Engine (AI analysis + generation)
        → Pipeline (Execution)
            → Client Report (Data + Strategy + Forecast)
                → Feedback → Admin UI
                → Correction loop → Strategy Engine
```

Every avatar report is derived from admin data plus AI-generated strategy and forecast.

### Mapping: Admin Panel → Client Report → Strategy Document

| Admin Panel Section | Client Report Section | Strategy Document Section |
|---------------------|----------------------|---------------------------|
| Overview (karma, status) | Executive Summary | Goals |
| Performance (activity) | Activity (Last 30 days) | — |
| Safety / Shadowban | Avatar Health | — |
| Phase | Warming Phase | Phase-based rules |
| Presence (subreddits) | Subreddit Activity | Subreddit Priorities |
| Profile (voice, hill) | Voice Profile (preview) | Tone calibration, Hook inventory |
| — (AI generated) | Strategy (what to do) | Full document |
| — (AI generated) | Forecast | Forecast subsection |
| — (AI generated) | Questions for Client | — |
| Drafts (posted/rejected) | (internal) | Correction triggers |

## Requirements

### Requirement 1: Budget Dashboard

**User Story:** As an operator, I want to see daily comment limits and remaining budget per avatar, so that I can monitor capacity and avoid over-posting.

> **Heuristic note:** The budget formula below is an empirical calibration based on observed Reddit rate-limiting patterns. The weights (7 days per unit, 500 karma per unit, 20 CQS per unit) are initial values subject to adjustment after production data collection.

> **Implementation note:** Partially exists. `safety.py` already enforces `MAX_COMMENTS_PER_DAY = 8` and phase-based caps. This requirement replaces the fixed constant with a dynamic formula and adds a UI dashboard.

#### Acceptance Criteria

1. THE Budget_Engine SHALL calculate daily comment limits per avatar using the formula: `base_limit = min(floor(account_age_days / 7), 10) + min(floor(comment_karma / 500), 5) + min(floor(cqs_score / 20), 3)`, yielding a value in the range 0–18.
2. THE Budget_Engine SHALL apply the MINIMUM of the formula result and the phase-based cap from Requirement 12 (Phase 1: 3, Phase 2: 7, Phase 3: formula uncapped).
3. IF an avatar's `reddit_account_created` is NULL, THEN THE Budget_Engine SHALL compute `account_age_days` from the avatar's `created_at` timestamp as a fallback.
4. IF an avatar's `cqs_score` is NULL or unavailable, THEN THE Budget_Engine SHALL treat the CQS component as 0 when calculating the daily limit.
5. THE Admin_UI SHALL display a Budget Dashboard showing each active avatar's daily limit, comments used today, and remaining capacity, where "active" means `active = true` and `is_frozen = false`.
6. WHEN an avatar's remaining daily budget reaches zero, THE Budget_Engine SHALL mark that avatar as exhausted for the current UTC day and THE Generation_Service SHALL skip that avatar for thread assignment.
7. THE Budget Dashboard SHALL group avatars by client and display a client-level aggregate of total daily capacity, total comments used, and total remaining capacity.
8. THE Budget_Engine SHALL reset all daily counters at 00:00 UTC each day.
9. THE Budget Dashboard SHALL refresh its data automatically every 60 seconds via HTMX polling.

### Requirement 2: Cross-Avatar Deduplication

**User Story:** As an operator, I want the system to prevent multiple avatars of the same client from commenting in the same thread, so that the client's presence appears natural and not coordinated.

> **Implementation note:** Partially exists. `ai_pipeline.py` already filters threads that have ANY draft for the client (`threads_with_drafts` subquery). This is stricter than R2 — it excludes threads even for the same avatar. R2 adds explicit logging and a configurable lookback window.

#### Acceptance Criteria

1. WHEN the Generation_Service selects threads for comment generation, THE Dedup_Service SHALL exclude threads where any other avatar belonging to the same client has an existing comment draft with status "approved" or "posted" created within the last 30 days.
2. WHEN the Generation_Service selects threads for comment generation, THE Dedup_Service SHALL exclude threads where any other avatar belonging to the same client has a pending comment draft regardless of its age.
3. THE Dedup_Service SHALL identify existing engagement by matching on `client_id` and `thread_id`, excluding drafts belonging to the current avatar and excluding drafts with status "rejected".
4. IF a thread is excluded by deduplication, THEN THE System SHALL log the exclusion as an activity event with type "dedup_excluded" including the excluded thread ID, the avatar ID that was blocked, and the avatar ID that holds the existing draft.
5. THE deduplication lookback window for "approved" and "posted" drafts SHALL be configurable via System_Settings with key `dedup_lookback_days` and default value "30".

### Requirement 3: Thread Freshness Filter

**User Story:** As an operator, I want the system to skip threads older than 48 hours, so that avatars only engage with active conversations where comments will be seen.

> **Implementation note:** Scraping already uses `max_age_hours=24` when fetching from Reddit. This requirement adds a second filter at scoring/generation time for threads that aged past the threshold while sitting in the DB.

#### Acceptance Criteria

1. WHEN the Scoring_Service evaluates threads for scoring, THE System SHALL exclude threads where `created_at` is more than the configured `thread_max_age_hours` before the current UTC time.
2. WHEN the Generation_Service selects threads for generation, THE System SHALL exclude threads where `created_at` is more than the configured `thread_max_age_hours` before the current UTC time.
3. THE thread freshness threshold SHALL be configurable via System_Settings with key `thread_max_age_hours`, default value "48", and valid range 1–168.
4. IF a thread has a NULL `created_at` value, THEN THE System SHALL use `scraped_at` as a fallback for age calculation.
5. WHEN a thread is excluded due to freshness, THE System SHALL log the exclusion as an activity event with type "thread_too_old" including the thread ID and thread age in hours.

### Requirement 4: Scoring Cost Preview

**User Story:** As an operator, I want to see the estimated LLM cost before running a scoring batch, so that I can make informed decisions about when and how many threads to score.

#### Acceptance Criteria

1. WHEN an operator initiates a scoring batch for a specific client via Admin_UI, THE System SHALL display the number of unscored threads (threads without a `ThreadScore` record for this client) and the estimated cost formatted as USD with 2 decimal places.
2. THE cost estimate SHALL use the formula: `estimated_cost = unscored_thread_count * ((4000 * $0.075 / 1_000_000) + (200 * $0.30 / 1_000_000))` based on Gemini Flash pricing with 4000 avg input tokens and 200 avg output tokens per thread.
3. THE cost preview SHALL include only threads that pass the thread freshness filter (thread age ≤ `thread_max_age_hours`) and are not locked (`is_locked = false`) in the unscored thread count.
4. WHEN the cost preview is displayed, THE Admin_UI SHALL require operator confirmation (proceed or cancel) before executing the scoring batch.
5. IF the operator cancels after viewing the cost preview, THEN THE System SHALL abort the scoring batch without scoring any threads.
6. IF the number of eligible unscored threads is zero, THEN THE System SHALL display a message indicating no threads are available for scoring and disable the proceed action.

### Requirement 5: Phase-Aware Filtering

**User Story:** As an operator, I want the pipeline to restrict avatar activity based on warming phase, so that new avatars build credibility before engaging in brand-related discussions.

> **Implementation note:** FULLY EXISTS. `services/phase.py` → `PhasePolicy.check_comment_allowed()` implements Phase 1/2/3 restrictions including subreddit type filtering, brand mention classification (explicit_brand_link, explicit_brand_name, inferred_brand), and daily limits. Activity events logged as "policy_block". No new development needed — this entry exists for traceability.

#### Acceptance Criteria

1. WHILE an avatar is in Phase 1 (account age 0-59 days), THE Phase_Gate SHALL restrict the avatar to subreddits in `avatar.hobby_subreddits` only, excluding professional and brand subreddits.
2. WHILE an avatar is in Phase 2 (account age 60-120 days), THE Phase_Gate SHALL allow the avatar to engage in hobby and professional subreddits (`hobby_subreddits` + `business_subreddits`), but block comments containing explicit brand name or brand link.
3. WHILE an avatar is in Phase 3 (account age 121+ days), THE Phase_Gate SHALL allow the avatar to engage in all subreddit types including brand-relevant threads, subject to brand ratio limits.
4. THE Phase_Gate SHALL determine the current phase from the avatar's `warming_phase` field (maintained by PhaseEvaluator).
5. WHEN the Phase_Gate excludes a thread for an avatar, THE System SHALL log the exclusion as an activity event with type "policy_block" including the avatar ID, subreddit, current phase, and exclusion reason.
6. IF the avatar's `warming_phase` is NULL or invalid, THEN THE Phase_Gate SHALL treat the avatar as Phase 1 (most restrictive).

### Requirement 6: Subreddit Saturation Guard

**User Story:** As an operator, I want to limit comments per subreddit per day, so that the client's presence in any single community does not appear suspicious.

> **Implementation note:** FULLY EXISTS. `safety.py` → `check_subreddit_limit()` enforces `MAX_COMMENTS_PER_SUBREDDIT_DAY = 2`. Called in `ai_pipeline.py` before generation. Enhancement needed: make configurable via System_Settings + add activity event logging.

#### Acceptance Criteria

1. THE Saturation_Guard SHALL enforce a maximum of 2 comments per subreddit per day per avatar (existing behavior via `check_subreddit_limit()`).
2. WHEN the daily comment count for an avatar in a subreddit reaches the saturation limit, THE Generation_Service SHALL skip remaining threads in that subreddit for the current UTC day and not invoke the LLM.
3. THE saturation limit SHALL be configurable via System_Settings with key `max_comments_per_sub_per_day`, default value "2", and accepted range 1–10.
4. THE Saturation_Guard SHALL count comment drafts with status "pending", "approved", or "posted" toward the daily limit to prevent concurrent generation from exceeding the cap.
5. WHEN a thread is skipped due to saturation, THE System SHALL log the event with type "saturation_limit_reached" including the subreddit name, avatar ID, and current count.

### Requirement 7: Pre-Generation Safety Validation

**User Story:** As an operator, I want the system to verify all budget and safety limits before calling the LLM for generation, so that tokens are not wasted on comments that cannot be published.

> **Implementation note:** Partially exists. `ai_pipeline.py` calls `check_avatar_can_post()` + `check_subreddit_limit()` before generation. `check_avatar_can_post()` already checks: active → shadowban → phase policy → daily limit → type limit → cooldown → brand ratio. This requirement formalizes the check order and adds unified activity event logging.

#### Acceptance Criteria

1. WHEN the Generation_Service begins processing a thread, THE System SHALL check the avatar's daily budget remaining BEFORE invoking the LLM.
2. WHEN the Generation_Service begins processing a thread, THE System SHALL check the subreddit saturation count BEFORE invoking the LLM.
3. WHEN the Generation_Service begins processing a thread, THE System SHALL check the cooldown timer for the avatar BEFORE invoking the LLM.
4. WHEN the Generation_Service begins processing a thread, THE System SHALL check the brand ratio for the avatar BEFORE invoking the LLM.
5. WHEN the Generation_Service begins processing a thread, THE System SHALL check the avatar's Phase_Gate eligibility for the thread BEFORE invoking the LLM.
6. THE pre-generation validation SHALL execute all checks in the following sequence: phase gate → budget → saturation → cooldown → brand ratio, and SHALL stop at the first failing check without executing subsequent checks.
7. IF any pre-generation check fails, THEN THE Generation_Service SHALL skip the thread without calling the LLM and log an activity event with type "pre_generation_check_failed" including the avatar ID, thread ID, and the name of the specific check that failed.
8. IF a thread is skipped due to a pre-generation check failure, THEN THE System SHALL NOT retry generation for that avatar-thread pair during the current pipeline run.

### Requirement 8: Scrape Freshness Gate

**User Story:** As an operator, I want the system to skip scraping a subreddit if it was scraped less than 30 minutes ago, so that redundant API calls are avoided.

> **Implementation note:** Partially exists. `last_scraped_at` is tracked on both `ClientSubreddit` and `Subreddit` models. `transparency.py` → `get_scrape_freshness()` uses 24h stale threshold for UI display. This requirement adds a pre-scrape gate with configurable threshold.

#### Acceptance Criteria

1. WHEN the Scraping_Service is triggered for a subreddit, THE System SHALL check the `last_scraped_at` timestamp on the `Subreddit` record (shared registry).
2. IF the elapsed time since `last_scraped_at` is less than the configured `min_scrape_interval_minutes`, THEN THE Scraping_Service SHALL skip the scrape and log an activity event with type "scrape_too_fresh" including the subreddit name, the `last_scraped_at` value, and elapsed minutes.
3. IF `last_scraped_at` is NULL (subreddit has never been scraped), THEN THE Scraping_Service SHALL proceed with the scrape without applying the freshness gate.
4. THE scrape freshness threshold SHALL be configurable via System_Settings with key `min_scrape_interval_minutes`, default value "30", and accepted range 1–1440.
5. WHEN a scrape is skipped due to freshness, THE System SHALL NOT update the `last_scraped_at` timestamp.
6. WHEN a scrape completes successfully, THE System SHALL update the `last_scraped_at` timestamp to the current UTC time (existing behavior).

### Requirement 9: Today's Activity Summary

**User Story:** As an operator, I want to see a summary of what each avatar did today, so that I can quickly assess daily progress and identify issues.

#### Acceptance Criteria

1. THE Admin_UI SHALL display a "Today's Activity" panel showing per-avatar statistics for the current UTC day.
2. THE activity summary SHALL include: comments generated, comments approved, comments posted, threads scored, threads skipped (with breakdown by skip reason).
3. WHEN an operator selects a specific avatar, THE Admin_UI SHALL display a chronological list of all activity events for that avatar on the current day.
4. THE activity summary SHALL refresh automatically every 5 minutes via HTMX polling.

### Requirement 10: Inline Draft Editing

**User Story:** As an operator, I want to edit comment drafts directly in the admin panel, so that I can refine generated content without switching to external tools.

> **Implementation note:** CommentDraft model has `ai_draft` (original AI text) and `edited_draft` (human-edited version). Current `edit_comment()` service overwrites `ai_draft` with the AI-cleaned version. This requirement adds a human-facing inline editor for `edited_draft`.

#### Acceptance Criteria

1. THE Admin_UI review queue SHALL provide an inline text editor for the `edited_draft` field of each comment draft.
2. WHEN an operator clicks save on an inline edit, THE System SHALL persist the changes via an HTMX partial update without full page reload.
3. THE inline editor SHALL preserve the original AI-generated text in the `ai_draft` field as read-only and only modify `edited_draft`.
4. WHEN an operator saves an inline edit, THE System SHALL record the edit action in the audit log with the operator's user ID, comment draft ID, and timestamp.
5. THE inline editor SHALL display a live character count and show a visual warning when the text exceeds 1500 characters, without preventing the save.
6. IF the HTMX save request fails, THEN THE System SHALL display an error indicator to the operator and retain the unsaved text in the editor.
7. WHEN an operator opens the inline editor for a draft that has no existing `edited_draft` value, THE System SHALL pre-populate the editor with the content of `ai_draft`.

### Requirement 11: Thread Liveness Check (Reference)

**User Story:** As an operator, I want the system to verify threads are not locked before generating comments, so that tokens are not wasted on un-postable threads.

#### Acceptance Criteria

1. THE Generation_Service SHALL verify that a thread is not locked, removed, or archived before invoking the LLM for comment generation.
2. NOTE: This requirement is ALREADY IMPLEMENTED in `services/thread_liveness.py`. No new development is needed. This entry exists for traceability within the pipeline-v2 specification.

### Requirement 12: Avatar Warming Phases

**User Story:** As an operator, I want avatars to progress through defined warming phases with different engagement rules, so that new accounts build credibility naturally before brand promotion.

> **Implementation note:** FULLY EXISTS. `services/phase.py` → `PhasePolicy` + `PhaseEvaluator` implement all phase rules. Avatar model has `warming_phase` (int), `phase_changed_at`, `last_phase_evaluated_at`. PhaseEvaluator handles promotion/demotion based on age, karma, activity, survival rate. This entry exists for traceability.

#### Acceptance Criteria

1. THE System SHALL define three warming phases: Phase 1 (account age 0-59 days), Phase 2 (account age 60-120 days), Phase 3 (account age 121+ days).
2. WHILE an avatar is in Phase 1, THE System SHALL limit the avatar to a maximum of 3 comments per day (existing: `MAX_COMMENTS_PER_DAY_PHASE1 = 3`).
3. WHILE an avatar is in Phase 2, THE System SHALL limit the avatar to a maximum of 7 comments per day.
4. WHILE an avatar is in Phase 3, THE System SHALL apply the standard budget formula (R1) without phase-based caps.
5. WHILE an avatar is in Phase 1, THE System SHALL prohibit any brand mentions in generated comments (existing: blocks all `BrandMentionLevel` values).
6. WHILE an avatar is in Phase 2, THE System SHALL block explicit brand name and brand link mentions but allow inferred brand references with human review flag.
7. WHILE an avatar is in Phase 3, THE System SHALL allow brand mentions only when the brand ratio is below the configured threshold (R14).
8. THE System SHALL store the avatar's current phase in the `warming_phase` field, managed by `PhaseEvaluator` (not a simple computed property — promotion requires meeting karma + activity + survival criteria).

> **Note on Phase 2 daily limit:** Current code uses `MAX_COMMENTS_PER_DAY = 10` for Phase 2. This requirement changes it to 7 for additional safety margin. Requires updating the constant.

### Requirement 13: Rate Limits and Cooldowns

**User Story:** As an operator, I want minimum time intervals between consecutive comments by the same avatar, so that posting patterns appear natural and avoid detection.

> **Implementation note:** FULLY EXISTS. `safety.py` → `check_avatar_can_post()` enforces `MIN_MINUTES_BETWEEN_COMMENTS = 15` using `CommentDraft.created_at` of the most recent approved/posted draft. Enhancement needed: make configurable via System_Settings + add Valkey cache for fast lookup.

#### Acceptance Criteria

1. THE Cooldown_Service SHALL enforce a minimum of 15 minutes between consecutive comment postings by the same avatar (existing behavior).
2. WHEN an avatar's last comment was posted less than the configured interval ago, THE Generation_Service SHALL defer generation for that avatar until the cooldown expires.
3. THE cooldown interval SHALL be configurable via System_Settings with key `min_comment_interval_minutes` and default value "15".
4. THE Cooldown_Service SHALL use the `created_at` timestamp of the most recent "approved" or "posted" comment draft for the avatar to calculate elapsed time (existing behavior uses `created_at`, not `posted_at`).
5. THE Cooldown_Service SHALL store cooldown state in Valkey with a TTL equal to the cooldown interval for fast lookup (enhancement over current DB query).

### Requirement 14: Brand Ratio Tracking

**User Story:** As an operator, I want the system to track and enforce a maximum percentage of brand-mentioning comments per avatar, so that avatars maintain a natural engagement profile.

> **Implementation note:** Partially exists. `PhasePolicy.get_brand_ratio()` calculates text-based brand ratio over 7-day window. `safety.py` uses simpler `type == "professional"` ratio. This requirement standardizes on 30-day text-based analysis with Valkey caching.

#### Acceptance Criteria

1. THE Brand_Ratio_Tracker SHALL calculate the brand mention ratio as: `brand_comments_last_30_days / total_comments_last_30_days` for each avatar, using text-based brand mention classification (existing `PhasePolicy.classify_brand_mention()`).
2. WHEN an avatar's brand ratio exceeds the configured threshold, THE Generation_Service SHALL exclude brand-relevant threads for that avatar until the ratio drops below the threshold.
3. THE brand ratio threshold SHALL be configurable via System_Settings with key `max_brand_ratio_percent` and default value "30".
4. THE Brand_Ratio_Tracker SHALL classify a comment as "brand-mentioning" using `PhasePolicy.classify_brand_mention()` which checks for `brand_name` and `brand_domain` in comment text (existing behavior).
5. THE Admin_UI SHALL display the current brand ratio for each avatar on the avatar detail page (existing in `get_avatar_health()` but uses 7-day window — update to 30-day).
6. THE Brand_Ratio_Tracker SHALL recalculate ratios daily at 00:00 UTC and cache the result in Valkey with a 24-hour TTL.
7. IF an avatar has fewer than 5 total comments in the 30-day window, THEN THE Brand_Ratio_Tracker SHALL NOT enforce the ratio limit (insufficient sample size).

### Requirement 15: Avatar Strategy Document Generation

**User Story:** As an operator, I want the system to generate a strategy document for each avatar, so that comment generation is guided by explicit goals, tone, and subreddit priorities.

#### Acceptance Criteria

1. THE Strategy_Engine SHALL generate a Strategy_Document for each avatar containing: goals (3-5 measurable objectives), subreddit priorities (ranked list with engagement frequency), tone guidelines (formality level, humor usage, expertise signals), cadence rules (posting frequency per day/week), and hook inventory (list of "Hill I Die On" positions).
2. WHEN an operator triggers strategy generation for an avatar, THE Strategy_Engine SHALL use the avatar's persona profile, assigned subreddits, client brand brief, and warming phase as inputs to the LLM.
3. THE Generation_Service SHALL include the avatar's Strategy_Document in the LLM prompt context when generating comments.
4. THE Strategy_Document SHALL be stored in the database associated with the avatar and versioned with a `generated_at` timestamp.
5. THE Admin_UI SHALL provide a page to view, regenerate, and manually edit an avatar's Strategy_Document.
6. THE Strategy_Document SHALL include a forecast subsection with: projected karma gain in 7, 14, 30 days (based on current cadence and historical performance), expected phase transition date, predicted brand ratio trajectory, and estimated conversion metrics (if tracking is configured for the client). **Note:** Forecasts are trend-based heuristics (see Appendix B). Present as ranges in client reports.
7. THE forecast SHALL be recalculated each time the Strategy_Document is regenerated or when auto-correction (Requirement 19) triggers.

### Requirement 16: Mentor Analysis

**User Story:** As an operator, I want the system to analyze top commenters in target subreddits, so that avatar strategies can be informed by proven engagement patterns.

#### Acceptance Criteria

1. WHEN an operator triggers mentor analysis for a subreddit, THE Strategy_Engine SHALL fetch the top 50 comments from the specified mentor user in that subreddit via PRAW.
2. THE Strategy_Engine SHALL analyze the fetched comments using LLM to extract: average comment length, tone patterns, common opening styles, topic preferences, engagement triggers, and upvote-to-length ratio.
3. THE Strategy_Engine SHALL store the mentor analysis result as a `MentorAnalysis` record linked to the subreddit and mentor username.
4. THE Strategy_Engine SHALL use mentor analysis data as input when generating or updating an avatar's Strategy_Document for that subreddit.
5. THE Admin_UI SHALL provide a page to trigger mentor analysis, view results, and select mentors per subreddit.

### Requirement 17: Subreddit Analysis

**User Story:** As an operator, I want the system to analyze top comments in a subreddit when no specific mentor is identified, so that avatar strategy reflects the community's engagement culture.

#### Acceptance Criteria

1. WHEN an operator triggers subreddit analysis and no mentor is configured, THE Strategy_Engine SHALL fetch the top 50 comments from the subreddit's all-time top posts via PRAW.
2. THE Strategy_Engine SHALL analyze the fetched comments using LLM to extract: dominant tone, average comment length, humor frequency, expertise level expected, common formats (lists, stories, one-liners), and topics that drive engagement.
3. THE Strategy_Engine SHALL store the subreddit analysis result as a `SubredditAnalysis` record linked to the subreddit.
4. THE Strategy_Engine SHALL use subreddit analysis data as input when generating or updating an avatar's Strategy_Document for that subreddit.
5. THE Admin_UI SHALL provide a page to trigger subreddit analysis and view results.

### Requirement 18: Hill I Die On Tracking

**User Story:** As an operator, I want the system to track how often each avatar uses "Hill I Die On" hooks, so that hook usage stays within the target ratio and does not become repetitive.

#### Acceptance Criteria

1. THE Hill_Tracker SHALL record which hook (if any) was used in each generated comment by storing a `hill_hook_used` field on the `CommentDraft` record.
2. THE Hill_Tracker SHALL calculate the hook usage ratio as: `comments_with_hook_last_30_days / total_comments_last_30_days` for each avatar.
3. WHEN an avatar's hook usage ratio is below 25%, THE Generation_Service SHALL include a prompt instruction to prioritize using a hook in the next comment.
4. WHEN an avatar's hook usage ratio exceeds 35%, THE Generation_Service SHALL include a prompt instruction to avoid hooks in the next comment.
5. THE target hook usage ratio SHALL be configurable via System_Settings with keys `hill_hook_target_min_percent` (default "25") and `hill_hook_target_max_percent` (default "35").

### Requirement 19: Auto-Correction on Negative Performance

**User Story:** As an operator, I want the system to automatically adjust avatar strategy when comments consistently receive negative scores, so that poor-performing approaches are corrected without manual intervention.

> **Heuristic note:** "Score of 0 or below" refers to Reddit karma on posted comments. Reddit does not expose exact downvote counts; the system uses `score <= 0` as a proxy for negative reception. The 3-consecutive threshold is an initial calibration — may be adjusted.

#### Acceptance Criteria

1. WHEN an avatar receives a `reddit_score` of 0 or below on 3 consecutive posted comments in the same subreddit (where `reddit_score` is NOT NULL), THE Strategy_Engine SHALL trigger an automatic strategy review for that avatar in that subreddit.
2. THE auto-correction review SHALL analyze the 3 failing comments and the subreddit's successful comment patterns to identify the mismatch.
3. WHEN auto-correction is triggered, THE Strategy_Engine SHALL update the avatar's Strategy_Document with revised tone, approach, or topic guidance for the affected subreddit.
4. THE System SHALL log the auto-correction event with type "strategy_auto_corrected" including the avatar ID, subreddit, and summary of changes.
5. THE Admin_UI SHALL display auto-correction history on the avatar detail page.
6. THE auto-correction check SHALL only consider comments where `reddit_score` is NOT NULL and `last_karma_check_at` is NOT NULL (comments that have been verified against Reddit).

### Requirement 20: Cross-Avatar Coordination

**User Story:** As an operator, I want the system to distribute subreddit assignments across avatars of the same client, so that engagement is spread naturally and no single avatar dominates a community.

#### Acceptance Criteria

1. WHEN the Generation_Service selects threads for a client, THE System SHALL distribute threads across available avatars using a round-robin strategy weighted by each avatar's remaining daily budget.
2. THE cross-avatar coordinator SHALL ensure no single avatar receives more than 50% of a client's daily thread assignments in any single subreddit.
3. WHEN multiple avatars are eligible for the same thread, THE System SHALL prefer the avatar with the highest subreddit-specific karma for that subreddit.
4. THE cross-avatar coordinator SHALL respect all other constraints (phase gate, cooldown, brand ratio, saturation) when distributing threads.

### Requirement 21: Client Report Generation

**User Story:** As an operator, I want to generate periodic reports for clients showing avatar activity, performance metrics, and strategic recommendations, so that clients have visibility into campaign progress.

#### Acceptance Criteria

1. THE System SHALL generate a Client_Report containing: total comments posted, comments by subreddit, average engagement score, top-performing comments, brand mention ratio, phase progression status, and strategic recommendations.
2. WHEN an operator triggers report generation for a client, THE System SHALL compile data from the specified period (weekly or monthly) and format it as a structured document.
3. THE Client_Report SHALL include a comparison to the previous period showing trends in engagement, volume, and brand ratio.
4. THE Admin_UI SHALL provide a page to trigger report generation, select the reporting period, and view generated reports.
5. THE System SHALL store generated reports in the database with `client_id`, `period_start`, `period_end`, `generated_at`, and `report_content` fields.

### Requirement 22: Enhanced Scoring with Strategic Signals

**User Story:** As an operator, I want the scoring system to incorporate strategic bonuses and penalties, so that thread selection reflects both quality and strategic alignment.

> **Heuristic note:** The +20%, -30%, +15% weights below are initial calibration values. They will be adjusted based on observed engagement outcomes after 30 days of production data.

#### Acceptance Criteria

1. WHEN a thread aligns with an avatar's "Hill I Die On" hook, THE Scoring_Service SHALL apply a +20% bonus to the thread's composite score.
2. WHEN a thread's topic has been commented on by the same avatar in the last 7 days, THE Scoring_Service SHALL apply a -30% repeat penalty to the composite score.
3. WHEN a thread is in a subreddit where the avatar has historically high engagement, THE Scoring_Service SHALL apply a +15% historical performance bonus.
4. THE strategic scoring adjustments SHALL be applied after the base scoring (relevance + quality + strategic) and before the final ranking.
5. THE Scoring_Service SHALL log all applied bonuses and penalties as metadata on the thread score record.

### Requirement 23: Batch Scoring with Cost Control

**User Story:** As an operator, I want to score threads in configurable batches with cost visibility, so that I can control LLM spending on scoring operations.

#### Acceptance Criteria

1. THE Scoring_Service SHALL support batch scoring where multiple threads are evaluated in a single LLM call with a configurable batch size.
2. THE batch size SHALL be configurable via System_Settings with key `scoring_batch_size` and default value "10".
3. WHEN batch scoring is used, THE Scoring_Service SHALL format multiple threads into a single prompt and parse individual scores from the structured response.
4. THE Admin_UI SHALL display cumulative scoring cost for the current day on the Budget Dashboard.
5. FOR ALL valid batch scoring responses, parsing the response SHALL produce exactly one score per input thread (count preservation property).

### Requirement 24: Unified Client Report (Admin Data + Strategy + Forecast)

**User Story:** As an operator, I want to generate a client-facing report that combines raw avatar data, AI-generated strategy, and performance forecast, so that clients receive a complete picture without accessing the admin panel.

#### Acceptance Criteria

1. THE Client_Report SHALL include three mandatory sections derived from admin data: Executive Summary (goals vs actual — karma, comments, conversions), Activity (comments posted, karma gained, top subreddits), and Avatar Health (shadowban status, warming phase, account age).
2. THE Client_Report SHALL include three mandatory sections from the Strategy_Engine: Strategy (target subreddits with priorities 1-10, tone calibration, hill usage plan), Weekly Tactics (comment cadence by week, professional vs hobby split), and Ready-to-Use Templates (example comments for each target subreddit).
3. THE Client_Report SHALL include a Forecast section with: projected karma in 7, 14, 30 days; expected phase transition date; and estimated site clicks or conversions (if tracking is configured).
4. THE Client_Report SHALL include a Questions for Client section with 3-5 specific questions to gather feedback for strategy correction.
5. THE Client_Report SHALL be exportable in three formats: Markdown (`.md`) for email and documentation, JSON (`.json`) for API integration, and PDF (`.pdf`) for client delivery.
6. WHEN generating a Client_Report, THE System SHALL use the avatar's current Strategy_Document (Requirement 15) and historical performance data from activity events.
7. THE Admin_UI SHALL provide a "Generate Client Report" button on the client detail page that triggers report generation and returns a download link.

### Requirement 25: Strategy as Pipeline Input

**User Story:** As an operator, I want the generation pipeline to use the avatar's strategy document as a primary input, so that comments are consistently aligned with strategic goals.

#### Acceptance Criteria

1. WHEN the Generation_Service creates a comment draft, THE LLM prompt SHALL include the following sections from the avatar's Strategy_Document: tone guidelines, cadence rules, hook inventory (Hill I Die On), and subreddit-specific priorities.
2. WHEN the Scoring_Service evaluates threads, THE System SHALL apply strategic bonuses and penalties from Requirement 22 ONLY if the avatar has a valid Strategy_Document with a `generated_at` timestamp less than 30 days old.
3. THE Admin_UI Pipeline tab SHALL display the current Strategy_Document summary (goals, top priorities, active hooks) as a reference panel visible during draft review.
4. WHEN an avatar has no Strategy_Document, THE System SHALL display a warning in the Admin_UI and SHALL generate comments using the base persona profile without strategic enrichment.

## Success Metrics

| Metric | Target | How Measured | Type |
|--------|--------|--------------|------|
| Strategy generation success rate | 95% | Successful LLM responses / attempts | Deterministic |
| Report generation time | < 5 seconds | API response time | Deterministic |
| Forecast accuracy (karma) | ±25% | Actual vs predicted after 30 days | Heuristic |
| Strategy usage in generation | 100% | Percentage of comments using strategy context | Deterministic |
| Auto-correction effectiveness | 70% | Score improvement after correction | Heuristic |
| Pre-generation safety catch rate | 100% | Budget/safety violations caught before LLM call | Deterministic |
| Brand ratio compliance | 100% | Avatars exceeding threshold blocked from brand threads | Deterministic |
| Cross-avatar dedup accuracy | 100% | Zero duplicate client presence in same thread | Deterministic |

> **Note:** Metrics marked "Heuristic" are operational estimates. They depend on Reddit engagement data which is inherently noisy. Targets represent aspirational calibration goals, not SLA guarantees.

---

## Appendix A: Current vs Future Capabilities

| Component | MVP (Phase 1 — Now) | Growth (Phase 2 — 3-6 mo) | Scale (Phase 3 — 6-12 mo) |
|-----------|---------------------|---------------------------|---------------------------|
| Phase Model | 3 phases (1, 2, 3) based on account age | Same + karma thresholds | 5 phases (0-4) with trust engine |
| Budget Engine | Formula-based daily limits | + per-subreddit limits | Dynamic limits from ML |
| Scoring | Base 3-axis + strategic bonuses | + batch scoring | + historical learning |
| Strategy Document | Manual trigger, LLM-generated | + auto-refresh weekly | + A/B testing |
| Mentor Analysis | Manual trigger, top 50 comments | + auto-discovery | + cross-sub patterns |
| Memory Layer | Thread dedup only | + user context (90-day TTL) | + topic + argument memory |
| Reporting | Markdown export | + JSON API | + PDF + scheduled delivery |
| Cost Intelligence | Basic token tracking | + per-client ROI | + predictive budgeting |
| Auto-Correction | 3 failures → strategy review | + gradual tone adjustment | + subreddit-specific models |
| Cross-Avatar Coordination | Round-robin with budget weight | + karma-weighted routing | + behavioral diversity scoring |

### What Ships in MVP (Requirements 1-14)

These are the **operational guardrails** — hard gates that prevent waste and reduce risk:

- R1: Budget Dashboard
- R2: Cross-Avatar Deduplication
- R3: Thread Freshness Filter
- R4: Scoring Cost Preview
- R5: Phase-Aware Filtering
- R6: Subreddit Saturation Guard
- R7: Pre-Generation Safety Validation
- R8: Scrape Freshness Gate
- R9: Today's Activity Summary
- R10: Inline Draft Editing
- R11: Thread Liveness Check (already built)
- R12: Avatar Warming Phases
- R13: Rate Limits and Cooldowns
- R14: Brand Ratio Tracking

### What Ships in Growth Phase (Requirements 15-21)

These are the **strategic engine** — intelligence that improves output quality over time:

- R15: Avatar Strategy Document Generation
- R16: Mentor Analysis
- R17: Subreddit Analysis
- R18: Hill I Die On Tracking
- R19: Auto-Correction on Negative Performance
- R20: Cross-Avatar Coordination
- R21: Client Report Generation

### What Ships in Scale Phase (Requirements 22-25)

These are **enhanced intelligence** — refinements that compound with data:

- R22: Enhanced Scoring with Strategic Signals
- R23: Batch Scoring with Cost Control
- R24: Unified Client Report (Admin + Strategy + Forecast)
- R25: Strategy as Pipeline Input

---

## Appendix B: Heuristic Definitions

All metrics below are **operational heuristics** — estimates based on available Reddit data. They are not ground-truth measurements and are subject to ongoing calibration.

| Metric | Type | Data Source | Estimated Accuracy | Notes |
|--------|------|-------------|-------------------|-------|
| Daily budget limit | Formula | account_age + karma + CQS | Deterministic formula | Thresholds calibrated empirically |
| Brand ratio | Calculation | keyword matching in comment text | ±5% (depends on keyword coverage) | False positives possible with common words |
| Hook usage ratio | Calculation | `hill_hook_used` field on drafts | Exact (binary flag) | Requires LLM to self-report hook usage |
| Forecast: karma gain | Trend projection | historical karma delta / time | ±25-40% | Highly dependent on subreddit activity |
| Forecast: phase transition | Date calculation | account_age_days + phase thresholds | Exact (deterministic) | Based on fixed day thresholds |
| Scoring: strategic bonus | Heuristic weight | keyword overlap + history | Relative ranking only | Not an absolute quality measure |
| Auto-correction trigger | Threshold | consecutive low-score comments | Binary (fires or not) | "Score" itself is LLM-assigned |
| Subreddit saturation | Counter | approved/posted drafts per day | Exact count | Resets at UTC midnight |

### How to Read Metrics in Client Reports

For client-facing reports, use **ranges and qualitative labels** instead of precise numbers:

| Internal Metric | Client-Facing Presentation |
|----------------|---------------------------|
| `trust_score: 0.73` | Trust level: High |
| `karma_forecast: +450 in 30d` | Karma trajectory: Strong positive |
| `brand_ratio: 0.22` | Brand presence: Within healthy range |
| `hook_usage: 0.31` | Value proposition frequency: On target |
| `engagement_score: 7.2` | Engagement quality: Above average |

---

## Appendix C: Privacy Constraints (Memory & Data)

### Data Handling Principles

- **Only public Reddit data** — No external data sources, no private messages, no user profiles beyond public post/comment history
- **No personal profiling** — System stores operational context (thread IDs, subreddit names, karma counts), not user behavioral profiles
- **No cross-user correlation** — Each avatar's memory is isolated; no tracking of Reddit users across threads or subreddits
- **TTL limits** — Thread data retained for 90 days rolling window; activity logs retained indefinitely for audit
- **No PII storage** — Reddit usernames only (public data); no emails, real names, or contact information stored

### What the System Stores

| Data Type | Retention | Purpose | Legal Basis |
|-----------|-----------|---------|-------------|
| Thread title + body | 90 days | Scoring + generation context | Legitimate interest (public data) |
| Thread metadata (score, age, sub) | 90 days | Freshness + scoring | Legitimate interest |
| Comment drafts (generated text) | Indefinite | Audit trail + learning | Contractual obligation |
| Avatar activity events | Indefinite | Transparency + reporting | Contractual obligation |
| Mentor comment samples | 30 days | Strategy generation | Legitimate interest (public data) |
| Subreddit analysis results | 90 days | Strategy generation | Legitimate interest (public data) |

### What the System Does NOT Store

- Reddit user passwords or OAuth tokens of non-avatar accounts
- Private messages or chat content
- User IP addresses or device fingerprints
- Cross-platform identity links
- Behavioral profiles of Reddit users (other than managed avatars)

> **Legal note:** All stored data is publicly available on Reddit. The system does not create profiles of non-avatar Reddit users or track individuals across platforms. Avatar credential storage uses encryption at rest.

---

## Appendix D: Operational Cost Estimation

### Per-Avatar Daily Cost (at current LLM pricing)

| Operation | Model | Calls/avatar/day | Cost/call | Cost/day |
|-----------|-------|-----------------|-----------|----------|
| Scoring (batch of 10) | Gemini Flash | 2-5 | $0.003 | $0.006-0.015 |
| Persona Selection | Claude Sonnet | 3-5 | $0.020 | $0.06-0.10 |
| Comment Generation | Claude Sonnet | 3-5 | $0.039 | $0.12-0.20 |
| Comment Editing | Claude Haiku | 3-5 | $0.003 | $0.009-0.015 |
| Hobby Comments | Gemini Flash | 3-5 | $0.0003 | $0.001-0.002 |
| Strategy refresh | Claude Sonnet | 0.14 (1/week) | $0.10 | $0.014 |
| **Total per avatar** | | | | **$0.21-0.35/day** |

### Monthly Cost at Scale

| Avatars | LLM cost/month | AWS infra/month | Total/month | Revenue (est.) | Margin |
|---------|---------------|-----------------|-------------|----------------|--------|
| 15 (3 clients) | $95-160 | $27 | $122-187 | $1,500 | 87-92% |
| 50 (10 clients) | $315-525 | $27 | $342-552 | $5,000 | 89-93% |
| 250 (50 clients) | $1,575-2,625 | $54 | $1,629-2,679 | $25,000 | 89-93% |

> **Note:** LLM pricing changes frequently. These estimates use May 2026 pricing. Claude Haiku for editing (instead of Sonnet) saves ~$70/mo at 10 clients.

---

## Appendix E: Terminology — Internal vs Client-Facing

For **internal technical documents** (this FRD, code comments, architecture docs), use precise technical terms. For **client reports, emails, and external communications**, use the safe alternatives below.

| Internal Term (this doc) | Client-Facing Term | Why |
|--------------------------|-------------------|-----|
| Phase Gate | Growth Phase | "Gate" implies restriction/control |
| Saturation Guard | Engagement pacing | "Saturation" implies flooding |
| Kill switch / Emergency stop | Service pause | Less alarming |
| Hook frequency | Value proposition frequency | "Hook" sounds manipulative |
| Brand ratio tracking | Brand presence balance | "Tracking" sounds surveillance-like |
| Cooldown | Natural pacing | "Cooldown" implies overheating |
| Budget exhausted | Daily capacity reached | Less negative |
| Auto-correction | Strategy optimization | "Correction" implies error |
| Deduplication | Presence coordination | Technical term → business term |
| Scoring pipeline | Content opportunity analysis | Less mechanical |
| Memory layer | Context awareness | "Memory" raises privacy concerns |

### Terms NEVER Used (Legal Compliance)

These terms must not appear in any written communication — internal or external:

- ❌ "fake accounts", "bot", "bots", "bot ring"
- ❌ "automating Reddit", "automated posting"
- ❌ "evading detection", "bypassing"
- ❌ "violating ToS", "against Reddit rules"

Use instead: "community engagement management", "persona-driven content strategy", "managed brand presence", "avatar", "Digital Assets"

</content>
