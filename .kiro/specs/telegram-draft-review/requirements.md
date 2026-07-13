# Requirements Document

## Introduction

Add Telegram as an additional delivery and review channel for draft management in the RAMP platform. The Telegram Bot provides an inline keyboard interface for users to approve, edit, or skip pending comment and post drafts — working alongside the existing Extension, Email, and Portal channels. Telegram does NOT post to Reddit itself; it only manages review decisions. Execution remains with the Browser Extension on the executor's machine.

**Key architectural decisions:**
- **Single bot** — one Telegram bot serves both ops alerts (existing) and draft review (new). The bot determines what to show based on the User's role and client assignments.
- **User-level linking** — `telegram_chat_id` lives on the User model (already exists). A single chat_id can serve multiple roles (owner sees ops + review, client_admin sees review only).
- **Edit = LLM regeneration** — when a client edits a draft via Telegram, the edited text is sent to the LLM as guidance for regeneration (not a direct body replacement).
- **Callback ID mapping** — Telegram's 64-byte `callback_data` limit is handled via short Redis-mapped IDs (callback_id → draft_id + action).
- **Approve-all = per avatar** — bulk approve operates on a single avatar's pending drafts (matches existing extension endpoint).
- **Scope = role-based** — users see drafts they have access to based on their RBAC role (owner/partner = all clients, client_admin/client_manager = their client's drafts).

## Glossary

- **Telegram_Bot**: The single RAMP Telegram bot that serves both ops alerts and client draft review, routing by User role
- **User**: A RAMP platform user with a role (owner/partner/client_admin/client_manager/etc.) who links their Telegram account
- **Client**: A RAMP platform client (business entity) whose drafts are managed
- **Draft_Notification**: A Telegram message containing draft details and action buttons sent to a linked user
- **Inline_Keyboard**: Telegram's interactive button interface attached to messages (Approve / Skip / Edit)
- **Verification_Code**: A 6-character alphanumeric code used to link a Telegram chat_id to a user account (already exists in current system)
- **Backend_API**: The existing RAMP FastAPI backend that processes draft review decisions
- **Chat_ID**: Telegram's unique identifier for a user's conversation with the bot (stored on User model)
- **Callback_ID**: A short Redis-mapped identifier (≤20 chars) that resolves to draft_id + action + HMAC for Telegram callback_data
- **Autopilot_Mode**: Client or avatar setting where drafts are auto-approved without manual review
- **Draft_Card**: A formatted Telegram message displaying draft metadata (thread title, subreddit, avatar name, truncated text) with action buttons
- **LLM_Regeneration**: Using client's edited text as guidance input to regenerate the draft via the generation LLM (not direct body replacement)

## Requirements

### Requirement 1: Telegram Account Linking (Existing Infrastructure)

**User Story:** As a user (any role), I want to link my Telegram account to RAMP, so that I can receive notifications appropriate to my role — including draft review notifications.

#### Acceptance Criteria

1. GIVEN that `telegram_chat_id` already exists on the User model with linking/unlinking via admin panel, WHEN a client_admin or client_manager user links their Telegram via the same mechanism, THE Backend_API SHALL recognize them as eligible for draft review notifications based on their role and client assignment
2. WHEN a user with role client_admin or client_manager has a linked Telegram account, THE Telegram_Bot SHALL include draft review capabilities (commands and notifications) for drafts belonging to their assigned client
3. WHEN a user with role owner or partner has a linked Telegram account, THE Telegram_Bot SHALL include draft review capabilities for ALL clients they have access to, in addition to existing ops alerts
4. WHEN a user sends `/start` to the bot, THE Telegram_Bot SHALL respond with role-appropriate welcome message: ops + review for owner/partner, review-only for client_admin/client_manager
5. WHEN a user unlinks Telegram (sets `telegram_chat_id` to null), THE Backend_API SHALL stop all notifications (both ops and review) for that user
6. THE Backend_API SHALL determine draft review eligibility by: (a) user has `telegram_chat_id` set, (b) user has role in (owner, partner, client_admin, client_manager), (c) user's assigned client has `autopilot_enabled=false`

### Requirement 2: Draft Notification Delivery

**User Story:** As a user with review access, I want to receive pending draft notifications via Telegram when drafts are generated, so that I can review them without opening the portal.

#### Acceptance Criteria

1. WHEN EPG generates drafts for a client with Autopilot_Mode disabled, THE Backend_API SHALL identify all users with `telegram_chat_id` set who have review access to that client (owner/partner = all, client_admin/client_manager = assigned client) and trigger Telegram notification delivery for each pending draft within 60 seconds of draft creation
2. THE Telegram_Bot SHALL format each Draft_Card with: thread title (linked to Reddit URL, maximum 80 characters with ellipsis if truncated), subreddit name prefixed with r/, avatar display name, comment or post text (truncated to 300 characters with ellipsis if longer), and an Inline_Keyboard with Approve, Skip, and Edit buttons
3. WHEN a user has more than 5 pending drafts in a single EPG build, THE Telegram_Bot SHALL send a summary message with total draft count and an "Approve All (avatar_name)" button per avatar, followed by individual Draft_Cards for each draft
4. WHILE Autopilot_Mode is enabled for the client, THE Telegram_Bot SHALL NOT send draft notifications for that client's drafts
5. IF the Telegram API returns an error during delivery (user blocked bot or chat not found), THEN THE Backend_API SHALL log the delivery failure with error category and timestamp, and set `telegram_chat_id` to null after 3 consecutive failures within a 24-hour window
6. THE Telegram_Bot SHALL respect Telegram API rate limits by spacing messages with a minimum 50ms delay between consecutive sends to the same chat and a maximum of 30 messages per second globally across all chats
7. IF a draft is approved or skipped via the portal or extension before the Telegram notification is delivered, THEN THE Backend_API SHALL skip sending the notification for that draft
8. WHEN the same user has access to multiple clients (owner/partner), draft notifications SHALL include the client name in the Draft_Card header for disambiguation

### Requirement 3: Single Draft Approval via Telegram

**User Story:** As a user with review access, I want to approve individual drafts by pressing the Approve button in Telegram, so that approved drafts proceed to execution.

#### Acceptance Criteria

1. WHEN the user presses the "✅ Approve" button on a Draft_Card, THE Telegram_Bot SHALL resolve the Callback_ID from Redis and call the Backend_API draft review endpoint to approve that draft within 5 seconds of the button press
2. WHEN the Backend_API confirms approval, THE Telegram_Bot SHALL update the Draft_Card message to show "✅ Approved" status and remove the action buttons within 3 seconds of receiving the confirmation
3. IF the draft has already been approved or rejected by another channel (portal, extension, or another user via Telegram), THEN THE Telegram_Bot SHALL update the Draft_Card message to show the current status text and display an inline notice indicating the draft was already reviewed
4. IF the Backend_API returns an error or is unreachable when the user presses "✅ Approve", THEN THE Telegram_Bot SHALL display an inline error message indicating the approval could not be processed and retain the action buttons for retry
5. WHEN a draft is approved via Telegram, THE Backend_API SHALL transition the draft status from "pending" to "approved" and the associated EPG slot status to "approved" using the same logic as the extension review endpoint

### Requirement 4: Single Draft Skip via Telegram

**User Story:** As a user with review access, I want to skip individual drafts by pressing the Skip button in Telegram, so that unwanted drafts are rejected.

#### Acceptance Criteria

1. WHEN the user presses the "❌ Skip" button on a Draft_Card that has status "pending", THE Telegram_Bot SHALL resolve the Callback_ID from Redis and call the Backend_API draft review endpoint to reject that draft
2. IF the Backend_API returns a successful rejection response, THEN THE Telegram_Bot SHALL update the message to show "❌ Skipped" status and remove the action buttons
3. IF the Backend_API returns an error when processing the skip request, THEN THE Telegram_Bot SHALL display an error message indicating the skip failed and retain the action buttons for retry
4. WHEN a draft is skipped via Telegram, THE Backend_API SHALL transition the draft status to "rejected" and the EPG slot status to "skipped"
5. IF the user presses the "❌ Skip" button on a draft that is no longer in "pending" status, THEN THE Telegram_Bot SHALL display a message indicating the draft has already been processed and remove the action buttons

### Requirement 5: Draft Edit Flow via Telegram (LLM Regeneration)

**User Story:** As a user with review access, I want to provide edit guidance through Telegram and have the AI regenerate the draft, so that I can refine comment content without opening the portal.

#### Acceptance Criteria

1. WHEN the user presses the "✏️ Edit" button on a Draft_Card, THE Telegram_Bot SHALL reply with the full draft text in a new message and a prompt: "Send your corrections or guidance as a reply — the AI will regenerate the draft based on your input"
2. WHEN the user sends a text message as a direct reply to the edit prompt message, THE Telegram_Bot SHALL call the Backend_API to regenerate the draft using the user's text as guidance input to the LLM (same model as comment generation, with user's text as editing instruction)
3. WHEN the Backend_API confirms regeneration, THE Telegram_Bot SHALL send the updated Draft_Card with the new regenerated text and Approve / Skip / Edit buttons (allowing iterative refinement)
4. IF the user sends a message that is not a reply to an active edit prompt, THEN THE Telegram_Bot SHALL ignore it for edit purposes
5. WHEN the user approves the regenerated draft, THE Backend_API SHALL record both the original text and the user's guidance in the learning service for correction pattern extraction
6. IF the edit prompt has been inactive for more than 30 minutes without a reply, THEN THE Telegram_Bot SHALL consider the edit session expired and subsequent replies SHALL be ignored
7. IF the LLM regeneration fails (timeout, error), THEN THE Telegram_Bot SHALL notify the user of the failure and retain the original draft text with Approve / Skip / Edit buttons

