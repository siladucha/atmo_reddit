# Design Document: AI Visibility Audit

## Overview

The AI Visibility Audit wraps existing RAMP services (Discovery Engine + GEO/AEO Monitoring) into a self-contained, automated product. An Operator creates an audit session with prospect data, the system executes Discovery and GEO phases sequentially without manual intervention, and delivers a branded report via a token-based portal URL.

**Key architectural principle**: The Audit does NOT duplicate any Discovery or GEO logic. It is a thin orchestration layer — a Celery task chain that calls existing service functions in sequence, managing state transitions between steps. All data lands in existing tables (discovery_sessions, discovery_entities, discovery_hypotheses, geo_prompts, geo_query_results, geo_execution_batches). The only new table is `audit_sessions` for lifecycle tracking.

**Design decisions**:
- Orchestration via Celery task chain (not a single monolithic task) — each phase is a separate task for observability, retry isolation, and progressive status updates
- Token-based prospect access (UUID + HMAC) — no login required, 90-day expiry
- Report as HTML with print CSS — no external PDF library, browser Ctrl+P for export
- Temporary Client record created for GEO phase (required by existing `run_geo_batch_for_client` API) — marked with `is_audit_prospect=True` flag, never shown in admin client list
- Cost tracking piggybacks on existing `ai_usage_log` table with `triggered_by="audit:{session_id}"` pattern

```
flowchart TD
    subgraph "Operator Action"
        CREATE[Create Audit Session<br>/admin/audits/new] --> TRIGGER[Trigger Execution]
    end

    subgraph "Phase 1: Discovery (existing services)"
        TRIGGER --> D1[create_session]
        D1 --> D2[extract_entities]
        D2 --> D3[form_hypotheses]
        D3 --> D4[research_hypotheses_task]
        D4 --> D5[Auto-decide hypotheses<br>confirm if score > 0.5]
    end

    subgraph "Phase 2: GEO Baseline (existing services)"
        D5 --> G1[Generate GEO Prompts<br>LLM from entities+hypotheses]
        G1 --> G2[run_geo_batch_for_client<br>Perplexity Sonar x3]
        G2 --> G3[Compute Visibility Score<br>+ Competitive Matrix]
    end

    subgraph "Phase 3: Report"
        G3 --> R1[Generate Report<br>Claude Sonnet]
        R1 --> R2[Store + Notify Operator]
    end

    R2 --> PORTAL[Prospect views at<br>/audit/{token}]
```

## Architecture

### New Model: AuditSession

Single new table that tracks the audit lifecycle and links to existing data.

```python
class AuditSession(Base):
    __tablename__ = "audit_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Prospect info
    prospect_name: Mapped[str] = mapped_column(String(200), nullable=False)
    brand_name: Mapped[str] = mapped_column(String(200), nullable=False)
    brand_domain: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company_brief: Mapped[str] = mapped_column(Text, nullable=False)  # min 50 chars
    competitors: Mapped[list] = mapped_column(JSONB, nullable=False)  # ["comp1", "comp2", ...]

    # Pricing
    pricing_tier: Mapped[str] = mapped_column(String(20), nullable=False)  # "standard" ($750) | "premium" ($1500)

    # Lifecycle
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="created")
    # Statuses: created → discovery_running → discovery_complete → geo_running →
    #           geo_complete → report_generating → completed → delivered
    #           Also: failed, abandoned
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    abandon_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Links to existing data
    discovery_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discovery_sessions.id"), nullable=True
    )
    geo_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("geo_execution_batches.id"), nullable=True
    )
    temp_client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=True
    )

    # Results (computed after GEO phase)
    visibility_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)  # 0-100
    competitive_matrix: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    report_html: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Cost & margin
    total_ai_cost_usd: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    gross_margin_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)

    # Access token for prospect portal
    access_token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Upsell tracking
    is_warm_lead: Mapped[bool] = mapped_column(Boolean, default=False)
    converted_client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=True
    )

    # Operator
    operator_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Calendar URL for CTA (configurable per operator)
    calendar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
```

### Access Token Generation

