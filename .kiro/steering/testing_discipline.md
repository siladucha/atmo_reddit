---
inclusion: always
---

# Testing Discipline — Agent Rules

## Core Principle

**Tests exist to catch production bugs before deploy. Not for coverage metrics.**

Every test must answer: "what production failure does this prevent?" If the answer is "none" — the test is waste.

---

## Rules for AI Agent

### When writing code

1. **After changing allocation_engine, portfolio_manager, epg.py, phase.py, or epg_executor.py** — run:
   ```bash
   pytest tests/test_epg_budget_integrity.py tests/test_epg_daily_minimum.py tests/test_epg_responsibility_boundaries.py -v
   ```
   All must pass. These are the budget/EPG integrity gate.

2. **After changing any service in the EPG critical path** — verify fill rate logic:
   - `scan_opportunities()` returns enough opportunities
   - `allocate_portfolio()` selects up to budget (not less)
   - `get_budget_used_today()` counts correctly
   - Phase gates are respected

3. **Never add a test without a corresponding production bug or requirement.** Don't test obvious things. Test the things that break.

### When fixing bugs

1. **Write the test FIRST (red)** — prove the bug exists in test
2. **Fix the code (green)** — make test pass
3. **Test name = bug description:** `test_phase3_low_karma_demotes` not `test_phase_validation_case_7`

### When asked to add tests

1. Don't add property-based (hypothesis) tests unless explicitly asked — they're slow and currently all skipped
2. Don't add tests for admin UI rendering — too brittle, changes constantly
3. DO add tests for: budget math, phase transitions, safety gates, data isolation

---

## Test Tiers (Priority)

| Tier | Blocks deploy? | What |
|------|---------------|------|
| **1 — Budget Integrity** | YES | `test_epg_budget_integrity.py` — allocation fills budget, phase ceiling valid |
| **2 — Safety** | YES | Isolation, safety_blocks, health_checker |
| **3 — Functional** | No | Everything else |

---

## Known State (July 15, 2026)

- **1542 passed** — working tests
- **235 skipped** — dead/broken tests (technical debt, documented in `docs/QA_GUIDE.md`)
- **1 failed** — `test_rented_avatar_passes_accessibility_check` (quality gate change, known)
- **Critical coverage:** EPG budget path fully covered (19 tests)

### Files that MUST stay green

```
tests/test_epg_budget_integrity.py       # 19 tests — allocation + budget + phase
tests/test_epg_daily_minimum.py          # 13 tests — enforcement guarantees
tests/test_epg_responsibility_boundaries.py  # 22 tests — architecture contracts
```

If any of these fail → **do not deploy**. Fix first.

---

## Anti-Patterns (Do NOT do)

1. ❌ Don't mark failing tests as `skip` to make CI green — fix the bug or fix the test
2. ❌ Don't write tests that depend on seed data (conftest `db` fixture rollbacks everything)
3. ❌ Don't write tests that make real LLM calls (mock `call_llm` / `call_llm_json`)
4. ❌ Don't write tests that require Docker (we run on local PG/Redis)
5. ❌ Don't add 7 property-based test files for one feature (draft_expiry has 7 — this is waste)
6. ❌ Don't test internal method signatures — test behavior through public interfaces

---

## Running Tests (Quick Reference)

```bash
# Full suite (CI equivalent):
pytest tests/ -q --timeout=30 --ignore=tests/test_geo_monitoring.py -k "not hypothesis"

# Critical path only (30 sec):
pytest tests/test_epg_budget_integrity.py -v

# Before deploy (mandatory):
python -c "from app.main import app"
pytest tests/test_epg_budget_integrity.py tests/test_epg_daily_minimum.py tests/test_epg_responsibility_boundaries.py -x -q
```

---

## Relationship to Deploy Protocol

The deploy protocol (`.kiro/steering/deploy_protocol.md`) Phase 1 Pre-Flight includes:
- Step 8: "Regression tests pass" — this means ALL Tier 1 tests green

If Tier 1 fails → deploy aborted. No exceptions.
