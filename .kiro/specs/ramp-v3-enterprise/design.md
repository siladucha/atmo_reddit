# RAMP v3.0 Enterprise — Design Document

## System Architecture

```mermaid
C4Context
    title RAMP v3.0 — System Context

    Person(client, "Client", "Brand managing community presence")
    Person(executor, "Executor", "Posts approved content via extension")
    Person(operator, "Operator (Max)", "System admin, pipeline ops")

    System(ramp, "RAMP v3.0", "AI Community Intelligence & Engagement Platform")

    System_Ext(reddit, "Reddit", "Community platform")
    System_Ext(llm, "LLM Providers", "Claude, Gemini, Perplexity")
    System_Ext(brevo, "Brevo", "Email delivery")

    Rel(client, ramp, "Views reports, approves policies")
    Rel(executor, ramp, "Receives tasks, posts content")
    Rel(operator, ramp, "Configures, monitors, debugs")
    Rel(ramp, reddit, "Scrapes, monitors, posts via extension")
    Rel(ramp, llm, "Scoring, generation, intelligence")
    Rel(ramp, brevo, "Task emails, notifications")
```

---

## Data Model (Complete)

```mermaid
erDiagram
    CLIENT ||--o{ CONTENT_NODE : "owns (inbound)"
    CLIENT ||--o{ OPPORTUNITY : "has"
    CLIENT ||--o{ POLICY : "configures"
    CLIENT ||--o{ GEO_REPORT : "receives"
    
    AVATAR ||--o{ CONTENT_NODE : "authors (outbound)"
    AVATAR ||--o{ AVATAR_MEMORY : "accumulates"
    AVATAR ||--o{ OPPORTUNITY : "assigned to"
    
    CONTENT_NODE ||--o{ CONTENT_RELATIONSHIP : "from"
    CONTENT_NODE ||--o{ CONTENT_RELATIONSHIP : "to"
    CONTENT_NODE ||--o| OPPORTUNITY : "source of"
    CONTENT_NODE ||--o| CONTEXT_SNAPSHOT : "captured at"
    CONTENT_NODE ||--o| GENERATION_RUN : "produced by"
    
    OPPORTUNITY ||--o{ OPPORTUNITY_STATUS_HISTORY : "lifecycle"
    OPPORTUNITY ||--o{ DECISION_EVENT : "decided on"
    
    DECISION_EVENT ||--o| POLICY : "applied"
    
    COMMUNITY_INTELLIGENCE ||--o| CONTENT_NODE : "derived from"
    
    CLIENT {
        uuid id PK
        text name
        text industry
        text tier "starter | growth | enterprise"
        jsonb settings
        jsonb strategy_context
    }
    
    AVATAR {
        uuid id PK
        uuid client_id FK
        text username
        text platform "reddit"
        jsonb identity "voice, persona, niche"
        jsonb config "temperature, frequency, phase"
        int warming_phase "0-3"
    }
    
    CONTENT_NODE {
        uuid id PK
        uuid client_id FK
        uuid avatar_id FK "nullable"
        text platform "reddit | twitter | linkedin"
        text platform_id "reddit post/comment id"
        text direction "inbound | outbound"
        text status "discovered→published"
        text title "nullable"
        text body
        text author
        text subreddit
        jsonb platform_metadata "ups, created_utc, url"
        vector embedding "384-dim"
        timestamp created_at
        timestamp updated_at
    }
    
    CONTENT_RELATIONSHIP {
        uuid id PK
        uuid from_content_id FK
        uuid to_content_id FK
        text relation_type
        jsonb metadata
        timestamp created_at
    }
    
    OPPORTUNITY {
        uuid id PK
        uuid client_id FK
        uuid avatar_id FK "nullable until assigned"
        uuid source_content_id FK
        text type "brand_mention | question | pain_point | competitor | trend | discussion"
        text status "discovered→completed | expired"
        float score "0.0-1.0"
        text recommended_action "ignore | monitor | engage | create"
        jsonb decision_context
        timestamp expires_at
        timestamp created_at
        timestamp updated_at
    }
    
    OPPORTUNITY_STATUS_HISTORY {
        uuid id PK
        uuid opportunity_id FK
        text old_status
        text new_status
        text changed_by "system | user_email"
        text reason
        timestamp created_at
    }
    
    DECISION_EVENT {
        uuid id PK
        uuid client_id FK
        uuid opportunity_id FK
        text decision "ignore | monitor | engage | create"
        jsonb reasoning
        text model_used "nullable"
        uuid policy_applied FK "nullable"
        timestamp created_at
    }
    
    POLICY {
        uuid id PK
        uuid client_id FK "nullable = global"
        uuid avatar_id FK "nullable = all avatars"
        text rule_name
        jsonb when_condition
        jsonb action
        int priority "1-100"
        boolean enabled
        timestamp created_at
        timestamp updated_at
    }
    
    GENERATION_RUN {
        uuid id PK
        uuid content_id FK
        uuid opportunity_id FK
        text model
        text prompt_version
        int tokens_in
        int tokens_out
        float cost
        float quality_score "nullable"
        text generated_text
        jsonb cache_info "hit/miss, cache_key"
        timestamp created_at
    }
    
    CONTEXT_SNAPSHOT {
        uuid id PK
        uuid content_id FK
        int depth "thread depth captured"
        vector embedding "384-dim"
        jsonb snapshot_json "full context at decision time"
        timestamp created_at
    }
    
    AVATAR_MEMORY {
        uuid id PK
        uuid avatar_id FK
        text memory_type "fact | style | previous_interaction | forbidden_topic"
        text content
        vector embedding "384-dim"
        float importance "0.0-1.0"
        timestamp created_at
        timestamp last_accessed_at
    }
    
    COMMUNITY_INTELLIGENCE {
        uuid id PK
        uuid client_id FK
        uuid source_content_id FK "nullable"
        text topic
        float sentiment "-1.0 to 1.0"
        int volume
        text source "reddit | twitter"
        timestamp collected_at
    }
    
    GEO_REPORT {
        uuid id PK
        uuid client_id FK
        text report_type "trends | competitors | pain_points | visibility"
        jsonb data
        date period_start
        date period_end
        timestamp created_at
    }
```

