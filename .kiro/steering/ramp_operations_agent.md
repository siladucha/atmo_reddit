---
inclusion: fileMatch
fileMatchPattern: "**/operations_agent*,**/watchdog/**,**/ramp_watchdog*,**/alert_aggregation*,**/signal_collector*"
---

# RAMP Operations Agent — Readiness & Tracking

## Current Status: Phase 1A+1B Deployed (External Watchdog + Telegram Alerts — July 2-3, 2026)

**Spec location:** `.kiro/specs/ramp-operations-agent/` (requirements.md, design.md, tasks.md)

## What's Deployed (July 2, 2026)

### External Watchdog — LIVE on Production

| Component | Location | Status |
|-----------|----------|--------|
| `ramp_watchdog.sh` | `/opt/ramp/ramp_watchdog.sh` (host) | ✅ Active (systemd timer, every 30s) |
| `pg_backup.sh` | `/opt/ramp/pg_backup.sh` (host) | ✅ Active (systemd timer, daily 03:00) |
| `ramp-watchdog.timer` | `/etc/systemd/system/` | ✅ Enabled |
| `ramp-backup.timer` | `/etc/systemd/system/` | ✅ Enabled |
| `watchdog.env` | `/opt/ramp/watchdog.env` | Created (Telegram creds pending) |
| Backup storage | `/opt/ramp/backups/` | ✅ 65MB first backup (14-day rotation) |
| State dir | `/var/lib/ramp-watchdog/` | ✅ Cooldown files, last_success marker |

**Checks performed (every 30 seconds):**
1. Redis alive (redis-cli PING)
2. PostgreSQL alive (pg_isready)
3. App /health endpoint (HTTP 200 check via HTTPS)
4. Celery Beat container running + heartbeat timestamp in Redis
5. Celery worker containers running
6. Disk usage (<90%)

**On failure:** Auto-restart container + Telegram alert (with 5-min cooldown to prevent spam).
**On recovery:** Clear alert state + send RECOVERED notification.

**Tested scenarios (production, July 2 2026):**
- Kill Beat → detected + restarted in 12s
- Kill PostgreSQL → detected + restarted in 23s
- Kill Redis → detected + restarted in 15s
- Kill App → detected + restarted in 30s (migrations)
- Kill ALL 5 containers → all recovered in 60s (2 watchdog passes)
- 50 concurrent requests after recovery → 100% success rate

### PostgreSQL Backup — LIVE
- Daily at 03:00 UTC via systemd timer
- Format: `pg_dump --format=custom` (compressed, restorable)
- Rotation: 14 days (older deleted automatically)
- Alert on failure: empty dump or pg_dump error → Telegram
- Weekly summary on Sunday
- RPO: 24 hours (WAL archiving planned for 15 min)

## Architecture Summary

3-layer autonomous operations agent:

| Layer | Where | Survives | Purpose |
|-------|-------|----------|---------|
| **1 — External Watchdog** | Host OS (systemd, outside Docker) | Container crash, Celery death, Docker failure | Infrastructure liveness |
| **2 — Decision Engine** | Celery (inside Docker) | App alive | Authority framework, actions, alerts |
| **3 — Intelligence** | Celery (inside Docker) | App alive | Economics, silent failures, briefings, scaling |

## Foundation Already Built (Daily Ops Review Phase 1)

| Component | File | Reuse for Agent |
|-----------|------|-----------------|
| Signal Collector | `app/services/daily_review/signal_collector.py` | 80% of metrics the agent needs (errors, cost, avatars, scraping, posting) |
| Cost Governor | `app/services/daily_review/cost_governor.py` | $1/day budget, `agent_` prefix tagging, exhaustion check |
| Alert Aggregation | `app/services/alert_aggregation.py` | Basic alerts (worker, kill switches, stale scrapes) + LLM spend spike alert (R-AI-007) |
| LLM Runaway Protection | `app/services/ai.py` | 3-layer budget gate (per-task 50 calls, $5/10min circuit breaker, 500/h + 3000/d caps). Agent can read Redis keys `ramp:llm:cost:window:*` for real-time spend visibility |
| ReviewSnapshot model | `app/models/review_snapshot.py` | Immutable point-in-time data pattern |
| Daily Review UI | `app/routes/daily_review.py` | 10 endpoints, HTMX partials pattern |

