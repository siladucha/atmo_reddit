# Design Document: Discovery Engine

## Overview

The Discovery Engine is the foundational pre-engagement layer that transforms client onboarding from "account creation" into "Reddit ecosystem intelligence." It produces 7 structured outputs (Environment Model, Client Model, Brand Model, Community Model, Opportunity Map, Risk Map, Initial Strategy) packaged as a Visibility Report — the $4K setup fee deliverable.

**Architectural Principle:** Discovery determines Strategy. Strategy determines EPG. EPG determines daily actions. Each layer references the one above it for explainability.

**Reuse:** Discovery leverages existing infrastructure — PRAW (reddit.py), LLM calling (ai.py), strategy engine (strategy_engine.py), subreddit registry, and scoring logic. No new external dependencies required.

## Architecture

### System Context

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DISCOVERY ENGINE                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Operator Input        AI Layer            Reddit Layer             │
│  ┌──────────┐     ┌────────────┐      ┌──────────────┐            │
│  │Client    │────▶│Entity      │─────▶│Subreddit     │            │
│  │Brief     │     │Extraction  │      │Search (PRAW) │            │
│  └──────────┘     │(Gemini)    │      └──────┬───────┘            │
│                    └────────────┘             │                     │
│                         │                    │                     │
│                         ▼                    ▼                     │
│                    ┌────────────┐      ┌──────────────┐            │
│                    │Hypothesis  │◀────▶│Reddit Signal │            │
│                    │Formation   │      │Collection    │            │
│                    │(Gemini)    │      │(PRAW batch)  │            │
│                    └─────┬──────┘      └──────────────┘            │
│                          │                                         │
│                          ▼                                         │
│                    ┌────────────┐                                   │
│                    │Confidence  │                                   │
│                    │Scoring     │                                   │
│                    │(rule-based)│                                   │
│                    └─────┬──────┘                                   │
│                          │                                         │
│              ┌───────────┼───────────┐                             │
│              ▼           ▼           ▼                             │
│        ┌──────────┐┌──────────┐┌───────────┐                      │
│        │Operator  ││Next      ││Visibility │                      │
│        │Feedback  ││Iteration ││Report Gen │                      │
│        │(confirm/ ││(if <5)   ││(Claude)   │                      │
│        │ reject)  ││          ││           │                      │
│        └──────────┘└──────────┘└─────┬─────┘                      │
│                                      │                             │
│                                      ▼                             │
│                               ┌─────────────┐                     │
│                               │  HANDOFF    │                     │
│                               │  Strategy → │                     │
│                               │  EPG        │                     │
│                               └─────────────┘                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Component Architecture

```
app/
├── models/
│   ├── discovery_session.py      # DiscoverySession model
│   ├── discovery_hypothesis.py   # Hypothesis model
│   ├── discovery_entity.py       # Entity model
│   └── visibility_report.py      # VisibilityReport model
├── services/
│   └── discovery/
│       ├── __init__.py
│       ├── session_manager.py    # Session CRUD, state transitions
│       ├── entity_extractor.py   # LLM entity extraction from brief
│       ├── hypothesis_engine.py  # Hypothesis formation + refinement
│       ├── reddit_researcher.py  # Reddit API research for signals
│       ├── confidence_scorer.py  # Rule-based confidence calculation
│       ├── report_generator.py   # Visibility Report generation (Claude)
│       └── strategy_handoff.py   # Discovery → Strategy → EPG bridge
├── routes/
│   └── discovery.py              # Admin routes + HTMX partials
├── tasks/
│   └── discovery.py              # Celery tasks for async research
└── templates/
    ├── admin_discovery.html           # Session list page
    ├── admin_discovery_session.html   # Active session page
    └── partials/
        ├── discovery_brief_form.html
        ├── discovery_entities.html
        ├── discovery_hypotheses.html
        ├── discovery_research_progress.html
        ├── discovery_results.html
        ├── discovery_report.html
        └── discovery_report_export.html
```

## Data Model

### DiscoverySession

```python
class DiscoverySession(Base):
    __tablename__ = "discovery_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    operator_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    client_brief: Mapped[str] = mapped_column(Text, nullable=False)  # max 5000 chars
    prospect_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="in_progress")  # in_progress | completed | abandoned
    current_iteration: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    abandon_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    session_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    total_ai_cost_usd: Mapped[float] = mapped_column(Numeric(10, 4), default=0)

    # Relationships
    entities = relationship("DiscoveryEntity", back_populates="session", cascade="all, delete-orphan")
    hypotheses = relationship("DiscoveryHypothesis", back_populates="session", cascade="all, delete-orphan")
    reports = relationship("VisibilityReport", back_populates="session", cascade="all, delete-orphan")
```

