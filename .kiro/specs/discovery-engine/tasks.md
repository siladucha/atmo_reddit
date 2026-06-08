# Implementation Plan: Discovery Engine

## Overview

Implementation of the Discovery Engine — a pre-engagement layer that analyzes client business context, forms hypotheses about Reddit ecosystem relevance, researches Reddit for evidence, and produces a Visibility Report as a sales artifact. Covers data models, core services (entity extraction, hypothesis formation, confidence scoring, Reddit research), report generation, strategy handoff, admin UI with HTMX flow, cost tracking, and tests.

## Tasks

- [x] 1. Create Discovery Models
  - [x] 1.1. Create `app/models/discovery_session.py` — DiscoverySession model (UUID PK, client_id FK nullable, operator_user_id FK, client_brief, prospect_name, status enum, current_iteration, timestamps, abandon_reason, session_metadata JSONB, total_ai_cost_usd)
  - [x] 1.2. Create `app/models/discovery_entity.py` — DiscoveryEntity model (UUID PK, session_id FK CASCADE, name, category enum, source enum, created_at)
  - [x] 1.3. Create `app/models/discovery_hypothesis.py` — DiscoveryHypothesis model (UUID PK, session_id FK CASCADE, iteration_number, statement, category enum, confidence_score, confidence_delta, status enum, classification, provenance JSONB, reddit_signals JSONB, rejection_reason, timestamps)
  - [x] 1.4. Create `app/models/visibility_report.py` — VisibilityReport model (UUID PK, session_id FK CASCADE, content JSONB, generated_at, operator_notes, report_version, model_used, generation_cost_usd)
  - [x] 1.5. Register all models in `app/models/__init__.py`
- [x] 2. Alembic Migration
  - [x] 2.1. Create migration: `discovery_sessions` table with indexes on client_id and operator_user_id
  - [x] 2.2. Create migration: `discovery_entities` table with index on session_id
  - [x] 2.3. Create migration: `discovery_hypotheses` table with unique constraint (session_id, iteration_number, statement) and composite index (session_id, status)
  - [x] 2.4. Create migration: `visibility_reports` table with index on session_id
  - [x] 2.5. Add `discovery_session_id` nullable UUID FK column to `strategy_documents` table
  - [x] 2.6. Verify migration runs cleanly up and down
- [x] 3. Pydantic Schemas
  - [x] 3.1. Create `app/schemas/discovery.py` with EntityExtractionOutput, HypothesisFormationOutput, RedditSignalOutput, VisibilityReportContent, SessionCreateRequest, and HypothesisDecision validation schemas
- [x] 4. Entity Extractor Service
  - [x] 4.1. Create `app/services/discovery/__init__.py`
  - [x] 4.2. Create `app/services/discovery/entity_extractor.py` with `extract_entities(client_brief, db, session_id)` that calls Gemini Flash via `call_llm_json()`, builds extraction prompt for business analyst role, handles LLM response parsing + validation (3-20 entities, correct categories), handles edge case <3 entities, logs AI usage with sub-type "entity_extraction", stores entities in DB and returns list
- [x] 5. Hypothesis Engine Service
  - [x] 5.1. Create `app/services/discovery/hypothesis_engine.py` with `form_hypotheses(entities, session, prior_hypotheses, rejection_context)` that calls Gemini Flash, builds hypothesis prompt with entities/confirmed directions/rejection reasons/exclusion list, validates output (3-7 hypotheses with quantifiable Reddit metric and correct category), handles retry if <3 returned, handles dedup, assigns initial confidence_score=50, stores provenance JSONB, logs AI usage with sub-type "hypothesis_formation", returns stored hypothesis records
- [x] 6. Confidence Scorer Service
  - [x] 6.1. Create `app/services/discovery/confidence_scorer.py` with `score_hypothesis(hypothesis, signals)` implementing pure Python scoring rules: ≥20 posts + ≥10 avg engagement → +10 to +30, <5 posts OR <3 avg engagement → -10 to -30, both fail → score=15 with no_signal. Generate confidence_reasoning text, calculate confidence_delta, implement No-Signal classification (search_too_narrow → adjacent terms, topic_absent → alternative platforms)
