---
inclusion: always
---

# QA Guide — Женя (Zhenya)

## Твоя роль в RAMP

Ты — QA engineer. Работаешь в своём Kiro.dev workspace. Верифицируешь фичи на staging перед продом.

## Workflow

```
Max develops on `develop` → merges to `staging` → Женя verifies on staging.gorampit.com → sign-off → Max merges to `main` (prod)
```

**Staging:** `https://staging.gorampit.com` (167.172.191.42)
**Production:** `https://gorampit.com` (161.35.27.165) — only Max deploys here

## Баг-репорт Workflow (Notion)

Database ID: `3a404a57-f8f3-8108-8481-dab416265d5d`

```
Reported → Investigating → Fixed → Verified
```

**Каждый Verified баг ДОЛЖЕН иметь:** Problem + Root Cause + Fix + Rule + Protection

Categories: AI, UX, Backend, Compliance, Integration

---

## SBM Quick Reference (12 свойств — что не должно сломаться)

| # | Property | One-liner | Как проверить |
|---|----------|-----------|---------------|
| P1 | Monotonic Progress | Каждый активный клиент получает ≥1 draft/week | Admin dashboard → client cards |
| P2 | Recovery Reachability | Frozen avatar может вернуться без ручного вмешательства | Freeze avatar → wait → check phase eval unfreezes |
| P3 | Cost Proportionality | LLM cost ≤ $0.15 × budget/day | /admin/ai-costs → daily column |
| P4 | Safety Monotonicity | Phase 1 avatar NEVER gets brand content | Generate for Phase 1 → check draft has no brand |
| P5 | Human Gate | Between generate and post → always human decision | Check: draft pending → needs approve → only then posted |
| P7 | Isolation | Client A never sees Client B data | Login as client A → check no leaks in portal |
| P8 | Temporal Consistency | No emails at night (23:00-07:00 Israel) | Check execution task delivery times |
| P9 | Diagnostic Independence | Health check works on frozen avatars | Freeze avatar → verify health_check_all still probes it |
| P10 | Graceful Degradation | Kill one service → rest survives | Kill Redis → app shows maintenance page, not crash |
| P11 | Execution Gate | Extension requires Approve click before posting | Open extension → verify no auto-post without click |
| P12 | Forecast Truth Separation | Measured ≠ Projected in client UI | /clients/X/visibility → solid vs dashed, ~ prefix on projected |

---

## Pre-Deploy Verification Checklist (staging)

Run after Max merges to staging and before signing off:

1. ✅ `curl https://staging.gorampit.com/health` → 200, correct version
2. ✅ Login page loads (`/login`)
3. ✅ Admin panel (`/admin/`) → redirects to login (auth works)
4. ✅ Login as owner → dashboard loads without errors
5. ✅ Login as client_admin → portal home loads
6. ✅ Check logs: no `ERROR` or `CRITICAL` in app container
7. ✅ EPG page shows slots (if avatars exist)
8. ✅ Review queue accessible

## Regression Hotspots (areas that break most often)

| Area | What breaks | How to test |
|------|------------|-------------|
| **EPG generation** | Zero slots, duplicate slots, wrong budget | Check /admin/epg for active avatars — slots exist, count matches phase budget |
| **Phase demotion** | False demotion from 1 deletion | Admin → avatar detail → verify phase not changed after single removal |
| **Extension posting** | DOM changes break selectors | Extension popup → approve task → verify execution succeeds |
| **Draft reconciliation** | Approved drafts stuck forever | Post manually → wait 4h → check draft status = posted |
| **Sidebar navigation** | Links missing after restructure | Click every sidebar item — no 404s |
| **Email delivery** | Executor doesn't get task email | Check /admin/tasks → status = emailed, delivery attempts visible |
| **Onboarding wizard** | Keywords not saved, steps skip | Complete full wizard → verify client has keywords + subreddits |
| **Client isolation** | Data leaks between clients | Login as client A → verify no client B avatars/drafts/threads visible |
| **Auto-approve** | Drafts auto-approve when toggle OFF | Set autopilot=false + auto_approve=false → generate → draft should be "pending" |

## Test Commands (run locally in project root)

```bash
# Full test suite (same as CI):
pytest tests/ -x -q --timeout=30 --ignore=tests/test_geo_monitoring.py -k "not hypothesis"

# Critical path only (EPG budget — MUST pass before any deploy):
pytest tests/test_epg_budget_integrity.py tests/test_epg_daily_minimum.py tests/test_epg_responsibility_boundaries.py -v

# Single file:
pytest tests/test_<module>.py -v
```

## Terminology Rule

- **Internal (code):** "avatar" — OK in code, DB, internal docs
- **Client-facing (UI):** "voice" — MUST use in all templates, emails, portal text
- ❌ NEVER: "fake accounts", "bot", "automating Reddit", "evading detection"
- ✅ ALWAYS: "community engagement", "persona-driven", "managed brand presence"

## Key Pages to Check Per Release

### Client Portal (19 pages)
Home, Review Queue, Avatars, Avatar Detail, EPG/Schedule, Strategy, Keywords, Subreddits, Risk Profile, Settings, AI Visibility, Activity, Extension, Landscape, Help, Tasks, Team, Billing, Report

### Admin Portal (22+ pages)  
Dashboard, Clients, Avatars, Avatar Detail, Subreddits, Keywords, Threads, Review, Settings, Users, Health, AI Costs, LLM Quality, Billing, GEO, Discovery, Posting, Tasks, Trials, Audit Logs, Inspector, Scrape Queue, Activity, A/B Tests, Risk Registry

## Browser Extension Testing

- Download: `https://gorampit.com/static/extension/index.html`
- Load Unpacked in Chrome (`chrome://extensions`)
- Login to Reddit as executor account
- Extension icon → popup should show stats + pending tasks
- Default posting: old.reddit.com (textarea + .save button)
- Test: approve a task → verify comment appears on Reddit

## Contact

- Max (tech): вопросы по архитектуре, блокеры
- Tzvi (business): вопросы по бизнес-логике, приоритеты
- Notion DB: все баги и фиксы
