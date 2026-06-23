# Subreddit Risk Profile — Feature Complete

**Date:** June 23, 2026
**From:** Max (Tech)
**To:** Tzvi (CEO)

---

## What Was Built

A full intelligence system that prevents comment removals before they happen. Instead of learning from failures after the fact, the system now proactively blocks unsafe avatar-subreddit pairings before wasting LLM tokens on comments that will get deleted.

## Business Impact

1. **Fewer removals** — the #1 cause of avatar demotions was moderators deleting comments from low-karma accounts. The Fitness Gate blocks these before generation.

2. **Lower AI costs** — no LLM tokens wasted on comments that would be removed. Blocked threads are counted against the daily budget but cost $0 in AI spend.

3. **Better client outcomes** — stable avatars that don't get demoted to Phase 1. Consistent output volume.

4. **Actionable intelligence** — new Risk Profile page shows per-subreddit: moderator behavior patterns, dangerous posting hours, extracted rules, and avatar fitness scores. Available to both admin and client portal users.

## How It Works (Simple Version)

Every Sunday at 05:00, the system:
1. Reads subreddit sidebar rules (via Reddit API + AI extraction)
2. Analyzes 30 days of our posting outcomes (which comments survived vs. got removed)
3. Computes a Risk Score (0-100) for each subreddit
4. Before generating any comment: checks if the avatar meets the subreddit's requirements

If an avatar doesn't meet requirements (karma too low, account too young, posting during dangerous hours) — that thread is skipped. No comment generated, no risk of removal.

## What Clients See

A new "Risk Profile" page accessible from the subreddit list (both admin and client portal):
- Risk score with color-coded badge (green/yellow/orange/red)
- Extracted subreddit rules (parsed from sidebar)
- Moderation insights (aggressiveness level, dangerous hours, removal patterns)
- Recommendations (AI-generated, max 5 per subreddit)
- Avatar fitness table (which avatars are safe for this subreddit)
- Daily history (30-day posting outcomes, survival rates)

## Kill Switch

System setting `fitness_gate_enabled` (default: ON). If we see it's too aggressive and blocking too many threads, we can disable it instantly without code changes from the admin panel.

## First Results

The system will start collecting data immediately on deployed. After the first Sunday batch run (next Sunday), full risk profiles will be populated. Until then, the Fitness Gate operates in "fail-open" mode — it allows all generation if no profile exists yet.

## Technical Summary

- 4 new services: rule_extractor, moderation_profiler, risk_scorer, fitness_gate
- 2 new models + 2 migrations
- 3 new weekly Celery tasks (05:00, 05:15, 05:30 Sunday)
- 2 new UI pages (admin + portal) with HTMX lazy-loading
- Pipeline integration between Smart Scoring and generation
- Full test suite (rule_extractor: 37 tests, risk_scorer: 39 tests, fitness_gate: 39 tests)

## Next Steps

1. Deploy to production (rsync + docker build)
2. Run migrations on server
3. Wait for first Sunday batch (will populate all profiles)
4. Monitor Activity Feed for `fitness_block` events (shows gate is working)
5. Tune thresholds if too aggressive (karma/age requirements)

---

**Status:** Ready for deployment.
