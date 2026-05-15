# Requirements Document — Telegram Posting Bot

## Introduction

Telegram Posting Bot — замена Flutter-приложения для владельцев Reddit-аватаров. Бот позволяет получать одобренные комментарии/посты, копировать текст, открывать Reddit и подтверждать публикацию — всё через Telegram-интерфейс.

**Решение заменяет:** `.kiro/specs/mobile-posting-app/` (Flutter + FCM). Все функции покрыты, App Store не нужен.

**Ключевые преимущества над Flutter:**
- Разработка 2-3 дня вместо 2 недель
- Нет App Store review, нет FCM, нет сертификатов
- Push-уведомления бесплатно (Telegram доставляет сам)
- Кросс-платформа из коробки (iOS, Android, Desktop, Web)
- Мгновенные обновления (деплой бота = все пользователи на новой версии)
- Нет установки — работник получает ссылку и сразу работает

**Юридическая модель (без изменений):**
- Владелец аккаунта сам публикует со своего устройства
- Человеческий контроль сохранён (видит текст перед публикацией)
- IP-адрес публикации = мобильный IP владельца
- Нет программного доступа к Reddit API для постинга

## Glossary

- **Avatar Owner**: Человек, владеющий Reddit-аккаунтом. Привязан к боту через telegram_user_id.
- **Posting Queue**: Очередь одобренных комментариев/постов для аватаров владельца.
- **Inline Keyboard**: Кнопки под сообщением в Telegram (Post, Skip, Confirm).
- **URL Button**: Кнопка в Telegram, открывающая ссылку (Reddit thread).
- **Avatar Assignment**: Связь между telegram_user_id и аватарами в системе.
- **Callback Query**: Нажатие inline-кнопки в Telegram (обрабатывается ботом).

## Requirements

### Requirement 1: Avatar Owner Registration & Auth

**User Story:** Как владелец аватаров, я хочу привязать свой Telegram к системе и видеть только свои аватары.

#### Acceptance Criteria

1. WHEN an Avatar Owner sends `/start` to the bot, THEY SHALL see a welcome message with instructions
2. THE system SHALL authenticate owners by `telegram_user_id` (unique, не подделывается)
3. AN admin SHALL assign avatars to owners via admin panel, указывая `telegram_user_id` или Telegram username
4. WHEN a registered owner sends `/start`, the bot SHALL show their assigned avatars and pending queue count
5. WHEN an unregistered user sends `/start`, the bot SHALL respond: "Вы не зарегистрированы. Обратитесь к менеджеру."
6. THE admin panel SHALL provide UI to link telegram_user_id to avatar_assignment

### Requirement 2: Posting Queue Display

**User Story:** Как владелец аватара, я хочу видеть список одобренных комментариев через Telegram.

#### Acceptance Criteria

1. WHEN the owner sends `/queue` or taps "📋 Queue" button, the bot SHALL show pending approved drafts
2. EACH queue message SHALL show: avatar username, subreddit, thread title (truncated 60 chars), time waiting
3. THE queue SHALL be sorted by approval time (oldest first — FIFO)
4. IF there are more than 5 items, the bot SHALL paginate with "Next →" / "← Prev" buttons
5. EACH item SHALL have an inline button "📝 Open" to see full details
6. THE bot SHALL show a summary header: "📋 Queue: 7 pending (Avatar1: 3, Avatar2: 4)"
7. WHEN the queue is empty, the bot SHALL respond: "✅ No pending posts. You're all caught up!"

### Requirement 3: Draft Detail & Posting Flow

**User Story:** Как владелец аватара, я хочу опубликовать комментарий максимально быстро через Telegram.

#### Acceptance Criteria

1. WHEN the owner taps "📝 Open" on a queue item, the bot SHALL send a detail message with:
   - Full comment text (as a regular message — owner can long-press to copy)
   - Subreddit + thread title as context
   - Inline keyboard: [🔗 Open Reddit] [✅ Posted] [⏭ Skip]
