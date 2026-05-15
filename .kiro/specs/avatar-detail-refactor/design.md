# Design — Avatar Detail Refactor

## Tab Mapping (12 → 7)

| New Tab (id) | Source Panels | Notes |
|---|---|---|
| `overview` | overview + phase (summary) + presence (summary) | Phase and Presence collapsed to summary cards with "View details" linking to anchor sections in same panel |
| `profile-safety` | profile + safety | Profile first (who), then Safety (alerts) |
| `performance` | performance + analytics | Karma chart toggles daily/weekly (default weekly) |
| `billing` | billing | Unchanged |
| `content` | drafts + pipeline | Long lists wrapped in `<details>` |
| `strategy` | strategy | Unchanged |
| `actions` | actions | Export moves here from header |

## Legacy ID Redirects (Requirement 1.8 / 9)

```
safety    → profile-safety
profile   → profile-safety
phase     → overview#phase-details
presence  → overview#presence-details
drafts    → content
pipeline  → content#pipeline-details
analytics → performance
performance → performance
billing, strategy, actions, overview → unchanged
```

Implemented client-side in the tab-init script — no server changes needed.

## HTMX Trigger Policy

- **Overview tab**: `hx-trigger="load"` — content above the fold, fetched immediately
- **All other tabs**: `hx-trigger="revealed once"` — content fetched on first tab activation, never re-fetched on scroll
- **Per-partial refresh buttons** (e.g., shadowban "Check Health"): unchanged — these trigger distinct backend operations, not just re-fetches
- **Removed**: every bare `hx-trigger="revealed"` (currently at lines 812, 823, 1297, 1312, 1322, 1334)

## Critical Signal Header

New row between avatar name and tab bar:

```html
<div class="flex flex-wrap gap-2 mb-3">
  {# shadowban badge — clickable to profile-safety #}
  {# freeze badge — clickable to profile-safety #}
  {# cqs badge — clickable to profile-safety #}
  {# phase badge — clickable to overview #phase-details #}
</div>
```

Each badge is a `<button>` that invokes `activateTab(targetTab, anchor)`.

## Tab Activation JS Contract

```js
// Public API on window.AvatarDetailTabs
activateTab(tabId, anchorId?)  // switches tab, optional scroll-to-anchor
getActiveTab()                  // returns current tab id
on('tab-activated', handler)    // event subscription
```

Hash sync:
- Tab click → `history.replaceState(null, '', '#tab=' + tabId)`
- Page load with hash → parse, run legacy-id redirect, activate
- Page load without hash → default `overview`

## Karma Chart Toggle (Requirement 6)

The Performance tab's karma chart partial already renders 30 daily columns. The toggle is client-side only:

```js
// Pseudo-code
function renderKarmaChart(granularity) {
  const data = granularity === 'weekly' 
    ? aggregateToWeeks(dailyData)
    : dailyData;
  // re-render bars
  localStorage.setItem('avatarDetail:karmaGranularity', granularity);
}
```

Backend keeps returning daily data; client decides display. No new endpoint.

## Collapsible Comment Lists

```jinja
{% if professional_comments|length > 5 %}
<details>
  <summary>Professional Comments ({{ professional_comments|length }}) — {{ approved_count }} approved, {{ pending_count }} pending</summary>
  {# render all cards except the first #}
</details>
{% else %}
{# render expanded #}
{% endif %}
```

First card always rendered outside `<details>` so the user sees a preview.

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Overview tab becomes too long with Phase summary card added | Phase summary is a 3-line card (current phase, days in phase, progress %) — full content stays anchored further down the panel, not in the summary |
| Safety alerts get buried inside merged Profile & Safety tab | Critical_Signal badge row in header surfaces them regardless of tab — covered by Requirement 2 |
| Existing bookmarks break | Legacy ID redirect (Requirement 1.8 / 9) handles `?tab=` and `#tab=` |
| Tab state JS rewrite breaks listeners elsewhere | Public event contract `avatarDetail:tab-activated` preserved; existing handlers continue to receive the event with the new tab id |
| HTMX `revealed` → `revealed once` change masks a legitimate reason for re-fetch | Audit each of the 6 sites before flipping; if any of them currently rely on re-fetch (e.g., to pick up new data after a write), replace with an explicit manual refresh button instead of silent re-loading |

## File Touch List

```
reddit_saas/app/templates/admin_avatar_detail.html   — main work
.kiro/specs/avatar-detail-refactor/tasks.md           — to write next
```

No route handler changes. No new partials. No CSS file changes beyond the existing Tailwind utility classes.

## Resolved Open Questions

### Q1 — Phase summary card content (Overview)

**Resolution:** The card answers "what should this avatar do *today*", not just "what phase is it in". The card surfaces three operational signals derived from phase + last-24h activity + nearest promotion gate + active blockers:

