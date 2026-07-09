# RAMP v3.0 Enterprise — Requirements

## Overview

RAMP v3.0 transforms the platform from a linear content pipeline (scrape→score→generate→post) into a **decision intelligence platform** for brand community engagement. The system shifts from "generate comments" to "make engagement decisions" — where the decision itself is the product.

## Architecture Vision

```mermaid
graph TD
    subgraph Sources["Data Sources"]
        REDDIT[Reddit API]
        TWITTER[Twitter API — Phase 4]
        LINKEDIN[LinkedIn API — Phase 4]
    end

    subgraph Graph["Content Graph Layer"]
        DISC[Discovery Engine] --> CN[(Content Nodes)]
        CN --> CR[(Content Relationships)]
    end

    subgraph Intel["Community Intelligence"]
        CR --> IE[Intelligence Engine]
        IE --> GEO[(GEO Reports)]
        IE --> TRENDS[(Trend Signals)]
    end

    subgraph Oppty["Opportunity Layer"]
        IE --> OE[Opportunity Engine]
        OE --> OSH[(Status History)]
    end

    subgraph Decision["Policy & Decision Layer"]
        OE --> DE[Decision Engine]
        POL[(Policies)] --> DE
        DE --> DL[(Decision Log)]
        DE --> ACT{Action?}
    end

    subgraph Gen["Generation Layer"]
        ACT -->|engage/create| GR[Generation Router]
        GR --> SC[Semantic Cache]
        SC --> LLM[LLM Generation]
        LLM --> GRuns[(Generation Runs)]
        LLM --> VAL[Validator]
    end

    subgraph Review["Human Review"]
        VAL --> RQ[Review Queue]
        RQ -->|approved| PUB[Publisher]
        RQ -->|rejected| REJ[Rejection Log]
    end

    subgraph Feedback["Feedback & Learning"]
        PUB --> FB[Metrics Collector]
        FB --> MEM[(Avatar Memory)]
        MEM --> IE
        FB --> SC
    end

    subgraph Analytics["Analytics"]
        PUB --> METRICS[(Time-Series Store)]
        FB --> METRICS
        METRICS --> DASH[Client Dashboards]
    end

    REDDIT --> DISC
    TWITTER --> DISC
    LINKEDIN --> DISC

    classDef newLayer fill:#2d6a4f,stroke:#1b4332,color:#fff;
    classDef existsLayer fill:#1d3557,stroke:#0d1b2a,color:#fff;
    class OE,DE,POL,DL,MEM,SC,IE newLayer;
    class DISC,CN,RQ,PUB,FB existsLayer;
```

## Core Entities

### R1: Content Graph

**Requirement:** Replace flat `reddit_threads` + `hobby_subreddits` tables with a unified Content Graph model.

```mermaid
erDiagram
    CONTENT_NODE {
        uuid id PK
        uuid client_id FK
        uuid avatar_id FK "nullable"
        text platform
        text platform_id
        text direction "inbound | outbound"
        text status "discovered | scored | generated | review | approved | published | rejected"
        text title
        text body
        text author
        jsonb platform_metadata
        timestamp created_at
        timestamp updated_at
    }

    CONTENT_RELATIONSHIP {
        uuid id PK
        uuid from_content_id FK
        uuid to_content_id FK
        text relation_type "reply_to | mentions | similar_to | about_topic | competitor_reference"
        jsonb metadata
        timestamp created_at
    }

    CONTENT_NODE ||--o{ CONTENT_RELATIONSHIP : "from"
    CONTENT_NODE ||--o{ CONTENT_RELATIONSHIP : "to"
    CLIENT ||--o{ CONTENT_NODE : owns
    AVATAR ||--o{ CONTENT_NODE : authored
```

**Acceptance criteria:**
- [ ] All scraped Reddit posts/comments stored as `content_nodes` with `direction=inbound`
- [ ] Generated content stored as `content_nodes` with `direction=outbound`
- [ ] Reply chains modeled via `content_relationships` (type=`reply_to`)
- [ ] Thread context reconstructable from graph traversal (max depth 5)
- [ ] Existing `reddit_threads` and `hobby_subreddits` data migrated to content_nodes
- [ ] Status workflow: discovered → scored → generated → review → approved → published

### R2: Opportunity Engine (First-Class Object)

**Requirement:** Opportunities are explicit, trackable entities with lifecycle — not implicit results of scoring.

```mermaid
stateDiagram-v2
    [*] --> Discovered: New signal detected
    Discovered --> Qualified: Passes initial filters
    Qualified --> Actionable: Score ≥ threshold + policy allows
    Actionable --> Assigned: Avatar selected
    Assigned --> Completed: Content published
    Actionable --> Expired: TTL exceeded
    Qualified --> Expired: TTL exceeded
    Discovered --> Expired: No action within window
    
    note right of Qualified
        Score recalculated on
        context change (new comments,
        sentiment shift)
    end note
```

