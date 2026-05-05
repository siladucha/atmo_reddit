# Design Document: Reddit API Health Dashboard

## Overview

Фича расширяет существующую страницу System Health (`/admin/health`) набором виджетов для мониторинга Reddit API и LLM API в реальном времени. Архитектура строится на двух источниках данных:

1. **In-memory MetricsCollector** — перехватывает структурированные лог-события (`REDDIT_API_CALL`, `REDDIT_API_RESULT`, `REDDIT_API_ERROR`, `LLM_CALL`, `LLM_RESULT`) через кастомный `logging.Handler`, агрегирует их в скользящем окне (по умолчанию 60 минут). Работает в том же процессе, где генерируются события — то есть в FastAPI-процессе для rate limit данных и в Celery-воркерах для scrape/LLM метрик.

2. **Database queries** — для scrape freshness данных используются существующие таблицы `client_subreddits` (поле `last_scraped_at`) и `scrape_log`. Для исторических LLM-метрик — таблица `ai_usage_log`.

**Ключевое архитектурное решение**: Celery-воркеры работают в отдельных процессах, поэтому in-memory коллектор FastAPI-процесса не видит события из воркеров. Вместо сложной межпроцессной синхронизации:
- Rate limit данные PRAW доступны только в процессе, который делает Reddit API вызовы. Если scraping идёт через Celery — rate limit gauge покажет "No data" (что корректно, т.к. FastAPI-процесс не делает scrape-вызовы).
- Reddit API метрики (call count, errors, latency) агрегируются из `scrape_log` таблицы в БД — это даёт полную картину по всем процессам.
- LLM метрики агрегируются из `ai_usage_log` таблицы в БД.
- In-memory коллектор используется как дополнительный источник для real-time rate limit данных в FastAPI-процессе (например, при health check вызовах Reddit API).

Виджеты обновляются через HTMX polling с разной частотой (30s для rate limit, 30s для Reddit metrics, 60s для LLM, 120s для scrape freshness).

## Architecture

```mermaid
graph TB
    subgraph FastAPI Process
        LH[Logging Handler] -->|intercepts| MC[MetricsCollector]
        MC -->|rate limit state| RE[Route Endpoints]
        DB[(PostgreSQL)] -->|scrape_log, ai_usage_log| RE
        RE -->|HTML partials| HT[HTMX Widgets]
        RE -->|JSON| API[/admin/health/metrics]
    end

    subgraph Celery Workers
        CW[Worker Process] -->|writes| DB
        CW -->|structured logs| LOG[Log Files]
    end

    subgraph Admin Browser
        HP[Health Page] -->|hx-get polling| HT
        HP -->|initial load| RE
    end
```

### Data Flow

1. **Reddit API rate limit** (in-memory path):
   - `reddit.py` → `_log_rate_limit()` → logger.info("Reddit rate limit status | ...")
   - `MetricsLoggingHandler` перехватывает лог → парсит → обновляет `MetricsCollector.rate_limit_state`
   - Widget endpoint читает `MetricsCollector.get_rate_limit()` → рендерит partial

2. **Reddit API metrics** (DB path):
   - `scrape_log` таблица уже содержит `duration_ms`, `posts_found`, `posts_new`, `errors` для каждого scrape
   - Widget endpoint делает SQL-агрегацию за последние N минут → рендерит partial

3. **LLM API metrics** (DB path):
   - `ai_usage_log` таблица содержит `model`, `cost_usd`, `duration_ms`, `input_tokens`, `output_tokens`
   - Widget endpoint делает SQL-агрегацию за последние N минут → рендерит partial

4. **Scrape freshness** (DB path):
   - `client_subreddits.last_scraped_at` + `scrape_log` агрегация
   - Используется существующая функция `transparency.get_scrape_freshness()` с расширением для all-clients


## Components and Interfaces

### 1. MetricsCollector (`app/services/metrics_collector.py`)

Thread-safe singleton, хранящий in-memory rate limit state. Основная роль — перехват rate limit данных из логов PRAW в FastAPI-процессе.

