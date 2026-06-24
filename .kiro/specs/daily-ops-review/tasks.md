# Implementation Plan:

## Overview

12 tasks implementing the Daily Operations Review system. Tasks 1-4 are backend (models, services). Tasks 5 is the route layer. Tasks 6-9 are templates. Tasks 10-12 are integration and polish.

Estimated total effort: 3-4 days.

## Tasks

- [x] 1. Create database models (DailyReviewSession, IntelligenceReport, ReviewDecision, ReviewHypothesis) and Alembic migration `dor01_daily_ops_review_tables`. Register models. Verify `alembic upgrade head` succeeds.
- [x] 2. Create `app/services/daily_review/cost_governor.py` — CostBudget dataclass (remaining_usd, is_warning, is_exhausted, can_spend, record_spend), `get_today_budget(db)` querying AIUsageLog for agent_ops, `get_weekly_cost_summary(db)`. Add system setting `agent_daily_budget_usd` default "1.00".
- [x] 3. Create `app/services/daily_review/signal_collector.py` — dataclasses (HealthSignal, HealthSnapshot, ChangeSignal, TrendItem). Implement `collect_health_snapshot(db)` querying ActivityEvent, AIUsageLog, ScrapeLog, PostingEvent, Avatar, CommentDraft with 7d averages and stddev. Implement `collect_changes(db, since)` comparing 24h vs previous 24h. Implement `collect_trends(db)` from PerformanceMetric 7d/30d vectors. Handle data gaps gracefully.
- [ ] 4. Create `app/services/daily_review/review_engine.py` — LLM-enhanced analysis gated by cost_governor. Functions: `enhance_health_summary` (Gemini Flash), `classify_trends` (Gemini Flash batch), `generate_hypotheses` (Claude Haiku), `generate_forecasts` (Gemini Flash batch all 7 domains), `generate_narrative` (Claude Haiku ≤500 words). Each function checks budget before calling, falls back to rule-based/template if exhausted.
- [x] 5. Create `app/routes/daily_review.py` — all endpoints: GET / (main page), POST /start, GET /section/{name}, POST /section/{name}/save, POST /section/{name}/complete, POST /complete, POST /decisions, PATCH /decisions/{id}, GET /decisions/open, POST /hypotheses, PATCH /hypotheses/{id}, GET /budget, GET /history. All protected by require_platform_admin. Register router in main.py.
- [x] 6. Create `app/templates/admin_daily_review.html` (extends admin_base.html) with two-column layout — left sidebar (section list with status badges, elapsed timer JS, budget bar) and main content area. Add "Daily Review" link to admin navigation in admin_base.html sidebar.
- [x] 7. Create section partials: `session_start.html` (hours since last, accuracy badge, Start button), `section_health.html` (signals table with delta indicators, verdict badge, "would users notice" answer), `section_changes.html` (Signal/Evidence/Impact/Confidence table, manual observation form), `budget_indicator.html` (progress bar + spend text).
- [ ] 8. Create section partials: `section_trends.html` (3-tab expected/unexpected/weak with reclassify dropdowns, recurring badge for 3+ days), `section_hypotheses.html` (hypothesis cards with observation, causes textarea, probability, action dropdown, link-to-signals checkboxes, history from last 3 sessions).
- [ ] 9. Create section partials: `section_forecast.html` (7-row table with editable overrides, yesterday accuracy row, "what could surprise us" textarea), `section_decisions.html` (candidates list, decision form with type/description/owner/deadline, max 3 counter, open decisions from 7d with status controls), `report_card.html`, `quick_review.html`.
- [ ] 10. Implement forecast accuracy evaluation: `evaluate_yesterday_forecast(db)` comparing yesterday's report forecast to actual metrics per domain. Define actual_state rules. Update report's forecast_accuracy JSONB. Compute rolling 7d/30d accuracy. Display on session_start and forecast section.
- [ ] 11. Implement auto-save (hx-trigger keyup delay:2s), session persistence (restore on reload), session abandonment (mark old in_progress as abandoned), stale data banner (3h+ sessions).
- [ ] 12. End-to-end integration: wire complete flow, verify narrative generation (LLM + template fallback), verify budget enforcement ($0.01 cap triggers offline mode), verify decision/hypothesis carry-over across sessions, Quick Review mode activation, responsive dark-theme styling.

## Task Dependency Graph

```json
{
  "waves": [
    {"tasks": [1]},
    {"tasks": [2, 3]},
    {"tasks": [4]},
    {"tasks": [5]},
    {"tasks": [6, 7, 8, 9, 10]},
    {"tasks": [11]},
    {"tasks": [12]}
  ]
}
```

## Notes

- All LLM calls use LiteLLM (existing `app/services/ai.py` pattern) with model selection: `gemini/gemini-2.0-flash` for classification/scoring, `anthropic/claude-3-5-haiku-20241022` for generation/narrative
- AIUsageLog records for agent ops use operation values: `agent_health_summary`, `agent_trend_classification`, `agent_hypothesis_generation`, `agent_forecast`, `agent_narrative`
- No new Celery Beat tasks — all analysis is synchronous during the HTTP request (signal collection < 10s, LLM calls < 5s each)
- Session auto-save uses existing HTMX patterns from the platform (see onboarding wizard for reference)
- Budget indicator updates via `hx-trigger="every 30s"` polling on the sidebar partial
