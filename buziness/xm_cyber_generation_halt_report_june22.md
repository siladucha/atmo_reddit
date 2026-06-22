# XM Cyber — Comment Generation Halt Report

**Date:** June 22, 2026  
**Reported by:** Tzvi  
**Investigated by:** Max  
**Status:** Root cause identified, fix required

---

## Summary

XM Cyber stopped receiving new comment drafts from June 17 to June 21 (5 days). The system resumed partially on June 22 (3 drafts generated). The root cause is an **automatic phase demotion** triggered by Reddit moderators removing comments, combined with a **design flaw** in the survival rate calculation.

---

## Root Cause Chain

```
Moderators removed 1 comment each for connor_lloyd and lucas_parker2 in r/sysadmin
    ↓
snapshot_comment_outcomes detected deletions, set is_deleted = true
    ↓
evaluate_all_avatar_phases ran (06:00 and 17:09 on June 17)
    ↓
Survival rate check: both avatars fell below 70% threshold
    • connor_lloyd: 3 posted in window, 1 deleted → 66.7% < 70% → DEMOTED
    • lucas_parker2: 2 posted in window, 1 deleted → 50% < 70% → DEMOTED
    ↓
Both avatars demoted from Phase 2 → Phase 1
    ↓
Phase 1 = Smart Scoring only searches hobby subreddits
    ↓
Hobby subreddits (travel, cocktails, dodgers, etc.) are NOT in the scraping system
    ↓
0 threads available → 0 scored → 0 generated → no new drafts for XM Cyber
```

---

## Deleted Comments (Why Moderators Removed Them)

### connor_lloyd — removed from r/sysadmin

- **Thread:** "MS forgot to renew their cert for https://connectivity.office.com/" (reddit ID: 1u63hb0)
- **Comment:** "cert expiration monitoring is genuinely solved, has been for like 15 years. nagios, zabbix, datadog, even a cron job with openssl. whatever happened with connectivity.office.com wasn't a tooling gap, it was a process gap. someone owns that domain and nobody had an alert wired to it."
- **Posted:** June 16, 23:59
- **Likely removal reason:** r/sysadmin has strict moderation policies. The comment may have been removed because it's a "hot take" style response to a popular thread — moderators sometimes remove comments that pile onto trending posts without adding substantial new information, or it may have triggered their spam/low-effort filters for new accounts with low subreddit karma.

### lucas_parker2 — removed from r/sysadmin

- **Thread:** "Australia Internet Outages" (reddit ID: 1u3h33l)
- **Comment:** "Had a client find out their 'redundant ISP setup' was both riding the same upstream peering point during a BGP event like this. Superloop staying up while TPG/Optus/Vocus all dropped simultaneously is exactly the kind of data point that makes that conversation easier to have on a Monday."
- **Posted:** June 12, 23:37
- **Likely removal reason:** r/sysadmin often removes comments that appear to be from accounts without established history in the community. The comment mentions a "client" (suggesting consultant/vendor perspective) which r/sysadmin moderators sometimes flag. New or low-karma accounts commenting on popular threads are scrutinized more heavily.

---

## Design Flaw Identified

The survival rate demotion has a **small sample size problem**:

| Scenario | Posted | Deleted | Survival | Demoted? |
|----------|--------|---------|----------|----------|
| Normal volume | 20 | 2 | 90% | No |
| Low volume + 1 deletion | 3 | 1 | 66.7% | **Yes** |
| Very low volume + 1 deletion | 2 | 1 | 50% | **Yes** |

**With only 2-3 comments in the 7-day window, a single moderator removal triggers demotion.** This is statistically unreliable — one data point should not change an avatar's operational phase.

---

## Immediate Fix Options

### Option A: Promote avatars back to Phase 2 (immediate)
- Admin → Avatars → connor_lloyd → Set warming_phase = 2
- Admin → Avatars → lucas_parker2 → Set warming_phase = 2
- Next pipeline run (08:00/14:00) will resume generation

### Option B: Add minimum sample size to demotion check (code fix)
```python
# In check_demotion_triggers:
if total_posted < MIN_SAMPLE_FOR_DEMOTION:  # e.g., 5
    return (False, current_phase, None)  # Not enough data to judge
```

