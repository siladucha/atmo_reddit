# RAMP — QA Test Suite Overview

**Prepared for:** QA Manager (Fredo)  
**Date:** June 14, 2026  
**Platform version:** 0.2.0  
**Test framework:** pytest + hypothesis (property-based testing)  
**Total:** 76 test files · 1,123 collected tests

---

## 1. Executive Summary

The RAMP test suite covers 9 functional areas across 4 testing methodologies. Test coverage focuses on business-critical paths: RBAC/isolation (preventing cross-client data leakage), AI pipeline correctness, safety gates, and the self-learning loop.

| Methodology | Files | Tests | Purpose |
|-------------|-------|-------|---------|
| Deterministic Unit | 42 | ~600 | Isolated function/service logic with known inputs/outputs |
| Property-Based (Hypothesis) | 22 | ~180 | Invariant validation on random inputs — finds edge cases |
| Integration | 3 | ~20 | Multi-service interaction with real DB |
| E2E | 2 | 2 | Full pipeline from onboarding to generation |

---

## 2. Coverage by Functional Area

### 2.1 Authentication & Security (33 tests, 3 files)

| File | Tests | Type | What It Validates |
|------|-------|------|-------------------|
| test_auth.py | 9 | DET | Register, login, JWT token creation/validation |
| test_get_current_user.py | 14 | DET | Base permission dependency — token parsing, user lookup |
| test_security.py | 10 | DET | Security headers, CSRF, XSS protection, cookie settings |

**Risk if failing:** Unauthorized access, session hijacking, credential leakage.

---

### 2.2 RBAC & Client Data Isolation (310 tests, 14 files)

This is the most heavily tested area — business-critical for multi-tenant SaaS.

| File | Tests | Type | What It Validates |
|------|-------|------|-------------------|
| test_permission_guards.py | 49 | DET | All 6 role guards (require_owner → require_authenticated) |
| test_rbac_scenarios.py | 53 | DET | End-to-end RBAC scenarios for all role combinations |
| test_cross_client_isolation.py | 35 | DET | Client A cannot see Client B's data |
| test_b2b_access_control.py | 32 | DET | B2B role hierarchy + team management |
| test_b2c_viewer_access.py | 28 | DET | B2C user scope restrictions |
| test_access_control.py | 26 | DET | Conditional draft approval logic |
| test_team_management.py | 19 | DET | client_admin team management scope |
| test_b2c_upgrade.py | 14 | DET | B2C → B2B role upgrade path |
| test_isolation_helper.py | 12 | DET | _avatar_accessible_by_client (owns + rents) |
| test_avatar_scoping.py | 11 | DET | Avatar visibility (owned + rented + farm) |
| test_generate_comment_isolation.py | 10 | DET | LLM generation uses only authorized context |
| test_llm_isolation_props.py | 8 | PBT | Random avatar/client combos can't leak data |
| test_query_scoping_props.py | 7 | PBT | Query scope layer blocks cross-tenant queries |
| test_select_persona_isolation.py | 6 | DET | Persona selection respects client boundary |

**Risk if failing:** Cross-client data leakage, privilege escalation, unauthorized LLM context injection.

---

### 2.3 AI Pipeline & EPG (122 tests, 9 files)

| File | Tests | Type | What It Validates |
|------|-------|------|-------------------|
| test_ai_service.py | 23 | DET | LLM cost calculation, JSON extraction, model fallback |
| test_epg_responsibility_boundaries.py | 22 | DET | EPG slot boundaries, phase gates, dedup |
| test_removal_feedback.py | 22 | DET | Removal feedback loop + risk weight adjustments |
| test_post_filter.py | 21 | DET | Post filter — text quality gate before scoring |
| test_karma_multiplier.py | 15 | DET | Subreddit karma multiplier calculation |
| test_outcome_analysis.py | 10 | DET | Posting outcome analysis (karma, removals) |
| test_feedback_loop.py | 7 | DET | Performance feedback → EPG weight adjustment |
| test_e2e_onboarding.py | 1 | E2E | Full: onboarding → score → generate → review |
| test_full_cycle.py | 1 | E2E | Discovery → Strategy → EPG → Posting cycle |

**Risk if failing:** Incorrect scoring, wrong avatar selection, EPG scheduling errors, cost overruns.

---

### 2.4 Admin UI & Operations (155 tests, 9 files)

