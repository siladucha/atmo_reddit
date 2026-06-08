# Language Defaults — Python

> **Usage:** Copy to `.kiro/steering/LANGUAGE_PYTHON.md` for Python/FastAPI projects.
> This file is paired with `AGENT.md` (methodology) and `project.md` (context).

---

## Architecture

```
project/
├── app/
│   ├── config.py          # pydantic-settings
│   ├── main.py            # App factory
│   ├── version.py         # Reads VERSION file
│   ├── models/            # SQLAlchemy / ORM models
│   ├── schemas/           # Pydantic request/response validation
│   ├── services/          # Business logic (one service per domain)
│   ├── routes/            # Thin HTTP handlers
│   ├── tasks/             # Background job definitions
│   ├── middleware/        # Auth, errors, logging
│   ├── dependencies/      # FastAPI DI (auth guards, DB session)
│   └── templates/         # Jinja2 (if server-rendered)
├── tests/
├── docs/
├── decisions/             # ADR, risks, assumptions, tech-debt
├── alembic/               # DB migrations
├── Makefile               # Self-documenting (make help)
├── Dockerfile
├── docker-compose.yml
├── docker-compose.prod.yml
├── entrypoint.sh          # Migrations + seed on startup
├── pyproject.toml
├── VERSION                # Single source of truth
└── .kiro/steering/
```

## Python Code Style

- Python 3.11+
- Type hints everywhere (params, returns, variables where non-obvious)
- `async` only for real I/O; sync for CPU-bound and simple logic
- SQLAlchemy 2.0 `mapped_column` style
- Config: pydantic-settings + `.env`
- Routes: thin handlers, delegate to services immediately
- Services: pure business logic, no HTTP concepts (no Request/Response objects)
- One file ≈ one responsibility (max ~500 lines, split at ~300 if growing)
- All code in English (variables, comments, docstrings, UI strings)
- No `# type: ignore` without comment explaining why

## Database Conventions

- Table names: plural `snake_case` (`users`, `comment_drafts`)
- Primary keys: UUID v4 (not auto-increment)
- Every table: `id`, `created_at`, `updated_at`
- Soft delete: `is_active` (default `true`) — not `DELETE`
- JSONB fields: document schema in code comment above field
- Indexes: for every `WHERE`, `JOIN`, `ORDER BY` column used in queries
- Migrations: one per logical change, descriptive revision message
- Foreign keys: always with `ondelete` clause (`CASCADE`, `SET NULL`, or `RESTRICT`)
- Constraints: CHECK constraints for enums and ranges in DB, not just in Python
- Connection pool: explicit size, match to worker count

## API Conventions

- REST: `/api/v1/{resource}` for machine clients
- Admin: `/admin/{resource}` (separate auth, separate UI layer)
- HTMX partials: inline in route files or `/partials/`
- Pagination: `limit` + `offset` params, return `total_count` in response
- Errors: `{"detail": "human message", "code": "MACHINE_CODE"}`
- Auth: JWT in HttpOnly cookie (browser) or `Authorization: Bearer` header (API)
- Dates: ISO 8601 in responses, timezone-aware

## Error Handling

- Services: raise typed exceptions (`NotFoundError`, `PermissionError`, `ValidationError`)
- Routes: catch → return appropriate HTTP status + message
- Background tasks: log + retry (transient) or log + freeze (permanent)
- Never swallow exceptions silently
- User-facing: human-readable, no stack traces, no internal paths
- Logging: structured (key=value or JSON), include request_id where possible

## Testing

- pytest + hypothesis (property-based testing)
- Every feature defines correctness properties (invariants that must always hold)
- Mocks for external APIs — never call real services in tests
- At least one E2E test per major workflow
- Test file naming: `tests/test_{module}.py`
- Fixtures in `conftest.py` — DB session, test client, auth helpers
- No tests that depend on execution order
- hypothesis settings: `max_examples=100` in CI, `50` locally

## Infrastructure