### DiscoveryEntity

```python
class DiscoveryEntity(Base):
    __tablename__ = "discovery_entities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("discovery_sessions.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # product | audience | problem | industry | competitor | use_case
    source: Mapped[str] = mapped_column(String(20), default="extracted")  # extracted | operator_added
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session = relationship("DiscoverySession", back_populates="entities")
```

### DiscoveryHypothesis

```python
class DiscoveryHypothesis(Base):
    __tablename__ = "discovery_hypotheses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("discovery_sessions.id", ondelete="CASCADE"), nullable=False)
    iteration_number: Mapped[int] = mapped_column(Integer, nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)  # max 1000 chars
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # clients | partners | feedback | recognition | hiring | market_research
    confidence_score: Mapped[int] = mapped_column(Integer, default=50)
    confidence_delta: Mapped[int] = mapped_column(Integer, default=0)  # change from initial 50
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed | confirmed | rejected | abandoned | research_failed
    classification: Mapped[str | None] = mapped_column(String(10), nullable=True)  # fact | choice
    provenance: Mapped[dict] = mapped_column(JSONB, default=dict)
    # provenance structure:
    # {
    #   "triggering_entities": [{"id": "...", "name": "...", "category": "..."}],
    #   "reasoning": "...",
    #   "llm_prompt_hash": "...",
    #   "search_terms": ["term1", "term2"],
    #   "confidence_reasoning": "..."
    # }
    reddit_signals: Mapped[dict] = mapped_column(JSONB, default=dict)
    # reddit_signals structure:
    # {
    #   "subreddits": [
    #     {"name": "r/...", "subscribers": 50000, "posts_30d": 120, "avg_engagement": 15, "relevance_score": 78}
    #   ],
    #   "total_posts_found": 45,
    #   "avg_engagement_overall": 12,
    #   "no_signal": null | {"cause": "search_too_narrow"|"topic_absent", "explanation": "...", "suggestions": [...]}
    # }
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session = relationship("DiscoverySession", back_populates="hypotheses")

    __table_args__ = (
        UniqueConstraint("session_id", "iteration_number", "statement", name="uq_hypothesis_session_iter_stmt"),
        Index("ix_hypothesis_session_status", "session_id", "status"),
        Index("ix_hypothesis_session_iteration", "session_id", "iteration_number"),
    )
```

### VisibilityReport

```python
class VisibilityReport(Base):
    __tablename__ = "visibility_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("discovery_sessions.id", ondelete="CASCADE"), nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # content structure:
    # {
    #   "executive_summary": "...",
    #   "demand_assessment": "...",
    #   "communities": [{"name": "r/...", "subscribers": N, "daily_posts": N, "relevance": N, "approach": "..."}],
    #   "discussion_activity": "...",
    #   "entry_points": [...],
    #   "competitive_landscape": "...",
    #   "visibility_outcomes": [{"type": "clients", "probability": "high", "reasoning": "..."}],
    #   "risks_and_limitations": "..."
    # }
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    operator_notes: Mapped[str | None] = mapped_column(Text, nullable=True)  # max 5000 chars
    report_version: Mapped[int] = mapped_column(Integer, default=1)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    generation_cost_usd: Mapped[float] = mapped_column(Numeric(10, 4), default=0)

    session = relationship("DiscoverySession", back_populates="reports")
```

### Migration

One Alembic migration creates all 4 tables plus indexes. Also adds `discovery_session_id` nullable FK to `strategy_documents` table for handoff linkage.

## Service Design

### 1. EntityExtractor (`services/discovery/entity_extractor.py`)

**Reuses:** `app/services/ai.py` → `call_llm_json()`

```python
async def extract_entities(client_brief: str, db: Session, session_id: uuid.UUID) -> list[DiscoveryEntity]:
    """
    Uses Gemini Flash to extract 3-20 named entities from the client brief.
    Categories: product, audience, problem, industry, competitor, use_case.
    Returns stored DiscoveryEntity records.
    """
```

**LLM Prompt Strategy:**
- Model: `gemini/gemini-2.5-flash-lite` (fast, cheap — $0.0003/call)
- System prompt: "You are a business analyst. Extract named entities..."
- Output: JSON array validated with Pydantic schema
- Timeout: 30 seconds
- Cost tracking: logged as `operation="discovery"`, `triggered_by=session_id`

