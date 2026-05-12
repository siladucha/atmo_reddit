# Design Document — RAMP Pipeline v2

**Version:** 2.0
**Date:** May 2026
**Status:** Draft
**Covers:** Requirements R1–R25

---

## 1. Overview — High-Level Architecture

Pipeline v2 wraps the existing core pipeline (scrape → score → generate → review) with three layers:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ADMIN UI (Jinja2 + HTMX)                     │
│  Budget Dashboard │ Activity Summary │ Strategy Viewer │ Reports    │
└────────────┬────────────────┬──────────────────┬────────────────────┘
             │                │                  │
┌────────────▼────────────────▼──────────────────▼────────────────────┐
│                     API LAYER (FastAPI routes)                       │
│  /admin/budget │ /admin/activity │ /admin/strategy │ /admin/reports │
└────────────┬────────────────┬──────────────────┬────────────────────┘
             │                │                  │
┌────────────▼────────────────▼──────────────────▼────────────────────┐
│                      SERVICE LAYER (new + modified)                  │
│                                                                     │
│  ┌──────────────┐  ┌────────────────┐  ┌──────────────────┐        │
│  │ budget_engine │  │ strategy_engine │  │  report_engine   │        │
│  │  (R1,R4,R7)  │  │ (R15-R19,R22,  │  │   (R21,R24)      │        │
│  │              │  │  R25)           │  │                  │        │
│  └──────┬───────┘  └───────┬────────┘  └────────┬─────────┘        │
│         │                  │                     │                  │
│  ┌──────▼───────┐  ┌───────▼────────┐  ┌────────▼─────────┐        │
│  │ dedup_service │  │  hill_tracker   │  │ coordination_svc │        │
│  │    (R2)       │  │    (R18)        │  │     (R20)        │        │
│  └──────────────┘  └────────────────┘  └──────────────────┘        │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │              EXISTING SERVICES (modified)                    │    │
│  │  safety.py │ scoring.py │ generation.py │ phase.py          │    │
│  │  (R6,R7,R8,R13,R14)  (R3,R22,R23)  (R2,R3,R7,R25) (R5,R12)│    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
             │                │                  │
┌────────────▼────────────────▼──────────────────▼────────────────────┐
│                    DATA LAYER (PostgreSQL + Valkey)                  │
│  New models: StrategyDocument, MentorAnalysis, SubredditAnalysis,   │
│              ClientReport                                           │
│  Modified: CommentDraft (+hill_hook_used), ThreadScore (+metadata)  │
│  Cache: Valkey (cooldowns, brand ratios, budget counters)           │
└─────────────────────────────────────────────────────────────────────┘
```

### Design Principles

1. **Wrap, don't rewrite** — existing services keep their interfaces; v2 adds pre/post hooks
2. **Configuration over code** — all thresholds in `system_settings` table
3. **Transparency first** — every skip/block logged as ActivityEvent
4. **Valkey for hot path** — counters and rate limits in cache, DB as source of truth
5. **Phased delivery** — MVP (R1-R14) ships independently of Growth (R15-R21) and Scale (R22-R25)


---

## 2. New Data Models

### 2.1 StrategyDocument (R15, R25)

```python
# app/models/strategy_document.py
class StrategyDocument(Base):
    __tablename__ = "strategy_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=False)
    
    # Content sections (stored as structured JSONB)
    goals: Mapped[dict] = mapped_column(JSONB, nullable=False)           # 3-5 measurable objectives
    subreddit_priorities: Mapped[dict] = mapped_column(JSONB, nullable=False)  # ranked list with frequency
    tone_guidelines: Mapped[dict] = mapped_column(JSONB, nullable=False)       # formality, humor, expertise
    cadence_rules: Mapped[dict] = mapped_column(JSONB, nullable=False)         # posting frequency
    hook_inventory: Mapped[dict] = mapped_column(JSONB, nullable=False)        # Hill I Die On positions
    forecast: Mapped[dict | None] = mapped_column(JSONB, nullable=True)        # karma projections, phase dates
    
    # Full markdown version for prompt injection
    document_md: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Versioning
    version: Mapped[int] = mapped_column(Integer, default=1)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Manual edits
    edited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_strategy_docs_avatar_current", "avatar_id", "is_current"),
    )
```

### 2.2 MentorAnalysis (R16)

```python
# app/models/mentor_analysis.py
class MentorAnalysis(Base):
    __tablename__ = "mentor_analyses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subreddit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("subreddits.id"), nullable=False)
    mentor_username: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Analysis results (LLM-generated)
    avg_comment_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tone_patterns: Mapped[dict] = mapped_column(JSONB, nullable=False)
    opening_styles: Mapped[dict] = mapped_column(JSONB, nullable=False)
    topic_preferences: Mapped[dict] = mapped_column(JSONB, nullable=False)
    engagement_triggers: Mapped[dict] = mapped_column(JSONB, nullable=False)
    upvote_to_length_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    
    # Raw data
    sample_comments_count: Mapped[int] = mapped_column(Integer, default=0)
    analysis_md: Mapped[str] = mapped_column(Text, nullable=False)  # Full LLM analysis text
    
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_mentor_analyses_subreddit", "subreddit_id"),
        UniqueConstraint("subreddit_id", "mentor_username", name="uq_mentor_subreddit"),
    )
```

### 2.3 SubredditAnalysis (R17)

```python
# app/models/subreddit_analysis.py
class SubredditAnalysis(Base):
    __tablename__ = "subreddit_analyses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subreddit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("subreddits.id"), nullable=False, unique=True)
    
    # Analysis results
    dominant_tone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    avg_comment_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    humor_frequency: Mapped[str | None] = mapped_column(String(50), nullable=True)  # none/low/medium/high
    expertise_level: Mapped[str | None] = mapped_column(String(50), nullable=True)  # beginner/intermediate/expert
    common_formats: Mapped[dict] = mapped_column(JSONB, nullable=False)  # lists, stories, one-liners
    engagement_topics: Mapped[dict] = mapped_column(JSONB, nullable=False)
    
    analysis_md: Mapped[str] = mapped_column(Text, nullable=False)
    sample_comments_count: Mapped[int] = mapped_column(Integer, default=0)
    
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

