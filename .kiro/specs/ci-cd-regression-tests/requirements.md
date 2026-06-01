# Requirements Document

## Introduction

CI/CD pipeline with regression tests for the RAMP Reddit Marketing SaaS platform. The pipeline automates code quality checks, runs the full regression test suite (57 test files including property-based tests), builds Docker images, and deploys to the DigitalOcean production server — replacing the current manual rsync + docker compose rebuild workflow.

The pipeline uses GitHub Actions (repo: `siladucha/atmo_reddit`) and triggers on push/PR events. It includes linting, unit/property-based testing with PostgreSQL + Redis services, Docker image building, and automated deployment with rollback capability.

## Glossary

- **Pipeline**: A GitHub Actions workflow that executes a sequence of jobs (lint, test, build, deploy) in response to repository events
- **Regression_Test_Suite**: The collection of 57 existing pytest test files in `tests/`, including property-based tests using Hypothesis, that validate platform correctness
- **Runner**: A GitHub-hosted virtual machine (Ubuntu) that executes pipeline jobs
- **Workflow_File**: A YAML configuration file in `.github/workflows/` that defines pipeline triggers, jobs, and steps
- **Service_Container**: A Docker container (PostgreSQL, Redis) started by GitHub Actions alongside the Runner to provide test dependencies
- **Artifact**: A build output (Docker image) stored in a container registry for deployment
- **Deploy_Target**: The DigitalOcean production server at `161.35.27.165` running Docker Compose
- **Rollback**: The process of reverting the Deploy_Target to the previous working version after a failed deployment
- **GHCR**: GitHub Container Registry — stores Docker images built by the Pipeline

## Requirements

### Requirement 1: Pipeline Trigger Configuration

**User Story:** As a developer, I want the pipeline to run automatically on code changes, so that regressions are caught before they reach production.

#### Acceptance Criteria

1. WHEN a push is made to the `main` branch, THE Pipeline SHALL execute the full workflow (lint, test, build, deploy)
2. WHEN a pull request is opened or updated targeting the `main` branch, THE Pipeline SHALL execute the lint and test jobs without deploying
3. THE Pipeline SHALL allow manual trigger via `workflow_dispatch` for on-demand execution
4. WHEN a push is made to branches matching `feat/*` or `fix/*`, THE Pipeline SHALL execute lint and test jobs only

### Requirement 2: Code Quality Stage

**User Story:** As a developer, I want automated linting on every change, so that code style issues are caught before review.

#### Acceptance Criteria

1. THE Pipeline SHALL run `ruff check` on the `reddit_saas/` directory as the first job
2. THE Pipeline SHALL run `ruff format --check` to verify code formatting compliance
3. IF the linting job fails, THEN THE Pipeline SHALL stop execution and report the failure without proceeding to tests
4. THE Pipeline SHALL use Python 3.11 matching the production runtime version
5. THE Pipeline SHALL complete the lint job within 2 minutes

### Requirement 3: Regression Test Execution

**User Story:** As a developer, I want all existing tests to run automatically in CI, so that regressions are detected before deployment.

#### Acceptance Criteria

1. THE Pipeline SHALL execute `pytest tests/` with all 57 test files in the Regression_Test_Suite
2. THE Pipeline SHALL provision a PostgreSQL 16 Service_Container with the `pgvector/pgvector:pg16` image for database-dependent tests
3. THE Pipeline SHALL provision a Redis 7 Service_Container for tests requiring cache/lock functionality
4. THE Pipeline SHALL install all project dependencies including the `dev` optional group (pytest, hypothesis, ruff)
5. WHEN a test fails, THE Pipeline SHALL report the specific test name and failure output in the job summary
6. THE Pipeline SHALL run Alembic migrations against the test database before executing tests
7. THE Pipeline SHALL set the `PYTHONPATH` to include the `reddit_saas/` directory matching the production configuration
8. THE Pipeline SHALL complete the test job within 10 minutes for the full Regression_Test_Suite

### Requirement 4: Test Environment Configuration

**User Story:** As a developer, I want the CI test environment to mirror production, so that tests produce reliable results.

#### Acceptance Criteria

1. THE Pipeline SHALL configure the test database connection via `DATABASE_URL` environment variable pointing to the PostgreSQL Service_Container
2. THE Pipeline SHALL configure the Redis connection via `REDIS_URL` environment variable pointing to the Redis Service_Container
3. THE Pipeline SHALL set `ENVIRONMENT=test` to activate test-specific configuration paths
4. THE Pipeline SHALL provide a `SECRET_KEY` environment variable for JWT operations during tests
5. THE Pipeline SHALL set `TZ=Asia/Jerusalem` matching the production timezone configuration
6. IF a test requires external API credentials (Reddit, LLM), THEN THE Pipeline SHALL use mock values to prevent external calls

