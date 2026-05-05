# Requirements Document

## Introduction

This feature adds full operational transparency to the Reddit Marketing SaaS platform for both admins (Max & Tzvi) and future self-service clients. The system currently runs a pipeline (scrape → score → generate → human review) but provides no chronological visibility into what happened, when, or how well. This feature introduces three capabilities: (1) an Activity Feed showing a chronological log of system events on the dashboard, (2) a Scrape Log table recording every scraping run with per-subreddit health metrics, and (3) a Client Transparency Dashboard showing pipeline statistics, scoring distributions, draft statuses, and AI costs scoped per client.

## Glossary

- **Activity_Feed**: A chronological list of system events displayed on the admin dashboard, showing human-readable summaries of pipeline actions (scraping, scoring, generation, review status changes).
- **Scrape_Log**: A PostgreSQL table (`scrape_log`) that records metadata for every individual subreddit scraping run, including timing, post counts, and errors.
- **Client_Transparency_Dashboard**: An admin page at `/admin/clients/{id}/transparency` that displays pipeline statistics, scoring distributions, draft pipeline status, AI costs, and per-subreddit scrape freshness for a specific client.
- **Pipeline_Statistics**: Aggregated metrics computed from existing tables (RedditThread, CommentDraft, AIUsageLog, Scrape_Log) scoped to a single client, covering thread counts, scoring tag distribution, draft status breakdown, and AI cost totals.
- **Activity_Event**: A single record in the `activity_events` table representing one system action (e.g., "Scraped 47 posts from r/meditation") with a type, client scope, and structured metadata.
- **Scrape_Freshness**: The `last_scraped_at` timestamp on the `client_subreddits` table indicating when a subreddit was last successfully scraped.
- **Admin_Dashboard**: The existing admin panel page at `/admin/` that displays system-wide statistics (admin_dashboard.html).
- **Pipeline**: The automated sequence of Celery tasks: scrape → score → generate → human review.
- **Tag_Distribution**: The breakdown of scored threads into engage, monitor, and skip categories.
- **Draft_Status_Breakdown**: The count of CommentDraft records grouped by status: pending, approved, rejected, posted.

## Requirements

### Requirement 1: Activity Event Data Model

**User Story:** As an admin, I want system events to be stored in a structured table, so that the activity feed can display a reliable chronological log of pipeline actions.

#### Acceptance Criteria

1. THE Activity_Event model SHALL store the following fields: id (UUID primary key), client_id (nullable FK to clients), event_type (string, one of: scrape, score, generate, review, system), message (human-readable text), metadata (JSONB for structured details), created_at (timestamptz with server default).
2. WHEN an Activity_Event is created without a client_id, THE Activity_Event model SHALL accept the record as a system-wide event.
3. WHEN an Activity_Event is created with a client_id, THE Activity_Event model SHALL associate the event with that specific client for scoped queries.
4. THE Activity_Event model SHALL require a non-empty event_type and message for every record.

### Requirement 2: Activity Event Recording in Pipeline

**User Story:** As an admin, I want the pipeline to automatically record events at each stage, so that I can see what the system did without checking logs manually.

#### Acceptance Criteria

1. WHEN the scraping task completes for a subreddit, THE Pipeline SHALL create an Activity_Event with event_type "scrape", a message like "Scraped {N} posts from r/{subreddit_name} ({M} new)", and metadata containing posts_found, posts_new, subreddit_name, and duration_ms.
2. WHEN the scoring task completes for a client, THE Pipeline SHALL create an Activity_Event with event_type "score", a message like "Scored {N} threads: {E} engage, {M} monitor, {S} skip", and metadata containing the tag counts.
3. WHEN the generation task completes for a client, THE Pipeline SHALL create an Activity_Event with event_type "generate", a message like "Generated {N} comment drafts", and metadata containing the count of drafts generated.
4. WHEN a CommentDraft status changes to approved, rejected, or posted, THE Pipeline SHALL create an Activity_Event with event_type "review" and a message describing the action.
5. IF a pipeline stage fails with an error, THEN THE Pipeline SHALL create an Activity_Event with event_type "system", a message describing the failure, and metadata containing the error details.