### 2.4 ClientReport (R21, R24)

```python
# app/models/client_report.py
class ClientReport(Base):
    __tablename__ = "client_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    
    # Period
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "weekly" | "monthly"
    
    # Content sections (JSONB for structured data)
    executive_summary: Mapped[dict] = mapped_column(JSONB, nullable=False)
    activity_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    avatar_health: Mapped[dict] = mapped_column(JSONB, nullable=False)
    strategy_section: Mapped[dict] = mapped_column(JSONB, nullable=False)
    weekly_tactics: Mapped[dict] = mapped_column(JSONB, nullable=False)
    forecast: Mapped[dict] = mapped_column(JSONB, nullable=False)
    questions_for_client: Mapped[dict] = mapped_column(JSONB, nullable=False)
    
    # Full rendered content
    report_md: Mapped[str] = mapped_column(Text, nullable=False)
    report_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    
    # Comparison to previous period
    period_comparison: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    generated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        Index("ix_client_reports_client_period", "client_id", "period_end"),
    )
```

### 2.5 Migrations to Existing Models

#### CommentDraft — add `hill_hook_used` (R18)

```python
# New column on comment_drafts table
hill_hook_used: Mapped[str | None] = mapped_column(String(255), nullable=True)
# Stores the hook text used (from avatar.hill_i_die_on), or NULL if no hook
```

#### ThreadScore — add `scoring_metadata` (R22)

```python
# New column on thread_scores table
scoring_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
# Stores applied bonuses/penalties: {"hill_bonus": 0.2, "repeat_penalty": -0.3, "history_bonus": 0.15}
```


---

## 3. New Services

### 3.1 budget_engine.py (R1, R4, R7)

```python
# app/services/budget_engine.py
"""Dynamic budget calculation and enforcement.

Replaces fixed MAX_COMMENTS_PER_DAY with formula-based limits
that account for account age, karma, CQS, and warming phase.
"""

class BudgetEngine:
    """Calculates and enforces daily comment budgets per avatar."""

    def calculate_daily_limit(self, avatar: Avatar) -> int:
        """R1.1-R1.4: Compute dynamic daily limit.
        
        Formula: base_limit = min(floor(age_days/7), 10) 
                            + min(floor(karma/500), 5)
                            + min(floor(cqs/20), 3)
        
        Then: effective_limit = min(base_limit, phase_cap)
        Phase caps: P1=3, P2=7, P3=uncapped (formula result)
        """

    def get_remaining_budget(self, db: Session, avatar: Avatar) -> int:
        """R1.5-R1.6: Daily limit minus today's used count."""

    def is_exhausted(self, db: Session, avatar: Avatar) -> bool:
        """R1.6: True if remaining budget is zero."""

    def get_client_budget_summary(self, db: Session, client_id: uuid.UUID) -> dict:
        """R1.7: Aggregate budget across all active avatars for a client."""

    def get_scoring_cost_preview(self, db: Session, client_id: uuid.UUID) -> dict:
        """R4.1-R4.6: Count eligible unscored threads and estimate cost.
        
        Returns: {unscored_count, estimated_cost_usd, eligible: bool}
        Applies thread freshness filter (R3) and is_locked check.
        """

    def reset_daily_counters(self):
        """R1.8: Called at 00:00 UTC — invalidates Valkey budget cache."""
```

### 3.2 dedup_service.py (R2)

```python
# app/services/dedup_service.py
"""Cross-avatar deduplication within the same client.

Prevents multiple avatars of the same client from commenting
in the same thread.
"""

class DedupService:
    """Thread deduplication across avatars of the same client."""

    def get_excluded_thread_ids(
        self, db: Session, client_id: uuid.UUID, avatar_id: uuid.UUID
    ) -> set[uuid.UUID]:
        """R2.1-R2.3: Return thread IDs that this avatar cannot comment on.
        
        Excludes threads where another avatar of the same client has:
        - "approved"/"posted" draft within lookback window (default 30 days)
        - "pending" draft regardless of age
        
        Excludes "rejected" drafts. Excludes drafts by the current avatar.
        """

    def log_dedup_exclusion(
        self, db: Session, thread_id: uuid.UUID, 
        blocked_avatar_id: uuid.UUID, existing_avatar_id: uuid.UUID
    ) -> None:
        """R2.4: Log activity event type='dedup_excluded'."""
```

### 3.3 strategy_engine.py (R15, R16, R17, R19, R22, R25)

```python
# app/services/strategy_engine.py
"""Avatar strategy document generation and management.

Generates strategy documents using LLM, performs mentor/subreddit
analysis, and handles auto-correction on negative performance.
"""

class StrategyEngine:
    """Generates and maintains avatar strategy documents."""

    def generate_strategy_document(
        self, db: Session, avatar: Avatar, client: Client
    ) -> StrategyDocument:
        """R15.1-R15.4: Generate full strategy document via LLM.
        
        Inputs: persona profile, assigned subreddits, client brand brief,
        warming phase, mentor analyses, subreddit analyses.
        
        Outputs: goals, subreddit_priorities, tone_guidelines, 
        cadence_rules, hook_inventory, forecast.
        """

    def generate_forecast(self, db: Session, avatar: Avatar) -> dict:
        """R15.6-R15.7: Generate karma/phase/conversion forecast."""

    def analyze_mentor(
        self, db: Session, subreddit_id: uuid.UUID, mentor_username: str
    ) -> MentorAnalysis:
        """R16.1-R16.4: Fetch top 50 comments via PRAW, analyze with LLM."""

    def analyze_subreddit(
        self, db: Session, subreddit_id: uuid.UUID
    ) -> SubredditAnalysis:
        """R17.1-R17.4: Fetch top 50 comments from subreddit, analyze."""

    def check_auto_correction(
        self, db: Session, avatar: Avatar, subreddit: str
    ) -> bool:
        """R19.1-R19.6: Check for 3 consecutive low-score comments.
        
        Triggers strategy review if detected. Updates strategy document
        with revised guidance for the affected subreddit.
        """

    def apply_strategic_scoring(
        self, db: Session, avatar: Avatar, thread: RedditThread, base_score: int
    ) -> tuple[int, dict]:
        """R22.1-R22.5: Apply bonuses/penalties to base score.
        
        +20% hill hook alignment
        -30% repeat topic (same avatar, same topic, last 7 days)
        +15% historical high engagement subreddit
        
        Returns: (adjusted_score, metadata_dict)
        """
```

