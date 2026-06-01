# Implementation Tasks

## Task 1: Create GitHub Actions Workflow File — Lint Job

- [ ] 1.1 Create `.github/workflows/ci-cd.yml` with workflow name, trigger configuration (push to main/feat/fix branches, pull_request to main, workflow_dispatch)
- [ ] 1.2 Add the `lint` job: ubuntu-latest runner, Python 3.11 setup, install ruff, run `ruff check reddit_saas/` and `ruff format --check reddit_saas/`
- [ ] 1.3 Verify lint job works by running `ruff check` and `ruff format --check` locally to confirm no pre-existing failures

## Task 2: Add Test Job with Service Containers

- [ ] 2.1 Add `test` job depending on `lint`, with PostgreSQL 16 service container (image: `pgvector/pgvector:pg16`, env: POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, health check)
- [ ] 2.2 Add Redis 7 service container (image: `redis:7-alpine`, health check with `redis-cli ping`)
- [ ] 2.3 Configure test job environment variables: DATABASE_URL (pointing to service container), REDIS_URL, SECRET_KEY, ENVIRONMENT=test, TZ=Asia/Jerusalem, PYTHONPATH
- [ ] 2.4 Add steps: checkout, setup-python 3.11, install dependencies (`pip install -e ".[dev]"`), run Alembic migrations (`alembic upgrade head`), run pytest with JUnit XML output
- [ ] 2.5 Add step to upload JUnit XML report as artifact and display test summary in job summary using `dorny/test-reporter` or native summary
- [ ] 2.6 Add conditional step to upload `.hypothesis/` directory as artifact when tests fail (for PBT failure reproduction)

## Task 3: Add Docker Build Job with GHCR Push

- [ ] 3.1 Add `build` job depending on `test`, conditioned on `github.ref == 'refs/heads/main' || github.event_name == 'workflow_dispatch'`
- [ ] 3.2 Add steps: checkout, login to GHCR using `docker/login-action` with `GITHUB_TOKEN`
- [ ] 3.3 Add Docker build+push step using `docker/build-push-action` with context `reddit_saas/`, tags `ghcr.io/siladucha/atmo_reddit:${{ github.sha }}` and `ghcr.io/siladucha/atmo_reddit:latest`, layer caching via `cache-from`/`cache-to` GitHub Actions cache
- [ ] 3.4 Add Docker label with version from `reddit_saas/VERSION` file (read in a prior step)

## Task 4: Add Deploy Job with Health Check

- [ ] 4.1 Add `deploy` job depending on `build`, conditioned on main branch or workflow_dispatch
- [ ] 4.2 Add SSH setup step: install SSH key from `secrets.DEPLOY_SSH_KEY`, configure known_hosts for `secrets.DEPLOY_HOST`
- [ ] 4.3 Add deploy script step via SSH: save current image digest, pull new image from GHCR, tag as `reddit-saas-app:latest`, run `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`
- [ ] 4.4 Add health check step: wait 30s, then `curl -sf http://localhost/health` and verify response contains expected version
- [ ] 4.5 Add rollback step (runs only if health check fails): revert to previous image digest, restart compose, verify health again
- [ ] 4.6 Add failure notification step: post deployment status to job summary with rollback details if triggered

## Task 5: Configure GitHub Repository Secrets

- [ ] 5.1 Document required secrets in a `.github/SECRETS.md` file: DEPLOY_SSH_KEY, DEPLOY_HOST, DEPLOY_USER (with setup instructions)
- [ ] 5.2 Generate a dedicated SSH deploy key pair (ed25519) and document how to add the public key to the server's `authorized_keys`
- [ ] 5.3 Update `.gitignore` to exclude any local secret/key files that might accidentally be committed

## Task 6: Update Server for Image-Based Deployment

- [ ] 6.1 Document server preparation steps: install Docker credential helper for GHCR, or use `docker login ghcr.io` with a PAT/token
- [ ] 6.2 Update `docker-compose.yml` (or create `docker-compose.prod.yml` override) to reference the GHCR image instead of local build for the `app` service
- [ ] 6.3 Ensure `entrypoint.sh` continues to handle Alembic migrations on container start (no changes needed, just verify)

## Task 7: Create CI Environment Configuration

- [ ] 7.1 Create `.env.ci.example` file documenting all environment variables needed for CI test execution
- [ ] 7.2 Add mock/dummy values for external API keys (REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, LITELLM_API_KEY) to prevent test failures from missing env vars
- [ ] 7.3 Verify all 57 test files pass locally with the CI-equivalent environment configuration (no external API calls)

## Task 8: Validate Pipeline End-to-End

- [ ] 8.1 Push the workflow file to a feature branch and verify lint + test jobs execute successfully
- [ ] 8.2 Create a PR to main and verify the pipeline runs lint + test (no build/deploy)
- [ ] 8.3 Merge to main and verify full pipeline: lint → test → build → deploy with health check passing
- [ ] 8.4 Test rollback by temporarily breaking the health check and verifying the rollback mechanism works