### Requirement 3: Activity Feed Display on Admin Dashboard

**User Story:** As an admin, I want to see a chronological activity feed on the dashboard, so that I get instant visibility into what the system is doing.

#### Acceptance Criteria

1. THE Admin_Dashboard SHALL display an Activity Feed section showing the most recent 50 Activity_Events in reverse chronological order.
2. WHEN the Activity Feed is displayed, THE Admin_Dashboard SHALL show each event with its timestamp, event_type badge (color-coded), and message text.
3. WHEN the admin loads the dashboard, THE Admin_Dashboard SHALL load the Activity Feed via an HTMX partial for fast page rendering.
4. WHERE a client filter is applied, THE Admin_Dashboard SHALL display only Activity_Events scoped to the selected client_id.
5. IF no Activity_Events exist, THEN THE Admin_Dashboard SHALL display a placeholder message "No activity yet. Run the pipeline to see events here."

### Requirement 4: Scrape Log Data Model

**User Story:** As an admin, I want every scraping run recorded in a dedicated table, so that I can track per-subreddit health and diagnose problems.

#### Acceptance Criteria

1. THE Scrape_Log model SHALL store the following fields: id (UUID primary key), client_id (FK to clients), subreddit_name (string), scraped_at (timestamptz with server default), posts_found (integer), posts_new (integer), errors (nullable text), duration_ms (integer).
2. THE Scrape_Log model SHALL have a database index on (client_id, subreddit_name, scraped_at) for efficient per-subreddit queries.
3. THE Scrape_Log model SHALL be created via an Alembic migration that does not alter existing tables beyond adding the new table and the last_scraped_at column on client_subreddits.

### Requirement 5: Scrape Log Recording

**User Story:** As an admin, I want the scraping task to write a Scrape_Log record after every subreddit scrape, so that I have a complete history of scraping runs.

#### Acceptance Criteria

1. WHEN the scraping task finishes processing a subreddit, THE Pipeline SHALL insert a Scrape_Log record with the client_id, subreddit_name, posts_found (total from Reddit API), posts_new (after deduplication), duration_ms (wall-clock time of the scrape), and errors (null on success, error message on failure).
2. WHEN the scraping task finishes processing a subreddit successfully, THE Pipeline SHALL update the corresponding ClientSubreddit.last_scraped_at to the current UTC timestamp.
3. IF the scraping task fails for a subreddit, THEN THE Pipeline SHALL still insert a Scrape_Log record with the error message and posts_found=0, posts_new=0.

### Requirement 6: Scrape Freshness on ClientSubreddit

**User Story:** As an admin, I want to see when each subreddit was last scraped, so that I can quickly spot stale data.

#### Acceptance Criteria

1. THE ClientSubreddit model SHALL have a last_scraped_at field (nullable DateTime with timezone) added via the same Alembic migration as the Scrape_Log table.
2. WHEN the admin views a client's subreddit list, THE Admin_Panel SHALL display the last_scraped_at timestamp for each subreddit, formatted as relative time (e.g., "2 hours ago").
3. WHILE a subreddit's last_scraped_at is older than 24 hours or null, THE Admin_Panel SHALL highlight that subreddit with a warning indicator (amber color).

### Requirement 7: Client Transparency Dashboard — Pipeline Statistics

**User Story:** As an admin, I want to see pipeline statistics for each client on a dedicated transparency page, so that I can demonstrate value to Tzvi and track client progress.

#### Acceptance Criteria

