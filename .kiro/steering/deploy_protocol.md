---
inclusion: fileMatch
fileMatchPattern: "**/deploy*,docker-compose*,Dockerfile,Makefile,*.sh,**/workflows/**"
---

# Agent Deploy Protocol — Mandatory Procedure

## What This Is

Formalized deployment protocol that the AI agent MUST follow for every production deploy.
No shortcuts. No skipping steps. Each phase gates the next.

---

## Safety Rules (Non-Negotiable)

1. **NEVER deploy to production without explicit user permission** in the current conversation
2. **NEVER skip pre-flight checks** — if any check fails, STOP and report
3. **NEVER run destructive commands** (DROP, DELETE, TRUNCATE) on production without showing them first
4. **ALWAYS verify SSH connectivity** before starting deploy sequence
5. **ALWAYS read health check output** — don't assume success
6. **If deploy fails at any step** — STOP, report the error, suggest rollback. Do NOT retry blindly.

---

## Phase 1: Pre-Flight (Local)

Run BEFORE any server interaction. ALL must pass.

| # | Check | Command | Pass Criteria |
|---|-------|---------|---------------|
| 1 | Changed files compile | `py_compile.compile(f, doraise=True)` for each changed .py | No SyntaxError |
| 2 | Key modules import | `import app.services.<module>` for changed services | No ImportError (scipy exception OK) |
| 3 | Templates exist | `os.path.exists(f)` for referenced templates | All exist |
| 4 | Alembic heads | `python -m alembic heads` | Exactly 1 head |
| 5 | Alembic current = head | `python -m alembic current` | Shows `(head)` |
| 6 | One-off scripts safe | py_compile + grep for DROP/DELETE/TRUNCATE | Compile OK, no unexpected destructive SQL |
| 7 | No .env in changeset | Verify .env not in files being deployed | .env excluded |
| 8 | **Regression tests pass** | `pytest tests/ -x -q --timeout=30 --ignore=tests/test_geo_monitoring.py -k "not hypothesis"` | **0 failures** (exit code 0) |

**If ANY check fails:** Report failure, suggest fix, STOP. Do not proceed to Phase 2.

### How to Run Phase 1

```python
# Use project's Python interpreter
PYTHON = "/Volumes/2SSD/Projects/ReddirSaaS/.venv/bin/python"
CWD = "/Volumes/2SSD/Projects/ReddirSaaS/reddit_saas"
```

---

## Phase 2: Deploy

Only after Phase 1 passes AND user confirms "deploy" / "давай" / equivalent.

| # | Step | Command | Timeout | Failure Action |
|---|------|---------|---------|----------------|
| 1 | Rsync code | `rsync -avz --exclude=... --delete ./ ramp:/app/` | 60s | Report, stop |
| 2 | Build image | `ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml build"` | 300s | Report, stop |
| 3 | Update watchdog | `ssh ramp "cp /app/watchdog/ramp_watchdog.sh /opt/ramp/ramp_watchdog.sh && chmod +x /opt/ramp/ramp_watchdog.sh"` | 5s | Non-blocking |
| 4 | Signal watchdog | `ssh ramp "touch /var/lib/ramp-watchdog/deploying"` | 2s | Non-blocking |
| 5 | Restart services | `ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"` | 60s | Report, check logs |
| 6 | Wait for startup | `sleep 10` | — | — |
| 7 | Health check | `ssh ramp "curl -sf http://localhost/health"` | 15s | Retry 3×, then report failure |

### Rsync Excludes (canonical)

```bash
--exclude='.venv/' --exclude='__pycache__/' --exclude='.hypothesis/' \
--exclude='.git/' --exclude='*.pyc' --exclude='.DS_Store' --exclude='logs/' \
--exclude='.env' --exclude='.claude/' --exclude='.kiro/' --exclude='.vscode/' \
--exclude='tests/' --delete
```

### Preferred: Use `deploy.sh`

`./deploy.sh app` handles all steps automatically (rsync, build, watchdog update, grace period marker, restart, health check). Manual steps above are for when deploy.sh is unavailable.

### Health Check Retry Logic