### Requirement 6: Bulk Approve All Drafts (Per Avatar)

**User Story:** As a user with review access, I want to approve all pending drafts for a specific avatar at once via Telegram, so that I can quickly clear my review queue.

#### Acceptance Criteria

1. WHEN the user presses the "✅ Approve All (avatar_name)" button or sends the `/approve_all avatar_username` command, THE Telegram_Bot SHALL call the Backend_API bulk approve endpoint for all pending drafts belonging to that specific avatar
2. IF the avatar has zero pending drafts when bulk approval is triggered, THEN THE Telegram_Bot SHALL respond with a message indicating that no pending drafts were found for that avatar
3. WHEN the Backend_API confirms bulk approval, THE Telegram_Bot SHALL send a confirmation message stating the count of approved drafts and the avatar name within 5 seconds of receiving the backend response
4. WHEN bulk approval is triggered, THE Backend_API SHALL use the same `/api/extension/drafts/approve-all?avatar_username=X` endpoint logic to approve all pending drafts for that avatar, transitioning each draft from "pending" to "approved" status and its associated EPG slot from "generated" to "approved"
5. IF some drafts fail to approve during bulk operation, THEN THE Telegram_Bot SHALL report both the count of successful approvals and the count of failures in a single response message
6. IF the Backend_API is unreachable or returns an error during bulk approval, THEN THE Telegram_Bot SHALL send an error message indicating the approval could not be completed and that pending drafts remain unchanged
7. THE Backend_API SHALL verify that the user has review access to the avatar's client before processing bulk approval (P7 isolation)

