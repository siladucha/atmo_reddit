# Avatar Capacity Report — Reddit API Limits Analysis

**Date:** May 31, 2026  
**Purpose:** Determine how many avatars the system can support daily given Reddit API constraints

---

## Reddit API Limits (Official)

| Constraint | Value | Source |
|-----------|-------|--------|
| Rate limit per OAuth token | **60 requests/min** (1,000/min for some apps) | Reddit API docs |
| Daily max (theoretical) | **86,400 req/day** per token | 60 × 1,440 min |
| Comment cooldown (new accounts) | ~10 min between comments | Reddit anti-spam |
| Comment cooldown (established) | None (but suspicious if too fast) | Behavioral |
| Max comments/day (safe) | ~50-80 per account before flags | Community knowledge |
| Subreddit-specific limits | Varies (some require min karma/age) | Per-subreddit |

---

## Our Current API Usage Per Avatar Per Day

### Scraping (shared, not per-avatar)
- **Not avatar-bound** — scraping uses a single read-only OAuth app
- 200 scrapes/day total (all subreddits, all clients)
- ~200 API calls/day for scraping

### Health Checks (per avatar)
- 2× daily (07:30, 13:30)
- Each check: 1 API call (fetch user profile + recent comments)
- **= 2 API calls/avatar/day**

### CQS Check (per avatar, weekly)
- 1× per 7 days
- 1 API call
- **= 0.14 API calls/avatar/day**

### Karma Tracking (per avatar)
- Every 4 hours = 6× daily
- Each: 1 API call (fetch user karma)
- **= 6 API calls/avatar/day**

### Presence Scan (per avatar, weekly)
- 1× per 7 days
- 1 API call (fetch 100 recent comments)
- **= 0.14 API calls/avatar/day**

### Profile Analytics (per avatar, daily)
- 1× daily (05:20)
- 1 API call
- **= 1 API call/avatar/day**

### Posting (per avatar) — FUTURE
- Phase 1: 3 comments/day
- Phase 2: 7 comments/day
- Phase 3: 18 comments/day
- Each post: 1 API call
- **= 3-18 API calls/avatar/day**

---

## Total API Calls Per Avatar Per Day

| Operation | Phase 1 | Phase 2 | Phase 3 |
|-----------|---------|---------|---------|
| Health checks | 2 | 2 | 2 |
| Karma tracking | 6 | 6 | 6 |
| Profile analytics | 1 | 1 | 1 |
| CQS (amortized) | 0.14 | 0.14 | 0.14 |
| Presence (amortized) | 0.14 | 0.14 | 0.14 |
| **Posting (comments)** | **3** | **7** | **18** |
| **TOTAL** | **~12** | **~16** | **~27** |

---

## Bottleneck Analysis

### Scenario 1: Single OAuth Token (current)

**Available:** 86,400 API calls/day (60/min × 1,440 min)  
**Scraping overhead:** ~200 calls/day (fixed)  
**Remaining for avatars:** ~86,200 calls/day

| Avatar Phase Mix | Avatars Supported | Daily API Calls |
|-----------------|-------------------|-----------------|
| All Phase 1 (12 calls/avatar) | **7,183** | 86,200 |
| All Phase 2 (16 calls/avatar) | **5,387** | 86,200 |
| All Phase 3 (27 calls/avatar) | **3,192** | 86,200 |
| Mixed (50 avatars: 20×P1, 20×P2, 10×P3) | **50** | 910 |
| Mixed (200 avatars: 80×P1, 80×P2, 40×P3) | **200** | 3,640 |

**Conclusion: API rate limit is NOT the bottleneck.** Even 200 avatars use only 4% of available capacity.

### Scenario 2: Posting Rate Limit (the REAL bottleneck)

Reddit doesn't officially publish per-account posting limits, but behavioral patterns suggest:

| Account Type | Safe Comment Rate | Risky Threshold |
|-------------|-------------------|-----------------|
| New (<1 month) | 1-3/day | >5/day |
| Established (1-6 months) | 5-10/day | >15/day |
| Mature (6+ months, high karma) | 10-20/day | >30/day |
| High-karma (1000+) | 20-50/day | >50/day |

**Our limits vs Reddit's tolerance:**

| Phase | Our Limit | Reddit Safe Zone | Status |
|-------|-----------|-----------------|--------|
| Phase 1 (3/day) | 3 | 1-3 (new accounts) | ⚠️ At edge |
| Phase 2 (7/day) | 7 | 5-10 (established) | ✅ Safe |
| Phase 3 (18/day) | 18 | 10-20 (mature) | ⚠️ At edge |

### Scenario 3: Timing Constraints (the ACTUAL bottleneck)

**Posting window:** 08:00–21:00 = **780 minutes**  
**Min gap between slots:** 45 minutes  

| Phase | Comments/day | Min time needed | Fits in window? |
|-------|-------------|-----------------|-----------------|
| Phase 1 | 3 | 3 × 45 = 135 min | ✅ Easily |
| Phase 2 | 7 | 7 × 45 = 315 min | ✅ Yes |
| Phase 3 | 18 | 18 × 45 = 810 min | ❌ **Exceeds 780 min window!** |

