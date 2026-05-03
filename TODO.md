# TODO — Reddit Marketing SaaS

## Current Status
- 60 tests passing
- UI: login, register, dashboard, client CRUD, avatar CRUD, review, threads, admin
- Backend: auth, Reddit scraping, AI pipeline (scoring + generation + editing), safety layer
- Server runs on localhost:8000

---

## Priority 1 — Make Pipeline Actually Work End-to-End

### Task 1.1: Celery Beat Scheduler
**File:** `reddit_saas/app/tasks/scheduler.py`
- Add Celery Beat schedule config
- For each active client: scrape → score → generate at 8am and 2pm
- For each active avatar: hobby scrape + generate at 10am
- Config in `worker.py` using `celery_app.conf.beat_schedule`

### Task 1.2: Wire Scraping Tasks to Save Threads Correctly
**File:** `reddit_saas/app/tasks/scraping.py`
- Test with real Reddit API (need credentials in .env)
- Verify threads save to DB with correct client_id
- Verify deduplication works across runs

### Task 1.3: Thread List/Detail API + UI
**File:** `reddit_saas/app/routes/pages.py`
- Client detail page already links to `/threads/{client_id}` — verify it works
- Add thread detail page showing full post + comments + scoring

### Task 1.4: Post Generation Pipeline
**File:** `reddit_saas/app/services/generation.py`
- Implement `generate_post()` function (currently stub)
- Brief creation → post draft → save to post_drafts
- Add post review UI (similar to comment review)

---

## Priority 2 — Production Readiness

### Task 2.1: Alembic Initial Migration
```bash
cd reddit_saas
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```
- Currently using `Base.metadata.create_all()` in seed.py — need proper migrations

### Task 2.2: Error Handling Middleware
**File:** `reddit_saas/app/main.py`
- Add global exception handler that logs errors and returns friendly HTML
- Currently shows raw "Internal Server Error"

### Task 2.3: Auth Middleware (Protect Routes)
**File:** `reddit_saas/app/middleware/auth.py`
- Currently all pages are accessible without login
- Add middleware that checks JWT cookie on all routes except /login, /register, /health
- Redirect to /login if not authenticated

### Task 2.4: Pagination
- Thread list, comment review, avatar list — all need pagination
- Currently limited to 50/100 items

---

## Priority 3 — Missing Features

### Task 3.1: Persona CRUD
- Model exists, no routes or UI
- Add persona management per client

### Task 3.2: Keyword Management
- Currently keywords are a JSON blob on client
- Add UI to manage keywords with priority levels

### Task 3.3: Redraft Endpoint
- "Regenerate this comment" button on review page
- Calls generate_comment again with same thread/avatar

### Task 3.4: Tracking Page
- Published comments history
- Filter by client, avatar, date
- Basic stats (comments/day, karma gained)

### Task 3.5: Shadowban Checker
- Periodic task that checks if avatars are shadowbanned
- Use Reddit API or HTTP check
- Auto-quarantine if detected

---

## Priority 4 — DevOps

### Task 4.1: Docker Build Verification
- Test `docker compose up` works end-to-end
- Fix any issues with Dockerfile

### Task 4.2: GitHub Actions CI
- Run tests on push
- Lint with ruff

### Task 4.3: AWS Deployment
- EC2 setup
- RDS PostgreSQL
- ElastiCache Redis
- Bedrock access

---

## How to Give Tasks to Claude

Copy a task block above and paste it to Claude with:
1. The task description
2. Reference to existing files (tell it to read them first)
3. "Run tests after: `python -m pytest tests/ -v`"
4. "Commit with descriptive message"

Example prompt:
```
Read reddit_saas/app/tasks/worker.py and reddit_saas/app/tasks/scraping.py.
Then implement Task 1.1: Add Celery Beat scheduler config.
After implementing, run: python -m pytest tests/ -v
Make sure all tests pass. Commit the changes.
```