```python
import hmac, hashlib, secrets

def generate_audit_token(audit_id: uuid.UUID) -> str:
    """Generate HMAC-signed token: {random_part}.{signature}"""
    random_part = secrets.token_urlsafe(32)
    signature = hmac.new(
        key=settings.SECRET_KEY.encode(),
        msg=f"{audit_id}:{random_part}".encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()[:16]
    return f"{random_part}.{signature}"
```

Portal URL format: `https://gorampit.com/audit/{access_token}`

### Component Architecture

```
app/
├── models/
│   └── audit_session.py          # AuditSession model (NEW)
├── services/
│   └── audit_orchestrator.py     # Orchestration logic (NEW)
├── tasks/
│   └── audit.py                  # Celery task chain (NEW)
├── routes/
│   ├── admin_audits.py           # Operator dashboard (NEW)
│   └── audit_portal.py           # Prospect-facing portal (NEW)
├── templates/
│   ├── admin_audit_list.html     # Audit management table
│   ├── admin_audit_detail.html   # Single audit detail + controls
│   ├── admin_audit_new.html      # Creation form
│   ├── audit_portal.html         # Prospect progress/results view
│   └── audit_report.html         # Standalone branded report
```

## Orchestration Flow

### Service: `audit_orchestrator.py`

Stateless orchestration functions called by Celery tasks. Each function:
1. Loads AuditSession from DB
2. Validates current status (guards against duplicate execution)
3. Calls existing service
4. Updates AuditSession status
5. Returns next-step indicator

```python
class AuditOrchestrator:
    """Coordinates audit phase execution using existing services."""

    def start_discovery(self, db: Session, audit_id: uuid.UUID) -> None:
        """Phase 1a: Create DiscoverySession + extract entities."""
        audit = self._load_and_validate(db, audit_id, expected_status="created")
        audit.status = "discovery_running"
        audit.started_at = now()
        db.commit()

        # Create discovery session using existing SessionManager
        session = create_session(
            db=db,
            client_brief=audit.company_brief,
            prospect_name=audit.prospect_name,
            operator_user_id=audit.operator_user_id,
            client_id=None,  # No client yet — prospect only
        )
        audit.discovery_session_id = session.id
        db.commit()

        # Extract entities (async — run in event loop)
        result = asyncio.run(extract_entities(
            client_brief=audit.company_brief,
            db=db,
            session_id=session.id,
        ))
        # Auto-confirm all entities (no operator review needed for audit)
        for entity in result["entities"]:
            entity.is_confirmed = True
        db.commit()

    def run_hypotheses(self, db: Session, audit_id: uuid.UUID) -> None:
        """Phase 1b: Form + research hypotheses."""
        audit = self._load_and_validate(db, audit_id, expected_status="discovery_running")
        session = db.query(DiscoverySession).get(audit.discovery_session_id)
        entities = session.entities

        # Form hypotheses
        hypotheses = asyncio.run(form_hypotheses(
            entities=entities,
            session=session,
            db=db,
        ))

        # Research all hypotheses (uses PRAW — synchronous)
        from app.tasks.discovery import research_hypotheses_task
        research_hypotheses_task(session_id=session.id)

        # Auto-decide: confirm score > 0.5, reject <= 0.5
        for h in session.hypotheses:
            if h.status == "proposed":
                if h.confidence_score > 50:
                    h.status = "confirmed"
                else:
                    h.status = "rejected"
                h.decided_at = now()
        db.commit()

        audit.status = "discovery_complete"
        db.commit()

    def run_geo_baseline(self, db: Session, audit_id: uuid.UUID) -> None:
        """Phase 2: Generate prompts + execute GEO batch."""
        audit = self._load_and_validate(db, audit_id, expected_status="discovery_complete")
        audit.status = "geo_running"
        db.commit()

        # Create temporary Client record for GEO API
        temp_client = Client(
            client_name=f"[Audit] {audit.prospect_name}",
            brand_name=audit.brand_name,
            brand_domain=audit.brand_domain,
            is_active=False,  # Never appears in normal flows
            is_audit_prospect=True,
        )
        db.add(temp_client)
        db.flush()
        audit.temp_client_id = temp_client.id
        db.commit()

        # Generate GEO prompts from discovery findings (LLM call)
        prompts = self._generate_geo_prompts(db, audit, temp_client)

        # Run GEO batch using existing service
        batch = run_geo_batch_for_client(
            db=db,
            client=temp_client,
            triggered_by=f"audit:{audit.id}",
        )
        audit.geo_batch_id = batch.id

        # Compute visibility scores
        self._compute_scores(db, audit, batch)

        audit.status = "geo_complete"
        db.commit()

    def generate_report(self, db: Session, audit_id: uuid.UUID) -> None:
        """Phase 3: LLM-generated report from all findings."""
        audit = self._load_and_validate(db, audit_id, expected_status="geo_complete")
        audit.status = "report_generating"
        db.commit()

        report_html = self._call_report_llm(db, audit)
        audit.report_html = report_html
        audit.status = "completed"
        audit.completed_at = now()
        audit.is_warm_lead = True

        # Compute margin
        tier_amount = 750 if audit.pricing_tier == "standard" else 1500
        if audit.total_ai_cost_usd > 0:
            audit.gross_margin_pct = ((tier_amount - float(audit.total_ai_cost_usd)) / tier_amount) * 100
        else:
            audit.gross_margin_pct = 100.0

        db.commit()
```

