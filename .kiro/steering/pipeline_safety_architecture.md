---
inclusion: fileMatch
fileMatchPattern: "**/phase*,**/safety*,**/epg*,**/portfolio_manager*,**/opportunity_engine*,**/ai_pipeline*,**/posting_safety*,**/smart_scoring*,**/hobby*"
---

# Pipeline Safety Architecture — Phase Demotion & Thread Safety

## Dual Pipeline Architecture

The system has TWO independent content pipelines. They do NOT share storage:

| Pipeline | Scraping Source | Storage Table | Scoring | Generation Task |
|----------|----------------|---------------|---------|-----------------|
| **Professional** | `queue_tick` → `subreddits` table | `reddit_threads` | `smart_score_for_avatar` → `thread_scores` | `generate_comments` |
| **Hobby** | `scrape_hobby_subreddits` → PRAW direct | `hobby_subreddits` | None (all posts eligible) | `generate_hobby_comments` |

### Critical Implication

Smart Scoring (`get_candidate_threads`) queries **only `reddit_threads`**. Hobby subreddits configured on avatars (`avatar.hobby_subreddits`) are NOT in the `subreddits` table and NOT in `reddit_threads`.

**Phase 1 avatars** in Smart Scoring return `hobby_subs` from `get_avatar_available_subreddit_names` → search `reddit_threads` → find 0 results → `status=no_threads`.

This is by design: Phase 1 professional generation is intentionally disabled. Hobby generation still works via the separate hobby pipeline (1-3 comments/day from `generate_hobby_comments`).

### Display Unification (Fixed June 28)

Despite separate storage, hobby drafts now have **structural parity** with professional drafts for display:
- `CommentDraft.hobby_post_id` has FK → `hobby_subreddits.id` (ondelete=SET NULL)
- `CommentDraft.hobby_post` relationship (lazy="joined") — auto-loaded like `draft.thread`
- Shared `HobbyThreadProxy` (`app/services/hobby_proxy.py`) makes `HobbySubreddit` look like `RedditThread` for templates
- Admin review queue, portal, avatar workflow — all resolve hobby context via relationship (no manual lookups needed)

**When an avatar is demoted Phase 2→1:** Professional generation drops to 0. Only hobby pipeline (1-3/day) continues. This is the expected safety behavior but can appear as "system broken" to business users.

---

## Phase Demotion System

### Phase State Machine (REDESIGNED — spec: phase-incubation-mentor-refactor)

```
Phase 0 (Incubation) → Phase 1 (Hobby) → Phase 2 (Professional) → Phase 3 (Brand)
     ▲                       │                    │                      │
     └───────────────────────┴────────────────────┴── demotion ──────────┘
```

**Mentor is NOT a phase.** Mentor = `avatar.pool == "mentor"` (pipeline exclusion flag).
Phase 0 = real phase for fresh/low-karma/recovering avatars. 1 comment/day, safe subs only.

### Demotion Targets (checked daily at 06:00 by `evaluate_all_avatar_phases`)

| Trigger | Threshold | Demotion Target |
|---------|-----------|-----------------|
| Shadowban detected | `is_shadowbanned = true` | → **Phase 0** (not freeze!) |
| CQS dropped to lowest | Phase 2+ | → **Phase 0** (not freeze!) |
| Low survival rate | <70% over 7-day window | → **Phase 0** |
| Karma drop | avg `reddit_score` < -2 over 14 days | → current - 1 |

### Key Change: Demotion Replaces Freeze

**Old behavior:** shadowban/CQS lowest → `is_frozen = true` → avatar exits all pipelines → deadlock (no monitoring, no recovery detection).

**New behavior:** shadowban/CQS lowest → demote to Phase 0 → avatar stays in pipeline (1/day, safe subs) → health checks continue → recovery auto-detected → graduation back to Phase 1.

**Freeze is reserved for:**
- Suspended (404/403 from Reddit — account deleted)
- Admin manual action
- Phase 0 timeout > 30 days without graduation (unrecoverable)

### Recovery in Phase 0

