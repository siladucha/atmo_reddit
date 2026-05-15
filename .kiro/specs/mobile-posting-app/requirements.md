# Requirements Document

> ⚠️ **SUPERSEDED** — This spec is replaced by `.kiro/specs/telegram-posting-bot/`.
> Decision: Telegram bot covers 100% of functionality with 20% of development time.
> No App Store, no FCM, no Flutter. Same backend API design applies.
> Date: May 14, 2026.

## Introduction

Mobile Posting App — мобильное приложение (React Native / Expo) для владельцев Reddit-аватаров, позволяющее публиковать предварительно одобренные комментарии и посты одним нажатием кнопки.

**Ключевая проблема:** Сейчас оператор (Tzvi) вручную копирует одобренные комментарии из веб-интерфейса, логинится в Reddit-аккаунт аватара, находит нужный тред и вставляет текст. Это занимает 2-5 минут на комментарий и не масштабируется.

**Решение:** Мобильное приложение, где владелец аватара (наёмный работник или фрилансер) видит очередь одобренных комментариев для своего аккаунта и публикует их одним тапом. Приложение открывает Reddit в in-app browser с предзаполненным текстом, владелец нажимает Submit — и комментарий опубликован.

**Юридическая ценность:**
- Владелец аккаунта сам публикует со своего устройства (не автоматизация)
- Человеческий контроль сохранён (владелец видит текст перед публикацией)
- IP-адрес публикации = мобильный IP владельца (не серверный)
- Нет программного доступа к Reddit API для постинга (нет нарушения ToS)

**Бизнес-модель:**
- Владельцы аватаров — наёмные работники или фрилансеры на зарплате/гонораре
- Каждый владелец управляет 1-5 аватарами
- Оплата: фиксированная ставка за опубликованный комментарий ($0.50-2.00) или месячная зарплата
- Приложение бесплатное для владельцев (часть платформы)

## Glossary

- **Avatar Owner**: Человек, владеющий Reddit-аккаунтом (аватаром). Логинится в приложение, видит задания для своих аватаров.
- **Posting Queue**: Очередь одобренных комментариев/постов, готовых к публикации конкретным аватаром.
- **Deep Link**: URL, открывающий Reddit на нужном треде/комментарии с предзаполненным текстом (через Reddit mobile app или mobile web).
- **Posting Confirmation**: Подтверждение от владельца, что комментарий опубликован. Меняет статус draft → posted.
- **Backend API**: Новые эндпоинты в существующем FastAPI-бэкенде для мобильного приложения.
- **Push Notification**: Уведомление владельцу о новых заданиях в очереди.
- **Clipboard Mode**: Режим, где текст копируется в буфер обмена, а владелец сам вставляет его в Reddit.
- **Avatar Assignment**: Связь между Avatar Owner (user) и конкретными аватарами, которыми он управляет.

## Requirements

### Requirement 1: Avatar Owner Authentication & Assignment

**User Story:** Как владелец аватаров, я хочу залогиниться в мобильное приложение и видеть только свои аватары, чтобы получать задания только для аккаунтов, которыми я управляю.

#### Acceptance Criteria

1. WHEN an Avatar Owner opens the app for the first time, THEY SHALL see a login screen accepting email + password (same credentials as web platform)
2. WHEN authenticated, the app SHALL display only avatars assigned to this user via the `avatar_assignments` table
3. THE system SHALL support a new `avatar_assignments` table linking `users.id` → `avatars.id` with role = 'owner'
4. AN admin SHALL be able to assign/unassign avatars to owners via the existing admin panel (`/admin/avatars/{id}`)
5. THE JWT token SHALL include a claim `avatar_ids: UUID[]` listing assigned avatar IDs for efficient mobile queries
6. WHEN a user has no assigned avatars, the app SHALL show an empty state with instructions to contact the manager

### Requirement 2: Posting Queue Display

**User Story:** Как владелец аватара, я хочу видеть список одобренных комментариев, готовых к публикации, сгруппированных по аватару, чтобы быстро понять что и куда постить.

#### Acceptance Criteria

1. THE app SHALL display a queue of CommentDrafts with `status = 'approved'` for all avatars assigned to the current user
2. EACH queue item SHALL show: avatar username, subreddit name, thread title (truncated to 80 chars), comment text preview (first 100 chars), and time since approval
3. THE queue SHALL be sorted by approval time (oldest first — FIFO)
4. THE queue SHALL support pull-to-refresh and auto-refresh every 60 seconds
5. WHEN a queue item is tapped, the app SHALL open a detail view showing: full comment text, full thread title, thread URL, comment_to context, and action buttons
6. THE queue SHALL also include PostDrafts with `status = 'approved'` (displayed separately or with a "Post" badge)
7. EACH avatar section SHALL show a count badge (e.g., "StopAutomatic717 — 3 pending")

### Requirement 3: One-Tap Posting Flow (Clipboard + Deep Link)

**User Story:** Как владелец аватара, я хочу опубликовать одобренный комментарий максимально быстро — одним-двумя нажатиями, без ручного копирования и поиска треда.