```python
class RateLimitState:
    """Snapshot of Reddit API rate limit."""
    remaining: int | None    # requests remaining
    used: int | None         # requests used
    reset_timestamp: float | None  # UNIX timestamp of reset
    captured_at: datetime    # when this was captured
    status: str              # "ok" | "warning" | "critical" | "unknown"

class MetricsCollector:
    """Thread-safe in-memory rate limit tracker."""
    
    def __init__(self, window_minutes: int = 60):
        self._lock: threading.Lock
        self._rate_limit: RateLimitState | None
        self._window_minutes: int
    
    def record_rate_limit(self, remaining: int, used: int, reset_ts: float) -> None:
        """Record a rate limit snapshot. Thread-safe."""
    
    def get_rate_limit(self) -> RateLimitState:
        """Return current rate limit state. Returns 'unknown' if no data."""
    
    def get_window_minutes(self) -> int:
        """Return the configured time window in minutes."""
```

### 2. MetricsLoggingHandler (`app/services/metrics_collector.py`)

Кастомный `logging.Handler`, который перехватывает структурированные лог-сообщения и передаёт данные в `MetricsCollector`.

```python
class MetricsLoggingHandler(logging.Handler):
    """Intercepts structured log messages and feeds MetricsCollector."""
    
    def __init__(self, collector: MetricsCollector):
        self.collector = collector
    
    def emit(self, record: logging.LogRecord) -> None:
        """Parse log message and route to collector."""
        msg = record.getMessage()
        if "Reddit rate limit status" in msg:
            # Parse: remaining=X | used=Y | reset_ts=Z
            self.collector.record_rate_limit(remaining, used, reset_ts)
```

### 3. Health Metrics Service (`app/services/health_metrics.py`)

Сервисный слой, агрегирующий метрики из БД для dashboard виджетов.

```python
def get_reddit_api_metrics(db: Session, window_minutes: int = 60) -> dict:
    """Aggregate Reddit API metrics from scrape_log table.
    
    Returns:
        {
            "total_calls": int,
            "error_count": int,
            "error_rate_pct": float,
            "avg_response_ms": float,
            "p95_response_ms": float,
            "calls_per_minute": float,
            "errors_by_type": {"timeout": int, "forbidden": int, "rate_limited": int, "other": int},
            "status": "ok" | "warning" | "critical",
            "window_minutes": int,
        }
    """

def get_llm_api_metrics(db: Session, window_minutes: int = 60) -> dict:
    """Aggregate LLM API metrics from ai_usage_log table.
    
    Returns:
        {
            "total_calls": int,
            "total_cost_usd": float,
            "avg_latency_ms": float,
            "error_count": int,
            "by_model": [{"model": str, "calls": int, "cost_usd": float}],
            "status": "ok" | "warning" | "critical",
            "window_minutes": int,
        }
    """

def get_all_scrape_freshness(db: Session) -> dict:
    """Scrape freshness across ALL clients (not per-client).
    
    Returns:
        {
            "subreddits": [
                {
                    "subreddit_name": str,
                    "client_name": str,
                    "last_scraped_at": datetime | None,
                    "is_stale": bool,
                    "is_never_scraped": bool,
                }
            ],
            "total_active": int,
            "stale_count": int,
            "never_scraped_count": int,
        }
    """

def get_metrics_snapshot(db: Session, collector: MetricsCollector) -> dict:
    """Full metrics snapshot for JSON API endpoint.
    
    Combines rate limit state + Reddit API metrics + LLM metrics.
    Returns dict with collected_at ISO timestamp and window_minutes.
    """
```

### 4. Route Endpoints (`app/routes/admin.py`)

Новые endpoints в существующем admin router:

| Endpoint | Method | Returns | Auth | Polling |
|---|---|---|---|---|
| `/admin/health` | GET | Full page (enhanced) | superuser | — |
| `/admin/health/metrics` | GET | JSON snapshot | superuser | — |
| `/admin/health/widget/rate-limit` | GET | HTML partial | superuser | 30s |
| `/admin/health/widget/reddit-metrics` | GET | HTML partial | superuser | 30s |
| `/admin/health/widget/llm-metrics` | GET | HTML partial | superuser | 60s |
| `/admin/health/widget/scrape-freshness` | GET | HTML partial | superuser | 120s |

