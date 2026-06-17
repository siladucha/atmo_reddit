# NeuroYoga (ATMO) — Client Setup Report

**Date:** June 17, 2026
**Client ID:** `721693db-cedc-4256-979d-823150894783`
**Admin URL:** https://gorampit.com/admin/clients/721693db-cedc-4256-979d-823150894783
**Portal URL:** https://gorampit.com/clients/721693db-cedc-4256-979d-823150894783/home

---

## What Was Done

### 1. Client Fields Populated

| Field | Value | Why |
|-------|-------|-----|
| `industry` | "Health & Wellness / NeuroTech" | Required for AI persona routing and subreddit suggestions |
| `brand_domain` | "atmo.ai" | Used in onboarding URL scrape and brand detection |
| `onboarding_completed_at` | 2026-05-15 | Marks client as fully onboarded → portal shows full UI, no wizard redirect |
| `current_onboarding_step` | 6 | Wizard complete |
| `brand_guardrails` | See below | Safety rules for AI generation — prevents off-brand content |

**Brand Guardrails (JSONB):**
```json
{
  "never_associate": [
    "pseudoscience",
    "medical claims",
    "cure promises",
    "anti-medicine",
    "religious practices"
  ],
  "restricted_claims": "Cannot claim to cure anxiety, depression, or any medical condition. Cannot make specific health outcome promises. Always position as complementary practice, not replacement for medical care.",
  "style_inspiration": "Andrew Huberman's podcast style — evidence-based, accessible, practical. Mix of science and personal experience."
}
```

### 2. Avatar Persona Names Set

| Reddit Username | Display Name | Persona Bio | Why |
|----------------|-------------|-------------|-----|
| `Hot-Thought2408` | **Alex** | "Breathing coach & biohacker. 5 years of daily breathwork practice, HRV tracking enthusiast." | Primary ATMO avatar — wellness/breathing niche. Clients see "Alex" not the username. |
| `Flaky_Finder_13` | **Dan** | "Senior QA automation engineer. Metalhead. Runs in the mornings, breathes on purpose." | Cross-niche avatar — hobby engagement in fitness/wellness from tech angle. |

### 3. Already Configured (Pre-Existing)

These fields were already populated correctly:

| Field | Status |
|-------|--------|
| `client_name` | NeuroYoga ✅ |
| `brand_name` | ATMO ✅ |
| `company_profile` | Full description of NeuroYoga app ✅ |
| `company_worldview` | Stress management philosophy ✅ |
| `company_problem` | People overwhelmed but no time for long sessions ✅ |
| `competitive_landscape` | Calm, Headspace, Wim Hof comparison ✅ |
| `brand_voice` | Warm, evidence-based, anti-hype ✅ |
| `icp_profiles` | Stressed professionals, biohackers, yoga practitioners ✅ |
| `keywords` | 5 high (breathing, acupressure, HRV...) + 4 medium + 4 low ✅ |
| `plan_type` | starter (3 avatars, 60 actions/mo) ✅ |
| Subreddits | 17 assignments (mix professional + hobby) ✅ |

---

## Client Portal Experience Now

When JJ (`jekorn12@gmail.com`, role: `client_manager`) logs in:

1. **Home** — Metrics + Momentum feed + Navigation tiles. No trial banner.
2. **Review Queue** — Pending/Approved/Posted tabs with batch approve + regenerate.
3. **Avatars** — Card layout showing "Alex" and "Dan" with persona bios, karma tier (Newcomer), phase badges. No reddit usernames visible.
4. **Report** — Engagement funnel + subreddit performance + top comments + Download Report button.
5. **Landscape** — Competitive presence analysis with scanning state (auto-refreshes).
6. **Settings** — Keywords (9 total), Subreddits (11 active), Brand Guardrails (5 never-associate topics), Voice Feedback.
7. **EPG / Schedule** — Daily publishing program per avatar.
8. **Strategy** — AI strategy documents per avatar.

---

## What's NOT Configured (Intentionally)

| Item | Reason |
|------|--------|
| `max_comments_per_month` | NULL = use plan default (60 for starter). No need to override. |
| `return_weights` | Using default EPG 2.0 weights. Can tune later. |
| `geo_monitoring_enabled` | False — GEO/AEO not needed for wellness niche yet. |
| `autopilot_enabled` | False — human review required (draft_approval workflow). |

---

## Verification Results

| Check | Result |
|-------|--------|
| Client portal home → 200 | ✅ |
| Avatars page shows "Alex", "Dan" | ✅ |
| No reddit username leak to client | ✅ |
| Karma tier shown (Newcomer) | ✅ |
| Persona bios visible | ✅ |
| Settings shows guardrails | ✅ |
| No trial banner (paying client) | ✅ |
| Momentum feed present | ✅ |
| Report page with Download button | ✅ |
| All 14 portal pages load without errors | ✅ |
