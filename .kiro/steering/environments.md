---
inclusion: always
---

# Environment Rules — STRICT

## Three Environments

| # | Environment | Where | Access |
|---|-------------|-------|--------|
| 1 | **Development** | Local Mac (`/Volumes/2SSD/Projects/ReddirSaaS/reddit_saas/`) | Free — no Docker, run directly |
| 2 | **Staging** | `ssh ramp-staging` / `https://staging.gorampit.com` (167.172.191.42) | Free — deploy, test, break things |
| 3 | **Production** | `ssh ramp` / `https://gorampit.com` (161.35.27.165) | **ONLY WITH EXPLICIT USER PERMISSION** |

## Rules

1. **NEVER** ssh to production (`ssh ramp`), deploy to production, or run commands on production server without explicit user approval in the current conversation.
2. **NEVER** modify production database, production .env, or production nginx without explicit user approval.
3. All development and testing happens locally or on staging.
4. Deploy flow: local dev → staging test → **ask user** → production.
5. If you need to check something on production (read-only), still ask first.

## Development (Local)

- Run app directly: `python -m uvicorn app.main:app --reload`
- **NO Docker on local machine** — Docker is NOT installed. Do not use docker/docker-compose commands locally.
- PostgreSQL runs natively (not in container). Access via `psql` directly or SQLAlchemy connection string in `.env`.
- Redis runs natively (not in container).
- Alembic migrations: run `alembic upgrade head` directly (no `docker compose exec`).
- `.env` in `reddit_saas/` directory
- Python venv at `/Volumes/2SSD/Projects/ReddirSaaS/.venv/`
- **Git branch: `develop`** — Max's primary working branch. All daily coding happens here.

## Staging

- Full Docker Compose (same as prod)
- Kill switches ALL disabled (false)
- Celery workers stopped (manual testing only)
- Safe to break, reset DB, deploy experimental code
- Reddit API key shared with prod (same app)
- LLM keys active (for onboarding/generation testing)

## Production

- **DO NOT TOUCH WITHOUT PERMISSION**
- Live system with real data and real clients
- Celery Beat running automated pipelines
- Any change requires explicit "deploy to prod" or equivalent from user