### 3.4 report_engine.py (R21, R24)

```python
# app/services/report_engine.py
"""Client report generation service.

Compiles admin data + strategy + forecast into client-facing reports.
"""

class ReportEngine:
    """Generates periodic client reports."""

    def generate_report(
        self, db: Session, client_id: uuid.UUID,
        period_type: str, period_start: datetime, period_end: datetime
    ) -> ClientReport:
        """R21.1-R21.5, R24.1-R24.4: Generate full client report.
        
        Sections:
        - Executive Summary (goals vs actual)
        - Activity (comments, karma, top subreddits)
        - Avatar Health (shadowban, phase, age)
        - Strategy (from StrategyDocument)
        - Weekly Tactics (cadence, split)
        - Forecast (karma, phase, conversions)
        - Questions for Client (3-5 feedback questions)
        - Period comparison (vs previous period)
        """

    def export_report(
        self, db: Session, report_id: uuid.UUID, format: str
    ) -> bytes:
        """R24.5: Export as markdown, JSON, or PDF."""

    def compile_activity_data(
        self, db: Session, client_id: uuid.UUID,
        period_start: datetime, period_end: datetime
    ) -> dict:
        """R21.1: Aggregate comments, scores, brand ratios for period."""
```

### 3.5 hill_tracker.py (R18)

```python
# app/services/hill_tracker.py
"""Hill I Die On hook usage tracking.

Monitors hook usage ratio and provides generation guidance.
"""

class HillTracker:
    """Tracks and manages Hill I Die On hook usage per avatar."""

    def record_hook_usage(
        self, db: Session, comment_draft_id: uuid.UUID, hook_text: str | None
    ) -> None:
        """R18.1: Store hill_hook_used on CommentDraft."""

    def get_hook_ratio(self, db: Session, avatar_id: uuid.UUID) -> float:
        """R18.2: comments_with_hook_last_30_days / total_last_30_days."""

    def get_hook_guidance(self, db: Session, avatar_id: uuid.UUID) -> str | None:
        """R18.3-R18.4: Return prompt instruction based on ratio.
        
        < 25%: "prioritize using a hook"
        > 35%: "avoid hooks"
        else: None (no guidance needed)
        """
```

### 3.6 coordination_service.py (R20)

```python
# app/services/coordination_service.py
"""Cross-avatar thread distribution for a client.

Distributes threads across avatars using weighted round-robin.
"""

class CoordinationService:
    """Distributes thread assignments across client avatars."""

    def distribute_threads(
        self, db: Session, client_id: uuid.UUID,
        eligible_threads: list[RedditThread],
        available_avatars: list[Avatar]
    ) -> list[tuple[RedditThread, Avatar]]:
        """R20.1-R20.4: Weighted round-robin distribution.
        
        Weight = remaining daily budget.
        Constraint: no avatar gets >50% of threads in any single subreddit.
        Tiebreaker: highest subreddit-specific karma.
        Respects: phase gate, cooldown, brand ratio, saturation.
        """
```


---

## 4. Modified Services

### 4.1 safety.py (R6, R7, R13, R14)

**Changes:**

| Current | New |
|---------|-----|
| `MAX_COMMENTS_PER_DAY = 8` (fixed) | Delegates to `BudgetEngine.calculate_daily_limit()` |
| `MAX_COMMENTS_PER_SUBREDDIT_DAY = 2` (fixed) | Reads from `SystemSetting("max_comments_per_sub_per_day")` |
| `MIN_MINUTES_BETWEEN_COMMENTS = 15` (fixed) | Reads from `SystemSetting("min_comment_interval_minutes")` |
| `MAX_BRAND_RATIO = 0.3` over 7-day window | Reads from `SystemSetting("max_brand_ratio_percent")` over 30-day window |
| No activity event on subreddit limit | Logs `"saturation_limit_reached"` event (R6.5) |
| Cooldown checks DB every time | Checks Valkey first, falls back to DB (R13.5) |
| Brand ratio uses type-based check | Uses `PhasePolicy.classify_brand_mention()` text-based (R14.4) |

**New function: `check_subreddit_limit()` enhancement (R6.3-R6.5)**

```python
def check_subreddit_limit(db: Session, avatar: Avatar, subreddit: str) -> SafetyCheckResult:
    """Enhanced: configurable threshold + counts pending drafts + logs event."""
    threshold = get_setting(db, "max_comments_per_sub_per_day", default=2)
    # Count pending + approved + posted (R6.4)
    sub_count = count_drafts_in_subreddit_today(db, avatar, subreddit, 
                                                 statuses=["pending", "approved", "posted"])
    if sub_count >= threshold:
        record_activity_event(db, "saturation_limit_reached", ...)
        return SafetyCheckResult(False, f"Subreddit limit for r/{subreddit}")
    return SafetyCheckResult(True)
```

**New function: `run_pre_generation_checks()` (R7.1-R7.8)**

