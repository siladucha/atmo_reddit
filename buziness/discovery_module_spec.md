# Discovery Module — How It Works

**Author:** Max | **Date:** June 8, 2026  
**For:** Tzvi (strategic context) + internal (implementation reference)

---

## What Discovery Does

Discovery continuously maps the relationship between an avatar, its communities, its goals, and the surrounding environment — then converts that understanding into strategy and daily guidance.

It's not a one-time research tool. It's a **living intelligence layer** that feeds the entire pipeline: which threads to engage, how to engage, what niche to own, and how to evolve.

---

## Three Operational Modes

### Mode 1: Client Onboarding Discovery (One-Time)

**Trigger:** New client signs up or prospect enters demo  
**Who runs it:** Operator (us) during sales/onboarding call, or self-serve via wizard  
**Duration:** 5–15 minutes active + 2 min background research  
**Output:** Reddit Landscape Report + preconfigured client workspace

**Flow:**
1. Operator enters client brief (company, product, audience, problem they solve)
2. AI extracts entities (products, audiences, problems, industries, competitors)
3. Operator confirms/edits entities → AI forms hypotheses ("r/cybersecurity has 10K+ posts about attack surface management")
4. System researches Reddit (live PRAW queries — subreddit search, engagement metrics, post volumes)
5. Operator sees results streaming in real-time, can stop early if enough signal found
6. Operator confirms/rejects hypotheses → generates **Visibility Report**
7. **Handoff:** Report data flows into Client record (subreddits, keywords, niche definition)

**What Tzvi pitched to clients:**
> "Day 1 Reddit Landscape Report" — instant deliverable proving value before avatars are even active. Shows client: "Here are 12 subreddits where your ICP discusses your category. Here's the engagement volume. Here are competitors already present."

---

### Mode 2: Avatar Niche Discovery (Per-Avatar, Periodic)

**Trigger:** Avatar created + assigned to client, OR authority score stagnates, OR quarterly review  
**Who runs it:** System (auto) + operator review  
**Duration:** Background (Celery), results in 5–10 min  
**Output:** NicheProfile updates, content archetype weighting, subreddit priority adjustments

**Flow:**
1. System evaluates avatar's current performance: which subreddits produce engagement, which approaches work, what topics get removed
2. Discovery session scoped to avatar: research current niche health in target subreddits
3. Identify gaps: "Avatar posts about K8s security but misses fintech-specific threads in r/devsecops"
4. Identify threats: "New competitor avatar active in same niche since last month"
5. Identify opportunities: "r/platformengineering grew 40% in 3 months, niche-adjacent"
6. Output: updated NicheProfile recommendations, subreddit add/remove suggestions, archetype reweighting

**Connection to AI-Native Expert warming:**
- Feeds into Requirement 1 (Niche Profile Configuration)
- Feeds into Requirement 8 (Niche-Aware Thread Selection)
- Feeds into Requirement 9 (Authority Progression Phases)

---

### Mode 3: Continuous Environment Mapping (Scheduled)

**Trigger:** Weekly Celery Beat (Sunday 04:00) + on-demand  
**Who runs it:** Fully automated  
**Duration:** Background, 15–30 min for all active clients  
**Output:** Strategy document updates, EPG adjustments, operator alerts

**Flow:**
1. For each active client: scan assigned subreddits for:
   - Moderation changes (new rules, banned topics)
   - Engagement trend shifts (declining/rising activity)
   - New competitor presence (brand mentions by others)
   - Topic drift (community discussing different things than 3 months ago)
2. For each active avatar: check:
   - Niche coherence trend (are recent posts staying in cluster?)
   - Removal rate by subreddit (moderator pattern detection)
   - Karma velocity vs. historical average
3. Generate alerts for operator:
   - "r/cybersecurity now requires flair — 3 comments removed this week"
   - "NeuroYoga avatar losing engagement in r/yoga, up in r/meditation"
   - "New competitor brand mentioned 15 times in r/attacksurface this month"
4. Auto-update strategy documents if confidence > threshold
5. Feed adjustments into next EPG generation (thread selection, subreddit priority)

