# Implementation Plan:

## Overview

12 tasks implementing the Discovery → Client Strategy Handoff feature. Tasks 1-2 are data layer (migration + models). Task 3 is Pydantic schemas. Tasks 4-5 are service layer. Tasks 6-7 are routes and templates. Tasks 8-11 are pipeline integration. Task 12 is deployment.

Estimated total effort: 3-4 days.

## Tasks

- [x] 1. Alembic Migration — Add Client Strategy Fields
  - [x] 1.1 Create migration file `alembic/versions/cstrat01_add_client_strategy_fields.py`
  - [x] 1.2 Add `strategy_context` JSONB column (nullable) to `clients` table
  - [x] 1.3 Add `strategy_version` Integer column (nullable=False, server_default="0") to `clients` table
  - [x] 1.4 Add `strategy_generated_at` DateTime(timezone=True) column (nullable) to `clients` table
  - [x] 1.5 Add `strategy_source_session_id` UUID column (nullable) to `clients` table
  - [x] 1.6 Add `strategy_history` JSONB column (nullable) to `clients` table
  - [x] 1.7 Add `priority` Integer column (nullable) to `client_subreddit_assignments` table
  - [x] 1.8 Add `engagement_approach` Text column (nullable) to `client_subreddit_assignments` table
  - [x] 1.9 Create index `ix_clients_strategy_version` on `clients(id, strategy_version)`
  - [x] 1.10 Add downgrade function that drops all new columns and index
  - [x] 1.11 Run `alembic upgrade head` locally to verify migration applies cleanly
- [x] 2. Data Model Updates
  - [x] 2.1 Add `strategy_context` (JSONB, nullable) field to Client model in `app/models/client.py`
  - [x] 2.2 Add `strategy_version` (Integer, default=0, server_default="0") field to Client model
  - [x] 2.3 Add `strategy_generated_at` (DateTime(timezone=True), nullable) field to Client model
  - [x] 2.4 Add `strategy_source_session_id` (UUID, nullable) field to Client model
  - [x] 2.5 Add `strategy_history` (JSONB, nullable) field to Client model
  - [x] 2.6 Add `priority` (Integer, nullable) field to ClientSubredditAssignment in `app/models/subreddit.py`
  - [x] 2.7 Add `engagement_approach` (Text, nullable) field to ClientSubredditAssignment in `app/models/subreddit.py`
  - [x] 2.8 Add `"handed_off"` to `DISCOVERY_SESSION_STATUSES` list in the discovery session status constants
- [x] 3. Pydantic Schema — ClientStrategyOutput
  - [x] 3.1 Create file `app/schemas/client_strategy.py`
  - [x] 3.2 Define `StrategyMetadata` model (generated_at, source_session_id, model_used, generation_cost_usd, prompt_version)
  - [x] 3.3 Define `Positioning` model (audience, problem, value_mechanism, differentiation, confidence ≤0.9, evidence_refs)
  - [x] 3.4 Define `SubredditPriority` model (subreddit with r/ pattern, priority 1-10, engagement_approach, reason)
  - [x] 3.5 Define `ContentPillar` model (name, goal, confidence ≤0.9)
  - [x] 3.6 Define `ForbiddenZone` model (type literal, description, severity literal)
  - [x] 3.7 Define `AeoTarget` model (intent, user_question, expected_visibility_outcome)
  - [x] 3.8 Define `PhaseEntry` model (id, goal, entry_conditions, activities, exit_conditions)
  - [x] 3.9 Define `PhaseRoadmap` model (phases: list of PhaseEntry, min 2 max 5)
  - [x] 3.10 Define `ClientStrategyOutput` model (positioning, subreddit_priorities, content_pillars, forbidden_zones, aeo_targets, phase_roadmap)
- [x] 4. Strategy Generator Service
  - [x] 4.1 Create file `app/services/discovery/strategy_generator.py`
  - [x] 4.2 Implement `_load_system_prompt()` — reads `docs/agents/client_strategy_agent.md`
  - [x] 4.3 Implement `_build_user_prompt()` — formats report_content + client_brief + confirmed_hypotheses as JSON string
  - [x] 4.4 Implement `_get_latest_report()` — returns latest VisibilityReport sorted by report_version
  - [x] 4.5 Implement `_call_and_validate()` — single LLM call with JSON parse + Pydantic validation, returns (ClientStrategyOutput | None, dict)
  - [x] 4.6 Implement `generate_client_strategy()` — main function with retry logic (max 2 attempts, 30s total timeout)
  - [x] 4.7 Add AI usage logging via `log_ai_usage()` after each LLM call
  - [x] 4.8 Add proper error handling: ValueError on both attempts failing, TimeoutError on budget exceeded