```python
def run_pre_generation_checks(
    db: Session, avatar: Avatar, thread: RedditThread, client: Client
) -> SafetyCheckResult:
    """R7.6: Ordered check sequence — stops at first failure.
    
    Order: phase_gate → budget → saturation → cooldown → brand_ratio
    Logs 'pre_generation_check_failed' on failure (R7.7).
    No retry for failed pair in current run (R7.8).
    """
```

### 4.2 scoring.py (R3, R22, R23)

**Changes:**

| Current | New |
|---------|-----|
| Scores all unscored threads | Filters by thread freshness first (R3.1) |
| One thread per LLM call | Supports batch mode (R23.1-R23.3) |
| No strategic adjustments | Applies bonuses/penalties post-scoring (R22) |
| No cost tracking on dashboard | Exposes cumulative daily cost (R23.4) |

**Thread freshness filter (R3.1, R3.3-R3.5):**

```python
def get_eligible_threads(db: Session, client: Client) -> list[RedditThread]:
    """Filter threads by freshness before scoring."""
    max_age_hours = int(get_setting(db, "thread_max_age_hours", default="48"))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    
    return db.query(RedditThread).filter(
        # Use created_at, fallback to scraped_at if NULL (R3.4)
        func.coalesce(RedditThread.created_at, RedditThread.scraped_at) >= cutoff,
        RedditThread.is_locked.is_(False),
        RedditThread.subreddit_id.in_(client_subreddit_ids),
        ~RedditThread.id.in_(already_scored_ids),
    ).all()
```

**Batch scoring (R23.1-R23.3):**

```python
def score_threads_batch(
    db: Session, threads: list[RedditThread], client: Client, batch_size: int = 10
) -> list[ThreadScore]:
    """Score multiple threads in a single LLM call.
    
    Formats N threads into one prompt, parses N individual scores.
    batch_size from SystemSetting('scoring_batch_size', default='10').
    """
```

### 4.3 generation.py (R2, R3, R7, R18, R25)

**Changes:**

| Current | New |
|---------|-----|
| No dedup check | Calls `DedupService.get_excluded_thread_ids()` (R2) |
| No freshness re-check | Re-checks thread age at generation time (R3.2) |
| Safety checks inline | Delegates to `run_pre_generation_checks()` (R7) |
| No strategy context | Injects StrategyDocument into prompt (R25.1) |
| No hook tracking | Records `hill_hook_used` on draft (R18.1) |
| No hook guidance | Includes hook ratio guidance in prompt (R18.3-R18.4) |

**Strategy injection (R25.1):**

```python
def build_generation_prompt(
    avatar: Avatar, thread: RedditThread, client: Client,
    strategy_doc: StrategyDocument | None
) -> list[dict]:
    """Enhanced prompt with strategy context.
    
    If strategy_doc exists and generated_at < 30 days:
        Include: tone_guidelines, cadence_rules, hook_inventory, 
                 subreddit-specific priorities
    Else:
        Use base persona profile only (R25.4)
    """
```

### 4.4 scraping.py tasks (R8)

**Changes:**

```python
# In tasks/scraping.py — before each subreddit scrape:
def scrape_subreddit(subreddit_id: uuid.UUID):
    """Enhanced with freshness gate (R8)."""
    subreddit = db.query(Subreddit).get(subreddit_id)
    
    min_interval = int(get_setting(db, "min_scrape_interval_minutes", default="30"))
    
    if subreddit.last_scraped_at is not None:  # R8.3: NULL = never scraped, proceed
        elapsed = (now - subreddit.last_scraped_at).total_seconds() / 60
        if elapsed < min_interval:
            record_activity_event(db, "scrape_too_fresh", ...)  # R8.2
            return  # R8.5: don't update last_scraped_at
    
    # ... existing scrape logic ...
    subreddit.last_scraped_at = now  # R8.6
```

### 4.5 phase.py (R5, R12)

**Changes:**

| Current | New |
|---------|-----|
| `MAX_COMMENTS_PER_DAY = 10` for Phase 2 | Changed to `7` (R12.3) |
| Phase 3 uses `MAX_COMMENTS_PER_DAY = 10` | Phase 3 uses `BudgetEngine.calculate_daily_limit()` (R12.4) |

```python
# Constants update:
MAX_COMMENTS_PER_DAY_PHASE1 = 3   # unchanged
MAX_COMMENTS_PER_DAY_PHASE2 = 7   # was 10, now 7 per R12.3
# Phase 3: no constant — uses BudgetEngine formula
```

### 4.6 transparency.py (R9)

**New function:**

```python
def get_today_activity_summary(db: Session) -> list[dict]:
    """R9.1-R9.3: Per-avatar stats for current UTC day.
    
    Returns per avatar:
    - comments_generated, comments_approved, comments_posted
    - threads_scored, threads_skipped (with breakdown by reason)
    - chronological event list (when avatar selected)
    """
```


---

## 5. API Endpoints

### 5.1 Budget Dashboard (R1, R4)

```
GET  /admin/budget                          → Budget dashboard page
GET  /admin/budget/panel                    → HTMX partial (auto-refresh every 60s)
GET  /admin/budget/client/{client_id}       → Client-level budget detail
POST /admin/budget/scoring-preview/{client_id} → Cost preview before scoring batch
POST /admin/budget/execute-scoring/{client_id} → Execute scoring after confirmation
```

### 5.2 Activity Summary (R9)

```
GET  /admin/activity/today                  → Today's activity summary page
GET  /admin/activity/today/panel            → HTMX partial (auto-refresh every 5 min)
GET  /admin/activity/today/avatar/{avatar_id} → Avatar-specific event timeline
```

### 5.3 Inline Draft Editing (R10)

```
GET  /admin/drafts/{draft_id}/editor        → HTMX partial: inline editor form
PUT  /admin/drafts/{draft_id}/edited-draft  → Save edited_draft (HTMX swap)
```

