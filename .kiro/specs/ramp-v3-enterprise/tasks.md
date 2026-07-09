# RAMP v3.0 Enterprise — Implementation Tasks

## Phase 1: Core Engagement (3 weeks)

### Task 1.1: Data Model + Migrations
- [ ] Create Alembic migration `v3_01_content_graph`:
  - `content_nodes` table (with pgvector embedding column)
  - `content_relationships` table
  - Indexes: platform_id, client_id+status, direction, subreddit, embedding (ivfflat)
- [ ] Create migration `v3_02_opportunities`:
  - `opportunities` table (with score CHECK 0-1)
  - `opportunity_status_history` table
- [ ] Create migration `v3_03_decisions`:
  - `decision_events` table
  - `policies` table
  - `generation_runs` table
  - `context_snapshots` table
- [ ] Create migration `v3_04_memory`:
  - `avatar_memory` table (with pgvector embedding)
  - `community_intelligence` table
  - `geo_reports` table
- [ ] Create SQLAlchemy models for all new tables
- [ ] Verify: `alembic heads` = 1, all compile, all import

### Task 1.2: Content Graph — Reddit Ingestion
- [ ] Create `app/services/v3/content_graph.py`:
  - `ingest_reddit_post(post_data) → ContentNode`
  - `ingest_reddit_comment(comment_data, parent_id) → ContentNode + relationship`
  - `build_thread_graph(thread_id, depth=5) → list[ContentNode]`
- [ ] Refactor `scraping.py` task to dual-write: existing tables + content_nodes
- [ ] Compute embedding on ingest (async, background) using `text-embedding-004`
- [ ] Status workflow: new content → status=`discovered`
- [ ] Platform metadata stored in JSONB: ups, created_utc, url, num_comments, author_karma

### Task 1.3: Opportunity Engine (Basic)
- [ ] Create `app/services/v3/opportunity_engine.py`:
  - `scan_new_content(client_id) → list[Opportunity]`
  - `score_opportunity(opp) → float` (multi-factor: relevance, freshness, competition, risk)
  - `expire_stale_opportunities() → int`
- [ ] Opportunity type detection:
  - `brand_mention`: client brand/product mentioned in content body
  - `question`: content is a question matching client keywords
  - `pain_point`: negative sentiment + keyword match
  - `discussion`: high engagement + keyword relevance
- [ ] TTL per type: question=48h, brand_mention=24h, discussion=72h, pain_point=72h
- [ ] Integration with existing `smart_scoring.py` (bridge: old scores → opportunity scores)

### Task 1.4: Decision Engine + Policy Engine
- [ ] Create `app/services/v3/policy_engine.py`:
  - `evaluate(opportunity, avatar, context) → PolicyResult`
  - Load policies from DB (cache in-memory, refresh every 60s)
  - Priority-ordered evaluation (highest first, first match wins)
- [ ] Create `app/services/v3/decision_engine.py`:
  - `decide(opportunity, avatar) → DecisionEvent`
  - Build context: phase, karma, sub risk, time, budget remaining
  - Apply policy engine
  - Log decision_event with full reasoning JSONB
- [ ] Seed system policies (priority 100):
  - Phase gates (existing `safety_blocks.py` logic)
  - Fitness gate rules (existing `fitness_gate.py` logic)
  - Budget exhaustion check
  - Dangerous hours block
- [ ] Structural invariant: no content_node with status=`generated` without prior decision_event

### Task 1.5: Generation Router + Semantic Cache
- [ ] Create `app/services/v3/generation_router.py`:
  - `route(opportunity, avatar, policy_action) → GenerationConfig`
  - Model selection: risk-based (high→Claude, medium→Flash, low→Flash Lite)
  - Returns: model, temperature, max_tokens, require_review flag
- [ ] Create `app/services/v3/semantic_cache.py`:
  - `check_cache(context_embedding, intent, subreddit) → Optional[CachedGeneration]`
  - `store_generation(content_id, embedding, text, metadata)`
  - Similarity threshold: 0.92 cosine (tunable)
  - Cache TTL: 30 days
- [ ] Integrate with existing `generation.py`:
  - Before calling LLM, check cache
  - On cache hit: adapt with lightweight model (Flash Lite)
  - On miss: full generation via existing `call_llm()`
  - Log to `generation_runs` table (replaces current per-call logging pattern)
- [ ] All calls through `call_llm()` + `log_ai_usage()` (P3 invariant maintained)

### Task 1.6: Human Review Integration
- [ ] Content nodes with status=`review` appear in existing review queue
- [ ] Approve action: status → `approved` → triggers EPG slot creation (existing flow)
- [ ] Reject action: status → `rejected`, log reason
- [ ] Edit action: update body, create `style` memory for avatar
- [ ] Extension popup: content_nodes (outbound, status=review) shown in "Review Drafts"
- [ ] Backward compatible: existing CommentDraft workflow continues working during migration

---

## Phase 2: Context & Memory (2 weeks)

