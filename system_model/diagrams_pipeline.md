> **What this is:** RAMP execution flow diagrams — full pipeline sequence diagram, dual pipeline architecture, component layout.
> **Data source:** Extracted from tasks/worker.py (Beat schedule), tasks/orchestrator.py (chaining), services/ (business logic).
> **IMPORTANT:** EPG build has NO distributed lock (GAP-003). Execution Task and Auto Posting are PARALLELLLEL paths (not ). Fitness Gate   EPG and Generation.

---

# Pipeline Diagrams (Correct)

## Main Pipeline Sequence

```mermaid
sequenceDiagram
    participant Beat as Celery Beat
    participant Scraper
    participant Scoring as Smart Scoring
    participant EPG as EPG Builder
    participant FitnessGate as Fitness Gate
    participant Gen as Generator
    participant Rev as Human Review
    participant ExecTask as Execution Task
    participant Poster as Auto Posting
    participant Karma as Karma Tracker
    participant Feedback as Feedback Loop
    participant DB as PostgreSQL
    participant Redis
    participant Reddit as Reddit API
    participant Claude as Claude Sonnet
    participant Gemini as Gemini Flash

    Note over Beat,Gemini: Phase 1: Scraping (every 60s, gated by interval)
    Beat->>Scraper: queue_tick
    Scraper->>Reddit: PRAW scrape (25 posts/sub)
    Reddit-->>Scraper: Threads
    Scraper->>DB: Save RedditThread records

    Note over Beat,Gemini: Phase 2: Scoring (08:00, 14:00)
    Beat->>Scoring: score_threads (per client)
    Scoring->>DB: Get unscored threads (budget * 3, max 15)
    Scoring->>Gemini: SCORING_PROMPT (batch up to 10)
    Gemini-->>Scoring: {tag: engage/monitor/skip, composite: 0-9}
    Scoring->>DB: Save ThreadScore (per-client)

    Note over Beat,Gemini: Phase 3: EPG Planning (08:15, 14:15)
    Beat->>EPG: build_and_generate_epg_all_avatars
    EPG->>DB: Get engage threads + avatar budget
    Note right of EPG: NO distributed lock (GAP-003)
    EPG->>DB: Save EPGSlot (status=planned)

    Note over Beat,Gemini: Phase 4: Fitness Gate + Generation
    EPG->>FitnessGate: Check avatar eligibility per subreddit
    FitnessGate-->>EPG: pass/block (min_karma, frequency, dangerous_hours)
    EPG->>Gen: Generate for passed slots
    loop For each planned slot
        Gen->>DB: Get voice_profile + learning_context + strategy_context
        Gen->>Claude: PERSONA_SELECT_PROMPT
        Claude-->>Gen: {persona, mode, thread_angle}
        Gen->>Claude: COMMENT_WRITER_PROMPT (with injections)
        Claude-->>Gen: {comment, approach, location}
        Gen->>Claude: EDITOR_PROMPT (cleanup pass)
        Claude-->>Gen: Cleaned text
        Gen->>DB: Save CommentDraft (status=pending), EPGSlot→generated
    end

    Note over Beat,Gemini: Phase 5: Human Review (async, manual)
    Rev->>DB: Get pending drafts
    alt Approve
        Rev->>DB: draft.status = approved, slot.status = approved
        alt Executor email configured
            Rev->>DB: Create ExecutionTask (status=generated)
        end
    else Edit + Approve
        Rev->>DB: draft.edited_draft = new text, status = approved
        Rev->>DB: Save EditRecord (learning capture)
    else Reject
        Rev->>DB: draft.status = rejected, slot.status = skipped
    end

    Note over Beat,Gemini: Phase 6a: Email Delivery (every 5 min)
    Beat->>ExecTask: dispatch_due_email_tasks
    ExecTask->>DB: Find tasks where scheduled_at within 30min
    ExecTask->>ExecTask: Send email via Brevo API
    ExecTask->>DB: task.status = emailed

    Note over Beat,Gemini: Phase 6b: Auto Posting (every 5 min, when enabled)
    Beat->>Poster: execute_pending_posts
    Poster->>DB: Find approved slots with scheduled_at <= now
    Poster->>Poster: check_posting_safety() [9 gates]
    alt All gates pass
        Poster->>Reddit: PRAW post_comment()
        Reddit-->>Poster: comment URL
        Poster->>DB: draft.status=posted, slot.status=posted
        Poster->>DB: Save PostingEvent (audit)
    else Gate fails
        Poster->>DB: Log failure reason
    end

    Note over Beat,Gemini: Phase 7: Signal Collection (every 4h)
    Beat->>Karma: track_karma_all_avatars
    Karma->>Reddit: Get comment karma/status
    Reddit-->>Karma: {score, is_deleted, replies}
    Karma->>DB: Save KarmaSnapshot (4h/24h/48h/7d)
    Karma->>DB: Draft reconciliation (3-pass matching)

    Note over Beat,Gemini: Phase 8: Adaptation (02:00 daily)
    Beat->>Feedback: run_feedback_loop_all
    Feedback->>DB: Analyze KarmaSnapshots (outcomes)
    Feedback->>Redis: Update epg_adjustments (subreddit weights)
    Note right of Feedback: Effects next EPG build (08:15)
```

