> **What this is:** Safety diagrams (9 posting gates), AI model routing, learning loop, and deployment.
> **Data source:** services/posting_safety.py (gates), services/ai.py + config.py (model routing), services/learning.py (loop), docker-compose.yml (deployment).
> **IMPORTANT:** 5 containers (NOT 6). Email via Brevo (NOT SendGrid). Kill switch propagation up to 5 m (not instant).

---

# Safety & AI Diagrams (Correct)

## Posting Safety Gates (9 Sequential Checks)

```mermaid
flowchart TD
    START[Post attempt] --> G0{POSTING_DISABLED\nenv var}
    G0 -->|true| BLOCK0[❌ Env-level kill]
    G0 -->|false| G1{auto_posting_enabled\nDB setting}
    G1 -->|false| BLOCK1[❌ Global disabled]
    G1 -->|true| G2{avatar.posting_mode\n== 'auto'?}
    G2 -->|no| BLOCK2[❌ Mode disabled]
    G2 -->|yes| G3{avatar.is_frozen?}
    G3 -->|yes| BLOCK3[❌ Frozen]
    G3 -->|no| G4{health_status in\nshadowbanned/suspended?}
    G4 -->|yes| BLOCK4[❌ Unhealthy]
    G4 -->|no| G5{warming_phase == 0?}
    G5 -->|yes| BLOCK5[❌ Mentor excluded]
    G5 -->|no| G6{today_count >= cap?\ncap = min phase_limit, system_cap}
    G6 -->|yes| BLOCK6[❌ Daily cap reached]
    G6 -->|no| G7{proxy_url_encrypted\nempty?}
    G7 -->|yes| BLOCK7[❌ No proxy]
    G7 -->|no| G8{user_agent_string\nempty?}
    G8 -->|yes| BLOCK8[❌ No UA]
    G8 -->|no| G9{resolved_ip same /24\nas last_posted_ip?}
    G9 -->|no| BLOCK9[❌ Subnet changed]
    G9 -->|yes| ALLOW[✅ POST ALLOWED]

    style ALLOW fill:#22c55e,color:#fff
    style BLOCK0 fill:#ef4444,color:#fff
    style BLOCK1 fill:#ef4444,color:#fff
    style BLOCK2 fill:#ef4444,color:#fff
    style BLOCK3 fill:#ef4444,color:#fff
    style BLOCK4 fill:#ef4444,color:#fff
    style BLOCK5 fill:#ef4444,color:#fff
    style BLOCK6 fill:#ef4444,color:#fff
    style BLOCK7 fill:#ef4444,color:#fff
    style BLOCK8 fill:#ef4444,color:#fff
    style BLOCK9 fill:#ef4444,color:#fff
```

## AI Model Routing Map

```mermaid
graph LR
    subgraph "Model Selection (NO centralized router)"
        DB_SETTING["system_settings DB table"]
        DB_SETTING -->|llm_scoring_model| GEMINI[Gemini Flash\n$0.0003/call]
        DB_SETTING -->|llm_generation_model| CLAUDE[Claude Sonnet\n$0.04/call]
    end

    subgraph "Uses Gemini Flash (cheap)"
        S1[Thread Scoring]
        S2[Batch Scoring]
        S3[Hobby Generation]
        S4[Rule Extraction]
        S5[Emotional Profile]
        S6[Compatibility Scoring]
        S7[Strategy Generation]
        S8[Report Generation]
        S9[Entity Extraction]
        S10[Hypothesis Generation]
        S11[Onboarding ICP/Keywords/Subs]
        S12[Correction Pattern Extraction]
    end

    subgraph "Uses Claude Sonnet (quality)"
        C1[Persona Selection]
        C2[Comment Generation]
        C3[Comment Editor]
        C4[Post Brief Generation]
        C5[Post Writing]
        C6[Avatar Analysis]
    end

    GEMINI --> S1
    GEMINI --> S2
    GEMINI --> S3
    GEMINI --> S4
    GEMINI --> S5
    GEMINI --> S6
    GEMINI --> S7
    GEMINI --> S8
    GEMINI --> S9
    GEMINI --> S10
    GEMINI --> S11
    GEMINI --> S12

    CLAUDE --> C1
    CLAUDE --> C2
    CLAUDE --> C3
    CLAUDE --> C4
    CLAUDE --> C5
    CLAUDE --> C6

    style GEMINI fill:#4ade80
    style CLAUDE fill:#818cf8
```

## Learning Loop Flow

```mermaid
flowchart TD
    subgraph "1. Capture"
        A1[Human edits draft] --> A2{edited_draft != ai_draft?}
        A2 -->|yes| A3[LearningService.capture_edit_record]
        A3 --> A4[(EditRecord saved\nmax 50 per avatar)]
    end

    subgraph "2. Pattern Extraction"
        B1{5+ EditRecords\naccumulated?} -->|yes| B2[recompute_correction_patterns]
        B2 --> B3[Cluster similar edits]
        B3 --> B4[Gemini Flash: generate rule_text]
        B4 --> B5[(CorrectionPattern saved\nmax 10 per avatar-client)]
    end

    subgraph "3. Injection (next generation call)"
        C1[select_few_shot_examples\nby subreddit + mode similarity]
        C2[get_correction_patterns\nby avatar + client]
        C1 --> C3[format_learning_context]
        C2 --> C3
        C3 --> C4[Append to COMMENT_WRITER_PROMPT\nsystem message]
        C4 --> C5[Claude Sonnet generates\nimproved draft]
    end

    A4 --> B1
    B5 --> C2
    A4 --> C1
```

## Deployment (5 containers, CORRECT)

```mermaid
graph TB
    subgraph "DigitalOcean FRA1: reddit-saas droplet"
        subgraph "Docker Compose (2 vCPU, 4GB RAM, 60GB SSD)"
            APP[app\nFastAPI/Uvicorn\nPort 8000]
            DB[(db\nPostgreSQL 16\nPort 5432\nTZ: Asia/Jerusalem)]
            REDIS[(redis\nRedis 7\nPort 6379)]
            CELERY[celery\nWorker prefork]
            BEAT[celery-beat\nScheduler]
        end
    end

    subgraph "External"
        REDDIT[Reddit API\nPRAW 60 req/min]
        CLAUDE_EXT[Anthropic Claude\nvia LiteLLM]
        GEMINI_EXT[Google Gemini\nvia LiteLLM]
        BREVO[Brevo Email API\n+ SMTP fallback]
    end

    subgraph "Developer"
        LOCAL[Local Mac\nrsync > ramp:/app/\ndocker compose build + up]
    end

    APP --> DB
    APP --> REDIS
    CELERY --> DB
    CELERY --> REDIS
    BEAT --> REDIS
    APP --> REDDIT
    CELERY --> REDDIT
    APP --> CLAUDE_EXT
    APP --> GEMINI_EXT
    CELERY --> CLAUDE_EXT
    CELERY --> GEMINI_EXT
    APP --> BREVO
    CELERY --> BREVO
    LOCAL --> APP

    style APP fill:#3b82f6,color:#fff
    style DB fill:#f59e0b,color:#fff
    style REDIS fill:#ef4444,color:#fff
    style CELERY fill:#8b5cf6,color:#fff
    style BEAT fill:#8b5cf6,color:#fff
```

**NOTE:** There is NO `celery-fast` container. ONE queue (default). ONE worker process. Beat is scheduler, not queue.
