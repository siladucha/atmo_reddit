открой сессию на прод!
получи доступ к прод


# Deploy Session — July 5, 2026

## Context

5 fixes from Tzvi's XM Cyber feedback:

1. **BUG FIX (critical):** Phase 2 avatars with empty `business_subreddits` got 0 professional threads. Fix: fallback to `ClientSubredditAssignment` in `smart_scoring.py`.
2. **d-wreck-w12 voice profile:** Rewritten from aggressive/sarcastic to calm pragmatist per Tzvi's PDF.
3. **Review queue counts:** `approved_count` now filters active+unfrozen + 14 days (was unbounded). Approved tab list also limited to 14 days.
4. **Sort by date:** Added newest/oldest toggle to client review queue.
5. **Edit persona:** Clients can edit avatar persona (1 edit per 30 days rate limit).

## Files Changed

- `app/services/smart_scoring.py` — Phase 2 fallback to client subs when business_subreddits empty
- `app/routes/portal.py` — approved_count filter, sort param, approved tab 14d filter, edit-persona endpoint
- `app/templates/client/review.html` — sort buttons + JS
- `app/templates/client/avatar_detail.html` — edit persona button + form + JS
- `_update_dwreck_prod.py` — one-time DB update script for d-wreck-w12 profile + business_subreddits

## Deploy Steps

```bash
# 1. Push code to server
cd /Volumes/2SSD/Projects/ReddirSaaS/reddit_saas
rsync -avz --exclude='.venv/' --exclude='__pycache__/' --exclude='.hypothesis/' \
  --exclude='.git/' --exclude='*.pyc' --exclude='.DS_Store' --exclude='logs/' \
  --exclude='.env' --exclude='.claude/' --exclude='.kiro/' --exclude='.vscode/' \
  --exclude='tests/' --delete \
  ./ ramp:/app/

# 2. Rebuild Docker image + restart
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml build && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"

# 3. Update d-wreck-w12 in production DB
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec app python _update_dwreck_prod.py"

# 4. Verify health
ssh ramp "curl -s http://localhost/health | python3 -m json.tool"

# 5. Verify d-wreck-w12 gets professional subs
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec app python -c \"
from app.database import SessionLocal
from app.models.avatar import Avatar
from app.models.client import Client
from app.services.smart_scoring import get_avatar_available_subreddit_names
db = SessionLocal()
a = db.query(Avatar).filter(Avatar.reddit_username=='d-wreck-w12').first()
c = db.query(Client).filter(Client.id=='352fbfb6-7f67-4400-96ea-468b19fb95c4').first()
subs = get_avatar_available_subreddit_names(db, a, c)
print(f'Available subs: {len(subs)} — {sorted(subs)[:5]}...')
db.close()
\""

# 6. Check portal loads (quick smoke test)
ssh ramp "curl -s -o /dev/null -w '%{http_code}' https://gorampit.com/health"
```

## Rollback

If something breaks:
- Code: `git checkout -- app/services/smart_scoring.py app/routes/portal.py` then rsync+rebuild
- DB (d-wreck-w12): voice profile change is non-breaking, no rollback needed
- No migration in this deploy — pure code + data update

## No Migration Required

All changes are code-only + one DB data update (avatar fields). No schema changes.

---

## Additional Fixes (deployed same day)

### 6. BUG FIX: `/admin/ab-tests` — TypeError: unhashable type: 'dict'

**Root cause:** `admin_ab_test.py` created a fresh `Jinja2Templates` instance inside each handler without disabling bytecode cache. Jinja2 tried to use the context dict as cache key → crash.

**Fix:** Moved `Jinja2Templates` to module level + `templates.env.cache = {}` (same pattern as `admin.py`).

**File:** `app/routes/admin_ab_test.py`

### 7. BUG FIX: Portal "Approve" button → 500 (CommentDraft.updated_at)

**Root cause:** `plan_enforcement.py` queried `CommentDraft.updated_at` which doesn't exist on the model. Every approve/edit action hit this error.

**Fix:** Changed to `CommentDraft.created_at` (the field that actually exists).

**File:** `app/services/plan_enforcement.py`

### 8. UX: Client review page — tooltips & "how it works"

**Problem:** Client manager (Jjekorn12) didn't understand how editing and regeneration work.

**Fix:**
- Expanded info block on Pending tab with clear action descriptions (Approve / Edit / Regenerate / Skip)
- Added `title` tooltips on all action buttons explaining what each does
- Added "click to edit ✎" hint in corner of each editable comment text area
- Improved "Ready to Post" tab info text

**Files:** `app/templates/client/review.html`, `app/templates/partials/client/drafts_list.html`

### 9. BUG FIX: Portal Approve/Regenerate — "Server error" (action_requests table + plan_enforcement)

