---
inclusion: manual
---

# RAMP v3.0 Enterprise — North Star (NOT for immediate implementation)

## Status: DEFERRED — Architecture Orientation Document

**Decision (July 8, 2026):** v3.0 is the long-term architectural target. NOT the current priority. Current priority = first paying client on existing architecture.

**Trigger for revisiting:** 5+ paying clients AND recurring pain points that map to v3.0 components.

**Same category as:** AWS migration (deferred until 100+ avatars or enterprise requirement).

---

## What v3.0 Solves (When We Need It)

| Current Limitation | v3.0 Solution | When It Hurts |
|---|---|---|
| Flat tables (`reddit_threads` + `hobby_subreddits`) don't model relationships | Content Graph (nodes + edges) | When we need "find all discussions about topic X across threads" or multi-platform |
| Opportunities are implicit (scoring result, not first-class) | Opportunity Engine with lifecycle | When clients ask "why didn't you engage on THAT thread?" and we can't explain |
| Safety gates hardcoded in Python | Declarative Policy Engine | When different clients need different engagement rules without code changes |
| Self-learning loop is pattern-based (regex extraction) | Avatar Memory with semantic search | When edit patterns don't generalize and we need richer few-shot |
| No decision audit trail | Decision Log with reasoning | When enterprise clients require compliance/audit export |
| Single platform (Reddit only) | Platform abstraction layer | When business requires Twitter/LinkedIn expansion |
| No semantic caching | Generation Router + Cache | When LLM costs exceed $500/mo and 30%+ calls are similar contexts |

---

## Architecture Target (Summary)

```
Current: SCRAPE → SCORE → GENERATE → REVIEW → POST → MEASURE → LEARN
                  (linear pipeline, flat data)

Target:  DISCOVER → GRAPH → INTELLIGENCE → OPPORTUNITIES → DECISIONS → GENERATE → REVIEW → POST → FEEDBACK → MEMORY
                  (graph-based, decision-centric, multi-platform)
```

Key new components:
- **Content Graph** — unified nodes + relationships (replaces reddit_threads + hobby_subreddits)
- **Opportunity Engine** — first-class lifecycle object with scoring, expiration, audit
- **Decision Engine** — explicit engage/ignore/monitor decisions with reasoning JSONB
- **Policy Engine** — declarative JSON rules replacing hardcoded safety gates
- **Avatar Memory** — semantic vector store replacing CorrectionPattern/EditRecord
- **Generation Router** — risk-based model selection + semantic cache
- **Community Intelligence** — trends, pain points, competitor signals as standalone value

---

## Incremental Adoption Path (Not All-or-Nothing)

When the time comes, adopt pieces incrementally:

| Priority | Component | Prerequisite | Standalone Value |
|----------|-----------|--------------|------------------|
| 1 | **Opportunity as first-class** | 3+ clients, "why no engagement" questions | Audit trail, client transparency |
| 2 | **Decision Log** | Enterprise client requirement | Compliance, explainability |
| 3 | **Avatar Memory** | Self-learning loop hitting limits (same patterns, no improvement) | Better generation quality |
| 4 | **Policy Engine** | 2+ clients needing different engagement rules | No-deploy config changes |
| 5 | **Content Graph** | Multi-platform requirement OR relationship queries needed | Thread context, cross-reference |
| 6 | **Generation Router + Cache** | LLM costs > $500/mo | 30-40% cost reduction |
| 7 | **Community Intelligence** | Clients paying for reports, not just engagement | Revenue from intelligence alone |
| 8 | **Platform Abstraction** | Business decision to expand beyond Reddit | Twitter/LinkedIn support |

---

## Pricing Evolution

| Stage | Pricing | When |
|-------|---------|------|
| **Now** | $149-$1,499 (current plans) | Pre-revenue, proving PMF |
| **After 5 clients** | Consider $399 minimum (drop Seed) | Proven value, raise floor |
| **After v3.0 Phase 1-2** | $499-$1,999 (Opportunity Intelligence) | Decision audit + intelligence as value |
| **After v3.0 Phase 3-5** | $1,999-$5,000+ (Enterprise) | Full platform with API, SSO, audit |

---

## Economics Reminder

Current unit economics (from `ai-cost-optimization/unit-economics.md`):
- 1 avatar Phase 2: ~$9.84/mo AI cost
- Formula: ~$8.50 × avatars + $3-5 overhead
- 85% of cost = Comment Generation (Claude Sonnet)
- At $149/mo Seed plan with 1 avatar: 93% margin

v3.0 target economics:
- ~$5.20/avatar/mo (with caching + Flash routing for low-risk)
- At $499/mo Starter: >99% margin
- Semantic cache reduces costs 30-40% after 30 days

---

## Spec Location

Full architectural spec (for when we're ready): `.kiro/specs/ramp-v3-enterprise/`
- `requirements.md` — 8 functional + 4 non-functional requirements with mermaid diagrams
- `design.md` — full data model, service interfaces, migration strategy
- `tasks.md` — 5 phases + migration tasks with checklists

---

## What NOT To Do Before v3.0 Trigger

1. ❌ Rewrite data model speculatively
2. ❌ Build Policy Engine without enterprise client asking for it
3. ❌ Add vector embeddings to content before semantic cache is needed
4. ❌ Abstract platform layer before second platform is confirmed
5. ❌ Build Community Intelligence before clients pay for reports

## What IS OK To Do Now (v3.0-Compatible Choices)

1. ✅ When writing new code — keep services thin and separable (helps future extraction)
2. ✅ When adding safety gates — document them as "future policy candidates" in comments
3. ✅ When storing AI decisions — include reasoning in JSONB (cheap, future-proof)
4. ✅ When new LLM operation — log everything (`log_ai_usage()` — already done)
5. ✅ When fixing scoring — treat thread_scores as proto-opportunities conceptually
6. ✅ When building for new client — note where current arch creaks (evidence for trigger)
