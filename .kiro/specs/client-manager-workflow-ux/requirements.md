# Requirements Document

## Introduction

This feature improves the daily client/manager workflow UX in the Reddit Marketing SaaS admin panel. The current admin panel has 15+ sidebar items at one level with no prioritization, no actionable badges, a basic Client Hub lacking operational depth, and a review flow that doesn't support batch operations or aging alerts. This feature addresses six core problems: overloaded navigation, missing badges/counters, lack of a client-centric operational view, suboptimal review flow, no "what to do now" prioritization, and audit log coverage gaps. The goal is to make the daily operator workflow faster, more intuitive, and client-centric.

## Glossary

- **Admin_Panel**: The dark-themed admin interface at `/admin/*` using `admin_base.html`, accessible to superusers.
- **Sidebar_Navigation**: The fixed left sidebar in `admin_base.html` containing grouped navigation links (Operations, Content, Monitoring, Settings).
- **Navigation_Badge**: A small numeric indicator displayed next to a sidebar link showing the count of actionable items (e.g., pending reviews, stale drafts).
- **Client_Hub**: An enhanced unified page at `/admin/clients/{id}` providing all operational data for a single client: overview, subreddits, avatars, threads, review queue, activity log, and reports.
- **Review_Queue**: The page at `/admin/review` where operators approve, reject, or edit comment/post drafts before manual posting.
- **Batch_Operation**: The ability to select multiple drafts in the Review_Queue and apply a single action (approve, reject) to all selected items at once.
- **Aging_Alert**: A visual indicator on a draft that has been in "pending" status longer than a configurable threshold (default: 24 hours).
- **Priority_Banner**: A top-of-page section on the Operations_Dashboard showing urgent actionable items ranked by importance.
- **Action_Log_Widget**: An inline HTMX partial on the Client_Hub showing the most recent audit log entries filtered to that client.
- **Operator**: A superuser who performs daily operations (review, pipeline triggers, monitoring).
- **Client_Manager**: A future role that manages specific assigned clients (currently all operators are superusers).

## Requirements

### Requirement 1: Sidebar Navigation Restructuring

**User Story:** As an operator, I want the sidebar navigation grouped by workflow frequency (daily work vs. setup vs. monitoring), so that I can find my most-used pages instantly without scanning 15+ items.

#### Acceptance Criteria

1. THE Sidebar_Navigation SHALL organize links into four groups: "Daily Work" (Dashboard, Review Queue, Activity), "Clients & Content" (Clients, Avatars, Subreddits, Threads, Keywords), "Monitoring" (System Health, Inspector, AI Costs, Audit Logs, Tasks, Scrape Queue), and "Settings" (System Settings, Billing, Users).
2. THE Sidebar_Navigation SHALL display groups in fixed top-to-bottom order: "Daily Work", "Clients & Content", "Monitoring", "Settings", with all groups always expanded (no collapse/expand behavior).
3. THE Sidebar_Navigation SHALL visually distinguish the "Daily Work" group label from other group labels by rendering it in a brighter text color (e.g., text-gray-300 vs. text-gray-500 for other groups) or by adding a 2px left-border accent in indigo-500 to the group section.
4. WHEN the operator is on any page listed in the sidebar, THE Sidebar_Navigation SHALL highlight the active link with the existing indigo-600 background style, regardless of which group the link belongs to.

### Requirement 2: Navigation Badges for Actionable Items

**User Story:** As an operator, I want to see badge counters on sidebar links showing pending items, so that I know what needs attention without navigating to each page.

#### Acceptance Criteria

1. THE Sidebar_Navigation SHALL display a Navigation_Badge next to "Review Queue" showing the combined count of CommentDraft and PostDraft records with status "pending".
2. THE Sidebar_Navigation SHALL display a Navigation_Badge next to "Scrape Queue" showing the count of active subreddits whose `last_scraped_at` is older than the configured `scrape_freshness_window_hours` system setting or is NULL.
3. WHEN a Navigation_Badge count is zero, THE Sidebar_Navigation SHALL hide the badge element entirely rather than displaying "0".
4. WHEN the pending review count exceeds 10, THE Navigation_Badge next to "Review Queue" SHALL display with a red background and white text. WHEN the pending review count is between 1 and 10 inclusive, THE Navigation_Badge SHALL display with an amber background and white text.
5. WHEN the stale subreddit count exceeds 5, THE Navigation_Badge next to "Scrape Queue" SHALL display with a red background and white text. WHEN the stale subreddit count is between 1 and 5 inclusive, THE Navigation_Badge SHALL display with an amber background and white text.
6. THE Navigation_Badge SHALL use a rounded pill shape with a minimum width of 20px and a font size no smaller than 12px to ensure readability.
7. THE Sidebar_Navigation SHALL refresh Navigation_Badge counts via an HTMX partial endpoint polled every 60 seconds using hx-trigger="every 60s".
8. IF the badge count endpoint returns an error or times out (within 5 seconds), THEN THE Sidebar_Navigation SHALL retain the previously displayed badge values until the next successful poll.

