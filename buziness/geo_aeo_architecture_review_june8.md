# Technical Review: GEO/AEO Layer vs Discovery Priorities

**Author:** Max (engineering)  
**Date:** June 8, 2026  
**Status:** Architecture Assessment (no implementation)  
**Triggered by:** Tzvi's Build vs Buy research email, June 7, 2026

---

## Executive Summary

After reviewing our current data model (26+ models), pipeline services, Discovery Engine, and the AI-Native Expert spec, my conclusion:

**GEO/AEO is NOT a standalone product. It is one of several views (dashboards) on top of Discovery as the core intelligence platform.**

The fundamental architectural question isn't "how to build GEO" — it's whether the underlying data layer captures enough attribution metadata to support multiple consumers (GEO, EPG intelligence, strategy engine, client reporting). The answer today: **almost, but with 4 critical gaps**.

---

## 1. Discovery Dependencies

### Which GEO capabilities DEPEND on Discovery data?

| GEO Capability | Discovery Dependency | Can Work Without? |
|----------------|---------------------|-------------------|
| Prompt library management | DiscoveryEntity (products, audiences, problems, competitors) | Partially — could use Client.keywords, but Discovery entities are richer |
| Brand mention detection | Client.brand_name + Client.competitive_landscape | ✅ Yes — no Discovery needed |
| Reddit URL attribution | CommentDraft.reddit_comment_url + PostingEvent | ✅ Yes — we already store this |
| Semantic attribution | NicheProfile (LSI keywords, named entities) — from AI-Native Expert spec | ❌ No — needs either Discovery entities OR NicheProfile |
| Competitor comparison | DiscoveryEntity (category=competitor) + DiscoveryHypothesis (reddit_signals) | Partially — Client.competitive_landscape gives names, Discovery gives Reddit presence data |
| Content-to-citation lineage | Full chain: Avatar → CommentDraft → Thread → PostingEvent → [external LLM query] | ❌ Missing the last link (external query → our content) |
| Prompt gap → content brief feedback loop | Discovery hypotheses + Strategy engine integration | ❌ Requires Discovery to identify which topics lack coverage |

### Which GEO capabilities operate INDEPENDENTLY?

1. **Prompt execution engine** — scheduled LLM queries to ChatGPT/Perplexity/Gemini. Zero dependency on any internal system. Can be built as a standalone Celery task.
2. **Brand mention detection** — regex/NLP on LLM response text. Only needs Client.brand_name.
3. **Citation extraction** — URL parsing from LLM responses. Standalone NLP task.
4. **Trend tracking** — time-series storage of appearance frequency. Standalone.

### What Discovery data should be collected NOW (even if GEO postponed)?

**Critical — losing attribution data every day we don't collect:**

1. **`reddit_comment_url` on ALL posted comments** — already stored on CommentDraft ✅ and PostingEvent ✅
2. **Thread permalink (full URL)** — stored as `thread.url` ✅ 
3. **Subreddit where comment was posted** — stored ✅
4. **Avatar username on posted content** — stored ✅
5. **reddit_score snapshots** — partially stored (reddit_score on CommentDraft, but no scheduled 4h/24h/48h snapshots) ⚠️
6. **Thread depth provoked (reply count to our comment)** — NOT stored ❌
7. **Comment removal detection** — stored (is_deleted + deleted_detected_at) ✅
8. **Client prompt library** — NOT stored ❌ (this is the key new entity for GEO)

### Metadata that MUST be stored now to avoid losing future attribution

| Data | Current Status | Risk of NOT Collecting |
|------|---------------|----------------------|
| Full Reddit comment permalink | ✅ CommentDraft.reddit_comment_url | N/A — already captured |
| Thread full URL | ✅ RedditThread.url | N/A |
| Karma at post time vs karma now | ⚠️ Single reddit_score, no history | Cannot measure engagement velocity |
| Reply count under our comment | ❌ Not tracked | Cannot prove "thread depth provoked" — key Tier-2 signal |
| Comment save count | ❌ Not trackable via PRAW reliably | Low priority — Reddit doesn't expose this well |
| LSI keywords used in comment | ❌ Not stored | Cannot retrospectively measure topic coherence |

