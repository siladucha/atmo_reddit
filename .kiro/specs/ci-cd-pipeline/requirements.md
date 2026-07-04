# Requirements Document

## Introduction

This feature implements a CI/CD pipeline for the RAMP platform using GitHub Actions. The pipeline automates testing, building, and deploying the application to two environments: Staging (fully automated on push) and Production (manual approval required). The system replaces the current manual rsync + docker compose workflow while preserving the same on-server build strategy (no container registry needed). Rollback capability is included for production deployments.

## Prerequisites (must be completed before pipeline is operational)

1. **Deploy SSH key** must be generated and authorized on both servers (`~/.ssh/authorized_keys` on staging and production)
2. **GitHub repository plan** must support Environments with protection rules (Pro/Team) — OR use `workflow_dispatch` as manual gate alternative
3. **Branch `feature/june-updates` must be merged to `main`** — pipeline triggers on `main`
4. **Alembic heads must be merged** — run `alembic merge heads` if multiple exist before first CI run

## Glossary

- **Pipeline**: A GitHub Actions workflow that automates testing, building, and deploying code
- **Staging_Server**: DigitalOcean droplet at 167.172.191.42 (staging.gorampit.com), 2 vCPU / 2GB RAM, accessed via `ssh ramp-staging`
- **Production_Server**: DigitalOcean droplet at 161.35.27.165 (gorampit.com), 2 vCPU / 4GB RAM, accessed via `ssh ramp`
- **Health_Endpoint**: `https://{domain}/health` — returns JSON `{"version": "X.Y.Z", "env": "...", "database": "ok", "redis": "ok", "status": "ok"}`. Returns 503 when DB/Redis unreachable.
- **Rollback**: Reverting a deployment by restoring the previous Docker image tag and restarting containers (code rollback only — database migrations are NOT automatically reversed)
- **GitHub_Secrets**: Encrypted environment variables stored in the GitHub repository settings, injected into workflow runs
- **Smoke_Test**: A post-deploy verification that confirms key endpoints respond with expected HTTP codes
- **Image_Tag_Previous**: Docker image tagged `reddit-saas-app:previous` before each deploy — enables instant rollback without file copying
- **App_Services**: The set of containers restarted during deploy: `app`, `celery`, `celery-fast`, `celery-beat`, `nginx`, `marketing`. DB and Redis are NEVER restarted by the pipeline.

## Requirements

### Requirement 1: Automated Test Execution in CI

**User Story:** As the sole engineer, I want tests to run automatically on every push, so that I catch regressions before code reaches any server.

#### Acceptance Criteria

1. WHEN a commit is pushed to any branch, THE Pipeline SHALL run the full pytest suite in a GitHub Actions job
2. THE Pipeline SHALL provision a PostgreSQL 16 service container and a Redis 7 service container, and expose their connection URLs as environment variables accessible to the test runner
3. THE Pipeline SHALL install Python 3.11 dependencies from pyproject.toml and execute tests with `pytest --tb=short -q --hypothesis-seed=0 -x` (deterministic hypothesis, fail-fast)
4. IF any test fails, THEN THE Pipeline SHALL mark the workflow as failed and prevent subsequent deploy jobs from executing via job-level dependency constraints
5. THE Pipeline SHALL complete the test job within 10 minutes for a test suite of 50+ files (property-based tests run with `--hypothesis-deadline=5000` to cap shrinking)
6. THE Pipeline SHALL cache pip dependencies between runs using a cache key derived from a hash of pyproject.toml, and SHALL restore cached dependencies on cache hit without re-running pip install
7. IF a service container fails to become healthy within 30 seconds, THEN THE Pipeline SHALL fail the workflow and report the unhealthy service in the job output
8. THE Pipeline SHALL run `alembic heads` and verify exactly ONE head exists; IF multiple heads detected, THE Pipeline SHALL fail with message "Alembic multiple heads — run `alembic merge heads` locally"

### Requirement 2: Automated Deployment to Staging

**User Story:** As the sole engineer, I want code to deploy automatically to staging after tests pass, so that I can validate changes in a production-like environment without manual steps.

#### Acceptance Criteria