---

## Service Architecture

```mermaid
flowchart TB
    subgraph API["API Layer (FastAPI)"]
        PORTAL[Portal Routes]
        ADMIN[Admin Routes]
        EXT_API[Extension API]
        PUBLIC[Public Routes]
    end
    
    subgraph Services["Service Layer"]
        subgraph Core["Core Services"]
            DISC_SVC[Discovery Service]
            OPP_SVC[Opportunity Service]
            DEC_SVC[Decision Service]
            GEN_SVC[Generation Service]
            PUB_SVC[Publisher Service]
        end
        
        subgraph Intelligence["Intelligence Services"]
            INTEL_SVC[Intelligence Service]
            GEO_SVC[GEO/AEO Service]
            TREND_SVC[Trend Detector]
        end
        
        subgraph Support["Support Services"]
            POLICY_SVC[Policy Engine]
            MEMORY_SVC[Memory Service]
            CACHE_SVC[Semantic Cache]
            ROUTER_SVC[Model Router]
        end
    end
    
    subgraph Tasks["Celery Tasks"]
        SCRAPE_T[Scrape Tasks]
        INTEL_T[Intelligence Tasks]
        OPP_T[Opportunity Tasks]
        GEN_T[Generation Tasks]
        FEEDBACK_T[Feedback Tasks]
    end
    
    subgraph Storage["Data Layer"]
        PG[(PostgreSQL + pgvector)]
        REDIS[(Redis — locks, cache, pubsub)]
    end
    
    API --> Services
    Services --> Tasks
    Services --> Storage
    Tasks --> Storage
```

---

