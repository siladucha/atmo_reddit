# Tzvi's Research: Build vs Buy — GEO/AEO Layer for RAMP

**From:** Tzvi Vaknin  
**Date:** Sun, Jun 7, 2026, 8:50 PM  
**Subject:** GEO/AEO Build vs Buy Research Findings

---

## Executive Summary

Tzvi recommends **building proprietary** GEO/AEO layer. The core argument: RAMP's unique closed loop between avatar posting activity and LLM citation tracking is something no external tool can replicate. Short-term: use a thin partner integration (Otterly $29/mo or PromptWatch $99/mo) as scaffolding while building the real thing.

---

## What We're Actually Building (3 Components)

### 1. Prompt Intelligence Layer
- Key prompts clients care about
- What do ChatGPT/Gemini/Perplexity say when asked those prompts today?
- Who gets cited? Does Reddit appear? Which threads?

### 2. Reddit Citation Attribution (RAMP-Exclusive)
- Of the Reddit content cited in LLM answers, how much was influenced/seeded by our avatars?
- Cross-reference LLM responses against our thread database
- Flag: "This Reddit thread that your avatar commented in is being cited by Perplexity"

### 3. Content Engineering Feedback Loop (Compound Moat)
- Use prompt response data to inform what topics avatars post about next
- Close the loop: "what LLMs cite" → "what we produce"

---

## Build Timeline Estimate

| Milestone | Duration | Description |
|-----------|----------|-------------|
| 1. Prompt monitoring core | 3–4 weeks | Prompt library per client, scheduled query runner (ChatGPT + Gemini + Perplexity APIs), response storage, brand appearance detection |
| 2. Reddit citation detection | 2–3 weeks | Parse LLM responses for Reddit URLs, cross-reference thread DB, flag RAMP-attributed citations |
| 3. Client-facing dashboard | 2–3 weeks | Brand frequency visualization, competitor comparison, trends, Reddit source tracking |
| 4. Content engineering feedback loop | 3–4 weeks | Prompt gap analysis → content briefs → feed back into avatar generation |

**Total: 10–14 weeks** (non-exclusive with other Phase 2 work)

Ship Milestones 1+2 first — they drive client retention. Milestones 3+4 are the product differentiator.

---

## Prerequisites

### Data Prerequisites
- **Prompt library per client** — 20–50 "key prompts" defined at onboarding. New onboarding field: "What would your ICP type into ChatGPT when evaluating your category?" Capture in Phase 1 onboarding even if module ships in Phase 2.
- **Competitor set per client** — already partially in place, needs structured entity list (not just keywords).
- **Reddit thread DB with RAMP attribution flags** — every thread avatars commented in needs a flag (permalink, subreddit, date, avatar ID). Confirm metadata is sufficient. Start logging now — losing attribution data every day we don't.

### Infrastructure Prerequisites
- Dedicated async job queue for LLM query runs (longer-running, more expensive — own Celery queue with rate limiting)
- Response storage schema (prompt, model, timestamp, response text, citations parsed, brand Y/N, Reddit cited Y/N, Reddit URL)
- LLM API access: OpenAI (web search enabled), Gemini (AI Studio API), Perplexity (Sonar API) — budget separately from avatar generation costs

### Process Prerequisites
- **Prompt curation workflow** — Tzvi (not Max) defines/maintains prompt library per client. 1–2 hours per client at onboarding + monthly review. Bad prompts = useless data.
- **Baseline measurement at onboarding** — run full prompt suite on Day 1 and store results. Without baseline, can't show delta.

---

## Cost Estimates (at 25 clients)

### Build Cost (One-Time)
- Max's time: 10–14 weeks (~3 months)
- No external contractors needed

### Monthly Technology Costs

