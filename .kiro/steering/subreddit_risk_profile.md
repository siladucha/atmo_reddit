---
inclusion: fileMatch
fileMatchPattern: "**/risk_*,**/fitness_gate*,**/moderation_profiler*,**/rule_extractor*,**/subreddit_risk_profile*,**/subreddit_daily_stats*"
---

# Subreddit Risk Profile — Architecture Reference

## System Overview

The Subreddit Risk Profile system provides a data-driven safety layer between Smart Scoring and Comment Generation. It reduces comment removals by extracting subreddit rules, learning moderation patterns, and gating unsafe avatar-subreddit pairings before generation.

## Weekly Pipeline (Sunday, Asia/Jerusalem)

04:30 — Emotional profiles refresh
05:00 — Rule extraction (PRAW sidebar/wiki to Gemini Flash to Pydantic)
05:15 — Moderation profiling (30-day deletion aggregation)
05:30 — Risk score computation (weighted formula + high_risk flags)

All three tasks share a distributed lock (risk_profile_batch, TTL=1800s). Only one batch runs at a time.

## Service Architecture

| Service | Input | Output | Key Logic |
|---------|-------|--------|-----------|
| rule_extractor.py | PRAW sidebar text | ExtractionResult (max 20 rules) | Gemini Flash, Pydantic validation, retry once, circuit breaker at 50% |
| moderation_profiler.py | CommentDraft deletion data (30d) | ModerationProfile dataclass | Hourly distributions, dangerous hours (>2x avg), patterns (>30%) |
| risk_scorer.py | SubredditRiskProfile fields | Integer 0-100 | Weighted: removal 40%, aggressiveness 25%, rules 20%, trend 15% |
| fitness_gate.py | Avatar + subreddit_name | FitnessResult (pass/block) | 6 sequential checks, fail-open if no profile |

## Fitness Gate Check Order

1. Profile exists? — fail-open if missing (allow generation)
2. min_karma — avatar SubredditKarma.comment_karma vs extracted threshold
3. min_account_age — avatar.reddit_account_created vs threshold (skip if NULL)
4. posting_frequency_limit — posted count in window vs limit
5. Extreme aggressiveness + <50 karma — block
6. Dangerous hours + <200 karma — block

## Fitness Score Formula (0-100)

score = compliance(40%) + karma_headroom(30%) + age_headroom(30%)

- Compliance: passed_rules / total_checkable_rules x 100
- Karma headroom: (avatar_karma - min_karma) / 1000 x 100, clamped 0-100
- Age headroom: (account_age_days - min_age) / 365 x 100, clamped 0-100

## Risk Score Formula (0-100)

score = removal_rate_score x 0.40 + aggressiveness_score x 0.25 + rule_strictness_score x 0.20 + trend_score x 0.15

Sub-scores:
- Removal rate: linear 0% = 0, 100% = 100
- Aggressiveness: low=10, medium=40, high=70, extreme=100
- Rule strictness: min(rule_count x 12, 100)
- Trend: linear regression slope of last 4 weeks, mapped to 0-100 (positive = higher risk)

## Key Models

| Model | Table | Key Fields |
|-------|-------|------------|
| SubredditRiskProfile | subreddit_risk_profiles | risk_score (CHECK 0-100), extracted_rules JSONB, moderation_profile JSONB, dangerous_hours JSONB, confidence_level |
| SubredditDailyStats | subreddit_daily_stats | subreddit_id + date (UNIQUE), comments_posted, comments_survived, removal_rate |
| AvatarSubredditCompatibility | extended | fitness_score (Integer, nullable), fitness_computed_at |
| Subreddit | extended | is_high_risk (Boolean) |

## Pipeline Integration

In generate_comments() after Smart Scoring selects engage threads:
- Check fitness_gate_enabled system setting
- Evaluate each thread with fitness gate
- Block unsafe pairings, decrement budget
- Log fitness_block and fitness_zero_eligible activity events

## System Setting

| Key | Default | Effect |
|-----|---------|--------|
| fitness_gate_enabled | true | When false, gate skipped entirely |

## UI Pages

- Admin: /admin/subreddits/{id}/risk-profile — full page with HTMX lazy-load
- Portal: /portal/subreddits/{id}/risk-profile — client-scoped (avatars + daily stats filtered)
- Badges: risk score shown on all subreddit list pages (color-coded: green/yellow/orange/red)

## Correctness Properties

1. Fail-open: missing profile always allows (never blocks pipeline)
2. Idempotent batch: running twice produces same result
3. Risk score bounded: CHECK constraint enforces 0-100
4. History append-only: FIFO capped at 12 weeks
5. Daily stats unique: UNIQUE(subreddit_id, date) + upsert
6. Budget consumption: blocked thread = consumed (decrements budget, no re-evaluation same day)
7. Lock safety: TTL 1800s >> max batch duration (~5 min)