## Key Service Interfaces

### Discovery Service

```python
class DiscoveryService:
    """Ingests content from platforms into Content Graph."""
    
    async def ingest_reddit_posts(self, subreddit: str, limit: int = 25) -> list[ContentNode]:
        """Scrape subreddit, create content_nodes, build relationships."""
        
    async def ingest_reddit_thread(self, thread_id: str, depth: int = 5) -> ContentNode:
        """Deep-scrape a thread, build reply_to relationships."""
        
    async def detect_changes(self, content_id: UUID) -> list[ContentChange]:
        """Check if existing content has new replies, score changes, etc."""
```

### Opportunity Service

```python
class OpportunityService:
    """Identifies and manages engagement opportunities."""
    
    async def scan_for_opportunities(self, client_id: UUID) -> list[Opportunity]:
        """Scan new content_nodes → create opportunities based on rules."""
        
    async def score_opportunity(self, opp_id: UUID) -> float:
        """Multi-dimensional scoring: relevance, timing, risk, potential."""
        
    async def expire_stale(self) -> int:
        """Mark expired opportunities (TTL exceeded, thread locked)."""
        
    async def reassess(self, opp_id: UUID) -> Opportunity:
        """Re-score when context changes (new comments, sentiment shift)."""
```

### Decision Service

```python
class DecisionService:
    """Makes and logs engagement decisions."""
    
    async def decide(self, opportunity: Opportunity, avatar: Avatar) -> DecisionEvent:
        """Apply policies → decide action → log reasoning → return decision."""
        
    async def get_decision_history(self, client_id: UUID, limit: int = 50) -> list[DecisionEvent]:
        """Audit trail for client."""
```

### Policy Engine

```python
class PolicyEngine:
    """Evaluates declarative policies against opportunities."""
    
    def evaluate(self, opportunity: Opportunity, avatar: Avatar, context: dict) -> PolicyResult:
        """Evaluate all active policies in priority order. First match wins."""
        
    def validate_policy(self, policy: Policy) -> list[str]:
        """Validate policy JSON structure before save."""
        
    def get_system_policies(self) -> list[Policy]:
        """Immutable system safety policies (phase gates, brand blocks)."""
```

### Memory Service

```python
class MemoryService:
    """Manages avatar persistent memory with semantic retrieval."""
    
    async def retrieve(self, avatar_id: UUID, context: str, k: int = 5) -> list[AvatarMemory]:
        """Top-K memories by embedding similarity to context."""
        
    async def store(self, avatar_id: UUID, memory_type: str, content: str, importance: float):
        """Create memory with embedding. Dedup if similar exists."""
        
    async def decay(self) -> int:
        """Reduce importance of old, unused memories. Evict if > 200 per avatar."""
```

### Generation Router

```python
class GenerationRouter:
    """Selects model and parameters based on task characteristics."""
    
    def route(self, opportunity: Opportunity, avatar: Avatar, policy_action: dict) -> GenerationConfig:
        """Returns: model, temperature, max_tokens, require_review."""
        
    async def check_cache(self, context_embedding: list[float], intent: str) -> Optional[str]:
        """Semantic cache lookup. Returns cached generation if fresh + similar."""
```

---

## Pipeline Flow (v3.0)

