# Implementation Plan

## Overview

Browser Extension MVP (Phase 1): Backend API + Extension scaffold + CQS probe + comment posting (REQUIRED_UI mode) + health probe + heartbeat. Closes CQS deadlock (MIT-001). 

## Tasks

- [x] 1. Backend — ExecutionNode Model + Migration
  - [x] 1.1. Create `app/models/execution_node.py`: id (UUID PK), executor_id (FK users.id), device_fingerprint, extension_version, last_heartbeat, is_online, active_reddit_username, tasks_in_queue, created_at, updated_at
  - [x] 1.2. Create Alembic migration `ext01` for execution_nodes table
  - [x] 1.3. Add `epg_mode` field to Avatar model (default "required")
  - [x] 1.4. Add task lifecycle fields to ExecutionTask: execution_node_id, task_hash, lease_expires_at, idempotency_key, task_lifecycle_status, probe_type, priority

- [x] 2. Backend — Extension API Routes
  - [x] 2.1. Create `app/routes/extension_api.py` with JWT auth middleware for extension endpoints
  - [x] 2.2. `GET /api/extension/policy` — per-avatar immutable config (epg_mode, limits, allowed types)
  - [x] 2.3. `GET /api/extension/tasks` — pending tasks filtered by active_reddit_username from last heartbeat, HMAC-signed payloads
  - [x] 2.4. `POST /api/extension/report` — untrusted results, validate idempotency_key (first wins, dupes → 200 NOOP)
  - [x] 2.5. `POST /api/extension/heartbeat` — update node status + active account
  - [x] 2.6. `POST /api/extension/register` — validate executor JWT, create ExecutionNode, return node_id
  - [x] 2.7. Register routes in main.py

- [x] 3. Backend — Task Orchestrator
  - [x] 3.1. Create `app/services/extension_dispatcher.py` with `create_extension_task()` — signs payload with HMAC, sets lease_expires_at, generates idempotency_key
  - [x] 3.2. `assign_task_to_node()` — CREATED → ASSIGNED transition
  - [x] 3.3. `validate_report()` — REPORTED → FINALIZED (check HMAC, idempotency, dedup)
  - [x] 3.4. `expire_stale_leases()` — cron logic: ASSIGNED/EXECUTING past lease → EXPIRED
  - [x] 3.5. `route_task()` — extension online + correct account → assign; else hold/email fallback
  - [x] 3.6. Modify `dispatch_due_email_tasks` to check extension availability first
  - [x] 3.7. Priority ordering: diagnostic tasks before content tasks

- [ ] 4. Backend — CQS Generator Unblock
  - [x] 4.1. Add `delivery_channel_preference` field — if extension available, prefer extension
  - [x] 4.2. Create tasks as `diagnostic_probe` type with `probe_type=reddit_cqs`

- [ ] 5. Backend — Signal Validator
  - [x] 5.1. Create `app/services/signal_validator.py` with `normalize_probe_result()` — extract CQS level from raw bot text, classify confidence
  - [x] 5.2. `process_health_signal()` — assign trust_weight, calculate decay, aggregate
  - [x] 5.3. `handle_cqs_improvement()` — create recovery_candidate + trigger PRAW probe
  - [ ] 5.4. `handle_karma_report()` — update SubredditKarma
  - [ ] 5.5. Emit activity events for all state-affecting signals
  - [ ] 5.6. Operator notification on recovery candidates

- [ ] 6. Backend — Backpressure + Lease Expiry
  - [ ] 6.1. Add Celery task `expire_extension_leases` (every 5 min): find ASSIGNED/EXECUTING past lease_expires_at → mark EXPIRED
  - [ ] 6.2. Re-creation logic: EXPIRED diagnostic tasks → re-create; EXPIRED content tasks → email fallback
  - [ ] 6.3. Queue overflow detection: if node reports tasks_in_queue > limit → hold new assignments

- [x] 7. Extension — Project Scaffold
  - [x] 7.1. Create `ramp_extension/` directory with structure: background/, content/, popup/, shared/, assets/
  - [x] 7.2. Create `manifest.json` (MV3, permissions: storage, alarms, notifications, host_permissions for reddit.com + gorampit.com)
  - [x] 7.3. Create build tooling (vite config) and `package.json`