| Item | Calculation | Cost/month |
|------|-------------|------------|
| Perplexity Sonar API | 18,000 queries × $5/1K | ~$90 |
| OpenAI (ChatGPT + web search) | 18,000 queries × $0.01–0.02 | ~$180–360 |
| Gemini API | 18,000 queries (comparable to OpenAI) | ~$150–250 |
| DB storage (PostgreSQL) | Text responses, 3–6 months | ~$20–40 |
| **Total** | | **~$450–750/month** |

**Per client: $16–28/month in API costs**

### Revenue Model
- Charge as $149/month add-on or include in Scale plan
- At 25 clients with 40% adoption: $3,725/month revenue vs $750/month cost
- **Strong margin even at low adoption**

### Partner Tool Comparison
- Partner tools: $99–$332/month per client
- At 25 clients: $2,500–$8,000/month to third party
- vs. build: $450–750/month total in API costs
- **Math strongly favors build at our scale**

---

## Critical Considerations (What We Haven't Thought About)

### 1. Prompt Quality Problem
- Difference between useful and useless dashboard is 100% prompt library quality
- Bad: "What is the best cybersecurity tool?"
- Good: "What attack surface management platform should a Series B SaaS company use instead of traditional vulnerability scanners?"
- Need AI-assisted wizard for prompt curation at onboarding
- This is a product design problem, not engineering

### 2. Non-Deterministic LLM Responses
- Same prompt asked twice → different citations
- Measurement must be **frequency-based** (how often brand appears across N runs), not binary
- Run each prompt 3–5 times, report appearance rate
- More expensive but intellectually honest
- Competitors reporting binary results are misleading clients

### 3. Reddit Citation Detection is Hard
- ChatGPT with web browsing: sometimes cites Reddit URL
- Gemini: often doesn't cite Reddit directly
- Perplexity: usually does cite
- Need two attribution levels:
  - **Explicit**: Reddit URL appears in response (easy)
  - **Semantic**: response contains claims matching tracked thread content without URL (harder NLP problem, but RAMP-unique)

### 4. The Feedback Loop IS the Product
- Every competitor builds a dashboard
- None can say: "Prompt X cites Reddit 6/10 times. Here are the 3 subreddits. Here's the content brief for your avatars."
- Closed loop: prompt gap → content brief → avatar action
- **Unique to RAMP** — only tool that can move the needle on what it measures
- Lead with this in sales conversations — it's a flywheel, not a reporting feature

### 5. Training Data Lag (6–12 Month Play)
- **Live web search LLMs** (Perplexity, ChatGPT-web): surface Reddit in days → measurable impact in weeks
- **Training data LLMs** (Claude, Gemini in some modes): 6–18 months lag
- Segment tracking accordingly
- Sell Perplexity/ChatGPT signal first, frame training data as long game
- Be honest with clients about this distinction

### 6. Competitive Tools Are Weak on Reddit-Specific Angle
- Profound, Otterly: run prompt → check if brand mentioned
- They DON'T know which Reddit threads influenced the answer
- They DON'T know if threads were seeded by managed accounts
- RAMP's attribution layer = proprietary data advantage
- The longer we run, the wider the gap
- Pitch to teams who tried Profound/Otterly: "tells you what's broken but not how to fix it"

---

## Tzvi's Recommendation

1. **Short-term**: Thin partnership integration (Otterly $29/mo Lite or PromptWatch $99/mo) as stopgap for Phase 2. Show clients something immediately.
2. **Medium-term**: Max builds Milestones 1+2 of proprietary layer.
3. **Long-term**: Replace partner tool entirely. Never pitch partner tool as the product — it's scaffolding.
4. **The proprietary build is the right long-term call.** The closed loop is something no external tool can replicate.

---

## Key Quotes for Sales/Pitch

> "Is what we're paying for actually showing up where our buyers research?" — the real question marketing teams ask

> "Prompt gap → content brief → avatar action" — RAMP's unique flywheel

> "Tells you what's broken but doesn't tell you how to fix it" — positioning vs Profound/Otterly

---

*Saved from Tzvi's email, June 7, 2026. Original subject: Build vs Buy GEO/AEO Layer Research.*