1. WHEN tests pass on the `main` branch, THE Pipeline SHALL automatically deploy code to the Staging_Server
2. THE Pipeline SHALL rsync the `reddit_saas/` directory to the Staging_Server at `/app/`, excluding `.venv/`, `__pycache__/`, `.hypothesis/`, `.git/`, `*.pyc`, `.DS_Store`, `logs/`, `.env`, `.claude/`, `.kiro/`, `.vscode/`
3. THE Pipeline SHALL execute `docker compose -f docker-compose.yml -f docker-compose.prod.yml build` on the Staging_Server (same compose overlay as production for parity), with a maximum build timeout of 300 seconds
4. THE Pipeline SHALL gracefully stop Celery workers before restart: `docker compose stop celery celery-fast celery-beat` (allows in-flight tasks to finish within 30s SIGTERM window)
5. THE Pipeline SHALL remove the Celery Beat schedule file before restart: `docker compose exec celery-beat rm -f /tmp/celerybeat-schedule` (prevents catch-up storm of overdue tasks)
6. THE Pipeline SHALL execute `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-deps app celery celery-fast celery-beat nginx marketing` (never restart db/redis)
7. THE Pipeline SHALL use SSH key authentication stored in GitHub_Secrets (secret: `DEPLOY_SSH_KEY`) to connect to the Staging_Server (secret: `STAGING_SERVER_IP`)
8. WHEN containers start, THE Pipeline SHALL wait 15 seconds (for migrations + startup), then poll the Health_Endpoint every 5 seconds for up to 30 seconds total, reporting success only on HTTP 200
9. IF any deployment step (rsync, docker build, docker stop, or docker up) fails with a non-zero exit code, THEN THE Pipeline SHALL halt the sequence, skip remaining steps, and report the failure with step name and exit code
10. THE Pipeline SHALL allow manual `workflow_dispatch` to deploy any branch to staging for ad-hoc testing

### Requirement 3: Post-Deploy Health Check

**User Story:** As the sole engineer, I want automated health verification after every deploy, so that I know immediately if a deployment broke the application.

#### Acceptance Criteria

1. WHEN deployment completes on either environment, THE Pipeline SHALL wait an initial 15 seconds (container startup + migrations), then send HTTP GET to the Health_Endpoint
2. THE Pipeline SHALL retry up to 6 times with 10-second intervals between attempts (total window: ~75 seconds including initial wait)
3. WHEN the Health_Endpoint returns HTTP 200, THE Pipeline SHALL compare the `version` field in the JSON response against the contents of `reddit_saas/VERSION` (trimmed, exact string match)
4. IF the Health_Endpoint returns HTTP 503 (DB/Redis starting up), THE Pipeline SHALL treat this as a transient failure and continue retrying (NOT trigger rollback)
5. IF the Health_Endpoint does not return HTTP 200 with correct version within all 6 retry attempts, THEN THE Pipeline SHALL mark the deployment as failed
6. WHEN the health check passes (HTTP 200 + version match), THE Pipeline SHALL output the verified version and environment in the workflow step summary

### Requirement 4: Manual Approval Gate for Production

**User Story:** As the sole engineer, I want production deployments to require explicit manual approval, so that untested changes never reach the live system accidentally.

#### Acceptance Criteria

1. THE Pipeline SHALL require a manual approval step before deploying to the Production_Server
2. IF GitHub Environments with required reviewers is available (Pro/Team plan), THE Pipeline SHALL use it; OTHERWISE THE Pipeline SHALL use a separate `workflow_dispatch`-triggered production workflow as the manual gate
3. WHEN staging deployment succeeds and health check passes, THE Pipeline SHALL output a "Ready for production" summary with commit SHA, branch, version, and test result counts
4. THE Pipeline SHALL only allow production deployment from the `main` branch (other branches cannot be deployed to production)
5. IF approval is not granted within 24 hours, THEN THE Pipeline SHALL expire the deployment request without deploying
6. THE Pipeline SHALL use a `concurrency` group (`deploy-production`) to prevent overlapping production deployments

### Requirement 5: Production Deployment with Pre-Deploy Image Backup

