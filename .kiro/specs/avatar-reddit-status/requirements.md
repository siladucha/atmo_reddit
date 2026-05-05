# Requirements Document

## Introduction

На странице `/avatars-page` отображается список аватаров с метриками здоровья, рассчитанными на основе внутренних данных (количество комментариев, brand ratio и т.д.). Однако реальный статус Reddit-аккаунта (актуальная карма, существование аккаунта, бан/suspension, shadowban) не проверяется через Reddit API.

Данная фича добавляет получение реального статуса Reddit-аккаунта через PRAW API и отображение этой информации на странице аватаров. Это позволит оператору видеть актуальное состояние каждого аватара в Reddit: жив ли аккаунт, не забанен ли, какая у него реальная карма и когда он последний раз был активен.

## Glossary

- **Avatar**: Сущность в системе, представляющая Reddit-аккаунт, используемый для публикации комментариев. Модель `Avatar` в БД.
- **Reddit_Status_Service**: Сервисный модуль, отвечающий за получение статуса Reddit-аккаунта через PRAW API.
- **Avatars_Page**: Страница `/avatars-page`, отображающая список аватаров с метриками.
- **PRAW_Client**: Клиент Reddit API (библиотека PRAW), используемый для получения данных об аккаунтах.
- **Reddit_Account_Status**: Набор данных о состоянии Reddit-аккаунта: существование, suspension, shadowban, карма, дата создания, последняя активность.
- **Status_Cache**: Кэшированные данные о статусе Reddit-аккаунта в БД, обновляемые по запросу для снижения нагрузки на Reddit API.
- **Status_Badge**: Визуальный индикатор на карточке аватара, отображающий текущий статус Reddit-аккаунта.

## Requirements

### Requirement 1: Получение статуса Reddit-аккаунта через API

**User Story:** As an operator, I want to fetch the real Reddit account status for each avatar, so that I can see whether the account is alive, suspended, or shadowbanned on Reddit.

#### Acceptance Criteria

1. WHEN the operator requests a status check for an avatar, THE Reddit_Status_Service SHALL fetch the Reddit account data using PRAW_Client by the avatar's `reddit_username`.
2. THE Reddit_Status_Service SHALL return the following fields for each account: account existence (boolean), suspension status (boolean), real comment karma (integer), real post karma (integer), Reddit account creation date (datetime), and account icon URL (string or null).
3. IF the Reddit account does not exist or has been deleted, THEN THE Reddit_Status_Service SHALL return a status indicating the account is not found, with all numeric fields set to zero.
4. IF the PRAW_Client raises a network or authentication error, THEN THE Reddit_Status_Service SHALL return an error status with a descriptive message and SHALL NOT update the previously cached status.
5. IF the Reddit account is suspended, THEN THE Reddit_Status_Service SHALL detect the suspension by handling the PRAW `Forbidden` exception or checking the `is_suspended` attribute and SHALL return a status indicating suspension.

### Requirement 2: Кэширование статуса в базе данных

**User Story:** As an operator, I want the Reddit status to be cached in the database, so that the avatars page loads quickly without hitting the Reddit API on every page view.

#### Acceptance Criteria

1. THE Avatar model SHALL store cached Reddit status fields: `reddit_status` (string: "active", "suspended", "not_found", "unknown"), `reddit_karma_comment` (integer), `reddit_karma_post` (integer), `reddit_account_created` (datetime or null), `reddit_icon_url` (string or null), and `reddit_status_checked_at` (datetime or null).
2. WHEN a status check completes successfully, THE Reddit_Status_Service SHALL update the cached fields on the Avatar record and set `reddit_status_checked_at` to the current UTC timestamp.
3. WHEN the Avatars_Page loads, THE Avatars_Page SHALL display the cached Reddit status data without making Reddit API calls.
4. THE Avatars_Page SHALL display the timestamp of the last status check next to each avatar's Reddit status, formatted as a relative time (e.g., "5 мин назад", "2 часа назад").

### Requirement 3: Проверка статуса по запросу (кнопка на UI)

**User Story:** As an operator, I want to trigger a Reddit status check for a single avatar or for all avatars at once, so that I can refresh the data when needed.

#### Acceptance Criteria

