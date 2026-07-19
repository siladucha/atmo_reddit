# End-to-End Pipeline — Architecture Overview

## Last Updated: July 2, 2026

## Core Loop

```
SCRAPE → SCORE → GENERATE → REVIEW → EXECUTE → MEASURE → LEARN
```

Each stage operates on specific schedules, with independent failure modes and safety gates between them.

---

## 1. SCRAPE (Content Collection)

**Schedule:** `queue_tick` every 60s (gated by DB scrape interval), hobby scraping 07:45 + 13:45

**Dual pipeline:**

| Pipeline | Source | Storage | Frequency |
|----------|--------|---------|-----------|
| Professional | PRAW → client subreddits | `reddit_threads` | Per DB interval (typically 6h) |
| Hobby | PRAW → avatar hobby_subreddits | `hobby_subreddits` | 2×/day (07:45, 13:45) |

**Filters applied at scrape:**
- Skip locked/removed/archived threads
- Link/video/image post filter (skip external URLs in both pipelines)
- 7-day freshness filter on hobby posts (added June 28)

**Output:** `RedditThread` or `HobbySubreddit` records with `status="new"`

---

## 2. SCORE (Relevance Assessment)

**Schedule:** 08:00, 14:00 — `run_full_pipeline_all_clients`

**Method:** Smart Scoring (budget-aware, 90% cost reduction vs naive)
- Formula: `remaining_budget × 3` threads per avatar (HARD_CAP=15)
- Model: Gemini Flash (~4K input, ~200 output tokens)
- Output: `ThreadScore` with tag: `engage` / `monitor` / `skip`
- Per-client scoring (same thread → different scores per client's keywords/strategy)

**Phase gating:** Only Phase 2+ avatars enter professional scoring. Phase 1 = hobby only (no scoring).

**Hobby pipeline:** No scoring — all posts with `status="new"` + `ai_comment=None` + `post_body > 20 chars` are eligible.

---

## 3. GENERATE (Comment Creation)

**Schedule:** Immediately after scoring; EPG build 08:15 (full daily budget), enforcement 09:00 (guarantee minimum), top-up 14:15 (fills remaining for underfilled avatars)

**Pre-generation gate:** Fitness Gate (6 checks per avatar×subreddit pair)
1. Subreddit ban → hard block
2. Profile exists? → fail-open if missing
3. min_karma (extracted rule vs actual)
4. min_account_age
5. posting_frequency_limit
6. Extreme aggressiveness + low karma → block
7. Dangerous hours + low karma → block

**Generation process:**
- Model: Claude Sonnet (~12K input, ~200 output tokens)
- Input: thread context + avatar persona + strategy + correction patterns (few-shot from self-learning loop)
- Placement intelligence: AI decides WHERE in thread to reply (depth + reasoning)
- Output: `CommentDraft` (status=`pending`) + `EPGSlot` (status=`generated`)

**EPG Portfolio Manager** allocates budget:
- Phase 0: 1 comment/day (safe subs only)
- Phase 1: 2-3/day (hobby only)
- Phase 2: 7/day (professional + hobby)
- Phase 3: 12-15/day (professional + hobby + brand)
- CQS=lowest: 0 (full stop)

---

## 4. REVIEW (Human Approval Gate — P5)

**Who:** Operator, client manager, or auto-approve policy

**Four paths:**
1. **Manual review (Admin UI)** — draft appears in Review Queue, human approve/reject/edit
2. **Extension review (July 7, 2026)** — draft appears in extension popup "📝 Review Drafts" section, executor approve/reject
3. **Auto-approve (avatar-level)** — `avatar.auto_approve_drafts=true`
4. **Auto-approve (client-level)** — `client.autopilot_enabled=true` (overrides avatar)

**Notification on pending drafts (when auto-approve=false):**
- Portal bell (SSE) — "New draft ready for review" with link to review page
- Extension badge — pending count shown on popup icon
- *(Planned: Telegram inline buttons, email digest)*

**On edit:** Learning service captures changes → extracts correction patterns → improves future generation

**Safety:** Auto-approve is explicit configured policy (admin sets it), not bypass. Extension review = explicit human tap. P5 satisfied.

---

## 5. EXECUTE (Posting — P11)

**Three channels (priority order):**

### 5a. Browser Extension (primary when online)
- Polling every 30s (`/api/extension/tasks`)
- Executor approves tasks in popup morning batch ("Approve All")
- Extension auto-executes at scheduled times: navigate → chrome.debugger click composer → insert text → chrome.debugger click submit → verify → report
- **chrome.debugger API**: CDP `Input.dispatchMouseEvent` for trusted clicks (bypasses `isTrusted` checks on Shadow DOM)
- Audit: state machine events emitted to backend at every transition
- **Delivery channel:** Set per-avatar in admin (email/extension/both). When `delivery_channel="extension"`, tasks are created with `task_lifecycle_status="CREATED"` for immediate polling.
- Status: v2 deployed July 2, 2026. Full auto-execution after approval.

### 5b. Email Task Delivery (fallback when extension offline)
- `dispatch_due_email_tasks` every 5 min
- Dispatches ~30 min before scheduled slot time
- Pre-dispatch liveness check (thread not locked/removed)
- **Executor email must be verified** — task creation blocked if `executor_email_verified=false` (July 4, 2026)
- Executor posts manually, submits permalink via action link
- Quiet hours gate: 23:00-07:00 Israel time blocked

### 5c. Automated API Posting (deferred)
- `execute_pending_posts` every 5 min — PRAW via proxy
- 9 safety gates (kill switch → mode → frozen → health → phase 0 → daily cap → proxy → user-agent → subnet)
- Currently: `POSTING_DISABLED=false` but `auto_posting_enabled=false` (no proxies purchased)

**Routing logic:** Extension online + correct account → extension. Offline >30 min → email fallback.

---

## 6. MEASURE (Outcome Tracking)

**Schedule:** `snapshot_comment_outcomes` every 4h, karma tracking every 4h

**Metrics captured:**
- KarmaSnapshot at 4h / 24h / 48h / 7d post-posting
- Deletion detection (auto-marks `is_deleted`, emits activity event)
- Reply count (thread depth — Tier-2 signal for EPG model)
- Engagement velocity (karma growth curves)

**Draft Reconciliation** (every 4h inside karma_tracking):
- Auto-links approved drafts to Reddit comments posted outside system
- 3-pass matching: exact body (98%) → fuzzy overlap ≥85% → thread+timing (75%)
- Zero extra API calls (reuses redditor object)

---

## 7. LEARN (Feedback & Adaptation)

**Schedule:** 02:00 daily — `run_feedback_loop_all`

**Three learning loops:**

1. **EPG Model Correction** — karma outcomes → hypothesis updates → subreddit adjustments → budget reallocation
2. **Self-Learning Loop** — human edit records → correction patterns → few-shot injection into generation prompts
3. **Phase Evaluation** (06:00 daily) — promote/demote avatars based on:
   - Survival rate (≥70% for promotion, min 5 posted sample)
   - Karma velocity
   - CQS level
   - Shadowban status → demote to Phase 0 (not freeze!)

---

## Parallel Systems (Independent of Core Loop)

| System | Schedule | Purpose |
|--------|----------|---------|
| Health Check | 07:30, 13:30 | Shadowban/suspension detection (2-layer: global + per-sub) |
| CQS Check | 06:30 (batch read) + 07:00 (task generation) | Contributor Quality Score monitoring |
| GEO/AEO Monitoring | Daily 09:30 (~1/7 prompts/day) | Brand visibility across Perplexity + Claude + ChatGPT (smoothed daily rotation via UUID.int % 7) |
| Discovery Engine | Sun 04:00 | Automated market/niche research |
| Subreddit Risk Profiles | Sun 05:00-05:30 | Rule extraction + moderation profiling + risk scoring |
| Emotional Profiles | Sun 04:30 | Subreddit tone analysis + avatar compatibility |
| Subreddit Ban Probe | Sun 03:45 | Weekly per-sub ban detection |
| Performance Metrics | 01:00 daily | Daily aggregation per avatar |
| Decision Record Archival | 01:30 daily | Prune >90 day records |
| **Zone Evaluation** | 06:00 daily (with phase eval) | Risk-aware zone graduation/demotion for Phase 0-1 avatars |
| Trial Negative Signals | Every 4h at :30 | Detect trial drop-off signals |
| Trial Classification | 02:30 daily | Classify expired trials |
| Avatar Invariant Check | 02:30 daily | Verify active clients have avatars |
| Onboarding Stall | Hourly at :45 | Detect stalled onboardings |
| BYOA Stale Drafts | Every 10 min | Fail stuck avatar provisioning |
| Extension Lease Expiry | Every 5 min | Expire stale extension tasks |
| Weekly Reports | Mon 08:00 | Generate intelligence reports for all clients |
| **Client Email Notifications** | Mon 08:00 + Sun 19:00 + on-event | Visibility digest (client), phase milestone (client), health alert (client), system health (owner), business summary (partner) |
| **A/B Test Metrics** | Mon 02:30 | Collect weekly experiment metrics + generate statistical reports |
| **A/B Test Duration** | Daily 07:00 | Alert when experiments reach planned duration |
| **Provider Budget Check** | Every 4h at :45 | Check provider spend vs budget → Telegram + email + bell alert at 70%/95% |
| **LLM Quality Check** | Every 4h at :20 | Detect model degradation (success rate drop, latency spike, fallback rate, empty responses) vs 7-day baseline |
| **EPG Daily Minimum Enforcement** | Daily 09:00 | Guarantee every active avatar has ≥1 EPG slot today; retry with archive fallback if 0 |

---

## Phase-Aware Content Routing

| Phase | Professional | Hobby | Brand | Daily Budget |
|-------|-------------|-------|-------|-------------|
| 0 (Incubation) | ❌ | Safe subs only | ❌ | 1 |
| 1 | ❌ | ✅ | ❌ | 2-3 |
| 2 | ✅ | ✅ | ❌ | 7 |
| 3 | ✅ | ✅ | ✅ | 12-15 |
| Mentor (pool) | ❌ | ❌ | ❌ | 0 (excluded from pipeline) |

### Risk-Aware Zone Routing (Phase 0-1, July 2 2026)

When `activation_routing_enabled=true`, Phase 0-1 subreddit selection uses zone-based routing instead of static `hobby_subreddits`:

| Zone | Risk Score | Phase 0 | Phase 1 | Graduation Criteria |
|------|-----------|---------|---------|-------------------|
| Safe | 0-25 | 1/day | 1/day | karma≥10, CQS≠lowest, 3 posted, 0 deleted, survival≥90% |
| Bridge | 26-50 | 0/day | 3/day | karma≥15 in 2+ bridge subs, total≥50, survival≥85% |
| Target | 51-80 | — | — | Phase 2+ only (professional pipeline takes over) |

**Flow:** `ActivationRouter.plan_route()` → `avatar.activation_route` JSONB → `scan_opportunities()` reads zone subs → `ZoneEvaluator` checks graduation daily at 06:00.

**Fallback:** No route = legacy `hobby_subreddits`. Feature-flagged, fail-open.

---

## Safety Architecture (Cross-Cutting)

**Kill Switches:**
- `pipeline_enabled` — stops scoring + generation
- `generation_enabled` — stops generation only
- `scrape_enabled` — stops scraping
- `auto_posting_enabled` — stops API posting
- `email_tasks_enabled` — stops email dispatch
- `fitness_gate_enabled` — disables pre-generation gate
- `activation_routing_enabled` — disables zone routing (legacy hobby_subs used)
- `POSTING_DISABLED` — env-level, cannot toggle from admin

**Human Gates:**
- P5: Content approval (draft → posted) — always human decision (auto-approve = policy, not bypass)
- P11: Execution approval (extension popup Approve button)

**Structural Safety:**
- P4: Phase eligibility (no brand content in Phase 1/2) — enforced at generation prompt assembly + safety_blocks.py
- P7: Client isolation (query_scope.py + isolation.py runtime assertions)
- P9: Diagnostic independence (diagnostics never gated by the condition they diagnose)

---

## Failure Cascade Model

```
Scraping stops → No fresh threads (MAX_AGE_HOURS=48)
    → Scoring returns 0 engage → Generation produces 0 drafts
    → EPG has 0 opportunities → 0 slots → 0 emails
    → Executor idle → Client gets zero value
    → SILENT (no component complains about zero input)
```

**Mitigated (July 2, 2026):** External watchdog on host (systemd, every 30s) detects:
- Container death (Beat, Workers, App, PG, Redis) → auto-restart + alert
- /health endpoint failure → app restart
- Disk >90% → alert

**Beat memory leak RESOLVED (July 7, 2026):** Beat now uses lightweight `beat_app.py` (no SQLAlchemy/PRAW/LiteLLM imports). Stable ~25 MB vs previous 225 MB leak that crashed every 3-6h. Deploy grace period prevents false watchdog alerts.

**RTO tested:** ≤60 seconds for full cascade failure (all 5 containers killed → all recovered).

**Known remaining gap (T-2026-06-28-006):** No pipeline-alive *semantic* signal. Zero output treated as "nothing to do" not "something is wrong." Watchdog ensures containers are RUNNING, but cannot detect "Beat is alive but schedule empty" or "scraping runs but returns 0 threads."

**Future mitigation:** Ops Agent Phase 2 — "expected output > 0" assertions at each pipeline boundary (signal_collector already has this data).

---

## Data Flow Diagram

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Reddit API │────▶│  SCRAPE     │────▶│  SCORE      │
│  (PRAW)     │     │  reddit_    │     │  Gemini     │
│             │     │  threads +  │     │  Flash      │
│             │     │  hobby_subs │     │             │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │ engage tagged
                                               ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  LEARN      │◀────│  MEASURE    │◀────│  EXECUTE    │
│  Feedback   │     │  Karma      │     │  Extension/ │
│  Loop       │     │  Snapshots  │     │  Email/API  │
│             │     │  Deletion   │     │             │
└──────┬──────┘     └─────────────┘     └──────▲──────┘
       │                                       │ approved
       │ correction                            │
       │ patterns                        ┌─────┴──────┐
       ▼                                 │  REVIEW    │
┌─────────────┐                          │  Human /   │
│  GENERATE   │─────────────────────────▶│  Auto-     │
│  Claude     │    CommentDraft          │  approve   │
│  Sonnet     │    (pending)             │            │
└─────────────┘                          └────────────┘
```
