# Requirements Document

## Introduction

A unified dashboard page that consolidates the EPG status and posting log across ALL avatars in the system into a single, at-a-glance view. Currently, EPG information is scattered across individual avatar workflow tabs, requiring operators to open 50+ tabs to understand the overall posting state. This page provides a centralized operations view with full audit trail visibility for the internal team (owner, partner, avatar_manager).

## Glossary

- **Dashboard**: The unified posting dashboard page at `/admin/posting-dashboard`
- **EPG_Panel**: The section of the Dashboard displaying EPGSlot records aggregated across all avatars
- **Posting_Log_Panel**: The section of the Dashboard displaying PostingEvent records across all avatars
- **EPG_Slot**: A planned publishing slot for an avatar on a specific date (model: `epg_slots`)
- **Posting_Event**: An audit record for every automated posting attempt (model: `posting_events`)
- **Platform_Admin**: A user with role owner, partner, or avatar_manager (the roles granted access to this page)
- **Status_Badge**: A color-coded visual indicator for EPG slot status (planned, generated, approved, posted, skipped)
- **Outcome_Badge**: A color-coded visual indicator for posting event outcome (success, failure, skipped)

## Requirements

### Requirement 1: Dashboard Page Access Control

**User Story:** As a platform administrator, I want the unified posting dashboard restricted to authorized roles, so that sensitive posting data is only visible to the internal operations team.

#### Acceptance Criteria

1. THE Dashboard SHALL be accessible at the route `/admin/posting-dashboard`
2. WHEN an unauthenticated user requests the Dashboard, THE Dashboard SHALL redirect to `/login`
3. WHEN a user with role owner requests the Dashboard, THE Dashboard SHALL render the page
4. WHEN a user with role partner requests the Dashboard, THE Dashboard SHALL render the page
5. WHEN a user with role avatar_manager requests the Dashboard, THE Dashboard SHALL render the page
6. WHEN a user with role client_admin, client_manager, client_viewer, qa, or b2c_user requests the Dashboard, THE Dashboard SHALL return HTTP 403

### Requirement 2: EPG Status Overview Panel

**User Story:** As a platform administrator, I want to see the EPG status for all avatars on a single page, so that I can understand the overall publishing program state at a glance.

#### Acceptance Criteria

1. THE EPG_Panel SHALL display EPG_Slot records for the selected date (defaulting to today in Asia/Jerusalem timezone)
2. THE EPG_Panel SHALL group EPG_Slot records by avatar, showing the avatar reddit_username as the group header
3. WHEN an EPG_Slot has status "planned", THE EPG_Panel SHALL display a gray Status_Badge
4. WHEN an EPG_Slot has status "generated", THE EPG_Panel SHALL display a blue Status_Badge
5. WHEN an EPG_Slot has status "approved", THE EPG_Panel SHALL display a yellow Status_Badge
6. WHEN an EPG_Slot has status "posted", THE EPG_Panel SHALL display a green Status_Badge
7. WHEN an EPG_Slot has status "skipped", THE EPG_Panel SHALL display a red Status_Badge
8. FOR EACH EPG_Slot row, THE EPG_Panel SHALL display: avatar username, slot_type, subreddit, thread_title (truncated to 60 characters), scheduled_at (formatted in Asia/Jerusalem timezone), and status
9. THE EPG_Panel SHALL display a summary bar showing counts per status (planned: N, generated: N, approved: N, posted: N, skipped: N)
10. WHEN the user selects a different date, THE EPG_Panel SHALL reload via HTMX to show EPG_Slot records for the selected date

### Requirement 3: EPG Status Filtering

**User Story:** As a platform administrator, I want to filter the EPG panel by status and avatar, so that I can focus on specific issues like unapproved slots or a specific avatar's schedule.

#### Acceptance Criteria

1. THE EPG_Panel SHALL provide a status filter with options: all, planned, generated, approved, posted, skipped
2. WHEN the user selects a status filter, THE EPG_Panel SHALL display only EPG_Slot records matching the selected status
3. THE EPG_Panel SHALL provide an avatar search input that filters by reddit_username substring match
4. WHEN the user types in the avatar search input, THE EPG_Panel SHALL filter results after a 300ms debounce using HTMX

### Requirement 4: Unified Posting Log Panel