### 5.4 Strategy Management (R15, R16, R17)

```
GET  /admin/avatars/{avatar_id}/strategy           → Strategy document viewer page
POST /admin/avatars/{avatar_id}/strategy/generate  → Trigger strategy generation
PUT  /admin/avatars/{avatar_id}/strategy/edit      → Save manual edits
GET  /admin/avatars/{avatar_id}/strategy/history   → Version history

GET  /admin/subreddits/{sub_id}/mentor-analysis    → Mentor analysis page
POST /admin/subreddits/{sub_id}/mentor-analysis    → Trigger mentor analysis
GET  /admin/subreddits/{sub_id}/subreddit-analysis → Subreddit analysis page
POST /admin/subreddits/{sub_id}/subreddit-analysis → Trigger subreddit analysis
```

### 5.5 Reports (R21, R24)

```
GET  /admin/clients/{client_id}/reports            → Reports list page
POST /admin/clients/{client_id}/reports/generate   → Trigger report generation
GET  /admin/reports/{report_id}                    → View report
GET  /admin/reports/{report_id}/export/{format}    → Download (md/json/pdf)
```

### 5.6 Auto-Correction (R19)

```
GET  /admin/avatars/{avatar_id}/corrections        → Auto-correction history
```

### 5.7 Configuration (System Settings)

```
GET  /admin/settings/pipeline-v2                   → Pipeline v2 settings page
PUT  /admin/settings/pipeline-v2                   → Update settings (HTMX)
```

---

## 6. UI Components (HTMX Partials)

### 6.1 Budget Dashboard Panel (R1, R4)

**Template:** `templates/partials/budget_dashboard.html`

```
┌─────────────────────────────────────────────────────────┐
│ Budget Dashboard                    Auto-refresh: 60s   │
├─────────────────────────────────────────────────────────┤
│ Client: NeuroYoga (ATMO)                                │
│ ┌─────────────┬───────┬──────┬───────────┐             │
│ │ Avatar      │ Limit │ Used │ Remaining │             │
│ ├─────────────┼───────┼──────┼───────────┤             │
│ │ zen_master  │  7    │  3   │  4  ████░ │             │
│ │ yoga_fan    │  3    │  2   │  1  █░░░░ │             │
│ ├─────────────┼───────┼──────┼───────────┤             │
│ │ TOTAL       │ 10    │  5   │  5        │             │
│ └─────────────┴───────┴──────┴───────────┘             │
│                                                         │
│ [Score Threads] → Preview: 42 threads, est. $0.03      │
│                   [Proceed] [Cancel]                    │
└─────────────────────────────────────────────────────────┘
```

**HTMX attributes:**
- `hx-get="/admin/budget/panel"` `hx-trigger="every 60s"`
- Scoring preview: `hx-post="/admin/budget/scoring-preview/{client_id}"` `hx-target="#scoring-preview"`

### 6.2 Today's Activity Summary (R9)

**Template:** `templates/partials/activity_summary.html`

```
┌─────────────────────────────────────────────────────────┐
│ Today's Activity (UTC)              Auto-refresh: 5min  │
├─────────────────────────────────────────────────────────┤
│ Avatar: zen_master                                      │
│   Generated: 3 │ Approved: 2 │ Posted: 1 │ Scored: 15  │
│   Skipped: 5 (freshness:2, dedup:1, saturation:2)      │
│                                                         │
│ Avatar: yoga_fan                                        │
│   Generated: 2 │ Approved: 1 │ Posted: 0 │ Scored: 8   │
│   Skipped: 3 (budget:1, phase:2)                        │
│                                                         │
│ [View Timeline ▼]                                       │
│   09:12 zen_master scored 15 threads                    │
│   09:14 zen_master generated comment in r/yoga          │
│   09:15 yoga_fan skipped r/fitness (phase_block)        │
└─────────────────────────────────────────────────────────┘
```

### 6.3 Inline Draft Editor (R10)

**Template:** `templates/partials/draft_editor.html`

```
┌─────────────────────────────────────────────────────────┐
│ Comment Draft — r/cybersecurity                         │
├─────────────────────────────────────────────────────────┤
│ AI Draft (read-only):                                   │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ "I've been using XDR solutions for a while and..."  │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                         │
│ Edited Draft:                                           │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ [editable textarea with live content]               │ │
│ │                                                     │ │
│ └─────────────────────────────────────────────────────┘ │
│ Characters: 234/1500                    [Save] [Cancel] │
│ ⚠️ Warning shown if > 1500 chars                        │
└─────────────────────────────────────────────────────────┘
```

**HTMX attributes:**
- Save: `hx-put="/admin/drafts/{id}/edited-draft"` `hx-target="closest .draft-card"` `hx-swap="outerHTML"`
- Error handling: `hx-on::after-request="handleSaveError(event)"`
- Pre-populate: if `edited_draft` is NULL, show `ai_draft` content (R10.7)

### 6.4 Strategy Viewer (R15, R25)

**Template:** `templates/partials/strategy_viewer.html`

```
┌─────────────────────────────────────────────────────────┐
│ Strategy Document — zen_master          v3 (May 12)     │
├─────────────────────────────────────────────────────────┤
│ Goals:                                                  │
│   1. Reach 500 karma in r/cybersecurity by June 15      │
│   2. Establish expertise in XDR discussions              │
│   3. Maintain <25% brand ratio                          │
│                                                         │
│ Subreddit Priorities:                                   │
│   1. r/cybersecurity (3x/week)                          │
│   2. r/netsec (2x/week)                                 │
│   3. r/sysadmin (1x/week, hobby)                        │
│                                                         │
│ Active Hooks: "Zero trust is theater without XDR"       │
│ Hook Usage: 28% (target: 25-35%) ✓                      │
│                                                         │
│ [Regenerate] [Edit] [View History]                      │
└─────────────────────────────────────────────────────────┘
```