1. THE Client_Transparency_Dashboard SHALL be accessible at `/admin/clients/{id}/transparency` and use the admin_base.html dark theme layout.
2. THE Client_Transparency_Dashboard SHALL display thread statistics: total threads scraped, threads in last 24 hours, threads in last 7 days — all scoped to the given client_id.
3. THE Client_Transparency_Dashboard SHALL display Tag_Distribution: count and percentage of threads tagged as engage, monitor, and skip — scoped to the given client_id.
4. THE Client_Transparency_Dashboard SHALL display Draft_Status_Breakdown: count of CommentDraft records in each status (pending, approved, rejected, posted) — scoped to the given client_id.
5. THE Client_Transparency_Dashboard SHALL display total AI cost (sum of cost_usd from AIUsageLog) scoped to the given client_id, broken down by operation type (scoring, generation, editing).
6. THE Client_Transparency_Dashboard SHALL display per-subreddit Scrape_Freshness: a table of active subreddits with last_scraped_at, total posts found (from Scrape_Log), and average posts_new per scrape.

### Requirement 8: Client Transparency Dashboard — Activity History

**User Story:** As an admin, I want to see a client-scoped activity history on the transparency page, so that I can review what the system did for a specific client.

#### Acceptance Criteria

1. THE Client_Transparency_Dashboard SHALL include a client-scoped Activity Feed showing the most recent 100 Activity_Events for the given client_id in reverse chronological order.
2. WHEN the activity history is displayed, THE Client_Transparency_Dashboard SHALL show each event with its timestamp, event_type badge, and message — identical formatting to the dashboard Activity Feed.
3. THE Client_Transparency_Dashboard SHALL load the activity history via an HTMX partial to support pagination or "load more" without full page reload.

### Requirement 9: Service Layer for Transparency Queries

**User Story:** As a developer, I want all transparency data queries encapsulated in a service module, so that the route handlers remain thin and the logic is testable.

#### Acceptance Criteria

1. THE Transparency_Service SHALL provide a function to retrieve Activity_Events with optional filters: client_id, event_type, limit, and offset.
2. THE Transparency_Service SHALL provide a function to compute Pipeline_Statistics for a given client_id, returning thread counts (total, 24h, 7d), Tag_Distribution, Draft_Status_Breakdown, and AI cost breakdown.
3. THE Transparency_Service SHALL provide a function to retrieve Scrape_Freshness data: per-subreddit last_scraped_at, total posts found, and average posts_new — for a given client_id.
4. THE Transparency_Service SHALL return all query results as plain dictionaries, not ORM objects, to keep templates decoupled from the data layer.

### Requirement 10: Alembic Migration

**User Story:** As a developer, I want the new tables and columns added via a proper Alembic migration, so that the database schema changes are versioned and reproducible.

#### Acceptance Criteria

1. THE Alembic migration SHALL create the `activity_events` table with all fields defined in Requirement 1.
2. THE Alembic migration SHALL create the `scrape_log` table with all fields defined in Requirement 4.
3. THE Alembic migration SHALL add the `last_scraped_at` column (nullable DateTime with timezone) to the `client_subreddits` table.
4. THE Alembic migration SHALL include a downgrade function that drops the `activity_events` table, drops the `scrape_log` table, and removes the `last_scraped_at` column from `client_subreddits`.
5. WHEN the migration is applied, THE existing 93 tests SHALL continue to pass without modification.

### Requirement 11: Test Coverage

**User Story:** As a developer, I want tests for the new models, service functions, and route handlers, so that the transparency feature is reliable and regressions are caught.

#### Acceptance Criteria

1. THE test suite SHALL include unit tests for the Transparency_Service functions: activity event retrieval with filters, pipeline statistics computation, and scrape freshness queries.
2. THE test suite SHALL include tests verifying that pipeline tasks (scrape, score, generate) create the expected Activity_Events and Scrape_Log records.
3. THE test suite SHALL include tests for the Client Transparency Dashboard route returning correct HTTP status and template context.
4. THE test suite SHALL include tests verifying that the Activity Feed on the Admin Dashboard renders correctly with and without events.
5. WHEN all new tests are run together with existing tests, THE test suite SHALL pass with zero failures.
