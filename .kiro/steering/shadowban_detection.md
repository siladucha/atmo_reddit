# Shadowban Detection Architecture

## Key Platform Fact (Confirmed June 28, 2026)

**Global shadowban = profile 404.** Reddit treats shadowbanned accounts identically to non-existent accounts at the API level (PRAW docs: "Shadowbanned accounts are treated the same as non-existent accounts, meaning that they will not have any attributes"). This means:

- `redditor.comments.new()` returns data → profile is publicly visible → **NOT shadowbanned** (guaranteed)
- `redditor.comments.new()` returns 0 OR throws 404 → **possible shadowban** (needs further probe)

**Invariant for detection code:** If Reddit API returns ANY user content (comments, submissions, karma) — regardless of age or lookback window — the account is definitively not globally shadowbanned. The date filter on comments is irrelevant to shadowban determination.

Source: PRAW 7.6+ docs, multiple Reddit marketing tool docs (prmotion.me, leadmore.ai, soar.sh), confirmed empirically with d-wreck-w12 (API returned 5 old comments → not shadowbanned → confirmed via in-thread visibility).

---

## Two-Layer Detection System

The system detects shadowbans at two levels:

### Layer 1: Global Shadowban (Site-Wide Reddit Admin Action)

**Detection method:** Check if avatar's submissions are visible in subreddit feed.
- Take avatar's most recent submission (via `redditor.submissions.new(limit=1)`)
- Query the subreddit's `new` listing for that post
- If post exists in profile but NOT in subreddit feed → **global shadowban confirmed**

**Where it runs:** Inside `health_check_all_avatars` (07:30 and 13:30 daily).

**On detection:**
- Set `avatar.is_shadowbanned = True`
- **Demote to Phase 0 (Incubation)** — NOT freeze. Avatar stays in pipeline with 1/day probe activity.
- Emit activity event `global_shadowban_detected`
- Send notification to operator
- Avatar continues at Phase 0 pace (1 comment/day in safe subs). This activity serves as shadowban probe.
- Health checks continue running. When shadowban clears → `is_shadowbanned = false` → avatar graduates Phase 0 → 1 normally.

**Recovery path (NEW — spec: phase-incubation-mentor-refactor):**
- Phase 0 avatar generates 1 comment/day → if karma appears on that comment → shadowban may be lifted
- Health check (07:30, 13:30) detects visibility restored → sets `is_shadowbanned = false`
- Avatar remains in Phase 0, graduates via standard criteria (age≥7d, karma≥10, 3 posted, 0 deleted)
- NO manual intervention needed for recovery

**Limitation:** Requires at least 1 submission in avatar's history. Accounts with zero posts cannot be checked this way. The CQS test posts (r/WhatIsMyCQS) serve as the probe — every avatar should have at least one.

**Known case:** `Flaky_Finder_13` — confirmed globally shadowbanned June 25, 2026. Posts in r/WhatIsMyCQS invisible in sub feed. Comment karma=0 despite executor activity.

### Layer 2: Per-Subreddit Ban (Moderator/AutoMod Action)

**Detection method:** Analyze `snapshot_comment_outcomes` data.
- 3 consecutive comments by same avatar in same subreddit = `[removed]` or `author=None`
- Each removed within 5 hours of posting (pattern = automod, not delayed manual moderation)
- No surviving comment between the 3 removals

**Where it runs:** Inside `snapshot_comment_outcomes` (every 4h).

**On detection:**
- Mark subreddit as banned for that avatar (exclude from pipeline)
- Emit activity event `subreddit_ban_detected`
- Do NOT freeze avatar globally (other subs still work)

**Unban probe:** Weekly (Sunday 03:45) — check last removed comment via read-only PRAW. If visible → unban → re-enable subreddit.

**Limitation:** Requires `reddit_comment_url` in database. Only works for comments posted through system or linked via draft reconciliation. If executor posted externally and never submitted permalink, system has nothing to check.

---

## Reconciliation Dependency

Draft reconciliation (`draft_reconciliation.py`) runs every 4h inside `track_karma_all_avatars`. It uses `redditor.comments.new(limit=100)` via read-only PRAW.

**Critical:** If avatar is globally shadowbanned:
- `redditor.comments.new()` returns 0 results (Reddit hides shadowbanned content from API)
- Reconciliation correctly finds nothing → drafts stay `approved` forever
- This is NOT a reconciliation bug — it's correct behavior given shadowban

**Implication:** Global shadowban detection (Layer 1) must run BEFORE reconciliation has a chance to mark things as "never posted". The health check (07:30) runs before karma tracking (every 4h at :15), so detection happens first.

---

## CQS Test Posts as Shadowban Probes

Every avatar creates posts in r/WhatIsMyCQS as part of CQS (Contributor Quality Score) checking. These posts serve dual purpose:
1. CQS score validation
2. **Global shadowban probe** — if CQS post invisible in sub feed, account is shadowbanned

This means: even avatars that have never posted real content can be checked for global shadowban via their CQS posts.

---

## Admin UI Actions

- **Manual Ban:** Operator marks avatar as shadowbanned (covers edge cases automation misses)
- **Manual Unban:** Operator clears shadowban flag (e.g., after successful Reddit appeal)
- **Per-sub Ban/Unban:** Operator manages individual subreddit exclusions

---

## Impact on Email Task Delivery

When avatar is shadowbanned:
- All pending `ExecutionTask` records should be cancelled (status → `cancelled`, reason: `avatar_shadowbanned`)
- No new EPG slots generated for this avatar
- Executor receives no further emails for this avatar
- Operator notified to reassign coverage

