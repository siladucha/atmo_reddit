# Deployment Guide

> **Audience:** Owner (Max)  
> **Last updated:** 2026-06-23

---

## Infrastructure

| Component | Details |
|-----------|---------|
| **Provider** | DigitalOcean |
| **Droplet** | `reddit-saas` — 2 vCPU, 4 GB RAM, 60 GB SSD |
| **Region** | Frankfurt (FRA1) 🇩🇪 |
| **OS** | Ubuntu 24.04 LTS |
| **IPv4** | `161.35.27.165` |
| **Cost** | ~$23/mo (with backups) |
| **Access** | `ssh root@161.35.27.165` |
| **Project path** | `/app/` (main app), `/marketing_site/` (marketing) |

---

## Docker Compose Stack

| Service | Image | Purpose |
|---------|-------|---------|
| `app` | Custom (Dockerfile) | FastAPI web server |
| `db` | postgres:16 | PostgreSQL database |
| `redis` | redis:7 | Task queue broker + cache |
| `celery_worker` | Custom | Background task processor |
| `celery_beat` | Custom | Task scheduler |
| `marketing` | Custom | Marketing site |
| `nginx` | nginx:alpine | Reverse proxy |

---

## Deploy Commands (from local Mac)

### Push Code to Server

```bash
cd reddit_saas
rsync -avz --exclude='.venv/' --exclude='__pycache__/' --exclude='.hypothesis/' \
  --exclude='.git/' --exclude='*.pyc' --exclude='.DS_Store' --exclude='logs/' \
  --exclude='.env' --exclude='.claude/' --exclude='.kiro/' --exclude='.vscode/' \
  --exclude='tests/' --delete \
  ./ root@161.35.27.165:/app/
```

### Rebuild and Restart

```bash
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml build && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
```

### Quick Restart (no rebuild)

```bash
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml restart app celery_worker celery_beat"
```

### Check Health

```bash
ssh root@161.35.27.165 "curl -s http://localhost/health"
```

### View Logs

```bash
# All services
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f --tail=50"

# Specific service
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f --tail=50 app"
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f --tail=50 celery_worker"
```

---

## Database Operations

### Sync Local → Server

```bash
# 1. Dump local DB
docker compose exec -T db pg_dump -U reddit_saas_user -d reddit_saas --no-owner --format=custom -f /tmp/dump.custom

# 2. Copy out of container
docker compose cp db:/tmp/dump.custom /tmp/reddit_saas_live.custom

# 3. Upload to server
scp /tmp/reddit_saas_live.custom root@161.35.27.165:/tmp/

# 4. Restore on server
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db pg_restore -U reddit_saas_user -d reddit_saas --clean --if-exists --no-owner --single-transaction /tmp/reddit_saas_live.custom"
```

### Makefile Shortcuts (local)

```bash
make db-sync          # Full local → Docker sync
make db-dump-local    # Dump local DB
make db-restore-to-docker  # Restore dump into Docker
make fresh-start      # Wipe Docker DB + restore from dump
make db-shell         # Open psql in Docker container
make health           # Check app health
```

---

## Marketing Site Deployment

```bash
# Push marketing site code
rsync -avz --exclude='.venv/' --exclude='__pycache__/' --exclude='.git/' \
  --exclude='*.pyc' --exclude='.DS_Store' --delete \
  ../marketing_site/ root@161.35.27.165:/marketing_site/

# Rebuild marketing container
ssh root@161.35.27.165 "cd /app && docker compose build --no-cache marketing && docker compose up -d marketing"
```

---

## Nginx Configuration

Nginx routes traffic:
- `/admin/*`, `/api/*`, `/login`, `/health` → main app (port 8000)
- `/` (catch-all) → marketing site (port 8001)

---

## Environment Variables

Stored in `/app/.env` on server. Key variables:

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |
| `SECRET_KEY` | JWT signing key |
| `REDDIT_CLIENT_ID` | Reddit API credentials |
| `REDDIT_CLIENT_SECRET` | Reddit API credentials |
| `OPENROUTER_API_KEY` | LLM API key (OpenRouter) |
| `ANTHROPIC_API_KEY` | Claude API key (direct) |
| `GOOGLE_API_KEY` | Gemini API key |
| `TZ` | Timezone (`Asia/Jerusalem`) |

⚠️ Never commit `.env` to git. Never echo secrets in logs.

---

## Entrypoint Behavior

`entrypoint.sh` runs on container start:
1. Checks if database tables exist
2. If tables exist (from pg_restore): stamps Alembic to latest revision
3. If no tables: runs `alembic upgrade head` (creates schema)
4. Runs seed data (`app/seed.py`)
5. Starts the application

---

## Monitoring

### Health Endpoint

`GET /health` returns:
```json
{
  "status": "healthy",
  "database": "connected",
  "redis": "connected",
  "celery": "active"
}
```

### Log Locations (inside containers)

- App logs: stdout (captured by Docker)
- Celery worker logs: stdout
- Nginx access logs: `/var/log/nginx/access.log`

### Backups

- DigitalOcean weekly backups enabled (automatic)
- Manual DB dumps recommended before major changes

---

## Scaling Notes

Current setup handles 10 clients comfortably. Upgrade path:

| Trigger | Action | Cost Impact |
|---------|--------|-------------|
| 5+ paying clients | Managed DB (DO) | +$15/mo |
| CPU > 80% sustained | Upgrade droplet (4 vCPU) | +$25/mo |
| 50+ clients | Separate worker droplet | +$23/mo |
| Enterprise requirement | Migrate to AWS | See `docs/aws_migration_checklist.md` |

---

## Security Features

| Feature | Implementation | Scope |
|---------|---------------|-------|
| HTTP Security Headers | `middleware/security.py` (SecurityHeadersMiddleware) | All responses |
| Auth Rate Limiting | 5 attempts per 15 min per IP | POST /login, /register (production only) |
| Global Rate Limiting | 100 req per 60s per IP | All routes (production only) |
| Custom 403 Page | Friendly HTML error page | Rate limit violations |
| **Auto-Logout on Inactivity** | `static/js/idle-logout.js` | All authenticated pages |

### Auto-Logout Behavior

- **Timeout:** 10 minutes of inactivity (no mouse, keyboard, scroll, click, or touch)
- **Warning:** Yellow toast appears at 9 minutes: "Session expires in 60 seconds due to inactivity"
- **Action:** Redirects to `/logout` at 10 minutes
- **Reset:** Any user activity (including HTMX requests) resets the timer
- **Scope:** All 3 base templates (`base.html`, `admin_base.html`, `client_base.html`)