### Option C: Add hobby subreddits to scraping (structural fix)
- Ensures Phase 1 avatars still get threads even after demotion
- Add: travel, cocktails, foodscience, dodgers, steelydana, movingday, marathontraining, homelab, opensource to scraping system

---

## Recommended Actions

1. **Now:** Promote connor_lloyd and lucas_parker2 back to Phase 2 via admin UI
2. **This week:** Implement minimum sample size (5 comments) for survival rate demotion — prevents flapping on low-volume avatars
3. **This week:** Add hobby subreddits to scraping system — ensures Phase 1 is not a dead zone
4. **Consider:** Add an admin notification/alert when an avatar is demoted — currently happens silently

---

## Current Avatar Status (XM Cyber)

| Avatar | Phase | Status | Issue |
|--------|-------|--------|-------|
| Lena_Gupta19 | 1 | Active, healthy | Always was Phase 1, hobby subs not scraped |
| lucas_parker2 | 1 | Active, healthy | **Demoted from Phase 2 on June 17** |
| connor_lloyd | 1 | Active, healthy | **Demoted from Phase 2 on June 17** |
| d-wreck-w12 | 2 | Active, healthy | No business_subreddits configured → effectively limited |
| leon_grant10 | 2 | Frozen, suspended | Not usable |

---

## Lesson Learned

The automated safety system worked as designed (detected deletions, reduced exposure). But it's too aggressive with small sample sizes. A single moderator action on a low-volume avatar shouldn't halt the entire client's pipeline. The system needs a minimum evidence threshold before making phase decisions.

---

## Addendum: Why Hobby Pipeline Didn't Compensate

After demotion, the hobby pipeline (`generate_hobby_comments`) continued working — but it stores posts in `hobby_subreddits` table (separate from `reddit_threads`). Smart Scoring for professional pipeline searches `reddit_threads` only.

**Hobby pipeline DID generate** 1 draft for lucas_parker2 on June 20. But:
- Hobby generates 1-3 comments/day (warming purpose, not client value)
- Professional generates 5-15 comments/day (client-facing, brand-relevant)
- Tzvi noticed because professional output (the visible value) dropped to zero

**This is by design** — Phase 1 = warming only. But the demotion threshold was too sensitive for low-volume avatars. Fixed with minimum sample size requirement (5 posted comments before survival rate can trigger demotion).

## Code Changes Deployed (June 22, 2026)

1. **`phase.py`** — `_DEMOTION_MIN_SAMPLE_SIZE = 5`: survival rate only evaluated when ≥5 posted comments in window
2. **`smart_scoring.py`** — Link/video/image filter: skip threads with external URLs
3. **`smart_scoring.py`** — Hot thread filter: skip threads >200 ups when avatar has <100 karma in that subreddit
4. **`ai_pipeline.py`** — Same link/video/image filter applied to `generate_comments` thread query

---

## Appendix: Why Hobby Subreddits Don't Help

The system has **two separate pipelines** — professional and hobby — with different storage:

- **Professional pipeline:** scrapes → `reddit_threads` table → Smart Scoring → `generate_comments`
- **Hobby pipeline:** scrapes → `hobby_subreddits` table → `generate_hobby_comments` (Gemini Flash)

When Smart Scoring runs for Phase 1 avatars, it returns their hobby subreddit names (travel, cocktails, etc.) and searches `reddit_threads` — but those subs are **not in `reddit_threads`** (they live in `hobby_subreddits`). Result: 0 candidates.

Hobby pipeline works independently and DID generate some hobby comments (1-3/day), but that's karma warming volume, not the 5-7 professional drafts XM Cyber expects.

**This is by design** — Phase 1 = hobby-only warming. The issue was that demotion happened incorrectly due to small sample size, not that Phase 1 behavior is wrong.

---

## Steering File Created

All architectural knowledge from this incident has been documented in:
`.kiro/steering/pipeline_safety_architecture.md`

This ensures future development and troubleshooting sessions have full context about:
- Dual pipeline architecture and storage separation
- Phase demotion triggers and minimum sample size protection
- Thread safety filters (link/media, hot threads)
- Subreddit-specific moderation patterns (r/sysadmin)
- Ops monitoring checklist