- [x] 7. Reddit Researcher Service
  - [x] 7.1. Create `app/services/discovery/reddit_researcher.py` with `research_hypothesis(hypothesis, entities)` using PRAW: extract search terms from hypothesis + entity names, subreddit search (limit=10), for each subreddit get subscriber count + recent posts (.hot limit=25) + 30-day volume estimate + avg engagement + topic relevance score, reuse rate limiting, broader search for no-signal, return structured reddit_signals dict, handle Reddit API errors gracefully
- [x] 8. Celery Research Task
  - [x] 8.1. Create `app/tasks/discovery.py` with `research_hypotheses_task(session_id, hypothesis_ids)` Celery task: process hypotheses sequentially with rate limiting, update session_metadata research_progress, apply confidence scoring after each, 120s soft timeout, mark remaining as research_failed on timeout, register in worker.py, set retry policy (bind=True, max_retries=2, default_retry_delay=30)
- [x] 9. Report Generator Service
  - [x] 9.1. Create `app/services/discovery/report_generator.py` with `generate_visibility_report(session)` using Claude Sonnet via `call_llm()`: build report prompt with confirmed hypotheses + reddit_signals + entities + client_brief, request all sections (exec summary, demand, communities, activity, entry points, competitive landscape, outcomes, risks), parse into structured JSONB, 60s timeout, log AI usage with sub-type "report_generation", store report with version number, update session status to completed
- [x] 10. Strategy Handoff Service
  - [x] 10.1. Create `app/services/discovery/strategy_handoff.py` with `prepare_handoff_context(session)` and `execute_handoff(session, db)`: create Client if no client_id, link session to client, pre-populate subreddit suggestions, set discovery_session_id on StrategyDocument, log discovery_handoff ActivityEvent
  - [x] 10.2. Modify `strategy_engine.py` → `generate_strategy()` to accept optional `discovery_context` dict parameter and inject into prompt when present; add "Based on Discovery" section to `_render_strategy_md`
- [x] 11. Session Manager Service
  - [x] 11.1. Create `app/services/discovery/session_manager.py` with create_session, get_session (eager-loaded), list_sessions (paginated, sorted desc), abandon_session (state validation), advance_iteration (max 5 validation), update_ai_cost (atomic increment)
- [x] 12. Route Setup
  - [x] 12.1. Create `app/routes/discovery.py` — FastAPI router with prefix `/admin/discovery`, register in `app/main.py`, apply `require_platform_admin` dependency
  - [x] 12.2. Implement GET /admin/discovery (session list, paginated 25/page), GET /admin/discovery/new (form), POST /admin/discovery/new (create + entity extraction → entity review partial), GET /admin/discovery/{session_id} (active session page)
- [x] 13. Iteration Flow Routes
  - [x] 13.1. Implement POST /admin/discovery/{id}/entities (confirm/edit entities → hypothesis formation → hypotheses partial)
  - [x] 13.2. Implement POST /admin/discovery/{id}/research (trigger Celery task → progress partial) and GET /admin/discovery/{id}/progress (HTMX poll endpoint)
  - [x] 13.3. Implement POST /admin/discovery/{id}/decide (confirm/reject decisions → next iteration or report prompt)
  - [x] 13.4. Implement POST /admin/discovery/{id}/report (generate report → report partial), POST /admin/discovery/{id}/report/edit (save notes), GET /admin/discovery/{id}/report/export (branded HTML)
  - [x] 13.5. Implement POST /admin/discovery/{id}/handoff (strategy handoff) and POST /admin/discovery/{id}/abandon (mark abandoned)
