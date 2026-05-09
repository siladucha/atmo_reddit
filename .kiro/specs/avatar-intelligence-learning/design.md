# Design Document: Avatar Intelligence & Learning — Subreddit Presence Map (Phase 1)

## Overview

This design covers the **Avatar Subreddit Presence Map** (Requirement 11) as the first deliverable of the Avatar Intelligence & Learning system. The feature adds a "Subreddit Presence" section to the existing avatar detail page (`/admin/avatars/{id}`) showing all subreddits where an avatar has commented, with per-subreddit metrics.

**Scope (Phase 1 — First Sprint):**
- New `avatar_subreddit_presence` database table
- Service layer for scanning Reddit comment history and aggregating by subreddit
- API endpoints: trigger scan, get presence data, HTMX partial refresh
- UI component on the avatar detail page (new tab or section in Overview)
- Background task integration (manual scan via Celery, weekly auto-update)
- Rate limiting integration (scan goes through existing Reddit API patterns)

**Design Rationale:**
- Reuses existing `SubredditKarma` model concept but creates a dedicated table for presence data (separation of concerns — karma tracking vs. presence mapping have different update frequencies and data sources)
- Leverages existing PRAW integration in `app/services/reddit.py`
- Uses Celery task (existing worker infrastructure) for async scan
- HTMX partial pattern matches existing admin panel conventions

## Architecture

```mermaid
graph TD
    A[Avatar Detail Page] -->|Click Scan| B[POST /admin/avatars/{id}/scan-presence]
    B -->|Creates Celery Task| C[scan_avatar_presence Task]
    C -->|PRAW: redditor.comments.new| D[Reddit API]
    D -->|Comment List| C
    C -->|Aggregate by Subreddit| E[avatar_subreddit_presence Table]
    E -->|HTMX GET| F[GET /admin/avatars/{id}/presence-partial]
    F -->|Render| A

    G[Weekly Scheduler] -->|Celery Beat| H[scan_all_avatars_presence Task]
    H -->|For each active avatar| C

    style A fill:#1e293b,stroke:#6366f1
    style C fill:#1e293b,stroke:#22c55e
    style E fill:#1e293b,stroke:#f59e0b
```

**Key architectural decisions:**

1. **Dedicated table vs. reusing SubredditKarma**: The existing `SubredditKarma` model tracks karma from internally-tracked comment performance. Subreddit Presence tracks data fetched directly from Reddit's comment history API. Different data sources, different update cadences, different purposes. Separate table avoids coupling.

2. **Celery task (not inline PRAW call)**: The existing "Refresh Reddit Data" button does a synchronous PRAW call, which blocks the request. For presence scanning (fetching up to 100 comments), we use an async Celery task to avoid blocking the UI. The HTMX polling pattern handles the async completion.

3. **New tab vs. section in Overview**: Adding a new "Presence" tab to the avatar detail page. The Overview tab is already dense with client assignment, health, and phase data. A dedicated tab keeps it clean and allows future expansion (e.g., presence heatmap, trend charts).

## Components and Interfaces

### 1. Database Model — `AvatarSubredditPresence`

**File:** `app/models/avatar_subreddit_presence.py`

```python
class AvatarSubredditPresence(Base):
    __tablename__ = "avatar_subreddit_presence"

    id: UUID (PK)
    avatar_id: UUID (FK → avatars.id, CASCADE)
    subreddit_name: str (max 255)
    comment_count: int (default 0)
    total_karma: int (default 0)
    avg_karma: float (computed as total_karma / comment_count)
    last_activity_at: datetime (timezone-aware)
    created_at: datetime (server_default=now)
    updated_at: datetime (server_default=now, onupdate=now)

    # Unique constraint: (avatar_id, subreddit_name)
    # Index: avatar_id (for fast lookup of all presence records for an avatar)
```

**Avatar-level metadata** (added to `Avatar` model or separate):
```python
# On Avatar model (new columns):
presence_last_scanned_at: datetime | None  # When presence was last refreshed
presence_scan_status: str | None  # "pending" | "running" | "completed" | "failed" | None
```

### 2. Service Layer — `app/services/presence.py`

```python
def scan_avatar_presence(db: Session, avatar_id: UUID) -> list[AvatarSubredditPresence]:
    """Fetch avatar's recent comments from Reddit, aggregate by subreddit, upsert presence records."""

def get_avatar_presence(db: Session, avatar_id: UUID, sort_by: str = "comment_count") -> list[AvatarSubredditPresence]:
    """Query presence records for an avatar, sorted by the specified field."""

def aggregate_comments_by_subreddit(comments: list[dict]) -> list[dict]:
    """Pure function: group raw comments by subreddit, compute count/karma/last_activity."""

def is_presence_stale(last_scanned_at: datetime | None) -> bool:
    """Return True if presence data is older than 7 days or never scanned."""
```

### 3. Celery Task — `app/tasks/presence.py`

```python
@celery_app.task(name="scan_avatar_presence")
def scan_avatar_presence_task(avatar_id: str) -> dict:
    """Async task: fetch comments via PRAW, aggregate, persist."""

@celery_app.task(name="scan_all_avatars_presence")
def scan_all_avatars_presence_task() -> dict:
    """Weekly scheduled task: scan presence for all active avatars."""
```

### 4. API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/admin/avatars/{id}/scan-presence` | Trigger manual presence scan (creates Celery task) |
| GET | `/admin/avatars/{id}/presence-partial` | HTMX partial: renders presence table + status |
| GET | `/admin/avatars/{id}/presence-data` | JSON API: returns presence records (for future use) |

### 5. UI Component — HTMX Partial

**File:** `app/templates/partials/avatar_presence.html`