```
Attempt 1: wait 10s after up -d, then curl
Attempt 2: wait 10s more, curl again  
Attempt 3: wait 10s more, curl again
All 3 fail → declare deploy FAILED, proceed to rollback assessment
```

---

## Phase 3: Post-Deploy Verification

Only after health check passes.

| # | Check | Command | Expected |
|---|-------|---------|----------|
| 1 | Version correct | Parse health JSON → `version` field | Matches `VERSION` file |
| 2 | No startup errors | `ssh ramp "cd /app && docker compose ... logs --tail=20 app 2>&1 \| grep -i error"` | No critical errors |
| 3 | Workers alive | `ssh ramp "cd /app && docker compose ... ps celery celery-beat"` | Both "running" |
| 4 | Smoke: login page | `ssh ramp "curl -s -o /dev/null -w '%{http_code}' https://gorampit.com/login"` | 200 |
| 5 | Smoke: admin redirect | `ssh ramp "curl -s -o /dev/null -w '%{http_code}' https://gorampit.com/admin/"` | 302 |

### One-Off Scripts (if any)

Run AFTER health check passes:
```bash
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec app python <script.py>"
```

Verify script output matches expectations. Report results.

---

## Phase 4: Confirmation

Report to user:
- ✅/❌ Health check result
- Version deployed
- Any warnings from logs
- One-off script results (if applicable)
- Total deploy time

---

## Rollback Procedure

When to rollback:
- Health check fails 3 consecutive times
- Critical errors in startup logs (migration failure, import error)
- User requests rollback

**Code-only rollback** (no migration in this deploy):
```bash
# On server — revert to previous git state and rebuild
ssh ramp "cd /app && git checkout -- . && docker compose -f docker-compose.yml -f docker-compose.prod.yml build && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
```

**If deploy included a migration** — rollback is MORE complex:
1. Code rollback as above
2. IF migration was additive (ADD COLUMN) — safe, old code ignores new column
3. IF migration was destructive (DROP/RENAME) — manual `alembic downgrade` needed
4. ALWAYS inform user about migration state

**Note:** Production has no git repo. Rollback = rsync previous code from local + rebuild. Keep local git clean.

---

## Deploy Plan Template

Before every deploy, create/update a deploy plan file (`_deploy_<date>.md`) with:

```markdown
# Deploy Session — <date>

## Changes
1. [description of change 1]
2. [description of change 2]

## Files Changed
- path/to/file1.py — what changed
- path/to/file2.html — what changed

## Migration Required: Yes/No
- If yes: migration name, what it does, reversible?

## One-Off Scripts: Yes/No  
- If yes: script name, what it does, safe?

## Pre-Flight Results
- [ ] All .py compile
- [ ] Imports OK
- [ ] Templates exist
- [ ] Alembic at head
- [ ] Scripts safe

## Deploy Steps
1. rsync
2. build + up
3. health check
4. [one-off script if needed]
5. verification

## Rollback Plan
- [what to do if it breaks]
```

---

## Special Cases

### Deploy with New Alembic Migration

Pre-flight adds:
- Verify migration file exists in `alembic/versions/`
- Check migration is not destructive (read the file)
- Verify single head (no branching)
- Note: entrypoint.sh runs `alembic upgrade head` automatically

Post-deploy adds:
- Verify migration applied: check logs for "Alembic migrations applied successfully"
- If "stamp head" appears in logs → WARNING: migration was skipped, investigate

### Deploy with nginx Changes

Add to Phase 2:
```bash
ssh ramp "cd /app && docker compose exec nginx nginx -t"  # test config
ssh ramp "cd /app && docker compose exec nginx nginx -s reload"  # zero-downtime reload
```

### Deploy with Extension Changes

Extension is local Chrome only — no server deploy needed.
Just verify backend API endpoints respond correctly.

---

## Agent Self-Check

Before starting ANY deploy:
1. Did user explicitly approve production deployment? → Must be YES
2. Is SSH session available (ControlMaster active)? → Must verify
3. Are there uncommitted local changes that should be committed first? → Inform user
4. Is this a rollback or forward deploy? → Choose correct procedure