---

## 7. Configuration — System Settings Keys

All configurable thresholds stored in `system_settings` table with `group = "pipeline_v2"`.

| Key | Default | Range | Requirement | Description |
|-----|---------|-------|-------------|-------------|
| `dedup_lookback_days` | `30` | 1–365 | R2.5 | Lookback window for approved/posted dedup |
| `thread_max_age_hours` | `48` | 1–168 | R3.3 | Max thread age for scoring/generation |
| `max_comments_per_sub_per_day` | `2` | 1–10 | R6.3 | Subreddit saturation limit per avatar |
| `min_scrape_interval_minutes` | `30` | 1–1440 | R8.4 | Minimum time between subreddit scrapes |
| `min_comment_interval_minutes` | `15` | 5–120 | R13.3 | Cooldown between avatar comments |
| `max_brand_ratio_percent` | `30` | 10–80 | R14.3 | Max brand mention ratio (30-day window) |
| `hill_hook_target_min_percent` | `25` | 5–50 | R18.5 | Below this: prompt to use hooks |
| `hill_hook_target_max_percent` | `35` | 20–80 | R18.5 | Above this: prompt to avoid hooks |
| `scoring_batch_size` | `10` | 1–50 | R23.2 | Threads per batch scoring LLM call |
| `strategy_max_age_days` | `30` | 7–90 | R25.2 | Strategy doc validity window |

### Valkey Cache Keys

| Key Pattern | TTL | Purpose |
|-------------|-----|---------|
| `budget:{avatar_id}:{date}` | Until 00:00 UTC | Daily budget remaining counter |
| `cooldown:{avatar_id}` | `min_comment_interval_minutes` | Cooldown lock |
| `brand_ratio:{avatar_id}` | 24h | Cached brand ratio (recalculated daily) |
| `scoring_cost:{client_id}:{date}` | Until 00:00 UTC | Cumulative scoring cost today |

---

## 8. Data Flow — Enhanced Pipeline Execution

### 8.1 Scoring Flow (with R3, R4, R22, R23)

```
Operator triggers scoring for Client X
    │
    ▼
[1] Cost Preview (R4)
    ├── Count eligible threads (fresh + unlocked + unscored)
    ├── Calculate estimated cost
    └── Display to operator → [Proceed] / [Cancel]
    │
    ▼ (on Proceed)
[2] Thread Freshness Filter (R3)
    ├── Exclude threads where age > thread_max_age_hours
    ├── Use scraped_at as fallback if created_at is NULL
    └── Log "thread_too_old" events
    │
    ▼
[3] Batch Scoring (R23)
    ├── Group threads into batches of scoring_batch_size
    ├── Send batch to Gemini Flash
    └── Parse individual scores from response
    │
    ▼
[4] Strategic Scoring Adjustments (R22)
    ├── For each avatar with valid StrategyDocument:
    │   ├── +20% if thread aligns with hill hook
    │   ├── -30% if same topic commented in last 7 days
    │   └── +15% if high historical engagement in subreddit
    └── Store adjustments in scoring_metadata
    │
    ▼
[5] Record ThreadScore + log activity event
```

### 8.2 Generation Flow (with R1-R3, R6-R7, R13-R14, R18, R20, R25)

```
Pipeline triggers generation for Client X
    │
    ▼
[1] Thread Selection
    ├── Get "engage" threads from ThreadScore
    ├── Apply thread freshness filter (R3.2)
    ├── Apply dedup exclusion (R2)
    └── Apply thread liveness check (R11)
    │
    ▼
[2] Cross-Avatar Coordination (R20)
    ├── Get available avatars (active, not frozen)
    ├── Weighted round-robin by remaining budget
    ├── Enforce 50% cap per avatar per subreddit
    └── Prefer highest subreddit karma on ties
    │
    ▼
[3] Per (avatar, thread) pair:
    │
    ├── [3a] Pre-Generation Safety (R7)
    │   ├── Phase Gate (R5) → block if phase restricts subreddit
    │   ├── Budget Check (R1) → block if daily limit exhausted
    │   ├── Saturation Check (R6) → block if subreddit limit hit
    │   ├── Cooldown Check (R13) → block if too soon
    │   └── Brand Ratio Check (R14) → block if ratio exceeded
    │   │
    │   └── On failure: log "pre_generation_check_failed", skip pair
    │
    ├── [3b] Build Prompt (R25)
    │   ├── Base persona profile
    │   ├── Strategy Document (tone, cadence, hooks, priorities)
    │   ├── Hook guidance from HillTracker (R18.3-R18.4)
    │   └── Thread context
    │
    ├── [3c] Call LLM (Claude Sonnet)
    │   └── Generate comment draft
    │
    └── [3d] Post-Generation
        ├── Record hill_hook_used on CommentDraft (R18.1)
        ├── Update Valkey budget counter
        ├── Update Valkey cooldown TTL
        └── Log "generation_complete" activity event
```

### 8.3 Auto-Correction Flow (R19)

```
Karma tracker detects reddit_score update on posted comment
    │
    ▼
[1] Check consecutive low scores
    ├── Query last 3 posted comments in same subreddit
    ├── Filter: reddit_score IS NOT NULL, last_karma_check_at IS NOT NULL
    └── If all 3 have score <= 0: trigger auto-correction
    │
    ▼
[2] Strategy Review
    ├── Analyze 3 failing comments
    ├── Compare with subreddit's successful patterns
    └── Identify mismatch (tone? length? topic?)
    │
    ▼
[3] Update Strategy Document
    ├── Revise tone/approach for affected subreddit
    ├── Log "strategy_auto_corrected" event
    └── Regenerate forecast
```

### 8.4 Report Generation Flow (R21, R24)