- Shadowbanned avatar generates 1 comment/day as **probe** (if karma appears → shadowban may be lifted)
- Health check detects shadowban clearance → `is_shadowbanned = false` → avatar graduates normally
- CQS improvement detected → activity event → avatar graduates normally
- No operator intervention needed for recovery

### Minimum Sample Size (ADDED June 22, 2026)

`_DEMOTION_MIN_SAMPLE_SIZE = 5` in `phase.py`. If fewer than 5 posted comments exist in the 7-day window, survival rate returns 1.0 (no demotion).

**Why:** With only 2-3 comments, a single moderator removal (common in r/sysadmin) was triggering demotion (1/2 = 50% < 70%). This is statistically unreliable.

### What Survival Rate Means

```
survival_rate = (total_posted - deleted) / total_posted
```

- `total_posted`: comments with status="posted" and `posted_at` within window
- `deleted`: subset where `is_deleted = true` (detected by `snapshot_comment_outcomes`)
- Window uses **UTC timestamps** — timezone matters for edge cases

---

## Thread Safety Filters (ADDED June 22, 2026)

### 1. Link/Video/Image Post Filter

In `smart_scoring.py`, `ai_pipeline.py` (professional), AND `opportunity_engine.py` + `ai_pipeline.py` (hobby):
```python
# Professional pipeline (RedditThread):
sa.or_(
    RedditThread.url.is_(None),
    RedditThread.url == "",
    RedditThread.url.like("%reddit.com%"),
)

# Hobby pipeline (HobbySubreddit) — ADDED June 26, 2026:
or_(
    HobbySubreddit.url.is_(None),
    HobbySubreddit.url == "",
    HobbySubreddit.url.like("%reddit.com%"),
)
```

Skips threads/posts with external URLs (imgur, i.redd.it, youtube, etc.) — these are link/media posts where LLM cannot produce meaningful text-only replies.

**June 26 fix:** Previously this filter was ONLY in the professional pipeline. The hobby pipeline (`scan_opportunities` Source 2 + `generate_hobby_comments`) had no url filter — image posts with body text > 20 chars passed through (e.g., r/GYM progress photos with diet description). Now filtered in both pipelines.

### 2. Hot Thread Filter

In `smart_scoring.py` (`get_candidate_threads`):
- Thread with `ups >= 200` = "hot"
- If avatar's `SubredditKarma.comment_karma` < 100 in that subreddit → skip

**Why:** Strictly moderated subs (r/sysadmin, r/networking, r/devops) aggressively remove comments from low-karma accounts on viral/trending posts. This is the #1 cause of moderator removals.

### 3. Subreddit Risk Profile & Fitness Gate (ADDED June 23, 2026)

Full subreddit intelligence pipeline: rule extraction → moderation profiling → risk scoring → pre-generation fitness gate.

#### Components

| Service | Purpose | Output |
|---------|---------|--------|
| `rule_extractor.py` | PRAW sidebar/wiki fetch → Gemini Flash structured extraction | `extracted_rules` JSONB (min_karma, min_age, frequency_limit, banned_topics, etc.) |
| `moderation_profiler.py` | 30-day deletion aggregation from `SubredditDailyStats` | `moderation_profile` JSONB (aggressiveness, dangerous_hours, removal_patterns) |
| `risk_scorer.py` | Weighted formula → composite score 0-100 | `risk_score`, `risk_score_history` FIFO (12 weeks), `is_high_risk` flag |
| `fitness_gate.py` | Pre-generation safety gate (6 checks) | Pass/Block decision per avatar×subreddit pair |

#### Fitness Gate Checks (in order)

1. **Subreddit ban** — hard block if avatar banned from this sub (per-subreddit ban detection)
2. **Profile exists?** — fail-open if no profile (returns score=50, allows generation)
3. **min_karma** — extracted rule vs `SubredditKarma.comment_karma`
4. **min_account_age** — extracted rule vs `avatar.reddit_account_created`
5. **posting_frequency_limit** — extracted rule vs recent comment count in this sub
6. **Extreme aggressiveness + <50 karma** — block (sub too dangerous for low-karma avatar)
7. **Dangerous hours + <200 karma** — block during hours with >2x avg deletion rate

