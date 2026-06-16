# Design Document

## Overview

The Post Generation Engine is a 10-step AI pipeline for generating Reddit self-posts from persona-based avatars. It extends the existing `post_generation.py` service by adding configurable multi-step processing: theme selection, experience generation, worthiness scoring, persona matching, friction generation, post type selection, post writing, worldview injection, anti-pattern filtering, and authenticity testing.

## Architecture

The pipeline is implemented as a set of 10 independent step modules orchestrated by a central `PostGenerationPipeline` class. Each step receives a `ClientPostConfig` and pipeline context, executes its logic (deterministic or LLM-based), and returns structured output. The orchestrator sequences steps, handles retries, enforces timeouts, and creates PostDraft records.

## Components and Interfaces

### PostGenerationPipeline (Orchestrator)

Location: `app/services/post_generation_pipeline.py`

```python
class PostGenerationPipeline:
    def __init__(self, db: Session, client: Client, run_id: uuid.UUID | None = None): ...
    def run(self, max_posts: int = 3) -> list[PostDraft]: ...
    def _load_config(self) -> ClientPostConfig: ...
    def _check_timeout(self): ...
```

### Pipeline Steps

Location: `app/services/post_gen_steps/`

| Module | Function | LLM Model | Purpose |
|--------|----------|-----------|---------|
| theme_selector.py | `select_theme()` | None (deterministic) | Weighted random from config |
| experience_generator.py | `generate_experiences()` | Gemini Flash | Generate 20 practitioner situations |
| worthiness_scorer.py | `score_situations()` | Gemini Flash | Score and rank situations |
| persona_matcher.py | `match_persona()` | Claude Sonnet (fallback: karma-based) | Match avatar to situation |
| friction_generator.py | `generate_friction()` | Gemini Flash | Extract emotional center |
| post_type_selector.py | `select_post_type()` | None (deterministic) | Affinity mapping + distribution |
| post_writer.py | `write_post()` | Claude Sonnet | Generate title + body |
| worldview_injector.py | `inject_worldview()` | Gemini Flash | Evaluate + inject concept |
| anti_pattern_filter.py | `check_anti_patterns()` | None (deterministic) | Regex + word list check |
| authenticity_tester.py | `test_authenticity()` | Gemini Flash | Pass/fail evaluation |

Each step follows:

```python
def step_function(
    db: Session,
    input_data: ...,
    config: ClientPostConfig,
    run_id: uuid.UUID,
) -> StepOutput:
    ...
```

### Integration Points

- **Celery Task**: `generate_posts` in `tasks/ai_pipeline.py` delegates to `PostGenerationPipeline` when client has active `ClientPostConfig`
- **Kill Switch**: `post_generation_enabled` system setting + `ClientPostConfig.post_generation_active` per-client flag
- **EPG**: PostDrafts with status="pending" automatically enter EPG scheduling queue (no change needed)
- **Self-Learning**: `LearningService.select_few_shot_examples()` + `get_correction_patterns()` injected into Post Writer prompt
- **Audit**: `log_system_action()`, `record_activity_event()`, `log_ai_usage()` at each step

## Data Models

### ClientPostConfig (New Table)

```python
class ClientPostConfig(Base):
    __tablename__ = "client_post_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), unique=True)
    allowed_themes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    forbidden_terms: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    content_mix_ratios: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    allowed_post_types: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    worldview_concepts: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    anti_pattern_words: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    worthiness_weights: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    top_n_situations: Mapped[int] = mapped_column(Integer, default=3)
    target_length_min: Mapped[int] = mapped_column(Integer, default=150)
    target_length_max: Mapped[int] = mapped_column(Integer, default=350)
    writing_rules: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    authenticity_threshold: Mapped[float] = mapped_column(Float, default=0.6)
    persona_theme_mapping: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    post_generation_active: Mapped[bool] = mapped_column(Boolean, default=False)
    brand_mention_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    client = relationship("Client", backref="post_config")
```

### Pydantic Schemas (LLM Output Validation)

Location: `app/schemas/post_gen_outputs.py`

