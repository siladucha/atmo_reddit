# Requirements Document

## Introduction

Per-user Telegram notification system for the RAMP platform. Extends the existing client-scoped SSE notification infrastructure to deliver real-time alerts via Telegram to platform users (owner, partner, avatar_manager, qa) and client-scoped users (client_admin, client_manager) based on their role and notification preferences. Reuses the existing watchdog Telegram bot (single bot, routing by chat_id) with a new webhook endpoint for receiving bot updates and a one-time token flow for user connection.

## Glossary

- **Telegram_Service**: The backend service responsible for sending Telegram messages to users and processing incoming bot updates via webhook.
- **Notification_Router**: The component that determines which users receive a given notification event based on role-based defaults and per-user preferences.
- **Connect_Flow**: The user-facing process of linking a Telegram account to a RAMP user via a one-time token and the bot's /start command.
- **Webhook_Endpoint**: The FastAPI route at `/api/telegram/webhook` that receives updates from Telegram Bot API.
- **Notification_Preferences**: A JSONB column on the User model storing per-event-type opt-in/opt-out settings.
- **Platform_Event**: A notification event not scoped to a single client (e.g., infra alerts, cost spikes, trial signals).
- **Client_Event**: A notification event scoped to a specific client (e.g., pipeline_complete, draft_posted, avatar_frozen).

## Requirements

### Requirement 1: User Model Extension

**User Story:** As a platform administrator, I want users to have Telegram connection fields and notification preferences stored in the database, so that the system can route notifications per-user.

#### Acceptance Criteria

1. THE User model SHALL include a `telegram_chat_id` field (String, max 64 characters, nullable, unique) for storing the connected Telegram chat identifier.
2. THE User model SHALL include a `telegram_connected_at` field (DateTime with timezone, nullable) recording when the Telegram account was linked.
3. THE User model SHALL include a `notification_preferences` field (JSONB, nullable, default NULL) storing a JSON object where each key is an event type string and each value is a boolean indicating opt-in (true) or opt-out (false).
4. THE User model SHALL include a `telegram_username` field (String, max 128 characters, nullable) for storing the Telegram display name provided during connection.
5. WHEN `notification_preferences` is NULL, THE Notification_Router SHALL apply role-based default preferences for that user's role, where internal roles (owner, partner, avatar_manager, qa) default to all event types opted-in, and client-scoped roles (client_admin, client_manager, client_viewer, b2c_user) default to only their own client's events opted-in.
6. IF a `telegram_chat_id` value is stored that already exists on another user record, THEN THE System SHALL reject the write and return a uniqueness constraint error.

### Requirement 2: Telegram Connect Flow

**User Story:** As a RAMP user, I want to connect my Telegram account via a one-time token link, so that I can receive notifications on my phone.

#### Acceptance Criteria

1. WHEN a user clicks "Connect Telegram" in their settings page, THE system SHALL invalidate any previously generated pending token for that user, generate a new one-time token (32-byte URL-safe, 15-minute expiry), and store its SHA-256 hash in the database.
2. WHEN a token is successfully generated, THE system SHALL present the user with a link in the format `https://t.me/<bot_username>?start=<token>`.
3. WHEN the Telegram bot receives a `/start <token>` message, THE Webhook_Endpoint SHALL validate the token hash against the database, verify it has not expired, and verify it has not already been consumed.
4. IF the token is valid, not expired, and not consumed, THEN THE Webhook_Endpoint SHALL atomically mark the token as consumed, store the sender's `chat_id` on the corresponding User record, set `telegram_connected_at` to the current time, store the Telegram username, and send a confirmation message to the user via Telegram.
5. IF the sender's `chat_id` is already associated with a different User record, THEN THE Webhook_Endpoint SHALL reject the connection and respond to the Telegram user with an error message indicating the Telegram account is already linked to another RAMP user.
6. IF the token is invalid, expired, or already consumed, THEN THE Webhook_Endpoint SHALL respond to the Telegram user with an error message instructing them to generate a new link from RAMP settings.
7. WHEN a user already has a `telegram_chat_id` set, THE settings page SHALL show a "Disconnect Telegram" option instead of "Connect Telegram".
8. WHEN a user disconnects Telegram, THE system SHALL clear `telegram_chat_id`, `telegram_connected_at`, and `telegram_username` from the User record and send a confirmation message to the Telegram chat indicating notifications have been disabled.

