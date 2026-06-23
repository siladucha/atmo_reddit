---
inclusion: always
---

# Dashboard Architecture — Role-Based Views (June 23, 2026)

## Dashboard Routing (`/admin/`)

The `/admin/` endpoint renders a different dashboard based on the authenticated user's role:

| Role | Dashboard | Template | Focus |
|------|-----------|----------|-------|
| **owner** | Ops Command Center | `admin_dashboard.html` | System health, alerts, pipeline controls |
| **partner** | Business Cockpit | `admin_dashboard_partner.html` | MRR, client health, trial funnel, costs |
| **client_admin/client_manager/client_viewer** | → Redirect | 303 → `/clients/{id}/home` | Client portal (paying or trial) |

### Owner Dashboard

Shows: system alerts bar → top metrics → pipeline summary → topology → kill switches → client cards → side panels (freshness, avatar health, schedule, backups).

**Alert bar** powered by `app/services/alert_aggregation.py`:
- Worker offline (critical)
- Kill switches ON (high)
- Frozen avatars (medium/high)
- Stale scrapes >12h (medium)
- Expiring trials <3d (medium)
- Paying clients with 0 posts in 7d (high)

### Partner Dashboard

Shows: business KPIs (MRR, paying, trials, AI spend, margin) → attention items → client health table → trial funnel → cost & revenue.

**Business metrics** powered by `app/services/business_metrics.py`:
- `get_business_metrics()` — MRR (plan × list price), active counts, AI spend, margin
- `get_client_health_table()` — per-client health scoring (green/yellow/red)
- `get_trial_funnel()` — active → onboarded → first draft → converted
- `get_attention_items()` — prioritized action list for partner

**MRR formula:** `SUM(active paying clients × PLAN_PRICES[plan_type])`
- trial=$0, seed=$149, starter=$399, growth=$799, scale=$1499
- Update to Stripe actual amounts when billing is live

**Client health scoring:**
- 🔴 Red: 0 posts in 7 days (with avatars) OR all avatars frozen OR trial expired
- 🟡 Yellow: <3 posts/week OR some avatars frozen
- 🟢 Green: everything flowing

### Client Portal — Paying (`/clients/{id}/home`)

Template: `client/home.html`
Shows: pending drafts CTA → quick actions → metric cards → momentum feed → karma sparkline → navigation tiles (avatars, schedule, subreddits, keywords, strategy, report, AI visibility).

### Client Portal — Trial (`/clients/{id}/home`)

Template: `client/home_trial.html` (rendered when `client.plan_type == "trial"`)
Shows: trial countdown → onboarding progress bar (step X/6) → "what's happening now" → quick stats → simplified navigation (review, avatars, subreddits, keywords only).

**Design principles for trial:**
- No empty pages (hide Strategy/Report/EPG/AI Visibility until data exists)
- Show progress, not absence ("warming up" not "0 posts")
- Celebrate first result ("Your first AI comment is ready!")
- Always show upgrade CTA with days remaining

---

## Key Services

| Service | Purpose | Used By |
|---------|---------|---------|
| `services/operations_dashboard.py` | Pipeline metrics, client cards, freshness, schedule | Owner dashboard |
| `services/business_metrics.py` | MRR, client health, trial funnel, attention items | Partner dashboard |
| `services/alert_aggregation.py` | System alerts (worker, kill switches, frozen, stale) | Owner dashboard |

---

## Design Rules

1. **Partner never sees pipeline buttons** — they don't run ops. Business metrics only.
2. **Owner dashboard = triage tool** — health → alerts → quick actions. Deep-dive on dedicated pages.
3. **Trial portal = guided experience** — progress + what's next + celebration moments.
4. **Client-scoped roles → portal** — no admin theme, no admin sidebar links they can't access.
5. **New features go to dedicated pages** — not crammed into dashboard. Prevent god-dashboard creep.
6. **Alert bar has max 6 items** — overflow shows "+N more". Prevents alert fatigue.
7. **Health indicators are conservative** — red only when clearly broken, not on transient issues.


---

## Deployment Notes

**Code lives inside Docker image** (Dockerfile: `COPY . .`). No volume mount for app code.

Deployment sequence:
1. `rsync` local → server `/app/`
2. `docker compose build app` — rebuilds image with new code
3. `docker compose up -d app celery celery-beat` — starts new containers

**`restart` alone does NOT pick up code changes.** It reuses the old image.
**`rsync` alone does NOT affect running containers.** Files on host != files in container.
