# Implementation Plan: Staging & CI/CD Infrastructure

## Overview

This plan converts the 20-step migration plan from the design document into actionable coding/configuration tasks. Each task produces documentation, configuration files, or shell scripts that a DevOps engineer can execute. Tasks are grouped logically and ordered by dependency chain.

The critical path is: Secrets Backup → CI Workflow → GHCR Push → Parameterize Compose → Staging Setup → Deploy Jobs → End-to-End Verification.

## Tasks

- [ ] 1. Foundation: Secrets backup and Git branch strategy
  - [ ] 1.1 Back up ENCRYPTION_KEY and .env off-server
    - SSH to production, copy `/app/.env` to a secure off-server location (1Password, encrypted file, or team vault)
    - Document the backup location and access procedure in a `docs/secrets-backup.md` file
    - Verify ENCRYPTION_KEY value is preserved and accessible
    - _Requirements: 5.2, 6.4_
  - [ ] 1.2 Set up GitHub branch protection on `main`
    - Configure branch protection rules: require PR, require CI status checks to pass, require 1 approval
    - Block direct push to `main` (force push disabled)
    - Document the protection rules in a comment or project wiki
    - _Requirements: 7.2, 11.3_
  - [ ] 1.3 Create `develop` branch from `main`
    - Create and push `develop` branch: `git checkout -b develop && git push -u origin develop`
    - Set `develop` as the staging deployment source
    - _Requirements: 7.2, 8.3_

- [ ] 2. CI Pipeline: GitHub Actions workflow
  - [ ] 2.1 Write GitHub Actions CI workflow file (lint, test, build)
    - Create `.github/workflows/ci.yml` with jobs: lint (`ruff check`), format check (`ruff format --check`), unit tests (`pytest` with PostgreSQL + Redis service containers), security scan (`pip-audit`), Docker image build
    - Configure test job to run Alembic migrations against test DB
    - Set workflow triggers: push to `develop`, push to `main`, PR to `main`
    - _Requirements: 7.1, 7.3, 15.1_
  - [ ] 2.2 Configure GHCR image push in CI workflow
    - Add step to authenticate with GHCR using `GITHUB_TOKEN`
    - Push images with tags: `sha-<commit>`, `develop` (for develop branch), `latest` (for main branch)
    - Build both `ramp-app` and `ramp-marketing` images
    - _Requirements: 7.1, 7.4_
  - [ ] 2.3 Create deploy SSH key and configure GitHub Secrets
    - Generate ED25519 SSH key pair for CI → server deploys
    - Add public key to server `/root/.ssh/authorized_keys` (or `deploy` user)
    - Add private key as `SSH_PRIVATE_KEY` GitHub Secret
    - Add `SERVER_HOST` (161.35.27.165) as GitHub Secret
    - _Requirements: 13.2, 13.4_

- [ ] 3. Checkpoint - Verify CI builds pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Docker Compose parameterization for registry-based deploys
  - [ ] 4.1 Parameterize docker-compose.yml to pull images from GHCR
    - Modify `docker-compose.yml` to accept `IMAGE_TAG` environment variable for app/marketing images
    - Change `image:` directives from local build to `ghcr.io/OWNER/ramp-app:${IMAGE_TAG:-latest}`
    - Ensure production compose override still works with new image source
    - Test: `docker compose config` validates syntax with variable substitution
    - _Requirements: 7.1, 7.5_

- [ ] 5. Staging environment setup
  - [ ] 5.1 Add DNS A record for staging.gorampit.com
    - Create A record pointing `staging.gorampit.com` to `161.35.27.165` in DNS provider
    - Verify resolution: `dig staging.gorampit.com`
    - _Requirements: 8.1, 8.2_
  - [ ] 5.2 Create /staging/ directory with compose files and .env
    - Create `/staging/docker-compose.yml` and `/staging/docker-compose.staging.yml` with staging overrides (half memory limits, reduced concurrency)
    - Create `/staging/.env` with unique secrets (different DB password, Redis password, SECRET_KEY, ENCRYPTION_KEY)
    - Set `POSTING_DISABLED=true` and `ENVIRONMENT=staging` in staging .env
    - Configure staging to use ports 8080/8443, project name `staging`, separate volumes (`staging_pgdata`)
    - Configure staging Celery Beat to disable Reddit API and LLM API tasks
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 13.4_
  - [ ] 5.3 Issue SSL certificate for staging.gorampit.com
    - Run `certbot certonly --standalone -d staging.gorampit.com` on server
    - Configure staging nginx to use the new certificate
    - Verify HTTPS works: `curl https://staging.gorampit.com/health`
    - _Requirements: 14.4_
  - [ ] 5.4 Deploy and verify staging environment
    - Pull images and start staging: `docker compose --project-name staging up -d`
    - Verify health endpoint returns 200 with correct version and `env: staging`
    - Verify staging DB is isolated (different volume, different password)
    - Verify staging cannot reach production data
    - _Requirements: 8.1, 8.2, 12.3_