### Requirement 3: Webhook Endpoint

**User Story:** As a system operator, I want a webhook endpoint registered with the Telegram Bot API, so that the bot can receive and process user messages.

#### Acceptance Criteria

1. THE system SHALL expose a POST endpoint at `/api/telegram/webhook` that accepts Telegram Bot API update payloads with a maximum request body size of 1 MB, and SHALL return HTTP 200 within 5 seconds for all valid requests to prevent Telegram retry storms.
2. THE Webhook_Endpoint SHALL verify incoming requests by comparing a secret token (passed via the `X-Telegram-Bot-Api-Secret-Token` header) against the configured `TELEGRAM_WEBHOOK_SECRET` environment variable using a constant-time comparison.
3. IF the webhook secret verification fails, THEN THE Webhook_Endpoint SHALL return HTTP 403 without processing the update.
4. WHEN the Webhook_Endpoint receives an update with a `/start <token>` command, THE system SHALL process the Connect_Flow as defined in Requirement 2.
5. WHEN the Webhook_Endpoint receives an update with a `/stop` command from a user whose `telegram_chat_id` matches the sender's chat_id, THE system SHALL clear the user's `telegram_chat_id`, `telegram_connected_at`, and `telegram_username`, and send a confirmation message indicating that notifications are disabled.
6. IF the Webhook_Endpoint receives a `/stop` or `/status` command from a chat_id that does not match any connected user, THEN THE Webhook_Endpoint SHALL respond with a message indicating the user is not connected and instructing them to connect via RAMP settings.
7. WHEN the Webhook_Endpoint receives a `/status` command from a user whose `telegram_chat_id` matches the sender's chat_id, THE system SHALL respond with the user's display name, role, and a list of enabled notification event types from their effective preferences (explicit or role-based defaults).
8. WHEN the Webhook_Endpoint receives an unrecognized command or plain text message, THE system SHALL respond with a help message listing available commands for the user's role (per Requirement 10) and a one-line description of each.
9. IF the update payload cannot be parsed as a valid Telegram Update object or contains no message and no callback_query, THEN THE Webhook_Endpoint SHALL return HTTP 200 with no further processing.
10. WHEN the Webhook_Endpoint receives a role-based command (/clients, /health, /costs, /errors, /pipeline, /kill, /trials, /mrr, /attention, /avatars, /frozen, /unfreeze, /drafts, /schedule, /approve, /queue, /review, /mute), THE system SHALL dispatch to the corresponding handler as defined in Requirement 10.
11. WHEN the Webhook_Endpoint receives a `callback_query` update (inline keyboard tap), THE system SHALL parse the callback data, validate the user's permissions, execute the action (approve/reject), and answer the callback query as defined in Requirement 10 acceptance criteria 23-28.

### Requirement 4: Role-Based Default Notification Types

**User Story:** As a platform architect, I want each role to have sensible default notification types, so that users receive relevant alerts without manual configuration.

#### Acceptance Criteria