### 2. HypothesisEngine (`services/discovery/hypothesis_engine.py`)

**Reuses:** `app/services/ai.py` → `call_llm_json()`

```python
async def form_hypotheses(
    entities: list[DiscoveryEntity],
    session: DiscoverySession,
    prior_hypotheses: list[DiscoveryHypothesis] | None = None,
    rejection_context: list[dict] | None = None,
) -> list[DiscoveryHypothesis]:
    """
    Generates 3-7 testable hypotheses per iteration.
    Each hypothesis includes at least one quantifiable Reddit metric.
    Excludes statements from prior iterations (dedup).
    """
```

**LLM Prompt Strategy:**
- Model: `gemini/gemini-2.5-flash-lite` (fast generation, JSON output)
- System prompt includes: entities, prior confirmed/rejected context, exclusion list
- Output schema: `[{statement, category, triggering_entities, reasoning}]`
- Retry: once with expanded prompt if <3 hypotheses returned

### 3. RedditResearcher (`services/discovery/reddit_researcher.py`)

**Reuses:** `app/services/reddit.py` → `get_reddit_client()`, `scrape_subreddit()`

```python
async def research_hypothesis(
    hypothesis: DiscoveryHypothesis,
    entities: list[DiscoveryEntity],
) -> dict:
    """
    Searches Reddit for evidence supporting/contradicting a hypothesis.
    Returns reddit_signals dict with subreddit data, post volumes, engagement.
    """
```

**Research Strategy:**
1. Extract search terms from hypothesis statement + entity names
2. Use `reddit.subreddits.search(query)` to find relevant subreddits (up to 10)
3. For each subreddit: fetch subscriber count + recent post sample (30-day)
4. Calculate average engagement (upvotes/comments per post)
5. Compute topic relevance score (keyword overlap between hypothesis terms and subreddit posts)
6. Apply no-signal detection logic (Requirement 5)

**Rate Limiting:** Uses existing `_wait_for_rate_limit()` from reddit.py. Research for all hypotheses in one iteration dispatched as Celery task with max 120s total timeout.

**Reuse of existing scraping:** The researcher does NOT use `scrape_subreddit()` (which saves to DB and is designed for thread monitoring). Instead, it uses lightweight PRAW queries (`reddit.subreddit(name).search()`, `.hot()`) for signal collection without persisting raw thread data. Subreddit metadata (subscribers, description) is cached in `session_metadata`.

### 4. ConfidenceScorer (`services/discovery/confidence_scorer.py`)

**Pure Python — no LLM, no external calls.**

```python
def score_hypothesis(hypothesis: DiscoveryHypothesis, signals: dict) -> tuple[int, str]:
    """
    Rule-based confidence scoring:
    - 20+ posts in 30d with avg engagement 10+ → +10 to +30
    - <5 posts in 30d OR avg engagement <3 → -10 to -30
    - No signal → set to 15
    Returns (new_score, reasoning_text)
    """
```

**Scoring Rules (from Requirement 4):**
- Base: 50 (neutral)
- Strong signal (≥20 posts, ≥10 avg engagement): +10 per strong subreddit, capped at +30
- Weak signal (<5 posts OR <3 avg engagement): -10 per weak area, capped at -30
- No signal: force to 15, attach No_Signal_Assessment
- Delta calculation: `new_score - initial_score`

### 5. ReportGenerator (`services/discovery/report_generator.py`)

**Reuses:** `app/services/ai.py` → `call_llm()`

```python
async def generate_visibility_report(session: DiscoverySession) -> VisibilityReport:
    """
    Uses Claude Sonnet to generate the full Visibility Report from confirmed hypotheses.
    Produces structured JSONB content with all required sections.
    """
```

**LLM Prompt Strategy:**
- Model: `claude-sonnet-4-20250514` (high-quality prose for sales artifact)
- Input context: all confirmed hypotheses + their reddit_signals + entities + client_brief
- Output: structured sections matching `content` JSONB schema
- Timeout: 60 seconds
- Estimated cost: ~$0.05–0.08 per report (12K input + 2K output tokens)

### 6. StrategyHandoff (`services/discovery/strategy_handoff.py`)

**Reuses:** `app/services/strategy_engine.py` → `StrategyEngine.generate_strategy()`

