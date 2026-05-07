# Implementation Plan: System Topology Timeline

## Overview

Implement a real-time System Topology Timeline panel on the Admin Dashboard that visualizes 9 pipeline nodes with current state, 24-hour activity heatmap, and forecast points. The panel uses CSS grid + Tailwind, auto-refreshes via HTMX every 60s, and all queries must complete within 100ms.

## Tasks

- [x] 1. Create TopologyService with data models and node state computation
  - [x] 1.1 Create `app/services/topology.py` with NodeState enum, HourBucket/NodeStatus/TopologyData dataclasses, and SCHEDULE_CONFIG dict
    - Define `NodeState(str, Enum)` with values: idle, running, success, warning, error, stale
    - Define `HourBucket` dataclass with hour (0-23), event_count, error_count
    - Define `NodeStatus` dataclass with node_id, label, state, last_run_at, last_duration_ms, last_error, forecast_point, forecast_relative, is_overdue, timeline (list[HourBucket])
    - Define `TopologyData` dataclass with nodes (list[NodeStatus]), current_hour, generated_at
    - Define `SCHEDULE_CONFIG` dict mapping node_id to schedule type/params (interval, cron, human, event, always)
    - _Requirements: 1.1, 3.1, 3.5, 3.7, 3.8_

  - [x] 1.2 Implement `compute_node_states(db: Session) -> dict[str, NodeState]`
    - Query `scrape_log` for Scraping node staleness (no entries within `scrape_interval_hours` default 6h)
    - Query `activity_events` type='score' for Scoring staleness (no entries within 2h after last scrape)
    - Query `activity_events` type='generate' for Generation staleness (no entries within 4h after last scoring)
    - Query `comment_drafts` for Review Queue warning (>50 pending OR oldest pending >24h)
    - Query `activity_events` + `scrape_log` errors for Reddit API error rate (>5% in 15 min)
    - Query `ai_usage_log` for LLM API error rate (>10% in 15 min)
    - Execute `SELECT 1` for Database health check
    - Query `activity_events` type='heartbeat' for Task Queue (no heartbeat within 5 min)
    - Query `activity_events` type='safety' for Safety node (any in last 1h → warning)
    - Default to "idle" when node completed successfully within expected interval
    - Use batched queries (single round-trip where possible)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 10.1, 10.6_

  - [ ]* 1.3 Write property test for staleness threshold (Property 1)
    - **Property 1: Staleness threshold determines node state**
    - Use Hypothesis to generate arbitrary last_activity timestamps and verify state is "stale" iff `now - last_activity > threshold`
    - Test all time-based nodes: Scraping/6h, Scoring/2h, Generation/4h, Task Queue/5min
    - **Validates: Requirements 1.2, 1.3, 1.4, 1.9, 1.11**

  - [ ]* 1.4 Write property test for error rate threshold (Property 2)
    - **Property 2: Error rate threshold determines error state**
    - Use Hypothesis to generate total_events (1-1000) and error_events (0-total) combinations
    - Verify Reddit API state is "error" iff error_rate > 5%, LLM API iff > 10%
    - **Validates: Requirements 1.6, 1.7**

  - [ ]* 1.5 Write property test for Review Queue warning (Property 3)
    - **Property 3: Review Queue warning threshold**
    - Use Hypothesis to generate pending_count (0-200) and oldest_draft_age (0-72h)
    - Verify state is "warning" iff pending_count > 50 OR oldest_draft_age > 24h
    - **Validates: Requirements 1.5**

- [x] 2. Implement timeline aggregation
  - [x] 2.1 Implement `aggregate_timeline(db: Session, hours: int = 24) -> dict[str, list[HourBucket]]`
    - Single SQL query on `activity_events` with `GROUP BY event_type, date_trunc('hour', created_at)` leveraging `ix_activity_events_type_created` index
    - Supplementary query on `scrape_log` grouped by `date_trunc('hour', scraped_at)` for Scraping node
    - Supplementary query on `ai_usage_log` grouped by `date_trunc('hour', created_at)` for LLM API node
    - Supplementary query on `comment_drafts` grouped by `date_trunc('hour', created_at)` for Review Queue node
    - Return exactly 24 HourBuckets per node (fill missing hours with zero counts)
    - Each bucket includes hour (0-23), event_count, error_count
    - Log performance warning if query exceeds 100ms
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 10.2, 10.3, 10.4, 10.5_

  - [ ]* 2.2 Write property test for timeline aggregation (Property 4)
    - **Property 4: Timeline aggregation produces correct hour buckets**
    - Use Hypothesis to generate sets of events with known timestamps
    - Verify: exactly 24 buckets per node, hour in [0,23], event_count matches manual count, error_count <= event_count, sum equals total events
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8**

