# Reddit Avatar Publisher — Complete System Diagram (Mermaid)

## 0. High-Level Architecture (Top Level)

```mermaid
flowchart LR

subgraph PLATFORM["🖥️ RAMP Platform<br/>(DigitalOcean Droplet)"]
    direction TB
    WEB["Web UI<br/>Admin Panel + Review Queue<br/>(FastAPI + Jinja2 + HTMX)"]
    ENGINE["Pipeline Engine<br/>(Celery Workers)"]
    DATA["Data Layer<br/>(PostgreSQL + Redis)"]
    WEB --> ENGINE
    ENGINE --> DATA
    WEB --> DATA
end

subgraph LLM_APIS["🧠 AI APIs"]
    direction TB
    SCORING["Gemini Flash<br/>Scoring"]
    GENERATION["Claude Sonnet<br/>Generation + Persona"]
end

subgraph REDDIT_EXT["🔴 Reddit"]
    direction TB
    SCRAPE_API["API (PRAW)<br/>Scraping + Health"]
    POST_WEB["Web<br/>Manual Posting"]
end

subgraph PEOPLE["👥 People"]
    direction TB
    MANAGER["Manager<br/>💻 Review & Approve"]
    OWNERS["Avatar Owners<br/>📋 Post Comments"]
end

ENGINE -->|scrape| SCRAPE_API
ENGINE -->|score| SCORING
ENGINE -->|generate| GENERATION
MANAGER -->|review drafts| WEB
OWNERS -->|copy-paste post| POST_WEB
OWNERS -->|mark posted| WEB

style PLATFORM fill:#0a2b3e,stroke:#1a5d7a,color:#eee
style LLM_APIS fill:#2d1b36,stroke:#6b2d5c,color:#eee
style REDDIT_EXT fill:#3a1a1a,stroke:#9e2a2a,color:#eee
style PEOPLE fill:#1a3a2a,stroke:#2d6a4f,color:#eee
```

---

## 1. Complete System Diagram

