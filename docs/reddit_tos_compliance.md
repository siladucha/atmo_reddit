# Reddit ToS Compliance — System Architecture Analysis

**Date:** May 2026
**Author:** Max (tech review)
**Status:** Internal reference document

---

## 1. Automation vs Human Approval

### Automated (read-only Reddit API usage):
- Scraping posts from subreddits (PRAW `subreddit.hot()`)
- AI scoring of threads (relevance/quality/strategic)
- AI generation of comment drafts
- Avatar status checks (shadowban detection)
- Karma tracking

### Requires human approval:
- Every comment goes through review queue: `pending → approved/rejected → posted`
- Operator manually approves or edits each draft
- **Posting is entirely manual.** There is no PRAW write method call anywhere in the codebase.

**Conclusion:** The system is a content suggestion engine with human-in-the-loop. Reddit API is used exclusively for reading.

---

## 2. Autoposting

**No autoposting exists.** Confirmed by full codebase search:
- No `praw.comment.reply()`, `submission.reply()`, `subreddit.submit()`
- No functions named `post_comment`, `submit_comment`, `auto_post`
- The `posted` status on CommentDraft is set by the operator manually after they copy the text and paste it into Reddit via browser

This is a key architectural decision: **the system never writes to Reddit via API.**

---

## 3. Coordinated Manipulation — Prevention Mechanisms

### Architectural constraints (implemented in `services/safety.py`):

| Mechanism | Implementation |
|----------|---------------|
| Max 2 comments per subreddit/day/avatar | `MAX_COMMENTS_PER_SUBREDDIT_DAY = 2` |
| Max 8 comments/day per avatar | `MAX_COMMENTS_PER_DAY = 8` |
| Min 15 minutes between comments | `MIN_MINUTES_BETWEEN_COMMENTS = 15` |
| Brand ratio ≤ 30% per week | `MAX_BRAND_RATIO = 0.3` |
| Max 1 link per week | `MAX_LINKS_PER_WEEK = 1` |
| Phase 1 (months 1-2): zero brand mentions | PhasePolicy blocks any brand content |
| Phase 2 (months 3-4): external citations only | No direct brand links |
| Phase 3 (month 5+): ramp-up (1 mention → 10% → 30%) | `RampUpStage: early/mid/complete` |

### No cross-avatar coordination:
- Avatars do not upvote each other's posts (upvote coordination deferred indefinitely)
- No mechanism for "multiple avatars comment on the same thread"
- Subreddit-centric architecture (see section 9) prevents clustering

---

## 4. Sanctions / Cooldowns / Internal Safety Rules

### Safety check pipeline (`services/safety.py`):

```
check_avatar_can_post() performs 6 checks:
1. Avatar active + not shadowbanned
2. Phase policy (PhasePolicy.check_comment_allowed)
3. Daily comment limit (8/day)
4. Type-specific limit (5 professional, 5 hobby)
5. Minimum time gap (15 min)
6. Brand ratio check (≤30% per week)
```

### Sanctions:
- `quarantine_avatar()` — deactivates avatar with audit trail
- `PolicyStatus.blocked` — comment is not generated
- `PolicyStatus.requires_review` — requires manual review
- Promotional content detection (`check_comment_content`) — blocks "check out", "visit our", URLs

### Phase demotion:
- `PhaseEvaluator` can demote avatar phase (3→2, 2→1) on violations
- Piggyback evaluation — phase check on every safety check

### Content safety:
- Max 500 characters per comment
- Promotional language detection (list of banned phrases)
- Brand mention level classification: `explicit_brand_link > explicit_brand_name > inferred_brand`

---

## 5. What Happens If Reddit Bans the App?

### Current architecture:
- One Reddit OAuth app (shared credentials via PRAW)
- If app is banned — all scraping stops
- **But:** system does not write to Reddit, so app ban is unlikely (read-only usage)

### Mitigation (implemented):
- `reddit_status.py` — detects shadowban/suspension per avatar
- `MetricsCollector` — tracks rate limit headers
- Circuit breaker pattern (in health_metrics) — stops requests on cascading errors
- Activity events log all API errors

