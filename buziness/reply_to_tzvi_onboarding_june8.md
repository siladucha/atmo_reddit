# Reply to Tzvi — Client Onboarding & Demo Flow

**From:** Max  
**Date:** June 8, 2026  
**Re:** Your email about onboarding UX and demo experience

---

Hi Tzvi,

Good timing on this — I've gone through the UX/UI doc (v2 and the full dev spec v3) again with fresh eyes. Let me share my thoughts on both topics.

---

## 1. Client Onboarding — My Assessment

The 6-step wizard in the UX spec is solid and well-thought-out. I agree with the principle: it should feel like a strategy session, not a form. Here's where I land on the "efficient vs. frictionless" balance:

### What I'd Keep As-Is (High Value, Low Friction)
- **Step 1 (Company URL → auto-build profile)** — this IS the wow moment. Worth the investment.
- **Step 2 (Problem/Competitors)** — conversational prompts, not form fields. Quick to answer.
- **Step 3 (ICP)** — essential for AI quality. Cap at 2 ICPs, toggling B2B/B2C is smart.
- **Step 5 (Keywords + Subreddits)** — AI pre-suggests based on previous answers. Client confirms.
- **Step 6 (Review + Quality Gate)** — non-negotiable. Thin briefs produce bad output.

### What I'd Simplify (Risk of Friction)
- **Step 4 (Tone Calibration Loop)** — the concept is right (rate 5 sample sentences), but forcing 3+ sentences rated 4+ before proceeding can stall onboarding for days. My suggestion:

  **Proposed fix:** Make the tone loop a "soft gate" — if they rate 3+ sentences as 4-5 stars, great, proceed. If not, let them proceed with a note: "We'll refine the voice in your first review cycle." The self-learning loop will pick it up from their edits anyway. Reserve the hard block for truly empty/thin briefs only.

- **Document upload** — keep it optional and prominent ("clients who upload a tone guide produce 40% better output"), but never block on it. Many prospects won't have a formal ToV doc ready during onboarding.

### What I'd Add
- **Estimated time per step** — already in the spec, but make it VERY visible. "Step 4 of 6 — ~4 min" reduces abandonment.
- **"Save & Continue Later"** — onboarding state persisted server-side. If a prospect starts on a Zoom call with you and finishes later, nothing is lost.
- **Post-onboarding "Day 1 Report"** — per the business brief. This is a real deliverable that proves instant value even before avatars are active.

---

## 2. The Demo / Free Trial Problem

You're right — prospects who want to pitch internally have nothing to show. Toffu.ai's advantage is that someone can create a free account and play with it in 5 minutes. Our product requires real avatars + time to demonstrate value. That's a structural challenge.

### My Recommendation: Interactive Demo Mode (Not a Full Free Trial)

The business brief describes a 14-day intelligence trial (no posting, intelligence layer only). That's the right direction. But I'd go even further for the demo scenario:

**Option A — "Instant Demo" (recommended for Zoom demos + internal pitching)**

A pre-built demo workspace with real data from an anonymized client (or XM Cyber with permission). The prospect sees:
- Real threads scored with engage/monitor/skip tags
- Real AI-generated comment drafts (they can browse but not approve)
- Real karma graphs and phase progression from months of operation
- A "Day 1 Reddit Landscape Report" generated for THEIR brand (URL input → instant report)

**Implementation effort:** 1-2 weeks. It's mostly a read-only view of existing data with a branded wrapper.

**Why this works:** The prospect can show their CMO: "Look — here's what the platform shows. These are real Reddit threads where our brand should be present. This is what the AI-generated comments look like. This is phase progression over 3 months." It's tangible, visual, and shareable.

**Option B — "14-Day Intelligence Trial" (per the business brief)**

Full version of what's described in the brief:
- Work email required (no gmail)
- They complete onboarding wizard → see their real subreddits scored
- Thread monitoring live, AI drafts generated (read-only, 1 edit/day)
- Day 1 Landscape Report auto-generated
- No posting, no avatar allocation
- At end of trial: "Here are the 47 threads your brand missed this month. Ready to start?"

**Implementation effort:** 3-4 weeks. Needs the self-serve onboarding wizard + a trial-mode RBAC role + throttled AI generation.

### My Suggestion on Sequencing

1. **NOW (this week):** I can build a static demo workspace with seed data — enough for your Zoom demos. A URL you can share: "Log in with demo@ramp.com, see what clients see." Takes 2-3 days.

2. **NEXT (weeks 2-3):** Self-serve onboarding wizard (the 6-step flow). This is needed for both the paid flow AND the trial flow anyway.

3. **THEN (weeks 4-5):** Wire up the 14-day trial mode (intelligence-only, no posting). This requires the wizard first.

---

## 3. The Sweet Spot (My Honest Take)

The onboarding flow in the spec is designed for a $799+/mo Growth client who will spend 25 minutes on an intake session because they've already committed budget. That's perfect for managed clients.

For prospects who are EVALUATING — they need something faster. The "Instant Demo" (Option A) lets them see the value in under 2 minutes. The "14-Day Trial" lets them experience it with their own data. Both are on the roadmap.

**Priority order I'd recommend:**
1. Demo workspace (for your Zoom calls) — this week
2. Onboarding wizard for paid clients — weeks 2-3
3. 14-day trial mode — weeks 4-5

This way you have something to show TODAY, and we build the self-serve funnel in parallel.

---

## 4. Regarding the UX Spec Specifically

A few notes for alignment:

- **Web scraping for auto-build (Step 1):** This is the "wow moment" and worth building. I'll use a lightweight approach (fetch homepage + LinkedIn API) rather than full browser automation. Gets us 80% of the value at 20% of the complexity.

- **Tone Calibration Loop:** Keeping it, but as a soft gate (not a hard block). The self-learning loop handles voice refinement organically through edits.

- **Post-activation 24-48h gap:** This is real and important. The confirmation screen needs to set expectations clearly. Email follow-up when avatars go live.

- **Quality Gate on Step 6:** This stays as a hard block. No thin briefs make it through. This protects our output quality and therefore our reputation.

---

Let me know which approach you prefer on the demo question and I'll start building this week.

Max