### Celery Task Chain: `tasks/audit.py`

```python
@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def audit_phase_discovery(self, audit_id: str) -> str:
    """Phase 1: Discovery (entities + hypotheses + research)."""
    try:
        orchestrator = AuditOrchestrator()
        with get_db_session() as db:
            orchestrator.start_discovery(db, uuid.UUID(audit_id))
            orchestrator.run_hypotheses(db, uuid.UUID(audit_id))
        return audit_id
    except Exception as e:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        _mark_failed(audit_id, str(e))
        raise

@celery_app.task(bind=True, max_retries=3, default_retry_delay=120)
def audit_phase_geo(self, audit_id: str) -> str:
    """Phase 2: GEO baseline measurement."""
    try:
        orchestrator = AuditOrchestrator()
        with get_db_session() as db:
            orchestrator.run_geo_baseline(db, uuid.UUID(audit_id))
        return audit_id
    except Exception as e:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        _mark_failed(audit_id, str(e))
        raise

@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def audit_phase_report(self, audit_id: str) -> str:
    """Phase 3: Report generation."""
    try:
        orchestrator = AuditOrchestrator()
        with get_db_session() as db:
            orchestrator.generate_report(db, uuid.UUID(audit_id))
        return audit_id
    except Exception as e:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        _mark_failed(audit_id, str(e))
        raise

def trigger_audit_execution(audit_id: uuid.UUID) -> None:
    """Dispatch the full audit pipeline as a Celery chain."""
    chain = (
        audit_phase_discovery.s(str(audit_id))
        | audit_phase_geo.s()
        | audit_phase_report.s()
    )
    chain.apply_async()
```

## GEO Prompt Generation

The bridge between Discovery findings and GEO measurement. Uses Gemini Flash to generate buyer-intent prompts that a real person would ask an AI search engine about the prospect's industry.

```python
GEO_PROMPT_GENERATION_SYSTEM = """You are an AI search behavior analyst.

Given a brand, its industry entities, and validated market hypotheses,
generate prompts that a potential buyer would type into ChatGPT, Gemini, or Perplexity
when researching solutions in this space.

RULES:
- Generate 10-30 prompts
- Each prompt should be a natural question (not a keyword)
- Mix intent types: informational, comparison, recommendation, problem-solving
- Include prompts where the brand SHOULD appear if well-known
- Include prompts about competitor categories
- Assign category: "brand_direct", "category", "comparison", "problem_solution", "competitor"

OUTPUT JSON:
{
  "prompts": [
    {"text": "What is the best...", "category": "comparison"},
    ...
  ]
}
"""
```

## Visibility Score Computation

```python
def compute_visibility_score(
    batch: GeoExecutionBatch,
    brand_name: str,
    db: Session,
) -> float:
    """Composite score 0-100 from GEO frequency metrics.

    Formula:
        score = avg(brand_appearance_rate) * 100

    Where brand_appearance_rate is already 0.0-1.0 per prompt
    (how often brand appeared across N runs of that prompt).
    """
    metrics = db.query(GeoFrequencyMetric).filter(
        GeoFrequencyMetric.execution_batch_id == batch.id
    ).all()

    if not metrics:
        return 0.0

    rates = [float(m.brand_appearance_rate) for m in metrics]
    return round(sum(rates) / len(rates) * 100, 1)
```