### 5. Templates

| Template | Description |
|---|---|
| `admin_health.html` | Enhanced — добавляет секцию API Metrics с 4 виджетами |
| `partials/health_rate_limit.html` | Rate limit gauge partial |
| `partials/health_reddit_metrics.html` | Reddit API metrics partial |
| `partials/health_llm_metrics.html` | LLM API metrics partial |
| `partials/health_scrape_freshness.html` | Scrape freshness table partial |

### 6. Initialization (`app/main.py`)

При старте FastAPI-приложения:
1. Создаётся singleton `MetricsCollector(window_minutes=60)`
2. Создаётся `MetricsLoggingHandler(collector)` и добавляется к root logger
3. Collector сохраняется в `app.state.metrics_collector` для доступа из route handlers

## Data Models

### Existing Models (no changes needed)

**ScrapeLog** — используется для Reddit API метрик:
- `duration_ms: int` — время выполнения scrape
- `posts_found: int` — найдено постов
- `posts_new: int` — новых постов
- `errors: str | None` — текст ошибки (если была)
- `scraped_at: datetime` — время scrape
- `subreddit_name: str` — имя сабреддита
- `client_id: UUID` — клиент

**AIUsageLog** — используется для LLM метрик:
- `model: str` — имя модели
- `cost_usd: Decimal` — стоимость вызова
- `duration_ms: int` — латентность
- `input_tokens: int` — входные токены
- `output_tokens: int` — выходные токены
- `operation: str` — тип операции (scoring, generation, etc.)
- `created_at: datetime` — время вызова

**ClientSubreddit** — используется для scrape freshness:
- `last_scraped_at: datetime | None` — время последнего scrape
- `is_active: bool` — активен ли сабреддит
- `subreddit_name: str` — имя

### New In-Memory Models (no DB migration)

**RateLimitState** — dataclass для хранения rate limit snapshot:
```python
@dataclass
class RateLimitState:
    remaining: int | None = None
    used: int | None = None
    reset_timestamp: float | None = None
    captured_at: datetime | None = None
    
    @property
    def status(self) -> str:
        if self.remaining is None:
            return "unknown"
        if self.remaining < 5:
            return "critical"
        if self.remaining < 20:
            return "warning"
        return "ok"
    
    @property
    def usage_pct(self) -> float | None:
        if self.used is None or self.remaining is None:
            return None
        total = self.used + self.remaining
        if total == 0:
            return 0.0
        return (self.used / total) * 100
```

### Status Indicator Thresholds

| Widget | Green | Yellow | Red |
|---|---|---|---|
| Rate Limit Gauge | usage < 60% | 60% ≤ usage ≤ 80% | usage > 80% |
| Reddit API Error Rate | error_rate < 5% | 5% ≤ error_rate ≤ 20% | error_rate > 20% |
| Reddit API Latency | avg < 3000ms | avg ≥ 3000ms | — |
| LLM Latency | avg < 5000ms | avg ≥ 5000ms | — |
| LLM Errors | errors = 0 | errors > 0 | — |
| Scrape Freshness | scraped < 24h | scraped ≥ 24h | never scraped |


## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Rate limit log parsing round-trip

*For any* valid tuple of (remaining: int 0–1000, used: int 0–1000, reset_ts: float), formatting it into the structured log message `"Reddit rate limit status | remaining={remaining} | used={used} | reset_ts={reset_ts}"` and then parsing that message with `MetricsLoggingHandler` should result in a `RateLimitState` where `state.remaining == remaining`, `state.used == used`, and `state.reset_timestamp == reset_ts`.

**Validates: Requirements 2.1**

### Property 2: Rate limit status classification