**User Story:** As the sole engineer, I want the current working state preserved before each deploy, so that I can roll back instantly if something goes wrong.

#### Acceptance Criteria

1. WHEN production deployment is approved, THE Pipeline SHALL tag the current Docker image: `docker tag reddit-saas-app:latest reddit-saas-app:previous` on the Production_Server before building new image
2. THE Pipeline SHALL also save the current VERSION to `/app/backups/previous_version.txt` for rollback verification
3. IF the image tagging fails, THEN THE Pipeline SHALL abort the deployment and report error
4. THE Pipeline SHALL rsync new code to `/app/` on the Production_Server using same excludes as staging
5. THE Pipeline SHALL gracefully stop Celery workers: `docker compose stop celery celery-fast celery-beat` (30s SIGTERM window)
6. THE Pipeline SHALL remove Celery Beat schedule file before restart
7. THE Pipeline SHALL build and restart using production overlay: `docker compose -f docker-compose.yml -f docker-compose.prod.yml build` and `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-deps app celery celery-fast celery-beat nginx marketing`
8. WHEN containers restart, THE Pipeline SHALL run the health check per Requirement 3 (15s wait + 6 retries × 10s)

**Important constraint:** This is CODE-ONLY rollback. If the new deployment included a database migration that already executed (DDL changes), rolling back code may leave the app incompatible with the new schema. In that case, manual intervention is required.

### Requirement 6: Automated Rollback on Health Check Failure

**User Story:** As the sole engineer, I want the system to automatically roll back a failed production deploy, so that the live application recovers without my manual intervention.

#### Acceptance Criteria

