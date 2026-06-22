# Guide — Discovery Engine

> **Audience:** Owner, Partner, Client Admin  
> **Last updated:** 2026-06-17

---

## Overview

The Discovery Engine is a structured research system that identifies Reddit engagement opportunities for a client or prospect. It replaces manual subreddit guessing with a data-driven, iterative process.

**Core value:** Prove that a subreddit is worth entering BEFORE avatars invest time there. Then continuously validate that it still works.

```
BRIEF → ENTITIES → HYPOTHESES → REDDIT RESEARCH → SCORING → DECISION → REPORT → HANDOFF
                                                                           ↑
                                                              CONTINUOUS DISCOVERY (weekly)
```

---

## What Problem It Solves

| Before (manual) | After (Discovery Engine) |
|-----------------|--------------------------|
| Analyst guesses subreddits based on intuition | System proves relevance with Reddit data |
| Takes 5–10 days of research per client | Takes 1 session (~15 min operator time) |
| No validation until comments get removed | Validates signal strength before entering |
| No ongoing re-evaluation | Weekly continuous check adjusts strategy |
| No deliverable for the client | Visibility Report as Day 1 artifact |

---

## How It Works — Step by Step

### Step 1: Create Session

Operator enters a **client brief** (50–5000 characters) describing the prospect's business, product, audience, and competitive landscape.

- Optional: link to existing client record
- Optional: prospect name (for pre-client research)

**Location:** Admin → Discovery → New Session

---

### Step 2: Entity Extraction (AI)

The system uses Gemini Flash to extract **3–20 named entities** from the brief.

| Category | Example |
|----------|---------|
| `product` | "Continuous Exposure Management platform" |
| `audience` | "Enterprise CISOs" |
| `problem` | "Vulnerability prioritization overload" |
| `industry` | "Cybersecurity" |
| `competitor` | "Tenable", "Qualys" |
| `use_case` | "Cloud security posture validation" |

Operator can add/remove entities before proceeding.

---

### Step 3: Hypothesis Formation (AI)

From the entities, the system generates **3–7 testable hypotheses**. Each hypothesis:

- Makes a specific claim about Reddit relevance
- Includes at least one quantifiable Reddit metric
- Is categorized by opportunity type

**Categories:**

| Category | What it means |
|----------|---------------|
| `clients` | Potential client acquisition opportunities |
| `partners` | Partnership/collaboration signals |
| `feedback` | Product feedback and sentiment discussions |
| `recognition` | Brand recognition and awareness signals |
| `hiring` | Talent acquisition signals |
| `market_research` | Market intelligence opportunities |

**Example hypothesis:**
> "r/cybersecurity has 20+ posts per month discussing vulnerability prioritization, with average engagement of 15+ upvotes — indicating active demand for exposure management education."

---

### Step 4: Reddit Research (Background Task)

A Celery task searches Reddit for evidence supporting each hypothesis:

1. Extracts search terms from hypothesis + entities
2. Searches `reddit.subreddits.search()` (up to 10 subreddits per hypothesis)
3. For each subreddit, fetches hot posts and measures:
   - Subscriber count
   - Post volume (estimated 30-day)
   - Average engagement (upvotes + comments)
   - Topic relevance score (keyword overlap, 0–100)

**Timeout:** 20 seconds per hypothesis, 120 seconds total.

**No-signal detection:**
- `search_too_narrow` — broader terms have signal, hypothesis wording too specific
- `topic_absent` — no signal at all, topic doesn't exist on Reddit

Progress is tracked live via HTMX polling. Operator can stop research early.

---

### Step 5: Confidence Scoring (Rule-Based)

Pure Python, no AI calls. Deterministic rules:

| Signal | Effect |
|--------|--------|
| Strong subreddit (≥20 posts/30d AND ≥10 avg engagement) | +10 per sub (cap +30) |
| Weak subreddit (<5 posts/30d OR <3 avg engagement) | −10 per sub (cap −30) |
| No signal (both narrow and broad fail) | Force to 15 |

Base score: 50. Final range: 0–100.

---

### Step 6: Operator Decision

For each hypothesis the operator chooses:

- **Confirm** — validated, use for strategy
- **Reject** — not relevant (requires reason)

Bulk "Confirm All" is available when signals are clear.

All hypotheses must be decided before generating report or advancing iteration.

---

### Step 7: Visibility Report (AI)

Claude Sonnet generates a structured report answering: **"What can Reddit give this client in the next 6–12 months?"**

Report sections:
- Executive summary
- Demand assessment
- Recommended communities (with subscribers, activity, approach)
- Discussion activity patterns
- Entry points (specific thread types to target)
- Competitive landscape
- Visibility outcomes (probability per category)
- Risks and limitations

This is the **Day 1 deliverable** — can be exported as branded HTML for the client.

