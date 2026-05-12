---
inclusion: auto
fileMatchPattern: "**/admin_dashboard*,**/admin_health*,**/dashboard*,**/topology*,**/transparency*"
---

# System Topology Dashboard — Design Specification

## Implementation Status: 90% COMPLETE (Sufficient for Pilot)

**What's done:**
- `app/services/topology.py` — full service with 9 nodes, state detection, 24h heatmap, forecast
- `app/templates/partials/topology_panel.html` — HTMX partial with heatmap grid
- `/admin/dashboard/topology-panel` — endpoint exists, auto-refreshes on dashboard
- All data sources wired: ScrapeLog, ActivityEvent, AIUsageLog, CommentDraft
- Tests: `tests/test_topology_service.py`

**What's remaining (nice-to-have, not blocking pilot):**
- Dedicated `/admin/topology` full page with worker count + queue depth
- Celery worker inspection (`celery_app.control.inspect()`)
- Redis queue depth (`llen("celery")`)

## Overview

The Admin Dashboard (`/admin/`) includes a **System Topology Timeline** section — a real-time visualization of all pipeline nodes, their current state, historical activity, and projected next execution.

This is NOT a simple status page. It's an **operational intelligence view** that shows:
1. All system nodes (pipeline stages) as a connected graph
2. Each node's current state (idle / running / error / stale)
3. A timeline of recent activity per node (last 24h)
4. A forecast point: when each node is expected to fire next

## System Nodes (Pipeline Stages)

Each node represents a distinct operational unit:

| Node ID | Label | Description |
|---------|-------|-------------|
| `scrape` | Scraping | Reddit subreddit scraping via PRAW |
| `score` | Scoring | AI thread scoring (Gemini Flash) |
| `generate` | Generation | Comment/post generation (Claude Sonnet) |
| `review` | Review Queue | Human review pending items |
| `reddit_api` | Reddit API | External Reddit API health |
| `llm_api` | LLM API | External LLM provider health |
| `database` | Database | PostgreSQL connectivity |
| `queue` | Task Queue | Celery/SQS worker health |
| `safety` | Safety Layer | Guardrail checks (brand ratio, phase gates) |

## Node State Machine

Each node has one of these states at any moment:

- **`idle`** — Not currently running, last run succeeded
- **`running`** — Currently executing (task in progress)
- **`success`** — Last run completed successfully (within expected interval)
- **`warning`** — Last run succeeded but is approaching staleness threshold
- **`error`** — Last run failed or node is unreachable
- **`stale`** — No activity for longer than expected interval

## Data Sources for Node State

### Scrape Node
- Source: `scrape_log` table (latest `scraped_at`, `errors`, `duration_ms`)
- Source: `activity_events` where `event_type = 'scrape'`
- Stale threshold: `scrape_interval_hours` per subreddit (default 6h)
- Running detection: activity_event with no corresponding completion event

### Score Node
- Source: `activity_events` where `event_type = 'score'`
- Source: `reddit_threads` with `scored_at` timestamps
- Stale threshold: 2h after last scrape completed (scoring should follow scraping)

### Generate Node
- Source: `activity_events` where `event_type = 'generate'`
- Source: `comment_drafts` creation timestamps
- Stale threshold: 4h after scoring completed

### Review Queue Node
- Source: `comment_drafts` where `status = 'pending'`
- Warning: > 10 pending items or oldest pending > 24h
- This node is human-driven, no "stale" concept

### Reddit API Node
- Source: `activity_events` where `event_type = 'reddit_api'` or scrape errors
- Source: Rate limit tracking (if available)
- Error: Any 429/503 in last 15 minutes

### LLM API Node
- Source: `ai_usage_log` — last successful call timestamp, error rate
- Error: > 3 consecutive failures or no calls in expected window

### Database Node
- Source: Direct health check (SELECT 1)
- Always checked on page load

### Queue Node
- Source: Celery inspect (active/reserved/scheduled tasks)
- Source: Worker heartbeat (last seen)
- Error: No worker heartbeat in 5 minutes

