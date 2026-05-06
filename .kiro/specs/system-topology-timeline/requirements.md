# Requirements Document

## Introduction

The System Topology Timeline is a real-time operational intelligence panel on the Admin Dashboard (`/admin/`) that visualizes all pipeline nodes as a connected system. It displays each node's current state, a 24-hour activity heatmap timeline, and a forecast point showing when each node is expected to fire next. The panel is positioned between the Top Metrics Bar and the Run All Controls section. It uses pure CSS grid + Tailwind (no external JS charting libraries), auto-refreshes every 60 seconds via HTMX, and must execute all queries within a 100ms budget.

## Glossary

- **Topology_Panel**: The HTMX partial that renders the complete System Topology Timeline section on the Admin Dashboard
- **Pipeline_Node**: A distinct operational unit in the system (Scraping, Scoring, Generation, Review Queue, Reddit API, LLM API, Database, Task Queue, Safety)
- **Node_State**: The current operational status of a Pipeline_Node — one of: idle, running, success, warning, error, stale
- **Timeline_Grid**: A CSS grid visualization showing 24 hourly columns per Pipeline_Node row, color-coded by activity intensity
- **Hour_Bucket**: An aggregated count of events for a specific Pipeline_Node within a one-hour time slot
- **Forecast_Point**: The calculated next expected execution time for a Pipeline_Node, derived from schedule configuration and last run timestamp
- **Stale_Threshold**: The maximum allowed time since last activity before a Pipeline_Node transitions to the "stale" state
- **Topology_Service**: The backend service module (`app/services/topology.py`) responsible for computing node states, timeline data, and forecast points
- **Topology_Endpoint**: The FastAPI route that returns topology data as an HTMX partial or JSON
- **Activity_Heatmap**: The visual representation of event density per hour per node using color intensity (darker = more events)

## Requirements

### Requirement 1: Topology Service — Node State Computation

**User Story:** As an admin operator, I want to see the current state of every pipeline node at a glance, so that I can immediately identify which parts of the system are healthy, degraded, or failing.

#### Acceptance Criteria

1. THE Topology_Service SHALL compute the Node_State for each of the 9 Pipeline_Nodes: Scraping, Scoring, Generation, Review Queue, Reddit API, LLM API, Database, Task Queue, Safety
2. WHEN the Scraping node has no `scrape_log` entries within the configured `scrape_interval_hours` (default 6h) for any active subreddit, THE Topology_Service SHALL set the Scraping Node_State to "stale"
3. WHEN the Scoring node has no `activity_events` with `event_type='score'` within 2 hours after the last scrape completion, THE Topology_Service SHALL set the Scoring Node_State to "stale"
4. WHEN the Generation node has no `activity_events` with `event_type='generate'` within 4 hours after the last scoring event, THE Topology_Service SHALL set the Generation Node_State to "stale"
5. WHEN the Review Queue has more than 50 pending `comment_drafts` or the oldest pending draft exceeds 24 hours, THE Topology_Service SHALL set the Review Queue Node_State to "warning"
6. WHEN the Reddit API has an error rate exceeding 5% in the last 15 minutes (based on `activity_events` and `scrape_log` errors), THE Topology_Service SHALL set the Reddit API Node_State to "error"
7. WHEN the LLM API has an error rate exceeding 10% in the last 15 minutes (based on `ai_usage_log` failures), THE Topology_Service SHALL set the LLM API Node_State to "error"
8. WHEN the Database health check (`SELECT 1`) fails, THE Topology_Service SHALL set the Database Node_State to "error"
9. WHEN the Task Queue has no worker heartbeat within the last 5 minutes (based on `activity_events` with `event_type='heartbeat'`), THE Topology_Service SHALL set the Task Queue Node_State to "error"
10. WHEN the Safety node has any guardrail firing `activity_events` with `event_type='safety'` in the last 1 hour, THE Topology_Service SHALL set the Safety Node_State to "warning"
11. WHEN a Pipeline_Node has completed its last operation successfully and is within its expected interval, THE Topology_Service SHALL set the Node_State to "idle"

### Requirement 2: Topology Service — Timeline Aggregation

**User Story:** As an admin operator, I want to see a 24-hour activity history for each pipeline node, so that I can understand load patterns, identify burst windows, and detect anomalies.

#### Acceptance Criteria

