# Design Document: System Settings UI

## Overview

This feature migrates all application configuration from the static `.env` / `pydantic-settings` pattern into a database-backed settings system with an admin UI. The core idea: settings live in the `system_settings` table, are cached in memory for performance, and are editable through a dedicated admin page at `/admin/settings`. Only true bootstrap values (`DATABASE_URL`, `REDIS_URL`) remain in `.env`.

The design builds on the existing `SystemSetting` model and `settings.py` service, extending them with:
- A `group` column for UI organization
- An in-memory cache layer with targeted invalidation
- A `get_setting(key)` function that replaces direct `Settings` object access
- A full admin page with inline HTMX editing, secret masking, and connection testing
- Audit logging for all changes

## Architecture

```mermaid
graph TD
    subgraph "Bootstrap (before DB)"
        ENV[".env file"] --> DB_URL["DATABASE_URL"]
        ENV --> REDIS_URL["REDIS_URL (Celery)"]
    end

    subgraph "Runtime Configuration"
        DB[(system_settings table)] --> CACHE["In-Memory Cache<br/>(dict)"]
        CACHE --> GET["get_setting(key)"]
        GET --> SERVICES["Services / Routes"]
    end

    subgraph "Admin UI"
        PAGE["/admin/settings"] -->|HTMX POST| SAVE["set_setting()"]
        SAVE --> DB
        SAVE -->|invalidate| CACHE
        SAVE -->|log| AUDIT["Audit Log"]
        PAGE -->|HTMX POST| TEST["Connection Test"]
        TEST --> REDDIT_API["Reddit API"]
        TEST --> LLM_API["LLM API"]
    end
```

**Key architectural decisions:**

1. **In-process dict cache** — No Redis dependency for settings cache. The app is single-process (uvicorn) so a module-level dict suffices. Cache invalidation happens synchronously on write.

2. **Lazy migration** — The existing `config.py` `Settings` class remains for `DATABASE_URL` and `REDIS_URL` only. All other settings migrate to `get_setting()` calls. This avoids a big-bang refactor of every module.

3. **Group column on model** — Adding a `group` field to `SystemSetting` allows the UI to organize settings without hardcoding group membership in the template.

4. **HTMX partial responses** — Consistent with the existing admin panel pattern. Each setting row is independently editable and saveable.

## Components and Interfaces

### 1. Settings Model (extended)

**File:** `app/models/settings.py`

Add a `group` column to `SystemSetting`:

```python
class SystemSetting(Base):
    __tablename__ = "system_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    group: Mapped[str] = mapped_column(String(50), nullable=False, default="app")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

### 2. Settings Service (extended)

**File:** `app/services/settings.py`

```python
# Public interface:
def get_setting(db: Session, key: str) -> str
def set_setting(db: Session, key: str, value: str, user_id: uuid.UUID | None = None) -> None
def get_all_settings(db: Session) -> list[dict]
def init_defaults(db: Session) -> None
def invalidate_cache(key: str | None = None) -> None
def reload_cache(db: Session) -> None
def test_reddit_connection(db: Session) -> dict  # {"success": bool, "message": str}
def test_llm_connection(db: Session) -> dict     # {"success": bool, "message": str}
```

**Cache design:**
```python
_cache: dict[str, str] = {}  # module-level in-memory cache
_cache_loaded: bool = False

def get_setting(db: Session, key: str) -> str:
    if key in _cache:
        return _cache[key]
    # DB lookup, populate cache, return value
    ...

def invalidate_cache(key: str | None = None) -> None:
    if key:
        _cache.pop(key, None)
    else:
        _cache.clear()
        _cache_loaded = False
```

### 3. Config Loader (refactored)

**File:** `app/config.py`

The existing `Settings` class is kept but reduced to bootstrap-only values:

```python
class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:postgres@localhost:5432/reddit_saas"
    redis_url: str = "redis://localhost:6379/0"
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
```

A new `get_config(key)` function wraps `settings_service.get_setting()` for use by other modules:

```python
def get_config(key: str, db: Session | None = None) -> str:
    """Get a config value. Bootstrap keys come from env, everything else from DB."""
    if key in ("database_url", "redis_url"):
        return getattr(get_settings(), key)
    if db is None:
        from app.database import SessionLocal
        db = SessionLocal()
        try:
            return settings_service.get_setting(db, key)
        finally:
            db.close()
    return settings_service.get_setting(db, key)