```mermaid
flowchart TB

subgraph SCHEDULER["⏰ Celery Beat Scheduler"]
    M["08:00 UTC<br/>Professional Pipeline"]
    A["14:00 UTC<br/>Professional Pipeline"]
    H["10:00 UTC<br/>Hobby Pipeline"]
    C["07:30 & 13:30 UTC<br/>Health Check"]
    QT["every 60s<br/>queue_tick (scrape)"]
    PH["06:00 UTC<br/>Phase Evaluation"]
    CQS["06:30 UTC<br/>CQS Batch Check"]
end

subgraph DO["🖥️ DigitalOcean Droplet (Docker Compose)"]
    subgraph CORE["Core Services"]
        API["FastAPI<br/>REST API + Jinja2/HTMX"]
        DB[("PostgreSQL 16<br/>26 tables")]
        REDIS[("Redis 7<br/>Cache + Queue + Locks")]
        WORKER["Celery Worker<br/>Background Jobs"]
    end
end

subgraph LLM["🧠 LLM APIs (via LiteLLM)"]
    GEMINI["Gemini 2.0 Flash<br/>Scoring (cheap, fast)"]
    CLAUDE_S["Claude Sonnet 4<br/>Generation + Persona"]
    CLAUDE_H["Claude 3.5 Haiku<br/>Strategy (fallback)"]
end

subgraph REDDIT["🔴 Reddit"]
    RD_API["Reddit API<br/>oauth.reddit.com"]
    RD_WEB["Reddit Web<br/>old.reddit.com"]
end

subgraph USERS["👥 Users"]
    MANAGER["Manager (Tzvi)<br/>💻 Desktop Web"]
    OWNER["Avatar Owner<br/>📋 Manual Copy-Paste"]
end

%% ==================== FLOW 1: SCRAPE ====================
QT --> S1

subgraph S1["1. SCRAPE (subreddit-centric)"]
    direction TB
    PRAW["PRAW Client"]
    SUBREDDITS["Shared Subreddits<br/>(stalest first, freshness gate)"]
    SUBREDDITS --> PRAW
    PRAW --> RD_API
end

S1 -->|raw threads| DB

%% ==================== FLOW 2: SCORE ====================
M --> PIPELINE
A --> PIPELINE

subgraph PIPELINE["AI Pipeline (per client)"]
    direction TB
    S2["2. SCORE (Gemini Flash)<br/>thread + keywords + profile<br/>→ engage/monitor/skip"]
    S3["3. SELECT PERSONA (Sonnet)<br/>thread + all avatars + karma<br/>→ avatar_id, mode, angle"]
    S4["4. GENERATE COMMENT (Sonnet)<br/>thread + voice + strategy + learning<br/>→ comment, location, approach"]
    S2 --> S3
    S3 --> S4
end

DB -->|unscored threads| S2
S2 -->|scores| DB
S3 -->|persona choice| DB
S4 -->|save| DRAFTS[(comment_drafts<br/>status='pending')]

S2 -.->|API call| GEMINI
S3 -.->|API call| CLAUDE_S
S4 -.->|API call| CLAUDE_S

DRAFTS -->|log| AI_LOG[("ai_usage_log")]

%% ==================== FLOW 5: HUMAN REVIEW ====================
DRAFTS -->|status='pending'| TZVI_UI

subgraph TZVI_UI["5. HUMAN REVIEW"]
    WEB_UI["Web Interface<br/>/review/comments"]
    ACTIONS["Actions:<br/>✅ Approve<br/>✏️ Edit + Approve<br/>❌ Reject<br/>🔄 Redraft"]
end

MANAGER -->|opens| WEB_UI
MANAGER -->|performs| ACTIONS
ACTIONS -->|Approve| APPROVED[(comment_drafts<br/>status='approved')]
ACTIONS -->|learning| LEARNING["Self-Learning Loop<br/>EditRecord → CorrectionPattern<br/>→ few-shot injection"]
ACTIONS -->|audit| AUDIT[(audit_log)]

%% ==================== FLOW 6: MANUAL POSTING ====================
APPROVED -->|copy text| OWNER
OWNER -->|paste in Reddit| RD_WEB
OWNER -->|confirm posted| API
API -->|update| POSTED[(comment_drafts<br/>status='posted')]

%% ==================== FLOW 7: HOBBY PIPELINE ====================
H --> S1_H

subgraph S1_H["1b. HOBBY PIPELINE"]
    HOBBY_SCRAPE["Scrape hobby subreddits"]
    HOBBY_GEN["Generate hobby comment<br/>(Gemini Flash — cheaper)"]
    HOBBY_SCRAPE --> HOBBY_GEN
end

S1_H -.->|PRAW| RD_API
S1_H -.->|API call| GEMINI
S1_H -->|save| DRAFTS

%% ==================== FLOW 8: HEALTH CHECK ====================
C --> HEALTH

subgraph HEALTH["7. HEALTH CHECK"]
    CHECK["health_checker.py"]
    CHECK --> METRICS["shadowban_status,<br/>suspension, CQS level"]
    METRICS --> FREEZE["Auto-freeze if:<br/>shadowbanned or<br/>CQS = lowest (Phase 2+)"]
end

HEALTH -.->|check| RD_API
HEALTH -->|update| DB

%% ==================== FLOW: PHASE & CQS ====================
PH -->|evaluate phases| DB
CQS -->|CQS batch| HEALTH

%% Styling
style SCHEDULER fill:#1a1a2e,stroke:#16213e,color:#eee
style DO fill:#0a2b3e,stroke:#1a5d7a,color:#eee
style LLM fill:#2d1b36,stroke:#6b2d5c,color:#eee
style USERS fill:#1a3a2a,stroke:#2d6a4f,color:#eee
style REDDIT fill:#3a1a1a,stroke:#9e2a2a,color:#eee
style TZVI_UI fill:#2a3a2a,stroke:#4a7a4a,color:#eee
style HEALTH fill:#3a2a1a,stroke:#8a6a2a,color:#eee
style PIPELINE fill:#1a2a3a,stroke:#3a5a7a,color:#eee
```

---

## 2. Simplified Data Flow Diagram

```mermaid
flowchart LR

subgraph DAY["Daily Pipeline (08:00 & 14:00 UTC)"]
    direction TB
    D1["1. Scrape<br/>Reddit posts"] --> D2["2. Score<br/>(Gemini Flash)"]
    D2 --> D3["3. Select Persona<br/>(Claude Sonnet)"]
    D3 --> D4["4. Generate Comment<br/>(Claude Sonnet)"]
    D4 --> D5["5. Human Review<br/>(Manager)"]
    D5 --> D6["6. Manual Post<br/>(Avatar Owner)"]
end

D1 -.-> RD["🔴 Reddit API"]
D6 -.-> RD_W["🔴 Reddit Web"]
D2 -.-> G["⚡ Gemini Flash"]
D3 -.-> S["🎯 Claude Sonnet"]
D4 -.-> S

style DAY fill:#1a1a2e,stroke:#333,color:#fff
```

---

## 3. Component Interaction Diagram