1. THE Notification_Router SHALL apply the following default notification types for the `owner` role: avatar_frozen, error, cost_spike, pipeline_dead_7d, infra_alert.
2. THE Notification_Router SHALL apply the following default notification types for the `partner` role: new_trial, trial_expired, client_inactive_7d, mrr_change.
3. THE Notification_Router SHALL apply the following default notification types for the `avatar_manager` role: avatar_frozen, shadowban_detected, cqs_dropped, health_alert.
4. THE Notification_Router SHALL apply the following default notification types for the `qa` role: drafts_ready, bulk_pending.
5. THE Notification_Router SHALL apply the following default notification types for `client_admin` and `client_manager` roles: pipeline_complete, epg_rebuilt, draft_posted, avatar_frozen.
6. THE Notification_Router SHALL NOT send Telegram notifications to users with role `client_viewer` or `b2c_user` by default, AND SHALL treat these roles as having an empty default notification type set that can be overridden via explicit `notification_preferences`.
7. WHEN a user has `notification_preferences` set (non-NULL), THE Notification_Router SHALL use only the event types explicitly set to `true` in the preferences object and SHALL treat any event type not present in the object as disabled.
8. IF a user's `notification_preferences` contains event types not listed in the defaults for that user's role, THEN THE Notification_Router SHALL still honor those preferences and deliver notifications for any event type set to `true`.

### Requirement 5: Notification Preferences Management

**User Story:** As a user, I want to configure which notification types I receive via Telegram, so that I only get alerts relevant to me.

#### Acceptance Criteria

1. WHILE a user has a non-NULL `telegram_chat_id`, THE system SHALL display a notification preferences section in the user's settings page showing all notification event types available for that user's role as toggles (on/off).
2. THE settings UI SHALL derive the current state of each toggle from the user's `notification_preferences` JSONB if non-NULL, or from the role-based defaults defined in Requirement 4 if NULL, so that the user sees which events are currently active.
3. WHEN a user saves notification preferences, THE system SHALL store the configuration in `notification_preferences` as a JSON object mapping event type strings to boolean values (e.g., `{"avatar_frozen": true, "pipeline_complete": false}`).
4. THE system SHALL provide an API endpoint `PATCH /api/users/me/notification-preferences` accepting a JSON body with event type toggles, returning HTTP 200 with the updated full preferences object on success.
5. IF the PATCH request body contains event type keys that are not in the set of notification types available for the requesting user's role, THEN THE system SHALL reject the request with HTTP 422 and an error message indicating which keys are invalid.
6. IF the PATCH request body is not valid JSON or contains more than 30 keys, THEN THE system SHALL reject the request with HTTP 422 and an error message indicating the validation failure.
7. WHEN a user resets preferences to defaults, THE system SHALL set `notification_preferences` to NULL, causing the Notification_Router to revert to role-based defaults as defined in Requirement 4.

### Requirement 6: Telegram Message Delivery

**User Story:** As a connected user, I want to receive formatted Telegram messages when relevant events occur, so that I am informed in real time.

#### Acceptance Criteria

1. THE Telegram_Service SHALL send messages using the existing watchdog bot token configured in the `TELEGRAM_BOT_TOKEN` environment variable.
2. THE Telegram_Service SHALL format messages using Telegram HTML parse mode with a severity icon prefix (✅ success, ⚠️ warning, 🔴 error, ℹ️ info).
3. THE Telegram_Service SHALL include the event title (max 255 characters) and optional body text in each message, with total message length limited to 4096 characters (Telegram message limit). IF the combined text exceeds 4096 characters, THEN THE system SHALL truncate the body and append "..." before the limit.
4. WHEN a message delivery fails with HTTP 403 (user blocked bot), THE Telegram_Service SHALL clear the user's `telegram_chat_id` and log the disconnection with user_id and event_type.
5. WHEN a message delivery fails with a transient error (HTTP 429 or 5xx), THE Telegram_Service SHALL retry up to 3 times with exponential backoff (2s, 4s, 8s). IF all retries fail, THEN the message SHALL be discarded and the failure logged.
6. THE Telegram_Service SHALL send messages asynchronously via a Celery task (`send_telegram_notification`) on the `fast` queue to avoid blocking the calling service.
7. IF a client-scoped event includes a `link` field, THEN THE Telegram_Service SHALL append a clickable URL to the RAMP platform page (e.g., `https://gorampit.com/clients/{id}/review`).
8. IF the user's `telegram_chat_id` is NULL at the time of delivery, THEN THE Telegram_Service SHALL skip delivery without error.

