# Dashboard Redesign Brief — Risk & Governance Analysis

**Date:** June 23, 2026
**Author:** Max (Tech)
**For:** Tzvi (CEO) + internal decision-making
**Status:** Draft for discussion

---

## 1. Problem Statement

The current dashboard system has 4 separate views (Owner, Partner, Client Manager, Client Portal) that evolved organically during feature development. Each was added when the role was implemented, without a unified information architecture. The result: **Tzvi sees pipeline ops he doesn't need, clients see empty screens during trial, and nobody has a clear "what requires my attention right now" signal.**

---

## 2. Current State

| Dashboard | Role | What It Shows | Primary Use Case |
|-----------|------|---------------|------------------|
| Owner (`admin_dashboard.html`) | Max | System topology, kill switches, bulk pipeline triggers, backups, worker status | Ops monitoring & emergency response |
| Partner (`admin_dashboard_partner.html`) | Tzvi | Same pipeline throughput (scraped/scored/generated), client cards, AI costs, Run All buttons | ? (unclear — Tzvi doesn't run pipeline) |
| Client Manager (`admin_dashboard_client_manager.html`) | Agency staff | Single-client metrics in admin theme | Day-to-day client management |
| Client Portal (`client/home.html`) | Client users | Campaign overview, pending drafts, navigation tiles, momentum feed | Client self-service |

---

## 3. Identified Risks

### 3.1 Business Visibility Risk — Partner Dashboard

**Risk level: HIGH**

Tzvi's current dashboard shows: Scraped 47 / Scored 12 / Generated 8 / Posted 3.

Tzvi **cannot answer** from his dashboard:
- How much are we earning this month? (No MRR view)
- Which trial clients are about to expire? (No trial funnel)
- Which paying client hasn't received value this week? (No "client health" indicator)
- Are we burning more on AI than we earn? (Cost is shown but not in context of revenue)
- Who should I call today? (No prioritized action list)

**Impact:** Tzvi relies on WhatsApp/Slack to Max for every business question. Partnership becomes bottleneck. CEO cannot independently assess platform health.

**Mitigation:** Redesign Partner view as Business Cockpit with MRR, trial funnel, client health table, cost-to-revenue ratio.

---

### 3.2 Trial Conversion Risk — Empty Portal

**Risk level: HIGH**

A trial client signs up → onboarding wizard completes → client lands on portal home.

What they see: "0 active avatars", "0 posted this week", empty momentum feed, navigation tiles to pages with no data.

**Impact:** Trial client feels nothing is happening. No sense of progress. No understanding of timeline. Churn before first value delivery.

**Benchmark:** Day 1-3 is the highest-risk period for SaaS trial abandonment. If user doesn't see momentum by Day 3, conversion drops 60%+ (industry standard).

**Mitigation:** Dedicated trial experience with progress bar, status messages ("Your avatar is warming up — first comments expected in 48h"), countdown, and first-result celebration moment.

---

### 3.3 Operational Blind Spot Risk — No Alert Aggregation

**Risk level: MEDIUM**

Currently, problems are discovered by accident:
- Frozen avatar → only visible if you click into Avatars page
- Stale scrape → only visible in Scrape Freshness side panel (owner only)
- Worker offline → small dot in pipeline summary bar
- Phase demotion → activity event buried in feed
- Trial expired → no notification anywhere

**Impact:** Issues accumulate silently. XM Cyber incident (June 22) — generation halted because avatar was demoted, discovered 3 days later.

**Mitigation:** Alert bar at top of Owner dashboard. Priority queue for Partner ("3 clients need attention"). Notification for client when their pipeline state changes.

---

### 3.4 Role Confusion Risk — Client Manager Duplication

**Risk level: LOW-MEDIUM**

Client Manager sees a dark-themed admin panel (`admin_base.html`) with full sidebar (links to Admin pages they can't access). They also can access the Client Portal (`client_base.html`) for the same data in a different theme.

**Impact:** Users confused about which interface to use. Two codepaths to maintain. Inconsistent experience — "which is the real dashboard?"

**Mitigation:** Eliminate `admin_dashboard_client_manager.html`. Route client-scoped roles directly to Client Portal with elevated action buttons (Run Pipeline, etc).

---

### 3.5 Information Overload Risk — Owner Dashboard Creep

**Risk level: LOW**

Owner dashboard currently has: metrics bar + pipeline summary + topology + portfolio health + kill switches + run all + client cards + 4 side panels + run history. ~8 distinct information blocks, each with HTMX lazy-loading.

Not a crisis yet (Max built it for himself), but as more features ship, this becomes the "god dashboard" where everything gets added because "owner should see it."

**Mitigation:** Owner dashboard should be a triage tool: system health → alerts → quick actions. Deep-dive belongs on dedicated pages (Decision Center, Posting Dashboard, Topology, etc).

---

## 4. Proposed Architecture

### 4.1 Owner — "Ops Command Center"

**Primary question:** Is the system healthy? What broke? What needs manual intervention?

```
┌─────────────────────────────────────────────────────────┐
│ 🔴 ALERTS: 2 frozen avatars, 1 stale scrape (>12h)     │  ← New: aggregated alerts
├─────────────────────────────────────────────────────────┤
│ System: Worker ✓  Pipeline ✓  Posting ✓  DB ✓          │  ← Simplified pulse
├─────────────────────────────────────────────────────────┤
│ Today: Scraped 47 → Scored 12 → Generated 8 → Posted 3 │  ← Keep (proven useful)
├──────────────────────────────┬──────────────────────────┤
│ Client Cards (2/3 width)     │ Avatar Health            │
│ [per-client pipeline cards]  │ Schedule                 │
│                              │ Scrape Freshness         │
├──────────────────────────────┴──────────────────────────┤
│ Pipeline Controls + Run All                              │  ← Keep (emergency use)
├─────────────────────────────────────────────────────────┤
│ Topology (collapsible)                                   │  ← Keep but collapse by default
└─────────────────────────────────────────────────────────┘
```

**Removed:** Portfolio Health (→ Decision Center), AI Costs (→ dedicated page), Run History (→ Tasks page).

---

### 4.2 Partner — "Business Cockpit"

**Primary question:** Is the business growing? Which clients need attention? Where should I spend my time today?

```
┌─────────────────────────────────────────────────────────┐
│ MRR: $4,800  │  Active: 6  │  Trials: 3  │  Churn: 0   │  ← Business KPIs
├─────────────────────────────────────────────────────────┤
│ ⚠ ATTENTION: Trial "Acme" expires in 2d, "FooBar" 0    │  ← Prioritized actions
│   posts this week, 4 drafts pending your review         │
├─────────────────────────────────────────────────────────┤
│ CLIENT HEALTH TABLE                                      │
│ Name       │ Plan    │ Avatars │ Posted/wk │ Health │    │
│ XM Cyber   │ Growth  │ 4       │ 12        │ 🟢     │    │
│ NeuroYoga  │ Starter │ 2       │ 3         │ 🟡     │    │
│ Acme Corp  │ Trial   │ 1       │ 0         │ 🔴     │    │
├──────────────────────────────┬──────────────────────────┤
│ Trial Funnel                 │ Cost & Revenue            │
│ Active → Onboarded →         │ AI spend: $351/mo        │
│ First post → Converted       │ Revenue: $4,800/mo       │
│                              │ Margin: 93%              │
└──────────────────────────────┴──────────────────────────┘
```

**Removed:** Pipeline buttons, Topology, Backups, Worker status, Scrape freshness — all ops concerns.

**Key insight:** Partner dashboard = **sales & retention tool**, not ops tool.

---

### 4.3 Client (Paying) — "Campaign Control Center"

Keep current design (works well), minor improvements:

```
┌─────────────────────────────────────────────────────────┐
│ 🎯 12 comments posted this week (+3 vs last week)       │  ← Hero metric with trend
├─────────────────────────────────────────────────────────┤
│ 📥 4 drafts waiting for review → [Review Now]           │  ← Action CTA (keep)
├─────────────────────────────────────────────────────────┤
│ Quick Stats: 3 avatars │ 5 subreddits │ +47 karma/wk   │
├──────────────────────────────┬──────────────────────────┤
│ Momentum Feed                │ Navigation Tiles          │
│ (last 5-7 events)           │ Avatars, Schedule, etc.   │
├──────────────────────────────┴──────────────────────────┤
│ Karma Growth (30-day sparkline)                          │
└─────────────────────────────────────────────────────────┘
```

---

### 4.4 Client (Trial) — "Guided Onboarding"

**Primary question:** What's happening? When will I see results? Is this worth paying for?

```
┌─────────────────────────────────────────────────────────┐
│ PROGRESS: ━━━━━━━━━━━━━━━░░░░░  Step 4/6               │  ← Visual progress
│ ✓ Profile  ✓ Subreddits  ✓ Keywords  ⏳ Avatar warming  │
├─────────────────────────────────────────────────────────┤
│ 📍 WHAT'S HAPPENING NOW                                  │
│ Your avatar @TechInsider is building credibility in      │
│ r/sysadmin. First AI-generated comments expected in ~48h │
├─────────────────────────────────────────────────────────┤
│ 🎉 FIRST RESULT (appears when first draft generated)     │
│ "Your first AI comment is ready for review!" → [See it]  │
├─────────────────────────────────────────────────────────┤
│ ⏰ 12 days left in trial                                 │
│ [Upgrade Now — keep your avatars and karma]              │
├─────────────────────────────────────────────────────────┤
│ [Review Queue]  [Your Avatars]  [Subreddits]            │  ← Simplified nav (3 tiles)
└─────────────────────────────────────────────────────────┘
```

**Key difference:** No empty tiles for Strategy/Report/EPG/AI Visibility — they appear only when data exists.

---

## 5. Implementation Effort Estimate

| Change | Effort | Dependencies |
|--------|--------|-------------|
| Partner Business Cockpit | 2-3 days | Need MRR calculation logic (clients × plan price) |
| Owner Alert Bar | 1 day | Aggregate existing health checks |
| Trial Onboarding Experience | 2 days | Progress state already in onboarding flow |
| Remove Client Manager duplicate | 0.5 day | Redirect + elevated buttons in portal |
| Client Portal hero metric | 0.5 day | Query already exists |

**Total: ~6-7 days of focused work.**

---

## 6. Data Requirements

### For Partner Business Cockpit (new queries needed):

| Metric | Source | Exists? |
|--------|--------|---------|
| MRR | `clients.plan_type` × price table | Need price lookup |
| Trial count | `clients WHERE plan_type='trial' AND is_active` | ✓ Exists |
| Trial expiry | `clients.created_at + 14 days` | ✓ Computable |
| Posts per week per client | `comment_drafts WHERE status='posted' AND posted_at > 7d` | ✓ Exists |
| Client health score | Composite: has_active_avatars + posts_this_week > 0 + no_frozen | Need new service |
| AI cost per client | `ai_usage_log GROUP BY client_id` | ✓ Exists |
| Churn | `clients WHERE is_active=false AND deactivated recently` | Need `deactivated_at` field |

### For Alert Aggregation (new service needed):

```python
# app/services/alert_aggregation.py
def get_system_alerts(db) -> list[Alert]:
    """Collect all actionable alerts across the system."""
    alerts = []
    alerts += get_frozen_avatar_alerts(db)      # existing query
    alerts += get_stale_scrape_alerts(db)       # existing in freshness panel
    alerts += get_worker_offline_alert(db)      # existing heartbeat check
    alerts += get_expiring_trial_alerts(db)     # new: trials < 3 days
    alerts += get_zero_activity_alerts(db)      # new: clients with 0 posts in 7d
    alerts += get_kill_switch_alerts(db)        # existing: any kill switch ON
    return sorted(alerts, key=lambda a: a.severity, reverse=True)
```

---

## 7. Risks of This Redesign

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Partner dashboard data wrong (MRR miscalculated) | Medium | Tzvi makes bad decisions | Validate against manual spreadsheet first |
| Trial experience overpromises timeline | Medium | Client frustrated when avatar takes >48h | Use ranges ("24-72h"), not exact times |
| Removing client_manager view breaks workflow | Low | Staff confused temporarily | Announce + redirect with explanatory banner |
| Feature creep back to "god dashboard" | High | Owner dashboard re-bloats over time | Strict rule: new features → dedicated page, not dashboard |
| Alert fatigue | Medium | Alerts ignored if too many false positives | Start with 3-4 alert types only, add slowly |

---

## 8. Decision Points for Tzvi

1. **Do you actually review drafts?** If yes → keep "Pending Reviews" prominently. If no → replace with "Clients waiting for review" (delegate signal).

2. **What's your daily workflow?** Understanding when/how Tzvi checks the platform determines what belongs "above the fold" on his dashboard.

3. **MRR calculation** — do we use plan_type × list price, or actual billed amounts? (No Stripe yet, so list price for now.)

4. **Client health definition** — what makes a client "red"? Proposed: 0 posts in 7 days OR all avatars frozen OR trial expired. Confirm.

5. **Priority order** — which dashboard first? Recommendation: Partner (highest business impact) → Trial (highest conversion impact) → Owner alerts (ops quality) → Client Manager removal (cleanup).

---

## 9. Success Metrics

| Dashboard | Metric | Target |
|-----------|--------|--------|
| Partner | Tzvi can answer "how's the business" without asking Max | Within 1 week of deploy |
| Trial | Trial-to-paid conversion rate | Track before/after (baseline needed) |
| Owner | Time to discover ops issue | < 30 seconds (alert visible on load) |
| Client | Portal engagement (return visits) | Measure via activity_events |

---

## 10. Next Steps

- [ ] Tzvi reviews this brief + answers Decision Points (Section 8)
- [ ] Agree on priority order
- [ ] Max implements Partner dashboard first (2-3 days)
- [ ] Ship, get Tzvi feedback, iterate
- [ ] Then Trial experience (2 days)
- [ ] Then Owner alert bar (1 day)