2. THE "🔗 Open Reddit" button SHALL be a URL button opening the thread in browser/Reddit app
3. WHEN the owner taps "✅ Posted", the bot SHALL:
   - Call backend API to mark draft as posted (status='posted', posted_at=now())
   - Edit the message to show "✅ Posted at HH:MM" (removes buttons)
   - Show next item in queue (if any)
4. WHEN the owner taps "⏭ Skip", the bot SHALL:
   - Log the skip event
   - Edit the message to show "⏭ Skipped"
   - Show next item in queue (if any)
5. THE bot SHALL track posting_speed_seconds (time from approval to "Posted" confirmation)
6. FOR PostDrafts, the Reddit URL SHALL point to subreddit submit page with title pre-filled

### Requirement 4: Push Notifications (Telegram Native)

**User Story:** Как владелец аватара, я хочу получать уведомления о новых одобренных комментариях.

#### Acceptance Criteria

1. WHEN a draft is approved AND the avatar has an assigned owner with telegram_user_id, the bot SHALL send a notification message within 60 seconds
2. THE notification SHALL contain: avatar username, subreddit, "New comment ready to post" + inline button "📝 Open"
3. THE system SHALL batch notifications: if 5+ drafts approved within 5 minutes for same owner, send ONE message: "📋 5 new comments ready" + "Open Queue" button
4. THE owner SHALL be able to mute notifications via `/mute` and unmute via `/unmute`
5. WHEN an approved draft has been pending >4 hours, the bot SHALL send a reminder: "⏰ 3 comments waiting >4h"

### Requirement 5: Stats & Commands

**User Story:** Как владелец аватара, я хочу видеть свою статистику постинга.

#### Acceptance Criteria

1. `/stats` SHALL show: posted today, posted this week, average speed, streak days
2. `/queue` SHALL show current pending queue
3. `/help` SHALL list all available commands
4. `/mute` / `/unmute` SHALL toggle notifications
5. `/avatars` SHALL list assigned avatars with status (active/frozen)

### Requirement 6: Backend API (same as mobile spec)

**User Story:** Бот использует те же API-эндпоинты, что были спроектированы для мобильного приложения.

#### Acceptance Criteria

1. `GET /api/mobile/queue` — approved drafts for user's assigned avatars (auth by user_id from avatar_assignment)
2. `POST /api/mobile/drafts/{id}/confirm-posted` — mark as posted, compute posting_speed_seconds
3. `POST /api/mobile/drafts/{id}/skip` — log skip event
4. `GET /api/mobile/stats` — posting stats for user
5. ALL endpoints SHALL validate avatar ownership via avatar_assignments table
6. THE bot SHALL authenticate to the API using internal service token (not JWT — bot is a trusted backend component)
7. ALL actions SHALL be logged in audit_log with source='telegram_bot'

### Requirement 7: Admin Integration

**User Story:** Как админ, я хочу управлять привязкой Telegram-аккаунтов к аватарам.

#### Acceptance Criteria

1. THE admin panel SHALL show "Telegram" field on avatar assignment UI (telegram_user_id or @username)
2. THE admin SHALL see posting stats per owner on `/admin/posting-team` page
3. THE admin SHALL be able to send a test message to an owner via admin panel (verify bot connectivity)
4. WHEN an avatar assignment is revoked, the bot SHALL notify the owner: "Avatar @username was unassigned from you"

### Requirement 8: Security & Isolation

**User Story:** Как платформа, я гарантирую что владелец видит только свои аватары.

#### Acceptance Criteria

1. ALL bot handlers SHALL validate telegram_user_id against avatar_assignments before showing any data
2. THE bot SHALL NOT store draft text after posting confirmation (stateless — fetches from API each time)
3. THE bot SHALL rate-limit commands: max 30 requests/minute per user
4. ALL posting confirmations SHALL be logged in audit_log with telegram_user_id + timestamp
5. THE bot token SHALL be stored in .env (never in code)
6. WHEN an unknown user tries commands, the bot SHALL respond with generic "Not registered" (no data leakage)