#### Schedule — WEEKLY (Not Daily)

| Time | Task | Purpose |
|------|------|---------|
| 05:00 Sun | `extract_subreddit_rules_batch` | PRAW sidebar/wiki → Gemini Flash → structured rules |
| 05:15 Sun | `compute_moderation_profiles_batch` | 30-day deletion aggregation, dangerous hours, aggressiveness |
| 05:30 Sun | `compute_risk_scores_batch` | Weighted score computation + high_risk flags + spike detection |

**Why weekly, not daily:**
- Subreddit rules change rarely (month/quarter cadence)
- Moderation profile uses 30-day window — daily refresh adds ~1 day of data, negligible change
- PRAW API calls + Gemini Flash = resource consumption (Reddit rate limits + LLM cost)
- Historical FIFO window is 12 weeks — weekly granularity is appropriate

**Exception:** `fitness_gate.py` runs in real-time (every generation attempt) using CACHED data from the weekly batch. No staleness issue — the gate reads existing `SubredditRiskProfile` rows, doesn't trigger fresh extraction.

#### Data Model

- **`SubredditRiskProfile`** — 1:1 with `Subreddit` (FK, ondelete=CASCADE)
  - `risk_score` (0-100, CHECK constraint)
  - `extracted_rules` JSONB (structured rules array)
  - `moderation_profile` JSONB (aggressiveness, patterns, hours)
  - `dangerous_hours` (array of hours with >2x avg deletion rate)
  - `recommendations` (AI-generated text)
  - `risk_score_history` JSONB (FIFO, 12 weekly entries)
  - `extraction_status` (success/no_content/failed/pending)
  - `confidence_level` (high/medium/low)

- **`SubredditDailyStats`** — daily posting stats per subreddit (UNIQUE on subreddit_id+date)
  - `posted_count`, `deleted_count`, `hour_distribution` JSONB
  - Populated by `snapshot_comment_outcomes` (writes deletion data)

#### Pipeline Integration Point

```
Smart Scoring → candidate threads selected
                     ↓
              Fitness Gate (per avatar × subreddit)
                     ↓
              Pass → generation proceeds
              Block → budget decremented, thread skipped, activity event emitted
```