```mermaid
sequenceDiagram
    participant CB as Celery Beat
    participant W as Celery Worker
    participant DB as PostgreSQL
    participant G as Gemini Flash
    participant C as Claude Sonnet
    participant MGR as Manager (Web)
    participant API as FastAPI
    participant OWN as Avatar Owner
    participant R as Reddit

    Note over CB,R: === SCRAPING (continuous, every 60s tick) ===
    CB->>W: queue_tick
    W->>DB: get stalest subreddit (freshness gate)
    W->>R: scrape posts (PRAW, 25 posts)
    R-->>W: posts
    W->>DB: save reddit_threads (skip locked)

    Note over CB,R: === AI PIPELINE (08:00 & 14:00 UTC) ===
    CB->>W: run_full_pipeline_all_clients
    W->>DB: get active clients
    
    loop Per client
        W->>DB: get unscored threads (max 50, <72h)
        W->>G: score threads (keywords + profile)
        G-->>W: relevance, quality, strategic, tag
        W->>DB: save ThreadScore (engage/monitor/skip)
        
        W->>DB: get threads with tag='engage'
        W->>C: select persona (thread + avatars + karma)
        C-->>W: avatar_id, engagement_mode, angle
        W->>DB: update thread assignment
        
        W->>C: generate comment (voice + strategy + learning)
        C-->>W: comment, location, approach
        W->>DB: save comment_draft (status='pending')
    end

    W->>DB: log ai_usage (tokens, cost)

    Note over MGR,API: === HUMAN REVIEW ===
    MGR->>API: GET /review/comments
    API->>DB: get pending drafts
    DB-->>API: drafts
    API-->>MGR: render UI (Jinja2 + HTMX)
    
    MGR->>API: POST approve/edit/reject
    API->>DB: status = 'approved' (or 'rejected')
    API->>DB: capture_edit_record (learning loop)
    API->>DB: audit_log entry

    Note over OWN,R: === MANUAL POSTING (current) ===
    MGR-->>OWN: notify (Slack/message) — approved drafts ready
    OWN->>API: GET /review/comments (view approved)
    OWN->>OWN: copy comment text
    OWN->>R: paste comment in Reddit browser
    OWN->>API: mark as posted
    API->>DB: status = 'posted', posted_at = now()
```

---

## 4. Mobile App State Diagram [PLANNED — NOT YET IMPLEMENTED]

```mermaid
stateDiagram-v2
    [*] --> Idle
    
    Idle --> Polling: Timer (every hour)<br/>within active hours (9-21)
    Polling --> Fetching: GET /api/mobile/feed
    Fetching --> HasComments: comments > 0
    Fetching --> Idle: comments = 0
    
    HasComments --> DisplayFeed
    DisplayFeed --> ReadyToPost
    
    ReadyToPost --> Posting: user taps [POST]
    Posting --> CopyClipboard: text copied
    CopyClipboard --> OpenReddit: Reddit opens in browser
    OpenReddit --> WaitConfirm: user pastes & submits
    WaitConfirm --> Reporting: user confirms "Posted"
    
    Posting --> Error: clipboard/browser fails
    Error --> ReadyToPost: retry button
    
    Reporting --> Idle: POST /api/mobile/report<br/>comment removed from feed
    
    Idle --> Settings: user opens settings
    Settings --> Idle: save
    
    Idle --> OfflineMode: no internet
    OfflineMode --> Idle: internet restored

    note right of Idle
        Mobile app NOT YET BUILT.
        Current posting: manual copy-paste
        via web interface.
    end note
```

---

## 5. Database Table Relationships

