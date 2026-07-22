---
inclusion: fileMatch
fileMatchPattern: "**/workflows/**,docker-compose*,Dockerfile,**/deploy*,.github/**"
---

# Development Workflow — CI/CD Discipline

## Status: TRANSITION IN PROGRESS (July 13, 2026)

**Old flow (DEPRECATED):** Mac → rsync → prod. No tests, no staging, no review.
**New flow (TARGET):** feature branch → PR to develop → CI → staging auto-deploy → verify → release tag → production deploy (same artifact).

---

## Team

| Person | Role | Works in | Git access |
|--------|------|----------|------------|
| **Max** | Tech lead, engineer | Local Mac + Kiro | Full (all branches) |
| **Женя (Zhenya)** | QA engineer | Her own Kiro.dev workspace | Read all branches, write to `feature/*` and `qa` |
| **Tzvi** | Business/clients | N/A | None (receives reports) |

**Workflow with QA:**
- Max develops on `develop` branch (his working branch)
- When ready for QA → merge `develop → staging` (auto-deploy to staging server)
- Женя verifies on `staging.gorampit.com` using QA checklists
- Женя works on `qa` branch for test fixes / QA automation
- Женя signs off → Max merges `staging → main` (prod deploy)
- Женя does NOT deploy to production directly

---

## Why This Change

- Regression rate increased: multiple broken deploys in June-July 2026
- No test gate: code goes to production without test validation
- No staging verification: production is the first place code runs in Docker
- Last full regression run: June 19, 2026 (20+ days of unvalidated changes)
- Direct rsync to prod = one typo away from 500 Internal Server Error for clients

---

## Git Flow — Four-Branch Model

### Branch → Environment Mapping

| Branch | Environment | Server | Purpose |
|--------|------------|--------|---------|
| `main` | Production | `gorampit.com` (161.35.27.165) | Live client-facing system |
| `staging` | Staging | `staging.gorampit.com` (167.172.191.42) | Pre-production verification |
| `develop` | — (local) | — | Max's working branch (daily development) |
| `qa` | — (local/staging) | — | Женя's QA working branch |

### Flow Diagram

```
feature/xyz (short-lived, for isolated changes)
    ↓ merge → develop
develop (Max's working branch — daily development happens here)
    ↓ push to staging when ready for QA
staging (staging.gorampit.com, 167.172.191.42)
    ↓ CI + auto-deploy to staging server
    ↓ Женя verifies on staging
    ↓ QA sign-off
    ↓ merge staging → main
main (gorampit.com, 161.35.27.165)
    ↓ CI + auto-deploy to production (with auto-rollback)
```

### Core Principles

1. **`develop` is Max's primary working branch.** Daily coding, experiments, WIP — all happen here.
2. **`qa` is Женя's working branch.** Test fixes, QA automation, regression scripts.
3. **`staging` = deployment gate.** Code reaches staging only when ready for verification.
4. **`main` = production.** Only verified code from staging gets merged here.
5. **Feature branches are optional.** Use `feature/*` for isolated multi-day work that shouldn't pollute `develop`. Merge back to `develop` when done.
6. **Flow is one-directional:** `feature/* → develop → staging → main`. No cherry-picks backwards (except hotfix).

### Branch Rules

| Branch | Push triggers deploy? | Who commits | Protected? |
|--------|----------------------|-------------|-----------|
| `main` | ✅ → production | Max (merge from staging only) | Yes — no direct commits |
| `staging` | ✅ → staging server | Max (merge from develop) | Yes — no direct commits |
| `develop` | ❌ | Max (daily work) | No |
| `qa` | ❌ | Женя (QA work) | No |
| `feature/*` | ❌ | Max | No |

### Normal Flow

```bash
# 1. Daily development on develop
git checkout develop && git pull
# ... work, commit ...
git add . && git commit -m "feat: ..."
git push origin develop

# 2. When ready for QA — merge to staging (triggers staging deploy)
git checkout staging && git pull
git merge develop
git push origin staging
# → CI passes → deploy-staging.yml runs → Женя verifies on staging.gorampit.com

# 3. After QA sign-off — merge to main (triggers prod deploy)
git checkout main && git pull
git merge staging --ff-only
git push origin main
# → CI passes → deploy-production.yml runs → verify on gorampit.com

# 4. Sync develop with main (pick up any hotfix or qa fixes)
git checkout develop && git merge main && git push origin develop
```

### Feature Branch Flow (for isolated work)

```bash
git checkout develop && git pull
git checkout -b feature/my-isolated-change
# ... work ...
git push -u origin feature/my-isolated-change
# When done:
git checkout develop && git merge feature/my-isolated-change
git push origin develop
git branch -d feature/my-isolated-change
```

### QA Branch Flow

```bash
# Женя works on qa branch
git checkout qa && git pull
# ... test fixes, automation ...
git push origin qa

# When QA fixes need to reach staging:
# Женя creates PR: qa → staging (or Max merges)
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
# Sync downstream:
git checkout staging && git merge main && git push origin staging
git checkout develop && git merge main && git push origin develop
```

### Invariants

- After every prod deploy: `staging` and `main` point to the same commit.
- `develop` may be ahead of `staging` (unreleased work). This is normal.
- `qa` branch is independent — Женя syncs from `staging` as needed.
- Feature branches are short-lived (hours/days, not weeks).
- If `staging` is ahead of `main`, it means code is being QA-verified. Merge to main after sign-off same day.

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

1. ❌ Don't commit directly to `main` or `staging` — merge from `develop`/`staging` respectively
2. ❌ Don't keep feature branches alive for weeks — merge to `develop` or abandon
3. ❌ Don't let staging drift ahead of main — after QA sign-off, merge to main same day
4. ❌ Don't force-push to `main` or `staging`
5. ❌ Don't deploy via rsync manually unless GitHub Actions is broken (emergency only)
6. ❌ Don't skip CI — if tests fail, fix them before merge
7. ❌ Don't develop on `staging` or `main` directly — use `develop` for daily work

---

## Success Criteria

**CI/CD fully operational:**
- ✅ CI runs on every push (hard gate, blocks merge on failure)
- ✅ Push to `staging` → auto-deploy to staging server
- ✅ Push to `main` → auto-deploy to production with auto-rollback
- ✅ Pre-deploy DB backup on every prod deploy
- ✅ No more manual rsync deploys

**Branch discipline (enforced by this document + agent behavior):**
- Daily work on `develop` branch
- Feature branches for isolated multi-day work → merge back to `develop`
- `staging` = QA verification gate (deploy trigger)
- `main` = production (deploy trigger)
- `qa` = Женя's independent working branch
- staging = main after every prod deploy (steady state)
