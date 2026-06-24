# Technical Design: Discovery → Client Strategy Handoff

## Overview

Replace the shallow Discovery handoff (create client + import subreddits) with a full Client Strategy generation step. A single Gemini Flash LLM call transforms the Visibility Report into an operational `strategy_context` JSONB field on the Client model. Downstream pipeline components (generation, EPG, phase evaluation, GEO) read this field directly — no new service layer, no additional API calls.

## Architecture

```
+---------------------+
|  Discovery Session  |
|  status=completed   |
+---------+-----------+
          | operator clicks "Create Strategy"
          v
+-----------------------------------------------------+
|  strategy_handoff.py :: execute_handoff()            |
|                                                     |
|  1. Resolve/create Client                           |
|  2. Load VisibilityReport.content + client_brief    |
|  3. Call strategy_generator.generate_client_strategy |
|  4. Save strategy_context -> Client                 |
|  5. Import subreddits (priority + approach)         |
|  6. Create GeoPrompts from aeo_targets              |
|  7. Set session.status = "handed_off"               |
+--------+--------------------------------------------+
         |
         v
+----------------------------------+
|  Client.strategy_context (JSONB) |
+------+----------+--------+-------+
       |          |        |
       v          v        v
+----------+ +--------+ +-----------+
|generation| |  EPG   | | phase.py  |
|  .py     | |scoring | | roadmap   |
|pillars + | |priority| | eval      |
|forbidden | |weights | |           |
+----------+ +--------+ +-----------+
```

**Key design constraint:** No separate model, no new table. One client = one active strategy stored inline. History kept as a capped JSONB array for rollback.

---
## Data Model Changes

### Client Model (modified)

New fields added to `app/models/client.py`:

```python
# Client Strategy — operational context from Discovery
strategy_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
strategy_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
strategy_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
strategy_source_session_id: Mapped[uuid.UUID | None] = mapped_column(
    UUID(as_uuid=True), nullable=True
)
strategy_history: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # max 3 previous
```

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `strategy_context` | JSONB | NULL | Active Client Strategy (full validated output) |
| `strategy_version` | Integer | 0 | Monotonic version counter |
| `strategy_generated_at` | DateTime(tz) | NULL | When current strategy was generated |
| `strategy_source_session_id` | UUID | NULL | Which Discovery session produced this strategy |
| `strategy_history` | JSONB | NULL | Array of up to 3 previous strategies (for rollback/comparison) |

### ClientSubredditAssignment (modified)

New fields added to `app/models/subreddit.py` on `ClientSubredditAssignment`:

```python
# Discovery-sourced priority and engagement approach
priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
engagement_approach: Mapped[str | None] = mapped_column(Text, nullable=True)
```

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `priority` | Integer | NULL | 1-based rank from Visibility Report relevance ordering |
| `engagement_approach` | Text | NULL | Recommended engagement strategy from report (e.g., "helpful_peer", "thought_leader") |

### DiscoverySession (status extension)

Add `"handed_off"` to the allowed status values. No column change — the `status` field is a String(20), so we add validation in the application layer:

```python
DISCOVERY_SESSION_STATUSES = ["in_progress", "completed", "abandoned", "handed_off"]
```

### Alembic Migration

**Migration name:** `add_client_strategy_fields`

Steps:
1. Add `strategy_context` JSONB column (nullable) to `clients`
2. Add `strategy_version` Integer column (default 0) to `clients`
3. Add `strategy_generated_at` DateTime column (nullable) to `clients`
4. Add `strategy_source_session_id` UUID column (nullable) to `clients`
5. Add `strategy_history` JSONB column (nullable) to `clients`
6. Add `priority` Integer column (nullable) to `client_subreddit_assignments`
7. Add `engagement_approach` Text column (nullable) to `client_subreddit_assignments`
8. Add index: `ix_clients_strategy_version` on `(id, strategy_version)`

**Backward compatibility:** All new fields are nullable with sensible defaults. Existing clients function without strategy_context (pipeline checks `if client.strategy_context:` before reading).

---
## Pydantic Schemas

### ClientStrategyOutput

Located in `app/schemas/client_strategy.py` (new file):