| File | Tests | Type | What It Validates |
|------|-------|------|-------------------|
| test_admin_panel.py | 33 | DET | Admin routes render correctly, CRUD operations work |
| test_admin_ui_preservation.py | 28 | PBT | UI changes don't break existing functionality |
| test_humanize_number.py | 23 | DET | Number formatting in templates |
| test_topology_service.py | 17 | DET | System topology data aggregation |
| test_admin_ui_bug_conditions.py | 16 | PBT | Edge cases that could crash admin renders |
| test_operations_dashboard.py | 16 | DET | Operations dashboard data endpoints |
| test_pages.py | 13 | DET | All UI pages load with 200 OK (smoke test) |
| test_fdr_api_endpoints.py | 7 | DET | Full Data Report API regression |
| test_admin.py | 2 | DET | Admin dashboard stats API |

**Risk if failing:** Broken admin panel, operator cannot manage clients/avatars.

---

### 2.5 Discovery Engine (60 tests, 8 files)

| File | Tests | Type | What It Validates |
|------|-------|------|-------------------|
| test_discovery_state.py | 13 | PBT | Session state machine transitions |
| test_session_manager.py | 12 | PBT | Session CRUD, iteration limits, status updates |
| test_discovery_routes.py | 8 | DET | Admin routes: create, research, decide, report |
| test_confidence_scorer.py | 8 | PBT | Hypothesis confidence scoring logic |
| test_entity_extractor.py | 6 | DET | NLP entity extraction from client brief |
| test_hypothesis_engine.py | 6 | PBT | Hypothesis formation from entities |
| test_strategy_handoff.py | 6 | PBT | Discovery → Strategy data transformation |
| test_discovery_flow.py | 1 | INT | Full flow: brief → entities → hypotheses → report |

**Risk if failing:** Incorrect research results, broken handoff to Strategy, duplicate clients.

---

### 2.6 GEO/AEO Monitoring (43 tests, 1 file)

| File | Tests | Type | What It Validates |
|------|-------|------|-------------------|
| test_geo_monitoring.py | 43 | DET | Prompt CRUD, competitor tracking, batch execution, brand detection, citation parsing, rate limiting |

**Risk if failing:** Incorrect brand visibility tracking, Perplexity API overuse, wrong competitive data.

---

### 2.7 Self-Learning Loop (63 tests, 13 files)

| File | Tests | Type | What It Validates |
|------|-------|------|-------------------|
| test_learning_loop.py | 16 | DET | Edit storage, retrieval, dedup |
| test_learning_panel_endpoint.py | 10 | DET | Admin learning panel renders correctly |
| test_learning_integration.py | 9 | INT | Full loop: edit → pattern → few-shot injection |
| test_format_learning_context.py | 8 | DET | Learning context formatted into LLM prompt |
| test_review_learning_hook.py | 6 | DET | Review actions trigger edit capture |
| test_edit_summary_props.py | 3 | PBT | Word-level diff algorithm correctness |
| test_pattern_computation_props.py | 3 | PBT | Pattern extraction threshold + limit |
| test_pattern_constraints_props.py | 2 | PBT | Pattern rule length validation |
| test_retention_props.py | 2 | PBT | Record retention (200 max, 180-day TTL) |
| test_example_selection_props.py | 1 | PBT | Few-shot example relevance scoring |
| test_learning_capture_props.py | 1 | PBT | Edit capture record structure |
| test_prompt_format_props.py | 1 | PBT | Formatted prompt structure |
| test_provenance_props.py | 1 | PBT | Generation provenance metadata stored |

**Risk if failing:** AI doesn't learn from human edits, stale patterns override correct ones.

---

### 2.8 Safety & Health (142 tests, 5 files)

| File | Tests | Type | What It Validates |
|------|-------|------|-------------------|
| test_health_checker.py | 41 | DET | 5-state health classification (healthy → suspended) |
| test_health_dashboard.py | 35 | PBT | Health dashboard data under various state combos |
| test_text_sanitizer.py | 33 | DET | Markdown/Unicode stripping, Reddit-safe output |
| test_risk_engine_filtering.py | 18 | DET | Risk engine + historical removal rate scoring |
| test_safety.py | 15 | DET | Content checks, brand ratio, phase gates, rate limits |

**Risk if failing:** Shadowbanned avatars keep posting, unsafe content passes through, account bans.

---

### 2.9 Data Integrity & Models (118 tests, 14 files)