### Not yet implemented (from gap analysis):
- No global kill switch (emergency controls — specced, not coded)
- No per-avatar OAuth tokens (oauth-avatar-auth spec not implemented)
- No proxy rotation

---

## 6. One Reddit App or Multiple?

**Currently: one.** `get_reddit_client()` creates a single PRAW instance from env variables (`reddit_client_id`, `reddit_client_secret`).

**Planned (oauth-avatar-auth spec):** Per-avatar OAuth tokens. Not yet implemented.

**Risk:** One app = single point of failure. But since the app is used only for reading (scraping + status checks), ban risk is minimal. Reddit bans apps for write abuse, not for read.

---

## 7. Rate Limiting

### Reddit API level:
- Reddit allows 60 req/min per OAuth token
- `MetricsCollector` tracks `X-Ratelimit-Remaining` headers
- `_log_rate_limit()` in reddit.py logs state

### Application level:
- `ScrapeRateLimiter` — distributed rate limiter (Redis sorted set sliding window)
- `ScrapeDistributedLock` — prevents parallel scrape of same subreddit
- `queue_tick` every 60 seconds checks which subreddits are due for scraping (interval-based gating)

### Avatar level (safety.py):
- 8 comments/day max
- 15 min minimum gap
- 2 comments/subreddit/day
- 1 link/week

---

## 8. Why Subreddit-Centric Architecture Is Safer Than Avatar-Centric

### Avatar-centric (dangerous):
- Focus on "how to maximize avatar activity"
- Avatar visits many subreddits → pattern of "bot traversing forums"
- Easily detectable: one account commenting in 20 different subreddits per day
- Coordination between avatars visible through shared subreddits

### Subreddit-centric (current architecture):
- Focus on "what content is relevant for this subreddit"
- Scraping is organized by subreddits, not by avatars
- Each avatar is bound to 2-5 subreddits (like a real user)
- `MAX_COMMENTS_PER_SUBREDDIT_DAY = 2` — avatar doesn't dominate a subreddit
- Scoring considers subreddit context, not avatar goals
- Persona routing (planned) selects avatar FOR a thread, not thread FOR an avatar

**Result:** Each avatar's behavior looks like a normal user who reads 3-4 subreddits and occasionally comments. Not like a bot traversing Reddit by list.

---

## 9. Summary (for Tzvi / investor conversations)

> "The system does not post to Reddit automatically. It reads, analyzes, generates drafts — and a human decides what to publish. Each avatar is limited to 8 comments per day with 15-minute pauses. The first 2 months — zero brand mentions. This is a content intelligence tool, not a bot."

### Key talking points:
1. **No automated posting** — human approves every comment
2. **Phase-gated brand mentions** — 2 months of pure community engagement before any brand content
3. **Rate limits everywhere** — per-avatar, per-subreddit, per-day, per-type
4. **No coordination** — avatars operate independently, no upvote rings
5. **Read-only API usage** — Reddit app only scrapes, never writes
6. **Audit trail** — every safety check, every block, every phase transition is logged
7. **Subreddit-first** — architecture prevents detectable bot patterns

---

## Appendix: Code References

| Component | File | Purpose |
|-----------|------|---------|
| Safety checks | `app/services/safety.py` | All rate limits and content checks |
| Phase policy | `app/services/phase.py` | Phase-based content restrictions |
| Phase types | `app/services/phase_types.py` | PolicyStatus, BrandMentionLevel enums |
| Reddit client | `app/services/reddit.py` | PRAW read-only operations |
| Reddit status | `app/services/reddit_status.py` | Shadowban/suspension detection |
| Metrics collector | `app/services/metrics_collector.py` | Rate limit header tracking |
| Health metrics | `app/services/health_metrics.py` | Circuit breaker, API health |
| Karma tracker | `app/services/karma_tracker.py` | Per-subreddit karma tracking |
| Review workflow | `app/routes/review.py` | Human approval flow |
| Comment draft model | `app/models/comment_draft.py` | Status workflow: pending→approved→posted |
