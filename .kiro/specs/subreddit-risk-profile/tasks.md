# Implementation Plan: Subreddit Risk Profile

## Overview
Implement the Subreddit Risk Profile system: models, services (rule extraction, moderation profiling, risk scoring, fitness gate), Celery tasks, pipeline integration, and UI pages for admin and portal.

## Tasks

- [x] 1. Create SubredditRiskProfile and SubredditDailyStats models + Alembic migration
  - **Requirements**: 6.1, 6.2, 6.3, 6.5
  - **Files**: `app/models/subreddit_risk_profile.py` (create), `app/models/subreddit_daily_stats.py` (create), `app/models/subreddit.py` (add is_high_risk), Alembic migration (generate)
  - **Details**: SubredditRiskProfile 1:1 with Subreddit (CASCADE), all JSONB fields, CHECK on risk_score 0-100. SubredditDailyStats with UNIQUE(subreddit_id, date). Add is_high_risk Boolean to Subreddit. Register in models __init__.

- [x] 2. Add fitness_score field to AvatarSubredditCompatibility model
  - **Requirements**: 6.4
  - **Files**: `app/models/avatar_subreddit_compatibility.py` (modify), Alembic migration (generate)
  - **Details**: Add fitness_score Integer(0-100, nullable) and fitness_computed_at DateTime(nullable).

- [x] 3. Implement rule_extractor service
  - **Requirements**: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8
  - **Files**: `app/services/rule_extractor.py` (create)
  - **Details**: ExtractedRule + ExtractionResult Pydantic models. extract_subreddit_rules() fetches PRAW sidebar/wiki, truncates to 4000 chars, calls Gemini Flash, validates with Pydantic, retries once. refresh_all_subreddit_rules() iterates with 3s delay, circuit breaker at 50% failure, preserves previous rules.

- [x] 4. Implement moderation_profiler service
  - **Requirements**: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8
  - **Files**: `app/services/moderation_profiler.py` (create)
  - **Details**: ModerationProfile dataclass. compute_moderation_profile() aggregates KarmaSnapshot+CommentDraft deletion data (30-day window), classifies aggressiveness, finds dangerous hours (>2x avg), identifies patterns (>30%). compute_daily_stats() upserts SubredditDailyStats via GROUP BY.

- [x] 5. Implement risk_scorer service
  - **Requirements**: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8
  - **Files**: `app/services/risk_scorer.py` (create)
  - **Details**: compute_risk_score() with weighted formula (removal 40%, aggressiveness 25%, rules 20%, trend 15%). refresh_all_risk_scores() iterates profiles, appends history (cap 12 weeks FIFO), sets/clears is_high_risk, emits spike events.

- [x] 6. Implement fitness_gate service
  - **Requirements**: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 8.5
  - **Files**: `app/services/fitness_gate.py` (create)
  - **Details**: FitnessResult dataclass. evaluate_fitness() checks in order: fail-open if no profile, min_karma, min_account_age, frequency_limit, extreme aggressiveness+<50 karma, dangerous hours+<200 karma. Computes fitness_score (40% compliance + 30% karma headroom + 30% age headroom). batch_evaluate_fitness() preloads data in bulk.

- [x] 7. Create risk_profile Celery tasks and register in Beat schedule
  - **Requirements**: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7
  - **Files**: `app/tasks/risk_profile.py` (create), `app/tasks/worker.py` (modify)
  - **Details**: Three tasks: extract_subreddit_rules_batch (05:00), compute_moderation_profiles_batch (05:15), compute_risk_scores_batch (05:30). Distributed lock key="risk_profile_batch" TTL=1800s. Add to worker includes + beat_schedule.

- [x] 8. Integrate Fitness Gate into generate_comments pipeline
  - **Requirements**: 8.1, 8.2, 8.3, 8.4, 8.6
  - **Files**: `app/tasks/ai_pipeline.py` (modify), `app/services/settings.py` (modify)
  - **Details**: In generate_comments(), after engage_threads query and before generation loop: check fitness_gate_enabled setting, evaluate each thread, filter blocked ones, log fitness_block/fitness_zero_eligible events, decrement budget for blocked threads.

- [x] 9. Create admin risk profile route and templates
  - **Requirements**: 5.1, 5.2, 5.3, 5.4, 5.6, 5.7, 5.8, 5.10, 5.11, 5.12
  - **Files**: `app/routes/admin_risk_profile.py` (create), `app/templates/admin_subreddit_risk_profile.html` (create), 7 partials in `app/templates/partials/risk_profile_*.html` (create), `app/main.py` (modify)
  - **Details**: Full page extends admin_base.html. HTMX lazy-load for daily-history and trend-chart. Color-coded risk badge. Rules list, insights, recommendations, avatar fitness table. Informational messages for insufficient data.

- [x] 10. Create portal risk profile route and client-scoped template
  - **Requirements**: 5.1, 5.5, 5.9, 5.10, 5.11, 5.12
  - **Files**: `app/routes/portal_risk_profile.py` (create), `app/templates/client/subreddit_risk_profile.html` (create), `app/main.py` (modify)
  - **Details**: Client-scoped page extends client_base.html. Reuses admin partials but scopes daily history and avatar fitness to user's client only. Requires require_client_access permission.

- [x] 11. Add navigation links to risk profile from subreddit list pages
  - **Requirements**: 5.1
  - **Files**: Admin subreddit templates (modify), `app/templates/client/subreddits.html` (modify), `app/templates/admin_client_detail.html` (modify)
  - **Details**: Add "Risk Profile" link/button and inline risk score badge (color-coded) on subreddit list rows in admin and portal views.

## Task Dependency Graph

```json
{
  "waves": [
    {"tasks": [1, 2]},
    {"tasks": [3, 4, 5, 6]},
    {"tasks": [7, 9, 10]},
    {"tasks": [8, 11]}
  ]
}
```

## Notes
- Tasks 1-2 must complete first (DB schema)
- Tasks 3-6 can be done in parallel after models exist
- Task 7 depends on tasks 3-5 (services it orchestrates)
- Task 8 depends on tasks 6-7 (fitness gate + task registration)
- Tasks 9-10 can start after task 1 (only need models for queries)
- Task 11 is last (needs routes from 9-10 to link to)