**Phase 3 problem:** 18 comments × 45 min gap = 810 min needed, but window is only 780 min.  
With jitter (±30 min), some slots will collide or fall outside window.

**Realistic Phase 3 capacity:** ~17 comments max in 780-min window with 45-min gaps.

---

## Per-Avatar Proxy Posting Capacity

When automated posting is implemented (per-avatar OAuth + proxy):

| Factor | Constraint | Impact |
|--------|-----------|--------|
| OAuth apps | 3-5 apps, max 3 avatars each | Max 15 avatars per app set |
| Proxy IPs | $2.50/mo per avatar | Linear cost scaling |
| Reddit rate limit | 60 req/min per OAuth app | Shared across 3 avatars |
| Per-avatar posting | 1 API call per comment | Negligible |

**Per OAuth app (3 avatars):**
- Worst case: 3 avatars × 18 comments = 54 posts/day
- API calls: 54 (posting) + 18 (health) + 18 (karma) = 90 calls/day
- Available: 86,400/day → **0.1% utilization**

---

## System-Wide Capacity Summary

### With 1 OAuth Token (read-only, current scraping)

| Avatars | Phase Mix | API Calls/Day | % of Limit | Status |
|---------|-----------|---------------|-----------|--------|
| 10 | 4×P1, 4×P2, 2×P3 | 362 | 0.4% | ✅ |
| 50 | 20×P1, 20×P2, 10×P3 | 1,110 | 1.3% | ✅ |
| 100 | 40×P1, 40×P2, 20×P3 | 2,220 | 2.6% | ✅ |
| 500 | 200×P1, 200×P2, 100×P3 | 11,100 | 12.8% | ✅ |
| 1000 | 400×P1, 400×P2, 200×P3 | 22,200 | 25.7% | ✅ |

### With Posting (per-avatar OAuth apps)

| OAuth Apps | Avatars | Posts/Day (max) | Status |
|-----------|---------|-----------------|--------|
| 1 app (3 avatars) | 3 | 54 | ✅ |
| 3 apps (9 avatars) | 9 | 162 | ✅ |
| 5 apps (15 avatars) | 15 | 270 | ✅ |
| 10 apps (30 avatars) | 30 | 540 | ✅ |
| 20 apps (60 avatars) | 60 | 1,080 | ✅ |

---

## Real Bottlenecks (Not API)

| Bottleneck | Limit | Impact | Solution |
|-----------|-------|--------|----------|
| **Behavioral detection** | Pattern analysis | Ban risk | Jitter, varied timing, human-like gaps |
| **Subreddit-specific limits** | 2 comments/sub/day | Limits per-sub density | More subreddits per avatar |
| **Brand ratio** | 30% max professional | Caps revenue-generating comments | More hobby padding |
| **Phase 3 timing** | 18 slots in 780 min | Can't fit with 45-min gaps | Reduce gap to 40 min or reduce budget to 16 |
| **LLM cost** | $1.17/client/day | Financial, not technical | Model optimization |
| **Human review** | ~150 drafts/day at 10 clients | Operator bandwidth | Auto-approve for trusted avatars |

---

## Recommendations

### Short-term (current scale: 10-50 avatars)
1. **No API concerns** — single token handles everything easily
2. **Fix Phase 3 timing conflict** — reduce to 16/day or reduce MIN_SLOT_GAP to 40 min
3. **Add jitter to MIN_MINUTES_BETWEEN_COMMENTS** — ±30% randomization

### Medium-term (50-200 avatars)
4. **Multiple OAuth apps for posting** — 5 apps × 3 avatars = 15 posting avatars
5. **Separate read token from posting tokens** — scraping on dedicated app
6. **Adaptive rate limiting** — slow down if 429s detected

### Long-term (200+ avatars)
7. **Per-avatar OAuth tokens** — each avatar authenticates independently
8. **Proxy rotation** — residential IPs per avatar ($2.50/mo each)
9. **Distributed posting workers** — separate Celery queues per OAuth app
10. **Budget Engine** — dynamic daily limits based on account age, karma, recent activity

---

## TL;DR

**Reddit API rate limit (60 req/min) is NOT the bottleneck.** Even 1,000 avatars would use only 26% of a single token's capacity.

**Key scaling insight:** Rate limits are **per-token**, not per-app. One web app can authorize unlimited avatars, each gets their own 60 req/min. Multiple apps exist for **risk isolation only** (if Reddit revokes an app, only avatars on that app are affected).

**Scaling strategy (in spec: `.kiro/specs/automated-proxy-posting/`):**
- Tier 1 (1-15 avatars): 3-5 apps × 3 avatars each — risk isolation
- Tier 2 (15-500 avatars): per-avatar OAuth tokens through shared web apps — unlimited capacity

**The real limits are:**
1. **Behavioral** — posting too fast/predictably triggers anti-spam
2. **Timing** — 45-min gaps × 18 posts doesn't fit in a 13-hour window
3. **Financial** — LLM costs ($1.17/client/day) scale linearly
4. **Human** — review queue bottleneck at 150+ drafts/day

**Bottom line:** We can technically support **500+ avatars** on API alone. The practical limit is **~60 posting avatars** (20 OAuth apps × 3 each) in Tier 1, or **unlimited** in Tier 2 with per-avatar tokens.
