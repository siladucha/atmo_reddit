# Guide — Daily Operations

> **Audience:** Owner, Partner, Client Admin, Client Manager  
> **Last updated:** 2026-05-29

---

## Daily Schedule (Platform Automated)

All times in Israel Time (Asia/Jerusalem):

| Time | What Happens | Your Action |
|------|-------------|-------------|
| 05:20 | Profile analytics snapshot | — |
| 06:00 | Phase evaluation (promotions/demotions) | Check if any avatars promoted |
| 06:30 | CQS batch check | Check for auto-frozen avatars |
| 07:30 | Health check (shadowban detection) | Check for health alerts |
| 08:00 | **Morning pipeline** (score + generate) | Review drafts after ~08:30 |
| 10:00 | Hobby pipeline (Phase 1 avatars) | Review hobby drafts |
| 13:30 | Health check (second run) | Check for new alerts |
| 14:00 | **Afternoon pipeline** (score + generate) | Review drafts after ~14:30 |
| Every 60s | Scrape scheduling (queue_tick) | — |
| Every 4h | Karma tracking (posted comments) | Check for removals in Activity Feed |

---

## Morning Routine (Owner/Partner)

**Time: ~09:00 (after morning pipeline completes)**

### 1. Check System Health (2 min)

Go to `/admin/dashboard`:
- All topology nodes green? ✅
- Any failed tasks in last 24h? Check activity feed
- Any frozen avatars? Check alerts

### 2. Review Priority Drafts (10-15 min)

Go to `/admin/review`:
- Sort by client priority
- Focus on Phase 3 avatars first (brand-relevant content)
- Approve/edit/reject

### 3. Check Avatar Health (3 min)

Go to `/admin/avatars`:
- Any 🔴 red health badges?
- Any newly frozen avatars?
- CQS drops?

### 4. Scan Activity Feed (2 min)

Dashboard → Activity Feed:
- Any errors or warnings?
- Pipeline completed successfully?
- Any unusual patterns?

---

## Review Process (Detailed)

### Priority Order

1. **Phase 3 brand comments** — highest value, most risk
2. **Phase 2 professional comments** — building authority
3. **Phase 1 hobby comments** — lowest risk, can batch-approve

### Review Checklist (Per Draft)

```
□ Does it sound like the avatar? (voice match)
□ Is it relevant to the thread? (not off-topic)
□ Is it helpful/valuable? (would a real user appreciate it?)
□ Is the length appropriate? (usually 2-5 sentences)
□ No brand mention violations? (check avatar phase)
□ No AI-tell phrases? ("Delve", "Crucial", "It's important to note")
□ No factual errors?
□ Would you upvote this if you saw it on Reddit?
```

### When to Edit vs Reject

**Edit** when:
- 80%+ is good, just needs minor fixes
- Tone is slightly off (one word change)
- Too long (trim the fat)
- Missing a personal touch ("In my experience...")

**Reject** when:
- Completely off-topic
- Sounds robotic/generic
- Would get downvoted on Reddit
- Factually wrong and you can't easily fix it
- Thread is dead/irrelevant

### Learning Impact

Every edit you make teaches the system:
- After ~5 consistent edits of the same type → system extracts a pattern
- After ~10 edits → pattern injected into future prompts
- Result: fewer edits needed over time

---

## Posting Tracking — How It Works

### Where Posted Comment Links Live

Every comment that gets posted on Reddit has its URL stored in the `comment_drafts` table:

| Field | Purpose |
|-------|---------|
| `reddit_comment_url` | Full Reddit permalink to the posted comment |
| `posted_at` | Timestamp when the comment was posted |
| `reddit_score` | Current karma (upvotes minus downvotes) |
| `is_deleted` | Whether the comment was removed/deleted |
| `deleted_detected_at` | When removal was first detected |
| `last_karma_check_at` | Last time the system checked this comment |

### Automated Karma Tracking (Every 4 Hours)

The `track_karma_all_avatars` Celery task runs every 4 hours and performs:

1. **For each active avatar:** fetches last 100 comments from Reddit via PRAW
2. **Matches** Reddit comments to our `comment_drafts` by text content (first 80 chars)
3. **Updates karma:** stores current `reddit_score` for each matched comment
4. **Detects removals:** if comment body is `[removed]` or `[deleted]` → marks `is_deleted = true`
5. **Detects disappearances:** if a comment posted < 2 days ago isn't found in Reddit history → likely removed
6. **Updates per-subreddit karma** breakdown for the avatar