**User Story:** As a platform administrator, I want to see a chronological log of all posting events across all avatars, so that I can monitor successes, failures, and investigate issues.

#### Acceptance Criteria

1. THE Posting_Log_Panel SHALL display Posting_Event records ordered by posted_at descending (most recent first)
2. FOR EACH Posting_Event row, THE Posting_Log_Panel SHALL display: avatar username, outcome, posted_at (formatted in Asia/Jerusalem timezone), duration_ms, subreddit (from linked EPG_Slot), and reddit_comment_url (as a clickable link opening in new tab)
3. WHEN a Posting_Event has outcome "success", THE Posting_Log_Panel SHALL display a green Outcome_Badge
4. WHEN a Posting_Event has outcome "failure", THE Posting_Log_Panel SHALL display a red Outcome_Badge with the error_message visible on hover or expandable
5. WHEN a Posting_Event has outcome "skipped", THE Posting_Log_Panel SHALL display a gray Outcome_Badge
6. THE Posting_Log_Panel SHALL display the 50 most recent events by default with a "Load More" button for pagination
7. WHEN the user clicks "Load More", THE Posting_Log_Panel SHALL append the next 50 events via HTMX without full page reload

### Requirement 5: Posting Log Filtering

**User Story:** As a platform administrator, I want to filter the posting log by outcome and avatar, so that I can quickly isolate failures or review a specific avatar's history.

#### Acceptance Criteria

1. THE Posting_Log_Panel SHALL provide an outcome filter with options: all, success, failure, skipped
2. WHEN the user selects an outcome filter, THE Posting_Log_Panel SHALL display only Posting_Event records matching the selected outcome
3. THE Posting_Log_Panel SHALL provide an avatar filter consistent with the EPG_Panel avatar filter
4. WHEN the user selects a date range filter, THE Posting_Log_Panel SHALL display only Posting_Event records within the specified date range

### Requirement 6: Approval Attribution

**User Story:** As a platform administrator, I want to see who approved each posted slot, so that I have a clear audit trail of human authorization.

#### Acceptance Criteria

1. WHEN an EPG_Slot has status "posted" or "approved", THE EPG_Panel SHALL display the approver username (from the linked CommentDraft.approved_by or audit trail)
2. WHEN an EPG_Slot has an associated CommentDraft with an approval timestamp, THE EPG_Panel SHALL display the approval time formatted in Asia/Jerusalem timezone
3. IF no approver information is available for a posted slot, THEN THE EPG_Panel SHALL display "—" in the approver column

### Requirement 7: Dashboard Summary Statistics

**User Story:** As a platform administrator, I want to see high-level statistics at the top of the page, so that I can assess the overall system health instantly.

#### Acceptance Criteria

1. THE Dashboard SHALL display a statistics header showing: total avatars with EPG today, total slots today, posts completed today, failures today, and overall success rate percentage for today
2. WHEN the statistics are computed, THE Dashboard SHALL use the Asia/Jerusalem timezone to define "today"
3. THE Dashboard SHALL auto-refresh statistics every 60 seconds via HTMX polling

### Requirement 8: Performance and Scalability

**User Story:** As a platform administrator, I want the dashboard to load within acceptable time even with 100+ avatars and thousands of posting events, so that the page remains usable as the system scales.

#### Acceptance Criteria

1. THE Dashboard SHALL render the initial page load (EPG for today + last 50 posting events) within 2 seconds for up to 100 avatars
2. THE Dashboard SHALL use database indexes on epg_slots(plan_date, status) and posting_events(posted_at) for query performance
3. WHEN loading the posting log, THE Dashboard SHALL use cursor-based pagination to avoid performance degradation on deep pages
4. THE Dashboard SHALL load EPG_Panel and Posting_Log_Panel content asynchronously via HTMX (lazy load after page shell renders)

### Requirement 9: Navigation Integration

**User Story:** As a platform administrator, I want to access the unified posting dashboard from the admin sidebar, so that it is discoverable and easily reachable.

#### Acceptance Criteria

1. THE Dashboard SHALL appear as a navigation item in the admin sidebar under the "Operations" section
2. THE Dashboard navigation item SHALL be visible only to users with role owner, partner, or avatar_manager
3. WHEN the user is on the Dashboard page, THE sidebar navigation item SHALL be highlighted as active
