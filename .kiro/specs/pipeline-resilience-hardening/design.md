# Design Document

## Overview

This design addresses 6 resilience gaps in the Celery + Redis pipeline. The implementation follows a layered approach: infrastructure-level fixes (pool config, index), service-level patterns (circuit breaker, DLQ, session management), and scheduler-level recovery (catch-up mechanism). All changes are backward-compatible and can be deployed incrementally.

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        Celery Worker                             │
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │  AI Pipeline │───▶│ LLM Service  │───▶│ Circuit Breaker  │  │
│  │  (tasks/)    │    │ (ai.py)      │    │ (Redis state)    │  │
│  └──────┬───────┘    └──────────────┘    └──────────────────┘  │
│         │                                                        │
│         ▼                                                        │
│  ┌──────────────┐    ┌──────────────┐                           │
│  │ Session Mgr  │───▶│ Connection   │                           │
│  │ (per-op)     │    │ Pool (40max) │                           │
│  └──────────────┘    └──────┬───────┘                           │
│                              │                                   │
│  ┌──────────────┐           │         ┌──────────────────────┐  │
│  │ DLQ Service  │◀──────────┼────────▶│ PostgreSQL           │  │
│  │              │           │         │ (dead_letter_tasks)  │  │
│  └──────────────┘           │         └──────────────────────┘  │
│                              │                                   │
│  ┌──────────────┐           │                                   │
│  │ Scrape Dedup │───────────┘                                   │
│  │ (SQL EXISTS) │                                               │
│  └──────────────┘                                               │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Heartbeat Task (catch-up detection)                       │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Pool exhaustion path**: Task requests session → pool_timeout fires → `ConnectionPoolExhausted` raised → task retries with backoff
2. **DLQ path**: Task fails final retry → `task_failure` signal handler → DLQ service persists to `dead_letter_tasks` table
3. **Catch-up path**: Heartbeat (every 60s) → checks Redis timestamps → detects overdue → dispatches catch-up task
4. **Circuit breaker path**: LLM call → check breaker state → if open: raise immediately; if closed: call provider → on failure: increment counter → if threshold: open breaker
5. **Dedup path**: Scrape returns posts → SQL `NOT IN (SELECT reddit_native_id FROM reddit_threads WHERE subreddit_id = ?)` → only new posts returned
6. **Session-per-op path**: Load entities → close session → call LLM (60s) → re-open session → verify entities → save

## Components and Interfaces

### ConnectionPoolMonitor (`database.py`)

- **Purpose**: Monitors pool utilization and raises clear errors on exhaustion
- **Interface**:
  - `ConnectionPoolExhausted` exception with pool utilization details
  - SQLAlchemy `checkout` event listener for pressure logging

### DLQService (`services/dlq.py`)

- **Purpose**: Persists failed tasks after retry exhaustion for inspection and replay
- **Interface**:
  - `persist_failed_task(task_name, task_id, args, kwargs, exc, retry_count)` → persists to DB
  - `retry_task(dlq_entry_id)` → re-dispatches original task, marks entry as `retried`
  - `discard_task(dlq_entry_id)` → marks entry as `discarded`
  - `check_accumulation_alert()` → logs ERROR if >5 entries in 10 min

### BeatCatchupService (`services/beat_catchup.py`)

- **Purpose**: Detects missed scheduled pipeline runs and triggers catch-up
- **Interface**:
  - `check_and_dispatch(redis_client)` → called from heartbeat, dispatches overdue tasks
  - `record_success(task_name, redis_client)` → updates last success timestamp in Redis

### CircuitBreaker (`services/circuit_breaker.py`)

- **Purpose**: Stops calling degraded LLM providers after consecutive failures
- **Interface**:
  - `check()` → raises `CircuitBreakerOpen` if breaker is open
  - `record_success()` → closes breaker if half-open
  - `record_failure()` → opens breaker if threshold reached
  - `CircuitBreakerOpen` exception with model name and remaining cooldown

### ScrapeDedup (`services/scrape_dedup.py`)

- **Purpose**: Memory-efficient deduplication using SQL-level filtering
- **Interface**:
  - `get_new_post_ids(db, subreddit_id, scraped_native_ids)` → returns only new IDs not in DB

### Session-Per-Operation Pattern

- **Purpose**: Prevents DB connection holding during long LLM calls
- **Interface**: Pattern applied to AI tasks — load data (short session) → LLM call (no session) → save results (short session with optimistic check)