1. **Today's action** — a single imperative line generated server-side:
   - `Post 1 hobby comment in r/<best-subreddit>` (Phase 1, quota unused)
   - `Quota used (1/1 hobby today) — wait until 00:00 UTC` (Phase 1, quota used)
   - `Generate 2 more professional drafts for review` (Phase 2/3, drafts below daily target)
   - `Eligible for promotion to Phase {n+1} — review evidence` (gates met)
   - `Blocked: shadowbanned — run health check, do not post` (overrides everything else)
   - `Blocked: frozen by ops — see Profile & Safety` (overrides everything else)
   - `Mentor — no pipeline action expected today` (Phase 0)

2. **Daily quota status** — current/limit for the most relevant counter for the phase:
   - Phase 1: hobby comments today (`0/1`)
   - Phase 2/3: professional drafts today + hobby comments today
   - Format: small horizontal pill with current/limit + green/amber dot

3. **Nearest promotion gate** — the single closest unmet requirement from `health.phase_progress`, rendered as one progress bar + label:
   - `Subreddit diversity: 3/5 — needs 2 more` (most actionable gate first if multiple are open)
   - `All gates met — eligible for promotion` (when `phase_eligible_for_next` is true)
   - Phase 3 → omit this signal entirely (no next phase)

**Why these three:** they answer respectively (a) what to do this hour, (b) am I done for the day, (c) what unblocks the next phase. A marketer can glance at the card and either close it (nothing pending) or click "View details" to drill into the full Phase Progress section anchored further down the Overview panel.

**Data source:** all three signals are derived from existing `health` and `avatar` template context — no new backend endpoint. A small helper (e.g., `avatar_today_recommendation(avatar, health)`) computes the imperative string and runs in the route handler.

### Q2 — Critical Signal badge color for Phase 1 (and beyond)

**Resolution:** The phase number itself is **informational (blue)**. The *status* next to the phase number carries the actionable color. This separates "where is this avatar in lifecycle" (info) from "is anything wrong" (alert).

| State | Color | When |
|---|---|---|
| `Phase 1 · On track` | green | Phase 1, days-in-phase ≤ expected_duration, no health blocker |
| `Phase 1 · Day {n}/{expected}` | neutral (blue) | Phase 1, days-in-phase within first 50% of expected_duration |
| `Phase 1 · Stalled {n}d` | amber | Phase 1, days-in-phase > 1.5× expected_duration AND not eligible for promotion |
| `Phase 1 · Blocked` | red | Shadowban detected OR freeze active OR CQS=lowest |
| `Mentor` | purple | Phase 0 (unchanged from current design) |
| `Phase 2 · …` / `Phase 3 · …` | same scheme, phase number stays blue/neutral, status drives color | |

**Rationale for marketer ergonomics:**

- A marketer scanning a list of 30 avatars needs to instantly find the *abnormal* ones. If Phase 1 itself is colored amber or yellow (just because it's "warming"), every brand-new avatar lights up amber on day one — alert fatigue.
- Conversely, blue alone ("informational") doesn't tell the marketer whether this Phase 1 avatar is progressing or stuck. The status suffix fixes that.
- Red is reserved exclusively for "stop and fix now" — shadowban, freeze, or CQS=lowest. Phase 1 itself is never red just for being Phase 1.
- The same scheme generalizes cleanly to Phase 2 and Phase 3, so the marketer learns one rule, not three.

**Expected_duration values** (used to decide On track vs Stalled): Phase 1 = 14 days, Phase 2 = 30 days, Phase 3 = no cap. These come from the warming-phases spec; confirm against `.kiro/specs/avatar-warming-phases/` before coding the helper.

### Q3 — Export action specifics

**Verified:** the Export dropdown in the page header (`admin_base.html` `export_button` block, used on this page) and the Export & Reports card in the Actions tab (`admin_avatar_detail.html` lines 1365–1392) point to **the exact same three endpoints**:

| Endpoint | Format | Label |
|---|---|---|
| `/export/avatars/{id}/report.md` | Markdown | Client Report (.md) |
| `/export/avatars/{id}/report` | JSON | Full Data (.json) |
| `/export/avatars/{id}` | JSON | Raw JSON |

The two locations are pixel-identical in function — no info is lost by removing the header dropdown. **Decision:** keep the Actions-tab card as the canonical Export surface; remove the header dropdown on this page only (other admin pages that use `export_button` block stay untouched).

**Implementation note:** the `{% block export_button %}` override is defined inside this template (lines 14-77) — removing it from `admin_avatar_detail.html` falls back to the parent template's empty block, no other page is affected.

## Remaining Open Questions

None for this round. Spec is ready for tasks.md and implementation.
