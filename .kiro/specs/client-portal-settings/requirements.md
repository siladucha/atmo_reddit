# Requirements Document

## Introduction

Rebuild the client portal settings page (`/clients/{id}/settings`) as a minimal, rarely-visited refinement screen — per Tzvi's UX Brief v2. All major configuration happens during onboarding; Settings is for ongoing tweaks only.

The page uses a simple single-column card layout with clearly separated sections. No profile editing (that belongs to onboarding). Focus: keywords, subreddits (request-based), brand guardrails, voice feedback, and placeholder sections for future features.

**Design principle (from Tzvi):** "The client should never feel like they are operating a tool. They should feel like they are reviewing and approving the work of a highly capable team."

## Glossary

- **Settings_Page**: The client portal page at `/clients/{id}/settings` for ongoing campaign refinement.
- **Keywords_Section**: Displays keywords with priority + hover tooltip showing which subreddits monitor each keyword. Add/remove inline.
- **Subreddits_Section**: View-only list of active subreddits. "Request to add" button (not free-add). Triggers upsell if at plan limit.
- **Guardrails_Section**: Edit brand guardrails (never-associate topics, restricted claims, style inspiration).
- **Voice_Feedback_Section**: Free-text feedback captured as training signal for the AI generation model.
- **VoiceFeedback**: New database model storing timestamped voice feedback entries.
- **Client_Manager_Role**: Users with `client_manager` or higher — can edit keywords, guardrails, submit feedback.
- **Client_Viewer_Role**: Users with `client_viewer` — read-only view of all settings.
- **Plan_Limit**: Maximum subreddits allowed by the client's subscription tier.
- **HTMX_Partial**: Server-rendered HTML fragment for inline DOM updates without full page reload.

## Requirements

### Requirement 1: Settings Page Layout

**User Story:** As a client portal user, I want a clean settings page with clearly separated sections, so that I can quickly find and adjust campaign configuration.

#### Acceptance Criteria

1. WHEN a user navigates to `/clients/{id}/settings`, THE Settings_Page SHALL display sections in this order: Keywords, Subreddits, Brand Guardrails, Voice Feedback, Notifications (coming soon), Team (coming soon), Plan & Billing (coming soon).
2. THE Settings_Page SHALL use a single-column card layout with section headers, consistent with the portal dark theme (`client_base.html`).
3. Deferred sections (Notifications, Team, Plan & Billing) SHALL display a "Coming soon" placeholder card with a lock icon.
4. WHILE a user has the `client_viewer` role, THE Settings_Page SHALL hide all add/remove/edit controls and display content as read-only.
5. WHILE a user has the `client_manager` role or higher, THE Settings_Page SHALL display full edit controls.

### Requirement 2: Keywords Management

**User Story:** As a client manager, I want to manage keywords and see which subreddits monitor each keyword, so that I can control what topics the system tracks.

#### Acceptance Criteria

1. THE Keywords_Section SHALL display active keywords as color-coded chips grouped by priority: high (orange), medium (amber), low (gray).
2. WHEN a user hovers over a keyword chip, THE Keywords_Section SHALL display a tooltip showing which subreddits that keyword is being monitored in.
3. WHEN a user with edit permission clicks the "x" button on a keyword chip, THE Keywords_Section SHALL remove that keyword from the client's keywords JSONB and return an updated view via HTMX partial.
4. WHEN a user with edit permission submits the "Add keyword" input with a priority selection, THE Keywords_Section SHALL add the keyword to the appropriate priority list.
5. WHEN a keyword is added or removed, THE Settings_Page SHALL display a confirmation toast: "Keyword added — your avatars will now monitor this topic" or "Keyword removed."
6. IF a user attempts to add a keyword that already exists in any priority level, THE Keywords_Section SHALL reject it with an inline error.
7. IF a user attempts to add an empty or whitespace-only keyword, THE Keywords_Section SHALL reject it silently.
8. WHILE the user has the `client_viewer` role, THE Keywords_Section SHALL display chips without "x" buttons or add input.

### Requirement 3: Subreddits View and Request

**User Story:** As a client manager, I want to view my active subreddits and request new ones through my account manager, so that I can expand coverage without direct system access.

#### Acceptance Criteria