```
Operator triggers report for Client X (weekly/monthly)
    │
    ▼
[1] Compile Admin Data
    ├── Comments posted, karma gained, top subreddits
    ├── Avatar health (shadowban, phase, age)
    └── Period comparison (vs previous period)
    │
    ▼
[2] Inject Strategy
    ├── Current StrategyDocument per avatar
    ├── Subreddit priorities, tone calibration
    └── Weekly tactics, templates
    │
    ▼
[3] Generate Forecast (LLM)
    ├── Projected karma (7/14/30 days)
    ├── Expected phase transition date
    └── Estimated conversions (if configured)
    │
    ▼
[4] Generate Questions (LLM)
    └── 3-5 specific feedback questions
    │
    ▼
[5] Store ClientReport + render formats
    ├── Markdown (.md)
    ├── JSON (.json)
    └── PDF (.pdf) — via markdown-to-pdf
```


---

## 9. Migration Plan

### 9.1 Alembic Migrations (ordered)

| # | Migration | Tables/Columns | Requirement |
|---|-----------|---------------|-------------|
| 1 | `add_hill_hook_used_to_comment_drafts` | `comment_drafts.hill_hook_used` (String, nullable) | R18 |
| 2 | `add_scoring_metadata_to_thread_scores` | `thread_scores.scoring_metadata` (JSONB, nullable) | R22 |
| 3 | `create_strategy_documents` | New table `strategy_documents` | R15, R25 |
| 4 | `create_mentor_analyses` | New table `mentor_analyses` | R16 |
| 5 | `create_subreddit_analyses` | New table `subreddit_analyses` | R17 |
| 6 | `create_client_reports` | New table `client_reports` | R21, R24 |
| 7 | `seed_pipeline_v2_settings` | Insert default SystemSetting rows | R2-R8, R13-R14, R18, R23, R25 |

### 9.2 Data Migration Notes

- **Phase 2 limit change (R12.3):** No data migration needed — just update the constant from 10 to 7. Existing comments are unaffected.
- **Brand ratio window change (R14.5):** No migration — the query window changes from 7 to 30 days at runtime.
- **Settings seeding (migration 7):** Insert rows only if key doesn't exist (idempotent).

### 9.3 Settings Seed Data

```python
PIPELINE_V2_SETTINGS = [
    {"key": "dedup_lookback_days", "value": "30", "group": "pipeline_v2",
     "description": "Lookback window (days) for cross-avatar dedup on approved/posted drafts"},
    {"key": "thread_max_age_hours", "value": "48", "group": "pipeline_v2",
     "description": "Maximum thread age (hours) for scoring and generation eligibility"},
    {"key": "max_comments_per_sub_per_day", "value": "2", "group": "pipeline_v2",
     "description": "Maximum comments per subreddit per day per avatar"},
    {"key": "min_scrape_interval_minutes", "value": "30", "group": "pipeline_v2",
     "description": "Minimum minutes between scrapes of the same subreddit"},
    {"key": "min_comment_interval_minutes", "value": "15", "group": "pipeline_v2",
     "description": "Minimum minutes between consecutive comments by same avatar"},
    {"key": "max_brand_ratio_percent", "value": "30", "group": "pipeline_v2",
     "description": "Maximum brand mention ratio (%) over 30-day window"},
    {"key": "hill_hook_target_min_percent", "value": "25", "group": "pipeline_v2",
     "description": "Below this hook usage %, prompt encourages hook usage"},
    {"key": "hill_hook_target_max_percent", "value": "35", "group": "pipeline_v2",
     "description": "Above this hook usage %, prompt discourages hook usage"},
    {"key": "scoring_batch_size", "value": "10", "group": "pipeline_v2",
     "description": "Number of threads per batch scoring LLM call"},
    {"key": "strategy_max_age_days", "value": "30", "group": "pipeline_v2",
     "description": "Strategy document validity window (days)"},
]
```

---

## 10. Dependencies — Implementation Order

### 10.1 Dependency Graph

```
Phase: MVP (R1-R14)
═══════════════════

Layer 0 (no dependencies — can start immediately):
  R5  Phase-Aware Filtering (traceability only, no code)
  R11 Thread Liveness (traceability only, already built)
  R12 Avatar Warming Phases (constant change: 10→7)
  R8  Scrape Freshness Gate (standalone gate in scraping task)
  R10 Inline Draft Editing (standalone UI feature)

Layer 1 (depends on settings infrastructure):
  R3  Thread Freshness Filter (needs SystemSetting read pattern)
  R6  Subreddit Saturation Guard (needs configurable threshold + logging)
  R13 Rate Limits/Cooldowns (needs Valkey cache pattern)
  R14 Brand Ratio Tracking (needs 30-day window + Valkey cache)

Layer 2 (depends on Layer 1):
  R1  Budget Dashboard (depends on R12 phase caps, R14 brand ratio)
  R2  Cross-Avatar Deduplication (depends on R3 freshness for thread eligibility)

Layer 3 (depends on Layer 2):
  R7  Pre-Generation Safety (orchestrates R1 budget + R6 saturation + R13 cooldown + R14 ratio)
  R4  Scoring Cost Preview (depends on R3 freshness filter for eligible count)
  R9  Today's Activity Summary (depends on all event logging from R2-R8)


Phase: Growth (R15-R21)
═══════════════════════

Layer 4 (depends on MVP complete):
  R16 Mentor Analysis (standalone PRAW + LLM)
  R17 Subreddit Analysis (standalone PRAW + LLM)
  R18 Hill I Die On Tracking (needs hill_hook_used column)

Layer 5 (depends on Layer 4):
  R15 Avatar Strategy Document (uses R16 mentor + R17 subreddit as inputs)

Layer 6 (depends on Layer 5):
  R19 Auto-Correction (needs R15 strategy doc to update)
  R20 Cross-Avatar Coordination (needs R1 budget for weighting)
  R21 Client Report Generation (needs activity data from MVP)


Phase: Scale (R22-R25)
══════════════════════

Layer 7 (depends on Growth complete):
  R22 Enhanced Scoring (needs R15 strategy doc for hill alignment)
  R23 Batch Scoring (standalone optimization, can parallel with R22)

Layer 8 (depends on Layer 7):
  R25 Strategy as Pipeline Input (needs R15 + R22 integrated)
  R24 Unified Client Report (needs R21 + R15 strategy + forecast)
```