## What's Missing (Red Zones — Remaining After Phase 1A+1B)

### Database Models (8 models, 1 migration — Phase 2)
- `agent_metric` — time-series metrics (60s collection)
- `agent_alert` — 4-tier alert system with cooldown/escalation
- `agent_action` — autonomous action log with rollback plans
- `agent_proposal` — confirmation-required workflow (Telegram approve/reject)
- `agent_heartbeat` — agent self-monitoring
- `agent_economic_snapshot` — daily cost/margin per client/avatar
- `agent_weekly_report` — generated markdown + structured JSONB
- `agent_config` — runtime configuration store
- Migration: `agent01`

### Autonomous Actions (Phase 2)
- Service recovery: restart workers, flush Redis queues, rotate logs
- Pipeline: freeze avatar, redistribute drafts, retry failed generation
- Resource: adjust concurrency, trigger model fallback

### Economics Engine (Phase 3)
- Per-client daily cost (LLM + infra + proxy)
- Margin calculation (revenue - cost)
- Break-even analysis
- Optimization suggestions (model downgrades, batch consolidation)
- **Partially addressed (July 9, 2026):** `unit_economics.py` implements $/client, $/avatar, $/draft, provider budget tracking, and "at N clients" forecast. Cost reconciliation task detects pricing drift. Full margin calculation (revenue - cost) still pending Stripe integration.

### Silent Failure Detection (Phase 3)
- Phantom scraping (scrape succeeds but 0 new threads)
- Scoring inflation (avg score drifting up without quality change)
- Stale learning (no edit records captured in 14 days)
- Orphaned avatars (active but no pipeline output 7+ days)
- Quality drift (karma/removal ratio degrading slowly)
- ~~LLM response quality degradation (empty responses, parse errors, latency spikes)~~ → **PARTIALLY ADDRESSED July 19, 2026:** `check_llm_quality` task (every 4h) detects per-model×operation degradation vs 7-day baseline. Alerts on dashboard + Telegram. Admin: `/admin/llm-quality`.

### Scaling Intelligence (Phase 4)
- 5-dimension capacity model (DB connections, Redis memory, Celery workers, LLM budget, Reddit API)
- Time-to-limit projection
- Bottleneck identification

### Briefings (Phase 4)
- Daily summary at 08:30 IST (Telegram)
- Weekly strategic report Sunday 10:00 IST

## Implementation Phases & Effort

| Phase | Scope | Effort | Value | Status |
|-------|-------|--------|-------|--------|
| **1A** | External Watchdog (systemd) | 3-5 days | 🔴 Critical — prevents silent death | ✅ **DEPLOYED July 2, 2026** |
| **1B** | Telegram Bot (alert delivery) | 1 hour | 🔴 Critical — operator notification | ✅ **DEPLOYED July 3, 2026** |
| **2** | Authority + Actions | 1.5-2 weeks | 🟡 High — autonomous recovery | Not started |
| **3** | Economics + Silent Failures | 1-1.5 weeks | 🟡 Medium — cost intelligence | Not started |
| **4** | Briefings + Reports + Scaling | 1 week | 🟢 Strategic — Max→architect | Not started |

**Total remaining: 3-5 weeks focused work (Phase 2-4).**

## Dependencies & Blockers