## Competitive Matrix Computation

```python
def compute_competitive_matrix(
    batch: GeoExecutionBatch,
    brand_name: str,
    competitors: list[str],
    db: Session,
) -> dict:
    """Build comparison matrix: brand + each competitor → appearance rate.

    Returns:
    {
        "brand": {"name": "XM Cyber", "score": 23.5, "prompts_appeared": 7, "total_prompts": 30},
        "competitors": [
            {"name": "CrowdStrike", "score": 67.2, "prompts_appeared": 20, "total_prompts": 30},
            {"name": "SentinelOne", "score": 45.0, "prompts_appeared": 13, "total_prompts": 30},
        ],
        "leader": "CrowdStrike",
        "brand_rank": 4,
        "total_brands": 5,
    }
    """
    results = db.query(GeoQueryResult).filter(
        GeoQueryResult.execution_batch_id == batch.id,
        GeoQueryResult.status == "success",
    ).all()

    # Count appearances per brand across all results
    brand_count = sum(1 for r in results if r.brand_mentioned)
    total = len(results)

    competitor_scores = []
    for comp in competitors:
        comp_count = sum(
            1 for r in results
            if r.competitors_mentioned and comp.lower() in str(r.competitors_mentioned).lower()
        )
        competitor_scores.append({
            "name": comp,
            "score": round(comp_count / total * 100, 1) if total > 0 else 0,
            "prompts_appeared": comp_count,
            "total_prompts": total,
        })

    # Sort competitors by score descending
    competitor_scores.sort(key=lambda x: x["score"], reverse=True)

    brand_score = round(brand_count / total * 100, 1) if total > 0 else 0
    all_scores = [{"name": brand_name, "score": brand_score}] + competitor_scores
    all_scores.sort(key=lambda x: x["score"], reverse=True)
    brand_rank = next(i+1 for i, s in enumerate(all_scores) if s["name"] == brand_name)

    return {
        "brand": {"name": brand_name, "score": brand_score, "prompts_appeared": brand_count, "total_prompts": total},
        "competitors": competitor_scores,
        "leader": all_scores[0]["name"],
        "brand_rank": brand_rank,
        "total_brands": len(all_scores),
    }
```

## Report Generation

Claude Sonnet generates the report narrative from structured data. The report is stored as self-contained HTML (inline CSS, no external deps).

### Report Structure

1. **Executive Summary** — 3-4 sentences: current visibility score, rank, key finding
2. **Market Discovery** — subreddits found, entities, community sizes, engagement volumes
3. **AI Visibility Baseline** — score gauge, competitive matrix chart, per-prompt breakdown table
4. **Subreddit Strategy** — which communities to target, expected audience size
5. **Competitive Positioning** — who dominates, where the gaps are
6. **Recommended Next Steps** — 3-5 data-backed actions (upsell hook)
7. **What Managed Service Delivers** — comparison current vs. projected

### Report Styling

- Self-contained HTML with `<style>` block (no external CSS/JS)
- RAMP brand colors: primary `#1a1a2e`, secondary `#16213e`, accent `#0f3460`
- Print-friendly CSS: `@media print { ... }` hides navigation, forces white background
- Charts as HTML/CSS (no JS): gauge via CSS conic-gradient, bars via flexbox + percentage widths
- Footer: audit date, session reference, "Powered by RAMP"

## Prospect Portal

### URL: `/audit/{access_token}`

No authentication required. Token validated via HMAC + expiry check.

### States

| Audit Status | Portal Display |
|-------------|---------------|
| created | "Your audit is queued. We'll begin shortly." |
| discovery_running | Step progress: "Analyzing your market..." (1/4 active) |
| discovery_complete | Step progress: "Market analysis complete. Measuring AI visibility..." (2/4 done) |
| geo_running | Step progress: "Querying AI search engines..." (3/4 active) |
| geo_complete | Step progress: "Generating your report..." |
| report_generating | Step progress: "Finalizing report..." |
| completed | Full report displayed + download button + CTA |
| delivered | Same as completed (delivered = operator marked it sent) |
| failed | "We encountered an issue. Our team has been notified." |