```

### 4. Admin Settings Route

**File:** `app/routes/admin.py` (new endpoints added)

```python
@router.get("/settings", response_class=HTMLResponse)
def admin_settings(request, current_user=Depends(require_superuser), db=Depends(get_db)):
    ...

@router.post("/settings/{key}", response_class=HTMLResponse)
def admin_update_setting(request, key: str, value: str = Form(...), ...):
    ...

@router.post("/settings/bulk-save", response_class=HTMLResponse)
def admin_bulk_save_settings(request, ...):
    ...

@router.post("/settings/test/reddit", response_class=HTMLResponse)
def admin_test_reddit(request, ...):
    ...

@router.post("/settings/test/llm", response_class=HTMLResponse)
def admin_test_llm(request, ...):
    ...
```

### 5. Template

**File:** `app/templates/admin_system_settings.html`

Extends `admin_base.html`. Renders settings grouped by `group` field. Each group is a visually separated card. Each setting row has:
- Key name (label)
- Current value (masked if secret, with reveal toggle)
- Description (helper text)
- Updated timestamp
- Edit button → inline input + save button (HTMX)

Connection test buttons appear within the `reddit_api` and `llm` group cards.

### 6. Sidebar Update

**File:** `app/templates/admin_base.html`

Add "System Settings" link between "Audit Logs" and "Billing" in the sidebar nav.

## Data Models

### SystemSetting (updated)

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK, default uuid4 | Primary key |
| key | String(255) | UNIQUE, NOT NULL, INDEX | Setting identifier |
| value | Text | NOT NULL, default "" | Setting value (always stored as string) |
| is_secret | Boolean | default False | Whether to mask in UI |
| description | Text | nullable | Human-readable description |
| group | String(50) | NOT NULL, default "app" | Grouping for UI display |
| updated_at | DateTime(tz) | server_default now(), onupdate now() | Last modification time |

### Default Settings Registry

| Key | Group | Secret | Description |
|-----|-------|--------|-------------|
| redis_url | redis | No | Redis connection URL |
| secret_key | auth | Yes | JWT signing secret |
| access_token_expire_minutes | auth | No | Token TTL in minutes |
| admin_email | auth | No | Default admin email |
| admin_password | auth | Yes | Default admin password |
| admin_name | auth | No | Default admin display name |
| app_env | app | No | Environment (development/production) |
| app_host | app | No | Server bind host |
| app_port | app | No | Server bind port |
| reddit_client_id | reddit_api | No | Reddit API Client ID |
| reddit_client_secret | reddit_api | Yes | Reddit API Client Secret |
| reddit_user_agent | reddit_api | No | Reddit API User Agent |
| llm_api_key | llm | Yes | LLM API key |
| llm_provider | llm | No | LLM provider name |
| llm_scoring_model | llm | No | Model for scoring |
| llm_generation_model | llm | No | Model for generation |
| monthly_budget_usd | budget | No | Monthly AI budget limit |
| aws_credits_remaining | budget | No | AWS credits remaining |
| alert_email | app | No | System alert email |
| dry_run_enabled | app | No | Dry run mode toggle |


## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: init_defaults idempotency

*For any* subset of settings that already exist in the database with arbitrary values, calling `init_defaults` SHALL create entries for all missing keys with their default values while leaving all pre-existing entries unchanged.

**Validates: Requirements 1.2**

### Property 2: All settings have valid group labels

*For any* setting in the defaults registry, its assigned group SHALL be one of the allowed values: `database`, `redis`, `auth`, `reddit_api`, `llm`, `app`, `budget`.

**Validates: Requirements 1.4**

### Property 3: Database-first resolution for non-bootstrap keys

*For any* non-bootstrap setting key that has a record in the database, `get_setting(key)` SHALL return the database value. If no database record exists, it SHALL return the default value from the registry.

**Validates: Requirements 2.3**

### Property 4: Cache read-through

*For any* setting key, after the first call to `get_setting(key)` returns a value, subsequent calls with the same key SHALL return the same value without querying the database.

**Validates: Requirements 3.1**

### Property 5: Cache invalidation on write

*For any* setting key and any pair of distinct values (old, new), if the key is cached with the old value and then `set_setting(key, new)` is called, the next call to `get_setting(key)` SHALL return the new value.

**Validates: Requirements 3.2**

### Property 6: Cache reload_all clears all entries

*For any* set of cached settings, after calling `reload_all`, the cache SHALL be empty and subsequent `get_setting` calls SHALL read fresh values from the database.

**Validates: Requirements 3.3**

### Property 7: Secret values masked in rendered output

*For any* setting with `is_secret=True` and any non-empty value, the rendered settings page HTML SHALL contain the masked placeholder `•••••` and SHALL NOT contain the actual secret value as plaintext.

**Validates: Requirements 4.4**

### Property 8: Audit log created with correct details on update

*For any* setting key, any value, and any admin user_id, calling `set_setting(key, value, user_id)` SHALL create an audit log entry with `action="update"`, `entity_type="system_setting"`, `user_id` matching the caller, and `details` containing the setting key.

**Validates: Requirements 7.1, 7.3**

### Property 9: Secret values redacted in audit log

*For any* secret setting key and any value, the audit log entry created by `set_setting` SHALL contain `"[REDACTED]"` in the details instead of the actual value.

**Validates: Requirements 7.2**

### Property 10: Connection test error truncation

*For any* connection test failure (Reddit or LLM) with any error message string, the displayed error message SHALL be truncated to at most 100 characters.

**Validates: Requirements 6.4, 6.8**

### Property 11: Bulk save persists all values

*For any* set of key-value pairs submitted via bulk save, after the operation completes, `get_setting(key)` SHALL return the new value for every key in the set.

**Validates: Requirements 5.3**

## Error Handling

### Settings Service Errors

| Scenario | Handling |
|----------|----------|
| Database unavailable during `get_setting` | Return default value from registry if available; log warning. If no default exists, raise `ServiceUnavailableError`. |
| Database unavailable during `set_setting` | Raise exception; let the route handler return a 500 error partial with retry suggestion. |
| Invalid key passed to `get_setting` | Return empty string (consistent with current behavior). |
| `init_defaults` fails mid-way | Transaction rollback; log error. App continues with whatever defaults already exist. |

### Connection Test Errors

| Scenario | Handling |
|----------|----------|
| Reddit API credentials invalid | Return `{"success": False, "message": "Authentication failed: <truncated error>"}` |
| Reddit API timeout | Return `{"success": False, "message": "Connection timed out after 10s"}` |
| LLM API key invalid | Return `{"success": False, "message": "API key rejected: <truncated error>"}` |
| LLM API timeout | Return `{"success": False, "message": "Connection timed out after 15s"}` |
| Network unreachable | Return `{"success": False, "message": "Network error: <truncated>"}` |

### UI Error Handling

| Scenario | Handling |
|----------|----------|
| Save fails (server error) | HTMX response replaces the setting row with an error state; red border + error message. |
| Validation failure | Return 422 with partial HTML showing the error message next to the field. |
| Connection test in progress | Disable button, show spinner. On timeout (30s client-side), show "Timed out" message. |

## Testing Strategy

### Property-Based Tests (Hypothesis)

The project already uses Hypothesis (`.hypothesis/` directory exists). Property tests will use `hypothesis` with `@given` decorators.

**Configuration:**
- Minimum 100 examples per property (`@settings(max_examples=100)`)
- Each test tagged with: `# Feature: system-settings-ui, Property N: <title>`

**Properties to implement:**
1. init_defaults idempotency
2. Valid group labels
3. DB-first resolution
4. Cache read-through
5. Cache invalidation on write
6. Cache reload_all
7. Secret masking in UI
8. Audit log correctness
9. Secret redaction in audit
10. Error truncation
11. Bulk save persistence

### Unit Tests (pytest)

Example-based tests for specific scenarios:
- Bootstrap keys (DATABASE_URL, REDIS_URL) always come from env
- Specific secret keys are marked `is_secret=True`
- Settings page returns 200 for superuser, 403 for non-superuser
- Sidebar contains "System Settings" link in correct position
- DATABASE_URL shown as read-only
- Success indicators displayed after save
- Connection test buttons present in correct groups

### Integration Tests

- Full request cycle: GET settings page → edit → POST save → verify DB updated
- Connection test endpoints with mocked external services
- Cache invalidation triggered by route handler save

### Test Organization

```
tests/
├── test_settings_service.py      # Property + unit tests for service layer
├── test_settings_cache.py        # Property tests for cache behavior
├── test_settings_routes.py       # Integration tests for admin endpoints
└── test_settings_audit.py        # Property tests for audit logging
```
