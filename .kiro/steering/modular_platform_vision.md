---
inclusion: manual
---

# Modular Platform Vision — Strategic Architecture Direction

## Status: DEFERRED — Strategic Orientation Document

**Decision (July 22, 2026):** This is the long-term platform architecture target. NOT for immediate implementation.
**Trigger for revisiting:** First monitoring-only client request OR 5+ paying engagement clients stable.

---

## Core Hypothesis

RAMP's architecture already allows decomposition into independent product modules. The GEO/AEO monitoring layer has zero dependency on Reddit avatars or the engagement pipeline. This means "AI Visibility Monitoring" can be sold standalone with ~12 hours of work.

---

## Current Module Independence Assessment

### Already Independent (zero Reddit/Avatar dependency)

| Component | Key Files | Ready to sell standalone? |
|-----------|-----------|:------------------------:|
| Auth + RBAC (7 roles) | `auth.py`, `permissions.py`, `user.py` | ✅ |
| AI Provider Layer | `ai.py`, `call_llm`, `log_ai_usage`, budget gates | ✅ |
| GEO/AEO Monitoring | `geo_query_runner.py`, `geo_providers.py`, `geo_brand_detection.py` | ✅ |
| Forecast & Reporting (5-layer) | `forecast/observed_reality.py`, `visibility_forecaster.py`, `report_composer.py`, `platform_risk.py`, `business_impact.py` | ✅ |
| Notifications | SSE + Redis PubSub + `notifications.py` | ✅ |
| Client Emails (Brevo) | `client_emails.py`, weekly digest | ✅ |
| Billing Dashboard | `unit_economics.py`, provider budgets | ✅ |
| UX Manual Overlay | YAML + registry | ✅ |
| Settings Engine | DB key-value + `get_config()` | ✅ |
| Audit Trail | `AuditLog` + `ActivityEvent` | ✅ |
| Celery Infrastructure | Beat + workers + distributed locks | ✅ |
| External Watchdog | systemd timer + PG backups | ✅ |

### Tightly Coupled to Reddit + Avatar

| Component | Coupling Reason |
|-----------|-----------------|
| Pipeline (scrape → score → generate → post) | Reddit threads + avatar credentials |
| EPG (portfolio manager, opportunity engine) | Daily plan for avatars |
| Phase System (0 → 1 → 2 → 3) | Avatar lifecycle |
| Health Checker (shadowban, CQS) | Reddit API probes |
| Browser Extension | Reddit DOM interaction |
| Draft Reconciliation | Matches drafts to Reddit comments |
| Karma Tracking | Reddit API |
| Subreddit Risk Profiles | PRAW + moderation patterns |
| Self-Learning Loop | Tied to comment drafts |

---

## Target Architecture (When Ready)

```
CORE PLATFORM (always included, any client)
├── Identity (users, orgs, RBAC, auth)
├── Billing (Stripe subscriptions, usage metering)
├── AI Engine (LLM router, cost tracking, quality monitoring)
├── Notifications (SSE, email, Telegram, webhooks)
├── Settings & Config (DB settings, feature flags)
├── Audit & Compliance (logs, events)
├── Admin Shell (admin panel framework)
├── Client Portal Shell (portal framework)
└── Scheduler (Celery Beat + task infrastructure)

FEATURE MODULES (enabled per-client by plan)
├── mod_visibility      — GEO/AEO monitoring, forecasting, reports
├── mod_engagement      — avatars, pipeline, EPG, posting, phases
├── mod_discovery       — market research, entity extraction, hypotheses
├── mod_intelligence    — subreddit profiling, risk scoring, fitness gate
├── mod_content_studio  — Voice Intelligence, repurposing (future)
└── mod_community       — Community Hub management (future)
```

### Module Boundary Rule (future)

Module = own folder `app/modules/<name>/` with:
- `models.py` (own tables only)
- `services/` (business logic)
- `routes.py` (endpoints)
- `tasks.py` (Celery tasks)
- `templates/` (UI)
- `__init__.py` with `register(app)` function

Core Platform doesn't import modules directly. Modules register via hooks/events.

---

## AI Visibility as Standalone Product

### What Exists (works today without avatars)

- `geo_query_runner.py` — no avatar_id anywhere
- `geo_providers.py` — pure abstraction (Perplexity, Claude, OpenAI)
- `geo_brand_detection.py` — string matching
- `visibility_forecaster.py` — S-curve math
- `report_composer.py` — JSONB assembly
- `business_impact.py` — ROI calculator
- Client visibility page (`/clients/{id}/visibility`)
- Weekly visibility digest email

### What Blocks Clean Standalone (~12h work)