### Requirement 7: Platform-Level Event Notifications

**User Story:** As an owner or partner, I want to receive Telegram notifications for platform-wide events that are not tied to a specific client, so that I stay aware of system health and business signals.

#### Acceptance Criteria

1. THE system SHALL provide a `notify_platform_users(event_type, title, body, severity)` function that delivers a Telegram message to every user whose role and preferences match the given `event_type`, where the `body` parameter is truncated to 1000 characters and `severity` is one of `info`, `warning`, or `error`.
2. WHEN an infra alert is triggered by the external watchdog (container restart, disk full), THE system SHALL call `notify_platform_users` with event_type `infra_alert` and severity `error`.
3. WHEN AI LLM cost in the current 10-minute Redis window exceeds 80% of the circuit breaker threshold (i.e. exceeds $4.00) or the hourly cost exceeds 3× the 7-day hourly average, THE system SHALL call `notify_platform_users` with event_type `cost_spike` and severity `warning`.
4. WHEN a paying client has 0 posts for 7 consecutive days, THE system SHALL call `notify_platform_users` with event_type `pipeline_dead_7d` and severity `warning`.
5. WHEN a new trial client signs up, THE system SHALL call `notify_platform_users` with event_type `new_trial` and severity `info`.
6. WHEN a trial expires without conversion, THE system SHALL call `notify_platform_users` with event_type `trial_expired` and severity `info`.
7. IF the Telegram API returns a non-2xx response or times out after 10 seconds, THEN THE system SHALL log the failure with the event_type and recipient, and retry delivery up to 2 additional times with 30-second intervals before discarding the message.
8. THE system SHALL enforce a per-event-type cooldown of 5 minutes per recipient, suppressing duplicate notifications for the same event_type within that window.

### Requirement 8: Client-Scoped Event Notifications

**User Story:** As a client_admin or client_manager, I want to receive Telegram notifications for events related to my company, so that I stay informed about pipeline activity.

#### Acceptance Criteria

1. WHEN a `pipeline_complete`, `avatar_frozen`, or `draft_posted` event occurs for a client, THE system SHALL invoke the existing `notify_client()` function and additionally deliver a Telegram message to each user who has a non-null `telegram_chat_id` associated with that client and has the corresponding event type enabled in their notification preferences.
2. WHEN a pipeline completes for a client, THE system SHALL deliver a Telegram message with event type `pipeline_complete` to each eligible user of that client within 30 seconds of event occurrence.
3. WHEN an avatar is frozen for a client, THE system SHALL deliver a Telegram message with event type `avatar_frozen` to each eligible user of that client within 30 seconds of event occurrence.
4. WHEN a draft is posted for a client, THE system SHALL deliver a Telegram message with event type `draft_posted` to each eligible user of that client within 30 seconds of event occurrence.
5. THE system SHALL scope event recipients to users whose `client_id` matches the event's client, OR to users with platform-level roles (owner, partner, avatar_manager) who have the corresponding event type enabled in their notification preferences.
6. THE system SHALL NOT send duplicate Telegram messages to the same user for the same event, enforcing deduplication by the combination of event_type, user_id, and a 60-second sliding window.
7. IF Telegram message delivery fails for a user, THEN THE system SHALL log the failure with the user_id, event_type, and error reason, and SHALL NOT retry delivery for that specific event instance beyond the retries defined in Requirement 6.
8. THE system SHALL consider a user "eligible" for Telegram delivery only when the user has a non-null `telegram_chat_id` AND has the specific event type set to enabled in their notification preferences (explicit or role-based default).

### Requirement 9: Watchdog Integration

**User Story:** As a system operator, I want the existing watchdog Telegram alerts to coexist with per-user notifications using the same bot, so that infrastructure does not need duplication.

