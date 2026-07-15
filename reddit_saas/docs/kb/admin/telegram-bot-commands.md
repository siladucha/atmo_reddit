# Telegram Bot — Command Matrix by Role

## Bot: @ramp_watchdog_bot

All commands handled via webhook (`/api/telegram/webhook`). English only.

---

## Command Access Matrix

| Command | Description | Owner | Partner | Avatar Mgr | QA | Client Admin | Client Mgr | Client Viewer | B2C | Unlinked |
|---------|-------------|:-----:|:-------:|:----------:|:--:|:------------:|:----------:|:-------------:|:---:|:--------:|
| `/start` | Show Chat ID + connection info | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `/help` | Show available commands (role-filtered) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ ¹ |
| `/status` | Account info + system brief (ops) | ✅ 🔧 | ✅ 🔧 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| `/settings` | Change notification level (inline buttons) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| `/pending` | Show drafts pending review (with buttons) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| `/approve_all` | Approve all drafts for avatar (with confirmation) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| `/costs` | AI spend today ($ + budget %) | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `/avatars` | Avatar fleet (active/frozen/banned/suspended) | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `/errors` | Pipeline errors 24h (max 10) | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `/pipelines` | Latest run per pipeline type | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `/cancel` | Abort edit mode | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |

¹ Unlinked `/help` shows: how to connect + what's available after linking.
🔧 `/status` for owner/partner includes system brief (avatars, drafts, AI cost today).

---

## Data Scope by Role

| Role | Draft Visibility | Avatar Visibility |
|------|-----------------|-------------------|
| Owner | All clients, all avatars | All |
| Partner | All clients, all avatars | All |
| Avatar Manager | All clients, all avatars | All |
| QA | All clients, all avatars | — (no /avatars) |
| Client Admin | Own client only | Own client's avatars |
| Client Manager | Own client only | Own client's avatars |
| Client Viewer | — | — |
| B2C User | — | — |

---

## Notification Delivery by Role

| Role | Gets Draft Cards | Gets Ops Alerts | Required Level |
|------|:----------------:|:---------------:|:--------------:|
| Owner | ✅ | ✅ (warning + critical) | ≥ warning |
| Partner | ✅ | ✅ (warning + critical) | ≥ warning |
| Avatar Manager | ✅ | ❌ | ≥ warning |
| QA | ✅ | ❌ | ≥ warning |
| Client Admin | ✅ (own client) | ❌ | ≥ warning |
| Client Manager | ✅ (own client) | ❌ | ≥ warning |
| Client Viewer | ❌ | ❌ | — |
| B2C User | ❌ | ❌ | — |

---

## Inline Buttons (Draft Cards)

| Button | Action | Notes |
|--------|--------|-------|
| ✅ Approve | Approves draft + creates execution task | Idempotent |
| ❌ Skip | Rejects draft + marks slot skipped | Idempotent |
| ✏️ Edit | Enters edit mode (reply with guidance) | Shows /cancel hint |
| ✅ Approve All | Bulk-approves for avatar (from summary card) | — |

---

## /approve_all Confirmation Flow

```
User: /approve_all HotThought2408
Bot:  ⚡ Approve 7 drafts for u/HotThought2408?
      [✅ Yes, approve all] [❌ Cancel]
User: taps "Yes"
Bot:  ✅ Approved 7 drafts for u/HotThought2408
```

---

## Edit Flow with /cancel

```
User: taps ✏️ Edit on draft card
Bot:  ✏️ Edit mode
      [full draft text]
      💡 Reply with corrections. Type /cancel to abort.
User: /cancel (as reply)
Bot:  ✅ Edit cancelled. Draft unchanged. Use /pending to review again.
```

---

## /settings Inline Flow

```
User: /settings
Bot:  ⚙️ Notification Settings
      Current: ⚠️ Warning + Critical
      [📢 All] [✓ ⚠️ Warning+Critical] [🔴 Critical] [🔇 Off]
User: taps "📢 All"
Bot:  ✅ Notification level updated: 📢 All
```

---

## /costs Output Example

```
💰 AI Costs Today

  Spent: $4.12 / $20
  █████████░ 21%
  Calls: 318
  Max single: $0.0821
```

---

## Connection Flow

```
1. Open Telegram → find @ramp_watchdog_bot → /start
2. Bot shows: "Your Chat ID: 123456789"
3. Go to RAMP panel → Profile → Telegram → paste Chat ID → Connect
4. Bot sends confirmation: "✅ Telegram connected! Use /help for commands."
5. Done — notifications flow based on level.
```

---

## Post-Connect Confirmation (automatic)

When user clicks "Connect" in RAMP profile, the bot immediately sends:
```
✅ Telegram connected!
Account: max@example.com
Notification level: 🔴 Critical only
Use /help for commands.
Use /settings to change notification level.
```

---

## Security Model

| Aspect | Implementation |
|--------|---------------|
| Callback auth | Short Redis ID → resolves to `{draft_id, action, user_id}`. Server re-checks `user_id` match. |
| Permission check | Every callback action re-verifies user has access to that draft's client (P7). |
| Idempotency | Repeated button press on same draft = no-op (draft already approved/rejected). |
| Redis as state | Temporary only (24h TTL callbacks, 30min TTL edit sessions). No persistent dependency. |
| Webhook secret | `X-Telegram-Bot-Api-Secret-Token` validated on every request. |
| Failure tolerance | 3 consecutive delivery failures → auto-clear user's `telegram_chat_id`. |

---

## Technical Notes

- Webhook: `POST /api/telegram/webhook`
- Register commands: `POST /api/telegram/register-commands` (call once)
- Bot token: DB `system_settings` → `telegram_bot_token`
- Webhook secret: DB `system_settings` → `telegram_webhook_secret`
- Kill switch: `telegram_draft_review_enabled` (default `false`)
- Callback TTL: 24 hours
- Edit session TTL: 30 minutes