| Dependency | Status | Blocks |
|------------|--------|--------|
| Telegram Bot Token | ✅ Configured (July 3, 2026) | Phase 1B ✅ DONE |
| UptimeRobot account | ❌ Not configured | External webhook backup |
| systemd access on prod | ✅ root SSH available | Phase 1A ✅ DONE |
| Redis pub/sub | ✅ Working | Alert delivery |
| LiteLLM budget tagging | ✅ `agent_` prefix in cost_governor | Phase 3 |
| External watchdog scripts | ✅ Deployed `/opt/ramp/` | Phase 1A ✅ DONE |
| PostgreSQL backup | ✅ Daily 03:00, 14-day rotation | Phase 1A ✅ DONE |
| Telegram alerts | ✅ Live (bot token + chat_id configured, tested) | Phase 1B ✅ DONE |

## Critical Motivation

**June 2026 incident:** Celery Beat stopped silently. System produced zero output for 17 days. Nobody noticed until manual inspection.

**July 2-3, 2026 fix:** External watchdog deployed + Telegram alerts configured. Tested by killing every container — auto-recovery in ≤60 seconds, operator notified on phone within 30s.

Without Layer 1 (External Watchdog + Alerts), this WOULD have repeated. The in-process monitoring (signal_collector, heartbeat) dies WITH the process it monitors.

## Priority Rule

Phase 1A+1B ✅ COMPLETE. Silent death is no longer possible — operator gets Telegram push within 30s of any failure. Next priority: Phase 2 (Authority Framework + Autonomous Actions) when engineering time allows.

## Audit History

| Date | Finding | Action |
|------|---------|--------|
| 2026-07-02 | 0% implemented, spec complete, no blockers except Telegram token | Steering file created, tracking initiated |
| 2026-07-02 | Pipeline E2E doc created (.kiro/steering/pipeline_end_to_end.md) | Agent signal sources now fully documented — collector can reference pipeline stages |
| 2026-07-02 | **Phase 1A DEPLOYED** | External watchdog (bash+systemd) + PG backup. Tested: kill all containers → auto-recovery ≤60s. Risk R-INFRA-001/002 → mitigated. |
| 2026-07-03 | **Phase 1B DEPLOYED** | Telegram bot token configured. Alerts now push to Max's phone. Tested: kill Beat → 🔴 alert received → ✅ recovered. |
| 2026-07-07 | **Beat memory leak RESOLVED** | Root cause: `include=[]` loaded 31 heavy modules into Beat (unnecessary). Fix: separate lightweight `beat_app.py`. Stable 25 MB. Risk R-INFRA-002 → `resolved`. Deploy grace period added to watchdog + deploy.sh. |
| 2026-07-15 | **Provider Budget Multi-Channel Alerting DEPLOYED** | `check_provider_budgets` Celery task every 4h. 3 channels: Telegram push, email (owner+partner), admin bell. Partner dashboard now shows system alerts bar. Redis cooldown 12h. Prevents R-AI-008 (silent credit exhaustion). |
| 2026-07-19 | **LLM Quality Monitor DEPLOYED** | `check_llm_quality` task every 4h. Tracks quality_outcome on every LLM call. Detects degradation vs 7-day baseline (success rate, latency, fallback rate, empty rate). Admin page + dashboard alerts. Risk R-AI-011 → mitigated. |
| 2026-07-22 | **Stripe Billing Integration DEPLOYED (code)** | BillingService + SubscriptionManager + AccessGate + webhook handler + portal billing + admin billing + coupons. 98 tests. Pending: staging/prod deploy. Risk R-BIZ-009 → mitigated. |
| 2026-07-22 | **Engineering Memory / QA Intelligence DEPLOYED** | BugReport PostgreSQL model, intake form /report-issue (3-layer anti-bot, screenshot upload, auto-detect role), admin sidebar links, 31 bugs seeded. Notion deprecated as primary store. Closes: BUG-025 (Report Bug link), BUG-032 (Extension link). QA verification UI pending. |

## Related Documentation

- `.kiro/steering/pipeline_end_to_end.md` — Full E2E pipeline (what the agent monitors)
- `.kiro/steering/system_behavior_model.md` — SBM properties (what the agent protects)
- `.kiro/steering/pipeline_safety_architecture.md` — Safety gates + phase system
- `.kiro/specs/ramp-operations-agent/` — Full spec (requirements, design, tasks)