### Task 2.1: Reply Threading (Depth)
- [ ] Extend Content Graph to model reply chains (depth tracking)
- [ ] `content_relationships` with `reply_to` type for parent-child
- [ ] Thread reconstruction: `get_thread_context(content_id, max_depth=5) → list[ContentNode]`
- [ ] Opportunity scoring includes thread depth factor (deep = less visible = lower score)
- [ ] Context for generation includes full parent chain (not just immediate parent)

### Task 2.2: Context Snapshots
- [ ] Create `app/services/v3/context_snapshot.py`:
  - `capture(content_id, depth) → ContextSnapshot`
  - Stores: thread title, parent chain, avatar identity, policy applied, opportunity metadata
  - Embedding computed from full snapshot text
- [ ] Automatically captured at generation time (before LLM call)
- [ ] Admin view: "Why was this generated?" shows snapshot
- [ ] Retention: 90 days (archival beyond, keep embedding + metadata)

### Task 2.3: Avatar Memory (Basic)
- [ ] Create `app/services/v3/memory_service.py`:
  - `retrieve(avatar_id, context_text, k=5) → list[AvatarMemory]`
  - `store(avatar_id, type, content, importance) → AvatarMemory`
  - `decay_all() → int` (reduce importance of old unused memories)
  - `evict(avatar_id, max_count=200)` (remove lowest importance)
- [ ] Memory injection into generation prompt (after context, before task instruction)
- [ ] Memory creation triggers:
  - Human edit → type=`style`, importance=0.8
  - Karma ≥ 5 → type=`previous_interaction`, importance based on karma
  - Admin-set → type=`fact` or `forbidden_topic`, importance=1.0
- [ ] Migrate existing `CorrectionPattern` → avatar_memory (type=style)
- [ ] Migrate existing `EditRecord` → avatar_memory (type=style, lower importance)
- [ ] Weekly decay task: importance *= 0.95 for memories not accessed in 14 days

### Task 2.4: Enhanced Opportunity Types
- [ ] Add types: `competitor` (competitor brand mentioned), `trend` (volume spike)
- [ ] Competitor detection: use existing `geo_competitors` data for keyword matching
- [ ] Trend detection: content volume per topic per subreddit, flag 2x spike in 7d window
- [ ] Opportunity reassessment: when new comments added to source thread, re-score
- [ ] "Monitor" decision → re-evaluate after 4h (new context may upgrade to "engage")

---

## Phase 3: Community Intelligence (2 weeks)

### Task 3.1: Community Intelligence Engine
- [ ] Create `app/services/v3/intelligence_engine.py`:
  - `analyze_content_batch(content_nodes) → list[CommunityIntelligence]`
  - Topic extraction (LLM-based, Gemini Flash)
  - Sentiment analysis (per topic, per subreddit)
  - Volume tracking (daily counts per topic)
- [ ] Weekly intelligence report generation:
  - Top 5 trending topics per client
  - Top 3 pain points (negative sentiment + high volume)
  - Competitor mention changes (week-over-week)
- [ ] Feed intelligence into opportunity scoring:
  - Trending topic + keyword match → score boost +0.15
  - Pain point in client's domain → auto-create opportunity (type=pain_point)

### Task 3.2: GEO Reports Integration
- [ ] Extend existing `visibility_report.py` to write to `geo_reports` table
- [ ] Structure: weekly reports with JSONB data (trends, competitors, pain_points sections)
- [ ] Link community_intelligence records to source content_nodes
- [ ] Competitor Share-of-Voice calculated from intelligence data (not just GEO batches)

### Task 3.3: Client Intelligence Dashboard
- [ ] New portal page: `/clients/{id}/intelligence`
- [ ] Sections:
  - Trending topics in client's communities (bar chart, 7d)
  - Pain points detected (list with sentiment score)
  - Competitor activity (mentions per competitor per week)
  - Opportunity funnel (discovered → qualified → completed, Sankey)
- [ ] HTMX lazy-load per section
- [ ] Data source: `community_intelligence` + `opportunities` tables

---

## Phase 4: Multi-Platform & Advanced Policies (2 weeks)

### Task 4.1: Post Generation
- [ ] Extend generation to produce Reddit posts (not just comments)
- [ ] Opportunity type `create` → full post generation (title + body)
- [ ] Policy controls: `allow_post=true` required, higher review threshold
- [ ] Target subreddit selection based on opportunity source + client strategy

### Task 4.2: Policy Engine UI Editor
- [ ] Admin page: `/admin/clients/{id}/policies`
- [ ] List active policies with priority, enable/disable toggle
- [ ] Create/edit policy form:
  - Condition builder (dropdowns for field, operator, value)
  - Action configuration (checkboxes + model selector)
  - Priority slider (1-80, system policies shown but not editable)
- [ ] Policy validation on save (schema check, conflict detection)
- [ ] Audit log: policy changes tracked in `audit_log`

