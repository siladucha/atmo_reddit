# Design Document: Activity Feed & Client Transparency

## Overview

This feature adds operational transparency to the Reddit Marketing SaaS platform through three interconnected capabilities:

1. **Activity Events** — a structured event log (`activity_events` table) that records every pipeline action (scrape, score, generate, review) with human-readable messages and JSONB metadata.
2. **Scrape Log** — a dedicated table (`scrape_log`) recording per-subreddit scraping run metrics (posts found, new posts, duration, errors) plus a `last_scraped_at` column on `client_subreddits` for freshness tracking.
3. **Client Transparency Dashboard** — a new admin page at `/admin/clients/{id}/transparency` aggregating pipeline statistics, scoring distributions, draft statuses, AI costs, scrape freshness, and client-scoped activity history.

The system instruments existing Celery tasks (scraping, scoring, generation) and review status changes to emit `ActivityEvent` records. A new `transparency.py` service encapsulates all aggregation queries, keeping route handlers thin. The admin dashboard gets an Activity Feed section loaded via HTMX partial, and each client gets a dedicated transparency page linked from the client detail page.

### Design Rationale

- **Separate table vs. reusing AuditLog**: `AuditLog` tracks human admin actions (CRUD, config changes) with `user_id` as a required context. Activity events are system-generated pipeline actions with no user context. Separate tables keep concerns clean and allow independent indexing/retention policies.
- **Scrape Log as separate table**: Embedding scrape metrics into `activity_events` metadata would work but makes per-subreddit aggregation queries (avg posts_new, total posts_found) expensive. A dedicated `scrape_log` table with a composite index enables efficient freshness and health queries.
- **Service layer returning dicts**: Following the existing pattern where route handlers receive pre-computed data and pass it to templates. Returning plain dicts from `transparency.py` keeps templates decoupled from SQLAlchemy models.

## Architecture

```mermaid
graph TB
    subgraph "Celery Tasks (Instrumented)"
        SCRAPE[scraping.py<br/>scrape_professional_subreddits<br/>scrape_hobby_subreddits]
        SCORE[ai_pipeline.py<br/>score_threads]
        GEN[ai_pipeline.py<br/>generate_comments]
    end

    subgraph "Review Flow"
        REVIEW[routes/review.py<br/>approve/reject/post]
    end

    subgraph "New Service Layer"
        TRANSPARENCY[services/transparency.py<br/>- get_activity_events<br/>- get_pipeline_stats<br/>- get_scrape_freshness<br/>- record_activity_event]
    end

    subgraph "New Models"
        AE[models/activity_event.py<br/>ActivityEvent]
        SL[models/scrape_log.py<br/>ScrapeLog]
    end

    subgraph "Modified Models"
        CS[models/subreddit.py<br/>+ last_scraped_at]
    end

    subgraph "New Routes"
        DASH_FEED[routes/admin.py<br/>GET /admin/ (+ feed)]
        DASH_PARTIAL[routes/admin.py<br/>GET /admin/activity-feed]
        TRANSP[routes/admin.py<br/>GET /admin/clients/{id}/transparency]
        TRANSP_PARTIAL[routes/admin.py<br/>GET /admin/clients/{id}/activity-feed]
    end

    subgraph "New Templates"
        T_FEED[partials/activity_feed.html]
        T_TRANSP[admin_client_transparency.html]
    end

    SCRAPE -->|record_activity_event + insert ScrapeLog| TRANSPARENCY
    SCORE -->|record_activity_event| TRANSPARENCY
    GEN -->|record_activity_event| TRANSPARENCY
    REVIEW -->|record_activity_event| TRANSPARENCY

    TRANSPARENCY --> AE
    TRANSPARENCY --> SL
    SCRAPE --> CS

    DASH_FEED --> TRANSPARENCY
    DASH_PARTIAL --> TRANSPARENCY
    TRANSP --> TRANSPARENCY
    TRANSP_PARTIAL --> TRANSPARENCY

    DASH_FEED --> T_FEED
    DASH_PARTIAL --> T_FEED
    TRANSP --> T_TRANSP
    TRANSP_PARTIAL --> T_FEED
```

### Data Flow