```python
class ExperienceSituation(BaseModel):
    role: str
    context: str
    tool_reference: str
    scale_indicator: str
    outcome: str
    content_category: str

class ExperienceGeneratorOutput(BaseModel):
    situations: list[ExperienceSituation] = Field(min_length=5, max_length=25)

class WorthinessScores(BaseModel):
    curiosity: int = Field(ge=1, le=10)
    relatability: int = Field(ge=1, le=10)
    frustration: int = Field(ge=1, le=10)
    authenticity: int = Field(ge=1, le=10)
    discussion_potential: int = Field(ge=1, le=10)

class FrictionOutput(BaseModel):
    emotion: str
    statement: str = Field(min_length=40, max_length=200)
    confidence: float = Field(ge=0.0, le=1.0)

class PostOutput(BaseModel):
    title: str = Field(min_length=10, max_length=300)
    body: str = Field(min_length=50)

class AuthenticityOutput(BaseModel):
    passed: bool
    confidence: float = Field(ge=0.0, le=1.0)
    markers: list[str] = Field(max_length=3)
```

### Pipeline Context (Internal Data Flow)

```python
@dataclass
class PipelineContext:
    run_id: uuid.UUID
    client: Client
    config: ClientPostConfig
    theme: str | None = None
    content_category: str | None = None
    situations: list[dict] | None = None
    scored_situations: list[ScoredSituation] | None = None
    selected_situations: list[SelectedSituation] | None = None
    posts: list[GeneratedPost] | None = None
```

### SQL Migration

```sql
CREATE TABLE client_post_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id UUID NOT NULL UNIQUE REFERENCES clients(id),
    allowed_themes JSONB,
    forbidden_terms JSONB,
    content_mix_ratios JSONB,
    allowed_post_types JSONB,
    worldview_concepts JSONB,
    anti_pattern_words JSONB,
    worthiness_weights JSONB,
    top_n_situations INTEGER DEFAULT 3,
    target_length_min INTEGER DEFAULT 150,
    target_length_max INTEGER DEFAULT 350,
    writing_rules JSONB,
    authenticity_threshold FLOAT DEFAULT 0.6,
    persona_theme_mapping JSONB,
    post_generation_active BOOLEAN DEFAULT FALSE,
    brand_mention_cap INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

## Error Handling

| Failure Mode | Response |
|---|---|
| Theme selection: no viable theme | Log ActivityEvent, terminate run gracefully |
| Experience generation: LLM fails | Retry once with exponential backoff, then terminate |
| Experience generation: <5 valid situations | Retry once with varied prompt, then terminate |
| Worthiness scoring: all below 5.0 | Log low-quality event, terminate |
| Persona matching: no eligible avatar | Skip situation, continue with others |
| Post writing: exceeds max word count | Regenerate with -20% max, then truncate at last sentence |
| Anti-pattern filter: 2+ violations | Regenerate once with avoidance instructions, then discard |
| Authenticity test: fail after rewrite | Discard post, log failure, continue with next situation |
| Pipeline timeout (>5 min) | Terminate, discard incomplete drafts, log timeout event |
| DB error on PostDraft save | Rollback transaction, raise RuntimeError |
| Learning service failure | Log warning, proceed without learning context |

## Correctness Properties

### Property 1: Human Review Mandatory
All PostDrafts are created with status="pending" and never auto-posted without explicit human approval.

### Property 2: Phase Isolation
Phase 1 avatars never receive brand or worldview content in generated posts.

### Property 3: Kill Switch Freshness
Pipeline checks kill switches fresh from DB (not cache) at entry point to reflect cross-process changes.

### Property 4: Traceability
Each pipeline run has a unique UUID included in all audit, activity, and AI usage records.

### Property 5: Atomicity
No partial PostDraft records are left on failure — transactions are rolled back.

### Property 6: Daily Cap Enforcement
Avatar daily cap is respected counting both pending and posted PostDrafts for today.

### Property 7: Brand Cap Enforcement
Brand mention cap is enforced over a rolling 30-day window per avatar.

## Testing Strategy

- Unit tests per pipeline step (mock LLM calls, verify schema validation)
- Integration test: full pipeline with mocked LLM returning valid JSON
- Test kill switch: verify pipeline skips when disabled
- Test timeout: inject slow step, verify 5-min termination
- Test phase gates: Phase 1 avatar gets zero brand content
- Test anti-pattern filter: known bad words trigger rejection
- Test idempotency: running pipeline twice doesn't create duplicate posts for same theme