*For any* integer `remaining` in the range [0, 1000], the `RateLimitState.status` property should return:
- `"critical"` if remaining < 5
- `"warning"` if 5 ≤ remaining < 20
- `"ok"` if remaining ≥ 20

And for `remaining = None`, status should be `"unknown"`. These categories are mutually exclusive and exhaustive.

**Validates: Requirements 2.3, 2.4, 2.5**

### Property 3: Rate limit gauge color classification

*For any* valid `usage_pct` (float 0.0–100.0), the gauge color classification should return:
- `"green"` if usage_pct < 60
- `"yellow"` if 60 ≤ usage_pct ≤ 80
- `"red"` if usage_pct > 80

And for `usage_pct = None` (unknown state), the classification should be `"gray"`.

**Validates: Requirements 5.2, 5.3, 5.4, 5.6**

### Property 4: Reddit API metrics internal consistency

*For any* set of scrape_log entries with known `duration_ms` and `errors` values within a time window, the aggregated metrics should satisfy:
- `error_rate_pct == (error_count / total_calls) * 100` (when total_calls > 0)
- `error_rate_pct == 0` when total_calls == 0
- `calls_per_minute == total_calls / elapsed_minutes` (when elapsed_minutes > 0)
- `error_count ≤ total_calls`

**Validates: Requirements 3.1, 3.2, 3.3, 3.6**

### Property 5: Response time statistics ordering invariant

*For any* non-empty list of positive integer `duration_ms` values, the computed statistics should satisfy:
- `min(values) ≤ avg_response_ms ≤ max(values)`
- `avg_response_ms ≤ p95_response_ms`
- `p95_response_ms ≤ max(values)`

**Validates: Requirements 3.4, 3.5**

### Property 6: Error breakdown sums to total

*For any* set of scrape_log entries with errors, the sum of `errors_by_type["rate_limited"] + errors_by_type["forbidden"] + errors_by_type["timeout"] + errors_by_type["other"]` should equal `error_count`.

**Validates: Requirements 3.7**

### Property 7: LLM per-model breakdown sums to totals

*For any* set of ai_usage_log entries within a time window, `sum(by_model[i].calls) == total_calls` and `sum(by_model[i].cost_usd) == total_cost_usd` (within floating-point tolerance).

**Validates: Requirements 4.1, 4.2, 4.5**

### Property 8: Reddit API widget status classification

*For any* `error_rate_pct` (float 0–100) and `avg_response_ms` (float ≥ 0), the Reddit API widget status should be the worst of:
- `"critical"` if error_rate > 20%
- `"warning"` if error_rate > 5% OR avg_response_ms > 3000
- `"ok"` otherwise

The status should always reflect the most severe condition.

**Validates: Requirements 6.3, 6.4, 6.5**

### Property 9: LLM widget status classification

*For any* `avg_latency_ms` (float ≥ 0) and `error_count` (int ≥ 0), the LLM widget status should be:
- `"warning"` if avg_latency_ms > 5000 OR error_count > 0
- `"ok"` otherwise

**Validates: Requirements 7.3, 7.4**

### Property 10: Scrape freshness classification and count consistency

*For any* set of subreddits with `is_active=True` and varying `last_scraped_at` values (including None), the freshness data should satisfy:
- `stale_count + fresh_count == total_active` (where fresh = scraped within 24h)
- `never_scraped_count ≤ stale_count` (never scraped is a subset of stale)
- A subreddit with `last_scraped_at = None` is always classified as `is_never_scraped=True` and `is_stale=True`
- A subreddit with `last_scraped_at` older than 24h is classified as `is_stale=True` and `is_never_scraped=False`

**Validates: Requirements 8.2, 8.3, 8.4**

## Error Handling

### MetricsCollector Errors

- **Log parsing failure**: If a structured log message cannot be parsed (malformed format), the `MetricsLoggingHandler.emit()` silently ignores it (no exception propagation to the logging system). This prevents metrics collection from breaking application logging.
- **Thread contention**: The `threading.Lock` in MetricsCollector uses a non-blocking pattern where possible. If lock acquisition fails, the operation is skipped rather than blocking the caller.

