# Deploy Session — Stale Draft Expiry

## Changes
1. New Celery Beat task `expire_stale_drafts` — runs every 60 min, expires stale approved (>48h) and pending (>72h) drafts
2. Cascades to EPGSlot (→expired) and ExecutionTask (→cancelled)
3. Emits per-client activity events for transparency
4. Amber badge for expired drafts in admin review + client portal
5. 'expired' status filter in admin review dropdown + client portal tab
6. 3 new system settings: `draft_expiry_approved_hours`, `draft_expiry_pending_hours`, `draft_expiry_enabled`

## Files Changed (new)
- `app/services/draft_expiry.py` — **NEW** DraftExpiryService (~320 lines)
- `app/tasks/draft_expiry.py` — **NEW** Celery task (lock + kill switch + delegate)
- `alembic/versions/cdu01_add_comment_drafts_updated_at.py` — **NEW** migration

## Files Changed (modified)
- `app/services/settings.py` — +3 settings in DEFAULT_SETTINGS (pipeline group)
- `app/tasks/worker.py` — +1 include, +1 beat_schedule entry
- `app/models/comment_draft.py` — +`updated_at` column definition
- `app/routes/admin.py` — added 'expired' to status validation tuple
- `app/routes/portal.py` — added expired tab support + expired_count
- `app/templates/admin_review.html` — added 'expired' in filter status loop
- `app/templates/partials/_review_queue_item.html` — added amber badge section for expired status
- `app/templates/client/review.html` — added expired tab + info block
- `app/templates/partials/client/drafts_list.html` — added amber badge + empty state for expired

## Migration Required: YES
- **`cdu01`** — `ALTER TABLE comment_drafts ADD COLUMN updated_at TIMESTAMPTZ DEFAULT NOW()`
- Non-destructive (ADD COLUMN, nullable, with default). Safe to run on live DB.
- `entrypoint.sh` runs `alembic upgrade head` automatically on container start.
- Revision chain: `exv01` → `cdu01` (head)

## One-Off Scripts: No

## Pre-Flight Results
- [x] All .py compile (7 files checked)
- [x] Imports OK
- [x] Templates exist (checked 4 templates)
- [x] Alembic single head: `cdu01`
- [x] Tests pass: 31/31

## Deploy Steps
1. `rsync` code to server
2. `docker compose build + up -d` (entrypoint runs `alembic upgrade head` → applies cdu01)
3. Health check: `curl -sf http://localhost/health`
4. Verify migration applied: check logs for "Running upgrade exv01 -> cdu01"
5. Verify settings: `/admin/settings` shows draft_expiry_* keys in "pipeline" group
6. Verify task registered: Beat logs show "expire_stale_drafts" in schedule

## Rollback Plan
- **Instant disable:** Set `draft_expiry_enabled` to `"false"` in `/admin/settings` — task still runs but does nothing
- **Code rollback:** rsync previous code + rebuild (migration is additive — old code ignores the new column)
- No data loss — expired drafts can be manually reverted to 'approved'/'pending' via admin if needed

## Risk Assessment: LOW
- Non-destructive migration (ADD COLUMN nullable)
- Kill switch (`draft_expiry_enabled`) can disable without deploy
- Hourly schedule — won't fire until next top-of-hour after deploy
- First run may expire accumulated stale drafts (capped at 500/run, clears backlog over multiple hours)
- All changes visible in Activity Feed per client

## What Happens on First Run
- Task fires at next :00 after deploy
- Queries approved drafts with `updated_at < now() - 48h` and pending drafts with `created_at < now() - 72h`
- NOTE: The new `updated_at` column defaults to NOW() on creation — so existing approved drafts will have `updated_at = migration_time` (not their original approval time). This means the first run won't expire old approved drafts (they'll look "fresh"). They'll become eligible 48h after deploy.
- Pending drafts use `created_at` (already exists) — old pending drafts WILL be expired on first run.
