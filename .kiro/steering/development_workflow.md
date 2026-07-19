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

## Git Flow — Two-Branch Promotion Model

```
feature/xyz (local Mac)
    ↓ push to origin
    ↓ CI runs (tests + imports + alembic)
    ↓ merge → staging
staging (staging.gorampit.com, 167.172.191.42)
    ↓ CI + auto-deploy to staging server
    ↓ Verify (smoke test, manual check)
    ↓ Operator approves
    ↓ merge staging → main (fast-forward or PR)
main (gorampit.com, 161.35.27.165)
    ↓ CI + auto-deploy to production (with auto-rollback)
```

### Core Principles

1. **All work happens on feature branches.** Never commit directly to `main` or `staging`.
2. **staging ≤ main.** Staging cannot be ahead of production (unless hotfix in progress). Both branches must be at the same commit, or main is ahead (has changes staging hasn't received yet — which shouldn't happen in normal flow).
3. **Flow is one-directional:** `feature/* → staging → main`. No cherry-picks backwards.
4. **Deploy = merge.** Push to `staging` triggers staging deploy. Push to `main` triggers production deploy.

### Branch Rules

- `main` = production. Push triggers CI → deploy to prod. Protected.
- `staging` = staging environment. Push triggers CI → deploy to staging. Pre-production verification.
- `feature/*` = active development. Always branch from `staging` (which equals `main` in steady state).
- **🚫 Working directly on `main` or `staging` is FORBIDDEN.** Never commit, develop, or make changes on these branches. Always use a feature branch.
- No force-push to `staging` or `main`.
- Direct push to `staging` allowed ONLY for CI-verified hotfixes (must still be a merge, not direct commit).

### Normal Flow

```bash
# 1. Create feature branch (from staging, which = main)
git checkout staging && git pull
git checkout -b feature/my-change

# 2. Work, commit, push
git add . && git commit -m "feat: ..."
git push -u origin feature/my-change

# 3. CI runs on push (tests must pass)

# 4. Merge to staging (triggers staging deploy)
git checkout staging && git pull
git merge feature/my-change
git push origin staging
# → CI passes → deploy-staging.yml runs → verify on staging.gorampit.com

# 5. After staging verification — merge to main (triggers prod deploy)
git checkout main && git pull
git merge staging --ff-only
git push origin main
# → CI passes → deploy-production.yml runs → verify on gorampit.com

# 6. Cleanup
git branch -d feature/my-change
git push origin --delete feature/my-change
```

### Hotfix Flow (production emergency)

```bash
git checkout main && git pull
git checkout -b hotfix/critical-fix
# fix, commit
git push -u origin hotfix/critical-fix
# CI passes
git checkout main && git merge hotfix/critical-fix && git push origin main
# → prod deploy
# Then sync staging:
git checkout staging && git merge main && git push origin staging
```

### Invariants

- After every prod deploy: `staging` and `main` point to the same commit.
- Feature branches are short-lived (hours/days, not weeks).
- If `staging` is ahead of `main`, it means code is being verified before prod. This is normal. But `staging` should never STAY ahead indefinitely — either merge to main or revert.

---

## CI Pipeline (GitHub Actions)

### Current State: FULLY IMPLEMENTED ✅

Three workflow files in `.github/workflows/`:

| File | Trigger | What It Does |
|------|---------|--------------|
| `ci.yml` | Push to any branch (except staging/main), PR to staging/main, called by deploy workflows | Tests + imports + alembic check |
| `deploy-staging.yml` | Push to `staging` | CI gate → rsync → build → restart → health check → smoke tests → data integrity |
| `deploy-production.yml` | Push to `main` | CI gate → pre-deploy backup → rsync → build → restart → health check → auto-rollback on failure → smoke tests → SSL check → DB integrity |

### CI checks (ci.yml):
1. Postgres 16 + Redis 7 ephemeral services
2. `pip install -e ".[dev]" fakeredis pytest-timeout`
3. Import verification: `from app.models import *; from app.main import app`
4. Alembic single head check
5. Full test suite: `pytest tests/ -x -q --timeout=30 --ignore=tests/test_geo_monitoring.py -k "not hypothesis"`

### Production deploy features:
- Pre-deploy DB backup (pg_dump, verified >1MB)
- Docker image tagged `:previous` before rebuild
- Auto-rollback if health check fails 6× (restores `:previous` image)
- SSL cert expiry check
- Celery workers health verification
- Database integrity check (FK violations, orphaned records)

---

## Deploy Script (Legacy — Deprecated)

`deploy.sh` is NO LONGER the primary deploy mechanism. Deploys happen via git push:
- `git push origin staging` → GitHub Actions CI + deploy to staging
- `git push origin main` → GitHub Actions CI + deploy to production (with auto-rollback)

`deploy.sh` kept as emergency fallback only (when GitHub Actions is broken).

---

## Staging Usage

**Server:** `167.172.191.42` / `ssh ramp-staging` / `staging.gorampit.com`

**Purpose:**
- Verify Docker build works (catches missing deps, Dockerfile issues)
- Verify migrations apply cleanly
- Smoke test UI (login, admin, portal)
- Test with production-like data (DB sync from prod weekly)

**Deploy:** Push to `staging` branch → GitHub Actions handles everything (CI → rsync → build → restart → health check → smoke tests → data integrity check).

**Staging verification checklist (automated by CI, but also manual 2 min):**
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

| Step | What | Status |
|------|------|--------|
| 1 | Create `.github/workflows/ci.yml` | ✅ DONE |
| 2 | Create `.github/workflows/deploy-staging.yml` | ✅ DONE |
| 3 | Create `.github/workflows/deploy-production.yml` | ✅ DONE |
| 4 | CI runs on every push (hard gate — blocks merge) | ✅ DONE |
| 5 | Staging auto-deploy on push to `staging` | ✅ DONE |
| 6 | Production auto-deploy on push to `main` + auto-rollback | ✅ DONE |
| 7 | SSH deploy key as GitHub Secret | ✅ DONE |
| 8 | Retire direct rsync-to-prod workflow | ✅ DONE (deploy.sh kept as emergency fallback) |
| 9 | Enforce feature branch discipline | ✅ In progress (this document) |
| 10 | Add ruff lint to CI | TODO (after test stability) |

---

## What NOT To Do

1. ❌ Don't commit directly to `main` or `staging` — always use feature branch
2. ❌ Don't keep feature branches alive for weeks — merge or abandon
3. ❌ Don't let staging drift ahead of main — after staging verification, merge to main same day
4. ❌ Don't force-push to `main` or `staging`
5. ❌ Don't deploy via rsync manually unless GitHub Actions is broken (emergency only)
6. ❌ Don't skip CI — if tests fail, fix them before merge

---

## Success Criteria

**CI/CD fully operational:**
- ✅ CI runs on every push (hard gate, blocks merge on failure)
- ✅ Push to `staging` → auto-deploy to staging server
- ✅ Push to `main` → auto-deploy to production with auto-rollback
- ✅ Pre-deploy DB backup on every prod deploy
- ✅ No more manual rsync deploys

**Branch discipline (enforced by this document + agent behavior):**
- All work on feature branches
- staging = main in steady state
- Feature branches short-lived (same-day merge target)