### Docker
- `docker-compose.yml` — dev (all services, default ports)
- `docker-compose.prod.yml` — production overrides (memory limits, restart policies)
- `docker-compose.dev.yml` (optional) — hot-reload, source mount
- `entrypoint.sh` — detect existing tables → stamp Alembic if needed → run migrate → seed

### Makefile (standard targets)
```makefile
make up            # Start all containers
make down          # Stop (preserve data)
make restart       # Rebuild + restart app
make fresh-start   # Clean + rebuild + seed
make db-sync       # Dump local → restore to Docker
make db-shell      # psql shell
make logs          # Tail logs
make health        # Curl health endpoint
make deploy        # Smart deploy to server
make help          # Show all targets
```

### Deploy Pattern
- rsync → server (exclude: `.venv/`, `.git/`, `tests/`, `.env`, IDE dirs)
- `docker compose build && docker compose up -d`
- Health check post-deploy: `curl /health`
- `deploy.sh` — auto-detect changes, deploy only affected services

### Versioning
- `VERSION` file in project root — single source of truth
- `app/version.py` reads it, exposes `__version__`
- Health endpoint + UI footer show version + environment
- pyproject.toml version matches VERSION

### Environment Controls
- Env-level kill switches via env vars (for critical things)
- DB-level kill switches (for features, togglable from admin)
- `.env` per environment — never committed
- `.env.example` — committed, documents all vars

## Dependencies

- Pin `>=major.minor` in pyproject.toml (not `==exact`)
- Dev deps separate: `[project.optional-dependencies] dev = [...]`
- Don't add libraries for things stdlib handles
- Prefer well-known packages over obscure ones (check GitHub stars, last commit)
- Audit quarterly: remove unused, patch CVEs
- Lock file (`pip-compile` output or `uv.lock`) for reproducible builds in CI

## AI/LLM Integration

- Abstraction layer (LiteLLM or custom wrapper) — easy provider swap
- Different models per task (cheap for classification, smart for generation)
- Pydantic schema on LLM output (validate structured responses, retry on parse failure)
- Retry with exponential backoff on transient errors (3 attempts, 60×2^n)
- Cost tracking: log every call (model, tokens_in, tokens_out, cost_usd, latency_ms)
- Kill switches per AI feature (`generation_enabled`, `scoring_enabled`)
- Never hardcode prompts in services — externalize to files or DB for versioning

## Background Tasks (Celery + Redis)

- Producer: FastAPI app + Celery Beat scheduler
- Consumer: prefork worker pool (match to CPU cores)
- Retry: `bind=True, max_retries=3, countdown=60*2**self.request.retries`
- Locks: Redis SETNX with TTL + Lua atomic release
- Rate limiter: Redis sorted set sliding window
- Scheduler: Celery Beat, documented in table format
- Timezone: explicitly set in Celery config (not default UTC)
- Dead letter: log permanently failed tasks (don't lose them silently)

## Observability

- Structured logging: JSON in production, human-readable in dev
- Health endpoint: `/health` → `{"version", "env", "status", "uptime", ...}`
- Health polled externally (UptimeRobot, Healthchecks.io, or cron)
- Activity events for pipeline transparency (what happened, when, result)
- Alert channels: Telegram for critical, admin dashboard for non-critical
- Metrics to track: error rate, p95 latency, queue depth, daily cost

## Safety & Security

- JWT auth (access + refresh, HttpOnly cookies for browser)
- RBAC: roles → permissions → query scoping → data isolation
- Numbered safety gates for automated actions (gate #0, #1, ...)
- Kill switches: env-level (global, needs restart) + DB-level (per-entity, instant)
- Auto-freeze on repeated failures (3 consecutive → freeze entity + alert)
- Encryption at rest: Fernet AES for passwords, tokens, proxy URLs
- Never commit `.env`, secrets, or private keys
- Audit log: who, what, when, from_where, result

## Git Workflow

- `main`: production-ready, deploy from here
- `feature/{spec-name}`: one branch per spec/feature
- Commits: conventional format (`feat:`, `fix:`, `chore:`, `docs:`)
- No force push on shared branches
- PR description: what changed + what was tested + breaking changes
- Tag releases: `v{VERSION}` on production deploys