### Database Query Errors

- **Empty data**: All aggregation functions handle the case where no records exist in the time window — returning zero counts, zero rates, and empty breakdowns.
- **DB connection failure**: Widget endpoints wrap DB queries in try/except. On failure, they return a partial with an error message and "unknown" status, rather than raising a 500 error.

### Widget Endpoint Errors

- **Auth failure**: All widget endpoints use `require_superuser` dependency. Unauthorized requests get redirected to login (existing behavior).
- **Template rendering error**: Caught by FastAPI error middleware (existing `middleware/errors.py`).

### HTMX Polling Errors

- **Network failure**: HTMX `hx-trigger="every Xs"` continues polling even after failures. The template includes `hx-on::after-request` error handling to show a subtle "Connection lost" indicator without replacing widget content.
- **Stale data**: If a widget endpoint returns an error, the previous content is preserved (HTMX default behavior with proper error handling).

### Rate Limit Edge Cases

- **No rate limit data**: Fresh MetricsCollector returns `status="unknown"`, gauge shows "No data" with gray indicator.
- **PRAW rate limiter not accessible**: The `_log_rate_limit` function in `reddit.py` already wraps access in try/except. If rate limit info is unavailable, no log is emitted, and the collector retains its last known state.

## Testing Strategy

### Unit Tests (example-based)

Focus on specific scenarios and edge cases:

1. **MetricsCollector initialization** — verify fresh collector returns unknown state
2. **Rate limit recording** — record values, read back, verify match
3. **Log message parsing** — test each structured log pattern (REDDIT_API_CALL, REDDIT_API_RESULT, etc.) with concrete examples
4. **DB aggregation functions** — test with known data sets, verify computed values
5. **Widget endpoint responses** — test each endpoint returns valid HTML with correct status codes
6. **JSON metrics endpoint** — test response structure, auth requirement, ISO timestamp format
7. **Empty data handling** — test all functions with no data in DB
8. **HTMX attributes** — verify templates contain correct `hx-get`, `hx-trigger`, `hx-swap` attributes

### Property-Based Tests (universal properties)

Using **Hypothesis** (Python PBT library) with minimum 100 iterations per property:

1. **Property 1**: Rate limit log parsing round-trip — generate random (remaining, used, reset_ts), format → parse → verify
2. **Property 2**: Rate limit status classification — generate random remaining values, verify threshold mapping
3. **Property 3**: Rate limit gauge color — generate random usage_pct, verify color mapping
4. **Property 4**: Reddit API metrics consistency — generate random scrape_log-like data, verify error_rate formula
5. **Property 5**: Response time statistics ordering — generate random duration lists, verify avg ≤ p95 ≤ max
6. **Property 6**: Error breakdown sums — generate random error entries, verify sum = total
7. **Property 7**: LLM breakdown sums — generate random ai_usage entries, verify per-model sums = totals
8. **Property 8**: Reddit API status classification — generate random error_rate + latency, verify status
9. **Property 9**: LLM status classification — generate random latency + error_count, verify status
10. **Property 10**: Scrape freshness consistency — generate random subreddit sets with timestamps, verify counts

Each property test tagged with: `# Feature: reddit-api-health-dashboard, Property {N}: {description}`

### Integration Tests

1. **Full page load** — GET `/admin/health` returns 200 with all widget containers
2. **Widget partial endpoints** — each returns valid HTML partial
3. **JSON metrics endpoint** — returns valid JSON with all required fields
4. **Auth enforcement** — all endpoints reject non-superuser access
5. **HTMX polling simulation** — verify widget endpoints work with `HX-Request` header

### Test Configuration

- **Framework**: pytest + hypothesis
- **Hypothesis settings**: `max_examples=100`, `deadline=None` (DB tests may be slow)
- **Fixtures**: In-memory SQLite or test PostgreSQL with seeded scrape_log and ai_usage_log data
- **Mocking**: MetricsCollector is a simple class — no mocking needed for unit tests. DB tests use test fixtures.