- [ ] 8. Extension — Service Worker
  - [x] 8.1. Auth module: store/retrieve JWT from chrome.storage.local
  - [x] 8.2. Poller: GET /tasks every N seconds (from policy.poll_interval_seconds)
  - [x] 8.3. HMAC verifier: validate task_hash before accepting task into local queue
  - [x] 8.4. Queue: chrome.storage.local, max 20 items, priority-ordered (diagnostic first)
  - [x] 8.5. Timer: hold tasks until scheduled_at, dispatch to content script
  - [x] 8.6. Heartbeat: POST /heartbeat every 60s (node_id, active_username, queue_depth)
  - [ ] 8.7. Kill switch: on `pause_all` command → clear queue, stop timer
  - [ ] 8.8. Account monitor: detect active_reddit_username change → abort executing task → report account_switch_error
  - [ ] 8.9. Network retry: exponential backoff on failures, queue results locally

- [ ] 9. Extension — Content Script
  - [x] 9.1. Reddit variant detection (shreddit / old / redesign) with selector fallback chains per variant
  - [x] 9.2. `getCurrentUsername()` — detect logged-in account
  - [x] 9.3. `postComment(threadUrl, text, replyTo)` — navigate, fill, submit, return permalink
  - [x] 9.4. `postCQSCheck()` — submit in r/WhatIsMyCQS, wait 60s, read bot reply, return raw text
  - [x] 9.5. `checkSubmissionVisibility(postUrl, subreddit)` — check /new feed, return present/absent
  - [ ] 9.6. `readKarma()` — parse profile for karma values
  - [ ] 9.7. `detectBanIndicators()` — scan for removal notices
  - [ ] 9.8. Error wrapping: all failures → structured error with code + details; report `dom_structure_changed` if all selectors fail

- [ ] 10. Extension — Popup UI (REQUIRED_UI mode for MVP)
  - [x] 10.1. `popup.html` layout: task queue, connection status, pause button
  - [x] 10.2. `popup.js`: fetch queue from service worker, render task cards with subreddit badge, thread title, comment preview, time
  - [x] 10.3. Approve/Reject buttons per task
  - [ ] 10.4. Connection indicator (green/yellow/red) + Pause button (stops content, keeps diagnostics)
  - [ ] 10.5. Badge count on icon. No business logic in UI (no phase, no strategy)

- [ ] 11. Extension — Onboarding Flow
  - [x] 11.1. First-run detection (no token in storage) + setup screen: enter RAMP URL + executor token
  - [ ] 11.2. POST /register → receive execution_node_id
  - [ ] 11.3. GET /policy → confirm connection + show config
  - [ ] 11.4. Success: "Connected as [username]" + mode display

- [ ] 12. Integration Test — Full Cycle
  - [ ] 12.1. CQS probe: task created → assigned → extension posts → reports raw → backend extracts level → recovery candidate
  - [ ] 12.2. Comment post: task signed → assigned → HMAC verified → posted → permalink reported → FINALIZED
  - [ ] 12.3. Lease expiry: task assigned → extension offline → lease expires → email fallback
  - [ ] 12.4. Account mismatch: wrong account active → task held + warning
  - [ ] 12.5. Kill switch: pause_all → all tasks stopped
  - [ ] 12.6. Queue overflow: >20 tasks → new deliveries rejected

## Task Dependency Graph

```
1 --> 2
1 --> 3
2 --> 4
2 --> 5
2 --> 6
3 --> 6
7 --> 8
7 --> 9
7 --> 10
7 --> 11
8 --> 9
1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11 --> 12
```

## Notes

- Task 4 sub-tasks 4.1 and 4.2 only — the `is_frozen` filter removals (originally 4.1-4.3) were already deployed June 27 and are marked DONE in the original spec.
- Phase 2-4 tasks (13-21) are NOT included in this implementation plan — they are future scope.
- Extension tasks (7-11) can be worked in parallel with backend tasks (1-6) once Task 7 scaffold is complete.
