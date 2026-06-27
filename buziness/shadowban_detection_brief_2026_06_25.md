# Shadowban Detection — Technical Brief for Tzvi

**Date:** June 25, 2026  
**Author:** Max  
**Status:** Design ready, implementation pending

---

## What Happened (Incident)

Jekorn (executor for avatar `Flaky_Finder_13`) reported completing task TASK-20260624-006 (comment in r/Metal). System showed the task as "accepted" but never transitioned to "posted".

**Investigation result:** The Reddit account `Flaky_Finder_13` is **globally shadowbanned** by Reddit admins. Everything she posts is invisible to all other users. Reddit does NOT notify the user — she likely thinks her comments are live.

**Proof:** Her posts in r/WhatIsMyCQS exist in her profile but are invisible in the subreddit feed. Comment karma = 0 despite activity.

---

## What is Shadowban

Reddit's stealth punishment. The user can still post, comment, vote — but nobody else sees their content. Reddit intentionally hides this from the user (no notification, no error message). The user discovers it only by checking in incognito or via third-party tools.

**Types:**
- **Global (site-wide)** — Reddit admin action. All content invisible everywhere. This is what happened to Flaky_Finder_13.
- **Per-subreddit** — Moderator action (AutoMod/ban). Content invisible only in that specific subreddit.

---

## Impact on Business

- Shadowbanned avatar = dead avatar. All posting effort wasted.
- Executor doesn't know → keeps "completing" tasks → we think it's working → client gets zero value.
- Current system detects per-subreddit bans (3 consecutive removals in same sub). Does NOT detect global shadowban.

---

## Solution: Global Shadowban Auto-Detection

**Where:** Inside existing `health_check_all_avatars` task (runs 2x daily at 07:30, 13:30).

**How:**
1. For each avatar, take their most recent Reddit post (submission)
2. Check if that post is visible in the subreddit's feed (read-only PRAW, no auth needed)
3. If NOT visible → global shadowban confirmed → mark `is_shadowbanned=true` → freeze avatar → notify operator

**Cost:** Zero additional API calls for avatars without posts. 1-2 extra calls for avatars with posts. Well within Reddit rate limits.

**Covers:**
- Any avatar that has ever made a post on Reddit (even CQS test posts like Flaky's r/WhatIsMyCQS)
- Detection within 12 hours (next health check cycle)

**Does NOT cover:**
- Brand new accounts with zero posts/comments (edge case — they wouldn't be useful anyway)

---

## Per-Subreddit Ban Detection (Separate System)

Already designed. Uses `snapshot_comment_outcomes` data:
- 3 consecutive comments in same subreddit = [removed] within 5h of posting
- Result: subreddit excluded from avatar's pipeline (not full freeze)
- Weekly unban probe: checks if old removed comment became visible again

---

## Immediate Actions Needed

1. ✅ Mark `Flaky_Finder_13` as shadowbanned in system
2. ⚠️ Tell Jekorn her account is banned — she needs to either:
   - Appeal at reddit.com/appeals (rarely succeeds for fresh accounts)
   - Create a new account and warm it organically for 2-4 weeks
3. ⚠️ Reassign her tasks to another avatar or pause NeuroYoga/Israel pipeline until replacement ready

---

## Timeline

- **Today:** Mark Flaky as banned, stop sending tasks
- **This week:** Implement global shadowban check in health_check task
- **Ongoing:** Per-subreddit detection (separate feature, already designed)

---

## Business Risk

With Flaky banned, NeuroYoga client has only **Hot-Thought2408** active (Austin/breathwork subs). Israel/Metal coverage = zero until new avatar onboarded.

Options:
1. Onboard a new avatar for Israel/Metal subs (2-4 weeks warming)
2. Redirect existing avatar to cover Israel temporarily (if voice/persona fits)
3. Inform client of reduced coverage during transition