### Auto-refresh

While status is `*_running` or `report_generating`, the page polls via HTMX every 30 seconds:
```html
<div hx-get="/audit/{{ token }}/status" hx-trigger="every 30s" hx-swap="outerHTML">
    <!-- Progress indicator -->
</div>
```

### CTA Section (after report)

```html
<div class="cta-card">
    <h3>Ready to improve these numbers?</h3>
    <p>Your visibility score is {{ score }}. Our managed service typically delivers
       20-40% improvement within 90 days.</p>
    <a href="{{ calendar_url }}" class="cta-button">Schedule a Strategy Call</a>
</div>
```

## Operator Dashboard

### Route: `/admin/audits`

Standard admin page extending `admin_base.html` (dark theme).

**List view:**
- Summary metrics bar: total completed | avg AI cost | avg margin | total revenue
- Tab filters: All | Running | Completed | Failed | Abandoned
- Table columns: Prospect | Brand | Status (badge) | Tier | Created | Completed
- Row click → detail page

**Detail view (`/admin/audits/{id}`):**
- Status timeline (visual steps)
- Discovery summary: entities found, hypotheses confirmed, subreddits discovered
- GEO results: visibility score, competitive matrix
- Report preview (iframe or inline)
- Costs: AI cost breakdown, margin %
- Actions: Re-run GEO | Convert to Client | Copy Portal Link | Mark Delivered | Abandon

## Convert to Client Flow

When operator clicks "Convert to Client":

1. Create real `Client` record with `brand_name`, `brand_domain`, `company_brief`
2. Copy confirmed entities into client's keyword structure
3. Create `ClientSubredditAssignment` records from discovered subreddits
4. Copy `GeoPrompt` records (re-link to new client_id)
5. Set `audit.converted_client_id = new_client.id`
6. Redirect to onboarding wizard step 4 (avatars)

## Cost Tracking

AI cost accumulates from:
- Entity extraction (Gemini Flash): ~$0.003
- Hypothesis formation (Gemini Flash): ~$0.005
- Reddit research (PRAW, no LLM cost): $0
- GEO prompt generation (Gemini Flash): ~$0.005
- GEO batch execution (Perplexity Sonar, 10-30 prompts x 3 runs): ~$0.50-$1.50
- Report generation (Claude Sonnet): ~$0.15

**Expected total per audit: $0.70-$1.70**

At $750 standard tier: gross margin ~99.8%
At $1,500 premium tier: gross margin ~99.9%