#### Acceptance Criteria

1. THE system SHALL use the same Telegram bot token for both watchdog alerts (sent to `TG_CHAT_ID` in watchdog.env) and per-user notifications (sent to individual `telegram_chat_id` values from the users table).
2. THE Webhook_Endpoint SHALL only process incoming messages (commands like /start, /stop, /status) and SHALL NOT intercept or modify the watchdog's outgoing `sendMessage` API calls, which are made directly by the bash watchdog script.
3. THE Telegram_Service SHALL NOT modify, restart, or replace the existing watchdog bash script (`/opt/ramp/ramp_watchdog.sh`) or its systemd timer configuration.
4. WHEN the `TELEGRAM_BOT_TOKEN` environment variable is not configured or is an empty string, THE Telegram_Service SHALL log a single WARNING-level message on first attempted delivery and skip all subsequent Telegram deliveries without raising exceptions or logging additional warnings.

### Requirement 10: Role-Based Bot Commands & Interactive Actions

**User Story:** As a user interacting with the RAMP Telegram bot, I want commands and interactive actions tailored to my role, so that I can monitor the system, get relevant information, and perform lightweight approvals without opening the web UI.

#### Acceptance Criteria

1. ALL connected users SHALL have access to the following base commands: `/stop` (disconnect), `/status` (show connection info + active preferences), `/help` (list available commands for current role), `/mute <minutes>` (suppress notifications for N minutes, default 60).
2. THE `/help` command SHALL only list commands available to the requesting user's role, with a one-line description for each.
3. WHEN a user sends a command they do not have role access to, THE bot SHALL respond with "⛔ This command is not available for your role. Use /help to see your commands."
4. ALL command responses SHALL be formatted with Telegram HTML parse mode and be under 4096 characters, truncating with "..." if data exceeds the limit.
5. WHEN a user with role `owner` sends `/health`, THE bot SHALL respond with: worker status (running/dead), Beat heartbeat age (seconds since last), Redis PING (ok/fail), PG status (ok/fail), disk usage %, last backup timestamp, app version.
6. WHEN a user with role `owner` sends `/costs`, THE bot SHALL respond with: today's total AI spend, hourly average, top-3 operations by cost, budget gate status (% of circuit breaker used), comparison vs yesterday.
7. WHEN a user with role `owner` sends `/errors`, THE bot SHALL respond with: error count last 1h vs 24h average, top-3 error types with count, any active alerts from alert_aggregation.
8. WHEN a user with role `owner` sends `/pipeline`, THE bot SHALL respond with: scraping status (last run, next due), scoring/generation pipeline last run time, pending queue depth, kill switch states.
9. WHEN a user with role `owner` sends `/clients`, THE bot SHALL respond with a list of active clients (name, plan_type, avatar count, last draft time), limited to 20 entries.
10. WHEN a user with role `owner` sends `/kill <switch_name>` (e.g., `/kill pipeline`), THE bot SHALL toggle the specified kill switch and respond with confirmation. Available switches: pipeline, generation, scrape, email_tasks.
11. WHEN a user with role `partner` sends `/clients`, THE bot SHALL respond with: client list (name, plan_type, health badge 🟢🟡🔴, days since last post), limited to 20 entries.
12. WHEN a user with role `partner` sends `/trials`, THE bot SHALL respond with: active trials (name, days remaining, onboarding step, trial score), limited to 10.
13. WHEN a user with role `partner` sends `/mrr`, THE bot SHALL respond with: current MRR, paying client count, change vs last month, next expiring trial.
14. WHEN a user with role `partner` sends `/attention`, THE bot SHALL respond with the top-5 attention items from `get_attention_items()` (same as partner dashboard).
15. WHEN a user with role `avatar_manager` sends `/avatars`, THE bot SHALL respond with: total active, frozen count, shadowbanned count, Phase 0/1/2/3 distribution, CQS distribution (lowest/low/medium/high).
16. WHEN a user with role `avatar_manager` sends `/frozen`, THE bot SHALL respond with a list of currently frozen avatars (name, freeze reason, frozen duration, last activity).
17. WHEN a user with role `avatar_manager` sends `/unfreeze <avatar_name>`, THE bot SHALL unfreeze the specified avatar and respond with confirmation including the new phase.
18. WHEN a user with role `qa` sends `/queue`, THE bot SHALL respond with: total pending drafts count, breakdown by client (top 5), oldest pending draft age.
19. WHEN a user with role `qa` sends `/review`, THE bot SHALL respond with the 3 oldest pending drafts (thread title, subreddit, avatar, preview of first 100 chars) with inline keyboard buttons [✅ Approve] [❌ Reject] per draft.
20. WHEN a user with role `client_admin` or `client_manager` sends `/drafts`, THE bot SHALL respond with: pending drafts count for their client, 3 most recent drafts (subreddit, avatar, first 80 chars of comment text), link to review page.
21. WHEN a user with role `client_admin` or `client_manager` sends `/schedule`, THE bot SHALL respond with: today's EPG slot count, approved/pending/posted breakdown, next scheduled slot time, link to EPG page.
22. WHEN a user with role `client_admin` or `client_manager` sends `/approve`, THE bot SHALL show the next pending draft with full text (up to 1000 chars) and inline keyboard buttons [✅ Approve] [✏️ Skip] [❌ Reject].
23. WHEN a notification about a new pending draft is sent to a `client_admin` or `client_manager`, THE notification message SHALL include inline keyboard buttons [✅ Approve] [❌ Reject] if `autopilot_enabled` is false for their client.
24. WHEN a user taps [✅ Approve] on an inline keyboard button, THE system SHALL approve the corresponding draft (same logic as web UI approval), update the message to show "✅ Approved by {user_name}", and emit a `draft_approved` activity event.
25. WHEN a user taps [❌ Reject] on an inline keyboard button, THE system SHALL reject the corresponding draft, update the message to show "❌ Rejected by {user_name}", and emit a `draft_rejected` activity event.
26. IF the draft has already been approved/rejected/posted by the time the button is tapped, THEN THE system SHALL update the message to show "⚠️ Already {status}" and take no further action.
27. THE system SHALL validate that the user tapping the button has the `can_review` permission for the draft's client before executing the action. IF not authorized, respond with "⛔ Not authorized" alert.
28. Inline keyboard callbacks SHALL be handled via Telegram `callback_query` updates at the same webhook endpoint, with callback data format: `approve:{draft_id}` or `reject:{draft_id}`.