### Requirement 7: Telegram Draft Review as Additive Channel

**User Story:** As a platform operator, I want Telegram draft review to work as an additional channel alongside existing ones, so that users can choose their preferred review method.

#### Acceptance Criteria

1. THE Backend_API SHALL treat Telegram draft notifications as additive — sending to Telegram does NOT disable portal bell notifications or extension badge counts
2. WHEN a user has `telegram_chat_id` set AND `telegram_notifications_level` is "all" or "warning", THE Backend_API SHALL send draft review notifications via Telegram for all clients the user has review access to
3. WHEN a user has `telegram_notifications_level` set to "critical" or "off", THE Backend_API SHALL NOT send draft review notifications via Telegram for that user (review notifications are non-critical)
4. THE Backend_API SHALL store no additional Telegram-specific fields on the Client model — all Telegram config remains on User model (existing `telegram_chat_id`, `telegram_notifications_level`)
5. WHEN an admin changes a user's `telegram_notifications_level` via the admin panel, THE change SHALL take effect immediately for the next draft generation cycle without delay

### Requirement 8: Bot Command Interface

**User Story:** As a user, I want to use Telegram bot commands to check my pending drafts and get help, so that I can interact with the system without buttons.

#### Acceptance Criteria

1. WHEN the user sends `/pending` command, THE Telegram_Bot SHALL respond with the count of pending drafts across all clients the user has access to, grouped by avatar, and a list of up to 5 most recent Draft_Cards ordered by creation date descending
2. IF the user sends `/pending` command and has zero pending drafts across all accessible clients, THEN THE Telegram_Bot SHALL respond with a message indicating no pending drafts exist
3. WHEN the user sends `/help` command, THE Telegram_Bot SHALL respond with a list of all available commands appropriate to the user's role, each accompanied by a one-line description of its function
4. WHEN the user sends `/status` command, THE Telegram_Bot SHALL respond with the linked account name, role, accessible client names, notification level, and total count of pending drafts
5. IF an unlinked user (no matching `telegram_chat_id` in DB) sends any command, THEN THE Telegram_Bot SHALL respond with instructions to link their account via the admin/portal panel
6. IF a linked user sends a command not recognized by the bot, THEN THE Telegram_Bot SHALL respond with a message indicating the command is unrecognized and suggest using `/help` to see available commands
7. WHEN a user with access to multiple clients sends `/pending`, THE Telegram_Bot SHALL group drafts by client name → avatar name for clarity