#### Acceptance Criteria

1. WHEN the user taps "Post" on a comment detail view, the app SHALL:
   a. Copy the comment text (edited_draft or ai_draft) to the device clipboard
   b. Show a toast "Copied to clipboard ✓"
   c. Open the thread URL in the device's default browser (or Reddit app if installed)
2. THE app SHALL display a floating overlay/notification reminding: "Paste your comment and submit on Reddit"
3. AFTER returning to the app (or after 30 seconds), the app SHALL prompt: "Did you post this comment?" with buttons [Yes, posted ✓] [Not yet] [Skip]
4. WHEN the user confirms "Yes, posted", the app SHALL call the backend API to update `comment_draft.status = 'posted'` and `posted_at = now()`
5. WHEN the user taps "Skip", the comment SHALL remain in the queue with a "skipped" visual indicator
6. FOR PostDrafts, the same flow SHALL apply but opening the subreddit's submit page URL with title pre-filled (via Reddit URL params: `https://www.reddit.com/r/{sub}/submit?title={title}`)
7. THE app SHALL track posting attempts: timestamp of "Post" tap, timestamp of confirmation, to measure posting speed

### Requirement 4: Backend API for Mobile

**User Story:** Как разработчик мобильного приложения, мне нужны API-эндпоинты для получения очереди, подтверждения постинга и управления заданиями.

#### Acceptance Criteria

1. `GET /api/mobile/queue` — returns approved drafts for the authenticated user's assigned avatars, sorted by approval time. Supports pagination (limit/offset).
2. `POST /api/mobile/drafts/{id}/confirm-posted` — marks a draft as posted (status='posted', posted_at=now()). Only allowed if draft belongs to user's assigned avatar.
3. `POST /api/mobile/drafts/{id}/skip` — marks a draft as skipped (adds to skip list, remains approved). Only allowed for user's avatars.
4. `GET /api/mobile/stats` — returns posting stats for the user: total posted today, total posted this week, average posting speed, earnings estimate.
5. `POST /api/mobile/device` — registers device for push notifications (FCM token).
6. ALL mobile endpoints SHALL require JWT authentication and validate avatar ownership.
7. ALL mobile endpoints SHALL be prefixed with `/api/mobile/` and use JSON request/response bodies.
8. THE API SHALL return proper error codes: 401 (unauthorized), 403 (not your avatar), 404 (draft not found), 409 (already posted).

### Requirement 5: Push Notifications

**User Story:** Как владелец аватара, я хочу получать push-уведомления когда появляются новые одобренные комментарии, чтобы не проверять приложение вручную.

#### Acceptance Criteria

1. WHEN a CommentDraft status changes to 'approved' AND the assigned avatar has an owner with a registered device, THE system SHALL send a push notification within 60 seconds
2. THE notification SHALL contain: avatar username, subreddit name, and "New comment ready to post"
3. THE system SHALL batch notifications: if 5+ drafts are approved within 5 minutes for the same owner, send ONE notification "5 new comments ready"
4. THE owner SHALL be able to mute notifications per avatar or globally (stored in user preferences)
5. THE system SHALL use Firebase Cloud Messaging (FCM) for both iOS and Android
6. THE notification tap SHALL deep-link to the specific draft in the app

### Requirement 6: Posting Analytics & Gamification

**User Story:** Как менеджер (Tzvi), я хочу видеть статистику постинга каждого владельца — скорость, объём, пропуски — чтобы управлять командой и платить по результатам.

#### Acceptance Criteria

1. THE admin panel SHALL show a new "Posting Team" page at `/admin/posting-team` with:
   - List of all avatar owners
   - Per-owner stats: drafts posted today/week/month, average posting speed (time from approval to posted), skip rate
   - Per-avatar breakdown within each owner
2. THE mobile app SHALL show the owner their own stats: posted today, streak (consecutive days with posts), estimated earnings
3. THE system SHALL track `posting_speed_seconds` (time between draft approval and posted confirmation) per draft
4. THE admin SHALL be able to set a target posting speed (e.g., "post within 2 hours of approval") and see compliance rate
5. WHEN an approved draft has been pending for >4 hours without posting, THE system SHALL send a reminder push notification to the owner

### Requirement 7: Security & Isolation

**User Story:** Как платформа, я должна гарантировать что владелец видит только свои аватары и не может влиять на чужие данные.

#### Acceptance Criteria

1. ALL mobile API endpoints SHALL validate that the requested draft/avatar belongs to the authenticated user's assignments
2. THE JWT token for mobile SHALL have a shorter expiry (7 days) with refresh token support (30 days)
3. THE app SHALL support biometric authentication (Face ID / fingerprint) for quick re-login
4. THE app SHALL NOT store comment text locally after posting confirmation (no persistent cache of draft content)
5. THE app SHALL pin SSL certificates to prevent MITM attacks on the API
6. WHEN an avatar assignment is revoked, ALL pending queue items for that avatar SHALL disappear from the owner's app on next refresh
7. THE system SHALL log all mobile posting confirmations in the audit_log with source='mobile_app'