1. **Pipeline instrumentation**: Each Celery task calls `record_activity_event()` after completing its work. Scraping tasks additionally insert `ScrapeLog` records and update `ClientSubreddit.last_scraped_at`.
2. **Review instrumentation**: The existing review route handlers (approve/reject/post) call `record_activity_event()` after status changes.
3. **Dashboard feed**: The admin dashboard route queries `get_activity_events(limit=50)` and renders the feed via an HTMX partial.
4. **Transparency page**: The transparency route calls `get_pipeline_stats()`, `get_scrape_freshness()`, and `get_activity_events(client_id=...)` to build the full page context.

## Components and Interfaces

### 1. Models

#### `ActivityEvent` (new file: `app/models/activity_event.py`)

```python
class ActivityEvent(Base):
    __tablename__ = "activity_events"

    id: Mapped[uuid.UUID]           # PK, default uuid4
    client_id: Mapped[uuid.UUID | None]  # FK clients.id, nullable (system-wide events)
    event_type: Mapped[str]         # "scrape" | "score" | "generate" | "review" | "system"
    message: Mapped[str]            # Human-readable, e.g. "Scraped 47 posts from r/meditation (12 new)"
    metadata: Mapped[dict | None]   # JSONB structured details
    created_at: Mapped[datetime]    # server_default=func.now()
```

#### `ScrapeLog` (new file: `app/models/scrape_log.py`)

```python
class ScrapeLog(Base):
    __tablename__ = "scrape_log"

    id: Mapped[uuid.UUID]           # PK, default uuid4
    client_id: Mapped[uuid.UUID]    # FK clients.id
    subreddit_name: Mapped[str]     # e.g. "meditation"
    scraped_at: Mapped[datetime]    # server_default=func.now()
    posts_found: Mapped[int]        # Total from Reddit API
    posts_new: Mapped[int]          # After deduplication
    errors: Mapped[str | None]      # null on success, error message on failure
    duration_ms: Mapped[int]        # Wall-clock time of the scrape

    __table_args__ = (
        Index("ix_scrape_log_client_sub_time", "client_id", "subreddit_name", "scraped_at"),
    )
```

#### `ClientSubreddit` (modified: `app/models/subreddit.py`)

```python
# Add one column:
last_scraped_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True), nullable=True
)
```

### 2. Service: `app/services/transparency.py`

All functions accept a `Session` and return plain `dict` / `list[dict]`.

```python
def record_activity_event(
    db: Session,
    event_type: str,
    message: str,
    client_id: uuid.UUID | None = None,
    metadata: dict | None = None,
) -> ActivityEvent:
    """Insert an ActivityEvent record. Commits immediately."""

def get_activity_events(
    db: Session,
    client_id: uuid.UUID | None = None,
    event_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Retrieve activity events with optional filters. Returns list of dicts."""

def get_pipeline_stats(db: Session, client_id: uuid.UUID) -> dict:
    """Compute pipeline statistics for a client.
    Returns:
        {
            "threads": {"total": int, "last_24h": int, "last_7d": int},
            "tags": {"engage": int, "monitor": int, "skip": int, "unscored": int},
            "drafts": {"pending": int, "approved": int, "rejected": int, "posted": int},
            "ai_costs": {"total": Decimal, "by_operation": {"scoring": Decimal, ...}},
        }
    """

def get_scrape_freshness(db: Session, client_id: uuid.UUID) -> list[dict]:
    """Per-subreddit scrape freshness data.
    Returns list of:
        {
            "subreddit_name": str,
            "last_scraped_at": datetime | None,
            "total_posts_found": int,
            "avg_posts_new": float,
            "is_stale": bool,  # last_scraped_at > 24h ago or None
        }
    """
```

### 3. Pipeline Instrumentation

#### `app/tasks/scraping.py` — changes

In `scrape_professional_subreddits`, for each subreddit in the loop:
1. Record wall-clock time (`time.time()` before/after).
2. After scraping + dedup, insert a `ScrapeLog` record via direct model insert (tasks use `SessionLocal`, not dependency injection).
3. Update `ClientSubreddit.last_scraped_at = datetime.now(timezone.utc)`.
4. Call `record_activity_event(db, "scrape", message, client_id, metadata)`.
5. On exception, still insert `ScrapeLog` with `errors=str(e)`, `posts_found=0`, `posts_new=0`, and create a `"system"` activity event for the failure.

