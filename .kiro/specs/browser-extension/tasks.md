# Browser Extension — Implementation Tasks

## Phase 1: MVP — CQS + Health Monitoring + Backend API

### Task 1: Backend — ExtensionSession Model + Migration
- [ ] Create `app/models/extension_session.py` with fields: id, executor_id, avatar_id, device_fingerprint, extension_version, last_heartbeat, is_online, active_reddit_username, mode, created_at, updated_at
- [ ] Create Alembic migration `ext01`
- [ ] Add relationship to User model

### Task 2: Backend — Extension API Routes
- [ ] Create `app/routes/extension_api.py`
- [ ] `POST /api/extension/register` — validate executor token, create ExtensionSession
- [ ] `GET /api/extension/tasks` — return pending tasks for active Reddit account
- [ ] `POST /api/extension/report` — handle task results, CQS results, health signals
- [ ] `POST /api/extension/heartbeat` — update last_heartbeat, is_online, active_reddit_username
- [ ] `GET /api/extension/config` — return limits (daily_cap, min_interval, active_hours)
- [ ] JWT auth middleware for extension endpoints (executor token scope)
- [ ] Register routes in main.py

### Task 3: Backend — Extension Task Dispatcher
- [ ] Create `app/services/extension_dispatcher.py`
- [ ] `route_task_to_executor()` — decide extension vs email delivery
- [ ] `get_active_extension_session(executor_email)` — find online session
- [ ] Modify `dispatch_due_email_tasks` to check extension availability first
- [ ] Add `delivery_channel` field to ExecutionTask ("email" | "extension")
- [ ] Add `dispatched_to_extension_at` timestamp field
- [ ] Fallback logic: offline > 30 min → email

### Task 4: Backend — CQS Generator Unblock
- [ ] Remove `is_frozen` skip from `generate_cqs_check_tasks()` (allow frozen avatars)
- [ ] Remove `health_status in (shadowbanned, suspended)` skip from generator
- [ ] Add `delivery_channel_preference` logic — if extension available, prefer extension
- [ ] Add CQS check for Phase 1 avatars (remove `warming_phase >= 2` from `run_cqs_check_batch`)
- [ ] Test: frozen avatar gets CQS task generated

### Task 5: Backend — Health Signal Ingestion
- [ ] Create `app/services/extension_health.py`
- [ ] `process_health_signal()` — handle signals from extension
- [ ] `handle_cqs_result()` — update avatar.cqs_level + cqs_checked_at directly
- [ ] `handle_shadowban_cleared()` — auto-unfreeze logic with operator notification
- [ ] `handle_karma_report()` — update SubredditKarma from extension data
- [ ] Emit activity events for all health state changes
- [ ] Create notification for operator on recovery events

### Task 6: Backend — Admin UI Extension Status
- [ ] Add "Extension" column to admin avatars list (online/offline/not_installed badge)
- [ ] Add extension session details to avatar detail page
- [ ] Show extension heartbeat status in operator dashboard

### Task 7: Extension — Project Scaffold
- [ ] Create `ramp_extension/` directory in project root
- [ ] `manifest.json` (Manifest V3, permissions: storage, alarms, notifications, host_permissions)
- [ ] Project structure: background/, content/, popup/, shared/, assets/
- [ ] Build tooling (webpack or vite for bundling)
- [ ] `package.json` with dev dependencies

### Task 8: Extension — Service Worker (background.js)
- [ ] Auth module — store/retrieve executor JWT token from chrome.storage.local
- [ ] Poller module — GET /api/extension/tasks every 30s (chrome.alarms API)
- [ ] Heartbeat module — POST /api/extension/heartbeat every 60s
- [ ] Task queue — local queue management (chrome.storage.local)
- [ ] Timer engine — fire tasks at scheduled_at (chrome.alarms)
- [ ] Kill switch handler — pause_all command processing
- [ ] Message passing to content script (chrome.runtime.sendMessage)
- [ ] Network error handling + retry with backoff

### Task 9: Extension — Content Script (reddit_actions.js)
- [ ] Reddit variant detection (shreddit / old / redesign)
- [ ] `getCurrentUsername()` — detect logged-in Reddit account
- [ ] `postComment(threadUrl, text, replyTo)` — navigate, fill, submit, return permalink
- [ ] `postCQSCheck()` — create post in r/WhatIsMyCQS, wait for bot reply, parse level
- [ ] `readKarma()` — parse karma values from profile page
- [ ] `detectBanIndicators()` — scan page for removal notices, ban alerts
- [ ] `checkThreadStatus(url)` — detect locked/removed/archived
- [ ] DOM selector fallback chain (primary → data-testid → ARIA → XPath)
- [ ] Error wrapping + reporting to service worker