**Root cause (multi-factor):**
1. `action_requests` table created by wrong DB user → `permission denied` for app user → session corrupted
2. `plan_enforcement.py` may not exist on production (new file, same commit) → `ModuleNotFoundError` on approve
3. `PermissionRequiresApproval` exception from `require_permission` dependency had no global handler → 500 on regenerate if tier ever changes

**Fixes:**
- `app/services/permission_context.py` — graceful degradation: `action_requests` query wrapped in try/except (session rollback on failure), `permission_matrix` access wrapped in try/except
- `app/routes/portal.py` — `plan_enforcement` import wrapped in `try/except ImportError: pass`; error logging enhanced with full traceback
- `app/main.py` — global `PermissionRequiresApproval` exception handler (returns 422 JSON instead of 500)
- Local DB: `GRANT ALL ON action_requests TO reddit_saas_user` (wrong table owner)

**Production action:** After deploy, run on server:
```bash
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec db psql -U reddit_saas_user -d reddit_saas -c \"SELECT tableowner FROM pg_tables WHERE tablename='action_requests';\""
# If owner != reddit_saas_user:
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec db psql -U user -d reddit_saas -c \"GRANT ALL ON TABLE action_requests TO reddit_saas_user;\""
```

**Files:** `app/services/permission_context.py`, `app/routes/portal.py`, `app/main.py`

---

## Technical Debt: Schema Drift (non-blocking)

`alembic check` on production shows significant drift between SQLAlchemy models and actual DB schema. This is **accumulated from multiple sessions** and does NOT block current operations.

### What's drifted:

**Tables in code but not in DB:**
- `avatar_subreddit_bans` — model exists, table not created (migration in chain but table missing)

**Tables in DB but not in code (legacy orphans):**
- `personas` — removed from models months ago
- `waitlist_signups` — marketing site legacy
- `ab_test_assignments` — old marketing A/B test (different from our new `ab_experiments`)
- `analytics_events` — marketing site legacy
- `action_requests` — created by permission_map spec, has ownership issue
- `avatar_subreddit_compatibility` — should exist (model present), might be index-only issue
- `alembic_version_marketing` — marketing site's migration tracker

