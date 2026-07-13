# Implementation Plan: Telegram Draft Review Channel

## Overview

Add Telegram as an additional draft review channel. 15 tasks covering: Redis callback infrastructure, Telegram Bot API wrapper, message formatting, webhook route, draft review logic (approve/skip/edit/bulk), command handlers, EPG integration hook, startup registration, settings, and deployment.

**Estimated effort:** 3-5 days focused work.
**Dependencies:** Existing `telegram_chat_id` on User model, existing `telegram_bot_token` in system_settings, Redis available.

## Tasks

- [ ] 1. Create Callback Store (Redis mapping for Telegram callback_data 64-byte limit). Create `app/services/telegram/__init__.py` and `app/services/telegram/callback_store.py`. Implement `CallbackStore` class with `create(draft_id, action, user_id)` → generates `secrets.token_urlsafe(12)` (16 chars), stores JSON in Redis `tg:cb:{id}` with 24h TTL. Implement `resolve(callback_id)` → reads and parses Redis key. Implement `invalidate(callback_id)` → deletes key. **Requirements: 9.2, 9.3, 9.6**
- [ ] 2. Create Bot Service (Telegram API wrapper). Create `app/services/telegram/bot_service.py` with `TelegramBotService` class. Implement `send_message`, `edit_message_text`, `edit_message_reply_markup`, `answer_callback_query`, `register_webhook`, `set_my_commands`. Use `httpx.AsyncClient` with 10s timeout. Add rate limiter (50ms between sends to same chat). Handle 4xx/5xx errors gracefully. **Requirements: 2.6, 11.1, 11.2, 11.3**
- [ ] 3. Create Draft Card Formatter. Create `app/services/telegram/formatter.py` with `DraftCardFormatter`. Implement `format_draft_card(draft, callback_ids, client_name)` → HTML: subreddit, avatar, thread link (80ch), body (300ch), InlineKeyboard [Approve|Skip|Edit]. Implement `format_summary(drafts_by_avatar, callback_ids)` → per-avatar Approve All buttons. Implement `format_approved/format_skipped/format_edit_prompt`. Handle HTML escaping and 4096-char message limit. **Requirements: 2.2, 2.3, 2.8**
- [ ] 4. Create Webhook Route. Create `app/routes/telegram_webhook.py`. Implement `POST /api/telegram/webhook` — validate `X-Telegram-Bot-Api-Secret-Token` header, parse Update JSON, route by type (callback_query / reply / command). Always return 200. Add router to `app/main.py`. Add to `auth.py` PUBLIC_ROUTES. Add nginx location block. **Requirements: 11.1, 11.2, 11.4, 11.6**
- [ ] 5. Implement Draft Review — Approve & Skip. In `app/services/telegram/draft_review.py` create `TelegramDraftReview` class. Implement `approve_draft(db, user, draft_id)` — verify pending + access (P7), set approved, sync EPG slot, create ExecutionTask, record activity event. Implement `skip_draft(db, user, draft_id)` — verify + reject + skip slot. Implement `_user_can_review_draft(user, draft)` — role-based (owner/partner=all, client_admin/manager=assigned). Handle idempotent case. **Requirements: 3.1, 3.2, 3.5, 4.1, 4.2, 4.4, 9.4**
- [ ] 6. Implement Draft Review — Notification Delivery. Implement `notify_pending_drafts(db, client_id, drafts)` — query eligible users (chat_id set, level=all/warning, review role, access to client, autopilot=false), check draft still pending, create callback_ids, format cards, send via bot_service. If >5 drafts: summary first. Handle API errors (increment `tg:fail:{user_id}`, clear chat_id after 3 failures/24h). **Requirements: 1.6, 2.1, 2.4, 2.5, 2.7, 7.2, 7.3**
- [ ] 7. Implement Draft Review — Bulk Approve (per avatar). Implement `bulk_approve(db, user, avatar_username)` — load avatar, verify access (P7), query pending drafts, approve all, create ExecutionTasks, commit, return count. Handle zero-pending case. **Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.7**
- [ ] 8. Implement Draft Review — Edit Flow (LLM Regeneration). Implement `start_edit_session(db, user, draft_id, chat_id, message_id)` — store edit session in Redis `tg:edit:{chat_id}:{message_id}` with 30min TTL. Implement `process_edit_reply(db, user, draft_id, guidance_text)` — load draft+thread context, call LLM (llm_generation_model) with original+guidance, update draft.body, log_ai_usage("telegram_draft_edit"), record in learning service. Handle LLM failure gracefully. Add operation to admin stage_map + billing op_labels. **Requirements: 5.1, 5.2, 5.3, 5.5, 5.6, 5.7**
- [ ] 9. Implement Command Handlers. In webhook route implement `_handle_command(message)`: lookup User by chat_id, route to `/start` (welcome), `/help` (command list), `/pending` (grouped draft cards), `/status` (account info), `/approve_all <avatar>` (bulk approve). Handle unlinked user and unknown commands. **Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 1.4**
- [ ] 10. Implement Callback Handler (button presses). In webhook route implement `_handle_callback(callback_query)`: answer_callback_query immediately, resolve callback_id from Redis, verify user, route by action (approve/skip/edit/approve_all), edit message on success, show error on failure, handle already-reviewed drafts. **Requirements: 3.1, 3.3, 3.4, 4.1, 4.3, 4.5, 5.1**
- [ ] 11. Implement Reply Handler (edit flow). In webhook route implement `_handle_reply(message)`: check Redis for edit session by `tg:edit:{chat_id}:{reply_to_message_id}`, if found → call `process_edit_reply`, send new Draft_Card with regenerated text. Ignore replies without matching session. **Requirements: 5.2, 5.3, 5.4, 5.6**
- [ ] 12. EPG Integration Hook. Modify `app/services/epg_executor.py` → `_notify_drafts_pending()`: after existing portal bell call, check `telegram_draft_review_enabled` setting, collect generated drafts, call `TelegramDraftReview().notify_pending_drafts()`. Wrap in try/except (never break pipeline). Hook both professional and hobby generation paths. **Requirements: 2.1, 10.3**
- [ ] 13. Webhook Registration on Startup. Add to `app/main.py` lifespan: read settings, if bot_token + webhook_secret + enabled → call `register_webhook()` + `set_my_commands()`. On failure: log error, schedule retry every 60s (non-blocking). **Requirements: 11.3, 11.5**
- [ ] 14. System Settings & Kill Switch. Add `telegram_draft_review_enabled` (default "false") and `telegram_webhook_secret` (default "") to DEFAULT_SETTINGS in `app/services/settings.py`. Verify existing `telegram_notifications_level` filtering works for review (all/warning → yes, critical/off → no). **Requirements: 7.2, 7.3, 7.5**
- [ ] 15. Deploy & Verify. Update nginx.conf, run pre-flight, deploy to staging, test E2E (link → generate → receive card → approve/skip/edit → verify status → /pending command). Deploy to production with user permission. Register webhook on production. **Requirements: 11.6**