Similar changes for `scrape_hobby_subreddits` (hobby scrapes don't have a client_id directly, so activity events use `client_id=None` or derive from avatar).

#### `app/tasks/ai_pipeline.py` — changes

- `score_threads`: After `score_unscored_threads()` returns, query the tag distribution for the just-scored threads and call `record_activity_event(db, "score", message, client_id, metadata)`.
- `generate_comments`: After the generation loop, call `record_activity_event(db, "generate", message, client_id, metadata)`.
- On exception in either task, create a `"system"` activity event.

#### `app/routes/review.py` — changes

After each status change (approve/reject/post), call `record_activity_event(db, "review", message, client_id, metadata)`.

### 4. Routes (additions to `app/routes/admin.py`)

```python
# Modified: admin_dashboard — add activity feed to context
@router.get("/", response_class=HTMLResponse)
def admin_dashboard(request, db, user):
    # ... existing stats ...
    events = transparency.get_activity_events(db, limit=50)
    return templates.TemplateResponse("admin_dashboard.html", {
        ..., "events": events
    })

# New: HTMX partial for activity feed (dashboard-level, optional client filter)
@router.get("/activity-feed", response_class=HTMLResponse)
def admin_activity_feed(request, db, user, client_id: str | None = None):
    events = transparency.get_activity_events(db, client_id=client_id, limit=50)
    return templates.TemplateResponse("partials/activity_feed.html", {
        "request": request, "events": events
    })

# New: Client Transparency Dashboard
@router.get("/clients/{client_id}/transparency", response_class=HTMLResponse)
def client_transparency(request, client_id: str, db, user):
    client = db.query(Client).filter(Client.id == client_id).first()
    stats = transparency.get_pipeline_stats(db, client_id)
    freshness = transparency.get_scrape_freshness(db, client_id)
    events = transparency.get_activity_events(db, client_id=client_id, limit=100)
    return templates.TemplateResponse("admin_client_transparency.html", {
        "request": request, "client": client, "stats": stats,
        "freshness": freshness, "events": events, "active_nav": "clients",
    })

# New: HTMX partial for client-scoped activity feed
@router.get("/clients/{client_id}/activity-feed", response_class=HTMLResponse)
def client_activity_feed(request, client_id: str, db, user):
    events = transparency.get_activity_events(db, client_id=client_id, limit=100)
    return templates.TemplateResponse("partials/activity_feed.html", {
        "request": request, "events": events
    })
```

### 5. Templates

#### `partials/activity_feed.html`

Reusable HTMX partial rendering a list of activity events. Each event shows:
- Relative timestamp (e.g., "2 min ago")
- Color-coded badge by `event_type`: scrape=blue, score=purple, generate=green, review=amber, system=red
- Message text

Empty state: "No activity yet. Run the pipeline to see events here."

#### `admin_dashboard.html` — modification

Add an Activity Feed section below the existing stats cards. Load via `hx-get="/admin/activity-feed"` with `hx-trigger="load"` for async loading.

Optional client filter dropdown that re-fetches the feed partial with `?client_id=...`.

#### `admin_client_transparency.html`

New full page extending `admin_base.html`. Sections:
1. **Header** with client name + link back to client detail
2. **Pipeline Statistics** — cards for thread counts (total, 24h, 7d)
3. **Tag Distribution** — engage/monitor/skip with counts and percentages
4. **Draft Status Breakdown** — pending/approved/rejected/posted counts
5. **AI Costs** — total + breakdown by operation
6. **Scrape Freshness** — table of subreddits with last_scraped_at, total posts, avg new posts, stale indicator
7. **Activity History** — client-scoped feed loaded via HTMX partial

#### `admin_client_detail.html` — modification

Add a "Transparency" link/button in the header area next to "Onboarding Wizard", pointing to `/admin/clients/{id}/transparency`.

### 6. Alembic Migration

Single migration file that:
1. Creates `activity_events` table
2. Creates `scrape_log` table with composite index
3. Adds `last_scraped_at` column to `client_subreddits`
4. Downgrade drops both tables and removes the column

### 7. Model Registration

Update `app/models/__init__.py` to import `ActivityEvent` and `ScrapeLog` so Alembic's `import *` picks them up.

## Data Models

### ActivityEvent Table

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK, default uuid4 | |
| client_id | UUID | FK clients.id, nullable | null = system-wide event |
| event_type | VARCHAR(50) | NOT NULL | "scrape", "score", "generate", "review", "system" |
| message | TEXT | NOT NULL | Human-readable summary |
| metadata | JSONB | nullable | Structured details |
| created_at | TIMESTAMPTZ | server_default=now() | |

**Index**: default PK index. Queries are by `created_at DESC` with optional `client_id` filter — the table is append-only and small enough that sequential scan on `created_at` is fine for the expected volume (hundreds of events/day). If volume grows, add `ix_activity_events_client_created` on `(client_id, created_at)`.

### ScrapeLog Table

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | UUID | PK, default uuid4 | |
| client_id | UUID | FK clients.id, NOT NULL | |
| subreddit_name | VARCHAR(255) | NOT NULL | |
| scraped_at | TIMESTAMPTZ | server_default=now() | |
| posts_found | INTEGER | NOT NULL | Total from Reddit API |
| posts_new | INTEGER | NOT NULL | After dedup |
| errors | TEXT | nullable | null on success |
| duration_ms | INTEGER | NOT NULL | Wall-clock time |

**Index**: `ix_scrape_log_client_sub_time` on `(client_id, subreddit_name, scraped_at)` for efficient per-subreddit freshness queries.

### ClientSubreddit — Column Addition

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| last_scraped_at | TIMESTAMPTZ | nullable | Updated after each successful scrape |

### Metadata JSONB Schemas

**Scrape event metadata:**
```json
{
  "subreddit_name": "meditation",
  "posts_found": 50,
  "posts_new": 12,
  "duration_ms": 3400
}
```

**Score event metadata:**
```json
{
  "threads_scored": 25,
  "engage": 5,
  "monitor": 12,
  "skip": 8
}
```

**Generate event metadata:**
```json
{
  "drafts_generated": 5
}
```

**Review event metadata:**
```json
{
  "draft_id": "uuid",
  "thread_title": "How to choose...",
  "action": "approved",
  "avatar_username": "zen_practitioner"
}
```

**System error event metadata:**
```json
{
  "error": "ConnectionError: Reddit API timeout",
  "task": "scrape_professional_subreddits",
  "subreddit_name": "meditation"
}
```


## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

The prework analysis identified 8 non-redundant properties after consolidation. Properties 1.3, 3.1, 3.4, 8.1, and 9.1 were merged into a single filter/ordering property. Properties 9.2 and 9.3 were removed as redundant with 7.2–7.5 and 7.6 respectively. Property 3.2 (feed rendering) was downgraded to example-based testing since it tests HTML output structure.

### Property 1: Activity event retrieval respects all filters and ordering

*For any* set of ActivityEvent records with varying `client_id`, `event_type`, and `created_at` values, and *for any* combination of filters (client_id, event_type, limit, offset), the `get_activity_events` function SHALL return only events matching all applied filters, in reverse chronological order, with the result size not exceeding the specified limit.

**Validates: Requirements 1.3, 3.1, 3.4, 8.1, 9.1**

### Property 2: Staleness detection is correct for any timestamp

*For any* `last_scraped_at` value (including `None`), the staleness check SHALL return `is_stale=True` if and only if the value is `None` or older than 24 hours from the current UTC time.

**Validates: Requirements 6.3**

### Property 3: Thread count temporal consistency

*For any* set of RedditThread records with varying `created_at` timestamps scoped to a client, the `get_pipeline_stats` function SHALL return thread counts where `total >= last_7d >= last_24h >= 0`.

**Validates: Requirements 7.2**

### Property 4: Tag distribution sums to scored total

*For any* set of RedditThread records with tags (engage, monitor, skip) scoped to a client, the sum of `tags["engage"] + tags["monitor"] + tags["skip"] + tags["unscored"]` SHALL equal the total thread count.

**Validates: Requirements 7.3**

### Property 5: Draft status breakdown sums to total

*For any* set of CommentDraft records with statuses (pending, approved, rejected, posted) scoped to a client, the sum of all status counts SHALL equal the total draft count for that client.

**Validates: Requirements 7.4**

### Property 6: AI cost aggregation consistency

*For any* set of AIUsageLog records scoped to a client, the total AI cost SHALL equal the sum of per-operation costs (scoring + generation + editing + any other operations).

**Validates: Requirements 7.5**

### Property 7: Scrape freshness aggregation correctness

*For any* set of ScrapeLog records for a given client and subreddit, the `total_posts_found` SHALL equal the sum of `posts_found` across all scrape runs, and `avg_posts_new` SHALL equal the arithmetic mean of `posts_new` across all scrape runs.

**Validates: Requirements 7.6, 9.3**

### Property 8: Service functions return plain dictionaries

*For any* call to `get_activity_events`, `get_pipeline_stats`, or `get_scrape_freshness`, every item in the returned result SHALL be a plain `dict` (or contain only plain `dict` values), not a SQLAlchemy model instance.

**Validates: Requirements 9.4**

## Error Handling

### Pipeline Instrumentation Errors

- **Activity event recording failure**: If `record_activity_event()` raises an exception (e.g., database connection lost), the calling task MUST catch the exception, log it, and continue. Activity event recording is observability — it must never cause a pipeline task to fail.
- **ScrapeLog recording failure**: Same principle — log and continue. The scraping task's primary job (saving RedditThread records) must not be blocked by a logging failure.
- **Partial scrape failure**: If scraping fails for one subreddit, the task already continues to the next (existing behavior). The new code adds a ScrapeLog record with `errors` field and an activity event with `event_type="system"` before continuing.

### Service Layer Errors

- **Missing client**: `get_pipeline_stats()` and `get_scrape_freshness()` return empty/zero-value dicts if the client_id doesn't exist. No exception raised.
- **Empty data**: All service functions handle the case where no records exist — return empty lists or zero counts. No special error state.

### Route Errors

- **Invalid client_id**: The transparency route returns 404 if the client doesn't exist, consistent with the existing `admin_client_detail` pattern.
- **Database errors**: Handled by the existing error middleware (`app/middleware/errors.py`), which returns a 500 page.

### Template Errors

- **Null values**: Templates use Jinja2's `default` filter and conditional rendering to handle null `last_scraped_at`, empty event lists, and zero counts gracefully.
- **Division by zero**: Tag distribution percentages use safe division (check for zero total before computing percentages).

## Testing Strategy

### Property-Based Tests (Hypothesis)

The project uses Python/pytest. We'll use **Hypothesis** for property-based testing, which is the standard PBT library for Python.

Each property test runs a minimum of **100 iterations** with randomly generated inputs.

**Tag format**: `# Feature: activity-feed-transparency, Property {N}: {title}`

Properties to implement as PBT:
1. **Activity event retrieval with filters** — generate random events, random filter combos, verify results match filters and ordering.
2. **Staleness detection** — generate random datetimes (past, recent, None), verify is_stale flag.
3. **Thread count temporal consistency** — generate random threads with random timestamps, verify total >= 7d >= 24h.
4. **Tag distribution invariant** — generate random threads with random tags, verify sum = total.
5. **Draft status breakdown invariant** — generate random drafts with random statuses, verify sum = total.
6. **AI cost aggregation** — generate random AIUsageLog records, verify total = sum of parts.
7. **Scrape freshness aggregation** — generate random ScrapeLog records, verify totals and averages.
8. **Service returns dicts** — generate random data, call service functions, verify return types.

### Unit Tests (pytest)

- **Model creation**: Verify ActivityEvent and ScrapeLog can be created with valid data.
- **Validation edge cases**: Empty event_type, empty message, null required fields.
- **Empty state rendering**: Activity feed with no events shows placeholder.
- **HTMX partial structure**: Dashboard contains hx-get for activity feed.
- **Relative time formatting**: Specific examples (1 min ago, 2 hours ago, 3 days ago).

### Integration Tests (pytest + TestClient)

- **Pipeline instrumentation**: Mock Reddit API and AI services, run scraping/scoring/generation tasks, verify ActivityEvent and ScrapeLog records are created.
- **Review instrumentation**: Approve/reject a draft via the review endpoint, verify ActivityEvent is created.
- **Transparency dashboard route**: GET `/admin/clients/{id}/transparency` returns 200 with correct template context.
- **Activity feed route**: GET `/admin/activity-feed` returns 200 with event data.
- **Client-scoped feed**: GET `/admin/clients/{id}/activity-feed` returns only events for that client.
- **Error resilience**: Verify that activity event recording failure doesn't crash the pipeline task.

### Test File Organization

```
tests/
├── test_transparency_service.py    # Unit + property tests for transparency.py
├── test_transparency_models.py     # Model creation and validation tests
├── test_transparency_routes.py     # Route integration tests
├── test_pipeline_instrumentation.py # Pipeline task instrumentation tests
```

### Regression

All new tests run alongside the existing 93 tests. The Alembic migration is applied before tests via the existing `setup_db` fixture (which calls `Base.metadata.create_all`). No existing tests should be modified.
