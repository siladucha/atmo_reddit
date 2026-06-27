# Requirements Document

## Introduction

A Chrome browser extension installed on executor (avatar owner) machines that enables RAMP to perform actions through the executor's authenticated Reddit browser session. Replaces the need for separate API credentials, residential proxies, and OAuth tokens by leveraging the executor's existing browser session as the execution layer.

### Problem Statement

1. **CQS Deadlock** — Frozen/shadowbanned avatars cannot get CQS checks because batch tasks skip them, but CQS improvement is the signal needed to evaluate recovery.
2. **Posting Infrastructure Complexity** — Current approach requires residential proxies ($50-200/mo), Reddit OAuth approval (pending months), per-account API credentials, IP subnet consistency checks.
3. **Executor Friction** — 8-step manual workflow (email → open Reddit → find thread → copy text → paste → post → copy permalink → submit) causes delays and task drops.
4. **Health Monitoring Gaps** — Frozen avatars are excluded from all diagnostic batch tasks, making automated recovery detection impossible.

## Glossary

| Term | Definition |
|------|-----------|
| Executor | Person who owns/operates a Reddit avatar account. Posts content on behalf of the system. |
| Extension | Chrome Manifest V3 browser extension installed on executor's machine |
| System action | Automated action initiated by RAMP (CQS check, health probe). Does not count toward posting limits. |
| Content action | Comment/post action that counts toward daily posting limits and requires executor awareness. |
| State transition | Change in avatar status (frozen→active, cqs_level change). Requires validation. |
| Execution lease | Time-limited lock on a task to prevent duplicate execution. |

## Requirements

### R1 — Extension-Backend Communication

- R1.1: Extension connects to RAMP backend via authenticated HTTPS polling (every 30-60s when browser active). Upgrade path: long-poll or SSE for reduced latency (Phase 2).
- R1.2: Extension authenticates using executor JWT token (configured during onboarding).
- R1.3: Extension reports its online/offline status to RAMP (heartbeat every 60s).
- R1.4: Extension pulls pending tasks from `GET /api/extension/tasks` endpoint.
- R1.5: Extension pushes results to `POST /api/extension/report` endpoint.
- R1.6: Extension works behind NAT/firewall without inbound connections.
- R1.7: Communication encrypted via TLS (HTTPS only).
- R1.8: Extension handles network disconnections gracefully (queue results locally, retry on reconnect with exponential backoff).

### R2 — CQS Auto-Check (System Action)

- R2.1: Extension posts "What is my CQS?" in r/WhatIsMyCQS when RAMP sends a `cqs_check` task.
- R2.2: CQS posts happen in background tab (system action, does not require executor approval).
- R2.3: Extension waits up to 60s for AutoModerator reply, then reads and reports CQS level back.
- R2.4: If no reply within 60s, reports "pending" — RAMP's existing batch (06:30) will read it later.
- R2.5: CQS check tasks work regardless of avatar's frozen/health status.
- R2.6: Extension verifies Reddit session is active before attempting post (reports auth_expired if not).
- R2.7: CQS actions are NOT subject to content posting rate limits (R8). They are system diagnostics.

### R3 — Comment Posting (Content Action)

- R3.1: Extension receives `post_comment` tasks containing: thread_url, comment_text, reply_to (optional for nested replies).
- R3.2: Extension navigates to thread_url, locates comment box, inserts text, submits via the authenticated browser session.
- R3.3: After successful post, extension extracts the new comment's permalink and reddit_comment_id.
- R3.4: Extension reports back: {status: "posted", permalink, comment_id, posted_at, idempotency_key}.
- R3.5: If thread is locked/archived/removed, extension detects this and reports {status: "blocked", reason: "thread_locked"}.
- R3.6: Extension respects timing from task (holds until `scheduled_at`).
- R3.7: Extension has configurable auto-mode (execute automatically) vs manual-mode (show in queue, wait for executor click).
- R3.8: Content actions are subject to all rate limits defined in R8.

### R4 — Health Monitoring (System Action, Best-Effort)