## Task Dependency Graph

```json
{
  "waves": [
    {
      "wave": 1,
      "tasks": [1, 2, 14],
      "description": "Foundation — Redis callback store, Telegram API wrapper, system settings"
    },
    {
      "wave": 2,
      "tasks": [3, 4, 5, 8],
      "description": "Core logic — Formatter, webhook route, approve/skip service, edit/LLM service"
    },
    {
      "wave": 3,
      "tasks": [6, 7, 9, 10, 11],
      "description": "Integration — Notification delivery, bulk approve, command/callback/reply handlers"
    },
    {
      "wave": 4,
      "tasks": [12, 13],
      "description": "Wiring — EPG hook, webhook registration on startup"
    },
    {
      "wave": 5,
      "tasks": [15],
      "description": "Deploy — Staging test, production deploy, E2E verification"
    }
  ]
}
```

**Critical path:** 1 → 3 → 6 → 12 → 15 and 2 → 4 → 10 → 15

**Parallelizable within waves:** Wave 1 all parallel. Wave 2 all parallel (depend only on wave 1). Wave 3 depends on wave 2 components.

## Notes

- No new database migrations required — all state in Redis (transient) + existing User model fields
- No new Python dependencies — uses existing `httpx`
- LLM regeneration (Task 8) uses `call_llm()` + `log_ai_usage()` — P3 compliance automatic
- Kill switch `telegram_draft_review_enabled` allows gradual rollout without deploy
- Same bot token as ops alerts — routing by User role, not by bot instance
- Telegram webhook requires HTTPS (already have via Let's Encrypt on gorampit.com)