| Dependency | Fix | Effort |
|-----------|-----|--------|
| `plan_type` has no "monitoring" value | Add plan_type="monitoring" | 1h |
| Onboarding step 5 = BYOA avatar connect | Conditional skip for monitoring plan | 4h |
| GEO prompts require manual creation | Auto-generate from onboarding keywords | 4h |
| Sidebar shows avatar-related pages | `{% if plan_type != 'monitoring' %}` guards | 2h |
| `observed_reality.py` collects Reddit metrics | Graceful skip when no avatars | 1h |

---

## Pricing Model (Monitoring-Only)

| Tier | Queries | Engines | Competitors | Report | Price | Cost | Margin |
|------|---------|---------|-------------|--------|-------|------|--------|
| Visibility Lite | 20/week | 2 | 5 | Weekly email | $99/mo | ~$3/mo | 97% |
| Visibility Pro | 50/week | 3 | 10 | Daily + portal | $249/mo | ~$20/mo | 92% |
| Visibility + Engagement | Pro + full RAMP | All | All | Real-time | $499+ | existing | existing |

### Sales Motion

1. Demo page shows gap (7.7% vs competitor 85%) — shock value
2. "Want to see this for your brand every week?" → $99/mo
3. "Want to close the gap, not just watch it?" → upsell to engagement

### Strategic Value of Monitoring-Only

- Lower entry barrier ($99 vs $149-399)
- Faster time-to-value (report in 24h, not 4-6 weeks of warming)
- Natural upsell funnel (see gap → want to close it)
- Validates PMF cheaply (people pay for AI visibility data?)
- Zero platform risk (no Reddit ToS issues with monitoring)
- Proves GEO/AEO thesis independently of engagement

---

## Current Friction Points (Not Blocking, But Noted)

### 1. Monolithic Router Registration
All 40+ routers load in `main.py` unconditionally. Not a problem at current scale.

### 2. Shared Models Without Boundaries
`Avatar` imported in 50+ files. SQLAlchemy loads full relationship graph. Fine for monolith, problem for microservices (future).

### 3. Client Model Overloaded
Mix of monitoring fields (`keywords`, `geo_monitoring_enabled`) and engagement fields (`max_avatars`, `autopilot_enabled`). Acceptable — group logically, don't split tables.

### 4. Navigation Assumes Full Product
All clients see Avatars, Schedule, Strategy in sidebar. Monitoring-only would need conditional nav.

---

## What IS OK To Do Now (Platform-Compatible Choices)

1. ✅ When adding client fields — note if monitoring-relevant or engagement-only (comment)
2. ✅ When building GEO features — keep zero dependency on avatars
3. ✅ When designing onboarding — think "what if no avatar step?"
4. ✅ When pricing — keep monitoring and engagement separable
5. ✅ When building reports — make them work with GEO data alone (no avatar metrics required)

## What NOT To Do Before Trigger

1. ❌ Refactor into microservices
2. ❌ Create `app/modules/` folder structure
3. ❌ Split models into separate apps
4. ❌ Build a plugin system
5. ❌ Abstract router registration with feature flags
6. ❌ Separate databases per module

All of this is premature abstraction for 0 paying clients. Current monolith serves first 10-20 clients fine. Conditional logic by `plan_type` is sufficient modularity.

---

## Trigger Conditions (When to Act)

| Trigger | Action |
|---------|--------|
| Client asks for monitoring-only | Implement the 12h checklist above |
| 3+ monitoring-only clients | Consider dedicated onboarding flow + marketing page |
| 5+ engagement clients stable | Consider formal module boundaries |
| Revenue > $5K/mo | Stripe billing becomes urgent (spec exists) |
| Team > 2 engineers | Module ownership boundaries become valuable |

---

## Relationship to Other Strategic Docs

| Document | Relationship |
|----------|-------------|
| `v3_north_star.md` | v3.0 assumes modular platform — this is the lighter precursor |
| `product_expansion_july2026.md` | Community Hub + Voice Intelligence = future modules |
| `competitive_landscape.md` | Monitoring-only = new competitive category (nobody sells AI visibility standalone) |
| `vulnerability_assessment.md` | Monitoring module has ZERO platform risk (no Reddit ToS issues) |

---

## Summary

Architecture is 80% ready for monitoring-only clients today. The remaining 20% is product decisions (plan_type, onboarding path, sidebar), not architectural changes. GEO/AEO is already a clean, independent subsystem with zero Reddit coupling.

The platform evolution is: monolith with conditional logic (now) → logical modules in monolith (5-10 clients) → extractable services (50+ clients, if ever needed).