### Requirement 3: Enhanced Client Hub with Operational Depth

**User Story:** As an operator, I want a unified Client Hub page where I can see everything about a client (subreddits, avatars, review queue, activity, pipeline status) without jumping between 5 different pages.

#### Acceptance Criteria

1. THE Client_Hub SHALL be accessible at `/admin/clients/{id}` and SHALL use a tabbed interface with tabs: Overview, Subreddits, Avatars, Review, Activity, and Reports, with the Overview tab selected by default on page load.
2. THE Client_Hub Overview tab SHALL display: client name, brand name, company profile summary (first 200 characters), active/inactive status badge, total subreddits count, total avatars count, pending reviews count (CommentDraft + PostDraft with status "pending"), threads scraped in the last 24 hours, comments generated in the last 24 hours, and pipeline control buttons (Scrape, Score, Generate, Full Pipeline).
3. WHEN an operator clicks a pipeline control button on the Overview tab, THE Client_Hub SHALL dispatch the corresponding pipeline task for the current client and SHALL display a confirmation indicator within 2 seconds confirming the task was queued.
4. THE Client_Hub Subreddits tab SHALL list all subreddits assigned to the client showing: subreddit name, last_scraped_at timestamp, a freshness color indicator (green if scraped within 12 hours, amber if 12–24 hours ago, red if more than 24 hours ago or never scraped), and a "Scrape Now" button per subreddit.
5. THE Client_Hub Avatars tab SHALL list all avatars assigned to the client with their warming_phase (0–3), health_status, confidence score (0–100), and a link to the avatar detail page at `/admin/avatars/{avatar_id}`.
6. THE Client_Hub Review tab SHALL display CommentDraft and PostDraft records filtered to the current client with status "pending", providing approve, reject, and edit actions with the same behavior as the main review queue at `/review`.
7. THE Client_Hub Activity tab SHALL display the 20 most recent ActivityEvent records for the current client, ordered by created_at descending, showing event_type, description, and timestamp for each entry.
8. EACH tab in the Client_Hub SHALL load its content via an HTMX partial endpoint (one endpoint per tab) to avoid full page reloads when switching tabs.
9. THE Client_Hub SHALL set active_nav to "clients" in the Sidebar_Navigation.
10. IF the client_id in the URL does not match any existing client, THEN THE Client_Hub SHALL return an HTTP 404 response with an error message indicating the client was not found.

### Requirement 4: Review Queue Batch Operations

**User Story:** As an operator, I want to select multiple pending drafts and approve or reject them in one action, so that I can process high-volume review queues faster.

#### Acceptance Criteria

1. THE Review_Queue SHALL display a checkbox next to each pending draft item for both CommentDraft and PostDraft entries.
2. WHEN one or more checkboxes are selected, THE Review_Queue SHALL display a floating action bar at the bottom of the page with "Approve Selected" and "Reject Selected" buttons and a count of selected items.
3. WHEN the operator clicks "Approve Selected", THE Review_Queue SHALL submit the list of selected draft IDs (maximum 50 per batch) and transition each draft to "approved" status, triggering the same per-draft side effects as individual approval (audit log entry, learning capture, and activity event) for each successfully transitioned draft.
4. WHEN the operator clicks "Reject Selected", THE Review_Queue SHALL submit the list of selected draft IDs (maximum 50 per batch) and transition each draft to "rejected" status, triggering the same per-draft side effects as individual rejection (audit log entry, learning capture, and activity event) for each successfully transitioned draft.
5. IF any draft in a batch operation cannot be transitioned because its status is no longer "pending" (e.g., already approved by another user), THEN THE Review_Queue SHALL skip that draft, complete the remaining transitions, and display a summary indicating how many drafts succeeded and listing the IDs of drafts that were skipped with the reason.
6. THE Review_Queue SHALL include a "Select All on Page" checkbox in the table header that toggles all visible draft checkboxes.
7. WHEN a batch operation completes, THE Review_Queue SHALL refresh the draft list via HTMX to reflect the updated statuses.
8. IF the operator submits a batch containing more than 50 draft IDs, THEN THE Review_Queue SHALL reject the request and display an error message indicating the maximum batch size has been exceeded.

### Requirement 5: Review Queue Aging Alerts