**Acceptance criteria:**
- [ ] `opportunities` table with type enum: brand_mention, question, pain_point, competitor, trend, discussion
- [ ] Status lifecycle: discovered → qualified → actionable → assigned → completed/expired
- [ ] Score (0.0–1.0) recalculated when source content changes
- [ ] Expiration (TTL per type, configurable)
- [ ] Full status history in `opportunity_status_history` table
- [ ] Every status transition has `changed_by` (system/user) and `reason`
- [ ] Opportunity links back to source `content_node`

### R3: Decision Engine + Decision Log

**Requirement:** Every engagement decision is explicit, reasoned, and auditable.

```mermaid
flowchart LR
    OPP[Opportunity<br/>score=0.72] --> DE{Decision Engine}
    POL[Active Policies] --> DE
    CTX[Context<br/>avatar karma, time,<br/>sub risk, phase] --> DE
    DE -->|decision=engage| GEN[Generation Router]
    DE -->|decision=ignore| LOG[Decision Log<br/>with reasoning]
    DE -->|decision=monitor| WATCH[Re-evaluate later]
    
    LOG --- REASON["reasoning: {<br/>&nbsp;&nbsp;score: 0.72,<br/>&nbsp;&nbsp;policy: 'brand_response',<br/>&nbsp;&nbsp;factors: [high_intent, safe_sub],<br/>&nbsp;&nbsp;blocked_by: null<br/>}"]
```

**Acceptance criteria:**
- [ ] `decision_events` table stores every decision (engage/ignore/monitor/create)
- [ ] Each decision has `reasoning` JSONB with: score, factors, policy_applied, blocked_by
- [ ] Decision Engine applies policies in priority order (higher priority = evaluated first)
- [ ] Context includes: avatar phase, karma, subreddit risk, time_of_day, daily budget remaining
- [ ] "Monitor" decisions re-enter evaluation after configurable interval
- [ ] Client can view decision history for their opportunities (audit trail)
- [ ] No content is generated without a prior decision_event record (structural invariant)

### R4: Declarative Policy Engine

**Requirement:** Engagement rules expressed as declarative JSON policies, configurable per client and per avatar.

```mermaid
flowchart TD
    subgraph PolicyEval["Policy Evaluation (priority order)"]
        P1["P1: System Safety<br/>(priority=100)<br/>phase_gate, brand_block"]
        P2["P2: Client Override<br/>(priority=80)<br/>custom rules from UI"]
        P3["P3: Subreddit Rules<br/>(priority=60)<br/>fitness gate, risk score"]
        P4["P4: Default Engagement<br/>(priority=40)<br/>score thresholds"]
    end

    OPP[Opportunity] --> P1
    P1 -->|blocked| DENY[Deny + log reason]
    P1 -->|pass| P2
    P2 -->|blocked| DENY
    P2 -->|pass| P3
    P3 -->|blocked| DENY
    P3 -->|pass| P4
    P4 --> ALLOW[Allow + set parameters]

    ALLOW --> PARAMS["require_review: true<br/>use_model: claude-sonnet<br/>max_length: 200"]
```

**Acceptance criteria:**
- [ ] `policies` table: client_id, avatar_id (nullable=global), rule_name, when_condition JSONB, action JSONB, priority, enabled
- [ ] Conditions support: opportunity.type, score, subreddit, phase, avatar.karma, time_of_day, daily_budget_remaining
- [ ] Actions support: allow_reply, require_review, allow_post, use_model, max_length, temperature
- [ ] Policies evaluated in priority order (highest first), first match wins
- [ ] System safety policies (phase gates, brand blocks) immutable by clients — priority ≥ 100
- [ ] Client-configurable policies editable via admin UI (priority 1-80)
- [ ] Policy change logged in audit trail
- [ ] Existing safety gates (fitness_gate, safety_blocks, phase policy) expressed as policies

### R5: Avatar Memory

**Requirement:** Each avatar accumulates persistent memory that improves responses over time.

```mermaid
flowchart LR
    subgraph Memory["Avatar Memory Store"]
        FACTS["Facts<br/>'I work in cybersecurity'<br/>'10 years experience'"]
        STYLE["Style Preferences<br/>'Short paragraphs'<br/>'Use analogies'"]
        HISTORY["Interaction History<br/>'Discussed XDR in r/sysadmin'<br/>'Got 47 karma on that'"]
        FORBIDDEN["Forbidden Topics<br/>'Never mention competitor Y'<br/>'Avoid pricing discussions'"]
    end

    GEN[Generation Prompt] -->|retrieves top-K<br/>relevant memories| Memory
    FEEDBACK[Post Feedback<br/>karma, edits, removals] -->|updates importance| Memory
    EDIT[Human Edit] -->|creates style memory| Memory
```

