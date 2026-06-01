# Guide — Pipeline Explained

> **Audience:** Everyone (non-technical explanation)  
> **Last updated:** 2026-05-29

---

## Overview

The pipeline is the automated workflow that turns Reddit conversations into engagement opportunities. It runs twice daily (08:00 and 14:00) and consists of 5 stages.

```
SCRAPE → SCORE → GENERATE → REVIEW → POST
```

Each stage has safety checks and can be paused independently.

---

## Stage 1: Scrape

**What:** Collects new threads from configured subreddits.

**How it works:**
1. System checks which subreddits are due for scraping (based on freshness interval)
2. For each due subreddit, fetches the 25 newest posts via Reddit API
3. Saves new threads to database (skips duplicates and locked threads)
4. Records scrape timestamp and metrics

**Frequency:** Continuous (every 60 seconds, the system checks if any subreddit is stale)

**What can go wrong:**
- Reddit API rate limiting (system auto-throttles)
- Subreddit went private (scrape fails, logged as error)
- No new threads (normal for low-activity subreddits)

**Kill switch:** `scrape_enabled` — stops all scraping when disabled

---

## Stage 2: Score

**What:** AI evaluates each new thread for relevance and engagement potential.

**How it works:**
1. Collects unscored threads (max 50 per run, within 72h freshness)
2. For each thread, sends to Gemini Flash with client's keywords and context
3. AI returns scores: relevance (0-1), quality (0-1), strategic value (0-1)
4. Tags each thread: `engage` (high score), `monitor` (medium), `skip` (low)

**AI Model:** Gemini Flash (fast, cheap — $0.0003 per thread)

**Scoring factors:**
- Keyword match (high/medium/low priority)
- Thread quality (upvotes, comment count, recency)
- Strategic fit (does this thread align with client goals?)
- Thread liveness (locked/removed threads auto-skip)

**Output:** Threads tagged "engage" move to generation stage.

---

## Stage 3: Generate

**What:** AI writes a comment in the avatar's voice for each "engage" thread.

**How it works:**
1. For each "engage" thread, selects the best avatar (persona routing)
2. Assembles context: voice profile, strategy, thread content, learning patterns
3. AI generates a comment matching the avatar's personality
4. Comment is validated (length, safety checks, brand ratio)
5. Saved as a draft with status "pending"

**AI Model:** Claude Sonnet (high quality — $0.039 per comment)

**What goes into the prompt:**
- Avatar's full voice profile
- Strategy document (goals, positioning)
- Thread title and body
- Top existing comments (for context)
- Few-shot examples from learning loop
- Correction patterns (learned from past edits)
- Comment approach constraint (diversity rotation)

**Safety checks during generation:**
- Avatar not frozen
- Avatar not shadowbanned
- Thread still live (not locked/removed)
- Daily budget not exceeded
- Phase-appropriate content (no brand in Phase 1)

---

## Stage 4: Review

**What:** Human reviews each generated draft and decides: approve, edit, or reject.

**How it works:**
1. Drafts appear in Review Queue
2. Reviewer reads the thread context and generated comment
3. Decision:
   - **Approve** → moves to posting queue
   - **Edit** → reviewer modifies, then approves (system learns from edit)
   - **Reject** → discarded (system learns what to avoid)