### Requirement 5: Docker Image Build

**User Story:** As a developer, I want Docker images built and stored automatically after tests pass, so that deployment uses verified artifacts.

#### Acceptance Criteria

1. WHEN the test job passes on the `main` branch, THE Pipeline SHALL build the Docker image using the existing `reddit_saas/Dockerfile`
2. THE Pipeline SHALL tag the image with both the git SHA and `latest`
3. THE Pipeline SHALL push the built image to GHCR at `ghcr.io/siladucha/atmo_reddit`
4. THE Pipeline SHALL use Docker layer caching to reduce build time on subsequent runs
5. THE Pipeline SHALL complete the build job within 5 minutes
6. THE Pipeline SHALL include the application version from `reddit_saas/VERSION` as a Docker label

### Requirement 6: Automated Deployment

**User Story:** As a developer, I want successful builds on main to deploy automatically, so that the manual rsync workflow is eliminated.

#### Acceptance Criteria

1. WHEN the build job succeeds on the `main` branch, THE Pipeline SHALL deploy to the Deploy_Target via SSH
2. THE Pipeline SHALL pull the new Docker image on the Deploy_Target and restart services using `docker compose`
3. THE Pipeline SHALL use the production compose files (`docker-compose.yml` + `docker-compose.prod.yml`) for deployment
4. THE Pipeline SHALL run Alembic migrations on the production database as part of deployment (handled by `entrypoint.sh`)
5. WHEN deployment completes, THE Pipeline SHALL verify the `/health` endpoint returns HTTP 200 with the expected version
6. THE Pipeline SHALL complete the deployment within 5 minutes (excluding image pull time)
7. THE Pipeline SHALL use GitHub Secrets for SSH keys and server credentials, with no secrets stored in the repository

### Requirement 7: Rollback on Deployment Failure

**User Story:** As a developer, I want automatic rollback when deployment fails, so that production remains available.

#### Acceptance Criteria

1. IF the health check fails after deployment, THEN THE Pipeline SHALL revert to the previous Docker image tag on the Deploy_Target
2. IF the Rollback is triggered, THEN THE Pipeline SHALL restart services with the previous image and verify health again
3. IF the Rollback succeeds, THEN THE Pipeline SHALL report the incident as a workflow failure with the rollback details
4. IF the Rollback also fails, THEN THE Pipeline SHALL send a notification and mark the deployment as requiring manual intervention
5. THE Pipeline SHALL store the previous successful image tag as a deployment reference for Rollback purposes

### Requirement 8: Secrets Management

**User Story:** As a developer, I want secrets handled securely in the pipeline, so that credentials are never exposed in logs or code.

#### Acceptance Criteria

1. THE Pipeline SHALL store all sensitive values (SSH keys, server IP, database passwords, API keys) as GitHub Actions encrypted secrets
2. THE Pipeline SHALL mask secret values in all job logs automatically via GitHub Actions built-in masking
3. THE Pipeline SHALL use a dedicated SSH deploy key (not a personal key) for server access
4. IF a step outputs a value that matches a secret pattern, THEN THE Pipeline SHALL redact the value from logs
5. THE Pipeline SHALL use `GITHUB_TOKEN` for GHCR authentication without additional registry credentials

### Requirement 9: Pipeline Notifications

**User Story:** As a developer, I want to be notified of pipeline failures, so that I can respond quickly to broken builds.

#### Acceptance Criteria

1. IF any pipeline job fails, THEN THE Pipeline SHALL create a visible failure status on the GitHub commit/PR
2. WHEN a deployment Rollback is triggered, THE Pipeline SHALL post a summary comment on the relevant commit
3. THE Pipeline SHALL provide a clear job summary with duration, test count, and pass/fail status for each stage

### Requirement 10: Test Result Reporting

**User Story:** As a developer, I want structured test reports in CI, so that I can quickly identify which tests failed and why.

#### Acceptance Criteria

1. THE Pipeline SHALL generate a JUnit XML test report via `pytest --junitxml=report.xml`
2. THE Pipeline SHALL upload the test report as a workflow Artifact for download
3. THE Pipeline SHALL display test results summary (passed/failed/skipped counts) in the GitHub Actions job summary
4. WHEN property-based tests fail, THE Pipeline SHALL preserve the Hypothesis database (`.hypothesis/`) as an Artifact for reproducing failures locally