1. THE Topology_Service SHALL aggregate events for each Pipeline_Node into 24 Hour_Buckets covering the last 24 hours
2. WHEN aggregating Scraping events, THE Topology_Service SHALL count entries from `scrape_log` grouped by `date_trunc('hour', scraped_at)`
3. WHEN aggregating Scoring events, THE Topology_Service SHALL count `activity_events` with `event_type='score'` grouped by `date_trunc('hour', created_at)`
4. WHEN aggregating Generation events, THE Topology_Service SHALL count `activity_events` with `event_type='generate'` grouped by `date_trunc('hour', created_at)`
5. WHEN aggregating Review Queue events, THE Topology_Service SHALL count `comment_drafts` status transitions grouped by `date_trunc('hour', created_at)`
6. WHEN aggregating LLM API events, THE Topology_Service SHALL count `ai_usage_log` entries grouped by `date_trunc('hour', created_at)`
7. WHEN aggregating Safety events, THE Topology_Service SHALL count `activity_events` with `event_type='safety'` grouped by `date_trunc('hour', created_at)`
8. THE Topology_Service SHALL return each Hour_Bucket with: hour (0–23), event_count, and error_count
9. THE Topology_Service SHALL execute the full timeline aggregation query within 100 milliseconds

### Requirement 3: Topology Service — Forecast Point Calculation

**User Story:** As an admin operator, I want to see when each pipeline node is expected to fire next, so that I can anticipate system load and verify the schedule is operating correctly.

#### Acceptance Criteria

1. THE Topology_Service SHALL calculate the Forecast_Point for each Pipeline_Node based on its schedule configuration and last execution timestamp
2. WHEN calculating the Scraping Forecast_Point, THE Topology_Service SHALL use the `queue_tick` interval (60 seconds) and the earliest subreddit due for scraping based on `last_scraped_at + scrape_interval_hours`
3. WHEN calculating the Scoring Forecast_Point, THE Topology_Service SHALL use the next scheduled AI pipeline run (08:00 or 14:00 UTC, whichever is sooner)
4. WHEN calculating the Generation Forecast_Point, THE Topology_Service SHALL use the next scheduled AI pipeline run plus an estimated scoring duration offset
5. WHEN calculating the Review Queue Forecast_Point, THE Topology_Service SHALL display "human-driven" (no automated forecast)
6. WHEN calculating the Task Queue Forecast_Point, THE Topology_Service SHALL use the heartbeat interval (60 seconds from last heartbeat)
7. WHEN calculating the Safety Forecast_Point, THE Topology_Service SHALL display "event-driven" (fires only when guardrails trigger)
8. THE Topology_Service SHALL return each Forecast_Point as an ISO 8601 timestamp or a descriptive label for non-scheduled nodes

### Requirement 4: Topology API Endpoint

**User Story:** As a frontend developer, I want a dedicated endpoint that returns topology data as both JSON and an HTMX partial, so that the dashboard can render the panel on load and auto-refresh it every 60 seconds.

#### Acceptance Criteria

1. THE Topology_Endpoint SHALL be accessible at `GET /admin/dashboard/topology-panel` and return an HTML partial for HTMX consumption
2. THE Topology_Endpoint SHALL require superuser authentication (using the existing `require_superuser` dependency)
3. WHEN requested, THE Topology_Endpoint SHALL return data for all 9 Pipeline_Nodes including: node_id, label, current Node_State, last_run_at, last_duration_ms, error details, Forecast_Point, and 24 Hour_Buckets
4. THE Topology_Endpoint SHALL also be accessible at `GET /admin/dashboard/topology` returning JSON for programmatic access
5. THE Topology_Endpoint SHALL complete the full response (query + render) within 200 milliseconds
6. IF the Database health check fails during topology computation, THEN THE Topology_Endpoint SHALL return a degraded response with the Database node marked as "error" and other nodes showing their last known state

### Requirement 5: Timeline Grid Visualization (Frontend)

**User Story:** As an admin operator, I want to see a heatmap grid showing when each node was active over the last 24 hours, so that I can visually correlate activity patterns across the pipeline.

#### Acceptance Criteria

1. THE Topology_Panel SHALL render a CSS grid with 9 rows (one per Pipeline_Node) and 24 columns (one per hour)
2. WHEN a Hour_Bucket has zero events, THE Timeline_Grid SHALL render the cell with a dark background (`bg-slate-800`)
3. WHEN a Hour_Bucket has events with no errors, THE Timeline_Grid SHALL render the cell with green intensity proportional to event count (low: `bg-emerald-900/50`, medium: `bg-emerald-700/70`, high: `bg-emerald-500`)
4. WHEN a Hour_Bucket has events with errors, THE Timeline_Grid SHALL render the cell with red intensity (`bg-red-900/50` to `bg-red-500`)
5. THE Timeline_Grid SHALL display hour labels (00–23) along the top axis
6. THE Timeline_Grid SHALL display Pipeline_Node labels along the left axis with the current Node_State indicator (colored dot)
7. THE Timeline_Grid SHALL mark the current hour with a distinct vertical border or highlight
8. THE Timeline_Grid SHALL use only Tailwind CSS classes and inline styles (no external JavaScript charting libraries)
9. THE Topology_Panel SHALL render correctly on viewport widths from 1024px to 1920px

### Requirement 6: Forecast Point Display