### Tracking Window & Rate Limits

| Parameter | Value | Purpose |
|-----------|-------|---------|
| Check window | 7 days | Only checks comments posted in last 7 days |
| Recheck interval | 4 hours minimum | Won't re-check same comment more often |
| API delay | 2 seconds between avatars | Respects Reddit rate limits |
| Comment fetch limit | 100 per avatar | Reddit API limit per request |

### What Gets Logged

After each tracking run, the system records:
- `karma_tracking_batch_completed` audit entry (avatars processed, comments updated, deletions detected)
- Activity event with full stats (visible in Dashboard → Activity Feed)

### Current Data (Production)

As of May 2026 (NeuroYoga pilot):
- **9 posted comments** with Reddit URLs being tracked
- **1 confirmed removal** (detected within 20 minutes of posting)
- **2 comments without URLs** (posted before URL tracking was added)
- Karma scores: range 1-2 (typical for niche subreddits)
- Last karma check: May 21 (system checks every 4h when avatars are active)

### How to Verify Tracking is Working

1. **Dashboard → Activity Feed** — look for "Karma tracking complete" events
2. **Avatar detail → Performance tab** — shows removal rate and karma per subreddit
3. **Direct check:** any posted draft with `last_karma_check_at` within last 4h = tracking is running

---

## Afternoon Check (5 min)

**Time: ~15:00 (after afternoon pipeline)**

1. Review new drafts from 14:00 pipeline
2. Check if morning-approved drafts were posted
3. Any new health alerts?
4. Spot-check karma tracking: any removals detected since morning?

---

## Weekly Tasks

### Monday: Avatar Health Review

- Check all avatar karma growth (week over week)
- Review removal rates per avatar
- Check phase eligibility (any ready for promotion?)
- Review learned patterns (are they accurate?)

### Wednesday: Subreddit Performance

- Check engage rates per subreddit
- Identify dead subreddits (0 engage for 2+ weeks)
- Consider adding new subreddits if coverage is thin

### Friday: Metrics & Reporting

- Export weekly stats for client meetings
- Note top-performing comments (for case studies)
- Flag any concerning trends

---

## Handling Common Situations

### Avatar Got Shadowbanned

1. System auto-freezes the avatar
2. Verify: check the avatar's Reddit profile in incognito
3. If confirmed: avatar is likely unrecoverable
4. Action: assign a replacement avatar to the client
5. Notify client if they're aware of specific avatars

### CQS Dropped to "Lowest"

1. System auto-freezes the avatar
2. This means Reddit considers the account low-quality
3. Usually caused by: too many removed comments, low engagement
4. Action: review the avatar's recent activity, adjust strategy
5. May need to retire this avatar and start fresh

### Pipeline Didn't Run

1. Check Dashboard → Topology panel
2. Look for red/grey nodes
3. Common causes:
   - Redis connection issue → restart Docker containers
   - Celery worker crashed → check logs
   - Kill switch accidentally toggled → check settings
4. Manual trigger: Dashboard → "Run Pipeline"

### Too Many Drafts in Queue

1. If queue > 50 pending: something may be misconfigured
2. Check: are scoring thresholds too low? (too many "engage" tags)
3. Check: are daily limits set correctly?
4. Quick fix: batch-reject old drafts (> 48h), adjust thresholds

### Client Asks "Why No Activity?"

1. Check client's `is_active` status
2. Check avatar health (all frozen?)
3. Check subreddit freshness (being scraped?)
4. Check keywords (too narrow? no matches?)
5. Check pipeline logs for that client in activity feed

---

## Key Metrics to Monitor

| Metric | Healthy | Warning | Critical |
|--------|---------|---------|----------|
| Drafts generated/day | 10-30 | < 5 or > 50 | 0 |
| Approval rate | > 70% | 50-70% | < 50% |
| Removal rate (posted) | < 10% | 10-20% | > 20% |
| Review latency | < 8h | 8-24h | > 24h |
| Avatar health | All active | 1-2 limited | Any shadowbanned |
| Pipeline completion | Both runs OK | 1 missed | Both missed |