## Data Models

### DeadLetterTask (`models/dead_letter_task.py`)

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default uuid4 |
| task_name | VARCHAR(255) | NOT NULL, indexed |
| task_id | VARCHAR(255) | NOT NULL |
| task_args | JSONB | default [] |
| task_kwargs | JSONB | default {} |
| exception_type | VARCHAR(255) | nullable |
| exception_message | TEXT | nullable |
| exception_traceback | TEXT | nullable |
| retry_count | INTEGER | default 0 |
| status | VARCHAR(20) | default 'pending' (pending/retried/discarded) |
| failed_at | TIMESTAMPTZ | default now() |
| retried_at | TIMESTAMPTZ | nullable |
| created_at | TIMESTAMPTZ | default now() |

### New Index

```sql
CREATE INDEX ix_reddit_threads_subreddit_native_id 
ON reddit_threads (subreddit_id, reddit_native_id);
```

### Modified: `database.py` engine configuration

- `pool_timeout=30` added
- `max_overflow` changed from 10 to 20

### System Settings

| Key | Default | Description |
|-----|---------|-------------|
| `beat_catchup_enabled` | `true` | Enable/disable missed schedule catch-up |
| `circuit_breaker_threshold` | `3` | Consecutive failures before opening breaker |
| `circuit_breaker_cooldown_seconds` | `120` | Seconds to wait before probe call |

## Detailed Design

### 1. Connection Pool Configuration (`database.py`)

**Changes:**
- Add `pool_timeout=30` to `create_engine()`
- Increase `max_overflow` from 10 to 20 (total capacity: 40 connections)
- Add pool event listeners for utilization monitoring

```python
from sqlalchemy import event

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=20,      # was 10, now 20 (burst to 40 total)
    pool_recycle=1800,
    pool_timeout=30,      # NEW: fail fast instead of hanging
)

@event.listens_for(engine, "checkout")
def _on_checkout(dbapi_conn, connection_record, connection_proxy):
    pool = engine.pool
    checked_out = pool.checkedout()
    pool_size = pool.size()
    overflow = pool.overflow()
    if checked_out > (pool_size + overflow) * 0.8:
        logger.warning(
            "POOL_PRESSURE | checked_out=%d pool_size=%d overflow=%d max_overflow=%d",
            checked_out, pool_size, overflow, engine.pool._max_overflow,
        )
```

**Custom exception:**
```python
class ConnectionPoolExhausted(Exception):
    """Raised when pool_timeout expires waiting for a connection."""
    def __init__(self, pool_size, overflow, checked_out):
        self.pool_size = pool_size
        self.overflow = overflow
        self.checked_out = checked_out
        super().__init__(
            f"Connection pool exhausted: {checked_out}/{pool_size + overflow} connections in use"
        )
```

### 2. Dead Letter Queue (`services/dlq.py` + model)

**Model: `models/dead_letter_task.py`**
```python
class DeadLetterTask(Base):
    __tablename__ = "dead_letter_tasks"

    id = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    task_name = mapped_column(String(255), nullable=False, index=True)
    task_id = mapped_column(String(255), nullable=False)
    task_args = mapped_column(JSONB, default=list)
    task_kwargs = mapped_column(JSONB, default=dict)
    exception_type = mapped_column(String(255))
    exception_message = mapped_column(Text)
    exception_traceback = mapped_column(Text)
    retry_count = mapped_column(Integer, default=0)
    status = mapped_column(String(20), default="pending")  # pending, retried, discarded
    failed_at = mapped_column(DateTime(timezone=True), default=func.now())
    retried_at = mapped_column(DateTime(timezone=True), nullable=True)
    created_at = mapped_column(DateTime(timezone=True), default=func.now())
```

**Service: `services/dlq.py`**
```python
class DLQService:
    def persist_failed_task(self, task_name, task_id, args, kwargs, exc, retry_count):
        """Persist a failed task to the DLQ table."""
        
    def retry_task(self, dlq_entry_id):
        """Re-dispatch original task and mark entry as retried."""
        
    def discard_task(self, dlq_entry_id):
        """Mark entry as discarded."""
        
    def check_accumulation_alert(self):
        """Alert if >5 entries in 10 min window."""
```