- R4.1: Extension periodically checks avatar's profile page for ban indicators (notification bar, account standing).
- R4.2: Extension monitors Reddit notification inbox for removal notices.
- R4.3: Extension reports health signals to RAMP: {type: "health_signal", signal: "comment_removed|ban_notice|profile_restricted"}.
- R4.4: Health monitoring is passive — runs only when browser is open, no forced activity.
- R4.5: Health signals are best-effort heuristics, NOT authoritative state-change triggers. They feed into the state transition layer (R10) as input signals only.

### R5 — Karma Reporting (System Action)

- R5.1: Extension reads karma values from Reddit profile page (comment_karma, link_karma).
- R5.2: Extension reports karma snapshot to RAMP on each health check cycle (piggyback, no extra navigation).
- R5.3: Extension can read per-subreddit karma breakdown if available from profile page.

### R6 — Executor UX (MVP Scope)

MVP (Phase 1):
- R6.1: Extension popup shows pending task queue with count badge on icon.
- R6.2: Each task shows: subreddit, thread title (truncated), comment preview, scheduled time.
- R6.3: Executor can approve/reject individual tasks from popup.
- R6.4: Extension shows connection status (connected/disconnected/auth expired).

Phase 2 additions:
- R6.5: Auto/Manual mode toggle.
- R6.6: History of completed tasks (last 20).
- R6.7: "Pause" button — stops all content posting but keeps system actions (CQS, health).
- R6.8: Onboarding wizard (enter RAMP URL + token → validate → ready).

### R7 — Multi-Account Support

- R7.1: One executor can manage multiple Reddit accounts (via Chrome profiles).
- R7.2: Extension detects which Reddit account is currently logged in and matches to RAMP avatar.
- R7.3: Tasks are filtered to only show/execute tasks for the currently active Reddit account.
- R7.4: Extension warns if wrong account is active for a pending task.

### R8 — Safety & Rate Limits

Content action limits (R3 — comment posting):
- R8.1: Extension enforces daily posting cap per avatar (from RAMP config, not hardcoded).
- R8.2: Extension enforces minimum interval between content posts (from RAMP config, default 3 min).
- R8.3: Auto-mode content posting only during configured active hours (default 08:00-22:00 executor local time).
- R8.4: Extension never posts more than 1 content comment per 3 minutes (absolute floor).

System action limits (R2, R4, R5 — CQS, health, karma):
- R8.5: System actions have separate rate limits: max 1 CQS check per hour, health probe max 1 per 30 min.
- R8.6: System actions are NOT blocked by content posting limits and vice versa.
- R8.7: System actions run in any mode (auto/manual/paused) — "Pause" only stops content actions.

General safety:
- R8.8: Extension does NOT post if Reddit session is expired/logged out — reports auth_expired.
- R8.9: Extension does NOT transmit Reddit cookies, passwords, or session tokens to RAMP backend.
- R8.10: Extension has kill switch — RAMP can send "pause_all" command to stop ALL actions instantly.
- R8.11: Extension operates in read-only mode for monitoring; write actions only on explicit tasks from RAMP.

### R9 — RAMP Backend Extension API

- R9.1: `GET /api/extension/tasks` — returns pending tasks for authenticated executor. Supports idempotency_key per task.
- R9.2: `POST /api/extension/report` — receives task results. Requires idempotency_key to prevent duplicate processing.
- R9.3: `POST /api/extension/heartbeat` — extension online status + active Reddit account.
- R9.4: `POST /api/extension/register` — initial extension registration with executor token.
- R9.5: Extension tasks coexist with email tasks. Extension is preferred channel when online.
- R9.6: If extension goes offline for >30 min, RAMP falls back to email delivery.
- R9.7: Extension-posted comments automatically update draft status + EPG slot (no reconciliation needed).
- R9.8: Task integrity: each task includes HMAC signature. Extension verifies before execution.
- R9.9: Execution lease: task has `lease_expires_at`. If not reported by deadline, task is released for re-delivery.
- R9.10: Duplicate prevention: backend rejects reports with previously-seen idempotency_key (returns 200 OK, no re-processing).

