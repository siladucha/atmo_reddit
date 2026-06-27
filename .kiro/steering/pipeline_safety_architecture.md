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

### 3. Subreddit-Specific Risks

r/sysadmin moderation patterns (learned June 2026):
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

## EPG Dedup Guard (FIXED June 25, 2026)

### Problem

EPG `build_portfolio()` runs twice daily (08:15 + 14:15 via Beat). Without proper dedup:
- If morning build succeeds → afternoon must NOT create new slots (duplicates)
- If morning build fails (all slots skipped due to Gemini Flash empty response) → afternoon SHOULD retry
- After deploy/restart, Beat fires overdue tasks → multiple concurrent EPG runs → massive duplication (22 slots for budget=3 avatar observed June 24)

### Previous Guard (Broken)

```python
# Old: counted ALL slots. If morning all skipped → afternoon blocked (no retry).
# Older: excluded skipped. Multiple runs all saw 0 → all created duplicates.
existing_slots_count = count(status.notin_(["skipped"]))
```

### Current Guard (2-Level)

```python
# Level 1: If ANY non-skipped slots exist → successful build, skip
existing_active_count = count(status.notin_(["skipped"]))
if existing_active_count > 0: return "already_planned"

# Level 2: Max 2 build attempts per day (morning + afternoon retry)
build_attempts = count(DISTINCT created_at)
if build_attempts >= 2: return "already_planned"

# Otherwise: retry allowed (previous attempts all failed)
```

### Invariants

1. **Max slots per avatar per day = budget** (Phase 1 lowest=1, Phase 1=3, Phase 2=7, Phase 3=12+3)
2. **Max build attempts = 2** (morning + afternoon). No infinite retry loops.
3. **Successful build blocks further builds** (non-skipped slots exist → done for today)
4. **Failed build allows ONE retry** (all skipped → afternoon can rebuild)

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