**Acceptance criteria:**
- [ ] `avatar_memory` table: avatar_id, memory_type (fact/style/previous_interaction/forbidden_topic), content, embedding VECTOR(384), importance (0-1)
- [ ] Memories retrieved via semantic search (embedding similarity) during generation
- [ ] Top-K memories (K=5-10) injected into generation prompt
- [ ] Successful interactions (karma ≥ 5) create `previous_interaction` memories
- [ ] Human edits create `style` memories (replaces current `CorrectionPattern` table)
- [ ] Importance score decays over time (recent > old), high-karma memories resist decay
- [ ] Memory deduplication (similarity > 0.95 → merge, keep higher importance)
- [ ] Maximum 200 memories per avatar (LRU eviction on importance)

### R6: Community Intelligence Layer

**Requirement:** Community knowledge (trends, pain points, competitor moves) as a separate, valuable layer — not just a scoring input.

**Acceptance criteria:**
- [ ] `community_intelligence` table: client_id, source_content_id, topic, sentiment, volume, source, collected_at
- [ ] Trend detection: topics with volume increase > 2x in 7 days flagged
- [ ] Pain point extraction: questions/complaints clustered by topic
- [ ] Competitor mention tracking: what competitors are cited for, in what context
- [ ] `geo_reports` table: structured JSONB reports (trends, competitors, pain_points) per period
- [ ] Intelligence feeds into Opportunity scoring (trending topics = higher opportunity score)
- [ ] Client-facing intelligence dashboard (separate from engagement metrics)

### R7: Generation Router (Model Selection)

**Requirement:** Model selection is dynamic, based on task complexity, risk level, and client tier.

```mermaid
flowchart TD
    TASK[Generation Task] --> ASSESS{Risk Assessment}
    
    ASSESS -->|high risk<br/>brand mention,<br/>competitive| CLAUDE[Claude Sonnet<br/>require_review=true]
    
    ASSESS -->|medium risk<br/>professional sub,<br/>Phase 2+| FLASH_PRO[Gemini Flash<br/>require_review=configurable]
    
    ASSESS -->|low risk<br/>hobby, safe sub,<br/>Phase 1| FLASH[Gemini Flash Lite<br/>auto-approve eligible]
    
    CACHE{Semantic Cache<br/>hit?}
    TASK --> CACHE
    CACHE -->|hit + fresh| ADAPT[Adapt cached response]
    CACHE -->|miss| ASSESS
    
    ADAPT --> VALIDATE[Quality Validator]
    CLAUDE --> VALIDATE
    FLASH_PRO --> VALIDATE
    FLASH --> VALIDATE
```

**Acceptance criteria:**
- [ ] Generation Router selects model based on: opportunity risk, subreddit risk_score, avatar phase, client tier, content type
- [ ] Semantic cache: content_node embedding + intent → check for similar prior generations
- [ ] Cache hit: adapt existing response (cheaper model call for adaptation vs full generation)
- [ ] Quality validator: checks length, tone match, brand safety before passing to review
- [ ] Cost tracked per generation in `generation_runs` table (model, tokens_in, tokens_out, cost)
- [ ] Routing rules configurable via Policy Engine (policy action `use_model`)

### R8: Context Snapshots

**Requirement:** At decision/generation time, the full context is captured immutably — enabling post-hoc analysis and model improvement.

**Acceptance criteria:**
- [ ] `context_snapshots` table: content_id, depth (thread depth captured), embedding, snapshot_json (full thread context)
- [ ] Created at generation time — captures exactly what the LLM saw
- [ ] Snapshot includes: thread title, parent chain (up to depth 5), avatar identity, policy that allowed, opportunity that triggered
- [ ] Enables: "why did we generate this?" debugging months later
- [ ] Enables: training data extraction for fine-tuning (future)

---

## Non-Functional Requirements

### NF1: Migration Path
- Current RAMP v0.3 data MUST be migratable to v3.0 schema
- `reddit_threads` → `content_nodes` (direction=inbound)
- `comment_drafts` → `content_nodes` (direction=outbound) + link to opportunity
- `thread_scores` → `opportunities` (type=discussion, score mapped from tag)
- Migration must be reversible (keep old tables as archive for 90 days)

