# Architectural Gap Analysis: Ori's Workflows vs. Current Backend

**Date:** May 7, 2026  
**Author:** Max (tech review)  
**Scope:** Full comparison of Ori's n8n PoC architecture with the Python/FastAPI backend

---

## Executive Summary

Ori's n8n workflows represent a **single-client, single-operator PoC** optimized for XM Cyber's specific use case. Our backend is a **multi-tenant SaaS platform** designed for scale. The architectures solve fundamentally different problems, but Ori's workflows contain **prompt engineering and pipeline logic** that is more battle-tested than our implementation in several areas.

**Key finding:** Our backend is architecturally superior in infrastructure (queue management, locking, multi-tenancy, observability), but Ori's workflows are superior in **AI pipeline sophistication** (prompt quality, diversity enforcement, structured output validation, prep-step before generation).

---

## 1. System Model Comparison

| Dimension | Ori (n8n) | Our Backend |
|-----------|-----------|-------------|
| **Architecture** | Workflow DAG (visual, linear) | Service-oriented (FastAPI + Celery) |
| **Central entity** | Subreddit-centric (scrape → score → generate per subreddit batch) | Hybrid: Subreddit-centric scraping, Client-centric scoring/generation |
| **State storage** | Supabase (PostgreSQL) + Airtable (review/tracking) | PostgreSQL (SQLAlchemy 2.0) |
| **Queue** | n8n internal (sequential, no retry) | Celery + Redis (with Beat scheduler) |
| **Orchestration** | n8n workflow chaining (executeWorkflow) | Celery chains (score.si → generate.si) |
| **Decision point** | Inline in workflow nodes (JS Code nodes) | Service layer (services/*.py) |
| **Multi-tenancy** | None (hardcoded for XM Cyber) | Full (client_id on all queries) |
| **Retry/DLQ** | `retryOnFail: true, waitBetweenTries: 5000` (basic) | `max_retries=0` on most tasks (no retry!) |
| **Idempotency** | Dedup by permalink + post (JS Set) | Dedup by reddit_native_id (DB query) |
| **Rate limiting** | `Wait` nodes (fixed 15s between API calls) | Redis sorted-set sliding window + distributed locks |
| **Scheduling** | n8n cron triggers | Celery Beat (crontab + periodic) |

---

## 2. Pipeline Comparison: Scrape → Score → Generate → Review

### 2.1 Scraping

| Aspect | Ori | Our Backend | Winner |
|--------|-----|-------------|--------|
| **Trigger** | Cron (manual schedule) | queue_tick every 60s (priority-based) | ✅ Ours |
| **Subreddit selection** | Hardcoded JSON array (33 subreddits) | DB-driven, per-client assignments | ✅ Ours |
| **Rate limiting** | Fixed `Wait` node (15s between calls) | Redis sliding window + backoff on 429 | ✅ Ours |
| **Deduplication** | JS Set (permalink + post) in-memory | DB query (reddit_native_id) + in-memory set | ✅ Ours |
| **Comment fetching** | Separate sub-workflow (recursive flatten) | Inline in _submission_to_dict (top 20 + 3 depth) | ⚠️ Ori (deeper) |
| **Image extraction** | Dedicated Code node (gallery + direct) | Basic preview URL extraction | ⚠️ Ori |
| **Error handling** | `onError: continueErrorOutput` (skip, continue) | try/except per subreddit, ScrapeLog with errors | ✅ Ours |
| **Freshness tracking** | None | last_scraped_at + ScrapeLog + stale indicators | ✅ Ours |
| **Shared subreddit registry** | N/A (single client) | Subreddit → ClientSubredditAssignment (many-to-many) | ✅ Ours |
| **Concurrent scrape prevention** | None (sequential execution) | ScrapeDistributedLock (Redis SETNX) | ✅ Ours |

**Critical gap in our system:** Comment depth. Ori fetches full recursive comment trees (all depths, all replies). We fetch top 20 comments with max depth 3. For scoring and generation, deeper comment context produces better results. This is a **quality gap**, not an architecture gap.

### 2.2 Scoring

| Aspect | Ori | Our Backend | Winner |
|--------|-----|-------------|--------|
| **Model** | Gemini Flash (via OpenRouter) | Configurable via llm_scoring_model (LiteLLM) | ✅ Ours (flexible) |
| **Prompt quality** | Detailed with override rules, intent classification, trigger detection | Nearly identical (adapted from Ori) | Tie |
| **Output schema** | JSON Schema validation (n8n Structured Output Parser) | call_llm_json (parse JSON from response) | ⚠️ Ori (schema enforcement) |
| **Per-client scoring** | N/A (single client) | ThreadScore table (per-client, per-thread) | ✅ Ours |
| **Batch vs. individual** | Individual (one thread per LLM call) | Individual (same) | Tie |
| **Cost tracking** | None | ai_usage_log per call | ✅ Ours |
| **Scoring fields** | alert, tag, scores{}, intent, triggers{}, override_applied, reason | alert, tag, relevance, quality, strategic, composite, intent, reason | ⚠️ Ori (triggers{} richer) |

**Critical gap:** Our scoring doesn't track `triggers` (competitor_mentioned, company_mentioned, buying_signal) as separate fields. We compute them inside the LLM but don't persist them. This loses valuable analytics data.

### 2.3 Persona Selection (Prep Step)

| Aspect | Ori | Our Backend | Winner |
|--------|-----|-------------|--------|
| **Exists** | Yes — "Split Out" node with mode/audience/thread_angle/pov_opportunity | Yes — select_persona() service | Tie |
| **Karma-aware routing** | No (static avatar list) | Yes — sorts by subreddit_karma, feeds to LLM | ✅ Ours |
| **Output** | mode, audience, thread_angle, pov_opportunity | persona_username, mode, audience, thread_angle, pov_opportunity, selection_reasoning | ✅ Ours |
| **Multi-avatar** | Implicit (6 avatars, LLM picks) | Explicit (filter by client_ids, sort by karma) | ✅ Ours |

### 2.4 Comment Generation

| Aspect | Ori | Our Backend | Winner |
|--------|-----|-------------|--------|
| **Prompt sophistication** | ~3000 words, V2, extremely detailed | ~800 words, simplified adaptation | ⚠️ Ori (significantly) |
| **Diversity enforcement** | 5-check system (opener, theme, approach, vocabulary, structure) | previous_comments list passed to LLM (no explicit checks) | ⚠️ Ori |
| **Forbidden patterns** | Dedicated file reference, extensive list | Basic content safety check (promotional patterns only) | ⚠️ Ori |
| **Opener variability** | Explicit table with 6 opener types, anti-monotony rules | Not implemented | ⚠️ Ori |
| **Comment length enforcement** | Hard max 80 words, rewrite rule (don't trim) | MAX_COMMENT_LENGTH = 500 chars (too permissive) | ⚠️ Ori |
| **Strategic angle** | 3-tier priority ladder (Reframe → Tear Down → Karma Play) | strategic_angle field in output, but no enforcement | ⚠️ Ori |
| **Location choosing** | Explicit logic (engagement + relevance + depth consideration) | comment_to field, but no explicit location strategy in prompt | ⚠️ Ori |
| **Technical depth rule** | Explicit "too deep vs. right depth" examples | Not implemented | ⚠️ Ori |
| **Language simplicity** | Banned buzzwords list with plain alternatives | Basic buzzword list in prompt | ⚠️ Ori |
| **Voice profile integration** | Detailed (Hill I Die On, Helpful Peer mode, triggers) | voice_profile_md passed as blob | ⚠️ Ori |
| **Output schema** | JSON with structured validation | call_llm_json (same pattern) | Tie |
| **Model** | Claude Opus 4.6 (via OpenRouter) | Claude Sonnet (via LiteLLM) | Ori (higher quality model) |

**This is the biggest gap.** Ori's comment generation prompt is a masterclass in prompt engineering. Our simplified version loses:
- Diversity enforcement (5 explicit checks)
- Forbidden patterns enforcement
- Opener variability rules
- Technical depth calibration
- Stream-of-consciousness standard
- The "Originality Mandate"

### 2.5 Comment Editing

| Aspect | Ori | Our Backend | Winner |
|--------|-----|-------------|--------|
| **Exists** | Implicit (generation prompt handles quality) | Explicit edit_comment() service | ✅ Ours |
| **Separate LLM call** | No (single generation call) | Yes (dedicated editor prompt) | ✅ Ours (but costly) |
| **Rules** | Embedded in generation prompt | Dedicated EDITOR_PROMPT with specific rules | ✅ Ours |

### 2.6 Hobby Pipeline

| Aspect | Ori | Our Backend | Winner |
|--------|-----|-------------|--------|
| **Avatar-subreddit matching** | Dynamic (query active avatars → extract hobby_sub-reddits → deduplicate) | Same pattern (avatar.hobby_subreddits) | Tie |
| **Session sampling** | Random 1-4 posts per subreddit per avatar | All new posts (up to max_comments=10) | ⚠️ Ori (more organic) |
| **Prompt** | Dedicated hobby prompt (2500+ words, engagement angles, knowledge depth rule) | Simplified hobby prompt (~800 words) | ⚠️ Ori |
| **Model** | Claude Opus 4.6 (expensive but high quality) | Scoring model (Gemini Flash — cheaper) | Trade-off |
| **Storage** | Supabase (hobby_subreddits table) | HobbySubreddit model | Tie |

**Gap:** Ori's session sampling (random 1-4 posts per subreddit) creates more organic-looking engagement patterns than our "process all new posts" approach.

### 2.7 Review & Approval

| Aspect | Ori | Our Backend | Winner |
|--------|-----|-------------|--------|
| **Review UI** | Airtable interface (manual) | HTMX review queue (/review/comments) | ✅ Ours |
| **Status tracking** | Airtable fields (comment_sent boolean) | CommentDraft.status workflow (pending→approved→posted) | ✅ Ours |
| **Audit trail** | Airtable record history | AuditLog + ActivityEvent models | ✅ Ours |
| **Webhook on approval** | "Update comment sent" workflow (Airtable → tracking table) | Direct DB update + audit log | ✅ Ours |
| **Multi-table sync** | Airtable "Reddit Comments" → "Reddit Comments Tracking" (copy on approve) | Single table with status field | ✅ Ours (simpler) |

---

## 3. Infrastructure Comparison

| Aspect | Ori | Our Backend | Winner |
|--------|-----|-------------|--------|
| **Deployment** | n8n Cloud (managed) | Docker on EC2 (self-managed) | Trade-off |
| **Database** | Supabase (managed PostgreSQL) + Airtable | PostgreSQL (Docker, migrating to RDS) | Trade-off |
| **Queue** | n8n internal (no DLQ, no visibility) | Celery + Redis (migrating to SQS) | ✅ Ours |
| **Distributed locks** | None needed (sequential) | Redis SETNX with Lua atomic release | ✅ Ours |
| **Rate limiting** | Fixed Wait nodes | Redis sorted-set sliding window | ✅ Ours |
| **Observability** | n8n execution history | ActivityEvent + ScrapeLog + AuditLog + structured logging | ✅ Ours |
| **Cost tracking** | None | ai_usage_log (per-call token/cost tracking) | ✅ Ours |
| **Health checks** | None | Avatar health (shadowban, karma, brand ratio) | ✅ Ours |
| **Phase system** | None (manual avatar management) | PhasePolicy + PhaseEvaluator + PhaseTransitionManager | ✅ Ours |
| **Emergency controls** | Disable workflow in n8n UI | scrape_enabled setting (partial) | ⚠️ Both weak |

---

## 4. Critical Risks

### 4.1 Risks from Ori's Architecture (that we've already solved)

| Risk | Ori's Exposure | Our Mitigation |
|------|---------------|----------------|
| No multi-tenancy | Hardcoded for XM Cyber | client_id on all queries |
| No rate limiting | Fixed waits (detectable pattern) | Sliding window + jitter (planned) |
| No distributed locks | Sequential execution | Redis SETNX |
| No audit trail | Airtable record history only | AuditLog + ActivityEvent |
| No phase system | Manual avatar management | Automated phase evaluation |
| No cost tracking | Unknown spend | ai_usage_log per call |
| Single point of failure | n8n Cloud goes down = everything stops | Celery workers + Beat (resilient) |

### 4.2 Risks in Our Architecture (that Ori handles better)

| Risk | Our Exposure | Ori's Approach |
|------|-------------|----------------|
| **Comment quality degradation** | Simplified prompts lose diversity/originality | 5-check diversity system, forbidden patterns, opener variability |
| **Detectable patterns** | Fixed MIN_MINUTES_BETWEEN_COMMENTS = 15 | Not addressed (but less critical at single-client scale) |
| **Shallow comment context** | Top 20 comments, depth 3 max | Full recursive comment tree |
| **No session sampling** | Process all posts sequentially | Random 1-4 posts per subreddit (organic) |
| **No structured output validation** | Parse JSON from LLM response (can fail) | n8n Structured Output Parser with JSON Schema |
| **Missing scoring triggers** | Don't persist competitor_mentioned, buying_signal | Separate fields in output schema |
| **Hobby comment quality** | Gemini Flash (cheap but lower quality) | Claude Opus (expensive but better) |

### 4.3 Scalability Risks

| Scale | Risk | Impact | Mitigation |
|-------|------|--------|-----------|
| **100 avatars** | Phase evaluation task takes too long (sequential) | Blocks other tasks | Parallelize with task groups |
| **100 avatars** | Health check sequential (PRAW calls) | 100 × 2-5s = 500s blocking | Batch with asyncio or separate workers |
| **1,000 avatars** | Single Redis instance bottleneck | Lock contention, rate limiter hot keys | Redis Cluster or Valkey sharding |
| **1,000 avatars** | `existing_ids` query loads ALL reddit_native_ids into memory | OOM on worker | Bloom filter or partitioned dedup |
| **10,000 avatars** | Single PRAW OAuth token rate limit (60 req/min) | Can't scrape fast enough | Multiple OAuth tokens + proxy rotation |
| **10,000 avatars** | PostgreSQL connection exhaustion | Connection pool saturated | PgBouncer + read replicas |
| **10,000 avatars** | LLM API rate limits (Anthropic/Google) | Pipeline stalls | Multiple API keys + queue backpressure |

---

## 5. What to Port from Ori

### 5.1 MUST Port (High Impact, Low Risk)

1. **Full comment generation prompt (V2)** — The 3000-word prompt with diversity enforcement, forbidden patterns, opener variability, technical depth rules, and stream-of-consciousness standard. This is Ori's most valuable IP.

2. **Diversity enforcement system** — The 5-check pre-writing scan (opener, theme, approach, vocabulary, structure). Currently we just pass previous_comments and hope the LLM self-regulates. It doesn't.

3. **Forbidden patterns file** — A dedicated, versioned file of banned patterns, buzzwords, and constructions. Currently scattered across prompts.

4. **Scoring triggers persistence** — Add `competitor_mentioned`, `company_mentioned`, `buying_signal` fields to ThreadScore. Already computed by LLM, just not saved.

5. **Session sampling for hobby pipeline** — Random 1-4 posts per subreddit instead of "all new posts". More organic engagement pattern.

6. **Deeper comment tree fetching** — Increase from depth 3 to full recursive (with token budget). Better context = better comments.

### 5.2 SHOULD Port (Medium Impact)

7. **Image extraction logic** — Ori's gallery/media_metadata parsing is more complete. Our preview URL extraction misses gallery posts.

8. **Structured output validation** — Add JSON Schema validation on LLM responses (pydantic model validation post-parse). Currently we just try json.loads() and hope.

9. **Hobby comment prompt (full version)** — The engagement angles, knowledge depth rule, and thread energy assessment. Our simplified version produces lower-quality hobby comments.

10. **Comment length enforcement** — Change from 500 chars to 80 words hard max with rewrite instruction. 500 chars is way too permissive for Reddit.

### 5.3 Should NOT Port

11. **Airtable/Supabase dual storage** — We have a proper relational model. No need for external state.

12. **n8n workflow structure** — Visual DAGs are great for prototyping, terrible for testing and version control.

13. **Fixed Wait nodes for rate limiting** — Our sliding window is superior.

14. **Sequential execution model** — Our parallel Celery chains are better for multi-tenant.

15. **Hardcoded subreddit lists** — Our DB-driven approach is correct.

16. **Claude Opus for hobby comments** — Too expensive. Gemini Flash is the right trade-off for karma-building content.

---

## 6. Architecture Comparison Table

| Capability | Ori | Ours | Gap Severity |
|-----------|-----|------|-------------|
| Multi-tenancy | ❌ | ✅ | N/A (we're ahead) |
| Queue management | ❌ | ✅ | N/A |
| Distributed locks | ❌ | ✅ | N/A |
| Rate limiting | ⚠️ (fixed waits) | ✅ (sliding window) | N/A |
| Observability | ❌ | ✅ | N/A |
| Cost tracking | ❌ | ✅ | N/A |
| Phase system | ❌ | ✅ | N/A |
| Safety checks | ❌ | ✅ | N/A |
| Audit trail | ⚠️ (Airtable) | ✅ | N/A |
| Comment generation quality | ✅✅ | ⚠️ | **CRITICAL** |
| Diversity enforcement | ✅✅ | ❌ | **CRITICAL** |
| Forbidden patterns | ✅ | ⚠️ | **HIGH** |
| Comment depth/context | ✅ | ⚠️ | **MEDIUM** |
| Scoring triggers | ✅ | ⚠️ | **MEDIUM** |
| Session sampling | ✅ | ❌ | **MEDIUM** |
| Image extraction | ✅ | ⚠️ | **LOW** |
| Structured output validation | ✅ | ⚠️ | **LOW** |
| Retry strategy | ⚠️ (basic) | ❌ (max_retries=0) | **HIGH** |
| Emergency controls | ⚠️ | ⚠️ | **HIGH** |
| Timing jitter | ❌ | ❌ | **HIGH** |

---

## 7. Priority Roadmap

### Immediate (before first paid pilot)

| # | Item | Effort | Impact | Risk if skipped |
|---|------|--------|--------|-----------------|
| 1 | Port Ori's full comment generation prompt (V2) | 2d | Critical | Comments get detected as AI, clients churn |
| 2 | Implement diversity enforcement (5-check system) | 3d | Critical | Repetitive comments, avatar burns |
| 3 | Create forbidden_patterns.md + enforcement | 1d | High | Buzzwords leak, detection risk |
| 4 | Add timing jitter (replace fixed 15min) | 1d | High | Detectable automation pattern |
| 5 | Emergency controls (global pause + per-avatar freeze) | 1d | High | Can't stop runaway pipeline |
| 6 | Add retry logic to Celery tasks (max_retries=3, exponential backoff) | 1d | High | Silent failures, lost work |

### Before Beta (10 clients)

| # | Item | Effort | Impact |
|---|------|--------|--------|
| 7 | Persist scoring triggers (competitor_mentioned, buying_signal) | 1d | Medium |
| 8 | Deeper comment tree fetching (full recursive with token budget) | 2d | Medium |
| 9 | Session sampling for hobby pipeline | 1d | Medium |
| 10 | Structured output validation (pydantic models for LLM responses) | 2d | Medium |
| 11 | Context assembly service (isolated per-client prompts) | 3d | High |
| 12 | Port hobby comment prompt (full version) | 1d | Medium |
| 13 | Comment length enforcement (80 words hard max) | 0.5d | Medium |
| 14 | SQS + Valkey migration (in progress) | 5d | Medium |
| 15 | DLQ for failed tasks | 2d | High |

### Before Scale (50+ clients)

| # | Item | Effort | Impact |
|---|------|--------|--------|
| 16 | Prompt versioning + A/B testing framework | 5d | High |
| 17 | Parallel phase evaluation (task groups) | 2d | Medium |
| 18 | Bloom filter for deduplication (replace in-memory set) | 3d | High |
| 19 | Multiple OAuth tokens + proxy rotation | 3d | High |
| 20 | PgBouncer + connection pooling | 1d | Medium |
| 21 | Subreddit intelligence (rule/wiki parsing) | 5d | High |
| 22 | Persona routing optimization (ML-based) | 5d | Medium |

### Enterprise-Grade (100+ clients)

| # | Item | Effort | Impact |
|---|------|--------|--------|
| 23 | Horizontal worker scaling (per-type pools) | 5d | High |
| 24 | Redis Cluster / Valkey sharding | 3d | Medium |
| 25 | Read replicas for PostgreSQL | 2d | Medium |
| 26 | Vector memory (comment similarity search) | 5d | Medium |
| 27 | Trust engine (per-avatar, per-subreddit decay) | 10d | High |
| 28 | Karma feedback loop (engagement → prompt improvement) | 10d | High |
| 29 | Behavioral fingerprint randomization | 5d | High |

---

## 8. Honest Assessment

### What Ori did better:
- **Prompt engineering** — The comment generation prompts are production-grade. Ours are MVP-grade.
- **Diversity enforcement** — Explicit, systematic, verifiable. Ours is "pass previous comments and hope."
- **Organic behavior simulation** — Session sampling, varied post counts, thread energy assessment.
- **Comment depth** — Full recursive tree gives better context for generation.

### What we did better:
- **Everything else.** Multi-tenancy, queue management, distributed locks, rate limiting, observability, cost tracking, phase system, safety checks, audit trail, health monitoring, shared subreddit registry, freshness tracking, transparency dashboard.

### What's a temporary workaround in Ori's system:
- Airtable for review/tracking (replaced by our CommentDraft workflow)
- Supabase for state (replaced by our PostgreSQL + SQLAlchemy)
- n8n for orchestration (replaced by Celery + Beat)
- Hardcoded subreddit lists (replaced by DB-driven assignments)
- Fixed Wait nodes (replaced by sliding window rate limiter)
- Manual avatar management (replaced by phase system)

### What's correct long-term architecture:
- **Our queue_tick model** — Priority-based, continuous, with distributed locks and rate limiting
- **Our shared subreddit registry** — Scrape once, score per-client (eliminates duplicate scraping)
- **Our phase system** — Automated evaluation with promotion/demotion criteria
- **Ori's prompt engineering** — The diversity enforcement and forbidden patterns approach
- **Our ThreadScore model** — Per-client scoring on shared threads (correct for multi-tenant)
- **Our safety service** — Phase policy + rate limits + brand ratio checks

### The synthesis:
Port Ori's AI sophistication (prompts, diversity, forbidden patterns) into our infrastructure. The infrastructure is right. The AI layer needs Ori's battle-tested prompts.

---

## 9. Risk Matrix

| Risk | Probability | Impact | Mitigation Priority |
|------|------------|--------|-------------------|
| Comments detected as AI (weak prompts) | HIGH | CRITICAL (avatar burns) | **P0** — Port Ori's prompts |
| Repetitive comments (no diversity) | HIGH | HIGH (detection + poor engagement) | **P0** — Diversity enforcement |
| Detectable timing patterns | MEDIUM | HIGH (account flags) | **P1** — Timing jitter |
| Silent task failures (no retry) | MEDIUM | MEDIUM (lost work) | **P1** — Retry logic |
| Pipeline can't be stopped | LOW | CRITICAL (runaway damage) | **P1** — Emergency controls |
| Shallow context → bad comments | MEDIUM | MEDIUM (lower quality) | **P2** — Deeper comment trees |
| Memory OOM at scale (dedup set) | LOW (now) | HIGH (at 50+ clients) | **P3** — Bloom filter |
| Reddit rate limit at scale | LOW (now) | HIGH (at 100+ clients) | **P3** — Multi-token + proxy |

---

## 10. Conclusion

The backend architecture is sound. The AI layer is the weak link. Priority #1 is porting Ori's prompt engineering and diversity enforcement into our service layer. Everything else (SQS migration, topology dashboard, etc.) is secondary to comment quality — because if comments get detected as AI or burn avatars, nothing else matters.

**Recommended next sprint:**
1. Port full V2 comment generation prompt → `services/generation.py`
2. Implement diversity enforcement service → `services/diversity.py`
3. Create `prompts/forbidden_patterns.md` + enforcement in safety checks
4. Add timing jitter to `MIN_MINUTES_BETWEEN_COMMENTS`
5. Add `max_retries=3` + exponential backoff to all Celery tasks