### Task 4.3: Platform Abstraction
- [ ] Create `app/services/v3/platforms/base.py` — abstract platform adapter
- [ ] Create `app/services/v3/platforms/reddit.py` — Reddit adapter (wraps current PRAW)
- [ ] Platform adapter interface:
  - `scrape(target, limit) → list[RawContent]`
  - `post(content, target) → PlatformResult`
  - `get_metrics(platform_id) → Metrics`
- [ ] Content nodes gain `platform` field (default: "reddit")
- [ ] Opportunity Engine platform-agnostic (works with any adapter output)
- [ ] Twitter adapter (stub — Phase 4+ implementation when business requires)

### Task 4.4: Content Relationships (Full Graph)
- [ ] Add relationship types: `mentions`, `similar_to`, `about_topic`, `competitor_reference`
- [ ] `similar_to`: computed via embedding cosine similarity > 0.85 (batch, nightly)
- [ ] `about_topic`: extracted from intelligence engine topic clustering
- [ ] `competitor_reference`: content mentioning known competitors
- [ ] Graph queries: "find all content about [topic] in [subreddit] last 7d" via recursive CTE

---

## Phase 5: Enterprise Features (2 weeks)

### Task 5.1: Decision Log Export / API
- [ ] REST API: `GET /api/v3/decisions?client_id=X&from=&to=` (paginated, JSON)
- [ ] CSV export: decision_events with reasoning flattened
- [ ] Webhook: POST to client URL on each decision (enterprise tier)
- [ ] Audit compliance: 1 year retention minimum, 5 years for enterprise

### Task 5.2: Advanced RBAC + SSO
- [ ] Extend existing RBAC with policy management permissions:
  - `policy_viewer`: can see policies, cannot edit
  - `policy_editor`: can create/edit policies (priority ≤ 80)
  - `policy_admin`: can create/edit all non-system policies
- [ ] SSO readiness: SAML/OIDC integration point (enterprise tier)
- [ ] API key management: per-client API keys with scope restrictions

### Task 5.3: Analytics Layer
- [ ] Materialized views for common dashboard queries (refresh hourly)
- [ ] Time-series aggregation: opportunities per day, decisions per type, generation cost per day
- [ ] Client-facing metrics: engagement rate, karma earned, visibility growth
- [ ] Admin metrics: cost per decision, cache hit rate, model distribution
- [ ] Consider ClickHouse migration when > 1M events/month

### Task 5.4: Scaling Preparation
- [ ] Content node partitioning by client_id (when > 10M rows)
- [ ] Read replica for analytics queries
- [ ] Redis cluster for semantic cache overflow (when PG vector search > 500ms)
- [ ] Worker auto-scaling based on opportunity queue depth
- [ ] Connection pooling optimization (PgBouncer when > 50 concurrent)

---

## Migration Tasks (Run in Parallel with Phase 1)

### Task M1: Dual-Write Mode
- [ ] Modify scraping tasks: write to both `reddit_threads` AND `content_nodes`
- [ ] Modify generation: write to both `comment_drafts` AND `content_nodes`
- [ ] Feature flag: `v3_dual_write_enabled` (default: false, gradual rollout)
- [ ] Verification: count comparison (old tables vs new tables, should match)

### Task M2: Historical Data Backfill
- [ ] Script: `_migrate_threads_to_content_nodes.py`
  - `reddit_threads` → content_nodes (direction=inbound, status based on existing data)
  - `hobby_subreddits` → content_nodes (direction=inbound)
  - `comment_drafts` → content_nodes (direction=outbound)
  - Relationships: draft → thread = reply_to
- [ ] Script: `_migrate_scores_to_opportunities.py`
  - `thread_scores` where tag=engage → opportunities (type=discussion, status=completed)
  - `opportunities` (EPG model) → new opportunities table
- [ ] Script: `_migrate_patterns_to_memory.py`
  - `correction_patterns` → avatar_memory (type=style, importance=0.8)
  - `edit_records` → avatar_memory (type=style, importance=0.6)
- [ ] Script: `_migrate_safety_to_policies.py`
  - Existing phase gates → policies (priority=100)
  - Existing fitness gate rules → policies (priority=100)
  - Existing `auto_approve_drafts` logic → policies (priority=50)
- [ ] All scripts idempotent (can re-run safely)
- [ ] Verification queries comparing old system output vs new system output

### Task M3: Switch Pipeline
- [ ] Replace `smart_scoring.py` calls with Opportunity Engine scan
- [ ] Replace `generation.py` direct calls with Decision Engine → Generation Router
- [ ] Replace `fitness_gate.py` checks with Policy Engine evaluation
- [ ] Feature flag: `v3_pipeline_enabled` (switches between old and new pipeline)
- [ ] Gradual rollout: one client at a time

### Task M4: Cleanup (after 90 days)
- [ ] Archive old tables (pg_dump specific tables → S3/backup)
- [ ] Drop old tables OR rename to `_archive_*`
- [ ] Remove dual-write code
- [ ] Remove feature flags (v3 becomes default)
- [ ] Update all steering docs to reflect v3 architecture