---

### Step 8: Strategy Handoff

Converts Discovery findings into operational config:

1. If prospect → creates a new Client record
2. Pre-populates subreddit assignments from recommended communities (up to 10)
3. Passes structured context to Strategy Engine
4. Logs `discovery_handoff` activity event

After handoff, the client is ready for pipeline configuration.

---

## Continuous Discovery (Weekly)

**Schedule:** Every Sunday at 04:00 (Celery Beat)

The system re-evaluates confirmed hypotheses against real posting outcomes:

1. Reads KarmaSnapshot data (engagement after posting)
2. Reads removal rates per subreddit
3. Updates hypothesis confidence based on actual results:
   - Removal rate >25% → confidence −15 ("community may be hostile")
   - Negative avg karma → confidence −20 ("content not resonating")
   - Avg karma ≥10 with 5+ posts → confidence +8 ("strong engagement")
4. Emits `DiscoveryDelta` events for audit trail
5. If confidence drops below 30 → flags for strategy review
6. **Propagates directly to EPG weights** — adjusts subreddit priority for avatars

**Key principle:** Discovery is not one-time. It continuously validates whether the Reddit ecosystem still supports the strategy.

---

## Iterations

A session supports up to **5 iterations**. Each iteration:

1. Can refine entities based on what was learned
2. Generates new hypotheses (deduped against prior iterations)
3. Uses rejection reasons to improve next-round hypotheses
4. Builds on confirmed directions from prior rounds

Most clients need 1–2 iterations. Complex niches may need 3–4.

---

## Cost Per Session

| Operation | Model | Cost |
|-----------|-------|------|
| Entity extraction | Gemini Flash Lite | ~$0.001 |
| Hypothesis formation | Gemini Flash Lite | ~$0.002 |
| Reddit Research | PRAW (free) | $0.00 |
| Confidence Scoring | Python (no AI) | $0.00 |
| Visibility Report | Claude Sonnet | ~$0.15–0.25 |
| **Total per session** | | **~$0.15–0.25** |

Continuous Discovery (weekly): **$0.00** — pure Python + DB queries + PRAW.

Discovery is one of the cheapest subsystems in the platform. The entire cost is one Claude Sonnet call for the report.

---

## Comparison with Legacy Approach (Ori / n8n)

| Aspect | Ori (n8n workflows) | RAMP Discovery Engine |
|--------|--------------------|-----------------------|
| Subreddit selection | Hardcoded list, chosen by intuition | AI-driven + Reddit Research with data |
| Validation | None — learn from failures | Confidence scoring before entry |
| Iteration | One-shot | Up to 5 rounds with refinement |
| Feedback loop | None | Weekly continuous + EPG propagation |
| Scalability | 1 client at a time, manual | Any client/prospect, reusable |
| Deliverable | None | Visibility Report (branded, exportable) |
| Cost per client | 5–10 hours analyst time | $0.25 + 15 min operator time |

---

## UI Location

| Page | Path | Purpose |
|------|------|---------|
| Session list | `/admin/discovery` | All sessions, filter by status |
| New session | `/admin/discovery/new` | Create session form |
| Active session | `/admin/discovery/{id}` | Step-by-step workflow |
| Results | `/admin/discovery/{id}/results` | Shareable results page |
| Report export | `/admin/discovery/{id}/report/export` | Branded HTML for client |

---

## Key Files

| File | Purpose |
|------|---------|
| `app/services/discovery/session_manager.py` | Session CRUD and lifecycle |
| `app/services/discovery/entity_extractor.py` | LLM entity extraction |
| `app/services/discovery/hypothesis_engine.py` | LLM hypothesis generation |
| `app/services/discovery/reddit_researcher.py` | PRAW-based signal collection |
| `app/services/discovery/confidence_scorer.py` | Rule-based scoring |
| `app/services/discovery/report_generator.py` | Visibility Report (Claude) |
| `app/services/discovery/strategy_handoff.py` | Discovery → Strategy bridge |
| `app/services/discovery/continuous.py` | Weekly re-evaluation |
| `app/tasks/discovery.py` | Celery tasks |
| `app/routes/discovery.py` | Admin routes |
| `app/models/discovery_session.py` | Session model |
| `app/models/discovery_entity.py` | Entity model |
| `app/models/discovery_hypothesis.py` | Hypothesis model |

---

## Demo Mode

For Zoom demos without Reddit API access:

**Admin → Discovery → Create Demo Session**

Creates a pre-populated completed session with realistic data. Redirects to results page instantly.

---

## Related

- [Pipeline Explained](./pipeline-explained.md) — how scored threads become comments
- [Onboarding New Client](./onboarding-new-client.md) — full onboarding flow
- [Glossary](../glossary.md) — terminology