```mermaid
sequenceDiagram
    participant Beat as Celery Beat
    participant Disc as Discovery
    participant Graph as Content Graph
    participant Intel as Intelligence
    participant Opp as Opportunity Engine
    participant Dec as Decision Engine
    participant Pol as Policy Engine
    participant Gen as Generation Router
    participant LLM as LLM Provider
    participant Mem as Avatar Memory
    participant Rev as Review Queue
    participant Ext as Extension
    
    Beat->>Disc: queue_tick (every 60s)
    Disc->>Graph: ingest_reddit_posts()
    Graph-->>Disc: new content_nodes
    
    Beat->>Intel: analyze_new_content (hourly)
    Intel->>Graph: read content_nodes + relationships
    Intel-->>Intel: detect trends, pain_points
    
    Beat->>Opp: scan_for_opportunities (08:15, 14:15)
    Opp->>Graph: query new/changed content
    Opp->>Intel: get relevant intelligence
    Opp-->>Opp: create/update opportunities
    
    Opp->>Dec: evaluate_opportunities()
    Dec->>Pol: evaluate(opportunity, avatar, context)
    Pol-->>Dec: allow + action params
    Dec-->>Dec: log decision_event
    
    Dec->>Gen: generate(opportunity, avatar, policy_action)
    Gen->>Mem: retrieve(avatar_id, context, k=5)
    Mem-->>Gen: relevant memories
    Gen->>LLM: call_llm(prompt + memories + context)
    LLM-->>Gen: generated text
    Gen-->>Gen: validate + log generation_run
    Gen->>Graph: create content_node (outbound, status=review)
    
    Graph->>Rev: new pending content
    Rev->>Ext: task appears in popup
    Ext-->>Rev: executor approves
    Rev->>Graph: status → approved → published
    
    Note over Ext,Graph: Feedback loop (every 4h)
    Ext-->>Mem: karma result → store interaction memory
```

---

## Decision Engine Detail

```mermaid
flowchart TD
    INPUT[/"Opportunity<br/>type=question<br/>score=0.78<br/>sub=r/sysadmin"/]
    
    INPUT --> CTX[Build Context]
    CTX --> |"avatar_karma=127<br/>phase=2<br/>time=10:15<br/>budget_remaining=5<br/>sub_risk=42"| EVAL
    
    EVAL[Policy Evaluation Loop]
    
    EVAL --> P100["P100: System Safety<br/>✅ phase ≥ 2 for professional"]
    P100 --> P80["P80: Client Custom<br/>✅ no custom block"]
    P80 --> P60["P60: Subreddit Rules<br/>✅ karma > min_karma(50)<br/>✅ not dangerous hour"]
    P60 --> P40["P40: Default Threshold<br/>✅ score 0.78 > 0.5 threshold"]
    
    P40 --> DECISION["Decision: ENGAGE<br/>require_review: true<br/>use_model: claude-sonnet<br/>max_length: 250"]
    
    DECISION --> LOG["Log to decision_events<br/>reasoning: {score, factors, policy}"]
    DECISION --> NEXT[Pass to Generation Router]
```

---

## Migration Strategy

```mermaid
flowchart LR
    subgraph Current["RAMP v0.3 (current)"]
        RT[reddit_threads]
        HS[hobby_subreddits]
        CD[comment_drafts]
        TS[thread_scores]
        OPP_OLD[opportunities — EPG]
        CP[correction_patterns]
        ER[edit_records]
    end
    
    subgraph V3["RAMP v3.0 (target)"]
        CN[content_nodes]
        CR[content_relationships]
        OPP_NEW[opportunities — lifecycle]
        DE[decision_events]
        AM[avatar_memory]
        POL[policies]
    end
    
    RT -->|"direction=inbound<br/>platform=reddit"| CN
    HS -->|"direction=inbound<br/>subreddit from avatar"| CN
    CD -->|"direction=outbound<br/>link to opportunity"| CN
    TS -->|"tag→type<br/>score→score/10"| OPP_NEW
    OPP_OLD -->|"map dimensions<br/>to opportunity score"| OPP_NEW
    CP -->|"type=style<br/>importance=0.8"| AM
    ER -->|"type=style<br/>importance=0.6"| AM
    
    style Current fill:#1a1a2e,color:#fff
    style V3 fill:#16213e,color:#fff
```

### Migration Phases:

1. **Phase A (non-destructive):** Create v3 tables alongside existing. Dual-write new content to both.
2. **Phase B (backfill):** Migrate historical data from old tables → new tables. Verify counts match.
3. **Phase C (switch):** Point pipeline services at new tables. Old tables become read-only archive.
4. **Phase D (cleanup):** After 90 days, drop old tables (or keep for analytics).