- [ ] 6. Checkpoint - Verify staging environment is running and isolated
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Deploy jobs and pipeline automation
  - [ ] 7.1 Add staging deploy job to GitHub Actions
    - Add job triggered on `develop` push (after CI passes): SSH to server → set IMAGE_TAG → docker compose pull → docker compose up -d
    - Use GitHub Actions concurrency groups to prevent simultaneous deploys
    - _Requirements: 7.1, 8.3_
  - [ ] 7.2 Add smoke test job after staging deploy
    - After deploy, poll `/health` endpoint for up to 60s (every 5s)
    - Verify HTTP 200, correct version matches commit SHA
    - On failure: trigger rollback to previous image tag
    - _Requirements: 7.1, 12.3_
  - [ ] 7.3 Add production deploy job with approval gate
    - Add job triggered on `main` push: requires `production` GitHub Environment approval
    - Before deploy: run `pg_dump` backup via SSH
    - Deploy: SSH → set IMAGE_TAG → docker compose pull → docker compose up -d
    - Post-deploy: poll `/health` for 60s, auto-rollback on failure
    - _Requirements: 7.1, 7.5, 7.6, 15.4_
  - [ ] 7.4 Implement auto-rollback on health check failure
    - If health check fails 5 times over 60s post-deploy, automatically set IMAGE_TAG to previous commit SHA and redeploy
    - Log rollback event and trigger critical notification
    - _Requirements: 7.6, 12.4_

- [ ] 8. Notifications and monitoring
  - [ ] 8.1 Configure Telegram bot notifications in CI
    - Create Telegram bot, add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to GitHub Secrets
    - Add notification steps for: build failed, staging deployed, smoke tests failed, rollback triggered, production deployed, production health failed
    - Format messages with commit SHA, branch, duration, and status
    - _Requirements: 12.1, 12.2_
  - [ ] 8.2 Add pre-deploy database backup step to production job
    - Before restarting production containers, run: `docker compose exec -T db pg_dump -U reddit_saas_user -d reddit_saas --format=custom -f /tmp/backup_pre_deploy_$(date +%Y%m%d_%H%M%S).custom`
    - Retain last 5 backups, delete older ones
    - _Requirements: 6.4, 15.4_

- [ ] 9. Checkpoint - Verify full pipeline (push to deploy to notification)
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. End-to-end verification and cutover
  - [ ] 10.1 Test full pipeline end-to-end
    - Push a test commit to `develop` → verify staging deploys automatically
    - Create PR from `develop` to `main` → verify CI runs
    - Merge PR → verify production approval gate appears
    - Approve → verify production deploys and Telegram notification arrives
    - Verify rollback: deploy a deliberately broken commit, confirm auto-rollback works
    - _Requirements: 9.1, 9.4_
  - [ ] 10.2 Disable rsync deploy and add certbot deploy hook
    - Remove developer SSH key from server's authorized_keys (keep only deploy key)
    - Or: document that rsync is deprecated and CI is the only deploy path
    - Add certbot renewal hook: `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh`
    - _Requirements: 14.3_

- [ ] 11. Runbook and documentation
  - [ ] 11.1 Write operational runbook (deploy, rollback, recovery)
    - Create `docs/runbook-cicd.md` with sections: normal deploy flow, manual rollback procedure, disaster recovery scenarios, staging reset procedure, secret rotation procedure
    - Include commands for: emergency rollback, force-deploy specific version, staging DB reset, checking pipeline status
    - Reference the post-migration verification checklist from the design document
    - _Requirements: 5.1, 5.3, 6.1, 6.2, 9.5_

- [ ] 12. Final checkpoint - Verify all systems operational
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- No property-based tests are needed — this feature produces infrastructure configuration and documentation, not application logic
- All steps can be performed without production downtime (additive transition)
- The critical path is: 1.1 → 2.1 → 2.2 → 4.1 → 5.2 → 7.1 → 7.3 → 10.1
- Parallel tracks: steps 1.2/1.3/2.3/5.1 are independent and can be done first
- Steps 8.1, 10.2, 11.1 are independent of the main deploy flow
- Blocker B7 (ENCRYPTION_KEY backup) must be resolved in step 1.1 before any infrastructure changes

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "2.3", "5.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2", "4.1"] },
    { "id": 3, "tasks": ["5.2", "5.3"] },
    { "id": 4, "tasks": ["5.4", "7.1"] },
    { "id": 5, "tasks": ["7.2", "7.3", "8.1"] },
    { "id": 6, "tasks": ["7.4", "8.2"] },
    { "id": 7, "tasks": ["10.1"] },
    { "id": 8, "tasks": ["10.2", "11.1"] }
  ]
}
```