### Safety Node
- Source: `activity_events` where `event_type = 'safety'`
- Warning: Any guardrail firing in last 1h
- Error: Multiple guardrail firings (possible misconfiguration)

## Timeline Visualization

### Layout
- Horizontal timeline (X-axis = time, last 24 hours)
- Each node is a row (Y-axis)
- Events rendered as dots/bars on the timeline
- Color-coded: green (success), amber (warning), red (error), gray (idle)
- Current time marked with vertical line
- Forecast point marked with dashed vertical line + label

### Implementation (HTMX + Tailwind + inline SVG or CSS grid)
- No external charting library (keep it lightweight)
- Use CSS grid with 24 columns (1 per hour) or 48 columns (30-min slots)
- Each cell colored based on activity in that time slot
- Tooltip on hover: event count, duration, errors
- Auto-refresh every 60 seconds via HTMX

### Forecast Point
- Based on schedule configuration (Celery Beat intervals or cron)
- Shows "next expected run" for each node
- Calculated from: last_run_at + configured_interval
- Displayed as a pulsing dot at the projected time

## API Endpoint

```
GET /admin/dashboard/topology
```

Returns JSON:
```json
{
  "nodes": [
    {
      "id": "scrape",
      "label": "Scraping",
      "state": "idle",
      "last_run_at": "2026-05-07T10:30:00Z",
      "last_duration_ms": 4500,
      "last_error": null,
      "next_expected_at": "2026-05-07T16:30:00Z",
      "events_24h": [
        {"hour": 0, "count": 2, "errors": 0},
        {"hour": 1, "count": 0, "errors": 0},
        ...
      ]
    },
    ...
  ],
  "connections": [
    {"from": "scrape", "to": "score"},
    {"from": "score", "to": "generate"},
    {"from": "generate", "to": "review"},
    {"from": "review", "to": "reddit_api"},
    {"from": "scrape", "to": "reddit_api"},
    {"from": "score", "to": "llm_api"},
    {"from": "generate", "to": "llm_api"}
  ],
  "current_time": "2026-05-07T14:22:00Z"
}
```

## HTMX Partial

```
GET /admin/dashboard/topology-panel
```

Returns rendered HTML partial for the topology timeline section.
Auto-refreshes every 60 seconds.

## Template Structure

The topology section goes BETWEEN the "Top Metrics Bar" and "Client Cards" on the admin dashboard:

```
Top Metrics Bar
↓
[NEW] System Topology Timeline
↓
Run All Controls
↓
Client Cards + Side Panels
↓
Run History
```

## Visual Design (Dark Theme)

- Background: `bg-dark-steel` (matches existing cards)
- Border: `border-slate-700`
- Node labels: left column, `text-gray-300`, monospace
- Timeline grid: `bg-slate-800` cells
- Active cells: colored based on state
- Connections: thin lines between nodes (optional, can be implied by order)
- Forecast marker: dashed border, `text-indigo-400`

## Service Layer

New service: `app/services/topology.py`

Functions:
- `get_node_states(db: Session) -> list[NodeState]` — compute current state for all nodes
- `get_timeline_events(db: Session, hours: int = 24) -> dict[str, list[HourBucket]]` — aggregate events per node per hour
- `get_forecast_points(db: Session) -> dict[str, datetime]` — next expected run per node

## Performance Considerations

- All queries should be indexed (activity_events already has `ix_activity_events_type_created`)
- Timeline aggregation: single query with GROUP BY date_trunc('hour', created_at), event_type
- Cache topology state in memory for 30 seconds (avoid DB hit on every HTMX poll)
- Total query budget: < 100ms for the full topology endpoint

## Dependencies

- No new Python packages required
- No JavaScript charting libraries (pure CSS grid + Tailwind)
- Uses existing models: ActivityEvent, ScrapeLog, AIUsageLog, CommentDraft

## Future Extensions (not in v1)

- Click on node → drill down to detailed logs
- Node dependency graph (visual arrows between nodes)
- Anomaly highlighting (unusual patterns in timeline)
- SLA indicators (expected vs actual execution time)
- Per-client topology view (filter by client)