```python
def prepare_handoff_context(session: DiscoverySession) -> dict:
    """
    Extracts data from completed Discovery session for strategy generation:
    - Confirmed hypotheses (statement + confidence)
    - Recommended communities (subreddit + relevance + approach)
    - Entry points
    - Competitive landscape
    Returns dict ready for injection into strategy generation prompt.
    """

def execute_handoff(session: DiscoverySession, db: Session) -> Client:
    """
    If prospect-only session: creates Client record from Discovery data.
    If existing client: uses existing record.
    Pre-populates subreddit suggestions for onboarding wizard.
    Links session to strategy via discovery_session_id FK.
    Logs activity event 'discovery_handoff'.
    """
```

**Strategy Integration:**
The existing `StrategyEngine.generate_strategy()` accepts context parameters for prompt building. The handoff service adds a `discovery_context` section to the strategy generation prompt containing:
- Validated hypotheses (what Reddit opportunities exist)
- Community priorities (which subreddits matter most)
- Competitive landscape (who else is active)
- Risk factors (where signal is weak)

This makes every strategy decision traceable back to Discovery data.

## Route Design

### URL Structure

```
GET  /admin/discovery                          → Session list page
GET  /admin/discovery/new                      → New session form
POST /admin/discovery/new                      → Create session + extract entities
GET  /admin/discovery/{session_id}             → Active session page
POST /admin/discovery/{session_id}/entities    → Confirm/edit entities → trigger hypothesis formation
POST /admin/discovery/{session_id}/research    → Trigger Reddit research (Celery task)
GET  /admin/discovery/{session_id}/progress    → HTMX poll: research progress
POST /admin/discovery/{session_id}/decide      → Confirm/reject hypotheses → next iteration or report
POST /admin/discovery/{session_id}/report      → Generate Visibility Report
POST /admin/discovery/{session_id}/report/edit → Save operator notes on report
GET  /admin/discovery/{session_id}/report/export → Render branded HTML for print/PDF
POST /admin/discovery/{session_id}/handoff     → Execute handoff to Strategy
POST /admin/discovery/{session_id}/abandon     → Mark session abandoned
```

### HTMX Flow (single page, partial swaps)

```
┌─────────────────────────────────────────────────────────────┐
│  /admin/discovery/{id}                                       │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Progress: ● Brief → ● Entities → ○ Research → ○ Report│   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  #discovery-content  ← HTMX partial swap target       │   │
│  │                                                        │   │
│  │  Step 1: Brief form (initial)                          │   │
│  │  Step 2: Entity review (after extraction)              │   │
│  │  Step 3: Hypothesis cards + research progress          │   │
│  │  Step 4: Results with confirm/reject + Fact/Choice     │   │
│  │  Step 5: Report view + export + handoff buttons        │   │
│  │                                                        │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────┐  ┌───────────────────────────┐   │
│  │ Session Info          │  │ AI Cost: $0.12            │   │
│  │ Iteration 2 of 5     │  │ Hypotheses: 4 confirmed   │   │
│  │ Status: in_progress   │  │ Time elapsed: 3m 45s      │   │
│  └──────────────────────┘  └───────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

All step transitions happen via `hx-post` / `hx-get` swapping `#discovery-content` — no full page reloads. Progress bar updates via `hx-swap-oob`.

## UI Design

### Design System

Follows existing admin panel: dark theme (`admin_base.html`), Tailwind CSS, HTMX partials.

**Key Visual Elements:**

| Element | Style |
|---------|-------|
| Hypothesis card (proposed) | `bg-gray-800 border-gray-700` |
| Hypothesis card (confirmed) | `bg-green-900/20 border-green-700` |
| Hypothesis card (rejected) | `bg-red-900/20 border-red-700 opacity-60` |
| Fact badge | `bg-blue-800 text-blue-200` label: "FACT" |
| Choice badge | `bg-amber-800 text-amber-200` label: "CHOICE" |
| Confidence bar | Green (70+) / Amber (40-69) / Red (<40) |
| No-signal indicator | `bg-gray-700 text-gray-400` with ⚠ icon |
| Research progress | Animated dots per hypothesis (queued/researching/done) |

### Visibility Report Export Page

Separate template (`discovery_report_export.html`) that:
- Extends a clean white-background template (NOT admin_base.html)
- Uses RAMP branding (logo, colors)
- Print-friendly CSS (`@media print`)
- Table of contents with anchor links
- Professional typography suitable for PDF generation via browser print

## Celery Task Design

### `tasks/discovery.py`

```python
@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def research_hypotheses_task(self, session_id: str, hypothesis_ids: list[str]):
    """
    Background task: runs Reddit research for all hypotheses in current iteration.
    Updates hypothesis records with reddit_signals and confidence_score.
    Max duration: 120 seconds (15s per hypothesis × 7 max + overhead).
    
    Progress tracking: updates session_metadata.research_progress dict
    which the HTMX progress endpoint polls.
    """
```

