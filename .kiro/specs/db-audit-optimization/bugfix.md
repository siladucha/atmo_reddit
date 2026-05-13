# Bugfix Requirements Document

## Introduction

Two related operational issues are degrading system reliability and performance:

1. **Audit log gaps** — Several significant system operations (pipeline orchestration, scraping tasks, karma tracking, presence scanning, profile analytics, phase evaluation) do not emit audit log entries. This means the admin audit logs page (`/admin/audit-logs`) shows an incomplete picture of system activity, making it difficult to trace what happened and when.

2. **Missing database indexes** — Frequently queried columns on high-volume tables (`avatar_subreddit_presence`, `subreddit_karma`, `scrape_log`, `audit_log`) lack composite or targeted indexes, causing sequential scans on tables that grow linearly with avatar/client count. This results in slow page loads on admin panels and degraded pipeline performance as data volume increases.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN the orchestrator runs `run_full_pipeline_all_clients` (scheduled at 08:00 and 14:00 UTC) THEN the system does not create an audit log entry recording the pipeline execution start/completion or which clients were processed

1.2 WHEN the orchestrator runs `run_hobby_pipeline_all_avatars` (scheduled at 10:00 UTC) THEN the system does not create an audit log entry recording the hobby pipeline execution or which avatars were processed

1.3 WHEN a scraping task (`scrape_subreddit_shared`, `scrape_professional_subreddits`, `scrape_hobby_subreddits`) completes or fails THEN the system does not create an audit log entry for the scrape operation

1.4 WHEN the karma tracking task (`track_karma_all_avatars`) runs every 4 hours THEN the system does not create an audit log entry recording the karma tracking batch

1.5 WHEN the presence scanning task runs for an avatar THEN the system does not create an audit log entry recording the presence scan

1.6 WHEN the profile analytics snapshot task (`snapshot_profile_analytics_all_avatars`) runs daily at 05:20 UTC THEN the system does not create an audit log entry

1.7 WHEN the phase evaluation task (`evaluate_all_avatar_phases`) runs daily at 06:00 UTC and promotes/demotes avatars THEN the system does not create an audit log entry for the batch evaluation (individual phase changes may emit ActivityEvents but not AuditLog entries)

1.8 WHEN the scoring service (`score_unscored_threads_for_client`) completes scoring a batch of threads THEN the system does not create an audit log entry recording the scoring results

1.9 WHEN queries filter `avatar_subreddit_presence` by `avatar_id` with ordering by `last_activity_at` or `total_karma` THEN the system performs a sequential scan because no composite index covers this access pattern

1.10 WHEN queries filter `subreddit_karma` by `avatar_id` with ordering by `last_updated_at` THEN the system performs a sequential scan on the ordering column (only a single-column `avatar_id` index exists)

1.11 WHEN queries filter `scrape_log` by `subreddit_id` and order by `scraped_at` THEN the system performs a sequential scan because no index covers the `subreddit_id + scraped_at` composite pattern

1.12 WHEN the admin audit logs page filters by `created_at` range combined with `action` or `entity_type` THEN the system may not use the optimal index path because the existing composite index is `(client_id, action, created_at)` which requires `client_id` as the leading column

### Expected Behavior (Correct)

2.1 WHEN the orchestrator runs `run_full_pipeline_all_clients` THEN the system SHALL create an audit log entry with action `pipeline_run_started` and details including client count, and upon completion SHALL log `pipeline_run_completed` with success/failure counts

2.2 WHEN the orchestrator runs `run_hobby_pipeline_all_avatars` THEN the system SHALL create an audit log entry with action `hobby_pipeline_run` and details including avatar count processed

2.3 WHEN a scraping task completes or fails THEN the system SHALL create an audit log entry with action `scrape_completed` or `scrape_failed` including subreddit name, posts found/new, and duration

2.4 WHEN the karma tracking task runs THEN the system SHALL create an audit log entry with action `karma_tracking_batch_completed` including avatars checked and any significant karma changes detected

2.5 WHEN the presence scanning task completes for an avatar THEN the system SHALL create an audit log entry with action `presence_scan_completed` including avatar_id and subreddits discovered/updated

2.6 WHEN the profile analytics snapshot task runs THEN the system SHALL create an audit log entry with action `profile_analytics_batch_completed` including avatars processed count

2.7 WHEN the phase evaluation task runs and results in promotions or demotions THEN the system SHALL create an audit log entry with action `phase_evaluation_completed` including promoted/demoted/unchanged counts

2.8 WHEN the scoring service completes scoring a batch THEN the system SHALL create an audit log entry with action `scoring_batch_completed` including client_id, threads scored, and tag distribution (engage/monitor/skip counts)

2.9 WHEN queries filter `avatar_subreddit_presence` by `avatar_id` with ordering THEN the system SHALL use an index that covers `(avatar_id, last_activity_at)` for efficient retrieval

2.10 WHEN queries filter `subreddit_karma` by `avatar_id` with ordering by `last_updated_at` THEN the system SHALL use a composite index `(avatar_id, last_updated_at)` for efficient retrieval

2.11 WHEN queries filter `scrape_log` by `subreddit_id` and order by `scraped_at` THEN the system SHALL use a composite index `(subreddit_id, scraped_at)` for efficient retrieval

2.12 WHEN the admin audit logs page filters by `action` and `created_at` range (without `client_id`) THEN the system SHALL use an index that supports this access pattern efficiently via a composite index `(action, created_at)`

### Unchanged Behavior (Regression Prevention)

3.1 WHEN admin CRUD operations (create/update/delete users, clients, avatars, subreddits, keywords) are performed THEN the system SHALL CONTINUE TO create audit log entries as currently implemented in `services/admin.py`

3.2 WHEN review actions (approve/reject/edit comment drafts) are performed THEN the system SHALL CONTINUE TO create audit log entries as currently implemented in `routes/review.py` and `routes/pages.py`

3.3 WHEN system settings are changed THEN the system SHALL CONTINUE TO create audit log entries as currently implemented in `services/settings.py`

3.4 WHEN health status changes are detected (shadowban/suspension) THEN the system SHALL CONTINUE TO create audit log entries as currently implemented in `services/health_checker.py`

3.5 WHEN CQS batch checks complete THEN the system SHALL CONTINUE TO create audit log entries as currently implemented in `services/cqs_checker.py`

3.6 WHEN pipeline triggers are initiated from admin UI THEN the system SHALL CONTINUE TO create audit log entries as currently implemented in `routes/admin.py`

3.7 WHEN existing indexes are used by current query patterns (e.g., `ix_comment_drafts_client_status`, `ix_reddit_threads_subreddit_not_locked`, `ix_thread_scores_client_tag`) THEN the system SHALL CONTINUE TO use those indexes without degradation

3.8 WHEN the `query_audit_logs` function is called with existing filter combinations THEN the system SHALL CONTINUE TO return correct paginated results with the same semantics
