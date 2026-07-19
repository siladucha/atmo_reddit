# Development Workflow — CI/CD Discipline

## Status: TRANSITION IN PROGRESS (July 13, 2026)

**Old flow (DEPRECATED):** Mac → rsync → prod. No tests, no staging, no review.
**New flow (TARGET):** feature branch → PR to develop → CI → staging auto-deploy → verify → release tag → production deploy (same artifact).

---

## Why This Change

- Regression rate increased: multiple broken deploys in June-July 2026
- No test gate: code goes to production without test validation
- No staging verification: production is the first place code runs in Docker
- Last full regression run: June 19, 2026 (20+ days of unvalidated changes)
- Direct rsync to prod = one typo away from 500 Internal Server Error for clients

---

## Git Flow — Artifact Promotion Model

```
feature/xyz (local Mac)
    ↓ push to origin
    ↓ CI runs (tests + imports + alembic)
    ↓ PR → develop
    ↓ merge
develop
    ↓ CI builds Docker image artifact (SHA-tagged)
    ↓ Auto-deploy to staging (same artifact)
staging.gorampit.com (167.172.191.42)
    ↓ Verify (smoke test, 2 min)
    ↓ Operator approves
    ↓ git tag v1.2.0 && git push origin v1.2.0
    ↓ CI deploys SAME artifact to production
production gorampit.com (161.35.27.165)
```

### Core Principle: What Was Tested = What Gets Deployed

Production NEVER rebuilds code. It receives the exact Docker image that was already verified on staging. This eliminates "works on staging, breaks on prod" class of bugs.

### Branch Rules

- `develop` = staging-ready code. Auto-deploys to staging on every merge.
- `main` = production mirror. Updated only when release tag is created (fast-forward from develop).
- `feature/*` = active development (may be broken). Always branches from `develop`.
- Direct push to `develop` → allowed for hotfixes only (must pass CI).
- No force-push to `develop` or `main`.
- **🚫 Working on `main` branch is FORBIDDEN.** Never commit, develop, or make changes directly on `main`. Always create a feature branch or work on `develop`. If you find yourself on `main`, switch to a feature branch before making any changes.

### Release Flow

```bash
# After staging verification passes:
git checkout develop
git pull origin develop
git tag v0.4.1
git push origin v0.4.1

# CI sees tag → deploys same artifact to production
# Then update main to match:
git checkout main
git merge develop --ff-only
git push origin main
```

---

## CI Pipeline (GitHub Actions)

### Phase 1 — Minimal Gate (implement NOW)

**Goal:** Catch import errors, broken modules, missing templates BEFORE merge.

```yaml
# .github/workflows/ci.yml
name: CI
on:
  push:
    branches: ['**']
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: reddit_saas
          POSTGRES_USER: reddit_saas_user
        ports: ['5432:5432']
        options: >-
          --health-cmd="pg_isready -U reddit_saas_user -d reddit_saas"
          --health-interval=5s
          --health-timeout=5s
          --health-retries=6
      redis:
        image: redis:7
        ports: ['6379:6379']
        options: >-
          --health-cmd="redis-cli ping"
          --health-interval=5s
          --health-timeout=5s
          --health-retries=6

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Cache pip
        uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: pip-${{ hashFiles('reddit_saas/pyproject.toml') }}
          restore-keys: pip-

      - name: Install
        working-directory: reddit_saas
        run: pip install -e ".[dev]" fakeredis pytest-timeout

      - name: Verify imports
        working-directory: reddit_saas
        run: python -c "from app.models import *; from app.main import app; print('OK')"

      - name: Alembic single head
        working-directory: reddit_saas
        env:
          DATABASE_URL: postgresql://reddit_saas_user:postgres@localhost:5432/reddit_saas
        run: |
          heads=$(alembic heads 2>/dev/null | wc -l)
          if [ "$heads" -ne 1 ]; then
            echo "::error::Multiple Alembic heads detected"
            exit 1
          fi

      - name: Run tests
        working-directory: reddit_saas
        env:
          DATABASE_URL: postgresql://reddit_saas_user:postgres@localhost:5432/reddit_saas
          REDIS_URL: redis://localhost:6379/0
          ENVIRONMENT: test
          SECRET_KEY: ci-test-key
          TZ: Asia/Jerusalem
        run: |
          pytest tests/ -x -q \
            --timeout=30 \
            --ignore=tests/test_geo_monitoring.py \
            -k "not hypothesis" \
            --tb=short \
            --junitxml=report.xml \
            || true  # Phase 1: report failures but don't block yet

      - name: Upload test report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: test-report
          path: reddit_saas/report.xml
```

**Key decisions:**
- `|| true` in Phase 1 — CI reports failures but doesn't block merge. Remove `|| true` when tests are stable (Phase 2).
- No ruff lint yet — 500+ violations exist, fixing them is not a priority vs shipping.
- hypothesis tests excluded — too slow for CI, run separately.
- GEO monitoring tests excluded — hang due to mock isolation issues.
- `pytest-timeout=30` — kills any test that hangs >30s.

### Phase 2 — Hard Gate (after test cleanup)

Remove `|| true`. CI blocks merge on test failure.

