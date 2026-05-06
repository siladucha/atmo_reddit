# Requirements Document

## Introduction

A single-page Daily Operations Dashboard that gives the sole technical operator a unified view of the entire platform's health and pipeline status. Currently, operational data is scattered across individual Client Hub pages, the Scrape Queue, and the existing admin dashboard. This feature consolidates all daily operational needs — client pipeline status, manual triggers, review queue counts, scrape freshness, run history, schedule visibility, and avatar health — into one actionable page accessible from the existing "Dashboard" link in the admin sidebar's Operations section.

## Glossary

- **Operations_Dashboard**: The new unified admin page at `/admin/` (replaces the current lightweight dashboard) providing a consolidated operational view across all clients.
- **Pipeline_Controls**: HTMX-powered buttons that trigger Celery tasks (scrape, score, generate, full-pipeline) for individual clients or all clients at once.
- **Scrape_Freshness_Panel**: A section displaying per-subreddit last-scraped timestamps with stale indicators (>24h since last scrape).
- **Run_History**: A chronological record of pipeline executions per client, sourced from ActivityEvent records.
- **Avatar_Health_Summary**: An aggregated view of avatar statuses showing counts by reddit_status (active, shadowbanned, suspended, unknown) and warming phase eligibility.
- **Schedule_Display**: A read-only section showing the next scheduled Celery Beat run times for automated pipeline tasks.
- **Client_Status_Card**: A per-client summary widget showing today's scrape/score/generate counts and pending review items.

## Requirements

### Requirement 1: Client Status Overview

**User Story:** As the operator, I want to see the status of all clients at a glance on one page, so that I can quickly identify which clients need attention without navigating to each Client Hub individually.

#### Acceptance Criteria

1. WHEN the operator navigates to `/admin/`, THE Operations_Dashboard SHALL display a Client_Status_Card for each active client.
2. THE Client_Status_Card SHALL show the client name, threads scraped today (last 24h), threads scored today, comments generated today, and pending review count.
3. WHEN a client has zero activity in the last 24 hours, THE Client_Status_Card SHALL display a visual warning indicator (amber highlight).
4. THE Operations_Dashboard SHALL load client status data via an HTMX partial endpoint to enable auto-refresh without full page reload.

### Requirement 2: Pipeline Controls (Per-Client and Bulk)

**User Story:** As the operator, I want to manually trigger pipeline steps for any client or all clients at once from the dashboard, so that I can intervene without navigating to individual Client Hub pages.

#### Acceptance Criteria

1. THE Client_Status_Card SHALL include Pipeline_Controls buttons for: Scrape, Score, Generate, and Full Pipeline.
2. WHEN the operator clicks a Pipeline_Controls button for a specific client, THE Operations_Dashboard SHALL POST to the existing `/pipeline/{action}/{client_id}` endpoint and display a confirmation toast.
3. THE Operations_Dashboard SHALL include a "Run All" section with buttons to trigger Scrape All, Score All, Generate All, and Full Pipeline All across every active client.
4. WHEN the operator clicks a "Run All" button, THE Operations_Dashboard SHALL trigger the corresponding pipeline action for each active client and display a summary confirmation.
5. WHILE a pipeline task is running for a client, THE Client_Status_Card SHALL display a loading indicator on the corresponding action button.
6. IF a pipeline trigger returns an error, THEN THE Operations_Dashboard SHALL display the error message inline near the triggering button.

### Requirement 3: Pending Reviews Quick Access

**User Story:** As the operator, I want to see the total pending review count and jump to the review queue directly, so that I never miss comments waiting for approval.

#### Acceptance Criteria

1. THE Operations_Dashboard SHALL display a global pending reviews counter in a prominent position (top metrics bar).
2. THE pending reviews counter SHALL show the total count of CommentDraft records with status "pending" across all clients.
3. WHEN the operator clicks the pending reviews counter, THE Operations_Dashboard SHALL navigate to `/admin/review`.
4. WHEN the pending reviews count exceeds zero, THE counter SHALL use a visually distinct style (badge with count) to draw attention.

### Requirement 4: Scrape Freshness Panel

**User Story:** As the operator, I want to see which subreddits are stale (not scraped recently), so that I can identify scraping failures or gaps before they affect content generation.