1. THE Avatars_Page SHALL display a "Check Status" button on each avatar card that triggers a status check for that specific avatar.
2. THE Avatars_Page SHALL display a "Check All" button in the page header that triggers a status check for all visible avatars.
3. WHEN the operator clicks the "Check Status" button for a single avatar, THE Avatars_Page SHALL send an HTMX request to the backend and SHALL replace the avatar card content with updated status data upon response.
4. WHEN the operator clicks the "Check All" button, THE Avatars_Page SHALL send an HTMX request to the backend and SHALL sequentially check each avatar's status, updating each card as results arrive.
5. WHILE a status check is in progress for an avatar, THE Avatars_Page SHALL display a loading indicator on the corresponding avatar card.
6. IF a status check fails for one avatar during a "Check All" operation, THEN THE Avatars_Page SHALL continue checking the remaining avatars and SHALL display an error indicator on the failed avatar card.

### Requirement 4: Отображение реального Reddit-статуса на карточке аватара

**User Story:** As an operator, I want to see the real Reddit account status visually on each avatar card, so that I can quickly identify problematic accounts.

#### Acceptance Criteria

1. THE Avatars_Page SHALL display a Status_Badge on each avatar card with the following visual states: green "Active" for active accounts, red "Suspended" for suspended accounts, gray "Not Found" for deleted or non-existent accounts, and yellow "Unknown" for accounts that have never been checked.
2. THE Avatars_Page SHALL display the real Reddit comment karma and post karma from the cached data, separately from the internally tracked karma values.
3. THE Avatars_Page SHALL display the Reddit account age calculated from the cached `reddit_account_created` field.
4. WHEN the cached Reddit karma differs from the internally stored karma by more than 10%, THE Avatars_Page SHALL highlight the karma values to indicate a discrepancy.
5. WHEN the `reddit_status_checked_at` value is older than 24 hours, THE Avatars_Page SHALL display a "stale" indicator next to the status to signal that the data may be outdated.

### Requirement 5: API-эндпоинт для проверки статуса

**User Story:** As a developer, I want a REST API endpoint to trigger Reddit status checks, so that the status check can be called from the UI via HTMX and potentially from background tasks.

#### Acceptance Criteria

1. THE Avatars API SHALL expose a `POST /api/avatars/{avatar_id}/check-reddit-status` endpoint that triggers a Reddit status check for a single avatar and returns the updated status data.
2. THE Avatars API SHALL expose a `POST /api/avatars/check-reddit-status-all` endpoint that triggers a Reddit status check for all active avatars and returns a summary of results.
3. WHEN the single-avatar endpoint is called, THE Avatars API SHALL return the updated Reddit_Account_Status as a JSON response within 10 seconds.
4. WHEN the check-all endpoint is called with more than 10 avatars, THE Avatars API SHALL process the checks with a 2-second delay between each request to avoid Reddit API rate limiting.
5. IF the avatar ID does not exist, THEN THE Avatars API SHALL return HTTP 404 with a descriptive error message.

### Requirement 6: HTMX-partial для обновления карточки аватара

**User Story:** As an operator, I want the avatar card to update in-place after a status check, so that I don't need to reload the entire page.

#### Acceptance Criteria

1. THE Avatars_Page SHALL use an HTMX partial template for each avatar card, so that individual cards can be replaced without a full page reload.
2. WHEN the status check endpoint returns a response, THE Avatars_Page SHALL swap the content of the corresponding avatar card with the updated partial.
3. THE HTMX partial SHALL render the same layout and data as the full-page avatar card, ensuring visual consistency.

### Requirement 7: Автоматическое обновление флага shadowban

**User Story:** As an operator, I want the system to automatically update the shadowban flag when a Reddit status check detects a suspension, so that the safety system can react accordingly.

#### Acceptance Criteria

1. WHEN a Reddit status check detects that an account is suspended, THE Reddit_Status_Service SHALL set the `is_shadowbanned` field on the Avatar record to `true`.
2. WHEN a Reddit status check detects that a previously suspended account is now active, THE Reddit_Status_Service SHALL set the `is_shadowbanned` field on the Avatar record to `false`.
3. WHEN the `is_shadowbanned` field is changed by a status check, THE Reddit_Status_Service SHALL log an audit event with the avatar username, previous status, and new status.