### Requirement 9: Security and Authorization

**User Story:** As a platform operator, I want Telegram interactions to be securely authenticated, so that only authorized users can review drafts they have access to.

#### Acceptance Criteria

1. IF a callback contains a Chat_ID that is not stored in any user's `telegram_chat_id` field or belongs to a user with `is_active=false`, THEN THE Backend_API SHALL reject the review action and return an error indication to the Telegram_Bot within 3 seconds
2. THE Telegram_Bot SHALL use Callback_ID mapping (short Redis key → draft_id + action + user_id) in callback_data to stay within Telegram's 64-byte limit while maintaining integrity
3. THE Backend_API SHALL validate that the Callback_ID resolves to a valid mapping in Redis before processing any action; expired or missing mappings SHALL result in a "session expired, use /pending to refresh" message
4. THE Backend_API SHALL verify that the user associated with the requesting Chat_ID has review access to the draft's client before processing any approve, reject, or edit action, enforcing P7 isolation by: owner/partner = access to all, client_admin/client_manager = access only to their assigned client's drafts
5. WHEN a user account is set to `is_active=false`, THE Backend_API SHALL reject all subsequent Telegram callbacks for that user's Chat_ID without processing the requested review action
6. Callback_ID Redis mappings SHALL expire after 24 hours to prevent stale callback accumulation

### Requirement 10: Interaction with Autopilot and Existing Flows

**User Story:** As a platform operator, I want Telegram to coexist with existing review mechanisms without conflicts, so that the system remains consistent.

#### Acceptance Criteria

1. WHILE Autopilot_Mode is enabled for a client (client.autopilot_enabled=true OR avatar.auto_approve_drafts=true), THE Backend_API SHALL NOT send Telegram draft-pending notifications for that client/avatar's drafts, because drafts are auto-approved and require no human review action
2. WHEN a draft is approved via any channel (portal, extension, Telegram), THE Backend_API SHALL mark the draft as approved exactly once (subsequent approval requests for the same draft SHALL return a success response with no state change) and THE Telegram_Bot SHALL update the Draft_Card message inline to reflect the new status
3. WHEN a new EPG build generates drafts and users with Telegram linked have review access to that client and autopilot is disabled, THE Backend_API SHALL trigger Telegram delivery as part of the post-generation notification flow alongside portal bell and extension badge within 60 seconds of draft creation
4. THE Backend_API SHALL use the same backend endpoints as the Extension for draft review operations (`/api/extension/drafts/{id}/review` and `/api/extension/drafts/approve-all`)
5. IF a draft approval or rejection request arrives via Telegram for a draft that is no longer in pending status, THEN THE Backend_API SHALL return a success response indicating the current status of the draft without modifying its state, and THE Telegram_Bot SHALL update the message to show current status

### Requirement 11: Webhook Integration

**User Story:** As a platform operator, I want the Telegram bot to receive updates via webhook on our existing HTTPS domain, so that responses are instant and no long-polling process is needed.

#### Acceptance Criteria

1. THE Backend_API SHALL expose a webhook endpoint at `POST /api/telegram/webhook` that receives Telegram Update objects and routes them to the appropriate handler (command, callback_query, or message reply)
2. THE webhook endpoint SHALL validate the incoming request using Telegram's secret_token mechanism to reject forged requests
3. THE Backend_API SHALL register the webhook URL (`https://gorampit.com/api/telegram/webhook`) with Telegram on application startup if not already registered
4. THE webhook endpoint SHALL respond with HTTP 200 within 5 seconds for every valid request (async processing for heavy operations like LLM regeneration)
5. IF webhook registration fails on startup, THE Backend_API SHALL log an error and retry registration every 60 seconds until successful, without blocking application startup
6. THE nginx configuration SHALL include `location = /api/telegram/webhook` proxying to the app service
