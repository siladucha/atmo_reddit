---
inclusion: fileMatch
fileMatchPattern: "**/ramp-operations-agent/**,**/daily_review/**,**/daily-ops-review/**,**/notifications/**,**/alert**"
---

# RAMP Agent — Role-Based Intelligence Surfaces

## Overview

The RAMP Operations Agent provides different intelligence surfaces to different roles. Each role gets scoped, relevant insights — never raw system internals they don't need.

Budget constraint: $1/day total for ALL agent intelligence. Trial clients and client managers get zero-LLM (templates + SQL rules only).

## Role Surfaces

### 1. Owner (Max) — Ops & Architecture

**Daily Ops Review** (Phase 1 — building now):
- 60-90 min structured morning ritual
- Health snapshot → changes → trends → hypotheses → forecast → 3 decisions
- Intelligence Report artifact (structured + narrative)
- Forecast accuracy tracking

**Operations Agent** (Phase 2):
- 24/7 monitoring → Telegram alerts (worker down, disk full, avatar banned)
- Autonomous recovery (restart workers, flush cache, freeze unhealthy avatars)
- Scaling intelligence (capacity model, time-to-limit projections)
- Silent failure detection (phantom scraping, scoring inflation, orphaned avatars)
- Telegram commands: `/status`, `/cost`, `/fleet`, `/approve {id}`, `/reject {id}`

**Delivery channel:** Admin panel (`/admin/daily-review`, `/admin/agent`) + Telegram bot

### 2. Partner (Tzvi) — Business & Clients

**What agent provides:**
- Weekly Business Digest (Sunday 10:00): MRR delta, churn risk, top/bottom clients, trial conversion, cost margin
- Client Health Alerts: "Client X had 0 posts in 7 days" / "Trial Y expires in 2 days"
- Revenue Forecast: "At current growth, break-even in N weeks"
- Meeting Prep: before client call — avatar stats, recent posts, karma trends, risks
- Upsell Signals: "Client Z on Seed plan uses 90% quota — suggest upgrade"

**Key constraint:** Partner NEVER sees pipeline buttons, kill switches, phase internals. Business metrics + client health only.

**Delivery channel:** Partner dashboard (`/admin/` partner view) + Telegram (high-severity alerts only) + email (weekly digest)

### 3. Client Managers — Daily Operations per Client

**What agent provides:**
- Daily Client Brief (09:00): "5 new drafts, 2 posted, 1 removed, avatar X risk 72%"
- Draft Priority Hints: "Review this first — thread trending, 4h window"
- Avatar Health Warnings: "Avatar Y removal rate 35% — consider pause"
- Content Quality Trends: "Approval rate dropped 15% — check generation quality"
- Action Suggestions: "Run pipeline for client Z — fresh threads, last run 48h ago"

**Key constraint:** Client managers see ONLY their assigned clients. Agent scopes all insights by client_id via UserClientAssignment.

**Delivery channel:** Portal notifications (SSE) + portal cards + email (daily brief)

**LLM budget:** $0 (SQL rules + templates only)

### 4. Avatar Managers — Fleet Health & Execution

**What agent provides:**
- Fleet Health Digest: "5 healthy, 2 at-risk, 1 frozen. Top risk: u/UserX (removal 40%)"
- Executor Performance: "Executor A: 90% SLA, avg 12 min. Executor B: 60% — follow up"
- Phase Promotion Ready: "u/Avatar1 completed 60 days Phase 1, karma +340 — ready for Phase 2?"
- Posting Anomaly: "3 failures in 10 min across 2 avatars — check proxy"
- Workload Balancing: "Avatar X at cap, 3 approved slots. Redistribute to Avatar Y?"

**Key constraint:** Avatar managers don't see client business data (MRR, plan, billing). Only avatar fleet ops.

**Delivery channel:** Admin panel (avatar section) + notifications + email (fleet digest)

**LLM budget:** $0 (SQL rules + templates only)

### 5. Trial Clients (self-service) — Guided First Steps

**What agent provides:**
- Onboarding Coach: "Step 3/6 complete. Next: choose subreddits."
- First Win Celebration: "Your first AI comment is ready for review!"
- Activity Nudge (email day 3, 7, 10): "No login in 3 days. Here's what happened."
- Upgrade Prompt (day 11): "Trial ends in 3 days. 15 comments generated, 8 posted."
- Quick Wins Report (weekly email): "3 posted, +12 karma, mentioned in 1 AI search"

**Key constraints:**
- No pipeline details, phases, risk scores exposed
- Language: positive, outcome-oriented ("warming up" not "Phase 1 hobby only")
- No LLM-enhanced analysis (budget $0 for trials)

**Delivery channel:** Portal notifications (SSE) + portal banners + email (templated)

## Budget Allocation ($1/day)

| Consumer | Budget | Spends on |
|----------|--------|-----------|
| Daily Review (owner) | $0.40 | Health summary, classifications, narrative |
| Monitoring/alerts (all roles) | $0.40 | Silent failure detection, anomaly classification |
| Reserve (spike days) | $0.20 | Extra analysis during incidents |
| Trial/client nudges | $0.00 | Template-only, no LLM |
| Partner digest | ~$0.05 (from monitoring) | Weekly summary (1 Gemini Flash call) |

## Implementation Phases

| Phase | Scope | Roles Served | Dependency |
|-------|-------|--------------|------------|
| Phase 1 | Daily Ops Review + Intelligence Report | Owner | Current spec (daily-ops-review) |
| Phase 2 | Telegram alerts, partner digest, client manager briefs | Owner + Partner + Client Manager | ramp-operations-agent spec |
| Phase 3 | Avatar manager fleet tools, trial nurture emails | All roles | Email infra (Brevo) + notification system |

## Architecture Principle

```
                    ┌─────────────────────────────┐
                    │     RAMP Operations Agent    │
                    │  (central intelligence hub)  │
                    │  - Signal collection (SQL)   │
                    │  - Rule-based scoring        │
                    │  - Optional LLM enrichment   │
                    └──────────────┬──────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         │                         │                         │
         ▼                         ▼                         ▼
┌─────────────────┐    ┌─────────────────────┐    ┌──────────────────┐
│  Owner Surface  │    │  Partner Surface    │    │  Scoped Surfaces │
│  ($0.40 LLM)   │    │  ($0.05 LLM)       │    │  ($0 LLM)        │
│                 │    │                     │    │                  │
│  - Daily Review │    │  - Weekly Digest    │    │  - Client Mgr    │
│  - Telegram bot │    │  - Client Alerts    │    │  - Avatar Mgr    │
│  - Full alerts  │    │  - Revenue forecast │    │  - Trial Client  │
│  - Agent page   │    │  - Upsell signals   │    │  (all templates) │
└─────────────────┘    └─────────────────────┘    └──────────────────┘
```

## Key Rules

1. **Scope isolation is absolute** — agent never leaks data across role boundaries
2. **LLM budget = owner privilege** — other roles get SQL+template intelligence only
3. **Never block operators** — if LLM budget exhausted, degrade gracefully, never halt
4. **Positive language for clients** — "warming up" not "Phase 1 hobby only", "building presence" not "low karma"
5. **Agent is advisory** — all final actions require human confirmation (Authority Framework)
6. **One agent, many surfaces** — single data pipeline, role-scoped presentation
