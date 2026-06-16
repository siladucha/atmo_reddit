# Client Portal Bugfix & Notification System — Report
## June 15, 2026

---

## Summary

Fixed critical client portal bugs reported during QA testing + implemented full real-time notification system (SSE + bell + activity log). All changes are LOCAL only — not yet deployed to production.

---

## Bugs Fixed

### 1. "Mark as Posted" button broken (CRITICAL)
**Symptom:** Clicking "Mark as Posted" showed popup "Could not mark as posted. Please try again."

**Root cause:** Route handlers used `raise HTTPException(...)` which FastAPI's custom exception handler converted to HTML responses. The JavaScript `fetch()` tried to parse HTML as JSON → failed → showed generic error.

**Fix:**
- All 3 portal action handlers (`mark-posted`, `approve`, `skip`) now return `JSONResponse` directly instead of raising HTTPException
- Wrapped in `try/except Exception` with `db.rollback()` — unhandled errors now return JSON 500 with meaningful message
- Added diagnostic logging (avatar.client_ids mismatch)
- JavaScript updated: uses `r.text()` + manual JSON.parse (handles both JSON and non-JSON), sets `Accept: application/json` header, detects session expiry (303/redirect)

**Files changed:**
- `app/routes/portal.py` — 3 handlers rewritten
- `app/templates/partials/client/drafts_list.html` — 3 JS functions updated

### 2. Very small text at 100% resolution
**Fix:** Bumped all CSS token font sizes +1px:
- body: 14px → 15px
- small: 12px → 13px  
- micro: 10px → 11px
- h3: 16px → 18px
- h2: 20px → 22px
- h1: 28px → 30px

**File:** `app/static/css/client-tokens.css`

### 3. No Audit Log in menu (HIGH)
**Fix:** Created full Activity Log page + added to sidebar navigation.

**New files:**
- `app/templates/client/activity_log.html` — shows who/what/when for last 30 days
- New route `GET /clients/{id}/activity` in `portal.py`
- Sidebar link added between Report and Schedule

### 4. Avatar detail "Recent Activity" bugs
**4a. Subreddit shows only "r/" (no name)**

**Root cause:** Hobby drafts have no `thread_id` (only `hobby_post_id`). The code did `d.thread.subreddit if d.thread else ""` — always empty for hobby posts.

**Fix:** Now resolves subreddit from `HobbySubreddit` model when `d.thread` is None.

**4b. Can't tell who approved/posted or when**

**Fix:** Added `posted_at` to activity items, status shown as colored badge, timestamps show "posted 3d ago" for posted items.

**Files changed:**
- `app/routes/portal.py` — activity building logic
- `app/templates/client/avatar_detail.html` — template section

---

## New Feature: Real-Time Notification System

### Architecture
```
Celery Worker → Redis PubSub → SSE Endpoint → Browser EventSource → Toast + Bell Badge
                                    ↓
                            notifications table
                                    ↓
                           Bell dropdown panel
```

### Components Built

| Layer | Component | Description |
|-------|-----------|-------------|
| 1 | `portal-actions.js` | Unified fetch wrapper with button loading states, toasts, error handling |
| 2 | `routes/sse.py` | SSE endpoint via Redis PubSub (async, per-client channel) |
| 3 | `models/notification.py` | DB model (client_id, type, title, body, link, is_read) |
| 3 | `services/notifications.py` | CRUD + Redis publish |
| 3 | `services/task_notifications.py` | Helpers for Celery tasks (fire-and-forget) |
| 3 | `routes/notifications.py` | API: list, count, mark-all-read |
| 3 | `notifications.js` | Client-side: SSE connection, bell badge, dropdown panel |
| 4 | AI pipeline hook | Emits notification when drafts generated |
| 4 | Posting hook | Emits notification when comment posted |
| 4 | Review queue | Auto-refreshes on `ramp:notification` event |

### UI Changes
- **Bell icon** (top-right) with red badge showing unread count
- **Dropdown panel** — click bell to see notification list with links
- **Mark all read** button
- **Toast notifications** appear in real-time as events happen
- **Activity Log** page in sidebar (audit trail)

### What Triggers Notifications

| Event | Type | Title Example | Link |
|-------|------|---------------|------|
| Pipeline complete | success | "Pipeline complete: 3 new drafts" | → review queue |
| Comment posted | success | "Comment posted on r/cybersecurity" | → reddit URL |
| Avatar frozen | warning | "Avatar Flaky_Finder_13 frozen" | → avatar detail |
| Error | error | "Pipeline failed: API timeout" | — |

---

## Files Created (New)

| File | Purpose |
|------|---------|
| `app/static/js/portal-actions.js` | Unified action handler with button states |
| `app/static/js/notifications.js` | SSE client + bell + panel |
| `app/routes/sse.py` | SSE streaming endpoint |
| `app/routes/notifications.py` | Notification API routes |
| `app/models/notification.py` | Notification DB model |
| `app/services/notifications.py` | Notification CRUD + Redis publish |
| `app/services/task_notifications.py` | Task helpers (pipeline, posting, freeze) |
| `app/templates/client/activity_log.html` | Activity log page |
| `alembic/versions/n0t1f1c4t10ns_add_notifications_table.py` | DB migration |

## Files Modified

| File | Changes |
|------|---------|
| `app/routes/portal.py` | Fixed 3 action handlers + added activity log route |
| `app/templates/partials/client/drafts_list.html` | Fixed JS functions |
| `app/templates/client_base.html` | Added bell UI + scripts |
| `app/templates/partials/client/sidebar.html` | Added Activity Log link |
| `app/templates/client/avatar_detail.html` | Fixed activity section |
| `app/templates/client/review.html` | Auto-refresh on notification |
| `app/static/css/client-tokens.css` | Font sizes bumped |
| `app/main.py` | Registered SSE + notifications routes |
| `app/models/__init__.py` | Added Notification import |
| `app/tasks/ai_pipeline.py` | Added notification emission |
| `app/services/posting.py` | Added notification emission |
| `nginx/nginx.conf` | SSE proxy config (no buffering) |
| `nginx/nginx.local.conf` | Same |

---

## Deployment Steps

```bash
# 1. Push code
rsync -avz --exclude='.venv/' --exclude='__pycache__/' --exclude='.hypothesis/' \
  --exclude='.git/' --exclude='*.pyc' --exclude='.DS_Store' --exclude='logs/' \
  --exclude='.env' --exclude='.claude/' --exclude='.kiro/' --exclude='.vscode/' \
  --exclude='tests/' --delete \
  ./ root@161.35.27.165:/app/

# 2. Run migration
ssh root@161.35.27.165 "cd /app && docker compose exec web alembic upgrade head"

# 3. Rebuild + restart
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml build && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"

# 4. Verify
ssh root@161.35.27.165 "curl -s http://localhost/health"
```

---

## Not Done (out of scope)

- Push notifications (mobile app — separate feature)
- Notification cleanup Celery Beat task (easy to add, not urgent)
- `portalAction()` not yet wired into all existing buttons in templates (existing markPosted/approve/skip still use their own fetch — they work but don't use the new unified system yet). Can migrate gradually.
- SSE reconnection hardening (EventSource handles basic reconnect, but edge cases with nginx timeouts need production testing)

---

## Testing Notes

- All Python files pass syntax check
- No diagnostics errors
- Migration ready (creates `notifications` table)
- SSE requires `redis.asyncio` — already covered by `redis>=5.0.0` in pyproject.toml
- Nginx must be rebuilt to pick up new SSE config