**Who reviews:**
- Owner / Partner (all clients)
- Client Admin / Client Manager (their own company's drafts)
- Client Viewer (only if `draft_approval_enabled`)

**Learning loop:**
- Every edit is captured as an EditRecord
- After 5+ edits with consistent patterns → CorrectionPattern extracted
- Patterns injected into future generation prompts
- Result: AI improves over time, fewer edits needed

---

## Stage 5: Post

**What:** Approved comments are posted on Reddit from the avatar's account.

**Current method (manual):**
1. Avatar owner sees approved drafts in their queue
2. Opens Reddit in the avatar's browser profile
3. Navigates to the thread
4. Pastes the approved comment
5. Marks "Posted" in the platform and pastes the Reddit comment URL

**Future method (automated proxy posting):**
1. System picks up approved EPG slots at scheduled time
2. Safety gates verify: kill switch, health, phase, daily limit, IP
3. Posts via Reddit API using avatar's proxy (residential IP)
4. Logs PostingEvent (IP, timestamp, reddit_comment_url)
5. Draft status → "posted"

### After Posting — Karma Tracking

Once a comment is posted and its `reddit_comment_url` is saved, the system automatically monitors it:

| Check | Frequency | What It Does |
|-------|-----------|--------------|
| Karma score | Every 4h | Fetches current upvote/downvote score |
| Removal detection | Every 4h | Checks if comment body is `[removed]` or `[deleted]` |
| Disappearance detection | Every 4h | If posted < 2 days ago and not found → likely removed |

**Tracking window:** 7 days from posting date. After 7 days, the comment is no longer actively checked (karma stabilizes by then).

**What happens on removal:**
- `is_deleted` flag set to `true`
- `deleted_detected_at` timestamp recorded
- Removal counted toward avatar's removal rate analytics
- If removal rate > 20% → warning in Avatar Intelligence panel

> See [Daily Operations → Posting Tracking](./daily-operations.md#posting-tracking--how-it-works) for full details on the tracking mechanism.

---

## EPG (Daily Publishing Program)

The EPG coordinates all stages into a daily plan per avatar:

```
Morning (08:00):
  1. Score new threads
  2. Select best threads for each avatar
  3. Assign time slots (spread across the day)
  4. Generate comments for each slot
  5. Drafts enter review queue

Throughout day:
  6. Reviewer approves/rejects
  7. Approved drafts posted at scheduled times

End of day (23:55):
  8. Ungenerated slots expire
  9. Stats logged
```

### EPG Slot Statuses

```
planned → generated → approved → posted
   │          │          │
   ▼          ▼          ▼
skipped    skipped    rejected
   │
   ▼
expired (end of day)
```

---

## Pipeline Safety Features

### Kill Switches

| Switch | What It Stops |
|--------|--------------|
| `pipeline_enabled` | Everything (scrape + score + generate) |
| `generation_enabled` | AI generation only |
| `scrape_enabled` | Subreddit scraping only |

### Avatar-Level Protection

- Frozen avatars excluded from all stages
- Shadowbanned avatars excluded before LLM calls
- Phase gates prevent inappropriate content
- Daily budget limits prevent over-posting

### Thread-Level Protection

- Locked threads skipped at scrape time
- Liveness re-checked before generation
- Stale drafts (for locked threads) auto-rejected
- Deduplication prevents double-commenting

### Content Safety

- Brand ratio check (max % of brand mentions per avatar per week)
- Promotional language detection
- Phase-appropriate content enforcement
- Text sanitization (strips formatting artifacts)

---

## Pipeline Timing

### Scheduled Runs

| Time | Pipeline | Avatars Affected |
|------|----------|-----------------|
| 08:00 | Full (score + generate) | All active Phase 2-3 avatars |
| 10:00 | Hobby only | All active Phase 1 avatars |
| 14:00 | Full (score + generate) | All active Phase 2-3 avatars |

### Manual Trigger

Admin can trigger pipeline anytime:
- Dashboard → "Run Pipeline" (all clients)
- Client detail → "Run Pipeline" (single client)
- Avatar workflow → "Rebuild EPG" (single avatar)

---

## Monitoring the Pipeline

### Healthy Pipeline Signs
- ✅ Scraping completes every 6h per subreddit
- ✅ Scoring runs at 08:00 and 14:00
- ✅ Drafts appear in review queue within 30 min of pipeline run
- ✅ No errors in activity feed
- ✅ All topology nodes green

### Warning Signs
- ⚠️ No new threads scored for 24h+
- ⚠️ Generation producing 0 drafts
- ⚠️ High rejection rate (>50%)
- ⚠️ Topology nodes yellow/red

### Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| No threads scraped | Reddit API issue or kill switch | Check `scrape_enabled`, check logs |
| Threads scored but no drafts | All threads below threshold | Lower scoring threshold or add keywords |
| Drafts generated but poor quality | Voice profile incomplete | Fill all voice profile fields |
| Drafts not appearing | Generation kill switch | Check `generation_enabled` |
| Everything stopped | Main kill switch | Check `pipeline_enabled` |