- [x] 3. Implement forecast calculation
  - [x] 3.1 Implement `calculate_forecasts(db: Session) -> dict[str, tuple[str | None, str | None, bool]]`
    - Scraping: use queue_tick interval (60s) + earliest subreddit due based on `last_scraped_at + scrape_interval_hours`
    - Scoring: next occurrence of 08:00 or 14:00 UTC (whichever is sooner)
    - Generation: next AI pipeline run + 15 min offset
    - Review Queue: return "human-driven" label
    - Task Queue: last heartbeat + 60s interval
    - Safety: return "event-driven" label
    - Database: return "always available" label
    - Reddit API / LLM API: next scheduled occurrence
    - Return ISO 8601 timestamp or descriptive label, relative time string, and is_overdue flag
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

  - [ ]* 3.2 Write property test for cron-based forecast (Property 5)
    - **Property 5: Cron-based forecast returns next scheduled occurrence**
    - Use Hypothesis to generate arbitrary UTC timestamps
    - Verify forecast is next 08:00 or 14:00 UTC strictly in the future, and forecast - now <= 12 hours
    - **Validates: Requirements 3.3, 3.4**

  - [ ]* 3.3 Write property test for interval-based forecast (Property 6)
    - **Property 6: Interval-based forecast returns last_run + interval**
    - Use Hypothesis to generate last_run timestamps and verify forecast == last_run + interval
    - Verify is_overdue == True when forecast < now
    - **Validates: Requirements 3.2, 3.6**

  - [ ]* 3.4 Write property test for forecast format invariant (Property 7)
    - **Property 7: Forecast output format invariant**
    - Use Hypothesis to generate TopologyData and verify each forecast_point is valid ISO 8601 or one of: "human-driven", "event-driven", "always available"
    - **Validates: Requirements 3.8**

- [x] 4. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement topology API endpoints
  - [x] 5.1 Implement `get_topology_data(db: Session) -> TopologyData` main entry point
    - Orchestrate calls to compute_node_states, aggregate_timeline, calculate_forecasts
    - Assemble NodeStatus list for all 9 nodes with complete data
    - Include current_hour and generated_at timestamp
    - _Requirements: 4.3, 10.4_

  - [x] 5.2 Add `GET /admin/dashboard/topology-panel` route to `app/routes/admin.py`
    - Require superuser authentication via `require_superuser` dependency
    - Call `get_topology_data(db)` and render Jinja2 partial template
    - Return HTML partial for HTMX consumption
    - Handle database failure gracefully (degraded response with Database node as "error")
    - _Requirements: 4.1, 4.2, 4.5, 4.6_

  - [x] 5.3 Add `GET /admin/dashboard/topology` JSON route to `app/routes/admin.py`
    - Require superuser authentication
    - Call `get_topology_data(db)` and return JSON response
    - Serialize TopologyData dataclasses to JSON-compatible dict
    - _Requirements: 4.4_

  - [ ]* 5.4 Write unit tests for topology endpoints
    - Test authentication requirement (401 without superuser)
    - Test response contains exactly 9 nodes
    - Test JSON endpoint returns valid structure
    - Test HTMX partial returns HTML with correct hx-* attributes
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [x] 6. Create topology panel template
  - [x] 6.1 Create `app/templates/partials/topology_panel.html` with CSS grid heatmap
    - Render CSS grid with 9 rows (one per Pipeline_Node) and 24 columns (one per hour)
    - Left column: node labels with state indicator dots (colored circles per NodeState)
    - Hour cells: color intensity based on event_count (bg-slate-800 for zero, emerald scale for events, red scale for errors)
    - Hour labels (00-23) along top axis
    - Current hour highlight with distinct vertical border
    - Forecast markers: pulsing indicator at projected hour column (dashed border, different opacity)
    - Overdue forecast: amber color with "overdue" label
    - Non-scheduled nodes: descriptive label instead of time marker
    - Relative time labels for forecasts ("in 45 min", "in 2h")
    - Section header "System Topology" with subtitle "Last 24 hours"
    - Manual refresh button triggering immediate HTMX reload
    - Collapse toggle with localStorage persistence script
    - Use only Tailwind CSS classes (no external JS charting libraries)
    - Max height 400px, responsive from 1024px to 1920px viewport
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 9.3, 9.4, 9.5_

  - [ ]* 6.2 Write property test for node state CSS mapping (Property 8)
    - **Property 8: Node state to CSS class mapping is total and correct**
    - Use Hypothesis to generate all valid NodeState enum values
    - Verify mapping: idle→"bg-gray-500", running→"bg-blue-500 animate-pulse", success→"bg-emerald-500", warning→"bg-amber-500", error→"bg-red-500", stale→"bg-gray-600 opacity-50"
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6**

  - [ ]* 6.3 Write unit tests for template rendering
    - Test panel HTML contains correct grid structure (9 rows × 24 cols)
    - Test collapse toggle includes localStorage script
    - Test HTMX attributes present (hx-get, hx-trigger, hx-swap)
    - _Requirements: 5.1, 8.1, 8.4, 9.5_

- [x] 7. Integrate topology panel into admin dashboard
  - [x] 7.1 Modify `app/templates/admin_dashboard.html` to include topology panel container
    - Add topology container div between Top Metrics Bar and Run All Bulk Controls
    - Use same card styling: `bg-dark-steel rounded-lg border border-slate-700 mb-6`
    - Add `hx-get="/admin/dashboard/topology-panel"` with `hx-trigger="load, every 60s"` and `hx-swap="innerHTML"`
    - Include loading placeholder text
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 9.1, 9.2_

  - [x] 7.2 Add manual refresh button and error handling
    - Manual refresh button triggers immediate HTMX reload of topology panel
    - On HTMX request failure, retain last rendered content (HTMX default behavior)
    - Display subtle error indicator on failure
    - _Requirements: 8.3, 8.5_

- [x] 8. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (8 properties total)
- Unit tests validate specific examples and edge cases
- No new database tables required — reads from existing: activity_events, scrape_log, ai_usage_log, comment_drafts
- All test files go in `tests/` directory: test_topology_service.py, test_topology_routes.py, test_topology_template.py
