# Requirements Document

## Introduction

Рефакторинг аутентификации Reddit-аватаров: переход от текущей модели с единым shared-клиентом (script-type app, read-only) к полноценному OAuth 2.0 flow (web-type app) с индивидуальной авторизацией каждого аватара. Каждый аватар проходит через `/api/v1/authorize`, получает собственный `refresh_token`, и система автоматически обновляет токены при истечении. Это обеспечивает масштабирование (50+ аватаров), выглядит как легитимный SaaS-инструмент, и открывает путь к self-service (клиенты подключают свои аккаунты).

## Glossary

- **OAuth_Service**: Сервис в бэкенде, отвечающий за OAuth 2.0 flow с Reddit API, генерацию authorization URL, обмен кодов на токены, и автоматическое обновление refresh_token.
- **Avatar**: Модель Reddit-аккаунта в системе, представляющая управляемый аккаунт с уникальным reddit_username.
- **Token_Store**: Компонент, отвечающий за зашифрованное хранение и извлечение OAuth-токенов (access_token, refresh_token) в PostgreSQL.
- **Reddit_OAuth_Provider**: Внешний OAuth 2.0 сервер Reddit (`https://www.reddit.com/api/v1/authorize`, `https://www.reddit.com/api/v1/access_token`).
- **Rate_Limiter**: Компонент, контролирующий частоту API-запросов к Reddit для каждого аватара в соответствии с лимитами Reddit API (60 запросов/минуту на аккаунт).
- **Credential_Encryptor**: Компонент, обеспечивающий шифрование/дешифрование секретных данных (refresh_token, access_token) перед записью/чтением из базы данных.
- **PRAW_Client_Factory**: Компонент, создающий экземпляры PRAW Reddit-клиента с индивидуальными OAuth-токенами и user_agent для каждого аватара.

## Requirements

### Requirement 1: OAuth Authorization Flow

**User Story:** As an admin, I want to authorize each avatar through Reddit's OAuth 2.0 web flow, so that each avatar has its own legitimate OAuth credentials instead of shared password-based auth.

#### Acceptance Criteria

1. WHEN an admin initiates OAuth authorization for an avatar, THE OAuth_Service SHALL generate a Reddit authorization URL with `response_type=code`, the avatar's unique `state` parameter, and scopes `identity,read,submit,privatemessages,history`.
2. WHEN Reddit redirects back with an authorization code, THE OAuth_Service SHALL exchange the code for an access_token and refresh_token via `POST /api/v1/access_token`.
3. WHEN the token exchange succeeds, THE OAuth_Service SHALL store the refresh_token and access_token associated with the avatar in the Token_Store.
4. WHEN the token exchange succeeds, THE OAuth_Service SHALL verify that the authorized Reddit username matches the avatar's `reddit_username` field.
5. IF the authorized Reddit username does not match the avatar's `reddit_username`, THEN THE OAuth_Service SHALL reject the authorization and return a descriptive error message.
6. IF the authorization code exchange fails, THEN THE OAuth_Service SHALL log the error and return a descriptive error message to the admin.
7. WHEN an admin initiates OAuth authorization, THE OAuth_Service SHALL include a cryptographically random `state` parameter to prevent CSRF attacks.

### Requirement 2: Token Storage and Encryption

**User Story:** As a system operator, I want OAuth tokens stored encrypted at rest, so that a database breach does not expose Reddit credentials.

#### Acceptance Criteria

1. WHEN the Token_Store saves a refresh_token or access_token, THE Credential_Encryptor SHALL encrypt the token using AES-256-GCM before writing to the database.
2. WHEN the Token_Store retrieves a token for use, THE Credential_Encryptor SHALL decrypt the token from the database and return the plaintext value.
3. THE Token_Store SHALL store each avatar's tokens in dedicated columns on the Avatar model: `oauth_access_token`, `oauth_refresh_token`, `oauth_token_expires_at`, `oauth_scopes`.
4. THE Token_Store SHALL store the `oauth_authorized_at` timestamp indicating when the avatar was last successfully authorized.
5. IF decryption fails due to a corrupted or invalid token, THEN THE Token_Store SHALL log the error and mark the avatar's OAuth status as `invalid`.

### Requirement 3: Automatic Token Refresh

**User Story:** As a system operator, I want access tokens to be refreshed automatically before expiry, so that avatar operations are never interrupted by expired tokens.

#### Acceptance Criteria

1. WHEN a PRAW client is requested for an avatar and the access_token expires within 5 minutes, THE OAuth_Service SHALL refresh the token using the stored refresh_token before returning the client.
2. WHEN a token refresh succeeds, THE Token_Store SHALL update the stored access_token and expiration timestamp.
3. IF a token refresh fails with an `invalid_grant` error, THEN THE OAuth_Service SHALL mark the avatar's OAuth status as `revoked` and emit an activity event.
4. IF a token refresh fails due to a network error, THEN THE OAuth_Service SHALL retry up to 3 times with exponential backoff before marking the token as `error`.
5. WHILE an avatar's OAuth status is `revoked` or `invalid`, THE PRAW_Client_Factory SHALL refuse to create a client for that avatar and log a warning.