Cost warning threshold: $15 (emits ActivityEvent but doesn't halt).

## Error Handling

| Phase | Error Type | Retry | Outcome if exhausted |
|-------|-----------|-------|---------------------|
| Discovery - entity extraction | LLM timeout | 3x (60s delay) | status="failed" |
| Discovery - hypotheses | LLM timeout | 3x (60s delay) | status="failed" |
| Discovery - research | PRAW rate limit | 3x (120s delay) | status="failed" |
| GEO - prompt generation | LLM timeout | 3x (60s delay) | status="failed" |
| GEO - batch execution | Perplexity 429 | 3x (60/120/240s) | status="failed" |
| Report - generation | Claude timeout | 2x (60s delay) | status="failed" |

On any `failed` status:
1. `error_message` stored on AuditSession
2. ActivityEvent emitted with `event_type="audit_failed"`
3. Operator can retry from the failed phase (button on detail page)

## Migration

Single Alembic migration:

```sql
CREATE TABLE audit_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prospect_name VARCHAR(200) NOT NULL,
    brand_name VARCHAR(200) NOT NULL,
    brand_domain VARCHAR(500),
    company_brief TEXT NOT NULL,
    competitors JSONB NOT NULL DEFAULT '[]',
    pricing_tier VARCHAR(20) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'created',
    error_message TEXT,
    abandon_reason VARCHAR(500),
    discovery_session_id UUID REFERENCES discovery_sessions(id),
    geo_batch_id UUID REFERENCES geo_execution_batches(id),
    temp_client_id UUID REFERENCES clients(id),
    visibility_score NUMERIC(5,2),
    competitive_matrix JSONB,
    report_html TEXT,
    total_ai_cost_usd NUMERIC(10,4) DEFAULT 0,
    gross_margin_pct NUMERIC(5,2),
    access_token VARCHAR(128) UNIQUE NOT NULL,
    token_expires_at TIMESTAMPTZ,
    is_warm_lead BOOLEAN DEFAULT FALSE,
    converted_client_id UUID REFERENCES clients(id),
    operator_user_id UUID NOT NULL REFERENCES users(id),
    calendar_url VARCHAR(500),
    created_at TIMESTAMPTZ DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ
);

CREATE INDEX ix_audit_sessions_status ON audit_sessions(status);
CREATE INDEX ix_audit_sessions_operator ON audit_sessions(operator_user_id);
CREATE INDEX ix_audit_sessions_token ON audit_sessions(access_token);

-- Add is_audit_prospect flag to clients table
ALTER TABLE clients ADD COLUMN is_audit_prospect BOOLEAN DEFAULT FALSE;
```

## Files Changed

| File | Change Type | Purpose |
|------|-------------|---------|
| `app/models/audit_session.py` | NEW | AuditSession SQLAlchemy model |
| `app/services/audit_orchestrator.py` | NEW | Orchestration logic (4 phase functions) |
| `app/services/audit_report_generator.py` | NEW | LLM report generation + HTML rendering |
| `app/services/audit_geo_prompts.py` | NEW | LLM-based GEO prompt generation from discovery data |
| `app/tasks/audit.py` | NEW | Celery task chain (3 tasks + trigger function) |
| `app/routes/admin_audits.py` | NEW | Operator dashboard routes |
| `app/routes/audit_portal.py` | NEW | Prospect portal routes (token-based) |
| `app/templates/admin_audit_list.html` | NEW | Audit list page |
| `app/templates/admin_audit_detail.html` | NEW | Audit detail page |
| `app/templates/admin_audit_new.html` | NEW | Audit creation form |
| `app/templates/audit_portal.html` | NEW | Prospect-facing portal |
| `app/templates/audit_report.html` | NEW | Standalone branded report template |
| `app/models/client.py` | MODIFIED | Add `is_audit_prospect` boolean column |
| `app/main.py` | MODIFIED | Include new routers |
| `app/middleware/auth.py` | MODIFIED | Add `/audit/` to PUBLIC_PREFIXES |
| `alembic/versions/xxx_add_audit_sessions.py` | NEW | Migration |


## Components and Interfaces

### 1. `audit_orchestrator.py` — Phase Coordinator

**Interface:**
```python
class AuditOrchestrator:
    def start_discovery(self, db: Session, audit_id: uuid.UUID) -> None
    def run_hypotheses(self, db: Session, audit_id: uuid.UUID) -> None
    def run_geo_baseline(self, db: Session, audit_id: uuid.UUID) -> None
    def generate_report(self, db: Session, audit_id: uuid.UUID) -> None
    def abandon(self, db: Session, audit_id: uuid.UUID, reason: str | None) -> None
    def retry_from_phase(self, db: Session, audit_id: uuid.UUID) -> None
```

**Consumed by:** Celery tasks in `tasks/audit.py`
**Consumes:** SessionManager, extract_entities, form_hypotheses, research_hypotheses_task, run_geo_batch_for_client

### 2. `audit_geo_prompts.py` — Prompt Generator

**Interface:**
```python
async def generate_audit_geo_prompts(
    db: Session,
    audit: AuditSession,
    client: Client,
    entities: list[DiscoveryEntity],
    hypotheses: list[DiscoveryHypothesis],
) -> list[GeoPrompt]
```

**Consumed by:** AuditOrchestrator.run_geo_baseline
**Consumes:** call_llm_json (Gemini Flash)

### 3. `audit_report_generator.py` — Report Builder

**Interface:**
```python
async def generate_audit_report(
    db: Session,
    audit: AuditSession,
) -> str  # Returns HTML string
```

**Consumed by:** AuditOrchestrator.generate_report
**Consumes:** call_llm_json (Claude Sonnet), Jinja2 template rendering

### 4. `tasks/audit.py` — Celery Tasks

**Interface:**
```python
def trigger_audit_execution(audit_id: uuid.UUID) -> None  # Dispatches chain
# Individual tasks:
audit_phase_discovery(audit_id: str) -> str  # Phase 1
audit_phase_geo(audit_id: str) -> str        # Phase 2
audit_phase_report(audit_id: str) -> str     # Phase 3
```

**Consumed by:** admin_audits route handler
**Consumes:** AuditOrchestrator

### 5. `routes/admin_audits.py` — Operator Dashboard

**Routes:**
| Method | Path | Response | Purpose |
|--------|------|----------|---------|
| GET | /admin/audits | HTML | List all audits |
| GET | /admin/audits/new | HTML | Creation form |
| POST | /admin/audits | Redirect | Create + trigger |
| GET | /admin/audits/{id} | HTML | Detail page |
| POST | /admin/audits/{id}/rerun-geo | JSON | Re-run GEO only |
| POST | /admin/audits/{id}/convert | Redirect | Convert to client |
| POST | /admin/audits/{id}/deliver | JSON | Mark delivered |
| POST | /admin/audits/{id}/abandon | JSON | Abandon session |

**Consumed by:** Admin UI (browser)
**Dependencies:** require_platform_admin

### 6. `routes/audit_portal.py` — Prospect Portal

**Routes:**
| Method | Path | Response | Purpose |
|--------|------|----------|---------|
| GET | /audit/{token} | HTML | Main portal page |
| GET | /audit/{token}/status | HTML partial | HTMX polling status |
| GET | /audit/{token}/report | HTML | Standalone report (print view) |

**Consumed by:** Prospect browser (no auth required)
**Auth:** Token validation (HMAC + expiry)

## Data Models

### New Table: `audit_sessions`

```sql
CREATE TABLE audit_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prospect_name VARCHAR(200) NOT NULL,
    brand_name VARCHAR(200) NOT NULL,
    brand_domain VARCHAR(500),
    company_brief TEXT NOT NULL,
    competitors JSONB NOT NULL DEFAULT '[]',
    pricing_tier VARCHAR(20) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'created',
    error_message TEXT,
    abandon_reason VARCHAR(500),
    discovery_session_id UUID REFERENCES discovery_sessions(id),
    geo_batch_id UUID REFERENCES geo_execution_batches(id),
    temp_client_id UUID REFERENCES clients(id),
    visibility_score NUMERIC(5,2),
    competitive_matrix JSONB,
    report_html TEXT,
    total_ai_cost_usd NUMERIC(10,4) DEFAULT 0,
    gross_margin_pct NUMERIC(5,2),
    access_token VARCHAR(128) UNIQUE NOT NULL,
    token_expires_at TIMESTAMPTZ,
    is_warm_lead BOOLEAN DEFAULT FALSE,
    converted_client_id UUID REFERENCES clients(id),
    operator_user_id UUID NOT NULL REFERENCES users(id),
    calendar_url VARCHAR(500),
    created_at TIMESTAMPTZ DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ
);

CREATE INDEX ix_audit_sessions_status ON audit_sessions(status);
CREATE INDEX ix_audit_sessions_operator ON audit_sessions(operator_user_id);
CREATE INDEX ix_audit_sessions_token ON audit_sessions(access_token);
```

### Modified Table: `clients`

```sql
ALTER TABLE clients ADD COLUMN is_audit_prospect BOOLEAN DEFAULT FALSE;
```

### Status Transition Diagram

```
created ──────► discovery_running ──► discovery_complete ──► geo_running
                     │                                           │
                     ▼                                           ▼
                  failed ◄──────────── geo_complete ──────► report_generating
                     ▲                      │                    │
                     │                      ▼                    ▼
                abandoned              completed ──────────► delivered
```

### Relationships to Existing Models

| AuditSession Field | References | Purpose |
|-------------------|-----------|---------|
| discovery_session_id | discovery_sessions.id | Links to full Discovery data (entities, hypotheses, reports) |
| geo_batch_id | geo_execution_batches.id | Links to GEO results (query results, frequency metrics) |
| temp_client_id | clients.id | Temporary client record for GEO API compatibility |
| operator_user_id | users.id | Who created this audit |
| converted_client_id | clients.id | Real client if prospect converts |

## Correctness Properties

### Property 1: Status Transitions Are Monotonic

The audit status must only advance forward through the defined sequence, except for terminal states (failed, abandoned) which can be reached from any running state.

**Invariant:** `status(t+1)` is always the next valid status after `status(t)` in the sequence, OR one of {failed, abandoned}.

**Validates: Requirements 1.3, 1.4**

### Property 2: No Duplicate Phase Execution

Each phase function validates the current status before executing. If the audit is not in the expected status, the function raises an error. This prevents double-execution from retried Celery tasks.

**Invariant:** `start_discovery` only executes when status="created", `run_hypotheses` only when status="discovery_running", etc.

**Validates: Requirements 2.1, 3.1**

### Property 3: Data Isolation

Audit data is scoped to the AuditSession. Temporary Client records have `is_audit_prospect=True` and `is_active=False`, ensuring they never appear in normal admin lists, pipeline flows, or client portal views.

**Invariant:** `SELECT * FROM clients WHERE is_active=True` never returns audit prospect records.

**Validates: Requirements 1.1, 5.4**

### Property 4: Token Uniqueness and Validity

Each audit session has a unique access_token. Token validation checks both HMAC signature integrity and expiry timestamp. Expired tokens return a branded error page, not a redirect to login.

**Invariant:** For any two audit sessions A and B, `A.access_token != B.access_token`.

**Validates: Requirements 1.2, 5.4**

### Property 5: Cost Accumulation Accuracy

Total AI cost is the sum of all ai_usage_log entries where triggered_by contains the audit session ID. The gross_margin_pct is computed only once at completion.

**Invariant:** `audit.total_ai_cost_usd >= 0` and `audit.gross_margin_pct <= 100.0` when set.

**Validates: Requirements 7.1, 7.2**

### Property 6: Prospect Data Preservation

When an audit completes, all structured data (entities, hypotheses, subreddits, GEO prompts, results) remains intact for potential client conversion. The "Convert to Client" action copies data — it does not move or delete it.

**Invariant:** After conversion, `audit.discovery_session_id` still points to valid data.

**Validates: Requirements 8.2, 8.3**

## Testing Strategy

### Unit Tests

| Test | Validates |
|------|-----------|
| `test_audit_session_creation` | Model creation with all required fields |
| `test_status_transitions` | Valid transitions accepted, invalid rejected |
| `test_token_generation_uniqueness` | 1000 tokens are all unique |
| `test_token_validation` | Valid token passes, tampered/expired fails |
| `test_visibility_score_computation` | Score formula correctness with mock metrics |
| `test_competitive_matrix_ranking` | Correct sorting and rank assignment |
| `test_cost_accumulation` | Cost summed correctly from AI usage logs |
| `test_margin_calculation` | Margin computed correctly for both tiers |

### Integration Tests

| Test | Validates |
|------|-----------|
| `test_discovery_phase_end_to_end` | Orchestrator creates session, extracts entities, forms hypotheses (mocked LLM) |
| `test_geo_phase_end_to_end` | Orchestrator generates prompts, runs batch (mocked Perplexity), computes scores |
| `test_report_generation` | Report HTML contains all required sections |
| `test_full_pipeline_happy_path` | All 3 phases complete sequentially, status transitions correct |
| `test_failure_recovery` | Phase fails, status="failed", error_message set, ActivityEvent emitted |
| `test_portal_token_access` | Valid token shows progress, invalid shows error page |
| `test_convert_to_client` | Client created with correct data from audit |

### Manual QA Checklist

- [ ] Create audit from admin panel with all fields
- [ ] Watch status progress through all phases (may need to mock external APIs)
- [ ] Access portal URL as prospect (no login)
- [ ] Verify report renders correctly in browser
- [ ] Ctrl+P produces clean PDF
- [ ] Re-run GEO on completed audit
- [ ] Convert audit to client and verify pre-populated data
- [ ] Test expired token shows branded error
- [ ] Verify temporary client never appears in admin client list