The gate runs BETWEEN scoring and generation in the professional pipeline. Budget is decremented for blocked threads (avatar won't get replacement thread — budget loss is the safety cost).

#### UI Access

- **Admin → Subreddits** (`/admin/subreddits`) — color-coded risk_score badge next to each sub name. Click → full risk profile page.
- **Admin → Subreddit Risk Profile** (`/admin/subreddits/{id}/risk-profile`) — full page: header, extracted rules, moderation insights, dangerous hours, avatar fitness table, 12-week trend chart (HTMX lazy), 30-day daily history (HTMX lazy).
- **Portal → Subreddits** (`/clients/{id}/subreddits`) — same badge. Click → client-scoped risk profile page.
- **Portal → Risk Profile** (`/portal/subreddits/{id}/risk-profile`) — client-scoped: daily stats filtered to client's avatars only.

**Color coding:** ≤30 = green, 31-60 = yellow, 61-80 = orange, >80 = red.

**Kill switch:** `fitness_gate_enabled` system setting (default: true). When disabled, gate returns pass for all.

#### Why Badges May Not Appear

If risk_score is NULL (never computed), the badge is hidden (`{% if item.risk_score is not none %}`). This happens when:
- Weekly batch hasn't run yet (new subreddit added mid-week)
- Migration `srp01` not applied
- Subreddit has <5 posted comments (insufficient data → profile exists but risk_score may be NULL)

**Manual trigger:** Admin can trigger batch via Celery CLI or future "Refresh Now" button.

#### Known Subreddit-Specific Patterns (learned June 2026)

r/sysadmin moderation:
- New/low-karma accounts on popular posts get removed
- "my client" / consultant language → flagged as vendor
- Pile-on comments on viral threads → removed as low-effort
- Generic "hot takes" that repeat what others already said → removed

---

## Monitoring & Ops Checklist

When a client reports "no comments generating":

1. Check `plan_type` (not expired trial)
2. Check avatars not all frozen/banned
3. Check kill switches enabled
4. Check Activity Feed for `score` events (look for "0 engage")
5. **Check avatar phases** — if recently demoted to Phase 1, that's the cause
6. Check `auto_downgrade` events in activity feed with `trigger_reason`

### Quick Fix for False Demotion

Admin → Avatar → Edit → Set `warming_phase = 2` (or appropriate phase). Next pipeline run will resume professional generation.

---

## EPG Portfolio Manager — Phase-Aware Opportunity Sourcing (FIXED June 24, 2026)

The Portfolio Manager (`build_portfolio`) uses `scan_opportunities()` which has two sources:

| Source | When Used | Storage | What It Returns |
|--------|-----------|---------|-----------------|
| **Source 1** (Professional) | Phase 2+ only | `reddit_threads` + `thread_scores` | Scored threads tagged "engage"/"monitor" |
| **Source 2** (Hobby) | Phase 1+ | `hobby_subreddits` | Fresh hobby posts (`status="new"`, `ai_comment=None`, `post_body` non-empty) |

### Key Design Decisions (June 24 fixes):

1. **Source 1 gated to Phase 2+** — Phase 1 avatars only get hobby posts. Previously Source 1 filled the 50-opportunity cap with professional threads that were then filtered out, leaving 0 hobby opportunities.
2. **`warm` pool included in Smart Scoring** — `smart_scoring.py` allows `("b2b", "b2c", "warm")`. Previously `warm` was excluded.
3. **Case-insensitive subreddit matching** — `func.lower(HobbySubreddit.subreddit).in_(hobby_sub_names)`.
4. **Dict-format hobby_subreddits supported** — avatars may have `[{"fullname": "...", "subreddit": "Biohackers"}]` format.
5. **`status == "new"` filter** — hobby posts must have `status="new"` (not NULL). Matches legacy EPG.
6. **`avatar_username` filter** — ensures one avatar doesn't pick up another's scraped posts.

### Troubleshooting: "Zero opportunities" for Phase 1 avatar

1. Check `hobby_subreddits` on avatar is non-empty
2. Check `hobby_subreddits` table has posts with `status="new"` for that `avatar_username`
3. Check posts have `post_body` > 20 chars (image-only posts skipped at generation)
4. Check `ai_comment` is NULL (already-generated posts excluded)
5. Check client's `max_comments_per_month` isn't exhausted

---


---

## EPG Scheduling Architecture (Redesigned July 6, 2026; Enforcement added July 10, 2026)

### Design: Build + Enforce + Top-Up

EPG runs as three complementary tasks:

| Time | Task | Purpose |
|------|------|---------|
| 08:15 | `build_and_generate_epg_all_avatars` | Full daily EPG build — allocates entire budget at once |
| 09:00 | `ensure_daily_epg_minimum` | **Enforcement** — guarantees every active avatar has ≥1 slot. Force scrape + rebuild for starving avatars. |
| 14:15 | `epg_topup_underfilled_avatars` | Top-up — fills remaining budget for avatars that got fewer slots in morning |

### How It Works

**Morning (08:15):** Full budget allocated. Phase 2 avatar gets up to 9 slots (7 comments + 2 posts). If only 5 opportunities exist → 5 slots created, 4 unfilled.

**Afternoon (14:15):** Top-up task checks each avatar:
1. Calculates `daily_limit - active_slots_today` (active = planned/generated/approved/posted)
2. If remaining > 0 → calls `build_portfolio(topup_remaining=N)` with capped budget
3. If remaining = 0 → skips (budget fully filled in morning)

**Key rule:** Skipped slots do NOT free up budget. If morning had 7 slots and 3 were skipped (no LLM response), afternoon sees 4 active + 3 skipped = only fills `limit - 4` more. Skipped = burned opportunity, not recyclable budget.

### Dedup Guard (Morning Build Only)

The dedup guard protects the morning build from duplicate runs (deploy restarts, manual triggers):

```python
# Only applies to morning build (topup bypasses dedup via topup_remaining param)
if existing_active_count > 0: return "already_planned"  # Successful build exists
if build_attempts >= 2: return "already_planned"         # Max retries exhausted
```

Top-up task bypasses dedup because it explicitly calculates remaining budget — it cannot over-allocate by design.

### Invariants

1. **Max slots per avatar per day = budget** (Phase 1=3, Phase 2=9, Phase 3=15). Enforced by: morning build uses full budget, afternoon uses only `limit - already_created`.
2. **Successful morning build + no afternoon gap = no afternoon run.** Top-up only fires when there's unfilled capacity.
3. **Top-up never exceeds remaining.** `build_portfolio(topup_remaining=N)` caps budget internally.
4. **Concurrent protection.** Both tasks use `DistributedLock(epg_build_lock:{avatar_id})`.

### Previous Design (Before July 6, 2026)

Two identical `build_and_generate_epg_all_avatars` runs (08:15 + 14:15). Dedup guard blocked afternoon if morning succeeded. This meant: (a) afternoon never added fresh threads, (b) if morning was underfilled, budget was wasted. Replaced with explicit top-up model.

### AttentionBudget CQS Fix (June 25-27)

`AttentionBudget.from_avatar()` now respects `cqs_level`:
- `cqs_level="lowest"` → max_comments=0, max_posts=0 (FULL STOP — zero EPG slots, zero emails)
- `cqs_level="low"` + Phase 1 → max_comments=2

**June 25:** Changed from ignored (budget=3 for lowest) to budget=1.
**June 27:** Changed from budget=1 to budget=0. Zero slots = zero tasks = zero emails. Recovery path: CQS check execution task (separate from EPG) prompts executor to post in r/WhatIsMyCQS every 7 days.

### CQS Self-Healing Loop (Added June 27)

When budget=0 (CQS=lowest), the system previously had no way to recover — no EPG → no tasks → no emails → executor never prompts CQS recheck. DEADLOCK.

**Fix:** `generate_cqs_check_tasks_all_avatars` (07:00 daily Beat task):
1. Queries avatars by interval (7d for lowest/young, 30d for mature)
2. Creates ExecutionTask(task_type="cqs_check", epg_slot_id=NULL)
3. Email: "Log in, post 'What is my cqs?' in r/WhatIsMyCQS"
4. Executor posts → bot replies → `check_cqs_all_avatars` (06:30) reads → CQS updates → budget restores

**Kill switch:** `cqs_check_tasks_enabled` (default true)
**Spec:** `.kiro/specs/cqs-execution-tasks/`

### Auto-Approve Precedence (Documented June 29)

Draft auto-approval uses **OR logic** across two levels:

```
auto_approve = avatar.auto_approve_drafts OR client.autopilot_enabled
```

| Level | Flag | Scope | Where set |
|-------|------|-------|-----------|
| Avatar | `auto_approve_drafts` | Single avatar | Admin → Avatar → Posting tab → toggle |
| Client | `autopilot_enabled` | ALL avatars of that client | Admin → Client → settings |

**Implementation:** `epg_executor.py` → `_should_auto_approve(db, avatar_id)`:
1. Checks `avatar.auto_approve_drafts` first
2. If False, checks `client.autopilot_enabled`
3. If either is True → draft+slot move to `approved` immediately after generation

**Common confusion:** Avatar toggle shows OFF, but drafts still auto-approved because client-level `autopilot_enabled=True` overrides it.

**P5 compliance:** Both settings are explicit operator decisions (configured via admin UI). Not bypass — pre-authorized policy.

---

## Extension Posting Safety (ADDED June 29, 2026)

The browser extension introduces a new posting path that bypasses proxy/OAuth/API infrastructure entirely. Safety is maintained through structural constraints:

### Principle: Extension is Execution-Only

The extension **cannot generate tasks**. It can only execute tasks created by RAMP backend. This means:
- Extension cannot decide WHAT to post (backend decides)
- Extension cannot decide WHERE to post (backend decides)
- Extension cannot decide WHEN to post (backend decides)
- Extension can only execute pre-approved actions and report results

### Safety Gates

| Gate | Mechanism | Bypass possible? |
|------|-----------|-----------------|
| **1. HMAC-signed tasks** | Every task delivered to extension includes HMAC signature (backend secret). Extension verifies signature before execution. Prevents task tampering or injection. | No — requires backend secret |
| **2. REQUIRED_UI mode** | Executor must click Approve in popup before ANY post is submitted. No auto-post code path exists (auto-dispatch was prototyped June 29 then removed). | No — structural (code removed) |
| **3. State machine verification** | Before executing, state machine transitions through PRECHECK → NAVIGATING → CONTEXT_VERIFIED. Context verification confirms: correct subreddit loaded, correct thread visible, comment composer accessible. | No — each step validates preconditions |
| **4. DOM_CHANGED detection** | If expected selectors fail (Reddit DOM update, page layout change), state machine emits `DOM_CHANGED` error and aborts. No blind posting into wrong context. | No — selector failure = abort |
| **5. Event stream audit trail** | Every state transition is emitted to backend (`/api/extension/events`). Full audit trail of: what was attempted, what succeeded, what failed, timing of each step. | No — events emitted before/after every action |
| **6. Heartbeat liveness** | Extension sends heartbeat every 60s. If backend doesn't receive heartbeat for >5 min, executor is considered offline. Tasks are not delivered to offline executors. | No — server-side check |

### What Extension CANNOT Do

- Generate content (no LLM access, no prompt assembly)
- Create tasks (receives tasks only)
- Modify task content (HMAC prevents tampering)
- Post without user approval (REQUIRED_UI enforced)
- Access other Reddit accounts (content script runs in current tab only)
- Exfiltrate credentials (never reads cookies/tokens — only interacts with DOM)

### Relationship to SBM Properties

| Property | How extension satisfies |
|----------|----------------------|
| **P5 (Human Gate)** | Executor approves content in popup before execution |
| **P11 (Execution Gate)** | REQUIRED_UI mode — no path from intent to post without Approve click |
| **P4 (Safety Monotonicity)** | Tasks are phase-gated at creation time (backend), not at extension |
| **P7 (Isolation)** | Extension operates on single avatar per session, cannot cross-post |
| **P9 (Diagnostic Independence)** | System actions (CQS check, health probe) run independently of content actions |

## Risk-Aware Avatar Activation (ADDED July 2, 2026)

Zone-based subreddit routing for Phase 0-1 avatars, replacing static hobby_subreddits with personalized routes derived from SubredditRiskProfile data.

### Architecture

```
Avatar Created / Demoted to Phase 0-1
    ↓
ActivationRouter.plan_route(db, avatar, client)
    ↓
activation_route JSONB → { safe_subs, bridge_subs, target_subs, current_zone }
    ↓
EPG scan_opportunities() reads zone subs instead of hobby_subreddits
    ↓
Daily 06:00: ZoneEvaluator.run_zone_evaluation_for_avatar()
    → graduate (safe→bridge→target) or demote (bridge→safe)
```

### Zone Classification

| Zone | Risk Score | Purpose | Budget (Phase 0) | Budget (Phase 1) |
|------|-----------|---------|-------------------|-------------------|
| Safe | 0-25 | Foundation karma, zero risk | 1/day | 1/day |
| Bridge | 26-50 | Niche footprint, moderate risk | 0/day | 3/day |
| Target | 51-80 | Client's actual subreddits | 0/day (Phase 2+ only) | 0/day (Phase 2+ only) |
| Dangerous | 81-100 | Blocked for Phase 0-1 entirely | — | — |

### Graduation Criteria

**Safe → Bridge:**
- total_karma ≥ 10
- CQS ≠ lowest
- account_age ≥ 7 days
- ≥ 3 posted in safe zone, 0 deleted
- survival_rate ≥ 90% (min 5 sample)

**Bridge → Target:**
- karma ≥ 15 in 2+ bridge subs
- total_karma ≥ 50
- survival_rate ≥ 85% (min 5 sample)
- compatibility_score ≥ 60 for target subs

### Demotion Within Zones

- Survival rate < 70% in current zone → demote to previous zone
- Per-subreddit ban in bridge sub → sub removed from route, alternative found
- Phase demotion (Phase 2→1 or Phase 2→0) → fresh route planned automatically

### Bridge Discovery

For each client target subreddit, finds 3-8 bridge candidates:
- Same category/topic but risk_score 26-50
- AvatarSubredditCompatibility ≥ 50
- Not in another client's exclusive list
- Fallback: avatar's hobby_subreddits if < 3 bridges found

### Safety Properties

- **Feature-flagged:** `activation_routing_enabled` (default: false). Legacy behavior unchanged when disabled.
- **Fail-open:** no route = existing hobby_subreddits path. Never blocks pipeline.
- **Dangerous hours:** `is_safe_posting_time()` filters opportunities in scan_opportunities() before slot creation.
- **All existing safety gates still apply:** fitness_gate, hot thread filter, phase policy, daily caps.
- **Zone graduation ≠ phase promotion:** zone routes within a phase; phase gates content type.

### Key Files

| File | Purpose |
|------|---------|
| `app/services/activation_router.py` | Core routing: plan, refresh, graduate, demote |
| `app/services/zone_evaluator.py` | Graduation/demotion criteria evaluation |
| `app/services/timing_engine.py` | `is_safe_posting_time()` for dangerous hours |
| `app/services/opportunity_engine.py` | Reads zone subs for Phase 0-1 (integration) |
| `app/tasks/ai_pipeline.py` | Zone eval hook after phase eval (daily 06:00) |
| `app/services/phase.py` | Route re-plan on demotion to Phase 0-1 |
| `app/services/admin.py` | Route refresh on client subreddit changes |
| `alembic/versions/raa01_activation_route.py` | Migration: activation_route JSONB + zone fields |

---

## Daily EPG Minimum Guarantee (ADDED July 10, 2026)

### Invariant

**Every active avatar with budget > 0 MUST receive ≥1 EPG slot (and generation) every day.**

This is a business requirement from Tzvi: clients pay for daily engagement activity. Zero-day is unacceptable for any avatar that should be working.

### Implementation — 3 Layers

| Layer | When | Mechanism |
|-------|------|-----------|
| **1 — Archive Fallback** | During `scan_opportunities()` | If no fresh unused hobby posts (7d), query entire archive excluding posts already drafted for this avatar |
| **2 — Enforcement Task** | 09:00 daily (`ensure_daily_epg_minimum`) | Checks all avatars for 0 slots today → force scrape + rebuild for starving avatars |
| **3 — Alert** | After enforcement | If still 0 after retry → activity event + operator alert |

### Archive Fallback Logic (Layer 1)

```
1. Primary: hobby_subreddits WHERE status="new" AND ai_comment IS NULL AND created_at >= 7 days ago
2. If empty → Archive: hobby_subreddits WHERE id NOT IN (all hobby_post_ids this avatar ever drafted for)
   - No freshness limit (yesterday, last week, last month — all valid)
   - Sorted by scraped_at DESC (most recent first)  
   - URL filter (no image/link posts)
   - post_body length > 20 chars
```

### Critical Rule: No Repeats

Archive fallback excludes ALL `hobby_post_id` values that exist in `comment_drafts` for this avatar (ANY status — pending, approved, posted, rejected). An avatar never gets the same thread twice.

### Enforcement Task (`ensure_daily_epg_minimum`)

- Beat schedule: 09:00 (45 min after morning EPG build at 08:15)
- For each starving avatar: `scrape_hobby_subreddits()` → `build_portfolio(topup_remaining=budget)`
- Uses topup path to bypass dedup guard (morning build may have produced zero_day)
- If recovery succeeds: `generate_all_planned_slots()` → avatar gets content
- If still 0: emit `⚠️ EPG daily minimum NOT met` activity event

### Phase 0 Inclusion

- `build_portfolio()` no longer excludes Phase 0 (was incorrectly blocking Incubation avatars as "Mentor")
- `scrape_hobby_all_avatars` now includes Phase 0 (`warming_phase >= 0`)
- Phase 0 budget = 1 comment/day in safe subs (from `AttentionBudget.from_avatar`)
- Mentor exclusion is via `avatar.pool == "mentor"` check (separate from phase)

### When Guarantee Does NOT Apply

- `budget.max_total_actions == 0` (CQS=lowest — legitimate full stop)
- `avatar.pool == "mentor"` (excluded from pipeline by design)
- `avatar.is_frozen == True` (admin action or suspended)
- `avatar.health_status in ("shadowbanned", "suspended")` (platform enforcement)
- `pipeline_enabled == false` (system-wide kill switch)
- `client.is_active == false` or expired trial

---

## Architecture Debt

| Issue | Impact | Status |
|-------|--------|--------|
| ~~Smart Scoring Phase 1 = dead code~~ | Source 1 gated to Phase 2+ | **FIXED June 24** |
| ~~Portfolio Manager dict crash~~ | hobby_subreddits dict format crash | **FIXED June 24** |
| ~~Hobby status filter mismatch~~ | `status IS NULL` → `"new"` | **FIXED June 24** |
| ~~`warm` pool excluded from scoring~~ | StopAutomatic717 blocked | **FIXED June 24** |
| ~~Case-sensitive subreddit match~~ | "Metal" ≠ "metal" | **FIXED June 24** |
| No admin alert on demotion | Demotion happens silently | TODO |
| ~~EPG budget miscounting~~ | skipped-without-draft counted as consumed → false "budget exhausted" | **FIXED June 24** |
| ~~EPG rebuild race condition~~ | No distributed lock → parallel runs create duplicate slots | **FIXED June 25** (dedup guard rewritten: 2-level check + max 2 attempts/day) |
| ~~Worker offline false alert~~ | Heartbeat only logged to stdout, alert queried empty DB table | **FIXED June 24** |
| No "demotion cooldown" | Repeated demotion/promotion cycles | TODO |
| Hobby pipeline limited to 1-3/day | Phase 1 warming rate | By design |
| Gemini Flash empty response | ~15% of hobby generations → slot skipped | Monitor |
| ~~Approved drafts stuck forever~~ | Drafts posted manually outside system never get "posted" status | **FIXED June 24** (draft_reconciliation.py) |
| Reddit API call duplication | karma_tracking + profile_analytics + presence all fetch comments independently | Optimization (non-blocking) |
| ~~Hobby pipeline missing image/video filter~~ | Image posts with body text passed hobby filter, generated nonsensical replies | **FIXED June 26** (url filter added to opportunity_engine + generate_hobby_comments) |
| ~~Locked thread email delivery~~ | Executor receives tasks for locked threads, stuck in limbo | **FIXED June 26** (pre-dispatch liveness check + executor "Can't Post" button) |
| ~~Hobby drafts "Unknown thread" in review queue~~ | hobby_post_id had no FK, no relationship, no eager load → admin review never resolved hobby context | **FIXED June 28** (shared HobbyThreadProxy + FK + relationship) |
| ~~Phase 0-1 sub selection is static~~ | Hobby subs hardcoded, no risk-aware routing | **DONE July 2** (`activation_router.py` — zone routing safe→bridge→target using SubredditRiskProfile, feature-flagged) |
| ~~EPG scan_opportunities no round-robin~~ | Most-scraped sub monopolizes all EPG slots (e.g., worldcup 51 posts → 100% of budget) | **FIXED July 13** (per-sub limit + shuffle in both primary query and archive fallback) |
| ~~EPG hobby prompt drift~~ | `epg_executor.py` had weak placeholder prompt vs full pipeline prompt → repetitive generic output ("Respect for the analysis" ×3) | **FIXED July 13** (full prompt rewrite: engagement angles, anti-repetition, connect-to-details, voice profile) |
| EPG vs pipeline prompt unification | Two code paths for hobby comment generation with different prompts → drift risk | TODO (deferred: Tzvi prompt audit pending) |