**Integration via Celery signal:**
```python
from celery.signals import task_failure

@task_failure.connect
def handle_task_failure(sender, task_id, exception, args, kwargs, traceback, einfo, **kw):
    """Capture permanently failed tasks into DLQ."""
    # Only capture if max_retries exhausted
    if hasattr(sender, 'request') and sender.request.retries >= sender.max_retries:
        dlq_service.persist_failed_task(...)
```

### 3. Beat Catch-Up Mechanism (`services/beat_catchup.py`)

**Design:**
- Integrated into the existing `system_heartbeat` task (runs every 60s)
- Tracks last successful execution per task in Redis
- Detects overdue tasks based on expected schedule
- Dispatches catch-up with deduplication (max 1 per 4h window)

```python
CATCHUP_TASKS = {
    "run_full_pipeline_all_clients": {
        "schedule_hours": [8, 14],  # Expected at 08:00 and 14:00
        "max_overdue_hours": 2,     # Trigger catch-up after 2h overdue
        "cooldown_hours": 4,        # Min 4h between catch-ups
    },
    "run_hobby_pipeline_all_avatars": {
        "schedule_hours": [10],
        "max_overdue_hours": 2,
        "cooldown_hours": 4,
    },
}

class BeatCatchupService:
    REDIS_PREFIX = "beat_catchup:"
    
    def check_and_dispatch(self, redis_client):
        """Called from heartbeat. Checks all catchup-eligible tasks."""
        
    def record_success(self, task_name, redis_client):
        """Called after successful task completion."""
        
    def _is_overdue(self, task_name, config, now):
        """Check if task is overdue based on schedule."""
        
    def _can_dispatch(self, task_name, config, redis_client):
        """Check cooldown window."""
```

### 4. LLM Circuit Breaker (`services/circuit_breaker.py`)

**State machine:**
```
CLOSED ──(3 failures in 5min)──▶ OPEN ──(cooldown expires)──▶ HALF_OPEN
   ▲                                                              │
   │                                                              │
   └──────────────(probe succeeds)────────────────────────────────┘
   
HALF_OPEN ──(probe fails)──▶ OPEN
```

**Redis keys:**
- `circuit_breaker:{model}:failures` — sorted set of failure timestamps
- `circuit_breaker:{model}:state` — "closed" | "open" | "half_open"
- `circuit_breaker:{model}:opened_at` — timestamp when breaker opened

```python
class CircuitBreaker:
    def __init__(self, redis_client, model: str, threshold: int = 3, 
                 cooldown_seconds: int = 120, window_seconds: int = 300):
        ...
    
    def check(self) -> None:
        """Raise CircuitBreakerOpen if breaker is open."""
        
    def record_success(self) -> None:
        """Record successful call. Close breaker if half-open."""
        
    def record_failure(self) -> None:
        """Record failure. Open breaker if threshold reached."""

class CircuitBreakerOpen(Exception):
    def __init__(self, model: str, remaining_seconds: int):
        super().__init__(f"Circuit breaker open for {model}, retry in {remaining_seconds}s")
        self.model = model
        self.remaining_seconds = remaining_seconds
```

**Integration in `ai.py`:**
```python
def call_llm(messages, model, ...):
    breaker = CircuitBreaker(redis_client, model)
    breaker.check()  # Raises CircuitBreakerOpen if open
    try:
        response = litellm.completion(**kwargs)
        breaker.record_success()
        return response
    except (Timeout, ConnectionError) as e:
        breaker.record_failure()
        raise
```

**Integration in `generate_comments`:**
```python
for thread in engage_threads:
    try:
        draft = generate_comment(...)
    except CircuitBreakerOpen as e:
        logger.warning("Circuit breaker open for %s, skipping thread %s", e.model, thread.id)
        continue  # Skip this thread, try next
```

### 5. Memory-Efficient Deduplication

**Current (problematic):**
```python
existing_ids = set(
    row[0] for row in db.query(RedditThread.reddit_native_id).all()
)
```

**New approach — SQL-level filtering:**
```python
def get_new_posts(db: Session, subreddit_id: UUID, scraped_native_ids: list[str]) -> list[str]:
    """Return only native_ids not already in DB for this subreddit.
    
    Uses SQL NOT IN with subreddit scope. For batches >100, uses
    chunked queries to stay within PostgreSQL parameter limits.
    """
    if not scraped_native_ids:
        return []
    
    # Chunk into batches of 100 for parameter limit safety
    new_ids = []
    for chunk in _chunks(scraped_native_ids, 100):
        existing = set(
            row[0] for row in db.query(RedditThread.reddit_native_id)
            .filter(
                RedditThread.subreddit_id == subreddit_id,
                RedditThread.reddit_native_id.in_(chunk),
            )
            .all()
        )
        new_ids.extend(nid for nid in chunk if nid not in existing)
    
    return new_ids
```