### NF2: Performance
- Opportunity scoring: < 100ms per opportunity (excluding LLM calls)
- Decision Engine: < 50ms per decision (policy evaluation is in-memory)
- Memory retrieval: < 200ms for top-K semantic search (pgvector)
- Content Graph traversal: < 500ms for depth-5 thread reconstruction

### NF3: Cost Boundaries
- Target cost per avatar per month: ≤ $5.20 (as specified in economics section)
- Generation Router must prefer cheaper models when quality allows
- Semantic cache should reduce LLM calls by ≥ 30% after 30 days of operation

### NF4: Backward Compatibility
- Existing API endpoints (extension, portal, admin) continue working during migration
- Phase system, safety gates, and SBM properties preserved as policies
- Existing self-learning loop (EditRecord, CorrectionPattern) data migrated to Avatar Memory

---

## Implementation Phases

```mermaid
gantt
    title RAMP v3.0 Implementation Roadmap
    dateFormat YYYY-MM-DD
    
    section Phase 1 — Core
    Data model + migrations          :p1a, 2026-07-15, 5d
    Content Graph (Reddit ingest)    :p1b, after p1a, 4d
    Opportunity Engine (basic)       :p1c, after p1b, 4d
    Decision Engine + Policies       :p1d, after p1c, 3d
    Generation Router + Cache        :p1e, after p1d, 3d
    Human Review (existing)          :p1f, after p1e, 2d
    
    section Phase 2 — Context
    Reply threading (depth)          :p2a, after p1f, 3d
    Context Snapshots                :p2b, after p2a, 2d
    Avatar Memory (basic)            :p2c, after p2b, 4d
    Enhanced Opportunity types       :p2d, after p2c, 3d
    
    section Phase 3 — Intelligence
    Community Intelligence Engine    :p3a, after p2d, 5d
    GEO Reports integration          :p3b, after p3a, 3d
    Client Intelligence Dashboard    :p3c, after p3b, 4d
    
    section Phase 4 — Multi-Platform
    Post generation                  :p4a, after p3c, 3d
    Policy Engine UI editor          :p4b, after p4a, 4d
    Platform abstraction (Twitter)   :p4c, after p4b, 5d
    Content Relationships (full)     :p4d, after p4c, 3d
    
    section Phase 5 — Enterprise
    Decision Log export / API        :p5a, after p4d, 3d
    SSO + advanced RBAC              :p5b, after p5a, 3d
    Analytics (ClickHouse or PG)     :p5c, after p5b, 4d
    Scaling + sharding               :p5d, after p5c, 4d
```

---

## Relationship to Current RAMP (v0.3)

| Current Component | v3.0 Equivalent | Migration Strategy |
|---|---|---|
| `reddit_threads` + `hobby_subreddits` | `content_nodes` (inbound) | Migrate + keep archive 90d |
| `comment_drafts` | `content_nodes` (outbound) | Migrate, link to opportunities |
| `thread_scores` | `opportunities` | Map score→opportunity, tag→type |
| `EPG Portfolio Manager` | `Opportunity Engine` + `Decision Engine` | Refactor into separate services |
| `fitness_gate` + `safety_blocks` | `policies` (system safety, priority 100) | Express as declarative rules |
| `CorrectionPattern` + `EditRecord` | `avatar_memory` (type=style) | Migrate patterns to memories |
| `ai_usage_log` | `generation_runs` (superset) | Extend, don't replace |
| `GeoExecution` + `GeoQueryResult` | `community_intelligence` + `geo_reports` | Keep existing, add intelligence layer on top |

---

## Pricing Tiers (v3.0)

| Tier | Price | Avatars | Communities | Features |
|------|-------|---------|-------------|----------|
| **Starter** | $499/mo | 1 | 3 | Basic engagement, human review, weekly reports |
| **Growth** | $1,999/mo | 3 | 10 | Opportunity Intelligence, dashboards, Policy Engine |
| **Enterprise** | $5,000+/mo | Unlimited | Unlimited | Full audit, API, custom policies, dedicated manager |

---

## Unit Economics (per avatar/month)

| Component | Cost |
|-----------|------|
| LLM (generation + routing + scoring) | ~$4.00 |
| Embeddings (cache, memory, opportunity) | ~$0.15 |
| Database + vector store | ~$0.50 |
| Scraping + queues | ~$0.30 |
| Monitoring + logs + audit | ~$0.25 |
| **Total** | **~$5.20** |

At 100+ avatars: infrastructure costs amortize to ~$3.00/avatar.

**Margin at scale:**
- 50 Growth clients × $1,999 = $100K/mo revenue
- 150 avatars × $5.20 = $780/mo AI/infra cost
- Margin: **>99%** (LLM costs negligible vs revenue at Growth tier pricing)
