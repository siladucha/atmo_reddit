# External Analyst Review — June 2026

**Source:** Independent architecture analyst (received UML + JSON diagnostic)
**Date:** June 25, 2026
**Accuracy assessment:** ~92% (corrections noted below)

---

## Analyst's Findings (verbatim summary)

### 1. System Identity
RAMP classified as **Closed-Loop Marketing system** — not just a Reddit parser. Key differentiator: avatar lifecycle management (karma, phases, emotional profiles) + AI self-learning from human edits.

### 2. Architecture Patterns Observed
- **Event-driven Batch Process** — not real-time. Pipeline "breathes" on Celery Beat schedule (08:00, 14:00). Justified by Reddit API limits and LLM cost.
- **Clear state segregation** — EPGSlot (when/where) vs CommentDraft (what). Prevents state chaos.
- **Infrastructure monolith** — single Docker Compose on one droplet. Good for MVP/Growth, creates SPOF.

### 3. Critical Risks Identified

#### A. Orchestration Problem (No single locus of control)
- Pattern: "Data-Driven Orchestration" (DB as message bus)
- Risk: Ghost Tasks (tasks stuck in pending if worker crashes)
- Analyst recommends: Consider Temporal or Prefect for pipeline observability

#### B. GAP-003: EPG Race Condition
- Risk: Double EPG build = avatar gets double daily load = ban risk
- Analyst recommendation: **PostgreSQL Advisory Locks** (`pg_advisory_lock(avatar_id)`) over Redis locks for this infra
- Reasoning: More reliable than Redis when DB is already the source of truth

#### C. GAP-012: Prompt Versioning
- Risk: Learning Loop trains on data from mixed prompt versions = noise in CorrectionPatterns
- Analyst recommendation: Minimum = PromptVersion table in DB. Maximum = PromptLayer/LangSmith integration.

#### D. Kill Switch Latency
- Risk: 5-min propagation delay. Celery prefork worker may already have safety check result in memory.
- Analyst recommendation: Add Redis check for POSTING_DISABLED **immediately before** `reddit.submit()` call, not just at task selection.

### 4. Cost Optimization Insight
Smart Scoring precision = highest ROI optimization. If Gemini Flash mis-tags a junk thread as "engage", expensive Claude Sonnet tokens are wasted on generation that human will reject anyway.
- Recommendation: Add pre-LLM heuristic filters (thread length, spam keywords, author karma) before scoring call.

### 5. Verdict
- Well-designed for niche. Data model reflects deep Reddit mechanics understanding.
- Enterprise readiness requires: GAP-003 fix + orchestrator consideration.

---

## Corrections to Analyst's Review

| Analyst claim | Actual truth | Impact |
|---|---|---|
| "в JSON заявлено обратное" (GAP-003 claimed fixed) | JSON correctly states GAP-003 as NOT_IMPLEMENTED, severity: medium | Analyst misread |
| "Scoring через Gemini" (only) | Scoring = Gemini Flash. Generation = Claude Sonnet. Persona selection = Claude. | Partially correct |
| No mention of Hobby pipeline | Dual pipeline not discussed | Missing from analyst's view |
| No mention of ExecutionTask (email delivery) | Analyst focused on auto-posting path only | Incomplete |
| "закрытый цикл автоматического маркетинга" | System is Human-in-the-Loop (not fully automatic). Term "automatic marketing" violates legal/brand guidelines. | Terminology risk |

---

## Engineering Responses to Analyst Recommendations

### GAP-003 Resolution: PostgreSQL Advisory Locks vs Redis

**Decision: PostgreSQL Advisory Locks (analyst's recommendation accepted)**

Rationale:
- EPG build already runs inside DB transaction (reads threads, writes slots)
- Advisory lock on `avatar_id` is zero-cost (no extra infra)
- Redis lock adds network hop + TTL management complexity
- If Redis is down, advisory lock still works

Implementation plan:
```python
# In portfolio_manager.build_portfolio() or epg task
db.execute(text("SELECT pg_advisory_lock(:avatar_id)"), {"avatar_id": avatar_id_int})
try:
    # ... EPG build logic ...
finally:
    db.execute(text("SELECT pg_advisory_unlock(:avatar_id)"), {"avatar_id": avatar_id_int})
```

Status: **ACCEPTED, not yet implemented**

### Kill Switch Latency Fix

**Decision: Accepted — add Redis check before PRAW call**

Implementation:
```python
# In posting.py, immediately before reddit.submit()
if redis_client.get("ramp:kill:posting_disabled"):
    return PostingResult(blocked=True, reason="kill_switch_last_moment")
```

Status: **ACCEPTED, not yet implemented**

### Pre-LLM Heuristic Filters

**Decision: Partially implemented already**

Existing filters (in smart_scoring.py):
- Hot thread filter (>200 ups when avatar karma <100)
- Link/video/image filter (external URLs)
- Thread age filter (reddit_created_at check)
- is_locked filter

NOT implemented:
- Author karma check (would require extra API call)
- Spam keyword pre-filter (could be done locally, zero-cost)
- Thread length minimum (trivial to add)

Status: **spam keyword pre-filter and length minimum = quick wins, TODO**

### Prompt Versioning

**Decision: Deferred (GAP-012 remains)**

Current priority order:
1. GAP-003 (EPG lock) — safety
2. Kill switch latency — safety
3. Cross-avatar deduplication — quality
4. Prompt versioning — observability (lower priority)

When implemented: PromptVersion table (id, prompt_key, version, text, created_at, active). Simple, no external tools.

---

## Questions From Analyst (Answered)

**Q: Advisory Locks or Redis Locks for GAP-003?**

A: Advisory Locks. Accepted. See implementation plan above.

---

*Filed by: Max (tech) | June 25, 2026*