### Task 10: Extension — Popup UI
- [ ] `popup.html` — layout with task queue, settings, history tabs
- [ ] `popup.js` — fetch queue from service worker, render tasks
- [ ] Task cards: subreddit badge, thread title, comment preview, scheduled time
- [ ] Approve/Reject buttons per task
- [ ] Auto/Manual mode toggle
- [ ] Pause button (stops posting, keeps monitoring)
- [ ] Connection status indicator (green/yellow/red)
- [ ] History tab — last 20 completed tasks
- [ ] Settings: RAMP URL input, token input, active hours config
- [ ] Badge count on extension icon (pending tasks)

### Task 11: Extension — Onboarding Flow
- [ ] First-run detection (no token in storage)
- [ ] Setup screen: enter RAMP URL + executor token
- [ ] Validation: POST /api/extension/register
- [ ] Success state: show "Connected" + detected Reddit username
- [ ] Error handling: invalid token, network error, wrong URL

### Task 12: Integration Test — CQS Self-Healing
- [ ] Test scenario: frozen avatar + extension online → CQS task created → extension posts → RAMP reads → CQS updates
- [ ] Test scenario: extension offline → fallback to email delivery
- [ ] Test scenario: wrong Reddit account → task held + warning
- [ ] Test scenario: kill switch → all tasks paused immediately

---

## Phase 2: Auto-Posting

### Task 13: Extension — Auto-Mode Comment Posting
- [ ] Auto-mode toggle in service worker state
- [ ] Timer engine: hold task until scheduled_at, then dispatch to content script
- [ ] Safety checks before posting: daily cap, min interval, active hours
- [ ] Thread liveness check (extension navigates, checks for lock indicators)
- [ ] Post → extract permalink → report to RAMP
- [ ] Rate limiting: hard minimum 3 minutes between posts

### Task 14: Backend — Extension-Posted Draft Handling
- [ ] On receiving `task_completed` with `status=posted`: update draft.status, slot.status, avatar.last_posted_at
- [ ] Store reddit_comment_url from extension report
- [ ] Emit `comment_posted_via_extension` activity event
- [ ] No reconciliation needed — immediate confirmation

### Task 15: Extension — Thread Safety Checks
- [ ] Detect locked thread (lock icon, "comments locked" banner)
- [ ] Detect removed/deleted thread (404, "[removed]" body)
- [ ] Detect archived thread ("archived" banner)
- [ ] Report blocked status to RAMP with specific reason
- [ ] RAMP cancels task + updates EPG slot status

---

## Phase 3: Intelligence

### Task 16: Extension — Shadowban Probe
- [ ] Open incognito/private window with avatar's profile URL
- [ ] Check if recent comments are visible (compare logged-in vs incognito)
- [ ] Report visibility ratio to RAMP
- [ ] Frequency: once per health check cycle (every 12h when browser open)

### Task 17: Backend — Auto-Unfreeze Logic
- [ ] If CQS improved from "lowest" to anything better → candidate for unfreeze
- [ ] If CQS improved + shadowban probe shows visible → auto-unfreeze
- [ ] Create `app/services/avatar_recovery.py`
- [ ] `evaluate_recovery(avatar)` — check all signals, decide unfreeze
- [ ] Emit `avatar_auto_recovered` activity event
- [ ] Send operator notification with recovery details
- [ ] Log in audit trail

### Task 18: Extension — Multi-Account Detection
- [ ] Detect current Reddit username from page DOM
- [ ] Compare with expected avatar for pending tasks
- [ ] If mismatch: show popup warning "Switch to u/X to complete tasks"
- [ ] Filter task queue to only show tasks for current account
- [ ] Report active account to RAMP heartbeat

### Task 19: Admin UI — Extension Dashboard
- [ ] New section in admin: "Extension Fleet"
- [ ] Per-executor: online status, last_seen, version, active account, mode
- [ ] Per-avatar: extension coverage (has extension? online?)
- [ ] Alerts: extension offline for executor with pending tasks
- [ ] Manual "push task to extension" button on task detail page

---

## Phase 4: Polish & Distribution

### Task 20: Firefox Port
- [ ] Adapt manifest.json for Firefox (Manifest V2/V3 hybrid)
- [ ] Test content script selectors on Firefox
- [ ] Firefox Add-ons submission

### Task 21: Chrome Web Store Submission
- [ ] Privacy policy page (hosted on gorampit.com/privacy-extension)
- [ ] Store listing: description, screenshots, category
- [ ] Review compliance (no credential exfiltration, minimal permissions)
- [ ] Submit for review

### Task 22: Executor Onboarding Update
- [ ] Generate extension token in admin UI (per executor)
- [ ] Email template with install instructions + token
- [ ] Onboarding guide page in portal
- [ ] Token rotation mechanism (invalidate old tokens)

### Task 23: Error Recovery & Resilience
- [ ] Retry logic for failed posts (1 retry after 60s)
- [ ] DOM selector auto-update mechanism (report broken selectors, receive updates from RAMP)
- [ ] Offline queue persistence (survive browser restart)
- [ ] Graceful degradation when RAMP backend unreachable