- [x] 5. Updated Strategy Handoff Service
  - [x] 5.1 Rewrite `execute_handoff()` in `app/services/discovery/strategy_handoff.py` with full flow (generate → save → subreddits → GEO → status → event)
  - [x] 5.2 Implement `_save_strategy_to_client()` — persists strategy_context with version increment and history rotation (max 3 previous)
  - [x] 5.3 Implement `_import_subreddits_with_priority()` — upsert logic for up to 10 subreddits with priority + engagement_approach
  - [x] 5.4 Implement `_create_geo_prompts()` — creates GeoPrompt records from aeo_targets (skips duplicates, category="discovery_generated")
  - [x] 5.5 Implement `_log_handoff_event()` — creates ActivityEvent for handoff completion
  - [x] 5.6 Ensure `execute_handoff()` returns Client object (not dict)
  - [x] 5.7 Verify on server: trigger handoff on test session, confirm strategy_context saved
- [x] 6. Route Updates
  - [x] 6.1 Update `handoff_to_strategy()` in `app/routes/discovery.py` with status guard (reject if already "handed_off")
  - [x] 6.2 Add guard: reject if session.status != "completed"
  - [x] 6.3 Add guard: reject if session has no reports
  - [x] 6.4 Return 422 on ValueError (strategy generation/validation failure)
  - [x] 6.5 Return 500 on unexpected Exception
  - [x] 6.6 Ensure `execute_handoff` returns Client and route redirects to `/admin/clients/{client.id}`
- [ ] 7. Template Updates
  - [ ] 7.1 Update "Create Strategy" button in discovery session detail template with HTMX `hx-indicator` loading spinner
  - [ ] 7.2 Add `hx-disabled-elt="this"` to prevent double-click during generation
  - [ ] 7.3 Show disabled "Strategy Created" button when `session.status == "handed_off"`
  - [ ] 7.4 Show "Complete session first" disabled button when session is not completed
  - [ ] 7.5 Add "Handed Off" green badge to discovery session list template for sessions with status "handed_off"
- [ ] 8. Pipeline Integration — Generation
  - [ ] 8.1 Update `app/services/generation.py` to read `client.strategy_context` for positioning in prompt context
  - [ ] 8.2 Inject `content_pillars` names from strategy_context into generation prompt
  - [ ] 8.3 Inject `forbidden_zones` (hard_block severity only) as negative constraints in generation prompt
  - [ ] 8.4 Add null-safe check: `if client.strategy_context:` before reading strategy fields
- [ ] 9. Pipeline Integration — EPG & Scoring
  - [ ] 9.1 Update `app/services/epg/portfolio_manager.py` to read subreddit_priorities from strategy_context for weight allocation
  - [ ] 9.2 Update ClientSubredditAssignment queries to `ORDER BY priority ASC NULLS LAST`
  - [ ] 9.3 Add null-safe check for strategy_context before applying priority weights
- [ ] 10. Pipeline Integration — Phase Evaluation
  - [ ] 10.1 Update `app/services/phase.py` to reference `phase_roadmap` from `client.strategy_context`
  - [ ] 10.2 Use `entry_conditions` from strategy phases to inform phase promotion logic
  - [ ] 10.3 Add null-safe fallback to current behavior when no strategy_context exists
- [ ] 11. Pipeline Integration — Avatar Strategy Engine
  - [ ] 11.1 Update `app/services/strategy_engine.py` to inject Client Strategy context (positioning, content_pillars, forbidden_zones) into avatar strategy generation prompt
  - [ ] 11.2 Add optional `client_strategy_id` reference field concept to StrategyDocument model
  - [ ] 11.3 Add null-safe check: only inject when `client.strategy_context` is present
- [ ] 12. Deploy & Verify
  - [ ] 12.1 rsync code to server (`rsync -avz --exclude=... ./ root@161.35.27.165:/app/`)
  - [ ] 12.2 Run Alembic migration on server: `docker compose exec app alembic upgrade head`
  - [ ] 12.3 Rebuild Docker image: `docker compose -f docker-compose.yml -f docker-compose.prod.yml build`
  - [ ] 12.4 Restart containers: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`
  - [ ] 12.5 Test handoff on an existing completed Discovery session
  - [ ] 12.6 Verify `strategy_context` is populated in DB for the test client
  - [ ] 12.7 Verify pipeline reads strategy_context in next scheduled run (check activity events)

## Task Dependency Graph

```json
{
  "waves": [
    {"tasks": [1]},
    {"tasks": [2, 3]},
    {"tasks": [4]},
    {"tasks": [5]},
    {"tasks": [6, 7]},
    {"tasks": [8, 9, 10, 11]},
    {"tasks": [12]}
  ]
}
```

## Notes

- All new fields are nullable with sensible defaults — backward compatible with existing clients
- Pipeline integration tasks (8-11) use null-safe checks so existing clients without strategy continue working
- The LLM call takes ~10-15s so HTMX loading indicators are critical for UX
- Strategy generation costs ~$0.0006 per call (well within $0.002 budget)
- Hard timeout of 30s includes retry — if first attempt takes >25s, retry is skipped
- Uses existing `app/services/ai.py` pattern (LiteLLM) with model `gemini/gemini-2.5-flash`
- AIUsageLog records use task_type `strategy_generation`