```mermaid
erDiagram
    clients {
        uuid id PK
        string client_name
        text company_profile
        jsonb keywords "high/medium/low"
        boolean is_active
        string plan_type
        int max_avatars
        boolean draft_approval_enabled
    }

    avatars {
        uuid id PK
        text[] client_ids
        string reddit_username
        text voice_profile_md
        int warming_phase "0=Mentor 1-3=Active"
        boolean is_frozen
        string freeze_reason
        boolean is_farm_avatar
        decimal rent_price
    }

    subreddits {
        uuid id PK
        string name UK
        datetime last_scraped_at
    }

    client_subreddit_assignments {
        uuid id PK
        uuid client_id FK
        uuid subreddit_id FK
        string type "target/hobby/presence"
        boolean is_active
    }

    reddit_threads {
        uuid id PK
        uuid subreddit_id FK
        string reddit_native_id UK
        string post_title
        boolean is_locked
        datetime created_at
    }

    thread_scores {
        uuid id PK
        uuid thread_id FK
        uuid client_id FK
        int relevance
        int quality
        int strategic
        int composite
        string tag "engage/monitor/skip"
    }

    comment_drafts {
        uuid id PK
        uuid thread_id FK
        uuid client_id FK
        uuid avatar_id FK
        string status "pending/approved/rejected/posted"
        string type "professional/hobby"
        text ai_draft
        text edited_draft
        string comment_approach
        string strategic_angle
        datetime posted_at
        jsonb learning_metadata
    }

    users {
        uuid id PK
        string email UK
        string role "owner/partner/client_admin/..."
        uuid client_id FK "nullable"
        boolean is_active
    }

    user_client_assignments {
        uuid id PK
        uuid user_id FK
        uuid client_id FK
        string role
    }

    avatar_rentals {
        uuid id PK
        uuid avatar_id FK
        uuid client_id FK
        boolean is_active
        datetime expires_at
        decimal price
    }

    edit_records {
        uuid id PK
        uuid avatar_id FK
        uuid comment_draft_id FK
        text ai_draft
        text edited_draft
        text edit_summary
    }

    correction_patterns {
        uuid id PK
        uuid avatar_id FK
        string pattern_type
        text rule_text
        int frequency
    }

    ai_usage_log {
        uuid id PK
        uuid client_id FK
        string model
        int input_tokens
        int output_tokens
        decimal cost_usd
    }

    audit_log {
        uuid id PK
        uuid user_id FK
        string action
        jsonb details
        datetime created_at
    }

    clients ||--o{ client_subreddit_assignments : has
    subreddits ||--o{ client_subreddit_assignments : assigned_to
    subreddits ||--o{ reddit_threads : contains
    clients ||--o{ thread_scores : scores_for
    reddit_threads ||--o{ thread_scores : scored_as
    clients ||--o{ comment_drafts : owns
    avatars ||--o{ comment_drafts : writes
    reddit_threads ||--o{ comment_drafts : generates
    users ||--o{ user_client_assignments : assigned
    clients ||--o{ user_client_assignments : has_users
    avatars ||--o{ avatar_rentals : rented_as
    clients ||--o{ avatar_rentals : rents
    avatars ||--o{ edit_records : learns_from
    avatars ||--o{ correction_patterns : has_patterns
    clients ||--o{ ai_usage_log : tracked
```

---

## 6. Deployment Architecture (Current — DigitalOcean)

```mermaid
flowchart TB

subgraph DO["DigitalOcean Droplet — 161.35.27.165"]
    subgraph DOCKER["Docker Compose"]
        APP["FastAPI App<br/>:8000<br/>(Jinja2 + HTMX + REST API)"]
        CELERY["Celery Worker<br/>(prefork pool)"]
        BEAT["Celery Beat<br/>(scheduler)"]
        PG["PostgreSQL 16<br/>26 tables"]
        RD["Redis 7<br/>Queue + Cache + Locks"]
    end
end

subgraph EXTERNAL["External Services"]
    ANTHROPIC["Anthropic API<br/>Claude Sonnet 4"]
    GOOGLE["Google AI API<br/>Gemini 2.0 Flash"]
    REDDIT_API["Reddit API<br/>oauth.reddit.com"]
end

subgraph USERS["Users"]
    MANAGER["Tzvi (Manager)<br/>💻 Browser → IP:8000"]
    OWNER["Avatar Owner<br/>📋 Manual posting via Reddit Web"]
end

MANAGER -->|HTTP :8000| APP
APP --> PG
APP --> RD
CELERY --> PG
CELERY --> RD
BEAT --> RD
CELERY -->|LiteLLM| ANTHROPIC
CELERY -->|LiteLLM| GOOGLE
CELERY -->|PRAW| REDDIT_API
OWNER -->|posts on| REDDIT_API

style DO fill:#0a2b3e,stroke:#1a5d7a,color:#eee
style DOCKER fill:#0d3b5e,stroke:#2a6a9a,color:#eee
style EXTERNAL fill:#2d1b36,stroke:#6b2d5c,color:#eee
style USERS fill:#1a3a2a,stroke:#2d6a4f,color:#eee
```

---

## 7. Deployment Architecture (Planned — AWS Migration)