```python
from pydantic import BaseModel, Field
from typing import Literal


class StrategyMetadata(BaseModel):
    """Generation metadata — auto-populated by strategy_generator, not by LLM."""
    generated_at: str  # ISO timestamp, set by service
    source_session_id: str  # UUID string
    model_used: str
    generation_cost_usd: float
    prompt_version: str = "1.0"


class Positioning(BaseModel):
    audience: str = Field(..., min_length=10, max_length=500)
    problem: str = Field(..., min_length=10, max_length=500)
    value_mechanism: str = Field(..., min_length=10, max_length=500)
    differentiation: str = Field(..., min_length=10, max_length=500)
    confidence: float = Field(..., ge=0.0, le=0.9)
    evidence_refs: list[str] = Field(default_factory=list)


class SubredditPriority(BaseModel):
    subreddit: str = Field(..., pattern=r"^r/[a-zA-Z0-9_]+$")
    priority: int = Field(..., ge=1, le=10)
    engagement_approach: str = Field(..., min_length=5, max_length=200)
    reason: str = Field(..., min_length=10, max_length=300)


class ContentPillar(BaseModel):
    name: str = Field(..., min_length=3, max_length=100)
    goal: str = Field(..., min_length=10, max_length=300)
    confidence: float = Field(..., ge=0.0, le=0.9)


class ForbiddenZone(BaseModel):
    type: Literal["claim", "topic", "tone", "community_risk", "competitive_trap"]
    description: str = Field(..., min_length=10, max_length=300)
    severity: Literal["hard_block", "soft_avoid"]


class AeoTarget(BaseModel):
    intent: str = Field(..., min_length=10, max_length=200)
    user_question: str = Field(..., min_length=10, max_length=300)
    expected_visibility_outcome: str = Field(..., min_length=10, max_length=300)


class PhaseEntry(BaseModel):
    id: str = Field(..., min_length=1, max_length=50)
    goal: str = Field(..., min_length=10, max_length=300)
    entry_conditions: list[str] = Field(..., min_length=1)
    activities: list[str] = Field(..., min_length=1)
    exit_conditions: list[str] = Field(..., min_length=1)


class PhaseRoadmap(BaseModel):
    phases: list[PhaseEntry] = Field(..., min_length=2, max_length=5)


class ClientStrategyOutput(BaseModel):
    """Full Client Strategy output — validated against this schema after LLM generation."""
    positioning: Positioning
    subreddit_priorities: list[SubredditPriority] = Field(..., min_length=1, max_length=10)
    content_pillars: list[ContentPillar] = Field(..., min_length=3, max_length=5)
    forbidden_zones: list[ForbiddenZone] = Field(..., min_length=1)
    aeo_targets: list[AeoTarget] = Field(..., max_length=10)
    phase_roadmap: PhaseRoadmap
```

**Notes:**
- `metadata` is NOT part of the LLM output — it is attached by the service after validation.
- Confidence fields capped at 0.9 per agent instructions ("Never output confidence >0.9").
- Subreddit pattern enforces `r/` prefix for consistency with report format.

---
## Services

### strategy_generator.py (new)

Located at `app/services/discovery/strategy_generator.py`:

```python
"""Client Strategy Generator — single LLM call to produce operational strategy from Discovery."""

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.discovery_session import DiscoverySession
from app.models.visibility_report import VisibilityReport
from app.schemas.client_strategy import ClientStrategyOutput
from app.services.ai import call_llm, log_ai_usage

logger = get_logger(__name__)

STRATEGY_MODEL = "gemini/gemini-2.5-flash"
STRATEGY_MAX_TOKENS = 2048
STRATEGY_TIMEOUT = 30  # seconds (hard limit inclusive of retry)
AGENT_PROMPT_PATH = Path("docs/agents/client_strategy_agent.md")


def _load_system_prompt() -> str:
    """Load agent instructions from markdown file at runtime."""
    return AGENT_PROMPT_PATH.read_text(encoding="utf-8")


def _build_user_prompt(
    report_content: dict,
    client_brief: str,
    confirmed_hypotheses: list[dict],
) -> str:
    """Construct the user message with all Discovery context."""
    return json.dumps({
        "visibility_report": report_content,
        "client_brief": client_brief[:2000],
        "confirmed_hypotheses": confirmed_hypotheses,
    }, indent=2)


def generate_client_strategy(
    session: DiscoverySession,
    db: Session,
) -> tuple[ClientStrategyOutput, dict]:
    """Generate and validate a Client Strategy from Discovery session data.

    Args:
        session: Completed Discovery session with report and hypotheses.
        db: Database session (for AI usage logging).

    Returns:
        Tuple of (validated ClientStrategyOutput, LLM usage metadata dict).

    Raises:
        ValueError: If both attempts fail validation.
        TimeoutError: If generation exceeds 30s total.
    """
    # Load inputs
    report = _get_latest_report(session)
    report_content = report.content or {}
    client_brief = session.client_brief
    confirmed = [
        {"statement": h.statement, "confidence_score": h.confidence_score}
        for h in session.hypotheses if h.status == "confirmed"
    ]

    system_prompt = _load_system_prompt()
    user_prompt = _build_user_prompt(report_content, client_brief, confirmed)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    start = time.time()

    # Attempt 1
    result, usage = _call_and_validate(messages, db, session)
    if result:
        return result, usage

    # Attempt 2 (retry on validation failure)
    elapsed = time.time() - start
    remaining = STRATEGY_TIMEOUT - elapsed
    if remaining < 5:
        raise ValueError("Insufficient time for retry (timeout budget exhausted)")

    logger.warning(f"Strategy generation retry for session {session.id}")
    result, usage = _call_and_validate(messages, db, session)
    if result:
        return result, usage

    raise ValueError(
        f"Strategy generation failed validation after 2 attempts for session {session.id}"
    )


def _call_and_validate(
    messages: list[dict],
    db: Session,
    session: DiscoverySession,
) -> tuple[ClientStrategyOutput | None, dict]:
    """Make LLM call and validate output. Returns (None, {}) on validation failure."""
    try:
        response = call_llm(
            messages=messages,
            model=STRATEGY_MODEL,
            temperature=0.4,
            max_tokens=STRATEGY_MAX_TOKENS,
            response_format={"type": "json_object"},
            timeout=STRATEGY_TIMEOUT,
        )

        content = response.get("content", "")
        usage_meta = response.get("usage", {})

        # Log AI usage
        log_ai_usage(
            db=db,
            model=STRATEGY_MODEL,
            input_tokens=usage_meta.get("prompt_tokens", 0),
            output_tokens=usage_meta.get("completion_tokens", 0),
            cost_usd=usage_meta.get("cost", 0.0),
            task_type="strategy_generation",
            related_id=str(session.id),
        )

        # Parse and validate
        parsed = json.loads(content)
        strategy = ClientStrategyOutput.model_validate(parsed)
        return strategy, usage_meta

    except (json.JSONDecodeError, ValidationError) as e:
        logger.warning(f"Strategy validation failed: {e}")
        return None, {}
    except Exception as e:
        logger.error(f"Strategy LLM call failed: {e}")
        return None, {}


def _get_latest_report(session: DiscoverySession) -> VisibilityReport:
    """Get the latest Visibility Report for a session."""
    if not session.reports:
        raise ValueError(f"No reports found for session {session.id}")
    return sorted(session.reports, key=lambda r: r.report_version, reverse=True)[0]
```

**Flow:**
1. Load latest VisibilityReport.content from session
2. Load confirmed hypotheses
3. Load system prompt from `docs/agents/client_strategy_agent.md`
4. Build user prompt as JSON blob (report + brief + hypotheses)
5. Call Gemini Flash with `response_format={"type": "json_object"}`
6. Parse JSON, validate against `ClientStrategyOutput`
7. On validation failure: retry once (same input)
8. Return validated output + usage metadata

**Error handling:**
- JSON parse failure → retry
- Pydantic validation failure → retry
- LLM timeout/network error → retry
- Both attempts fail → raise ValueError (caller handles)
- Total time > 30s → raise TimeoutError

---
### strategy_handoff.py (modified)

Updated `app/services/discovery/strategy_handoff.py` — the `execute_handoff` function is extended to include strategy generation, GEO prompt creation, and session status update:

```python
def execute_handoff(session: DiscoverySession, db: Session) -> Client:
    """Execute the full Discovery -> Client Strategy handoff.

    Steps (atomic — rolls back on any failure after client resolution):
    1. Resolve or create Client record
    2. Generate Client Strategy via LLM
    3. Save strategy_context to Client (with versioning + history)
    4. Import subreddit assignments with priority + engagement_approach
    5. Create GEO prompts from aeo_targets (if geo_monitoring_enabled)
    6. Mark session status as "handed_off"
    7. Log activity event

    Returns:
        Client record (for redirect).

    Raises:
        ValueError: If strategy generation fails after retries.
    """
    # Step 1: Resolve/create client (existing logic)
    client = _resolve_or_create_client(session, db)

    # Step 2: Generate strategy
    from app.services.discovery.strategy_generator import generate_client_strategy
    strategy_output, usage_meta = generate_client_strategy(session, db)

    # Step 3: Save to client with versioning
    _save_strategy_to_client(client, strategy_output, usage_meta, session, db)

    # Step 4: Import subreddits with priority + approach from strategy output
    _import_subreddits_with_priority(session, client, strategy_output, db)

    # Step 5: Create GEO prompts (conditional)
    if client.geo_monitoring_enabled:
        _create_geo_prompts(client, strategy_output, db)

    # Step 6: Mark session as handed off
    session.status = "handed_off"

    # Step 7: Activity event
    _log_handoff_event(session, client, strategy_output, db)

    return client


def _save_strategy_to_client(
    client: Client,
    strategy: ClientStrategyOutput,
    usage_meta: dict,
    session: DiscoverySession,
    db: Session,
) -> None:
    """Persist strategy with versioning and history rotation."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    strategy_dict = strategy.model_dump()

    # Attach metadata (not from LLM)
    strategy_dict["metadata"] = {
        "generated_at": now.isoformat(),
        "source_session_id": str(session.id),
        "model_used": "gemini/gemini-2.5-flash",
        "generation_cost_usd": usage_meta.get("cost", 0.0),
        "prompt_version": "1.0",
    }

    # Rotate history (keep max 3 previous)
    if client.strategy_context:
        history = client.strategy_history or []
        history.insert(0, client.strategy_context)
        client.strategy_history = history[:3]

    # Set new strategy
    client.strategy_context = strategy_dict
    client.strategy_version = (client.strategy_version or 0) + 1
    client.strategy_generated_at = now
    client.strategy_source_session_id = session.id


def _import_subreddits_with_priority(
    session: DiscoverySession,
    client: Client,
    strategy: ClientStrategyOutput,
    db: Session,
) -> int:
    """Import subreddits from strategy output with priority rank + engagement approach.

    Uses strategy.subreddit_priorities (LLM-ranked) rather than raw report communities.
    Updates existing assignments if subreddit already assigned.
    """
    from app.models.subreddit import ClientSubredditAssignment, Subreddit

    imported = 0
    for sp in strategy.subreddit_priorities[:10]:
        sub_name = sp.subreddit.replace("r/", "").strip()
        if not sub_name:
            continue

        # Find or create subreddit
        subreddit = (
            db.query(Subreddit)
            .filter(Subreddit.subreddit_name.ilike(sub_name))
            .first()
        )
        if not subreddit:
            subreddit = Subreddit(subreddit_name=sub_name, is_active=True)
            db.add(subreddit)
            db.flush()

        # Check for existing assignment
        existing = (
            db.query(ClientSubredditAssignment)
            .filter(
                ClientSubredditAssignment.client_id == client.id,
                ClientSubredditAssignment.subreddit_id == subreddit.id,
            )
            .first()
        )

        if existing:
            # Update priority + approach without duplicate
            existing.priority = sp.priority
            existing.engagement_approach = sp.engagement_approach
            existing.is_active = True
        else:
            assignment = ClientSubredditAssignment(
                client_id=client.id,
                subreddit_id=subreddit.id,
                type="professional",
                is_active=True,
                priority=sp.priority,
                engagement_approach=sp.engagement_approach,
            )
            db.add(assignment)

        imported += 1

    return imported


def _create_geo_prompts(
    client: Client,
    strategy: ClientStrategyOutput,
    db: Session,
) -> int:
    """Create GeoPrompt records from strategy aeo_targets.

    Skips prompts with identical prompt_text already existing for this client.
    Sets category="discovery_generated" for auto-created prompts.
    """
    from app.models.geo_prompt import GeoPrompt

    created = 0
    for target in strategy.aeo_targets:
        prompt_text = target.user_question

        # Check for duplicate
        exists = (
            db.query(GeoPrompt)
            .filter(
                GeoPrompt.client_id == client.id,
                GeoPrompt.prompt_text == prompt_text,
            )
            .first()
        )
        if exists:
            continue

        geo_prompt = GeoPrompt(
            client_id=client.id,
            prompt_text=prompt_text,
            category="discovery_generated",
            is_active=True,
        )
        db.add(geo_prompt)
        created += 1

    return created
```