---

## Semantic Cache Design

```mermaid
flowchart TD
    REQ[Generation Request<br/>context + intent + subreddit]
    
    REQ --> EMBED[Compute embedding<br/>of context+intent]
    EMBED --> SEARCH[pgvector similarity search<br/>in generation_runs<br/>WHERE subreddit matches<br/>AND created_at > 7d ago]
    
    SEARCH -->|similarity > 0.92<br/>+ same intent| HIT[Cache HIT]
    SEARCH -->|no match| MISS[Cache MISS]
    
    HIT --> ADAPT[Adapt cached text<br/>with lightweight model<br/>Gemini Flash Lite]
    MISS --> FULL[Full generation<br/>Claude Sonnet / Gemini Flash]
    
    ADAPT --> SAVE[Save to generation_runs<br/>cache_info: {hit: true, source_id}]
    FULL --> SAVE
    
    SAVE --> OUTPUT[Return generated text]
```

**Cache eviction:** Entries older than 30 days or with quality_score < 3.0 are excluded from search.

**Expected savings:** 30-40% reduction in full LLM calls after 30 days of operation per client.

---

## Policy Engine Schema

```mermaid
classDiagram
    class Policy {
        +UUID id
        +UUID client_id
        +UUID avatar_id
        +String rule_name
        +JSON when_condition
        +JSON action
        +int priority
        +bool enabled
        +evaluate(opportunity, context) PolicyResult
    }
    
    class PolicyResult {
        +bool allowed
        +String blocked_by
        +String reason
        +JSON action_params
    }
    
    class WhenCondition {
        +String opportunity_type
        +String score_operator "> | < | >= | <="
        +float score_value
        +list~String~ subreddits
        +int min_phase
        +int min_karma
        +list~int~ allowed_hours
        +float max_risk_score
    }
    
    class ActionParams {
        +bool allow_reply
        +bool allow_post
        +bool require_review
        +String use_model
        +int max_length
        +float temperature
    }
    
    Policy --> PolicyResult : produces
    Policy --> WhenCondition : has
    Policy --> ActionParams : has
```

### Built-in System Policies (immutable, priority 100):

| Rule | Condition | Action |
|------|-----------|--------|
| `phase_0_safe_only` | phase=0 AND subreddit NOT IN safe_list | block |
| `phase_1_no_brand` | phase≤1 AND opportunity.type=brand_mention | block |
| `phase_2_no_direct_link` | phase≤2 AND content contains brand URL | block |
| `frozen_avatar_block` | avatar.is_frozen=true | block |
| `budget_exhausted` | daily_budget_remaining=0 | block |
| `dangerous_hours` | time_of_day IN subreddit.dangerous_hours AND karma<200 | block |

These replace current hardcoded safety gates (`safety_blocks.py`, `fitness_gate.py`, `posting_safety.py`) with declarative equivalents.

---

## Technology Decisions

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Content Graph storage | PostgreSQL + JSONB + pgvector | Already in stack, no new infra. Graph queries via recursive CTEs. |
| Embedding model | `text-embedding-004` (384-dim) | Already used. Free tier on Google. |
| Vector similarity | pgvector (cosine) | In-process, no external service. <200ms for 10K vectors. |
| Semantic cache | Same PG table (generation_runs + embedding) | No Redis needed — cache is persistent, not ephemeral. |
| Policy evaluation | In-memory Python (loaded from DB on startup, refreshed every 60s) | < 1ms evaluation, no DB round-trip per decision. |
| Analytics store | PostgreSQL (for now), ClickHouse when > 1M events | YAGNI — PG handles current scale. |
| Task queue | Celery + Redis (unchanged) | Working, tested, no migration needed. |
| Multi-platform | Abstraction layer in Discovery Service | Platform-specific adapters (Reddit, Twitter, LinkedIn). |