### 10.2 Recommended Sprint Plan

| Sprint | Requirements | Effort | Key Deliverable |
|--------|-------------|--------|-----------------|
| Sprint 1 | R5, R8, R10, R11, R12 | S | Standalone gates + inline editor |
| Sprint 2 | R3, R6, R13, R14 | M | Configurable thresholds + Valkey cache |
| Sprint 3 | R1, R2 | M | Budget engine + dedup service |
| Sprint 4 | R4, R7, R9 | M | Safety orchestration + dashboard panels |
| Sprint 5 | R16, R17, R18 | M | Analysis services + hook tracking |
| Sprint 6 | R15 | L | Strategy document generation |
| Sprint 7 | R19, R20, R21 | L | Auto-correction + coordination + reports |
| Sprint 8 | R22, R23, R24, R25 | L | Enhanced scoring + unified reports |

### 10.3 Requirement-to-File Mapping

| Requirement | New Files | Modified Files |
|-------------|-----------|----------------|
| R1 | `services/budget_engine.py`, `templates/partials/budget_dashboard.html` | `services/safety.py`, `routes/admin.py` |
| R2 | `services/dedup_service.py` | `services/generation.py`, `tasks/ai_pipeline.py` |
| R3 | — | `services/scoring.py`, `services/generation.py` |
| R4 | `templates/partials/scoring_preview.html` | `routes/admin.py`, `services/budget_engine.py` |
| R5 | — | — (traceability only) |
| R6 | — | `services/safety.py` |
| R7 | — | `services/safety.py`, `services/generation.py` |
| R8 | — | `tasks/scraping.py` |
| R9 | `templates/partials/activity_summary.html` | `services/transparency.py`, `routes/admin.py` |
| R10 | `templates/partials/draft_editor.html` | `routes/admin.py` |
| R11 | — | — (traceability only) |
| R12 | — | `services/phase.py` |
| R13 | — | `services/safety.py` |
| R14 | — | `services/safety.py`, `services/phase.py` |
| R15 | `models/strategy_document.py`, `services/strategy_engine.py`, `templates/admin_strategy.html` | `routes/admin.py` |
| R16 | `models/mentor_analysis.py` | `services/strategy_engine.py`, `routes/admin.py` |
| R17 | `models/subreddit_analysis.py` | `services/strategy_engine.py`, `routes/admin.py` |
| R18 | `services/hill_tracker.py` | `models/comment_draft.py`, `services/generation.py` |
| R19 | — | `services/strategy_engine.py`, `routes/admin.py` |
| R20 | `services/coordination_service.py` | `tasks/ai_pipeline.py` |
| R21 | `models/client_report.py`, `services/report_engine.py`, `templates/admin_reports.html` | `routes/admin.py` |
| R22 | — | `services/scoring.py`, `services/strategy_engine.py` |
| R23 | — | `services/scoring.py` |
| R24 | — | `services/report_engine.py`, `routes/admin.py` |
| R25 | — | `services/generation.py` |

---

## Appendix: Requirement Coverage Matrix

| Req | Title | Design Section | Status |
|-----|-------|---------------|--------|
| R1 | Budget Dashboard | 3.1, 5.1, 6.1, 7 | New service + UI |
| R2 | Cross-Avatar Deduplication | 3.2, 4.3 | New service |
| R3 | Thread Freshness Filter | 4.2, 4.3 | Modify scoring + generation |
| R4 | Scoring Cost Preview | 3.1, 5.1, 6.1 | New endpoint + UI |
| R5 | Phase-Aware Filtering | 4.5 | Traceability only |
| R6 | Subreddit Saturation Guard | 4.1 | Modify safety.py |
| R7 | Pre-Generation Safety | 3.1, 4.1, 4.3 | New orchestration function |
| R8 | Scrape Freshness Gate | 4.4 | Modify scraping task |
| R9 | Today's Activity Summary | 4.6, 5.2, 6.2 | New endpoint + UI |
| R10 | Inline Draft Editing | 5.3, 6.3 | New endpoint + UI |
| R11 | Thread Liveness | — | Already built |
| R12 | Avatar Warming Phases | 4.5 | Constant change |
| R13 | Rate Limits/Cooldowns | 4.1, 7 | Modify safety + Valkey |
| R14 | Brand Ratio Tracking | 4.1, 7 | Modify safety + Valkey |
| R15 | Strategy Document | 2.1, 3.3, 5.4, 6.4 | New model + service + UI |
| R16 | Mentor Analysis | 2.2, 3.3, 5.4 | New model + service |
| R17 | Subreddit Analysis | 2.3, 3.3, 5.4 | New model + service |
| R18 | Hill I Die On Tracking | 2.5, 3.5, 4.3 | New service + column |
| R19 | Auto-Correction | 3.3, 5.6 | Strategy engine method |
| R20 | Cross-Avatar Coordination | 3.6, 4.3 | New service |
| R21 | Client Report | 2.4, 3.4, 5.5 | New model + service + UI |
| R22 | Enhanced Scoring | 2.5, 3.3, 4.2 | Modify scoring + strategy |
| R23 | Batch Scoring | 4.2, 7 | Modify scoring |
| R24 | Unified Client Report | 3.4, 5.5 | Extend report engine |
| R25 | Strategy as Pipeline Input | 3.3, 4.3 | Modify generation |