---

## 2. Data Model Review

### Current Attribution Chain

```
Avatar → CommentDraft → RedditThread → Subreddit → ClientSubredditAssignment → Client
                    ↓
              PostingEvent (audit: IP, proxy, url, timing)
                    ↓
              EPGSlot (scheduling: plan_date, scheduled_at, status)
                    ↓
              ThreadScore (per-client: relevance, quality, strategic, intent)
```

**This chain is COMPLETE for internal attribution.** We can trace any posted comment back to: which avatar, which client, which thread, which subreddit, when it was scored, what the AI said about it, and when it was posted.

### Missing Entities for GEO

| Entity | Purpose | Schema Recommendation |
|--------|---------|----------------------|
| `PromptLibrary` | Client's monitored prompts (20-50 per client) | `id, client_id, prompt_text, category (brand/competitor/gap), is_active, created_at, updated_at` |
| `PromptExecution` | Scheduled query result | `id, prompt_id, llm_provider (openai/perplexity/gemini), response_text, brand_mentioned (bool), reddit_cited (bool), reddit_urls (JSONB), competitor_mentioned (JSONB), executed_at, cost_usd, tokens_used` |
| `CitationEvent` | When our content is found in LLM response | `id, prompt_execution_id, comment_draft_id (nullable), thread_id (nullable), attribution_type (explicit_url/semantic_match/none), confidence_score (0-100), detected_at` |
| `KarmaSnapshot` | Time-series comment performance | `id, comment_draft_id, checked_at, karma_value, reply_count, is_deleted` |

### Missing Relationships

| From | To | Relationship Type | Why Missing |
|------|----|--------------------|-------------|
| PromptExecution → RedditThread | Thread cited in LLM response | FK (nullable) | Entity doesn't exist yet |
| CitationEvent → CommentDraft | Our comment cited | FK (nullable) | Entity doesn't exist yet |
| CommentDraft → content_archetype | Which structural format was used | Column on CommentDraft | AI-Native Expert not implemented |
| CommentDraft → topic_coherence_score | How on-niche was this comment | Column on CommentDraft | AI-Native Expert not implemented |
| Avatar → NicheProfile | Semantic cluster definition | 1:1 relationship | AI-Native Expert not implemented |
| Client → PromptLibrary | Monitored prompts | 1:many | GEO not started |

### Missing Event Logs

| Log | Purpose | When to Capture |
|-----|---------|-----------------|
| Karma snapshots at 4h/24h/48h | Engagement velocity measurement | New Celery Beat task |
| Reply count under our comments | Thread depth provoked (Tier-2 signal) | Extend health_check task |
| LLM external query results | GEO prompt monitoring | New PromptExecution entity |
| Citation detection events | Attribution tracking | New CitationEvent entity |

### Does Current Schema Support Full Attribution?

| Chain | Status | Gap |
|-------|--------|-----|
| Avatar → Comment | ✅ CommentDraft.avatar_id | — |
| Comment → Thread | ✅ CommentDraft.thread_id | — |
| Thread → Subreddit | ✅ RedditThread.subreddit_id | — |
| Thread → Client | ✅ ThreadScore.client_id | — |
| Thread → Discovery Topic | ⚠️ Indirect via DiscoveryHypothesis.reddit_signals → subreddit names | No direct FK. Must match by subreddit name. |
| Thread → Future GEO Attribution | ❌ No link from external LLM response back to our thread | Needs PromptExecution + CitationEvent |
| Comment → Performance Over Time | ⚠️ Single reddit_score, no time-series | Needs KarmaSnapshot |

---

## 3. GEO Build Complexity Assessment

### Tzvi's estimate: 10-14 weeks total. My challenge:

### EASY (2-3 weeks combined) — Tzvi's Milestone 1