### Requirement 11: Webhook Registration

**User Story:** As a system operator, I want an admin command or startup check that registers the webhook URL with Telegram, so that the bot receives updates.

#### Acceptance Criteria

1. THE system SHALL provide a CLI command (`python -m app.cli.register_telegram_webhook`) that calls the Telegram `setWebhook` API with the URL `https://gorampit.com/api/telegram/webhook` and the configured secret token.
2. WHEN the Telegram API responds with `ok: true`, THE CLI command SHALL print a success message including the webhook URL and exit with code 0.
3. THE system SHALL provide an admin endpoint `POST /admin/telegram/register-webhook` (owner-only) that triggers webhook registration and returns a JSON response containing the registration status and the webhook URL.
4. IF the Telegram bot token or webhook secret token is not configured in system settings at the time of registration, THEN THE system SHALL abort the operation and return an error message indicating which configuration value is missing.
5. IF the Telegram `setWebhook` API returns a non-success response or the request fails due to a network error, THEN THE system SHALL log the error details, return an error message indicating the failure reason to the operator, and the CLI command SHALL exit with a non-zero exit code.
6. THE CLI command SHALL also register the bot's command list with Telegram via `setMyCommands` API, setting different command menus per scope (all users: /start, /stop, /status, /help; additional commands are handled internally based on role).