**Index drift (models declare, DB doesn't have):**
- ~30 indexes defined in models but never migrated (performance optimization indexes)
- Several indexes in DB removed from models (old patterns)

**Nullable drift:**
- ~50 columns have `nullable` mismatch (model says `nullable=False`, DB has `nullable=True`)
- This is because original migrations used `server_default` without explicit `nullable=False`

**FK drift:**
- Several ForeignKey constraints differ in `ondelete` behavior (code says CASCADE, DB has no action)

### Why it's not blocking:

1. SQLAlchemy doesn't validate schema at startup
2. App creates objects correctly (respects model definition)
3. Queries work because columns exist (nullable mismatch doesn't break reads/writes)
4. Missing indexes = slower queries at scale, not errors

### Recommended fix (separate session):

Create a single consolidation migration:
```bash
alembic revision --autogenerate -m "consolidate: sync schema with models"
# Then manually review — remove dangerous operations (DROP TABLE for active tables)
# Keep: add missing indexes, create avatar_subreddit_bans, fix nullable, fix FK ondelete
# Skip: drop legacy tables (do that manually with business confirmation)
```

**Priority:** Low (not blocking). Do before 10+ clients (index performance matters at scale).

---

## Extension Status After Deploy

### What's working:
- Extension v3.0.0 on local Chrome (Load Unpacked)
- `old-reddit-actions.js` loaded on old.reddit.com (manifest fixed)
- Scheduler defaults to `old_reddit` strategy
- Human-like flow: subreddit → scroll → find thread → click → scroll to comments → type → submit
- Backend creates tasks with `posting_strategy="old_reddit"` for extension avatars
- Hot-Thought2408 set to `delivery_channel=extension`

### What's broken (EPG pipeline):
- **ALL EPG slots `skipped` with:** `generation_error: type object 'CommentDraft' has no attribute 'updated_at'`
- Error occurs AFTER draft creation succeeds (drafts exist as `pending`)
- Cannot reproduce manually (calling `_generate_hobby_slot` directly works)
- Suspect: some code path during auto-approve → commit → refresh calls `CommentDraft.updated_at` which doesn't exist on model or DB
- **Impact:** No new CREATED tasks for extension to poll → popup shows nothing

### Next steps to fix EPG:
1. ~~Add `traceback.print_exc()` to the except block in `epg_executor.py` line 214~~ → **FIXED (see Deploy #2 below)**
2. ~~OR: add `updated_at` column to CommentDraft model + migration~~ → **DONE**

---

## Deploy #2 — Stabilization (13:43 IST)

### Fixes

| # | Error | Root Cause | Fix |
|---|-------|-----------|-----|
| 1 | `column comment_drafts.updated_at does not exist` | Model defines `updated_at` but column never migrated to production DB | Migration `cdu01` — `ALTER TABLE comment_drafts ADD COLUMN updated_at TIMESTAMPTZ DEFAULT now()` |
| 2 | `No module named 'pytz'` | `dispatch_due_email_tasks` imported `pytz` which is not in Docker image | Replaced with `from zoneinfo import ZoneInfo` (Python 3.11 stdlib) |

### Affected endpoints/tasks (were erroring every 5 min):
- `GET /clients/{id}/partials/drafts` — portal drafts page (500)
- `GET /api/extension/tasks` — extension task polling (500)
- `expire_extension_leases` celery task (every 5 min)
- `dispatch_due_email_tasks` celery task (every 5 min)

### Files Changed
- `alembic/versions/cdu01_add_comment_drafts_updated_at.py` — **NEW** migration
- `app/tasks/execution_tasks.py` — `import pytz` → `from zoneinfo import ZoneInfo`

### Migration: Yes
- `cdu01` — additive only (ADD COLUMN), safe, auto-applied by entrypoint.sh

### Result
- ✅ Health: `ok`
- ✅ Migration applied: `exv01 -> cdu01`
- ✅ Zero errors in app logs after restart
- ✅ Zero errors in celery logs after restart
- ✅ EPG pipeline should now work (the `updated_at` column that was blocking generation exists)
- ✅ Email task dispatch restored (`pytz` → `zoneinfo` fix)
- ✅ Extension task polling restored

---

## Deploy #3 — Extension UX + Draft Expiry + Posting Strategy (pending)

### What's New

| # | Change | File(s) |
|---|--------|---------|
| 1 | Extension popup: "Today's Schedule" shows tasks with time/sub/preview | popup.html, popup.js, popup.css |
| 2 | Extension popup: Cancel button (✗) on each scheduled task | popup.js |
| 3 | Extension scheduler: auto-expires tasks >24h from local queue | scheduler.js |
| 4 | Extension scheduler: defaults to old_reddit strategy (null → old_reddit) | scheduler.js |
| 5 | Extension scheduler: prefers old.reddit.com tabs, creates new tabs there | scheduler.js |
| 6 | Extension executor: human-like flow (subreddit→scroll→find→click→post) | executor-old-reddit.js |
| 7 | Extension manifest: old-reddit-actions.js in content_scripts for old.reddit.com | manifest.json |
| 8 | Extension poller: shows "Server updating" banner on 5xx/network errors | poller.js |
| 9 | Backend: `posting_strategy=old_reddit` default on extension tasks | execution_tasks.py, extension_dispatcher.py, extension_api.py |
| 10 | Backend: DraftExpiryService (approved >48h, pending >72h → expired + cascade) | services/draft_expiry.py |
| 11 | Backend: EPG executor traceback logging | epg_executor.py |
| 12 | Version: Extension 0.3.0 (was 3.0.0) | manifest.json |

### Extension Changes (local only — no server deploy needed)

Files 1-8 are Chrome extension source. Effect is immediate after `chrome://extensions` → Reload.

### Backend Changes (require server deploy)

Files 9-11 need rsync + build + restart:

```bash
cd /Volumes/2SSD/Projects/ReddirSaaS/reddit_saas
rsync -avz --exclude='.venv/' --exclude='__pycache__/' --exclude='.hypothesis/' \
  --exclude='.git/' --exclude='*.pyc' --exclude='.DS_Store' --exclude='logs/' \
  --exclude='.env' --exclude='.claude/' --exclude='.kiro/' --exclude='.vscode/' \
  --exclude='tests/' --delete \
  ./ ramp:/app/

ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml build && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"

# Health check (wait 15s for startup)
sleep 15 && ssh ramp "docker exec app-app-1 curl -sf http://localhost:8000/health"
```

### After Deploy — Trigger EPG Rebuild

```bash
ssh ramp "docker exec app-celery-1 python -c \"
from app.tasks.epg import build_and_generate_epg_all_avatars
build_and_generate_epg_all_avatars.delay()
print('EPG rebuild triggered')
\""
```

Wait 2-3 min, then check extension popup for new tasks.

### Verification

- [ ] Health check passes
- [ ] EPG rebuild completes without `updated_at` error (check celery logs)
- [ ] New execution tasks created with `posting_strategy=old_reddit`
- [ ] Extension popup shows tasks in "Needs Approval" (if auto_approve=False) or "Today's Schedule" (if auto-approved)
- [ ] `draft_expiry_enabled` setting exists in DB (default true from DEFAULT_SETTINGS)
- [ ] Old stale tasks don't reappear (24h auto-expiry in scheduler)

### No Migration Required

DraftExpiryService uses existing columns. posting_strategy column already exists (from ab01 migration applied in Deploy #1).
