# TODO — Reddit Marketing SaaS

_Last updated: 2026-05-03_

## Current Status
- 60 unit tests passing across 9 test modules
- 12 Jinja2 templates (login, register, dashboard, client list/detail/new, avatar list/new, review, threads, admin, guide)
- Backend: auth (JWT cookie), Reddit scraping, AI pipeline (scoring + generation + editing), safety layer, avatar health
- Middleware: auth (route protection) + global error handler
- Celery Beat scheduler running 4 jobs (8am, 14:00, 10:00, every 12h)
- Orchestrator tasks for batch client/avatar execution
- Server runs on `localhost:8000`

---

## Recently Completed (May 2–3)
- ✅ Celery Beat scheduler — `app/tasks/worker.py:24–41`
- ✅ Auth middleware — `app/middleware/auth.py` (JWT cookie, redirect to /login)
- ✅ Error handling middleware — `app/middleware/errors.py` (HTML error pages)
- ✅ Orchestrator tasks — `app/tasks/orchestrator.py` (3 master tasks)
- ✅ Avatar health checks — quarantine/karma tracking
- ✅ Avatar creation form + CRUD routes — `app/routes/avatars.py`
- ✅ User guide / onboarding template — `app/templates/guide.html`
- ✅ Polished UI (12 templates, Tailwind responsive)
- ✅ Daily log rotation (7-day history)
- ✅ Documentation moved into `docs/` folder

---

## Priority 1 — Make Pipeline Actually Work End-to-End

### Task 1.1: Test Scrape Tasks Against Real Reddit API
**File:** `reddit_saas/app/tasks/scraping.py`
- Set Reddit API credentials in `.env`
- Run `scrape_professional_subreddits.delay(client_id)` manually
- Verify threads save to DB with correct client_id
- Verify deduplication by `reddit_native_id` works across runs
- Confirm orchestrator chain (scrape → score → generate) completes

### Task 1.2: Thread Detail Page
**File:** `reddit_saas/app/routes/pages.py` + `templates/threads.html`
- Thread list page exists (`/threads/{client_id}`)
- Add thread detail page: full post body + comment tree + scoring breakdown
- Show generated drafts linked to that thread

### Task 1.3: Post Generation Pipeline
**File:** `reddit_saas/app/services/generation.py`
- `generate_post()` is currently a stub
- Brief creation → post draft → save to `post_drafts`
- Source material picker (high-scoring threads or external feed)
- Add post review UI parallel to comment review

---

## Priority 2 — Production Readiness

### Task 2.1: Alembic Initial Migration
- `alembic/versions/` is currently empty — using `Base.metadata.create_all()` in `seed.py`
- Generate first migration: `alembic revision --autogenerate -m "initial schema"`
- Verify all 11 models are picked up
- Run `alembic upgrade head` against fresh DB
- Document migration workflow in README

### Task 2.2: Pagination
- Thread list, comment review queue, avatar list — all hard-capped at 50/100 items
- Add `?page=N&size=M` query params + page nav in templates

### Task 2.3: Real Auth Tests (Currently Mocked)
- 60 tests pass, but most use the fake auth middleware bypass
- Add integration tests that actually exercise `/auth/login` → cookie → protected route

---

## Priority 3 — Missing Features

### Task 3.1: Persona CRUD
- Model exists (`app/models/persona.py`), no routes or UI
- Add persona management per client

### Task 3.2: Keyword Management UI
- Currently keywords are a JSONB blob on `clients`
- Add UI to manage keywords with priority levels (HIGH/MEDIUM/LOW)

### Task 3.3: Redraft Endpoint
- "Regenerate this comment" button on review page
- Calls `generate_comment` again with same thread/avatar; new draft replaces or appends

### Task 3.4: Tracking Page
- Published comments/posts history (filter by client, avatar, date)
- Basic stats: comments/day, karma gained

### Task 3.5: Shadowban Auto-Detection
- `check_all_avatars_health` runs every 12h but only logs warnings
- Wire to `services/safety.quarantine_avatar()` when shadowban detected
- Notify human reviewer (email/Slack)

---

## Priority 4 — DevOps

### Task 4.1: Docker Build Verification
- `docker compose up` end-to-end smoke test
- Confirm worker + beat + web all start

### Task 4.2: GitHub Actions CI
- Run `pytest tests/` on push
- Lint with `ruff`

### Task 4.3: AWS Deployment
- EC2 setup
- RDS PostgreSQL
- ElastiCache Redis
- Bedrock access (LLM)

---

## How to Give Tasks to Claude

Copy a task block above and paste it to Claude with:
1. The task description
2. Reference to existing files (tell it to read them first)
3. "Run tests after: `python -m pytest tests/ -v`"
4. "Commit with descriptive message"

Example prompt:
```
Read reddit_saas/app/tasks/scraping.py and reddit_saas/app/tasks/orchestrator.py.
Then implement Task 1.1: smoke-test scrape against real Reddit API.
After implementing, run: python -m pytest tests/ -v
Make sure all tests pass. Commit the changes.
```
