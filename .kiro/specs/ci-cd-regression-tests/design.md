# Design Document

## Overview

GitHub Actions CI/CD pipeline for the RAMP platform. The pipeline consists of 4 sequential jobs: lint → test → build → deploy. It replaces the manual rsync + docker compose rebuild workflow with automated, tested deployments.

## Architecture

### Pipeline Structure

```
┌─────────────────────────────────────────────────────────────────┐
│  GitHub Actions Workflow: .github/workflows/ci-cd.yml           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────────┐ │
│  │  Lint   │───▶│  Test   │───▶│  Build  │───▶│   Deploy    │ │
│  │ (ruff)  │    │(pytest) │    │(docker) │    │(SSH + pull)  │ │
│  └─────────┘    └─────────┘    └─────────┘    └─────────────┘ │
│       │              │              │               │           │
│       │         ┌────┴────┐         │          ┌────┴────┐     │
│       │         │Services │         │          │Rollback │     │
│       │         │PG + Redis│        │          │on fail  │     │
│       │         └─────────┘         │          └─────────┘     │
│       │                             │                           │
│  On: push/PR/dispatch          On: main only             On: main only │
└─────────────────────────────────────────────────────────────────┘
```

### Trigger Matrix

| Event | Branches | Jobs Executed |
|-------|----------|--------------|
| push | main | lint → test → build → deploy |
| push | feat/*, fix/* | lint → test |
| pull_request | main (target) | lint → test |
| workflow_dispatch | any | lint → test → build → deploy |

### Job Details

#### Job 1: Lint
- Runner: `ubuntu-latest`
- Python: 3.11
- Steps: checkout → setup-python → pip install ruff → ruff check → ruff format --check
- Working directory: `reddit_saas/`

#### Job 2: Test
- Runner: `ubuntu-latest`
- Python: 3.11
- Services: PostgreSQL 16 (pgvector), Redis 7
- Steps: checkout → setup-python → install deps → alembic upgrade → pytest
- Environment variables: DATABASE_URL, REDIS_URL, SECRET_KEY, ENVIRONMENT=test, TZ
- Outputs: JUnit XML report, Hypothesis DB on failure
- Working directory: `reddit_saas/`

#### Job 3: Build
- Runner: `ubuntu-latest`
- Condition: `github.ref == 'refs/heads/main'` or `workflow_dispatch`
- Steps: checkout → login GHCR → docker build → tag (SHA + latest) → push
- Uses: `docker/build-push-action` with layer caching
- Context: `reddit_saas/`

#### Job 4: Deploy
- Runner: `ubuntu-latest`
- Condition: `github.ref == 'refs/heads/main'` or `workflow_dispatch`
- Steps: SSH → save current tag → pull new image → docker compose up → health check → rollback if failed
- Rollback: revert to saved tag, restart, re-check health
- Notification: GitHub commit status + job summary

### Deployment Flow

```
Deploy Job:
1. SSH to 161.35.27.165
2. Record current image digest (for rollback)
3. docker pull ghcr.io/siladucha/atmo_reddit:$SHA
4. docker tag ... as reddit-saas-app:latest
5. docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
6. Wait 30s for containers to start + migrations
7. curl http://localhost/health → check version matches
8. If health OK → success
9. If health FAIL → rollback:
   a. docker tag previous_digest as reddit-saas-app:latest
   b. docker compose up -d
   c. Verify health again
   d. If still fails → mark as manual intervention needed
```

### Secrets Required

| Secret Name | Purpose |
|-------------|---------|
| `DEPLOY_SSH_KEY` | SSH private key for server access |
| `DEPLOY_HOST` | Server IP (161.35.27.165) |
| `DEPLOY_USER` | SSH user (root) |
| `POSTGRES_PASSWORD` | For test DB (CI only) |
| `REDIS_PASSWORD` | For test Redis (CI only) |

Note: `GITHUB_TOKEN` is automatically available for GHCR push.

### File Structure

```
.github/
└── workflows/
    └── ci-cd.yml          # Main pipeline workflow
reddit_saas/
├── .env.ci.example        # Reference for CI environment variables
└── (existing files)
```

## Correctness Properties

Since this feature is entirely infrastructure/configuration (GitHub Actions YAML, deployment scripts), there are no code logic components suitable for property-based testing. The correctness is verified by:

1. **Pipeline execution itself** — if tests pass in CI, the regression suite validates the codebase
2. **Health check after deploy** — verifies the deployed version matches expectations
3. **Rollback mechanism** — tested by the deployment flow itself

All acceptance criteria are testable as integration examples (run the pipeline, observe the result) rather than property-based tests.

## Design Decisions

### Why GHCR over Docker Hub
- Free for public repos, generous limits for private
- Native GitHub Actions integration via `GITHUB_TOKEN`
- No additional credentials to manage
- Image lifecycle tied to repository

### Why SSH deploy over self-hosted runner
- Simpler setup (no runner agent on server)
- Server already has SSH access configured
- No persistent process needed on the droplet
- Matches current manual workflow (just automated)

### Why not a staging environment
- Single DigitalOcean droplet ($23/mo budget)
- Health check + rollback provides safety net
- Staging adds complexity without proportional value at current scale
- Can add staging when moving to multi-droplet or AWS

### Why image pull instead of build on server
- Build on server uses server CPU/RAM (limited: 2 vCPU, 4 GB)
- Pre-built image is tested (same artifact that passed CI)
- Faster deploys (pull ~30s vs build ~3-5 min)
- Reproducible: exact same image in CI and production

### Why not deploy marketing site in same pipeline
- Marketing site has separate build context (`../marketing_site`)
- Different change frequency
- Can add as a separate job later if needed
- Current scope: main app + celery workers only