**Index migration:**
```sql
CREATE INDEX ix_reddit_threads_subreddit_native_id 
ON reddit_threads (subreddit_id, reddit_native_id);
```

### 6. Session-Per-Operation Pattern for AI Tasks

**Pattern for LLM-calling tasks:**
```python
def generate_comment_resilient(thread_id, client_id, avatar_id):
    # Phase 1: Load data (short session)
    db = SessionLocal()
    try:
        thread = db.query(RedditThread).get(thread_id)
        client = db.query(Client).get(client_id)
        avatar = db.query(Avatar).get(avatar_id)
        # Extract all needed data into plain dicts/dataclasses
        thread_data = ThreadContext(id=thread.id, title=thread.post_title, ...)
        client_data = ClientContext(id=client.id, keywords=client.keywords, ...)
        avatar_data = AvatarContext(id=avatar.id, voice=avatar.voice_profile, ...)
    finally:
        db.close()
    
    # Phase 2: LLM call (no DB session held — can take 60s)
    result = call_llm(messages=[...])
    
    # Phase 3: Save results (short session, optimistic check)
    db = SessionLocal()
    try:
        # Verify entities still valid
        thread = db.query(RedditThread).get(thread_data.id)
        if not thread or thread.is_locked:
            logger.info("Thread %s no longer valid, skipping save", thread_data.id)
            return None
        
        draft = CommentDraft(thread_id=thread.id, ...)
        db.add(draft)
        db.commit()
        return draft
    finally:
        db.close()
```

## Error Handling

| Error | Source | Handling |
|-------|--------|----------|
| `ConnectionPoolExhausted` | Pool timeout | Retry with backoff (60×2^n) |
| `CircuitBreakerOpen` | LLM call attempt | Skip current thread, continue loop |
| `sqlalchemy.exc.TimeoutError` | Pool timeout (raw) | Wrapped into ConnectionPoolExhausted |
| DLQ persistence failure | DB unavailable | Fallback to ERROR-level logging |
| Catch-up dispatch failure | Redis/Celery error | Log warning, skip this tick |

## Testing Strategy

- **Circuit breaker**: Property-based tests for state transitions (closed→open→half_open→closed)
- **DLQ**: Property-based tests for persist/retry/discard lifecycle
- **Deduplication**: Property-based tests verifying bounded memory and correctness (no false positives/negatives)
- **Pool config**: Integration test verifying timeout behavior
- **Catch-up**: Unit tests with mocked time for schedule detection

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Circuit breaker state machine validity

*For all* sequences of success/failure calls, the breaker state transitions are valid (closed→open→half_open→closed, never closed→half_open directly)

**Validates: Requirements 4.1, 4.3, 4.4, 4.5**

### Property 2: DLQ completeness

*For all* tasks that exhaust retries, the task metadata is persisted to DLQ (no silent loss)

**Validates: Requirements 2.1, 2.7**

### Property 3: DLQ idempotency

*For any* DLQ entry, retrying it dispatches exactly one new task regardless of how many times retry_task is called

**Validates: Requirements 2.3**

### Property 4: Deduplication correctness

*For all* sets of scraped posts, the deduplication returns exactly the posts whose `reddit_native_id` is not in the database for that subreddit

**Validates: Requirements 5.1, 5.2, 5.4**

### Property 5: Deduplication memory bound

*For all* deduplication operations, Python heap growth is O(batch_size) not O(total_threads)

**Validates: Requirements 5.6**

### Property 6: Catch-up at-most-once

*For all* sequences of heartbeat ticks, at most one catch-up is dispatched per task per 4-hour window

**Validates: Requirements 3.4**

### Property 7: Pool timeout determinism

*For any* state where the pool is exhausted, tasks fail within pool_timeout + 1s (no indefinite hangs)

**Validates: Requirements 1.1, 1.2**

### Property 8: Session-per-op consistency

*For any* session-per-operation execution, after re-acquiring session, if entity state changed, the operation is safely skipped (no stale writes)

**Validates: Requirements 6.4, 6.5**