---
## Route Changes

### Endpoint: `POST /admin/discovery/{session_id}/handoff`

Same endpoint, updated handler in `app/routes/discovery.py`:

```python
@router.post("/{session_id}/handoff", response_class=HTMLResponse)
def handoff_to_strategy(
    request: Request,
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """Execute Discovery -> Client Strategy handoff (with LLM generation)."""
    session = SessionManager.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status == "handed_off":
        raise HTTPException(status_code=400, detail="Session already handed off")

    if session.status != "completed":
        raise HTTPException(status_code=400, detail="Session must be completed before handoff")

    if not session.reports:
        raise HTTPException(status_code=400, detail="No visibility report generated yet")

    try:
        client = execute_handoff(session, db)
        db.commit()
    except ValueError as e:
        db.rollback()
        logger.error(f"Strategy generation failed: {e}")
        raise HTTPException(status_code=422, detail=f"Strategy generation failed: {e}")
    except Exception as e:
        db.rollback()
        logger.error(f"Handoff failed: {e}")
        raise HTTPException(status_code=500, detail=f"Handoff failed: {e}")

    # Redirect to client detail page
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"/admin/clients/{client.id}", status_code=303)
```

**Changes from current:**
1. Added guard: `session.status == "handed_off"` prevents duplicate handoffs
2. Added guard: `session.status != "completed"` ensures report exists
3. Added guard: `not session.reports` defensive check
4. Changed error for strategy failure to 422 (validation issue, not server error)
5. `execute_handoff` now returns `Client` object directly (not a dict)

---

## Template Changes

### Discovery Session Detail (`admin_discovery_detail.html`)

**Button state management:**

```html
{% if session.status == "handed_off" %}
    <button disabled class="btn btn-secondary opacity-50 cursor-not-allowed">
        <svg>...</svg> Strategy Created
    </button>
    <span class="text-xs text-green-400">Handed off {{ session.updated_at | timeago }}</span>
{% elif session.status == "completed" and session.reports %}
    <form hx-post="/admin/discovery/{{ session.id }}/handoff"
          hx-indicator="#handoff-spinner"
          hx-disabled-elt="this"
          class="inline">
        <button type="submit" class="btn btn-primary">
            <span id="handoff-spinner" class="htmx-indicator">
                <svg class="animate-spin h-4 w-4">...</svg>
            </span>
            Create Strategy
        </button>
    </form>
{% else %}
    <button disabled class="btn btn-secondary opacity-50 cursor-not-allowed">
        Create Strategy
    </button>
    <span class="text-xs text-gray-400">Complete session first</span>
{% endif %}
```

**Loading indicator:**
- HTMX `hx-indicator` shows spinner during LLM call (~10-15s)
- `hx-disabled-elt="this"` prevents double-click
- On success: 303 redirect to client detail page (HTMX follows redirects)
- On error: HTMX `hx-swap="innerHTML"` shows error message inline

### Discovery Session List (`admin_discovery.html`)

Add visual badge for handed_off status:

```html
{% if session.status == "handed_off" %}
    <span class="px-2 py-0.5 text-xs rounded-full bg-green-500/20 text-green-300">
        Handed Off
    </span>
{% endif %}
```

---
## Pipeline Integration

### generation.py — Comment Generation

**File:** `app/services/generation.py`

**What changes:** The comment generation prompt now includes Client Strategy context when available.

```python
# In generate_comment() — after building base prompt context:

strategy = client.strategy_context
if strategy:
    # Inject positioning into prompt context
    prompt_context["client_positioning"] = strategy.get("positioning", {})

    # Inject content pillars as positive constraints
    prompt_context["content_pillars"] = [
        p["name"] for p in strategy.get("content_pillars", [])
    ]

    # Inject forbidden zones as negative constraints
    prompt_context["forbidden_zones"] = [
        f["description"] for f in strategy.get("forbidden_zones", [])
        if f.get("severity") == "hard_block"
    ]
```