```mermaid
flowchart TB

subgraph AWS["AWS Account (planned — when 100+ avatars)"]
    subgraph VPC["VPC"]
        subgraph PUBLIC["Public Subnet"]
            ALB["Application Load Balancer"]
        end
        subgraph PRIVATE["Private Subnet"]
            EC2["EC2 Instance<br/>Docker:<br/>- FastAPI<br/>- Celery Worker"]
            RDS["RDS PostgreSQL<br/>db.t4g.small"]
            VALKEY["ElastiCache Valkey<br/>Serverless"]
            SQS["SQS Queues<br/>(replace Celery/Redis)"]
        end
    end
    S3["S3 Bucket<br/>Logs & Backups"]
    CLOUDWATCH["CloudWatch<br/>Logs + Metrics"]
end

subgraph EXTERNAL["External LLM APIs"]
    ANTHROPIC["Anthropic API<br/>Claude Sonnet 4"]
    GOOGLE["Google AI API<br/>Gemini Flash"]
end

USER["Manager (Desktop)"] -->|HTTPS| ALB
OWNER["Avatar Owner (Phone)"] -->|HTTPS| ALB
ALB --> EC2
EC2 --> RDS
EC2 --> VALKEY
EC2 --> SQS
EC2 -->|LiteLLM| ANTHROPIC
EC2 -->|LiteLLM| GOOGLE
EC2 --> S3
EC2 --> CLOUDWATCH
REDDIT["Reddit API"] <-->|PRAW| EC2

style AWS fill:#0a2b3e,stroke:#1a5d7a,color:#eee
style EXTERNAL fill:#2d1b36,stroke:#6b2d5c,color:#eee
```

---

## 8. Celery Beat Schedule (Visual)

```mermaid
gantt
    title Daily Task Schedule (UTC)
    dateFormat HH:mm
    axisFormat %H:%M

    section Continuous
    queue_tick (scrape)          :active, 00:00, 24h

    section Morning Batch
    Profile Analytics           :05:20, 10min
    Phase Evaluation            :06:00, 15min
    CQS Batch Check             :06:30, 20min
    Health Check (AM)           :07:30, 15min
    AI Pipeline (morning)       :08:00, 30min

    section Midday
    Hobby Pipeline              :10:00, 15min
    Health Check (PM)           :13:30, 15min
    AI Pipeline (afternoon)     :14:00, 30min

    section Periodic
    Karma Tracking (every 4h)   :00:15, 10min
```

---

## 9. Comment Draft Status Workflow

```mermaid
stateDiagram-v2
    [*] --> pending: AI generates draft

    pending --> approved: Manager approves
    pending --> approved: Manager edits + approves
    pending --> rejected: Manager rejects
    pending --> rejected: Thread locked (auto-reject)

    approved --> posted: Avatar owner posts manually

    rejected --> [*]: End (archived)
    posted --> [*]: End (success)

    note right of pending
        Self-learning loop captures
        all transitions (edit records)
    end note

    note right of approved
        Current: manual copy-paste
        Future: mobile app one-tap
    end note
```

---

## 10. Self-Learning Loop

```mermaid
flowchart LR

subgraph REVIEW["Human Review"]
    APPROVE["✅ Approve"]
    EDIT["✏️ Edit + Approve"]
    REJECT["❌ Reject"]
end

subgraph LEARNING["Learning Service"]
    CAPTURE["capture_edit_record()"]
    DIFF["compute_edit_summary()<br/>(word-level diff)"]
    PATTERNS["recompute_correction_patterns()<br/>(every 5 new records)"]
    FEWSHOT["select_few_shot_examples()<br/>(relevance-scored)"]
end

subgraph GENERATION["Next Generation"]
    INJECT["format_learning_context()"]
    PROMPT["Generation Prompt:<br/>voice + strategy +<br/>few-shot + patterns +<br/>thread"]
end

APPROVE --> CAPTURE
EDIT --> CAPTURE
REJECT --> CAPTURE
CAPTURE --> DIFF
DIFF --> PATTERNS
PATTERNS --> FEWSHOT
FEWSHOT --> INJECT
INJECT --> PROMPT

style REVIEW fill:#2a3a2a,stroke:#4a7a4a,color:#eee
style LEARNING fill:#2d1b36,stroke:#6b2d5c,color:#eee
style GENERATION fill:#1a2a3a,stroke:#3a5a7a,color:#eee
```

---

## Legend

| Icon | Meaning |
|------|---------|
| 🔄 | Scheduled / Automated Job |
| 🧠 | AI Call (LiteLLM → Anthropic/Google) |
| 👤 | Human Action |
| 💾 | Database / Storage |
| 📋 | Manual Copy-Paste (current posting) |
| 📱 | Mobile Application [PLANNED] |
| 💻 | Desktop Web |
| 🔴 | Reddit External Service |
| ⏰ | Time-based Trigger |
| 🖥️ | DigitalOcean Droplet |