| Component | Real Effort | Notes |
|-----------|-------------|-------|
| Prompt library CRUD | 2 days | Standard model + admin HTMX partial. Trivial. |
| Scheduled prompt execution | 3 days | Celery Beat task + LLM API calls. We do this daily already (scoring, generation). Same pattern. |
| Citation extraction (URL parsing) | 1 day | Regex for reddit.com URLs in response text. Trivial. |
| Brand mention detection | 1 day | `client.brand_name in response_text` + fuzzy match. Trivial. |
| Basic dashboarding | 3 days | HTMX partial showing frequency over time. Same pattern as all our other admin panels. |

**My estimate: 2 weeks** (including schema, migrations, tests, admin UI). Tzvi says 3-4. I agree if we include prompt curation UX (the wizard).

### MEDIUM (3-4 weeks combined) — Tzvi's Milestone 2 + 3

| Component | Real Effort | Notes |
|-----------|-------------|-------|
| Reddit URL attribution | 3 days | Parse reddit URLs from LLM responses → match against reddit_threads.url. We have the data. It's a JOIN. |
| Competitor comparison | 1 week | Need competitor entity list per client (already in DiscoveryEntity category=competitor). Build comparison view. Medium because UX is complex. |
| Trend analysis (time-series) | 3 days | Standard time-series queries on PromptExecution table. Chart.js or similar. |
| Client-facing dashboard | 1 week | New template set (client_admin/client_manager accessible). Needs RBAC integration. Medium because it's the first non-admin client-visible analytics page. |

**My estimate: 3.5 weeks.** Tzvi says 4-6 (Milestones 2+3). Reasonable.

### HARD (6-12 weeks, not 3-4) — Tzvi's Milestone 4 + Semantic Layer