## Dual Pipeline Architecture

```mermaid
graph TB
    subgraph "Professional Pipeline (Phase 2+)"
        PS1[queue_tick every 60s] --> PS2[subreddits table]
        PS2 --> PS3[(reddit_threads)]
        PS3 --> PS4[Smart Scoring<br/>Gemini Flash<br/>budget*3, max 15]
        PS4 --> PS5[(thread_scores)]
        PS5 --> PS6[EPG Portfolio Manager]
        PS6 --> PS7[Generation<br/>Claude Sonnet]
        PS7 --> PS8[5-15 drafts/day]
    end

    subgraph "Hobby Pipeline (Phase 1+)"
        HP1[scrape_hobby_all_avatars<br/>07:45, 13:45] --> HP2[PRAW direct]
        HP2 --> HP3[(hobby_subreddits)]
        HP3 --> HP4[EPG Portfolio Manager<br/>Source 2]
        HP4 --> HP5[Generation<br/>Gemini Flash]
        HP5 --> HP6[1-3 drafts/day]
    end

    subgraph "Shared"
        SH1[Human Review]
        SH2[Execution Task / Auto Posting]
        SH3[Karma Tracking]
    end

    PS8 --> SH1
    HP6 --> SH1
    SH1 --> SH2
    SH2 --> SH3

    style PS1 fill:#e6f3ff
    style HP1 fill:#fff3e6
```

## Component Architecture

```mermaid
graph TB
    subgraph "Layer: Onboarding"
        OB1[Client Onboarding<br/>6-step AI wizard]
        OB2[Avatar Onboarding<br/>PRAW + Claude analysis]
        OB3[Trial Provisioning<br/>async BYOA]
    end

    subgraph "Layer: Ongoing Intelligence"
        D1[Continuous Discovery<br/>Sun 04:00]
        D2[Strategy Generation<br/>max 1/week/client]
        D3[GEO/AEO Monitoring<br/>admin trigger]
        D4[Trial Intelligence<br/>every 4h]
    end

    subgraph "Layer: Discovery"
        EX1[Scraping<br/>every 60s]
        EX2[Smart Scoring<br/>08:00, 14:00]
    end

    subgraph "Layer: Planning"
        EX3[EPG Build<br/>08:15, 14:15]
        FG[Fitness Gate<br/>inline check]
    end

    subgraph "Layer: Generation"
        EX4[Comment Generation<br/>Claude Sonnet]
        EX4H[Hobby Generation<br/>Gemini Flash]
    end

    subgraph "Layer: Human Gate"
        EX5[Review Queue<br/>approve/edit/reject]
    end

    subgraph "Layer: Execution (PARALLEL paths)"
        EX6[Auto Posting<br/>PRAW + 9 gates]
        EX7[Execution Task<br/>Email to executor]
    end

    subgraph "Layer: Signals"
        S1[Karma Tracking<br/>every 4h]
        S2[Outcome Snapshot<br/>4h/24h/48h/7d]
        S3[Health Check<br/>07:30, 13:30]
        S4[Draft Reconciliation<br/>inside karma tracking]
    end

    subgraph "Layer: Adaptation"
        A1[Phase Evaluation<br/>daily 06:00]
        A2[Feedback Loop<br/>daily 02:00]
        A3[Learning Loop<br/>on human edit]
        A4[Risk Profile<br/>weekly Sun]
    end

    OB1 --> OB2
    OB2 --> EX1
    D1 --> D2
    D2 --> EX4

    EX1 --> EX2
    EX2 --> EX3
    EX3 --> FG
    FG --> EX4
    FG --> EX4H
    EX4 --> EX5
    EX4H --> EX5
    EX5 --> EX6
    EX5 --> EX7
    EX5 --> A3

    EX6 --> S1
    EX7 --> S1
    S1 --> S2
    S1 --> S4
    S2 --> A2
    S3 --> A1
    A2 --> EX3
    A1 --> EX2
    A3 --> EX4
    A4 --> FG
```