**Progress Reporting:**
The task updates `session_metadata["research_progress"]` as it processes each hypothesis:
```json
{
  "research_progress": {
    "hypothesis_id_1": "complete",
    "hypothesis_id_2": "researching",
    "hypothesis_id_3": "queued"
  }
}
```
The HTMX progress partial polls `GET /admin/discovery/{id}/progress` every 2 seconds and renders status per hypothesis.

## Cost Model

| Operation | Model | Est. Cost | Frequency |
|-----------|-------|-----------|-----------|
| Entity extraction | Gemini Flash | $0.0003 | 1 per session |
| Hypothesis formation | Gemini Flash | $0.0005 | 1-5 per session |
| Reddit research | PRAW (free) | $0 | 1-5 per session |
| Confidence scoring | Pure Python | $0 | per hypothesis |
| Report generation | Claude Sonnet | $0.06 | 1 per session |
| **Total per session** | | **~$0.07** | |

At $4K setup fee per client, Discovery AI cost is **0.002%** of revenue. Essentially free.

## Integration Points

### With Existing Strategy Engine

`strategy_engine.py` → `generate_strategy()` currently builds context from:
- Avatar karma data
- Subreddit affinity
- Comment history
- Forecast calculations

**After Discovery integration:**
- Add `discovery_context` parameter to `generate_strategy()`
- When `discovery_session_id` is present on the strategy: inject confirmed hypotheses, community priorities, competitive landscape into the strategy prompt
- Strategy markdown output gains a "Based on Discovery" section explaining why these subreddits/approaches were chosen

### With Existing Onboarding Wizard

The 7-step wizard (`onboard_step_get/post` in admin.py) currently:
- Step 2: Manual subreddit entry
- Step 3: Manual keyword entry

**After Discovery integration:**
- Add "Import from Discovery" button on Step 2 (pre-fills subreddit list from report)
- Add "Import from Discovery" button on Step 3 (pre-fills keywords from entities)
- Client detail page shows "Discovery History" section

### With EPG

EPG already references Strategy for daily program generation. The chain is:
```
Discovery → Strategy.discovery_context → EPG reads strategy → Daily actions
```
No direct Discovery→EPG code needed. The integration flows through Strategy.

## Security & Permissions

- Discovery routes protected by `require_platform_admin` (owner/partner roles only)
- Client-facing Discovery is out of scope for MVP (deferred 6-12 months)
- Reddit API credentials: uses existing shared PRAW client (read-only operations)
- LLM prompts: never include client secrets or avatar credentials
- RBAC: sessions scoped to operator (view all for owner/partner)

## Error Handling

| Failure | Behavior |
|---------|----------|
| LLM timeout (entity extraction) | Show error, preserve brief text, allow retry |
| LLM timeout (hypothesis generation) | Show error, allow retry without losing entities |
| Reddit API rate limit | Back off, retry within 120s window. Mark hypothesis as "research_failed" if all retries exhausted |
| Reddit API unavailable | Mark affected hypotheses "research_failed", allow selective retry |
| Report generation timeout (>60s) | Show error, allow retry |
| Session DB error | Show generic error, preserve form data in browser |

## Testing Strategy

### Unit Tests
- `test_entity_extractor.py` — mock LLM, verify entity parsing + categorization
- `test_confidence_scorer.py` — rule-based scoring with known inputs/outputs
- `test_hypothesis_engine.py` — mock LLM, verify dedup logic + retry behavior
- `test_strategy_handoff.py` — verify Client creation, FK linkage, activity event

### Integration Tests
- `test_discovery_flow.py` — full session: brief → entities → hypotheses → research (mocked PRAW) → report → handoff
- `test_discovery_routes.py` — HTTP endpoints with auth, validation, HTMX responses

## Migration Plan

### Database Migration (single Alembic revision)

1. Create `discovery_sessions` table
2. Create `discovery_entities` table
3. Create `discovery_hypotheses` table
4. Create `visibility_reports` table
5. Add `discovery_session_id` (nullable UUID FK) to `strategy_documents`
6. Add indexes per Requirement 13

### Code Deployment (incremental)

1. **Phase 1** (models + services): Data model + entity extraction + hypothesis engine + confidence scorer
2. **Phase 2** (Reddit research + UI): Reddit researcher + HTMX flow + progress tracking
3. **Phase 3** (Report + Handoff): Report generation + export + strategy handoff + EPG chain verification

Each phase is independently deployable and testable.
