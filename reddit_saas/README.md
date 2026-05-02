# Reddit Marketing SaaS

AI-powered Reddit engagement platform for B2B companies.

## Quick Start

### Prerequisites
- Docker Desktop (recommended) OR PostgreSQL 16 + Redis 7
- Python 3.11+
- Reddit API credentials (create at reddit.com/prefs/apps)
- LLM API key (OpenRouter, Anthropic, or AWS Bedrock)

### 1. Start infrastructure

```bash
# With Docker:
cd reddit_saas
docker compose up -d db redis

# Or with Homebrew:
brew install postgresql@16 redis
brew services start postgresql@16
brew services start redis
createdb reddit_saas
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — fill in Reddit and LLM credentials
```

### 3. Install dependencies

```bash
pip install -e .
# or
pip install -r requirements.txt
```

### 4. Initialize database

```bash
# Create tables and seed test data
python -m app.seed
```

### 5. Run the app

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 6. Run Celery worker (separate terminal)

```bash
celery -A app.tasks.worker worker --loglevel=info
```

### 7. Open in browser

- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

## API Endpoints

### Auth
- `POST /auth/register` — Create account
- `POST /auth/login` — Get JWT token

### Pipeline (trigger manually for testing)
- `POST /pipeline/scrape/{client_id}` — Scrape subreddits
- `POST /pipeline/score/{client_id}` — Score threads with AI
- `POST /pipeline/generate/{client_id}` — Generate comments
- `POST /pipeline/full-pipeline/{client_id}` — Run full pipeline

### Review
- `GET /review/comments?status=pending` — List pending comments
- `PATCH /review/comments/{id}` — Approve/reject/edit
- `GET /review/posts?status=pending` — List pending posts
- `PATCH /review/posts/{id}` — Approve/reject/edit

### Avatars
- `GET /avatars/` — List avatars with health status
- `GET /avatars/{id}/health` — Detailed health metrics
- `POST /avatars/{id}/quarantine` — Deactivate avatar
- `POST /avatars/{id}/reactivate` — Reactivate avatar

### Admin
- `GET /admin/stats` — Dashboard stats
- `GET /admin/ai-usage` — AI cost breakdown by client

## Architecture

See `architecture.md` for full system design, data flow diagrams, and database schema.