---

## Detection Fixes (June 26-28, 2026)

1. **zero_content_with_history** — When API returns 0 comments + submission probe inconclusive, but avatar has posted_drafts in DB → classify as shadowbanned (not unknown)
2. **Young account accelerated checks** — Accounts <90 days get health checked every 4h instead of 12h
3. **Stale unknown auto-freeze** — health_status="unknown" >48h → auto-freeze with reason "health_unknown_stale_48h"
4. **Quiet hours gate** — dispatch_due_email_tasks blocks 23:00-07:00 Israel time
5. **Avatar health gate at dispatch** — cancel execution task if avatar frozen/banned between creation and dispatch
6. **CQS=lowest → budget=0** — full stop on EPG generation (was budget=1)
7. **CQS self-healing tasks** — periodic "post in r/WhatIsMyCQS" email tasks independent of EPG
8. **CRITICAL FIX (June 28): `zero_content_with_history` false positive** — `check_comment_visibility()` now returns `total_from_api` (comments API returned before date filter). If `total_from_api > 0` but `total_sampled == 0` → avatar is inactive (all comments older than lookback), NOT shadowbanned. The `zero_content_with_history` path now only triggers when `total_from_api == 0` (Reddit truly returned nothing). Previously, an avatar that hadn't commented in 7 days would be incorrectly classified as shadowbanned if it had any `posted` drafts in DB. **Caused false freezes for: d-wreck-w12, connor_lloyd, Flaky_Finder_13.**

---

## CQS Deadlock Fix (June 27, 2026)

**Problem:** Frozen/shadowbanned avatars were excluded from ALL diagnostic batch tasks, creating a deadlock where recovery could never be detected:
- `run_cqs_check_batch()` skipped `is_frozen=True` AND `warming_phase < 2`
- `generate_cqs_check_tasks()` skipped `is_frozen=True` AND `health_status=shadowbanned`
- Result: frozen avatar gets no diagnostics → recovery signal invisible to RAMP

**Evidence:** Flaky_Finder_13 CQS improved from LOWEST to LOW on June 26 (AutoModerator confirmed via manual executor post). RAMP never saw the improvement because all diagnostic paths were gated by the condition they were trying to diagnose.

**Fix (deployed June 27):**
- `cqs_checker.py` `run_cqs_check_batch()` — removed `is_frozen == False` and `warming_phase >= 2` filters. Now checks ALL active avatars including frozen and Phase 1.
- `cqs_task_generator.py` `generate_cqs_check_tasks()` — removed `is_frozen` and `health_status` skip filters. Frozen/shadowbanned avatars now receive CQS email tasks.
- Added recovery signal detection: if frozen avatar's CQS improves from "lowest", emits `cqs_recovery_detected` activity event.
- Tests: 27 pass.

**Principle established:** Diagnostic systems must NEVER be gated by the condition they are trying to diagnose. "Patient too sick to examine" is an anti-pattern.

**Future: Browser Extension role in recovery detection**
The browser extension (spec: `.kiro/specs/browser-extension/`) will further strengthen recovery detection by:
- Posting CQS checks through the executor's browser session (bypasses Reddit API limitations for shadowbanned accounts)
- Reporting CQS level directly to RAMP backend regardless of avatar frozen/health state
- Enabling passive health monitoring independent of PRAW batch tasks
- Supporting dual-confirmation auto-unfreeze (CQS improved + PRAW probe passes, OR operator approval)

Until the extension is built, the batch filter removal ensures RAMP can at least detect CQS improvements via the standard `check_cqs_all_avatars` Beat task reading AutoModerator replies.

---

## Incident Log

| Date | Avatar | Type | Detection | Notes |
|------|--------|------|-----------|-------|
| 2026-06-25 | Flaky_Finder_13 | Global | Manual investigation | CQS posts invisible in r/WhatIsMyCQS. Executor was posting but nothing visible. |
| 2026-06-26 | Flaky_Finder_13 | Global | Live PRAW probe (confirmed) | Account age 48d, karma=0, CQS=lowest. health_check failed to detect (submission too old for limit=100 feed). Fixed: zero_content_with_history detection. 23 tasks cancelled, account frozen. |
| 2026-06-26 | connor_lloyd | Global | submission_visibility_probe | Post in r/badtattoos not in feed. Auto-detected by system. |
| 2026-06-27 | Flaky_Finder_13 | Recovery signal | Manual investigation + CQS fix | CQS improved LOWEST→LOW (June 26 post). Shadowban still active. Batch filter fix deployed — RAMP can now detect this. |
| 2026-06-28 | d-wreck-w12 | **FALSE POSITIVE** | zero_content_with_history | Comments all >7d old → total_sampled=0, but API returned 5 comments. Submission too old (>24h). System incorrectly concluded shadowban. Unfrozen manually. **FIX DEPLOYED:** total_from_api distinction. |
| 2026-06-28 | Flaky_Finder_13 | **Recovery confirmed** | Manual PRAW probe | Shadowban LIFTED! Comment in r/worldcup visible, score=3. Unfrozen. |
| 2026-06-28 | connor_lloyd | **Recovery confirmed** | Manual PRAW probe | Shadowban LIFTED! karma=86, comments in r/sysadmin visible (score=11). Unfrozen. |
| 2026-06-28 | NotSoDelgado88 | Global | Manual comment-in-thread probe | Comment in r/whatisit HIDDEN. karma=0, fresh account. Confirmed shadowbanned. |