| File | Tests | Type | What It Validates |
|------|-------|------|-------------------|
| test_audit_preservation.py | 14 | PBT | Audit log query/filter correctness |
| test_audit_critical_regressions.py | 12 | DET | Critical audit regression scenarios |
| test_avatar_analysis_endpoint.py | 11 | DET | Avatar LLM analysis REST API |
| test_audit_bug_condition.py | 10 | PBT | Audit log gap detection in background tasks |
| test_avatar_analysis_few_shot.py | 10 | DET | Few-shot injection into analysis prompt |
| test_avatars.py | 9 | DET | Avatar CRUD + health state transitions |
| test_avatar_analysis_properties.py | 8 | PBT | Analysis service invariants |
| test_avatar_analysis_edit_endpoint.py | 7 | DET | Analysis edit submission endpoint |
| test_clients.py | 7 | DET | Client CRUD + relationship integrity |
| test_embedding_service.py | 18 | DET | Embedding diversity + cosine similarity |
| test_reddit_service.py | 4 | DET | Reddit deduplication (no real API calls) |
| test_review.py | 4 | DET | Review API — approve/reject/edit flow |
| test_avatar_analysis_edit_properties.py | 3 | PBT | Edit storage + few-shot retrieval |
| test_avatar_analysis_usage_log.py | 1 | PBT | AI usage cost tracking |

**Risk if failing:** Data corruption, lost edits, incorrect cost attribution.

---

## 3. Test Execution

### Run all tests
```bash
cd reddit_saas
../.venv/bin/python -m pytest tests/ -v
```

### Run by category
```bash
# RBAC only
../.venv/bin/python -m pytest tests/test_rbac_scenarios.py tests/test_permission_guards.py tests/test_cross_client_isolation.py -v

# Safety only
../.venv/bin/python -m pytest tests/test_safety.py tests/test_health_checker.py tests/test_text_sanitizer.py -v

# Property-based only (slower — generates random inputs)
../.venv/bin/python -m pytest tests/ -k "props or properties" -v

# Quick smoke (all pages load)
../.venv/bin/python -m pytest tests/test_pages.py -v
```

### Run single file
```bash
../.venv/bin/python -m pytest tests/test_geo_monitoring.py -v
```

---

## 4. Known Gaps (Not Yet Tested)

| Area | Risk | Priority |
|------|------|----------|
| Automated posting (PRAW + proxy) | Cannot unit-test without mocking Reddit API | P1 — mock tests needed |
| Celery Beat scheduling (timing) | Timing jitter, race conditions | P2 — integration test |
| OAuth callback flow | Pending Reddit approval | P3 — blocked |
| Admin user deletion (FK cascade) | Was broken, just fixed (June 14) | P1 — regression test needed |
| GEO batch execution (Perplexity) | Requires API key | P2 — mock test |
| Client deactivation cascade | Complex FK chain | P1 — E2E test needed |
| Mobile API endpoints | Not built yet | Deferred |
| Concurrent posting (Redis locks) | Race conditions | P2 — load test |

---

## 5. Testing Methodology Notes

### Property-Based Tests (Hypothesis)
- Generate random inputs to find edge cases humans wouldn't think of
- Each PBT file runs 50-200 examples per test by default
- Slower than deterministic tests (~5-10x per test case)
- Most valuable for: RBAC boundaries, data isolation, pattern matching

### Deterministic Tests
- Fixed inputs → expected outputs
- Fast execution, good for regression
- Cover happy path + known edge cases

### Integration Tests
- Use real PostgreSQL (test DB via conftest.py)
- No mocking of DB layer
- Validate multi-service orchestration

### E2E Tests
- Mock external APIs (Reddit, LLM) but use real DB + real routes
- Validate full business workflows end-to-end

---

## 6. CI/Environment Requirements

- Python 3.12+
- PostgreSQL 16 running locally (test DB auto-created by conftest.py)
- Redis running locally (for lock/rate limiter tests)
- No internet required (all external APIs mocked)
- `.env` file with DB credentials (see `.env.example`)

---

## 7. Recommended QA Process

1. **Before each deploy:** Run full suite (`pytest tests/ -v`)
2. **After RBAC changes:** Run isolation suite (`tests/test_rbac_scenarios.py`, `test_cross_client_isolation.py`, `test_permission_guards.py`)
3. **After AI prompt changes:** Run learning + generation tests
4. **After DB migrations:** Run all model/CRUD tests + audit tests
5. **Weekly:** Run property-based tests with `--hypothesis-seed=random` to explore new edge cases

---

*Document auto-generated from test suite analysis. Last updated: June 14, 2026.*