**Access pattern:** `client.strategy_context["positioning"]`, `client.strategy_context["content_pillars"]`, `client.strategy_context["forbidden_zones"]`

### smart_scoring.py / EPG — Subreddit Priority Weighting

**File:** `app/services/smart_scoring.py`, `app/services/epg/portfolio_manager.py`

**What changes:** EPG slot allocation uses subreddit priorities from strategy to weight distribution.

```python
# In portfolio_manager.py :: build_portfolio()

# Read subreddit priorities from strategy
strategy = client.strategy_context
if strategy:
    sub_priorities = {
        sp["subreddit"].replace("r/", ""): sp["priority"]
        for sp in strategy.get("subreddit_priorities", [])
    }
    # Higher priority (lower number) = more allocation weight
    # Priority 1 gets 3x weight, priority 10 gets 1x weight
    for subreddit_name, allocation in portfolio.allocations.items():
        priority_rank = sub_priorities.get(subreddit_name, 5)
        allocation.weight_multiplier = max(1.0, 4.0 - (priority_rank * 0.3))
```

**Also:** `ClientSubredditAssignment.priority` is read directly by EPG for simpler cases:

```python
# In epg slot allocation:
assignments = (
    db.query(ClientSubredditAssignment)
    .filter(ClientSubredditAssignment.client_id == client.id, ClientSubredditAssignment.is_active == True)
    .order_by(ClientSubredditAssignment.priority.asc().nulls_last())
    .all()
)
```

### phase.py — Phase Roadmap Evaluation

**File:** `app/services/phase.py`

**What changes:** Phase evaluation references Client Strategy roadmap for phase-appropriate activities.

```python
# In evaluate_avatar_phase():

strategy = client.strategy_context
if strategy and strategy.get("phase_roadmap"):
    phases = strategy["phase_roadmap"].get("phases", [])
    # Use entry_conditions from strategy to inform phase promotion logic
    # e.g., phase_2 entry_condition: "avatar has >50 karma in 2+ subreddits"
    for phase in phases:
        if _check_conditions_met(avatar, phase.get("entry_conditions", [])):
            recommended_phase = phase["id"]
```

### strategy_engine.py — Avatar Strategy Linkage

**File:** `app/services/strategy_engine.py`

**What changes:** When generating per-avatar StrategyDocument, inject parent Client Strategy context.

```python
# In generate_avatar_strategy():

client = avatar.client  # or resolved via client_ids
if client and client.strategy_context:
    # Inject client-level context into avatar strategy prompt
    strategy_prompt_context["client_positioning"] = client.strategy_context.get("positioning", {})
    strategy_prompt_context["client_pillars"] = client.strategy_context.get("content_pillars", [])
    strategy_prompt_context["client_forbidden_zones"] = client.strategy_context.get("forbidden_zones", [])
```

---
## Performance Budget

### Token Estimates

| Component | Tokens | Notes |
|-----------|--------|-------|
| System prompt (agent instructions) | ~1,200 | `client_strategy_agent.md` is ~3KB |
| User prompt (report + brief + hypotheses) | ~2,500 | Report ~5KB JSON + brief 2KB + 5-8 hypotheses |
| **Total input** | **~3,700** | Well within Flash context window |
| Output (strategy JSON) | ~1,200 | 6 sections, structured JSON |
| **Total tokens** | **~4,900** | |

### Cost Estimate

| Metric | Value |
|--------|-------|
| Gemini Flash input price | $0.075 / 1M tokens |
| Gemini Flash output price | $0.30 / 1M tokens |
| Input cost (3,700 tokens) | $0.000278 |
| Output cost (1,200 tokens) | $0.000360 |
| **Total per generation** | **~$0.0006** |
| With retry (worst case 2x) | ~$0.0012 |
| Target from requirements | <$0.002 |

**Verdict:** Well within the $0.002 budget even with retry.

### Timing Breakdown

