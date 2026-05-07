# Product Brief: Dashboard Pipeline Visibility — Drill-down & Timeline

**Date:** May 7, 2026  
**Author:** Max (Tech)  
**For:** Product Analyst  
**Priority:** Medium (not blocking E2E test, but critical for daily ops transparency)

---

## Problem Statement

The admin dashboard (`/admin/`) has two elements showing "what's happening" in the pipeline:

1. **Top Metrics Bar** — shows "Next Scheduled Run: in 1h 19m" (single line, no context)
2. **System Topology** — 24-hour heatmap grid (shows activity at 06:00, but unclear what exactly happened)

**What the operator cannot understand today:**
- What specifically happened at 06:00? (avatar phase evaluation? scrape? scoring?)
- How many threads were processed? Were there errors?
- What exactly is scheduled in 1h 19m? (only shows label "Morning pipeline" — not enough)
- What is the current pipeline status? (idle? in progress? completed with errors?)
- Chronology: what happened → what's happening now → what's coming next

---

## Current Behavior

### Top Metrics Bar (4 cards)

| Card | Shows | Missing |
|------|-------|---------|
| Pending Reviews | Count (e.g., "8") + "action needed" badge | Which clients? How old are the oldest drafts? |
| Active Clients | Count (e.g., "2") | Which ones? Last activity per client? |
| Active Avatars | Count (e.g., "5") | Which ones? Phase? Reddit status? |
| Next Scheduled Run | "in 1h 41m" + label | Full schedule? What ran last? Result? |

### System Topology (heatmap)

- 9 nodes × 24 hours grid
- Cell color = event count (green) or error count (red) per hour
- Hover tooltip: "X events, Y errors" — no details
- Forecast point (pulsing dot) — when next run is expected
- **No click interaction, no drill-down, no event list**

### Scheduled Tasks (in code, not visible to user)

| Key | Label | Cron |
|-----|-------|------|
| evaluate-avatar-phases-daily | Evaluate avatar warming phases | 06:00 UTC |
| ai-pipeline-morning | Morning pipeline (score + generate) | 08:00 UTC |
| hobby-pipeline-daily | Hobby pipeline (all avatars) | 10:00 UTC |
| ai-pipeline-afternoon | Afternoon pipeline (score + generate) | 14:00 UTC |
| karma-tracking-4h | Karma tracking (all avatars) | Every 4h at :15 |
| avatar-health-check | Avatar health check | Every 12h at :30 |

---

## Desired Outcome

The operator (Tzvi) should be able to answer these questions in under 5 seconds:

1. "What just happened?" — see last completed task with result
2. "Is anything running right now?" — see current pipeline state
3. "What's coming next?" — see upcoming schedule with context
4. "Why is this number high/low?" — drill into any metric card
5. "What happened at hour X on node Y?" — click topology cell for details

---

## Proposed Features

### Feature 1: Metric Card Drill-down

**Interaction:** Click on any of the 4 top metric cards → expand/popup with details.

| Card | Drill-down Content |
|------|-------------------|
| Pending Reviews | Last 5 pending drafts: client name, avatar, thread title, age (e.g., "3h ago") |
| Active Clients | List of active clients: name, last pipeline activity timestamp, today's thread count |
| Active Avatars | List of active avatars: username, phase (1/2/3), reddit_status, last activity |
| Next Scheduled Run | Full schedule table: all 6 tasks, next_at time, last_run time, last result (success/error) |

**Open questions:**
- Popup/modal vs. inline expand vs. slide-out panel?
- Should clicking navigate to a detail page or stay on dashboard?

### Feature 2: Pipeline Timeline (Chronology)

A unified "past → present → future" view showing:

**Past (last 2–4 hours):**
- Last 5–10 completed tasks
- Each entry: task type icon, timestamp, duration, result (success/error/skipped)
- Expandable: click to see details (posts_found, threads_scored, drafts_generated, errors)

**Present:**
- Current pipeline state: IDLE / RUNNING (which task) / ERROR (last failure)
- If running: progress indicator, started_at, estimated completion

**Future (next 2–4 hours):**
- Next 3–5 scheduled tasks
- Each entry: task type, scheduled time, countdown ("in 1h 19m")
- Visual distinction from past entries (dimmed, dashed border, or different column)

**Open questions:**
- Horizontal timeline (left=past, right=future) or vertical list?
- Where to place: replace current "Next Scheduled Run" card? New section? Sidebar?
- How much history to show by default?

### Feature 3: Topology Cell Detail

**Interaction:** Click on any heatmap cell → show event list for that node+hour.

**Content:**
- List of activity_events for that node in that hour
- Each event: timestamp (HH:MM:SS), message, key metadata
- Error events highlighted in red
- Link to full Run History page with pre-applied filter (node + time range)

**Open questions:**
- Popup positioned near the cell? Or panel below the grid?
- Should it auto-close when clicking another cell?

---

## Data Availability (already in the system)

| Data | Source | Records |
|------|--------|---------|
| Pipeline events | `activity_events` table | 613 rows |
| Scrape results | `scrape_log` table | 27 rows |
| Schedule definition | `operations_dashboard.py` (code) | 6 entries |
| Next-run calculation | Celery crontab `.remaining_estimate()` | Real-time |
| Last-run results | `activity_events` filtered by type | Available |
| Error details | `activity_events.metadata` JSONB | Available |

**No new data collection needed.** All information exists — it just needs to be surfaced in the UI.

---

## Technical Constraints

- **HTMX** — inline expand and partial loads are natural; no SPA framework needed
- **Polling** — topology panel already refreshes every 60s; no WebSocket available
- **Dark theme** — all new UI must use existing `bg-dark-steel`, `border-slate-700` palette
- **Mobile** — admin panel is desktop-first, but should not break on tablet
- **Performance** — dashboard loads in <500ms today; drill-downs should be lazy-loaded (HTMX partials)

---

## Questions for the Product Analyst

1. **Drill-down pattern:** Popup/modal vs. inline expand vs. slide-out panel? What's most natural for an ops dashboard?
2. **Timeline placement:** Separate section on dashboard? Replace "Next Scheduled Run" card with a richer widget? New page?
3. **Visual language:** How to distinguish "completed" vs. "scheduled" vs. "in progress" vs. "failed"?
4. **Alert behavior:** Should failed tasks trigger a visual/audio alert? Toast notification? Badge on sidebar?
5. **User context:** Tzvi (business) vs. Max (tech) — different detail levels needed? Or one view for both?
6. **Scope:** Should this be a single "Pipeline Control Center" page, or distributed across the existing dashboard?
7. **Interaction depth:** How many clicks to get from "something looks wrong" to "here's the exact error"?

---

## Success Criteria

- Operator can identify "what happened in the last pipeline run" without scrolling or navigating
- Operator can see the full schedule and understand when each task fires
- Operator can investigate errors by clicking, not by reading logs
- New operators (Tzvi) can understand the system state within 30 seconds of opening the dashboard

---

## References

- Current dashboard: `reddit_saas/app/templates/admin_dashboard.html`
- Topology panel: `reddit_saas/app/templates/partials/topology_panel.html`
- Schedule logic: `reddit_saas/app/services/operations_dashboard.py`
- Activity events model: `reddit_saas/app/models/activity_event.py`
- System Topology spec: `.kiro/specs/system-topology-timeline/`
- Load dynamics doc: `docs/load_dynamics_aws_costs.md` (node descriptions)