#### Acceptance Criteria

1. THE Scrape_Freshness_Panel SHALL list all active subreddits across all clients with their last_scraped_at timestamp and time-since-scrape in human-readable format.
2. WHEN a subreddit has not been scraped in the last 24 hours, THE Scrape_Freshness_Panel SHALL mark it as stale with a red indicator.
3. WHEN a subreddit has never been scraped (last_scraped_at is NULL), THE Scrape_Freshness_Panel SHALL display "Never" with a red indicator.
4. THE Scrape_Freshness_Panel SHALL group subreddits by client and sort stale subreddits to the top within each group.
5. THE Scrape_Freshness_Panel SHALL be loadable as an HTMX partial for on-demand refresh.

### Requirement 5: Pipeline Run History

**User Story:** As the operator, I want to see when the last full pipeline run happened for each client and what the results were, so that I can verify the system is operating correctly.

#### Acceptance Criteria

1. THE Operations_Dashboard SHALL display a Run_History section showing the last pipeline run per client with timestamp and outcome summary.
2. THE Run_History SHALL source data from ActivityEvent records filtered by event_type in (scrape, score, generate).
3. THE Run_History entry SHALL show: client name, event type, timestamp (relative format like "2h ago"), and the event message (e.g., "Scraped 15 posts from r/cybersecurity").
4. THE Run_History SHALL display the most recent 20 events across all clients, ordered by created_at descending.
5. THE Run_History SHALL be loadable as an HTMX partial to support filtering by client.

### Requirement 6: Next Scheduled Run Display

**User Story:** As the operator, I want to see when the next automated pipeline run is scheduled, so that I know whether to wait or trigger manually.

#### Acceptance Criteria

1. THE Schedule_Display SHALL show the next scheduled run time for each Celery Beat task: morning pipeline (08:00 UTC), afternoon pipeline (14:00 UTC), hobby pipeline (10:00 UTC), and avatar health check (every 12h at :30).
2. THE Schedule_Display SHALL compute and display time-until-next-run in human-readable format (e.g., "in 3h 20m").
3. THE Schedule_Display SHALL indicate which schedule entry will fire next by highlighting it.

### Requirement 7: Avatar Health Summary

**User Story:** As the operator, I want to see a summary of avatar health across all clients, so that I can quickly spot shadowbanned accounts or avatars eligible for phase promotion.

#### Acceptance Criteria

1. THE Avatar_Health_Summary SHALL display aggregate counts of avatars by reddit_status: active, shadowbanned, suspended, unknown.
2. WHEN any avatar has reddit_status "shadowbanned" or "suspended", THE Avatar_Health_Summary SHALL highlight those counts with a red indicator.
3. THE Avatar_Health_Summary SHALL display the count of avatars eligible for phase promotion (warming_phase < 3 and last_phase_evaluated_at older than 30 days or NULL).
4. THE Avatar_Health_Summary SHALL display the total active avatar count and a breakdown by warming_phase (Phase 1, Phase 2, Phase 3).
5. WHEN the operator clicks on a status category in the Avatar_Health_Summary, THE Operations_Dashboard SHALL navigate to `/admin/avatars` with the corresponding status filter applied.

### Requirement 8: Page Layout and Responsiveness

**User Story:** As the operator, I want the dashboard to be well-organized and scannable, so that I can complete my daily check in under 60 seconds.

#### Acceptance Criteria

1. THE Operations_Dashboard SHALL use the existing admin_base.html dark theme layout with active_nav set to "dashboard".
2. THE Operations_Dashboard SHALL organize content into a top metrics bar (pending reviews, total clients, total avatars, next run time) followed by a two-column layout: client cards on the left (wider), and side panels (freshness, avatar health, schedule) on the right.
3. THE Operations_Dashboard SHALL use Tailwind CSS utility classes consistent with the existing admin panel styling.
4. THE Operations_Dashboard SHALL use HTMX attributes (hx-get, hx-post, hx-target, hx-swap) for all interactive elements to avoid full page reloads.
5. THE Operations_Dashboard SHALL include an auto-refresh mechanism that polls the client status section every 60 seconds via HTMX hx-trigger="every 60s".