**Connection to GEO/AEO (Tzvi's June 7 research):**
- Prerequisite #1: Discovery maps which subreddits + topics are most cited by LLMs
- Feeds Tzvi's "Content Engineering Feedback Loop": what LLMs cite → what Discovery recommends → what avatars produce
- Prompt library per client (Tzvi's prerequisite) = specialized Discovery session entities

---

## How Discovery Connects to Everything

```
┌─────────────────────────────────────────────────────────┐
│                     DISCOVERY                            │
│                                                         │
│  Onboarding → Visibility Report → Client Setup          │
│  Avatar Niche → NicheProfile → Generation Prompts       │
│  Environment → Strategy Docs → EPG Daily Program        │
│                                                         │
└──────────┬──────────────┬──────────────┬────────────────┘
           │              │              │
           ▼              ▼              ▼
    ┌──────────┐   ┌──────────┐   ┌──────────┐
    │ Scoring  │   │Generation│   │   EPG    │
    │(relevance│   │(niche,   │   │(thread   │
    │ filter)  │   │ archetype│   │ selection,│
    │          │   │ entity   │   │ timing)  │
    │          │   │ linking) │   │          │
    └──────────┘   └──────────┘   └──────────┘
```

---

## What's Built Today (June 8, 2026)

| Component | Status | Notes |
|-----------|--------|-------|
| Mode 1: Onboarding Discovery | **Working** | Full flow: brief → entities → hypotheses → research → results → report → handoff |
| Entity extraction (Gemini Flash) | ✅ | Async, validated, logged |
| Hypothesis formation (Gemini Flash) | ✅ | Async, retry on <3, dedup |
| Reddit research (PRAW) | ✅ | Celery task, per-hypothesis, progress streaming |
| Confidence scoring | ✅ | Pure Python, no LLM needed |
| Results UI with streaming | ✅ | HTMX poll every 3s, results appear as they complete |
| Stop Research button | ✅ | Operator can halt, completed results preserved |
| Confirm/Reject decisions | ✅ | Form parsing, Confirm All button, audit logged |
| Rate limit display | ✅ | Real-time Reddit API utilization in sidebar |
| Strategy handoff | ✅ | Creates Client record from Discovery data |
| Visibility Report generation | ✅ | Async LLM, exportable |
| AI cost tracking | ✅ | All LLM calls logged in ai_usage_log |
| Audit trail | ✅ | Session created, research started, decisions made |
| Mode 2: Avatar Niche Discovery | **Not started** | Spec exists (AI-Native Expert warming) |
| Mode 3: Continuous Environment | **Not started** | Architecture defined, no implementation |

---

## What Tzvi Cares About (Highlighted)

### For Sales Demos (NOW)
- **"Day 1 Reddit Landscape Report"** — run Discovery for prospect's brand during Zoom call. Takes 5 min. Prospect sees real data: subreddits, post volumes, engagement levels, competitor presence. Shareable PDF.
- **Pre-built demo workspace** — static data from anonymized client for instant demos without running live research.

### For Client Onboarding (Phase 1)
- Discovery IS the first step of onboarding. Client brief → AI extracts their world → validates on Reddit → sets up workspace.
- Quality gate: thin briefs produce poor research. System enforces minimum 50-char brief, extracts 3+ entities before proceeding.

### For GEO/AEO Layer (Phase 2, per June 7 research)
- Discovery provides the **prompt library curation** — entities extracted become the seed for "what would ICP type into ChatGPT?"
- Discovery provides the **competitor set** — entities tagged as "competitor" feed into brand appearance monitoring
- Discovery provides the **subreddit-to-topic map** — which subreddits map to which prompts (for citation attribution)
- **Prerequisite data capture starts NOW** — every Discovery session captures structured entities that will power GEO/AEO later

### For Pricing/Positioning
- Discovery runs on Gemini Flash Lite — cost per full session < $0.01
- Reddit research uses shared PRAW client — no additional API cost
- Can offer "free Discovery scan" as sales tool without margin impact
- Premium value: the report itself is what competitors charge $500+ for in consulting

---

## Implementation Sequence

| Priority | What | Effort | Unlocks |
|----------|------|--------|---------|
| ✅ DONE | Mode 1 core flow | — | Sales demos, client onboarding |
| P0 | Report export (branded PDF/HTML) | 2 days | Shareable deliverable for prospects |
| P0 | Demo workspace with seed data | 2 days | Tzvi's Zoom demos |
| P1 | Onboarding wizard integration (Discovery as Step 1) | 1 week | Self-serve client setup |
| P1 | Prompt library capture at onboarding | 2 days | GEO/AEO prerequisite |
| P2 | Mode 2: Avatar Niche Discovery | 2 weeks | AI-Native Expert warming |
| P2 | Mode 3: Weekly environment scan | 2 weeks | Auto-strategy updates |
| P3 | GEO/AEO integration (Milestones 1+2) | 6-8 weeks | Citation tracking |

---

## UX Flow Summary (What Operator Sees)

```
/admin/discovery (list)
  └── [+ New Session]
        └── Brief form (company description, 50+ chars)
              └── AI extracts entities (3-20)
                    └── Operator confirms entities [+ add manual / - remove]
                          └── AI forms hypotheses (3-7 per iteration)
                                └── [Confirm Entities → Form Hypotheses]
                                      └── [Start Research]
                                            └── Progress stream (real-time, can stop)
                                                  └── Results (confirm/reject each, or Confirm All)
                                                        └── [Generate Report] or [Next Iteration]
                                                              └── Visibility Report (export)
                                                                    └── [Handoff → Create Client]
```

**Key UX principles:**
- Every step persisted in DB — leave and come back anytime
- Research results stream in real-time (no waiting for all to complete)
- Stop button available during research
- Max 5 iterations (refinement cycle)
- Confirm All shortcut for batch decisions
- Rate limit visible in sidebar (shared Reddit API budget awareness)