| Component | Real Effort | Why Hard |
|-----------|-------------|----------|
| **Semantic attribution** | 4-6 weeks | Requires pgvector, embedding pipeline for all our comments, cosine similarity matching between LLM response chunks and our content. This is a new capability stack (embeddings infra). We have zero embedding infrastructure today. |
| **Influence detection** | 2-3 weeks | "Did our comment in this thread influence the LLM's answer even without a URL?" Requires semantic similarity + temporal correlation. Research-grade problem. |
| **Content-to-citation lineage** | 2-3 weeks | Full provenance chain: prompt → LLM response → citation → our thread → our comment → our avatar. Needs all the "Easy" entities PLUS semantic matching. |
| **Closed-loop feedback** (prompt gap → content brief → avatar action) | 3-4 weeks | Requires: gap analysis engine (which prompts don't mention us?), brief generation (what should avatars write?), injection into EPG thread selection. Touches 3 existing services (EPG, scoring, generation). |
| **Non-deterministic measurement** (3-5 runs per prompt) | 1 week | 3-5× API cost. Need statistical aggregation (appearance_rate, not binary). Changes PromptExecution schema to be run-based. |

**My estimate for the full "Hard" layer: 8-12 weeks.** This is where Tzvi's timeline breaks down. He estimates 3-4 weeks for Milestone 4. That's only possible if we skip semantic attribution entirely and just do the "Easy" prompt gap analysis (which prompts don't mention us → generate brief). The full semantic layer is a different beast.

### Total Realistic Timeline

| Layer | Effort | Delivers |
|-------|--------|----------|
| Easy (Milestones 1) | 2 weeks | "Show me where my brand appears in AI answers" — basic monitoring |
| Medium (Milestones 2+3) | 3.5 weeks | "Which Reddit threads are being cited? Were they ours?" — attribution |
| Hard (Milestone 4 + semantics) | 8-12 weeks | "Here's what to write next to fill the gap" — closed loop |
| **Total** | **13.5-17.5 weeks** | Full GEO platform |

Tzvi's 10-14 weeks is realistic only if we reduce scope on the semantic layer (skip full embeddings, do keyword-based matching instead of true semantic similarity). That gets us 80% of the value for 60% of the effort.

---

## 4. Discovery as Core Platform

### Position A: Discovery is a feature feeding GEO

**Arguments:**
- Discovery is currently a pre-sales/onboarding tool (one-time session per client)
- GEO runs continuously (scheduled queries, ongoing monitoring)
- GEO has its own revenue justification ($149/mo add-on)
- Discovery doesn't need GEO data to function
- Simpler mental model: Discovery = onboarding, GEO = operations

**Problems with this position:**
- Creates data silos (Discovery entities ≠ GEO prompt keywords ≠ scoring keywords)
- Duplicates entity management (competitor list exists in 3 places: Client.competitive_landscape, DiscoveryEntity, future PromptLibrary)
- No feedback loop (what GEO learns about which prompts work doesn't flow back to Discovery)

### Position B: Discovery is the core intelligence platform

**Arguments:**
- Discovery already extracts: products, audiences, problems, competitors, use cases (DiscoveryEntity)
- Discovery already validates: Reddit ecosystem potential per hypothesis (DiscoveryHypothesis.reddit_signals)
- Discovery already produces: recommended communities + entry points (VisibilityReport)
- Discovery already feeds: Strategy Engine (via discovery_context injection)
- GEO prompt library is literally "DiscoveryEntity entities rephrased as buyer-intent questions"
- EPG thread selection could prioritize threads aligned with confirmed Discovery hypotheses
- Client reporting could show: "Your Discovery hypothesis #3 ('ICP discusses X in r/Y') has been validated by 47 avatar engagements generating 312 karma"

**With Discovery as core, the architecture looks like:**

```
                    ┌─────────────────────┐
                    │   Discovery Engine   │
                    │  (entities, hypos,   │
                    │   reddit signals)    │
                    └─────────┬───────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
              ▼               ▼               ▼
     ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
     │  GEO/AEO    │  │   EPG 2.0   │  │  Strategy   │
     │ (prompt mon, │  │ (thread sel, │  │  Engine     │
     │  attribution)│  │  portfolio)  │  │ (goals,     │
     └─────────────┘  └─────────────┘  │  cadence)   │
              │               │          └─────────────┘
              │               │               │
              ▼               ▼               ▼
     ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
     │   Client    │  │  Generation  │  │   Avatar    │
     │  Dashboard  │  │  Pipeline    │  │  Warming    │
     └─────────────┘  └─────────────┘  └─────────────┘
```

### My Recommendation: Position B

**Discovery is the core intelligence platform.** GEO, EPG, reporting, and strategy are all consumers of Discovery data.

**Key evidence:**
1. Discovery already has the entity model (product, audience, problem, competitor, use_case)
2. Discovery already validates against Reddit signals
3. Strategy Engine already accepts discovery_context
4. The "closed loop" Tzvi describes IS Discovery → avatar action → outcome → back to Discovery
5. Building GEO as standalone creates entity duplication that will become tech debt within 2 months

**Concrete implication:** Don't build `PromptLibrary` as a standalone entity. Build it as a **view** on DiscoveryEntity — each entity of type "problem" or "use_case" automatically generates candidate prompts. The operator curates/edits them, but the source of truth is Discovery.

---

## 5. Immediate Actions (Without Building GEO)

### Fields to Add to Client Onboarding

| Field | Location | Purpose |
|-------|----------|---------|
| `buyer_intent_prompts` | Client model (JSONB) | "What would your ICP type into ChatGPT?" — 5-10 seed prompts at onboarding. NOT the full prompt library (that comes from Discovery entities), but the client's own examples. |
| `competitor_brands` | Client model (JSONB array) | Structured list of competitor brand names for exact-match detection. Currently buried in `competitive_landscape` free text. |
| `target_llm_platforms` | Client model (JSONB array) | Which AI platforms matter to this client? (chatgpt, perplexity, gemini, claude). Default: all. |

### Entities to Add to Database

| Entity | Schema | Migration Priority |
|--------|--------|-------------------|
| `KarmaSnapshot` | `id, comment_draft_id, checked_at, karma_value, reply_count, is_deleted` | **P0 — do this week** |

This is the single most important missing entity. Without time-series karma data, we cannot:
- Measure engagement velocity
- Detect "this comment provoked discussion"
- Build thread_depth_provoked metric
- Feed outcome data back to GEO attribution

### Logs to Start Collecting

| Log | How | When |
|-----|-----|------|
| Karma + reply_count at 4h, 24h, 48h post-publication | New Celery Beat task `snapshot_comment_outcomes` | **P0 — this week** |
| Thread depth under our comments (direct reply count) | Part of karma snapshot task | P0 |
| Content archetype classification | Add `content_archetype` column to CommentDraft | P1 — when AI-Native Expert starts |

### Events to Start Tracking

| Event | Trigger | ActivityEvent Type |
|-------|---------|-------------------|
| Comment karma milestone (10, 25, 50, 100+) | Karma snapshot task detects threshold | `comment_karma_milestone` |
| Comment cited in external source | Future GEO detection | `external_citation_detected` |
| Thread our avatar commented in goes viral (>100 ups) | Karma snapshot detects thread growth | `thread_viral_detection` |

### Celery Beat Addition (Do Now)

```python
# Add to worker.py beat_schedule:
"snapshot-comment-outcomes": {
    "task": "app.tasks.karma_tracking.snapshot_comment_outcomes",
    "schedule": crontab(minute=0, hour="*/4"),  # Every 4 hours
},
```

Task logic:
1. Query CommentDraft WHERE status="posted" AND posted_at > now()-48h AND last_karma_check_at < now()-4h
2. For each: fetch reddit_score + reply count via PRAW
3. Write KarmaSnapshot record
4. Update CommentDraft.last_karma_check_at
5. If karma > threshold → emit ActivityEvent

---

## 6. Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Building GEO before Discovery is battle-tested | High | Entity duplication, rework | Treat Discovery as foundation; GEO builds on top |
| Semantic attribution is research-grade, not engineering | Medium | 6+ weeks on uncertain outcome | Start with explicit URL matching only. Semantic = Phase 2 |
| LLM API costs for GEO queries spiral (18K queries/mo at 25 clients) | Low | $400-700/mo additional cost | Budget is manageable, margin stays >80% |
| Perplexity/OpenAI change APIs or rate-limit us | Medium | Feature breaks | Abstract provider behind adapter pattern (same as LiteLLM) |
| Non-deterministic results confuse clients | High | "Last week you said I was cited, now I'm not!" | Frequency-based reporting (appeared in 6/10 queries), never binary |
| Building prompt curation UX is harder than expected | Medium | Bad prompts → useless data | Start with Tzvi curating manually in DB/admin; build wizard later |

---

## 7. Recommended Roadmap

### Phase 0: Foundation (This Week — No GEO Code)
- [ ] Add `KarmaSnapshot` model + migration
- [ ] Add `snapshot_comment_outcomes` Celery Beat task (4h/24h/48h karma checks)
- [ ] Add `buyer_intent_prompts` JSONB to Client model
- [ ] Add `competitor_brands` JSONB array to Client model
- [ ] Start capturing reply_count in karma snapshots

### Phase 1: Discovery Hardening (Weeks 1-2 — Before GEO)
- [ ] Validate Discovery → Strategy handoff works for all clients (not just test data)
- [ ] Ensure DiscoveryEntity entities are comprehensive (audit existing clients)
- [ ] Add "auto-generate prompt candidates" from DiscoveryEntity (rule-based, no LLM)

### Phase 2: GEO Easy Layer (Weeks 3-4)
- [ ] PromptExecution model + Celery Beat task (scheduled LLM queries)
- [ ] Brand/competitor mention detection (regex + fuzzy)
- [ ] Reddit URL extraction from responses
- [ ] URL → our RedditThread matching (JOIN on URL)
- [ ] Basic admin dashboard (appearance frequency, trend, which prompts cite Reddit)
- [ ] Integrate with Perplexity Sonar API first (best Reddit citation behavior)

### Phase 3: GEO Attribution Layer (Weeks 5-7)
- [ ] CitationEvent model (explicit URL attribution)
- [ ] "Our avatar commented in cited thread" detection (PostingEvent JOIN)
- [ ] Client-facing dashboard (RBAC: client_admin+ access)
- [ ] Competitor comparison view
- [ ] Weekly report generation (markdown, like strategy docs)

### Phase 4: GEO Closed Loop (Weeks 8-12) — Only After AI-Native Expert Ships
- [ ] Prompt gap analysis ("these prompts don't mention you")
- [ ] Content brief generation (gap → recommended topics → EPG injection)
- [ ] EPG integration (prioritize threads in gap subreddits)
- [ ] Feedback cycle: GEO outcomes → Discovery hypothesis confidence update
- [ ] Semantic matching (requires pgvector — coordinate with AI-Native Expert embedding infra)

### Deferred (Not in 12-week scope)
- Semantic attribution (embedding similarity matching)
- Multi-run statistical measurement (3-5 runs per prompt)
- Claude/Gemini training-data lag tracking (6-18 month signals)

---

## 8. Dependency Map

```
┌──────────────────────────────────────────────────────────────────┐
│                        PREREQUISITE LAYER                          │
│                                                                    │
│  KarmaSnapshot ─────┐                                            │
│  (outcome tracking)  │                                            │
│                      ▼                                            │
│  DiscoveryEntity ──► Prompt Candidate Generation                  │
│  (products/problems) (auto-suggest buyer-intent prompts)          │
│                      │                                            │
│  Client.competitor_brands ──► Brand/Competitor Detection           │
│  (structured list)            (regex matching in LLM responses)   │
│                                                                    │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                         GEO EASY LAYER                             │
│                                                                    │
│  PromptExecution (Celery Beat → LLM APIs)                         │
│       │                                                            │
│       ├──► Brand mentioned? (boolean + context snippet)            │
│       ├──► Reddit cited? (URL extraction)                          │
│       └──► URL → our RedditThread? (JOIN)                          │
│                                                                    │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                      GEO ATTRIBUTION LAYER                         │
│                                                                    │
│  CitationEvent (explicit URL → our thread → our comment)           │
│       │                                                            │
│       └──► "Avatar X's comment in r/Y thread was cited by          │
│             Perplexity in response to prompt Z"                     │
│                                                                    │
│  Competitor tracking (same prompts, competitor brand detection)     │
│  Trend analysis (time-series on PromptExecution)                   │
│                                                                    │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼ (requires AI-Native Expert + pgvector)
┌──────────────────────────────────────────────────────────────────┐
│                       GEO CLOSED LOOP                              │
│                                                                    │
│  Prompt Gap Analysis → Content Brief → EPG Injection               │
│       │                                                            │
│       └──► Discovery hypothesis confidence update                  │
│       └──► Semantic attribution (embedding similarity)             │
│                                                                    │
└──────────────────────────────────────────────────────────────────┘
```

---

## 9. Key Architectural Decision

**The question isn't "when do we build GEO."**

**The question is: "Do we invest 2 days now to add KarmaSnapshot + competitor_brands + buyer_intent_prompts to the schema, so that when GEO ships in 8 weeks, we have 8 weeks of historical attribution data instead of zero?"**

The answer is obviously yes. The cost is 2 engineering days. The benefit is time-series data we can never recover retroactively.

---

## 10. Response to Tzvi's Recommendation

Tzvi recommends thin partner integration (Otterly/PromptWatch) as stopgap. I agree with this for client-facing demos, but with a caveat:

**Partner tools cannot show "this citation came from YOUR avatar's comment."** They show "your brand appeared" — but not WHY. The attribution layer is our unique value. A partner tool gives us the "Easy" layer (brand monitoring) but cannot give us the "Attribution" or "Closed Loop" layers.

So:
- **Yes** to Otterly ($29/mo) for immediate client demo ("look, Perplexity mentions you here")
- **No** to replacing our build with a partner — the partner gives us 20% of the value (monitoring) and 0% of the moat (attribution)
- **Build Priority:** Phase 0 (this week: KarmaSnapshot), then GEO Easy (weeks 3-4) to replace Otterly with our own monitoring that includes the attribution data

The closed-loop flywheel Tzvi describes is the product differentiator. It depends on Discovery + EPG + GEO all sharing the same entity model. Building GEO as a standalone bolted-on module would miss the architectural opportunity.

---

*This document is for strategic architecture planning. No implementation has been started. Next step: discuss with Tzvi whether to proceed with Phase 0 (2 days) immediately, and when to schedule GEO Easy (weeks 3-4) relative to other Phase 2 priorities.*