**User Story:** As an operator, I want to see which drafts have been pending for too long, so that I can prioritize stale items before they become irrelevant (threads may get locked or buried).

#### Acceptance Criteria

1. WHEN a CommentDraft or PostDraft has been in "pending" status for longer than 24 hours, THE Review_Queue SHALL display an Aging_Alert indicator (amber clock icon and "Pending Xh" label) next to the draft, where X is the whole number of hours since created_at.
2. WHEN a draft has been pending for longer than 48 hours, THE Aging_Alert SHALL change to red color and display "Stale — Xh" to indicate critical urgency.
3. WHEN a draft transitions out of "pending" status (to "approved", "rejected", or "posted"), THE Review_Queue SHALL remove the Aging_Alert indicator from that draft.
4. THE Review_Queue SHALL use oldest-first (ascending created_at) as the default sort order.
5. THE Review_Queue SHALL display the draft creation timestamp in relative format next to each item, using hours ("3h ago") for drafts less than 24 hours old and days ("2d ago") for drafts 24 hours or older.
6. WHEN a CommentDraft's associated RedditThread has is_locked set to true, THE Review_Queue SHALL display a "Thread Locked" badge alongside the Aging_Alert to indicate the draft is no longer actionable.
7. IF a PostDraft is displayed in the Review_Queue, THEN THE Review_Queue SHALL apply aging alerts (criteria 1 and 2) based on its created_at timestamp but SHALL NOT display a "Thread Locked" badge, since PostDraft has no thread relationship.

### Requirement 6: Review Queue Client Filter

**User Story:** As an operator, I want to filter the review queue by client, so that I can focus on one client's drafts at a time during my review session.

#### Acceptance Criteria

1. THE Review_Queue SHALL display a client filter control at the top of the page listing all clients where `is_active = true`, plus an "All" option as the first entry.
2. WHEN the operator selects a client from the filter, THE Review_Queue SHALL display only drafts belonging to the selected client while preserving all other active filters (status, sort order, age, subreddit, avatar).
3. WHEN the operator selects "All" (default when no `client_id` query parameter is present), THE Review_Queue SHALL display drafts from all active clients.
4. WHEN the operator selects a client filter option, THE Review_Queue SHALL update the browser URL query parameter `client_id` via `hx-push-url` so that the selected filter persists across page refreshes and is shareable as a link.
5. WHEN the operator selects a client filter option, THE Review_Queue SHALL replace the draft list section and stats bar via an HTMX partial request without a full page reload, completing the update within 2 seconds under normal network conditions.
6. IF no drafts exist for the selected client in the current status, THEN THE Review_Queue SHALL display an empty-state message indicating no drafts match the current filters.

### Requirement 7: Priority Banner on Dashboard

**User Story:** As an operator, I want the dashboard to tell me "what needs attention right now" with a prioritized list of urgent tasks, so that I can start my daily workflow without manually checking multiple pages.

#### Acceptance Criteria

1. THE Operations_Dashboard SHALL display a Priority_Banner above the top metrics bar listing actionable items sorted by the following fixed priority order: (1) avatars with "shadowbanned" or "suspended" health_status, (2) pipeline failures in the last 24 hours, (3) subreddits not scraped in over 24 hours, (4) drafts pending review for over 24 hours.
2. THE Priority_Banner SHALL include items of these types: drafts pending over 24 hours (count and link to review queue filtered by status=pending), subreddits not scraped in over 24 hours (count and link to subreddits page filtered by stale status), avatars with "shadowbanned" or "suspended" health_status (count and link to avatars page filtered by health status), and pipeline failures in the last 24 hours (count and link to activity feed filtered by error status), where a pipeline failure is defined as an ActivityEvent with event_type in ("scrape", "score", "generate") whose event_metadata contains an "error" key.
3. WHEN there are no urgent items across all four categories, THE Priority_Banner SHALL display a green "All clear — no urgent items" message.
4. THE Priority_Banner SHALL refresh via HTMX partial on page load and every 60 seconds thereafter.
5. EACH item in the Priority_Banner SHALL be rendered as a clickable element displaying the item count and category label, and SHALL navigate to the relevant admin page with query parameters pre-applied to filter to the specific urgent subset (e.g., ?status=pending&age=24h for drafts, ?stale=true for subreddits, ?health=shadowbanned,suspended for avatars, ?type=error for activity feed).
6. IF the Priority_Banner HTMX partial request fails, THEN THE Operations_Dashboard SHALL retain the last successfully loaded banner content and display a non-blocking error indicator.

### Requirement 8: Client Hub Action Log Widget

