# Docker — Working with Containers

## Quick Start

```bash
# First time (or after wiping data):
make fresh-start

# Normal start (data persists in Docker volume):
make up

# Check status:
make health
make status
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Docker Compose                                      │
│                                                      │
│  ┌─────────┐  ┌────────┐  ┌─────────────┐          │
│  │   app   │  │ celery │  │ celery-beat │          │
│  │ :8000   │  │ worker │  │  scheduler  │          │
│  └────┬────┘  └───┬────┘  └──────┬──────┘          │
│       │            │              │                   │
│  ┌────┴────────────┴──────────────┴──────┐          │
│  │              db (PostgreSQL)           │          │
│  │              redis (Valkey)            │          │
│  └───────────────────────────────────────┘          │
│                                                      │
│  Volume: reddit_saas_pgdata (persistent)            │
└─────────────────────────────────────────────────────┘
```

## Data Management

### Where data lives

| Location | Purpose | Persistence |
|----------|---------|-------------|
| Docker volume `reddit_saas_pgdata` | PostgreSQL data | Survives `docker compose down` |
| Local PostgreSQL (port 5432) | Development DB | Always available |
| `/tmp/reddit_saas_dump.custom` | Transfer file | Temporary |

### Syncing local DB → Docker

The primary database is your **local PostgreSQL**. Docker containers use a copy.

```bash
# One command to sync everything:
make db-sync

# Or step by step:
make db-dump-local        # Dump local DB to /tmp/
make db-restore-to-docker # Restore into Docker + restart app
```

### Backing up Docker DB

```bash
make db-dump-docker       # Saves Docker DB to /tmp/reddit_saas_dump.custom
```

### Inspecting Docker DB

```bash
make db-shell    # Opens psql inside Docker
make db-tables   # Shows all tables with row counts
```

## Container Lifecycle

| Command | What it does |
|---------|-------------|
| `make up` | Start containers (data preserved) |
| `make down` | Stop containers (data preserved) |
| `make down-clean` | Stop + **delete all data** |
| `make restart` | Rebuild app image + restart (for code changes) |
| `make restart-all` | Rebuild all images + restart |

## Startup Flow (entrypoint.sh)

1. `alembic upgrade head` — apply pending migrations
2. If alembic fails:
   - Check if tables exist (data was restored from dump) → `stamp head`
   - If no tables → `create_all` + `stamp head`
3. `python -m app.seed` — seed default data (idempotent)
4. `uvicorn` — start the app

## Common Scenarios

### After changing code (models, routes, etc.)

```bash
make restart
```

### After adding a new migration

```bash
make restart  # entrypoint.sh runs alembic upgrade head
```

### After wiping Docker (or first clone)

```bash
make fresh-start  # Rebuilds + syncs local DB
```

### Debugging

```bash
make logs-app     # Watch app logs
make app-shell    # Shell into app container
make db-shell     # psql into Docker DB
```

## Port Mapping

| Service | Internal Port | External Port |
|---------|--------------|---------------|
| app | 8000 | **8000** (http://localhost:8000) |
| db | 5432 | not exposed (use `make db-shell`) |
| redis | 6379 | not exposed |

> **Note:** Local PostgreSQL also runs on port 5432. There's no conflict because Docker DB is only accessible internally.

## Troubleshooting

### "relation X does not exist" on startup

The Docker DB is empty or missing columns. Sync from local:
```bash
make db-sync
```

### App keeps restarting

Check logs:
```bash
make logs-app
```

Common causes:
- Missing env vars in `.env`
- DB not ready (healthcheck should handle this)
- Missing columns (run `make db-sync`)

### Need to start completely fresh

```bash
make down-clean   # Deletes volume
make fresh-start  # Rebuilds everything
```