Renders:
- Presence table (subreddit name, comment count, avg karma, last activity, Reddit link)
- Sort controls (comment count / avg karma / last activity)
- "Scan Subreddit Presence" button (triggers POST, shows spinner)
- "Last updated" timestamp with stale indicator (>7 days = amber badge)
- Empty state with "Scan Now" CTA when no data exists
- Task status indicator (pending/running) with auto-poll via `hx-trigger="every 3s"`

### 6. PRAW Integration

The scan uses the existing `get_reddit_client()` from `app/services/reddit.py`:

```python
reddit = get_reddit_client()
redditor = reddit.redditor(avatar.reddit_username)
comments = redditor.comments.new(limit=100)
```

This is 1 API call (paginated listing, Reddit returns up to 100 in one request). At 20 avatars weekly, that's 20 calls/week — trivial against the 55 req/min rate limit.

## Data Models

### `avatar_subreddit_presence` Table

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK, default uuid4 | Row identifier |
| avatar_id | UUID | FK(avatars.id) CASCADE, NOT NULL | Which avatar |
| subreddit_name | VARCHAR(255) | NOT NULL | Subreddit display name (no r/ prefix) |
| comment_count | INTEGER | NOT NULL, default 0 | Total comments in this subreddit |
| total_karma | INTEGER | NOT NULL, default 0 | Sum of karma across all comments |
| last_activity_at | TIMESTAMPTZ | NULL | Most recent comment timestamp |
| created_at | TIMESTAMPTZ | NOT NULL, server_default=now | Row creation |
| updated_at | TIMESTAMPTZ | NOT NULL, server_default=now | Last upsert |

**Constraints:**
- `UNIQUE(avatar_id, subreddit_name)` — one row per avatar per subreddit
- `INDEX(avatar_id)` — fast lookup for avatar detail page

**Avatar model additions:**

| Column | Type | Description |
|--------|------|-------------|
| presence_last_scanned_at | TIMESTAMPTZ, NULL | When presence was last refreshed |
| presence_scan_status | VARCHAR(20), NULL | Current scan status |

### Alembic Migration

Single migration adding:
1. `avatar_subreddit_presence` table
2. Two columns on `avatars` table: `presence_last_scanned_at`, `presence_scan_status`

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Presence record contains all required fields

*For any* valid `AvatarSubredditPresence` record, serializing it for display SHALL produce output containing: subreddit name, comment count, average karma (total_karma / comment_count), last activity date, and a Reddit link (`https://reddit.com/r/{subreddit_name}`).

**Validates: Requirements 11.2**

### Property 2: Presence list sorting is correct

*For any* list of `AvatarSubredditPresence` records and any valid sort key (`comment_count`, `avg_karma`, `last_activity_at`), the service layer SHALL return records ordered by that key in descending order.

**Validates: Requirements 11.3**

### Property 3: Comment aggregation produces correct subreddit distribution

*For any* list of Reddit comments (each with a subreddit name, karma score, and timestamp), the `aggregate_comments_by_subreddit` function SHALL produce one entry per unique subreddit where: `comment_count` equals the number of comments in that subreddit, `total_karma` equals the sum of karma scores for that subreddit, and `last_activity_at` equals the maximum timestamp for that subreddit.

**Validates: Requirements 11.4**

### Property 4: Staleness detection respects 7-day threshold

*For any* timestamp, `is_presence_stale` SHALL return `True` if and only if the timestamp is more than 7 days before the current time, or if the timestamp is `None`.

**Validates: Requirements 11.9**

## Error Handling

| Scenario | Handling |
|----------|----------|
| Reddit API rate limit (429) | Celery task retries with exponential backoff (max 3 retries, 60s × 2^attempt) |
| Avatar account suspended/private | Task marks scan as "failed", logs error, does NOT clear existing presence data |
| PRAW timeout | Task retries once after 30s |
| Avatar not found in DB | Return 404 from endpoint |
| Scan already running | Return existing task status (idempotent — don't create duplicate task) |
| Empty comment history | Store empty presence (0 records), set `presence_last_scanned_at` to now |
| Database write failure | Task fails, DLQ captures it, existing data preserved |

**Idempotency:** The scan endpoint checks `presence_scan_status`. If already "pending" or "running", it returns the current status without creating a new task. This prevents duplicate scans from rapid button clicks.

## Testing Strategy

### Property-Based Tests (Hypothesis)

The feature has pure logic suitable for property-based testing:

- **`aggregate_comments_by_subreddit`** — pure function, input varies meaningfully (different subreddit distributions, karma values, timestamps)
- **Sorting logic** — universal property across all valid record sets
- **Staleness check** — pure function with clear threshold behavior
- **Serialization** — field presence is a universal property

**Configuration:**
- Library: `hypothesis` (already in project — `.hypothesis/` directory exists)
- Minimum 100 iterations per property test
- Tag format: `Feature: avatar-intelligence-learning, Property {N}: {title}`

### Unit Tests (pytest)

- Service layer: `scan_avatar_presence` with mocked PRAW (verify DB writes)
- Empty state handling (no comments → empty presence)
- Upsert behavior (second scan updates existing records, doesn't duplicate)
- Stale indicator logic (boundary: exactly 7 days)

### Integration Tests

- Full scan flow: trigger endpoint → task executes → DB updated → partial renders
- HTMX partial returns correct HTML structure
- Celery task retry on simulated rate limit
- Weekly scheduler triggers scan for all active avatars

### What's NOT property-tested

- HTMX refresh mechanism (UI integration)
- Celery task dispatch/completion (infrastructure wiring)
- Reddit API behavior (external service)
- Template rendering (snapshot/visual testing territory)