### Requirement 4: Per-Avatar PRAW Client Creation

**User Story:** As a developer, I want to obtain a configured PRAW client for any authorized avatar, so that all Reddit API calls are made with the correct identity and rate limits.

#### Acceptance Criteria

1. WHEN a PRAW client is requested for an avatar, THE PRAW_Client_Factory SHALL create a `praw.Reddit` instance configured with the avatar's OAuth access_token and a unique user_agent containing the avatar's reddit_username.
2. THE PRAW_Client_Factory SHALL format the user_agent as `platform:reddit-saas:v1.0 (by /u/{reddit_username})` for each avatar.
3. WHEN a PRAW client is created, THE PRAW_Client_Factory SHALL configure it as an authenticated (non-read-only) client capable of submitting comments and posts.
4. IF an avatar has no valid OAuth tokens, THEN THE PRAW_Client_Factory SHALL raise a descriptive exception instead of returning an unauthenticated client.

### Requirement 5: Per-Avatar Rate Limiting

**User Story:** As a system operator, I want each avatar's Reddit API usage rate-limited independently, so that one avatar's activity does not cause rate limit errors for other avatars.

#### Acceptance Criteria

1. THE Rate_Limiter SHALL track API request counts per avatar independently using a sliding window of 60 seconds.
2. WHILE an avatar has made 60 or more requests in the current 60-second window, THE Rate_Limiter SHALL delay subsequent requests for that avatar until the window resets.
3. WHEN a request is delayed due to rate limiting, THE Rate_Limiter SHALL log the delay duration and avatar username.
4. THE Rate_Limiter SHALL use Redis for tracking request counts to support distributed workers (Celery).
5. IF Redis is unavailable, THEN THE Rate_Limiter SHALL fall back to in-memory tracking with a conservative limit of 30 requests per 60 seconds per avatar.

### Requirement 6: OAuth Status Tracking on Avatar Model

**User Story:** As an admin, I want to see the OAuth authorization status of each avatar at a glance, so that I can identify avatars that need re-authorization.

#### Acceptance Criteria

1. THE Avatar model SHALL include an `oauth_status` field with values: `not_connected`, `active`, `expired`, `revoked`, `invalid`, `error`.
2. WHEN an avatar is successfully authorized via OAuth, THE OAuth_Service SHALL set the avatar's `oauth_status` to `active`.
3. WHEN a token refresh fails permanently, THE OAuth_Service SHALL update the avatar's `oauth_status` to the appropriate error state (`revoked`, `invalid`, or `error`).
4. THE Avatar model SHALL include an `oauth_error_message` field to store the last error description for non-active statuses.
5. WHEN an admin views the avatar list, THE system SHALL display the `oauth_status` for each avatar with a visual indicator (color-coded badge).

### Requirement 7: Migration from Shared Client to Per-Avatar Auth

**User Story:** As a system operator, I want a clear migration path from the current shared Reddit client to per-avatar OAuth, so that existing functionality continues working during the transition.

#### Acceptance Criteria

1. WHILE an avatar has `oauth_status` equal to `not_connected`, THE PRAW_Client_Factory SHALL fall back to the existing shared read-only Reddit client for scraping operations.
2. WHEN all avatars for a pipeline operation have `oauth_status` equal to `active`, THE system SHALL use per-avatar authenticated clients for that operation.
3. THE system SHALL maintain the existing shared Reddit client configuration (`reddit_client_id`, `reddit_client_secret` in system_settings) as a fallback for read-only scraping.
4. WHEN an avatar transitions from `not_connected` to `active`, THE OAuth_Service SHALL log an activity event recording the successful migration.

### Requirement 8: Reddit App Configuration

**User Story:** As a system operator, I want to configure the Reddit OAuth app credentials (web-type app) in system settings, so that the OAuth flow uses the correct app identity.

#### Acceptance Criteria

1. THE system SHALL store Reddit OAuth app credentials (`oauth_client_id`, `oauth_client_secret`, `oauth_redirect_uri`) in the system_settings table.
2. WHEN the OAuth flow is initiated, THE OAuth_Service SHALL use the configured `oauth_client_id`, `oauth_client_secret`, and `oauth_redirect_uri` from system_settings.
3. THE system SHALL validate that `oauth_redirect_uri` matches the URI registered in the Reddit app configuration.
4. IF OAuth app credentials are not configured, THEN THE OAuth_Service SHALL return a descriptive error message indicating that setup is required.

### Requirement 9: Encryption Key Management

**User Story:** As a system operator, I want the encryption key for OAuth tokens managed securely via environment variables, so that the key is not stored in the database alongside the encrypted data.

#### Acceptance Criteria

1. THE Credential_Encryptor SHALL read the encryption key from the `OAUTH_ENCRYPTION_KEY` environment variable.
2. THE Credential_Encryptor SHALL require the encryption key to be at least 32 bytes (256 bits).
3. IF the `OAUTH_ENCRYPTION_KEY` environment variable is not set, THEN THE system SHALL refuse to start and log a clear error message.
4. THE Credential_Encryptor SHALL use a unique nonce (IV) for each encryption operation to ensure identical plaintexts produce different ciphertexts.
