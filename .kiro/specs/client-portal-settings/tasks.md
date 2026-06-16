# Implementation Plan: Client Portal Settings

## Overview

Rebuild `/clients/{id}/settings` as minimal refinement screen per Tzvi's UX Brief v2. Single-column cards, no profile editing, request-based subreddits, keyword tooltips showing monitoring subreddits.

## Tasks

- [x] 1. Database schema changes
  - [x] 1.1 Add `brand_guardrails` JSONB column to Client model
    - Add `brand_guardrails: Mapped[dict | None] = mapped_column(JSONB, nullable=True)` to `app/models/client.py`
    - _Requirements: 4.6_
  - [x] 1.2 Create VoiceFeedback model
    - Create `app/models/voice_feedback.py` with fields: id (UUID PK), client_id (FK), user_id (FK), feedback_text (Text, max 500), created_at (DateTime)
    - Register in `app/models/__init__.py`
    - _Requirements: 5.2_
  - [x] 1.3 Create SubredditRequest model
    - Create `app/models/subreddit_request.py` with fields: id (UUID PK), client_id (FK), user_id (FK), subreddit_name (String 100), note (Text nullable), status (String: pending/approved/rejected), created_at, resolved_at
    - Register in `app/models/__init__.py`
    - _Requirements: 3.3, 3.5_
  - [x] 1.4 Create Alembic migration
    - Single migration: add `brand_guardrails` to clients, create `voice_feedback` table, create `subreddit_requests` table
    - _Requirements: 1.1, 4.6, 5.2, 3.3_

- [x] 2. Settings page layout and GET route
  - [x] 2.1 Rewrite `settings.html` template
    - Single-column card layout (no left sub-nav)
    - Sections: Keywords, Subreddits, Brand Guardrails, Voice Feedback
    - Deferred sections: Notifications, Team, Plan & Billing with lock icons and "Coming soon"
    - Conditional edit controls based on `can_edit` context variable
    - Dark theme consistent with `client_base.html`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_
  - [x] 2.2 Update `portal_settings` GET route
    - Load keywords from `client.keywords` JSONB
    - Build keyword-to-subreddit map (which subs monitor each keyword)
    - Load active subreddit assignments with names
    - Load `brand_guardrails` from client
    - Load last 5 VoiceFeedback entries
    - Load pending SubredditRequest count
    - Compute plan limit for subreddits
    - Pass `can_edit` based on user role
    - _Requirements: 1.4, 1.5, 2.1, 2.2, 3.1, 4.3, 5.4_

- [x] 3. Keywords section
  - [x] 3.1 Create `partials/client/settings_keywords.html`
    - Color-coded chips by priority (high=orange, medium=amber, low=gray)
    - Each chip has "x" remove button (if can_edit)
    - Hover tooltip on each chip showing "Monitored in: r/sub1, r/sub2"
    - Add form: text input + priority dropdown + Add button
    - Inline error area for duplicates
    - HTMX: target `#settings-keywords` on add/remove
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.8_
  - [x] 3.2 Implement `POST /clients/{id}/settings/keywords/add`
    - RBAC check (client_manager+)
    - Validate: non-empty, non-duplicate across all priorities
    - Add to keywords JSONB at correct priority
    - Return updated partial + toast trigger
    - _Requirements: 2.4, 2.5, 2.6, 2.7_
  - [x] 3.3 Implement `POST /clients/{id}/settings/keywords/remove`
    - RBAC check (client_manager+)
    - Remove from keywords JSONB
    - Return updated partial + toast trigger
    - _Requirements: 2.3, 2.5_

- [x] 4. Subreddits section (view + request)
  - [x] 4.1 Create `partials/client/settings_subreddits.html`
    - List of active subreddits (name, type, status) as read-only rows
    - "Request to add subreddit" button (if can_edit)
    - Request form (hidden by default, revealed on click): subreddit name + optional note + Submit
    - Plan limit check: if at limit, show amber upsell tooltip instead of form
    - Pending requests indicator (if any)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.6, 3.7_
  - [x] 4.2 Implement `POST /clients/{id}/settings/subreddits/request`
    - RBAC check (client_manager+)
    - Validate: non-empty subreddit name, strip "r/" prefix
    - Check plan limit (show upsell if exceeded)
    - Create SubredditRequest record (status=pending)
    - Return updated partial + toast: "Request sent"
    - _Requirements: 3.3, 3.4, 3.5_

- [x] 5. Brand Guardrails section
  - [x] 5.1 Create `partials/client/settings_guardrails.html`
    - "Never-associate topics" — tag chips + add input
    - "Restricted claims" — textarea
    - "Style inspiration" — textarea
    - "Save guardrails" button
    - Read-only mode for viewers
    - HTMX: target `#settings-guardrails`
    - _Requirements: 4.1, 4.3, 4.5_
  - [x] 5.2 Implement `POST /clients/{id}/settings/guardrails`
    - RBAC check (client_manager+)
    - Parse never_associate from comma/tag format into list
    - Build JSONB: {"never_associate": [...], "restricted_claims": "...", "style_inspiration": "..."}
    - Persist to client.brand_guardrails
    - Return partial + toast: "Guardrails updated"
    - _Requirements: 4.2, 4.4, 4.6_

- [x] 6. Voice Feedback section
  - [x] 6.1 Create `partials/client/settings_voice_feedback.html`
    - Label: "Our recent comments didn't feel right — here's what to change"
    - Textarea (500 char max) + live counter + orange Submit button
    - History: last 5 entries (text + date)
    - Read-only for viewers (history only)
    - HTMX: target `#settings-voice-feedback`
    - _Requirements: 5.1, 5.4, 5.6, 5.7_
  - [x] 6.2 Implement `POST /clients/{id}/settings/voice-feedback`
    - RBAC check (client_manager+)
    - Validate: non-empty after strip, max 500 chars
    - Create VoiceFeedback record
    - Query last 5 for history
    - Return partial (cleared form + updated history) + toast: "Got it"
    - _Requirements: 5.2, 5.3, 5.5_

- [x] 7. Final integration and testing
  - [x] 7.1 RBAC enforcement on all POST routes
    - Verify all return 403 for client_viewer
    - Verify `can_edit` controls template rendering
    - _Requirements: 1.4, 2.8, 3.7, 4.5, 5.7_
  - [x] 7.2 Verify complete page render
    - All 4 active sections render for client_manager
    - All 3 deferred sections show placeholders
    - Keyword tooltips display correct subreddit info
    - Test with real data from existing client

## Notes

- NO profile editing in Settings (belongs to onboarding flow)
- Subreddits: REQUEST only, NOT direct add/remove
- Keywords: show which subreddits monitor each keyword (tooltip on hover)
- Voice Feedback: log + toast only (not injected into AI prompt yet)
- Brand Guardrails: stored as prompt context (no enforcement/blocking yet)
- Design: single-column cards, NOT left sub-nav layout

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "1.4"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["3.1", "3.2", "3.3", "4.1", "4.2"] },
    { "id": 3, "tasks": ["5.1", "5.2", "6.1", "6.2"] },
    { "id": 4, "tasks": ["7.1", "7.2"] }
  ]
}
```