1. THE Subreddits_Section SHALL display a list of active subreddit assignments showing: subreddit name (as r/name), assignment type (professional/hobby), and current status.
2. THE Subreddits_Section SHALL display a "Request to add subreddit" button.
3. WHEN a user clicks "Request to add subreddit" and the client has NOT reached the Plan_Limit, THE Subreddits_Section SHALL display a form with subreddit name input and optional note, then store the request for the account manager to process.
4. WHEN a user clicks "Request to add subreddit" and the client HAS reached the Plan_Limit, THE Subreddits_Section SHALL display an inline amber upsell tooltip: "You've reached your subreddit limit. Contact your account manager to add more slots."
5. WHEN a subreddit request is submitted, THE Settings_Page SHALL display a toast: "Request sent — your account manager will review and add this subreddit."
6. THE Subreddits_Section SHALL NOT allow direct add or remove of subreddits — only requests.
7. WHILE the user has the `client_viewer` role, THE Subreddits_Section SHALL display the list without the "Request to add" button.

### Requirement 4: Brand Guardrails

**User Story:** As a client manager, I want to update brand guardrails, so that the AI avoids topics, claims, and language that don't align with my brand.

#### Acceptance Criteria

1. THE Guardrails_Section SHALL display three editable fields: "Never-associate topics" (tag input), "Restricted claims" (textarea), and "Style inspiration" (textarea).
2. WHEN a user with edit permission saves guardrails (via Save button), THE Settings_Page SHALL persist the updated values and display a toast: "Guardrails updated — we'll apply these to all future drafts."
3. THE Guardrails_Section SHALL pre-populate fields with existing client data (from onboarding or previous edits).
4. IF the backend fails to persist, THE Guardrails_Section SHALL display an error toast.
5. WHILE the user has the `client_viewer` role, THE Guardrails_Section SHALL display all fields as read-only text.
6. THE Guardrails_Section SHALL store data in a JSONB field `brand_guardrails` on the Client model: `{"never_associate": [...], "restricted_claims": "...", "style_inspiration": "..."}`.

### Requirement 5: Voice Feedback

**User Story:** As a client manager, I want to submit voice/tone feedback when recent comments didn't feel right, so that the AI adjusts its writing style.

#### Acceptance Criteria

1. THE Voice_Feedback_Section SHALL display a label: "Our recent comments didn't feel right — here's what to change" with a textarea (500 char max) and orange "Submit feedback" button.
2. WHEN a user submits feedback, THE Voice_Feedback_Section SHALL create a VoiceFeedback record (client_id, user_id, text, created_at) and display a toast: "Got it — we'll apply this to future generations."
3. WHEN feedback is submitted, THE Voice_Feedback_Section SHALL clear the textarea and prepend the new entry to the history list.
4. THE Voice_Feedback_Section SHALL display a history of the last 5 feedback entries (reverse chronological) with text and submission date.
5. IF a user submits empty/whitespace-only feedback, THE Voice_Feedback_Section SHALL reject silently.
6. THE Voice_Feedback_Section SHALL show a live character counter ("128 / 500").
7. WHILE the user has the `client_viewer` role, THE Voice_Feedback_Section SHALL show history only without the submission form.

### Requirement 6: Notifications (Deferred)

**User Story:** As a client manager, I want to configure notification preferences.

#### Acceptance Criteria

1. Email digest frequency: Radio group (Daily / Weekly / Off), default Weekly.
2. Slack webhook: text input + "Test" button. Growth+ plans only (greyed with upsell tooltip on lower tiers).
3. Shadowban alerts: always on, greyed checkbox + lock icon.

### Requirement 7: Team Management (Deferred)

**User Story:** As a client admin, I want to invite read-only viewers to the workspace.

#### Acceptance Criteria

1. "Invite teammate" — email input + "Send invite" button (creates client_viewer user).
2. Active team list: name, email, "Remove" link.

### Requirement 8: Plan and Billing (Deferred)

**User Story:** As a client user, I want to see my current plan, usage against limits, and upgrade options.

#### Acceptance Criteria

1. Current plan card: tier name, usage meters (monthly actions, active avatars, active subreddits).
2. Progress bars: amber at 80%, red at 95%.
3. Contextual upgrade CTA: "You are at 80% of your monthly action limit. Upgrade to Growth for 2.5x more actions." Never generic.