1. IF the Health_Endpoint fails all retry attempts after a production deployment (per Requirement 3), THEN THE Pipeline SHALL initiate an automatic rollback
2. THE Pipeline SHALL restore the previous image: `docker tag reddit-saas-app:previous reddit-saas-app:latest`
3. THE Pipeline SHALL restart App_Services: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-deps app celery celery-fast celery-beat nginx marketing`
4. IF no `reddit-saas-app:previous` image exists, THEN THE Pipeline SHALL skip rollback, output alert, and stop with failure status indicating manual intervention required
5. THE Pipeline SHALL complete rollback (tag + restart + health verify) within 2 minutes
6. WHEN rollback containers start, THE Pipeline SHALL verify Health_Endpoint returns HTTP 200 with version matching `/app/backups/previous_version.txt`
7. IF the rollback health check also fails, THEN THE Pipeline SHALL output critical alert via workflow annotations and stop (manual intervention required)
8. THE Pipeline SHALL log each rollback step (tag restore, restart, health check) with UTC timestamps

**Limitation:** Rollback does NOT revert database migrations. If the failed deploy included a migration that executed successfully but the app code broke, rollback will restore old code against new schema. This scenario requires manual `alembic downgrade` — the pipeline will alert but not attempt automatic schema rollback.

### Requirement 7: Database Migration Handling

**User Story:** As the sole engineer, I want migrations to run automatically as part of deployment, so that schema changes are applied without manual SSH commands.

#### Acceptance Criteria

1. THE Pipeline SHALL rely on the existing `entrypoint.sh` mechanism that runs `alembic upgrade head` on container startup
2. WHEN the application container starts after deployment, THE Pipeline SHALL verify that migrations completed by checking the Health_Endpoint response (healthy response implies successful migration)
3. IF the application fails to start due to a migration error, THEN THE Pipeline SHALL treat this as a health check failure and trigger rollback on production
4. THE Pipeline SHALL NOT run migrations as a separate CI step — migrations execute inside the container during startup as the current architecture requires
5. THE Pipeline SHALL check for multiple Alembic heads in CI (Requirement 1, criterion 8) to prevent migration failures at deploy time

**Known limitation:** `entrypoint.sh` uses `stamp head` when tables already exist but alembic_version is inconsistent. This can mask migration bugs. Health check passes (app runs), but alembic state may be corrupted. Monitor `docker compose logs app | grep -i migration` after deploys with schema changes.

### Requirement 8: Secrets and SSH Key Management

**User Story:** As the sole engineer, I want SSH keys and server credentials managed securely, so that deploy access is never exposed in code or logs.

#### Acceptance Criteria

1. THE Pipeline SHALL store the SSH private key for server access in GitHub_Secrets under a dedicated secret name
2. THE Pipeline SHALL store the Staging_Server IP and Production_Server IP as separate GitHub_Secrets
3. THE Pipeline SHALL configure SSH with `StrictHostKeyChecking=no` for CI runners (known hosts change with server reprovisioning)
4. THE Pipeline SHALL mask all secret values in workflow logs to prevent accidental exposure
5. THE Pipeline SHALL use a dedicated SSH deploy key (not the developer's personal key) with access limited to the two servers

### Requirement 9: Deployment Notifications

**User Story:** As the sole engineer, I want to receive notifications about deployment outcomes, so that I know when deploys succeed or fail without monitoring the GitHub Actions UI.

#### Acceptance Criteria

1. WHEN a deployment to staging succeeds, THE Pipeline SHALL output a success summary in the GitHub Actions workflow with version and timestamp
2. WHEN a deployment to production succeeds, THE Pipeline SHALL output a success summary with version, timestamp, and the approved-by user
3. IF a deployment fails on either environment, THEN THE Pipeline SHALL output a failure summary with the failing step, error output, and affected environment
4. IF an automatic rollback is triggered on production, THEN THE Pipeline SHALL output a rollback notification with the reason for failure and the version rolled back to
5. THE Pipeline SHALL use GitHub Actions workflow annotations and job summaries for all notifications (extensible to Telegram/Slack webhook later)

### Requirement 10: Pipeline Configuration and Branch Strategy

**User Story:** As the sole engineer, I want a clear branch-to-environment mapping, so that I know exactly which branch triggers which deployment.

#### Acceptance Criteria

1. THE Pipeline SHALL trigger staging deployment on pushes to the `main` branch after tests pass
2. THE Pipeline SHALL allow manual `workflow_dispatch` to deploy any branch to staging for ad-hoc testing
3. THE Pipeline SHALL only allow production deployment from the `main` branch (other branches cannot be deployed to production)
4. THE Pipeline SHALL run tests on all branches on push (not just main) to provide early feedback on feature branches
5. THE Pipeline SHALL store workflow configuration in `.github/workflows/` at the repository root
6. THE Pipeline SHALL use `concurrency` groups to prevent overlapping deployments to the same environment: `deploy-staging` and `deploy-production`

### Requirement 11: Smoke Tests After Deployment

**User Story:** As the sole engineer, I want basic endpoint verification after deployment beyond just the health check, so that I can confirm critical functionality is working.

#### Acceptance Criteria

1. WHEN the health check passes after deployment, THE Pipeline SHALL additionally verify that the `/login` page returns HTTP 200
2. THE Pipeline SHALL verify that the `/admin` endpoint returns HTTP 302 (redirect to login when unauthenticated)
3. THE Pipeline SHALL verify that the `/api/sse/notifications` endpoint returns HTTP 401 when called without auth (confirms API routing works)
4. IF any smoke test fails, THEN THE Pipeline SHALL mark the deployment as degraded in the workflow summary (warning, not automatic rollback)
5. THE Pipeline SHALL complete all smoke tests within 30 seconds

### Requirement 12: Marketing Site Deployment

**User Story:** As the sole engineer, I want the marketing site deployed through the same pipeline, so that all deployments are automated and consistent.

#### Acceptance Criteria

1. WHEN the main application deploys successfully, THE Pipeline SHALL also rsync the `marketing_site/` directory (at repo root, NOT inside `reddit_saas/`) to `/marketing_site/` on the target server
2. THE Pipeline SHALL rebuild only the marketing Docker service from `/app/`: `docker compose -f docker-compose.yml -f docker-compose.prod.yml build marketing` and `docker compose up -d --no-deps marketing` (build context is `../marketing_site` relative to `/app/`)
3. THE Pipeline SHALL verify the marketing site health at `https://{domain}/mkt/health` after deployment
4. THE Pipeline SHALL support a separate lightweight workflow triggered on changes to `marketing_site/**` only — this workflow skips main app tests/build and only deploys marketing