**User Story:** As an admin operator, I want to see a visual marker showing when each node is expected to fire next, so that I can verify the schedule is on track and anticipate upcoming load.

#### Acceptance Criteria

1. WHEN a Pipeline_Node has a calculated Forecast_Point within the next 24 hours, THE Timeline_Grid SHALL display a pulsing indicator at the corresponding hour column
2. WHEN a Pipeline_Node has a Forecast_Point in the past (overdue), THE Topology_Panel SHALL display the forecast marker with a warning color (`text-amber-400`) and label "overdue"
3. WHEN a Pipeline_Node is non-scheduled (Review Queue, Safety), THE Topology_Panel SHALL display a descriptive label instead of a time marker
4. THE Forecast_Point indicator SHALL be visually distinct from historical activity cells (dashed border, different opacity, or pulsing animation via Tailwind)
5. THE Forecast_Point display SHALL include a human-readable relative time label (e.g., "in 45 min", "in 2h")

### Requirement 7: Node State Indicators

**User Story:** As an admin operator, I want clear visual indicators for each node's current state, so that I can instantly identify problems without reading detailed metrics.

#### Acceptance Criteria

1. WHEN a Pipeline_Node is in "idle" state, THE Topology_Panel SHALL display a gray dot indicator (`bg-gray-500`)
2. WHEN a Pipeline_Node is in "running" state, THE Topology_Panel SHALL display a blue pulsing dot indicator (`bg-blue-500 animate-pulse`)
3. WHEN a Pipeline_Node is in "success" state, THE Topology_Panel SHALL display a green dot indicator (`bg-emerald-500`)
4. WHEN a Pipeline_Node is in "warning" state, THE Topology_Panel SHALL display an amber dot indicator (`bg-amber-500`)
5. WHEN a Pipeline_Node is in "error" state, THE Topology_Panel SHALL display a red dot indicator (`bg-red-500`)
6. WHEN a Pipeline_Node is in "stale" state, THE Topology_Panel SHALL display a gray dot with a strikethrough or dimmed appearance (`bg-gray-600 opacity-50`)
7. THE Node_State indicator SHALL be positioned next to the Pipeline_Node label in the left column of the Timeline_Grid

### Requirement 8: HTMX Auto-Refresh Integration

**User Story:** As an admin operator, I want the topology panel to auto-refresh every 60 seconds without full page reload, so that I always see current system state while working on the dashboard.

#### Acceptance Criteria

1. THE Topology_Panel SHALL use HTMX `hx-get` to load its content from `/admin/dashboard/topology-panel` on page load
2. THE Topology_Panel SHALL use HTMX `hx-trigger="load, every 60s"` to auto-refresh every 60 seconds
3. WHEN the HTMX request fails (network error or server error), THE Topology_Panel SHALL retain the last successfully rendered content and display a subtle error indicator
4. THE Topology_Panel SHALL use `hx-swap="innerHTML"` to replace only the panel content without affecting surrounding dashboard elements
5. THE Topology_Panel SHALL include a manual refresh button that triggers an immediate HTMX reload

### Requirement 9: Dashboard Layout Integration

**User Story:** As an admin operator, I want the topology timeline positioned between the Top Metrics Bar and Run All Controls, so that system health is the first detailed view I see after the summary numbers.

#### Acceptance Criteria

1. THE Topology_Panel SHALL be rendered between the Top Metrics Bar (grid of 4 metric cards) and the Run All Bulk Controls section in the admin dashboard template
2. THE Topology_Panel SHALL use the same card styling as other dashboard sections: `bg-dark-steel rounded-lg border border-slate-700`
3. THE Topology_Panel SHALL include a section header "System Topology" with a subtitle showing the time range ("Last 24 hours")
4. THE Topology_Panel SHALL not exceed 400px in height to avoid pushing critical controls below the fold
5. THE Topology_Panel SHALL be collapsible (toggle visibility) with state persisted in localStorage

### Requirement 10: Performance and Query Optimization

**User Story:** As a platform developer, I want the topology queries to execute within strict time budgets, so that the dashboard remains responsive and the 60-second refresh cycle does not degrade user experience.

#### Acceptance Criteria

1. THE Topology_Service SHALL execute all node state computations in a single database round-trip where possible (batch queries)
2. THE Topology_Service SHALL use the existing index `ix_activity_events_type_created` on `(event_type, created_at)` for timeline aggregation queries
3. THE Topology_Service SHALL aggregate timeline data using a single SQL query with `GROUP BY date_trunc('hour', created_at), event_type` rather than per-node individual queries
4. THE Topology_Endpoint SHALL complete the full computation (all node states + timeline + forecasts) within 100 milliseconds of database query time
5. WHEN the database query exceeds 100 milliseconds, THE Topology_Service SHALL log a performance warning with the actual query duration
6. THE Topology_Service SHALL use connection pooling from the existing SQLAlchemy session (no additional database connections)

