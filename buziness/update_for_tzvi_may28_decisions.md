# RAMP — Status Update & Decisions Needed

**From:** Max  
**To:** Tzvi  
**Date:** May 28, 2026

---

## Table of Contents

0. [Strategic Direction: AI-Native Expert](#0-strategic-direction-ai-native-expert)
1. [Proxy Posting — Effort & ETA](#1-proxy-posting--effort--eta)
2. [Mobile/PWA Posting — Effort & ETA](#2-mobilepwa-posting--effort--eta)
3. [Pitch for Client Conversations](#3-pitch-for-client-conversations)
4. [Roadmap — Updated for Client Presentations](#4-roadmap--updated-for-client-presentations)
5. [Hotfixes / Features + Demo Readiness](#5-hotfixes--features--demo-readiness)
6. [Decision Matrix — What Do We Build First?](#6-decision-matrix--what-do-we-build-first)
7. [What I Need From You](#what-i-need-from-you)

---

## Summary

Platform status, posting infrastructure options, roadmap alignment, and the AI-Native Expert strategy. Six items that need your input.

---

## 0. Strategic Direction: AI-Native Expert

I've added this to the platform architecture as the long-term goal for every avatar:

**The path:** Avatar warming → credibility → brand integration → **AI-Native Expert** — where the avatar's content becomes authoritative enough that ChatGPT, Gemini, and Perplexity cite it as a source when users ask about the client's domain.

**Why this matters for clients:**
- Reddit is the #1 source LLMs use for "real user opinions"
- An avatar with high karma + niche authority + structured content = gets indexed as an expert
- Client's brand gets associated with problem-solution patterns in LLM training data
- This is AEO/GEO — the next frontier after SEO

**What we build toward:**
- Topic authority scoring (per-avatar, per-niche)
- LLM-friendly content formats (first-hand data markers, structured comparisons)
- Citability scoring (which comments are likely to be picked up by AI search)
- Entity linking (brand ↔ problem-solution associations)

**Timeline:** This is a Phase 2-3 feature. Right now it shapes HOW we generate content (quality, structure, niche depth) — not a separate module yet. The spec (`.kiro/specs/ai-native-expert-warming/`) is next on my design queue.

**Honest caveat:** AI citation tracking is not yet fully measurable. There's no reliable API to check "did ChatGPT cite this Reddit comment." Tools like Profound/Otterly/Brandlight are emerging but immature. What IS measurable today: authority signals (karma quality, thread depth, saves, cross-references) that correlate with LLM indexing. We build toward citability — and measure what we can now.

**Reference:** Watch [How to Get Mentioned by AI Chatbots in 2026 (GEO Playbook + Spotlight Demo)](https://www.youtube.com/watch?v=HTooZdm5-3c) — covers the exact playbook we're implementing: structured content, first-hand data markers, niche authority signals. This is the market direction. GEO/AEO is becoming a recognized discipline (Frase, Searchbloom MERIT framework, Inc. magazine coverage). We're positioning RAMP as the Reddit execution layer for this strategy.

**Homework for our next meeting:** Please watch that video before we talk. I want us to discuss:
- How do we pitch this to XM Cyber and future clients? (it's a stronger story than "we post comments")
- Which content formats from the GEO playbook map to what our avatars already produce?
- Should "AI-Native Expert" be a separate pricing tier or included in Growth/Scale plans?
- How do we measure progress toward citability without a direct API? (proxy metrics: karma quality, thread depth, saves, brand mention frequency in AI answers when we manually check)

**For client conversations:** "Your avatars don't just post on Reddit — they become recognized experts in your domain. When someone asks ChatGPT about [your category], the answer is built from conversations your avatars participated in."

---

## 1. Proxy Posting — Effort & ETA

**What it is:** System posts approved comments automatically. No human at posting stage.

**Existing assets:**
- Full spec written (requirements + design + implementation plan)
- OAuth per-avatar auth spec ready
- EPG (daily publishing program) already built and integrated
- Safety gates, kill switches, audit logging — all exist
- Timing engine designed (jitter, active hours, peak bias)

**What Ori had:** Nothing. His n8n workflows generated drafts and tracked them in Airtable, but actual posting was always manual copy-paste. No proxy infrastructure, no OAuth per-avatar. We build from scratch — on a much stronger foundation.

**Effort:**

| Component | Days |
|-----------|------|
| OAuth per-avatar (token storage, refresh, PRAW factory) | 3 |
| Proxy routing + encryption | 2 |
| Safety gates service | 1 |
| Timing engine | 1 |
| Core posting service + Celery tasks | 3 |
| Admin UI (proxy config, posting logs, dashboard) | 2 |
| Testing + hardening | 2 |
| **Total** | **~2 weeks** |

**ETA:** First automated post in production ~2 weeks from start.

**What I need:**
- Budget: $12.50/mo for 5 avatars (residential proxies)
- 2-3 Reddit accounts for OAuth app registration
- Comfort with "human approves, system posts" framing

---

## 2. Mobile/PWA Posting — Effort & ETA

**What it is:** Lightweight web app for posting team (Fredo + future hires). They see approved comments, copy text, open Reddit, paste, confirm done.

**Current state:** Fredo is already posting manually from the admin panel. The PWA would streamline this into a mobile-friendly flow with push notifications and posting speed tracking.

**Effort:**

| Component | Days |
|-----------|------|
| `avatar_assignments` table + admin UI | 2 |
| Backend API (queue, confirm, skip, stats) | 3 |
| PWA frontend (queue, detail, copy+open flow) | 4-5 |
| Web Push notifications on approval | 2 |
| Posting team admin page + analytics | 2 |
| Testing + polish | 2 |
| **Total** | **~3 weeks** |

**ETA:** First worker posting via PWA ~3 weeks from start.

**What I need:**
- Is Fredo enough for now, or do we need more posters?
- Payment model for future posters: per-post or monthly?
- Who manages quality control?

---

## 3. Pitch for Client Conversations

### Posting Infrastructure (for prospects)

> "Your content goes through a human approval workflow, then our managed posting infrastructure delivers it at optimal times. Full audit trail, instant pause capability, zero operational overhead on your side."

### AI-Native Expert (for premium positioning)

> "We don't just post on Reddit — we build recognized domain experts. Your avatars become the voices that AI search engines cite when users ask about your category. This is AEO: when someone asks ChatGPT about [exposure management / breathwork / whatever], the answer references conversations your experts participated in."

### Combined value prop

> "Phase 1-2: Build credibility. Phase 3: Integrate your brand. Expert tier: Your avatars become the sources AI chatbots cite. The longer RAMP runs, the harder it is to replicate what you've built."

---

## 4. Roadmap — Updated for Client Presentations

Marketing roadmap page needs these updates:

| Current (outdated) | Should say |
|-------------------|-----------|
| "Telegram Posting Bot" everywhere | "Managed Posting Infrastructure" |
| Phase 1.5 "AI Ops Assistant" | Move to Phase 3 (not client-facing priority) |
| No mention of AI-Native Expert | Add as Phase 2 feature: "AI Search Authority (AEO/GEO)" |
| Phase transition triggers reference Telegram | Change to "Posting infrastructure live" |

**New roadmap narrative for clients:**

```
Phase 0 (Done): Core AI pipeline — scraping, scoring, generation, review
Phase 1 (Now): Client portal + posting infrastructure + first pilots
Phase 2 (Jun-Jul): AI-Native Expert system + outcome tracking + scale prep
Phase 3 (Aug-Oct): Agency multi-tenant + white-label + self-service
Phase 4 (Nov+): LinkedIn expansion + advanced intelligence
```

I'll update the marketing roadmap page today (1-2 hours). Then you have a clean URL to share.

---

## 5. Hotfixes / Features + Demo Readiness

### Critical for Next Demo

| Item | Effort | Impact |
|------|--------|--------|
| Domain + SSL | 2-3h (once you buy domain) | Professional URL, shareable |
| Ensure XM Cyber demo data is fresh | 1h (run pipeline) | Real numbers |
| Fix any broken client portal pages | 1-2h audit | Demo doesn't crash |

### High-Value Quick Wins (1-2 days each)

| Item | Effort | Why |
|------|--------|-----|
| Nested comment replies | 2 days | Removes "only top-level" limitation |
| Comment karma tracking (check score after 24h) | 1 day | Shows ROI in numbers |
| Client portal — hide internal fields | 0.5 day | Security + professionalism |

### Can Wait

| Item | Why |
|------|-----|
| Stripe billing | Manual invoicing works for first 5 clients |
| Self-serve onboarding | We onboard manually during pilot |
| Cross-avatar deduplication | Not a problem at 5-10 avatars |
| AI-Native Expert scoring | Shapes content quality now, formal module later |

---

## 6. Decision Matrix — What Do We Build First?

| Option | Timeline | Unblocks |
|--------|----------|----------|
| **A: Proxy posting** | 2 weeks | Removes ops bottleneck, enables scale, Fredo focuses on warming only |
| **B: PWA for Fredo** | 3 weeks | Streamlines manual posting, push notifications, speed tracking |
| **C: Both (shared backend)** | 4 weeks | Maximum flexibility, per-avatar mode toggle |
| **D: Client portal polish** | 1 week | Better demos, but posting bottleneck remains |
| **E: AI-Native Expert spec** | 3-4 days (design only) | Shapes content strategy, no code yet |

**My recommendation:** A first (proxy posting removes the bottleneck), then D (polish for demos), then E (spec for AI-Native Expert to guide content quality). Fredo continues manual posting during the 2-week build.

---

## What I Need From You

1. **Posting priority:** A, B, C, D, or E? (or your sequence)
2. **Domain:** Have you bought one? What domain do you want?
3. **Proxy budget:** $12.50/mo confirmed?
4. **Reddit OAuth accounts:** Which accounts for app registration?
5. **Fredo capacity:** Is he enough for now? Need more posters?
6. **Next demo date:** When is the next client meeting?
7. **AI-Native Expert:** Should I write the full spec now, or focus on posting first?
8. **Roadmap update:** Green light to update the marketing page today?
9. **Avatar inventory review:** From your side — look at what avatars are warming up and assess which ones are ready to offer to clients. You know natural Reddit behavior best. Flag any that look ready for Phase 2+ or client assignment.

---

If aligned on direction, I'll start implementation this week.