| Step | Expected Duration |
|------|------------------|
| Load report + hypotheses from DB | <50ms |
| Load system prompt from disk | <5ms |
| Build user prompt (JSON serialize) | <10ms |
| LLM call (Gemini Flash) | 8-12s |
| JSON parse + Pydantic validation | <50ms |
| Save to client + flush | <100ms |
| Import subreddits (up to 10 queries) | <200ms |
| Create GEO prompts (up to 10 queries) | <200ms |
| Update session status | <50ms |
| **Total (happy path)** | **~10-13s** |
| **Total (with retry)** | **~20-25s** |
| **Hard timeout** | **30s** |

**UX implication:** The HTMX loading indicator is necessary — 10-15s is long for a button click. The indicator prevents double-submission and communicates progress.

---

## Migration Plan

### Alembic Migration Steps

**Migration file:** `alembic/versions/xxxx_add_client_strategy_fields.py`

```python
"""Add client strategy fields and subreddit priority.

Revision ID: cstrat01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


def upgrade():
    # Client strategy fields
    op.add_column("clients", sa.Column("strategy_context", JSONB, nullable=True))
    op.add_column("clients", sa.Column("strategy_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("clients", sa.Column("strategy_generated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("clients", sa.Column("strategy_source_session_id", UUID(as_uuid=True), nullable=True))
    op.add_column("clients", sa.Column("strategy_history", JSONB, nullable=True))

    # Subreddit assignment priority fields
    op.add_column("client_subreddit_assignments", sa.Column("priority", sa.Integer(), nullable=True))
    op.add_column("client_subreddit_assignments", sa.Column("engagement_approach", sa.Text(), nullable=True))

    # Index for strategy queries
    op.create_index("ix_clients_strategy_version", "clients", ["id", "strategy_version"])


def downgrade():
    op.drop_index("ix_clients_strategy_version", table_name="clients")
    op.drop_column("client_subreddit_assignments", "engagement_approach")
    op.drop_column("client_subreddit_assignments", "priority")
    op.drop_column("clients", "strategy_history")
    op.drop_column("clients", "strategy_source_session_id")
    op.drop_column("clients", "strategy_generated_at")
    op.drop_column("clients", "strategy_version")
    op.drop_column("clients", "strategy_context")
```

### Backward Compatibility

1. **`strategy_context` starts as NULL** — all existing clients unaffected
2. **Pipeline checks `if client.strategy_context:`** before reading any strategy fields — graceful degradation
3. **`priority` on assignments is nullable** — existing assignments keep NULL priority (sorted last with `.nulls_last()`)
4. **No FK constraint** on `strategy_source_session_id` — session can be deleted without breaking client
5. **`strategy_version` defaults to 0** — indicates "no strategy generated yet"

### Rollout Sequence

1. Run Alembic migration (adds columns, zero downtime)
2. Deploy updated code (strategy_generator.py, modified handoff, schema)
3. Test on staging with one Discovery session
4. Operator triggers handoff on real session → verifies strategy_context populated
5. Verify pipeline reads strategy_context in next generation run
6. Monitor: check ActivityEvent logs for "discovery_handoff" events with strategy metadata

---

## Files Modified/Created Summary

| File | Action | Purpose |
|------|--------|---------|
| `app/schemas/client_strategy.py` | **NEW** | Pydantic validation schema for LLM output |
| `app/services/discovery/strategy_generator.py` | **NEW** | LLM call + validation logic |
| `app/services/discovery/strategy_handoff.py` | MODIFIED | Full handoff orchestration (strategy + GEO + status) |
| `app/models/client.py` | MODIFIED | +5 fields (strategy_context, version, generated_at, source_session_id, history) |
| `app/models/subreddit.py` | MODIFIED | +2 fields on ClientSubredditAssignment (priority, engagement_approach) |
| `app/routes/discovery.py` | MODIFIED | Guards + error handling on handoff endpoint |
| `app/services/generation.py` | MODIFIED | Read strategy_context for prompt enrichment |
| `app/services/smart_scoring.py` | MODIFIED | Read subreddit priorities for allocation |
| `app/services/phase.py` | MODIFIED | Read phase_roadmap for evaluation |
| `app/services/strategy_engine.py` | MODIFIED | Inject client strategy into avatar strategy |
| `alembic/versions/cstrat01_*.py` | **NEW** | DB migration |
| `templates/admin_discovery_detail.html` | MODIFIED | Button states + loading indicator |
| `templates/admin_discovery.html` | MODIFIED | "Handed Off" badge in session list |