### R10 — State Transition Layer (Recovery & Status Changes)

Architecture: measurement and state transitions are SEPARATED.

**Measurement layer** (extension reports signals):
- R10.1: Extension reports CQS level from bot reply (raw measurement).
- R10.2: Extension reports health observations (best-effort heuristics, not authoritative).
- R10.3: Extension reports karma values (factual, from profile page).

**State transition layer** (RAMP backend decides):
- R10.4: CQS level change is recorded immediately (factual — bot said "LOW").
- R10.5: Avatar state transitions (frozen→active, health_status changes) require EITHER:
  - (a) Operator approval via admin UI notification, OR
  - (b) Two independent confirming signals (e.g., CQS improved + PRAW submission_visibility_probe passes)
- R10.6: Single extension health signal alone NEVER triggers auto-unfreeze. It only creates a "recovery candidate" flag for operator review or triggers secondary PRAW verification.
- R10.7: Operator gets notification: "Avatar X shows recovery signals — CQS improved to LOW. Verify and unfreeze?"
- R10.8: Activity event `cqs_recovery_candidate` emitted (different from `cqs_recovery_confirmed`). Confirmed only after validation.

**Self-healing automation (Phase 3, requires dual confirmation):**
- R10.9: Auto-unfreeze allowed ONLY when: CQS improved above "lowest" AND independent PRAW probe confirms submission visible in subreddit feed. Both signals required.
- R10.10: If auto-unfreeze fires, operator is notified post-factum with full evidence chain.

## Non-Functional Requirements

### NF1 — Performance

- Extension adds < 50ms latency to Reddit page load.
- Background tasks (CQS check, health probe) complete within 90s.
- Extension memory usage < 50MB.
- Polling interval: 30s default (configurable). Upgrade path to long-poll/SSE documented.

### NF2 — Privacy & Security

- Zero credential exfiltration — extension never reads or sends passwords/tokens/cookies to RAMP.
- All RAMP communication is HTTPS.
- Extension source code is open for executor inspection (transparency).
- Extension permissions are minimal: Reddit domain only + RAMP API domain.
- Task payloads signed with HMAC (backend secret). Extension verifies integrity before execution.

### NF3 — Reliability

- Extension works across Chrome updates (Manifest V3 compliant).
- Extension recovers from browser restart (persists pending tasks in chrome.storage.local).
- Extension handles Reddit UI changes gracefully (selector fallbacks + error reporting).
- Idempotent execution: re-delivery of same task (same idempotency_key) does not cause duplicate posts.

### NF4 — Observability

- Extension logs all actions locally (viewable in popup "History" tab).
- Extension reports errors/warnings to RAMP for operator visibility.
- RAMP admin UI shows per-executor extension status (online/offline/last_seen/version).

## Out of Scope (MVP)

- Firefox extension (Chrome first, Firefox Phase 2)
- Post creation (only comments in MVP)
- Upvote/downvote coordination
- Content editing after posting
- Mobile browser support
- Automated Chrome profile switching (manual in MVP)
- Auto-mode for content posting (manual approve in MVP, auto-mode Phase 2)
- Long-poll/SSE communication (polling in MVP, upgrade path documented)
- Auto-unfreeze without operator approval (Phase 3, requires dual confirmation)

## Dependencies

- RAMP backend extension API (R9)
- Executor onboarding flow update (token generation + install instructions)
- Chrome Web Store developer account ($5 one-time)
- Reddit DOM structure stability (mitigation: multiple selector strategies + version-pinned selectors)

## Success Metrics

- CQS check latency: from 7-10 days (email loop) → < 24 hours (extension auto-check)
- Executor posting friction: from 8 manual steps → 1 click (manual mode MVP) → 0 steps (auto mode Phase 2)
- Proxy cost: from $50-200/mo → $0
- Shadowban recovery detection: from never (deadlock) → < 7 days (CQS check cycle)
- Task completion rate: from ~60% (email tasks dropped/ignored) → >90% (extension queue visible)