- [x] 14. Templates — Pages
  - [x] 14.1. Create `templates/admin_discovery.html` (session list with "New Discovery" button, extends admin_base.html)
  - [x] 14.2. Create `templates/admin_discovery_session.html` (active session container with progress bar, sidebar info, #discovery-content swap target)
  - [x] 14.3. Add "Discovery" link to admin sidebar navigation (between Dashboard and Clients)
- [x] 15. Templates — Partials
  - [x] 15.1. Create `templates/partials/discovery_brief_form.html` (textarea 5000 char max with live counter, client name field, optional client dropdown, submit button)
  - [x] 15.2. Create `templates/partials/discovery_entities.html` (entities grouped by category, editable chips, add/remove, confirm button)
  - [x] 15.3. Create `templates/partials/discovery_hypotheses.html` (hypothesis cards with statement, category badge, confidence bar, Fact/Choice badge)
  - [x] 15.4. Create `templates/partials/discovery_research_progress.html` (per-hypothesis progress dots, hx-trigger="every 2s")
  - [x] 15.5. Create `templates/partials/discovery_results.html` (research results per hypothesis: confidence bar with delta, reddit_signals table, no-signal indicator, confirm/reject buttons with reason field)
  - [x] 15.6. Create `templates/partials/discovery_report.html` (rendered report sections, operator notes textarea, export button, "Create Strategy" handoff button)
  - [x] 15.7. Create `templates/partials/discovery_report_export.html` (clean white-background branded template for print/PDF with TOC and sections)
- [x] 16. Client Detail Integration
  - [x] 16.1. Add "Discovery History" section to client detail page with linked sessions (date, status, iteration count, link to report) and "Start Discovery" button that pre-fills client_id
- [x] 17. Cost Integration
  - [x] 17.1. Ensure all Discovery LLM calls use log_ai_usage() with operation="discovery" and triggered_by=session_id; update admin_ai_costs() route to include "discovery" as filterable operation; add per-session cost display and Discovery cost line item on AI costs page
- [x] 18. Running Cost Display
  - [x] 18.1. On active session page show running total "$X.XX spent this session", update after each LLM call via HTMX oob swap or session page refresh
- [x] 19. Unit Tests
  - [x] 19.1. Create `tests/test_entity_extractor.py` — mock LLM responses, verify entity parsing, edge cases (<3 entities, malformed JSON)
  - [x] 19.2. Create `tests/test_confidence_scorer.py` — verify scoring rules with known inputs (strong signal, weak signal, no signal, narrow, absent)
  - [x] 19.3. Create `tests/test_hypothesis_engine.py` — mock LLM, verify dedup, retry logic, category assignment
  - [x] 19.4. Create `tests/test_session_manager.py` — state transitions, pagination, validation
  - [x] 19.5. Create `tests/test_strategy_handoff.py` — verify Client creation, FK linkage, ActivityEvent logging, subreddit pre-population
- [x] 20. Integration Tests
  - [x] 20.1. Create `tests/test_discovery_flow.py` — full flow with mocked LLM + mocked PRAW: session → entities → hypotheses → research → confirm/reject → report → handoff
  - [x] 20.2. Create `tests/test_discovery_routes.py` — HTTP tests: auth enforcement, HTMX partial responses, validation errors, form preservation on error

## Task Dependency Graph

```json
{
  "waves": [
    {"tasks": [1, 2, 3]},
    {"tasks": [4, 5, 6]},
    {"tasks": [7, 8]},
    {"tasks": [9, 10, 11]},
    {"tasks": [12, 13]},
    {"tasks": [14, 15, 16, 17, 18]},
    {"tasks": [19, 20]}
  ]
}
```

## Notes

- Entity extraction uses Gemini Flash (fast, cheap ~$0.0003/call)
- Hypothesis formation uses Gemini Flash
- Report generation uses Claude Sonnet (high-quality prose for sales artifact)
- Reddit research uses existing PRAW infrastructure (no new dependencies)
- Confidence scoring is pure Python (no LLM calls)
- All LLM costs tracked under operation="discovery" for economic model validation
- Total estimated AI cost per Discovery session: ~$0.07
- Admin UI follows existing dark theme (admin_base.html) with HTMX partials
- Maximum 5 iterations per session
- Visibility Report serves as $4K setup fee deliverable