**User Story:** As an operator, I want to see recent actions taken on a client (pipeline runs, draft approvals, setting changes) directly on the Client Hub, so that I have full context without navigating to the global audit log.

#### Acceptance Criteria

1. THE Action_Log_Widget SHALL display the 20 most recent audit log entries where client_id matches the current client, ordered by created_at descending.
2. THE Action_Log_Widget SHALL display for each entry: timestamp in relative format (e.g., "3 minutes ago") for entries less than 24 hours old and absolute format (e.g., "May 10, 14:32") for older entries, user name joined from the User table (or "System" when user_id is NULL), action type, entity type, and a one-line summary extracted from the details JSONB field.
3. IF the details JSONB field is NULL or empty for an audit log entry, THEN THE Action_Log_Widget SHALL display the action and entity_type as the summary fallback instead of a blank value.
4. THE Action_Log_Widget SHALL be loadable as an HTMX partial at `/admin/clients/{id}/action-log` for lazy loading and refresh.
5. THE Action_Log_Widget SHALL include a "View All" link that navigates to `/admin/audit-logs?client_id={id}` with the client filter pre-applied.
6. WHEN an action is performed on the Client_Hub (pipeline trigger, draft approval, or setting change), THE Action_Log_Widget SHALL auto-refresh within 2 seconds to display the new entry by emitting an HTMX trigger event that causes the widget to re-fetch its partial.
7. IF no audit log entries exist for the current client, THEN THE Action_Log_Widget SHALL display an empty state message indicating no recent activity has been recorded.

### Requirement 9: Audit Log Coverage for Missing Actions

**User Story:** As an operator, I want all significant admin actions to be logged in the audit trail, so that I have a complete record of who did what and when.

#### Acceptance Criteria

1. WHEN an operator triggers a database backup, THE Admin_Panel SHALL create an audit log entry with action "trigger_backup", entity_type "system", and details including the backup outcome ("success" or "failure").
2. WHEN an operator deletes audit log entries (single or bulk), THE Admin_Panel SHALL create an audit log entry with action "delete_audit_logs" and entity_type "audit_log" including the count of deleted records and any active filter parameters in the details field, before the deletion is committed.
3. WHEN an operator triggers a pipeline action from the dashboard or Client_Hub, THE Admin_Panel SHALL create an audit log entry with action "trigger_pipeline", entity_type "task", and details including the pipeline_type and target entity_id.
4. WHEN an operator performs a batch approve or batch reject in the Review_Queue for up to 50 drafts at a time, THE Admin_Panel SHALL create an audit log entry with action "batch_approve" or "batch_reject", entity_type "comment_draft", and details including the count of affected drafts and a list of their IDs.
5. THE Admin_Panel SHALL include the user_id of the authenticated operator in every audit log entry created by an operator-initiated action.
6. IF the audited action fails after the audit log entry is created, THEN THE Admin_Panel SHALL update or append to the audit log details field to reflect the failure outcome.

### Requirement 10: Review Flow Post-Approval UX Improvement

**User Story:** As an operator, I want the post-approval flow to match my actual workflow (approve now, post to Reddit later, then mark as posted), so that I am not prompted to mark as posted immediately after approving.

#### Acceptance Criteria

1. WHEN the operator approves a draft, THE Review_Queue SHALL transition the draft to "approved" status and return an inline confirmation element displaying the text "Approved" without rendering a "Mark as Posted" form or URL input field in the response.
2. THE Review_Queue SHALL list all approved-but-not-posted drafts under the existing "Approved" status filter tab, displaying for each draft: the thread title, subreddit, avatar username, and a "Mark as Posted" action button.
3. WHEN the operator clicks the "Mark as Posted" button on an approved draft in the "Approved" tab, THE Review_Queue SHALL expand an inline form containing a URL input field (pre-labelled for the Reddit comment URL) and a submit button, without navigating away from the list.
4. WHEN the operator submits the "Mark as Posted" form with a URL that starts with "https://www.reddit.com/" or "https://reddit.com/" and has a total length of no more than 2048 characters, THE Review_Queue SHALL transition the draft to "posted" status, store the URL, and replace the form with a "Posted" confirmation element.
5. IF the operator submits the "Mark as Posted" form with an empty URL field, THEN THE Review_Queue SHALL display a validation error adjacent to the URL input indicating that the Reddit URL is required, and SHALL NOT transition the draft status.
6. IF the operator submits the "Mark as Posted" form with a URL that does not start with "https://www.reddit.com/" or "https://reddit.com/", THEN THE Review_Queue SHALL display a validation error adjacent to the URL input indicating that a valid Reddit URL is required, and SHALL NOT transition the draft status.
