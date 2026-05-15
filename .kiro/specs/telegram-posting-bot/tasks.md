# Implementation Tasks — Telegram Posting Bot

## Phase 1: Core Bot (Priority: P0, ~2-3 days)

### Task 1.1: Database Models & Migration
- [ ] Create `app/models/avatar_assignment.py` — SQLAlchemy model with telegram_user_id (BIGINT), avatar_id, is_active, assigned_at, assigned_by
- [ ] Create `app/models/posting_event.py` — SQLAlchemy model (draft_id, draft_type, telegram_user_id, avatar_id, action, created_at)
- [ ] Create Alembic migration: `avatar_assignments` table + indexes
- [ ] Create Alembic migration: `posting_events` table + indexes
- [ ] Create Alembic migration: add `posted_by_telegram`, `posted_source`, `posting_speed_seconds` to `comment_drafts` and `post_drafts`
- [ ] Register new models in `app/models/__init__.py`

### Task 1.2: Bot Setup & Infrastructure
- [ ] Add `aiogram>=3.4` to `pyproject.toml` dependencies
- [ ] Create `app/bot/__init__.py` — bot instance (Bot + Dispatcher)
- [ ] Create `app/bot/config.py` — bot settings (token from env, webhook URL)
- [ ] Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` to `.env.example`
- [ ] Create `app/bot/middleware.py` — auth middleware (check telegram_user_id in avatar_assignments)
- [ ] Create `app/bot/webhook.py` — FastAPI route `POST /webhook/telegram` (receives updates, feeds to dispatcher)
- [ ] Register webhook route in `app/main.py`
- [ ] Add bot startup hook: set webhook URL on app startup (lifespan event)

### Task 1.3: Core Handlers
- [ ] Create `app/bot/handlers/start.py` — `/start` command: check registration, show welcome or "not registered"
- [ ] Create `app/bot/handlers/queue.py` — `/queue` command: fetch approved drafts, format message, paginate with inline buttons
- [ ] Create `app/bot/handlers/detail.py` — `open:{draft_id}` callback: show full draft text + action buttons
- [ ] Create `app/bot/handlers/post_actions.py` — `posted:{draft_id}` callback: update status, compute speed, log event, show next
- [ ] Create `app/bot/handlers/post_actions.py` — `skip:{draft_id}` callback: log event, edit message, show next
- [ ] Create `app/bot/handlers/help.py` — `/help` command: list all commands
- [ ] Create `app/bot/handlers/avatars.py` — `/avatars` command: list assigned avatars with status
- [ ] Register all handlers in dispatcher (app/bot/__init__.py)

### Task 1.4: Bot Service Layer
- [ ] Create `app/services/telegram_bot.py` — business logic for bot operations
- [ ] Implement `get_owner_queue(telegram_user_id)` — fetch approved drafts for owner's avatars
- [ ] Implement `confirm_posted(draft_id, telegram_user_id)` — validate ownership, update status, compute speed, log
- [ ] Implement `skip_draft(draft_id, telegram_user_id)` — validate ownership, log skip event
- [ ] Implement `get_owner_stats(telegram_user_id)` — aggregate posting stats (today/week/streak)
- [ ] Implement `get_owner_avatars(telegram_user_id)` — list assigned avatars with status

### Task 1.5: Admin — Avatar Assignment UI
- [ ] Add "Telegram Owner" section to `/admin/avatars/{id}` page
- [ ] Create HTMX partial `partials/avatar_telegram_assignment.html` — form with telegram_user_id + username fields
- [ ] Add `POST /admin/avatars/{id}/assign-telegram` endpoint — create/update avatar_assignment
- [ ] Add `POST /admin/avatars/{id}/unassign-telegram` endpoint — deactivate assignment
- [ ] Add audit log entries for assignment changes
- [ ] Show current assignment status (telegram_user_id, username, assigned_at)

---

## Phase 2: Notifications (Priority: P0, ~1 day)

### Task 2.1: Notification Service
- [ ] Create `app/services/telegram_notifications.py`
- [ ] Implement `notify_owner_new_draft(avatar_id, draft)` — find owner, check mute, send message with inline buttons
- [ ] Implement batch logic: Redis INCR `tg_batch:{telegram_user_id}` with 5-min TTL, if >5 → batch message
- [ ] Implement `send_stale_reminders()` — find approved drafts >4h, group by owner, send reminders

### Task 2.2: Review Flow Integration
- [ ] Modify `routes/review.py` — after approve, call `notify_owner_new_draft` (async, non-blocking)
- [ ] Modify `routes/pages.py` — same hook on UI-based approval
- [ ] Handle case: avatar has no assigned owner (skip notification silently)

### Task 2.3: Mute/Unmute & Reminders
- [ ] Add `is_muted BOOLEAN DEFAULT false` to `avatar_assignments` table (or separate preferences)
- [ ] Create `app/bot/handlers/mute.py` — `/mute` and `/unmute` commands
- [ ] Add Celery Beat task `remind_stale_approved_drafts` — every 30 min, check for stale drafts, notify owners
- [ ] Respect mute preference in all notification paths

---

## Phase 3: Stats & Admin (Priority: P1, ~1 day)

### Task 3.1: Stats Command
- [ ] Create `app/bot/handlers/stats.py` — `/stats` command
- [ ] Format: posted today/week, avg speed, streak, pending count
- [ ] Include per-avatar breakdown if owner has multiple avatars

### Task 3.2: Admin Posting Team Page
- [ ] Create `app/templates/admin_posting_team.html` — table of all avatar owners
- [ ] Create `app/services/posting_analytics.py` — aggregate stats per owner (posted today/week, speed, skip rate)
- [ ] Add `GET /admin/posting-team` route in `routes/admin.py`
- [ ] Columns: Owner (telegram username), Avatars, Posted Today/Week, Avg Speed, Skip Rate, Last Active, Status
- [ ] Add nav link in admin sidebar

### Task 3.3: Admin Test Message
- [ ] Add "Send Test" button on avatar assignment UI
- [ ] Endpoint `POST /admin/avatars/{id}/test-telegram` — sends "🔔 Test message from RAMP" to owner
- [ ] Verify bot connectivity without waiting for real drafts

---

## Phase 4: Polish (Priority: P2, optional)

### Task 4.1: Error Handling & Edge Cases
- [ ] Handle Telegram API errors (user blocked bot, chat not found)
- [ ] Handle race conditions (draft posted by web while owner taps "Posted" in bot)
- [ ] Handle draft status changes (draft rejected while in owner's queue view)
- [ ] Graceful degradation if Redis unavailable (skip batching, send individual notifications)

### Task 4.2: Monitoring
- [ ] Log all bot interactions (command, callback, user_id, timestamp)
- [ ] Add bot health check endpoint (verify webhook is set, bot is responsive)
- [ ] Track notification delivery failures (Telegram API errors)

### Task 4.3: Earnings & Gamification (future)
- [ ] `/earnings` command — estimated payout based on posting_rate_per_comment setting
- [ ] Streak tracking with emoji milestones
- [ ] Weekly summary message (auto-sent Sunday evening)

---

## Dependencies & Blockers

| Task | Depends On | Blocker |
|------|-----------|---------|
| Task 1.2 (Bot setup) | TELEGRAM_BOT_TOKEN in .env | Need to create bot via @BotFather |
| Task 2.2 (Review hook) | Task 2.1 (notification service) | Sequential |
| Task 3.2 (Admin page) | Task 1.1 (models exist) | Sequential |
| All tasks | None external | No App Store, no Firebase, no certificates |

## Estimated Timeline

| Phase | Duration | Notes |
|-------|----------|-------|
| Phase 1: Core Bot | 2-3 days | Models + bot + handlers + admin UI |
| Phase 2: Notifications | 1 day | Hook into review + batch logic |
| Phase 3: Stats & Admin | 1 day | Stats command + posting team page |
| Phase 4: Polish | 1-2 days | Error handling, monitoring (optional for launch) |
| **Total** | **4-5 days** | vs 2 weeks for Flutter |

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Posting speed | <2 min per comment | posting_speed_seconds avg |
| Queue clearance | 90% posted within 4h | Stale draft count |
| Skip rate | <10% | skipped / total |
| Bot response time | <2s | Telegram webhook → response |
| Notification delivery | >99% | Telegram API success rate |

## Migration from Flutter Spec

The Flutter mobile-posting-app spec (`.kiro/specs/mobile-posting-app/`) is **SUPERSEDED** by this spec. Key differences:

| Aspect | Flutter Spec | Telegram Bot Spec |
|--------|-------------|-------------------|
| Auth | JWT + refresh tokens | telegram_user_id (automatic) |
| Push | FCM + device_registrations table | Telegram native (no extra table) |
| Deployment | App Store + separate Flutter build | Part of existing Docker container |
| API | HTTP endpoints (/api/mobile/*) | Direct DB/service calls (in-process) |
| Tables needed | avatar_assignments + device_registrations + posting_events | avatar_assignments + posting_events |
| Dev time | 2 weeks | 4-5 days |

**Backend API endpoints (`/api/mobile/*`) are still useful** — they can serve as a REST interface if we later add a web-based posting UI or need external integrations. But the bot itself calls services directly for performance.