**Trigger to enable Phase 2:** All tests pass in CI for 5 consecutive pushes.

### Phase 3 — Lint + CD (after stabilization)

Add:
- `ruff check reddit_saas/ --select E,F,W` (errors + fatal only, not style)
- Auto-deploy to staging on main merge
- Auto-deploy to prod with manual approval (GitHub Environment)

---

## Deploy Script Changes

`deploy.sh` must be updated to:

1. **Refuse direct deploy from feature branch** — must be on `main` or explicit `--force`
2. **Run local test gate** before rsync (fast subset: imports + critical tests)
3. **Deploy to staging first** when `./deploy.sh staging`
4. **Deploy to prod** only via `./deploy.sh prod` (current `./deploy.sh app` renamed)

### Immediate: Local test gate in deploy.sh

```bash
# Add to deploy.sh BEFORE rsync
log "Running pre-deploy test gate..."
cd reddit_saas
python -c "from app.models import *; from app.main import app" || {
    error "Import check failed — aborting deploy"
    exit 1
}
pytest tests/ -x -q --timeout=30 \
    --ignore=tests/test_geo_monitoring.py \
    -k "not hypothesis" \
    --tb=line 2>/dev/null || {
    error "Tests failed — aborting deploy"
    error "Run 'pytest tests/ -x' locally to see details"
    exit 1
}
cd ..
log "Test gate passed ✓"
```

---

## Staging Usage

**Server:** `167.172.191.42` / `ssh ramp-staging` / `staging.gorampit.com`

**Purpose:**
- Verify Docker build works (catches missing deps, Dockerfile issues)
- Verify migrations apply cleanly
- Smoke test UI (login, admin, portal)
- Test with production-like data (DB sync from prod weekly)

**Deploy to staging:**
```bash
./deploy.sh staging  # rsync + build + up on staging server
```

**Staging verification checklist (manual, 2 min):**
1. `curl https://staging.gorampit.com/health` → 200 + correct version
2. Open `/login` → page loads
3. Open `/admin/` → redirects to login (auth works)
4. Check logs: `ssh ramp-staging "docker compose logs --tail=20 app"` → no errors

---

## Test Hygiene Rules

### For Agent (AI)

1. **After ANY code change** — run `python -c "from app.models import *; from app.main import app"` to verify imports
2. **Before suggesting deploy** — run the test gate (pytest -x -q --timeout=30)
3. **When adding new code** — verify it doesn't break existing tests (run relevant test file)
4. **When fixing a bug** — if a test exists for that area, run it. Don't add new tests unless asked.

### For Max (human)

1. **Before pushing** — run `make test-gate` (or pytest subset)
2. **Before merging to main** — CI must show results (Phase 1: informational, Phase 2: blocking)
3. **Before deploying to prod** — staging must have the same version deployed and smoke-tested
4. **Weekly** — full regression run + report update

### Test Triage Priority

| Category | Action | When |
|----------|--------|------|
| Tests that HANG | `--ignore` or `pytest.mark.skip` | Immediately |
| Tests with stale assertions | Fix assertion to match current code | This week |
| Tests for removed features | Delete the test file | This week |
| Tests that need new fixtures (new models) | Update fixtures | Before Phase 2 |
| Property-based tests | Keep excluded from CI, run manually | Monthly |

---

## Migration Plan (Current → Target)

| Step | What | Effort | Status |
|------|------|--------|--------|
| 1 | Create `.github/workflows/ci.yml` | 10 min | TODO |
| 2 | Push current branch, see CI run | 5 min | TODO |
| 3 | Full local test run + triage report | 1-2h | TODO |
| 4 | Fix critical failures (import errors, fixture mismatches) | 2-4h | TODO |
| 5 | Mark flaky/hanging tests with `pytest.mark.skip` | 30 min | TODO |
| 6 | CI green on feature branch (with `\|\| true`) | — | TODO |
| 7 | Remove `\|\| true` → CI blocks on failure | 1 min | TODO |
| 8 | Add staging deploy to workflow | 30 min | TODO |
| 9 | Add test gate to `deploy.sh` | 15 min | TODO |
| 10 | Retire direct rsync-to-prod workflow | — | TODO |

---

## What NOT To Do

1. ❌ Don't add ruff formatting enforcement until tests are stable (one thing at a time)
2. ❌ Don't rewrite deploy.sh completely — add gates incrementally
3. ❌ Don't block all deploys on test failures in Phase 1 (informational first)
4. ❌ Don't fix 100 tests at once — triage, skip broken, fix incrementally
5. ❌ Don't set up CD (auto-deploy) until CI is reliably green for 2+ weeks

---

## Success Criteria

**Phase 1 complete when:**
- CI runs on every push (even if not blocking)
- Test failures are visible in GitHub (not hidden on local machine)
- deploy.sh refuses to deploy with broken imports

**Phase 2 complete when:**
- CI blocks merge on test failure
- 0 skipped tests remaining (all either pass or deleted)
- Staging deploy happens before every prod deploy

**Phase 3 complete when:**
- `main` is always green
- Prod deploy is one button (GitHub Actions deploy workflow)
- No more rsync from local Mac
