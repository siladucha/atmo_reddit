# Reddit API Limits & Posting Capacity Analysis

## Date: May 28, 2026
## Version: 2.0 (incorporates behavioral detection & identity trust analysis)

---

## Core Insight

**The bottleneck is NOT API rate limits. The bottleneck is maintaining trusted Reddit identities at scale under adversarial platform conditions.**

RAMP is not a posting engine. It is a **trust simulation engine** — accumulating and preserving identity trust across a distributed set of managed accounts operating under continuous platform surveillance.

---

## 1. Reddit Rate Limits — API Layer (Not the Real Problem)

### API Request Limits (per OAuth app / client_id)

| Tier | Limit | Window | Notes |
|------|-------|--------|-------|
| OAuth authenticated | 100 QPM | Averaged over 10 min | Per client_id (app), not per account |
| Older docs / some sources | 60 QPM | Per minute | May be legacy or per-account |
| Unauthenticated | Rejected | — | Not supported anymore |

**Key insight:** Rate limits are tracked per OAuth client_id. Even 250 avatars at max posting volume = 2.8 API calls/minute. One OAuth app handles this trivially. API capacity is never the constraint.

### Write Action Limits (posting/commenting)

Reddit does NOT publish exact write limits. Based on community observations and PRAW documentation:

| Account State | Comment Cooldown | Practical Limit |
|---------------|-----------------|-----------------|
| New account (<7 days) | 10-15 min between comments | ~6-10/day |
| Low karma in subreddit | 10 min cooldown | ~6-10/day in that sub |
| Normal account (100+ karma) | No visible cooldown | ~50-100/day (soft) |
| High karma (1000+) | No cooldown | Unclear upper bound |

**Critical:** Reddit's "you are doing that too much" error is per-account AND per-subreddit. An account with 500 karma globally but 0 karma in r/cybersecurity will still get rate-limited in that specific subreddit.

### CQS (Contributor Quality Score) — Reddit's Hidden Throttle

Reddit assigns each account a CQS level: `high`, `medium`, `low`, `lowest`. This is NOT publicly documented but affects:
- Comment visibility (low CQS = comments may be auto-collapsed)
- Rate limiting (lowest CQS = severe write restrictions)
- Account standing (lowest CQS can lead to shadowban)

Our system already monitors CQS (daily batch check at 06:30, auto-freeze on "lowest").

---

## 2. The Real Threat: Behavioral Graph Detection

### What Reddit Almost Certainly Builds

This is the actual risk surface — not API limits:

| Detection Layer | What Reddit Tracks | Risk to RAMP |
|----------------|-------------------|--------------|
| Account interaction graphs | Who replies to whom, who upvotes whom | Coordinated cluster detection |
| Subreddit overlap graphs | Which accounts appear in the same subs | Unnatural co-occurrence patterns |
| Timing correlation graphs | When accounts are active, posting cadence | Synchronized behavior detection |
| Semantic similarity graphs | Writing style, vocabulary, structure | LLM fingerprint detection |
| Growth curve analysis | How fast accounts gain karma | Unnatural acceleration patterns |
| Device/IP fingerprinting | Browser, OS, IP, session patterns | Shared infrastructure detection |
| Passive behavior analysis | Scroll, dwell time, voting, navigation | Absence of human browsing patterns |

### The Coordination Problem

The threat is NOT: "one avatar posts 8 comments/day."

The threat IS: "250 accounts behave as a coordinated influence cluster."

Signals that expose coordination:
- Identical LLM output patterns (sentence structure, vocabulary distribution)
- Identical active hours across accounts
- Similar subreddit trajectories (all enter r/cybersecurity within the same week)
- Parallel growth curves (all gain karma at similar rates)
- Linguistic fingerprints (same model = same stylistic tells)
- Absence of passive behavior (accounts that only post but never browse/vote/lurk)

### What This Means for Architecture

RAMP needs not just timing jitter, but **multi-dimensional entropy**:

| Entropy Layer | What It Diversifies | Implementation |
|--------------|--------------------|--------------------|
| Persona entropy | Writing style, vocabulary, opinion patterns | Already built (voice profiles, approach diversity) |
| Behavioral entropy | Posting times, frequency, day-of-week distribution | Timing engine + per-avatar schedules |
| Topic entropy | Subreddit selection, thread choice | EPG + hobby pipeline + subreddit rotation |
| Lifecycle entropy | Growth speed, phase transitions, activity gaps | Phase system + variable warming speeds |
| Semantic entropy | LLM output diversification | Approach rotation + temperature variation + model mixing |

**Missing (not yet built):**
- Anti-correlation strategy (ensure avatars DON'T cluster in behavior)
- Passive behavior simulation (voting, browsing patterns via API)
- Semantic fingerprint diversification (vary LLM parameters per avatar)
- Lifecycle staggering (avatars enter subreddits at different times)

---

## 3. Corrected Capacity Targets

### Production Posting Limits (Conservative)

Previous analysis used "50-100 comments/day" as normal account capacity. This is technically possible for a real human but **dangerously high for managed synthetic identities**.

| Avatar Type | Target/day | Hard Ceiling | Rationale |
|-------------|-----------|-------------|-----------|
| Phase 1 (warming) | 2-3 hobby only | 5 | Building trust, zero brand exposure |
| Phase 2 (seeding) | 3-5 mixed | 7 | Establishing presence, low risk |
| Phase 3 (brand) | 4-6 mixed | 8 | Full operation, proven trust |
| Mentor (phase 0) | 1-2 | 3 | High-value, maximum caution |
| High-risk subreddits (cyber, AI, finance) | 1-2 per sub | 3 per sub | Aggressive moderation |

### Per-Avatar API Calls (Corrected)

| Operation | API Calls | Notes |
|-----------|-----------|-------|
| Post 1 comment | 1 (submission.reply or comment.reply) | Write action |
| Verify thread exists/not locked | 1 (fetch submission) | Read action |
| IP resolution (daily, not per-post) | 0 Reddit calls | External service |
| **Total per comment** | **2 Reddit API calls** | |
| **Total per avatar/day (5 comments avg)** | **10 Reddit API calls** | |

### Scaling Table — Corrected

| Avatars | Avg comments/day | Reddit API calls/day | QPM load | OAuth apps |
|---------|-----------------|---------------------|----------|-----------|
| 5 | 25 | 50 | 0.03 | 1 |
| 10 | 50 | 100 | 0.07 | 1 |
| 25 | 125 | 250 | 0.17 | 1 |
| 50 | 250 | 500 | 0.35 | 1 |
| 100 | 500 | 1,000 | 0.69 | 1 |
| 250 | 1,250 | 2,500 | 1.74 | 1 (still fine) |

**Conclusion:** Even at 250 avatars, one OAuth app at 100 QPM is 57× more capacity than needed. API is irrelevant.

---

## 4. Full Cycle — Proxy Posting

### Execution Flow

```
EPG generates daily program (08:00 local)
    ↓
Admin/client reviews & approves EPG (morning)
    ↓
Scheduler calculates jittered execution times per slot
    ↓
Celery dispatches post_comment task at calculated time (eta)
    ↓
Safety gates: kill switch → mode → frozen → health → CQS → phase → daily cap → proxy → IP
    ↓
PRAW client created (avatar's proxy + OAuth + user-agent)
    ↓
Thread liveness check (not locked/removed)
    ↓
Comment submitted via Reddit API (submission.reply or comment.reply)
    ↓
PostingEvent audit record created
    ↓
Draft status → posted, avatar.last_posted_at updated
    ↓
On error: classify → retry (transient) or freeze (auth/ban/consecutive)
```

### Entropy Measures in Proxy Flow

| Measure | How Applied |
|---------|-------------|
| Timing jitter | ±30% of interval between slots, cryptographic random |
| Active hours | 08:00-23:00 in avatar's declared timezone (varies per avatar) |
| Peak bias | 2× weight for 12-14, 18-22 local time |
| Min interval | 45-90 min between posts (randomized within range) |
| Day-of-week variation | Not all avatars post every day (EPG decides) |
| Subreddit rotation | Never same subreddit twice in a row |
| Approach diversity | Karma-gated rotation, max 2 identical in a row |

### What's Missing (Behavioral Entropy Gaps)

| Gap | Risk | Mitigation (future) |
|-----|------|---------------------|
| No passive behavior | Account only posts, never browses | Simulate read sessions via API (fetch posts without commenting) |
| No voting behavior | Real users upvote/downvote | Add periodic voting on non-target threads |
| Identical growth curves | All avatars gain karma at similar pace | Stagger warming start dates, vary daily volume |
| LLM semantic fingerprint | Claude Sonnet has detectable patterns | Mix models per avatar, vary temperature, inject persona-specific vocabulary |
| No session simulation | API calls are atomic, no "browsing session" | Group API calls into session-like bursts with dwell time |
| Subreddit entry timing | Multiple avatars enter same sub simultaneously | Stagger subreddit onboarding by 1-2 weeks per avatar |

---

## 5. Full Cycle — Mobile/PWA Posting

### Execution Flow

```
EPG generates daily program (08:00 local)
    ↓
Admin/client reviews & approves EPG (morning)
    ↓
Push notification sent to avatar owner (Web Push)
    ↓
Owner opens PWA → sees queue sorted by priority
    ↓
Owner taps comment → sees full text + thread link
    ↓
Owner long-presses to copy text
    ↓
Owner taps "Open Reddit" → browser opens thread
    ↓
Owner pastes comment → submits on Reddit
    ↓
Owner returns to PWA → confirms "Posted ✓"
    ↓
System logs: posted_at, posting_speed_seconds, source='pwa'
    ↓
Reminder if pending >4h, escalation if >8h
```

### Why Mobile Path is NOT Just a Fallback

Mobile/PWA posting is **trust preservation infrastructure**:

| Use Case | Why Human Posting is Superior |
|----------|-------------------------------|
| Account warming (Phase 1) | Real device, real IP, real browsing session = maximum trust signals |
| Mentor accounts | Too valuable to risk on automation |
| Post-ban rehabilitation | Account needs to demonstrate "real human" behavior |
| High-value enterprise clients | Zero tolerance for detection risk |
| Recovery mode | After CQS drop, human posting rebuilds trust faster |
| New subreddit entry | First 5-10 comments in a new sub should be human-posted |

**Strategic framing:** Mobile path is not "expensive backup." It is the **human legitimacy layer** — the mechanism that generates the trust signals that automated posting cannot produce.

### Workforce Scaling (Non-Linear Reality)

Linear math (workers × rate = output) breaks down after ~20 workers:

| Scale | Workers | Hidden Costs |
|-------|---------|-------------|
| 1-5 | 1 part-time | Manageable, direct oversight |
| 5-15 | 2-3 | Scheduling coordination needed |
| 15-30 | 5-8 | QA overhead, ghost posting risk, fraud detection needed |
| 30-50 | 10-15 | Miniature BPO operation: shift management, training, turnover |
| 50+ | 17+ | Full ops team needed, coordination lag, inconsistency |

**Realistic costs (including overhead):**

| Avatars | Workers | Direct cost/mo | Overhead/mo | Total/mo |
|---------|---------|---------------|-------------|----------|
| 5 | 1 | $200-300 | $0 | $200-300 |
| 10 | 1-2 | $400-600 | $0 | $400-600 |
| 25 | 3-4 | $900-1,200 | $200 | $1,100-1,400 |
| 50 | 5-7 | $1,500-2,100 | $500 | $2,000-2,600 |
| 100 | 10-14 | $3,000-4,200 | $1,500 | $4,500-5,700 |

---

## 6. Identity Lifecycle Model

### Trust Accumulation Phases

```
[Birth] → [Warming] → [Establishing] → [Operating] → [Mature]
  0-7d      1-8 weeks    2-4 months      4-12 months    12+ months
```

| Phase | Posting Mode | Volume | Behavior Profile |
|-------|-------------|--------|-----------------|
| Birth (0-7d) | Manual ONLY | 1-2/day, hobby only | Browsing, voting, subscribing to subs |
| Warming (1-8 weeks) | Manual preferred | 2-3/day, hobby only | Building subreddit karma, varied activity |
| Establishing (2-4 months) | Hybrid (manual + auto) | 3-5/day, mixed | Consistent presence, some brand-adjacent |
| Operating (4-12 months) | Auto primary | 4-6/day, full program | Proven trust, stable CQS, brand integration |
| Mature (12+ months) | Auto with caution | 3-5/day, strategic | High-value, reduce volume, increase quality |

### Anti-Correlation Strategy (Not Yet Built)

To prevent cluster detection, avatars must NOT:
- Enter the same subreddit in the same week
- Post at the same time of day (even with jitter)
- Use the same comment approaches in the same threads
- Gain karma at the same rate
- Have overlapping subreddit portfolios beyond 30%

**Implementation concept:**
```python
# Before assigning subreddit to avatar, check:
# 1. How many other avatars are already active there?
# 2. When did the last avatar enter this sub?
# 3. What's the overlap % with other avatars' sub portfolios?
# If overlap > 30% or entry < 2 weeks ago → defer or choose different sub
```

---

## 7. OAuth App Strategy

### Reddit's Responsible Builder Policy

Key constraint: "registering multiple accounts or submitting multiple requests for the same use case" is prohibited.

### Defensible Architecture

| Approach | Legal Risk | Operational Risk | Recommendation |
|----------|-----------|-----------------|----------------|
| 1 app for everything | None | Single point of failure | Start here |
| 1 app per client | Low (different use cases) | Manageable | Scale to this |
| Multiple apps per client | High (circumvention) | Complex | Never do this |

**Strategy:**
- **Phase 1 (MVP):** 1 OAuth app. All avatars. Simple.
- **Phase 2 (5+ clients):** 1 app per client tenant. Defensible as "each client is a separate application."
- **Phase 3 (enterprise):** Client brings their own OAuth app (self-service model). Maximum isolation.

**Per-app avatar limits (self-imposed):**
- Soft limit: 20 avatars per app
- Hard limit: 50 avatars per app
- Rationale: if app gets flagged, blast radius is contained

### Multi-Tenant Isolation as Security Feature

```
Client A → OAuth App A → Proxy Pool A → Avatar Set A
Client B → OAuth App B → Proxy Pool B → Avatar Set B
Client C → OAuth App C → Proxy Pool C → Avatar Set C
```

No shared infrastructure between clients at the Reddit-facing layer:
- Different OAuth credentials
- Different proxy IPs
- Different user-agents
- Different posting schedules
- Different subreddit portfolios

If Client A's avatars get detected → zero impact on Client B.

---

## 8. Passive Behavior Gap (Critical Missing Piece)

### The Problem

Reddit sees more than posting. A real user:
- Browses subreddits (page views)
- Reads threads (dwell time)
- Votes on content (upvotes/downvotes)
- Subscribes/unsubscribes
- Collapses/expands comments
- Saves posts
- Occasionally messages

An automated avatar that ONLY posts comments is a red flag. It has no "life" between posts.

### What We Can Simulate via API

| Action | API Endpoint | Detectable? | Value |
|--------|-------------|-------------|-------|
| Upvote posts | POST /api/vote | Low risk | Simulates engagement |
| Subscribe to subreddits | POST /api/subscribe | Low risk | Simulates interest |
| Save posts | POST /api/save | Low risk | Simulates bookmarking |
| Read threads (fetch) | GET /comments/{id} | Minimal | Creates read history |
| Browse subreddit (fetch) | GET /r/{sub}/hot | Minimal | Creates browse pattern |

### What We CANNOT Simulate

| Action | Why Not |
|--------|---------|
| Scroll behavior | Only visible in browser, not API |
| Dwell time | Only visible in browser, not API |
| Click patterns | Only visible in browser, not API |
| Session duration | Partially (can space API calls) |
| Mobile app usage | Would need actual app sessions |

### Recommendation

**Phase 1 (now):** Don't simulate passive behavior. Focus on posting quality and timing.

**Phase 2 (10+ clients):** Add periodic "browse sessions" — fetch 5-10 posts from subscribed subreddits, upvote 1-2, between posting actions. Low cost, adds behavioral depth.

**Phase 3 (scale):** Consider whether mobile/PWA path naturally generates passive behavior (it does — human browses Reddit to find the thread, generating real session data).

---

## 9. Risk Matrix (Revised)

| Risk | Probability | Impact | Proxy Exposure | Mobile Exposure | Mitigation |
|------|------------|--------|---------------|-----------------|-----------|
| OAuth app banned | Low (if 1 app/client) | High (all avatars on that app) | HIGH | None | Per-client app isolation |
| Behavioral cluster detection | Medium (at 50+ avatars) | Critical (mass ban) | HIGH | Very low | Anti-correlation, entropy layers |
| CQS degradation | Medium | Medium (rate limited) | Same | Same | Monitor + auto-freeze + quality focus |
| Proxy IP flagged | Low (residential) | Low (single avatar) | Medium | None | IP consistency check, provider diversity |
| LLM fingerprint detection | Unknown (emerging) | High (pattern = all avatars) | HIGH | None | Model mixing, temperature variation |
| Subreddit mod ban | Medium | Low (single sub) | Same | Same | Rule compliance, subreddit intel |
| Reddit policy change | Low-Medium | Critical | HIGH | Low | Mobile path as insurance |
| Worker fraud/ghost posting | N/A | N/A | None | Medium | Confirmation verification, spot checks |
| Coordinated timing detection | Medium | High | HIGH | Very low | Lifecycle staggering, timezone diversity |

### Worst-Case Scenarios (Revised)

**Proxy worst case:** Reddit deploys ML classifier for automated posting behavior → detects LLM-generated comments across multiple accounts → mass suspension of 50+ avatars simultaneously. Recovery: 2-4 weeks to warm new accounts. Revenue impact: significant.

**Mobile worst case:** Key workers quit → 2-3 day posting gap → some schedule adherence loss. Recovery: 1-2 days to reassign. Revenue impact: minimal.

**Existential risk:** Reddit explicitly bans all third-party posting tools (like Twitter did). Mitigation: mobile path becomes the ONLY path. This is why it must exist.

---

## 10. Growth Strategy — Revised Hybrid Model

### Phase 1: MVP (5-10 avatars, 1-2 clients)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Primary posting | Proxy (auto) | Removes bottleneck, validates pipeline |
| Warming method | Manual (PWA) for first 2 weeks | Builds initial trust with real behavior |
| OAuth apps | 1 | Simple, sufficient |
| Proxy provider | 1 | Simple, sufficient |
| Daily volume | 3-5 per avatar | Conservative, safe |

### Phase 2: Growth (10-50 avatars, 3-10 clients)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Primary posting | Proxy for Phase 2+ avatars | Proven trust, safe to automate |
| Warming method | Manual for all new avatars (4-8 weeks) | Trust accumulation period |
| OAuth apps | 1 per client | Isolation, defensible |
| Proxy providers | 2 (failover) | Redundancy |
| Daily volume | 4-6 per avatar (Phase 3), 2-3 (Phase 1) | Phase-appropriate |
| Anti-correlation | Basic (subreddit staggering) | Prevent obvious clustering |

### Phase 3: Scale (50-250 avatars, 10-50 clients)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Primary posting | Proxy for established avatars | Efficiency at scale |
| Warming pool | 10-15 avatars always in manual warming | Pipeline of fresh trusted accounts |
| OAuth apps | 1 per client, max 20 avatars/app | Blast radius containment |
| Proxy providers | 2-3, geographic diversity | Match avatar timezones |
| Daily volume | 4-6 max, reduce for high-risk subs | Quality over quantity |
| Anti-correlation | Full (timing, subreddit, semantic) | Critical at this scale |
| Passive behavior | Browse sessions between posts | Behavioral depth |
| Semantic diversity | Model mixing per avatar | Prevent LLM fingerprinting |

### Phase 4: Enterprise (250+ avatars)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Architecture | Full client isolation (app + proxy + schedule) | Zero cross-client contamination |
| Warming | Dedicated warming team (3-5 workers) | Continuous trust pipeline |
| Detection monitoring | Automated anomaly detection on our side | Catch problems before Reddit does |
| Volume | Reduce to 3-4/day per avatar | Longevity over throughput |
| Passive simulation | Full browse + vote + save sessions | Behavioral realism |
| Semantic | Per-avatar LLM config (model, temperature, vocabulary constraints) | Unique fingerprint per identity |

---

## 11. Cost Comparison (Revised)

### At 50 Avatars (Phase 2-3 mix)

| Cost Category | Proxy Only | Mobile Only | Hybrid (35 auto + 15 manual) |
|--------------|-----------|-------------|-------------------------------|
| Proxy/routing | $125/mo | $0 | $87.50/mo |
| Workforce | $0 | $2,000-2,600/mo | $600-900/mo |
| LLM (generation) | $162/mo | $162/mo | $162/mo |
| Infrastructure | $27/mo | $27/mo | $27/mo |
| **Total ops** | **$314/mo** | **$2,189-2,789/mo** | **$876-1,176/mo** |
| Detection risk | Medium-High | Very Low | Low |
| Reliability | 100% | 90-95% | 97% |
| Trust quality | Medium | High | High |

### The Real Calculation: Risk-Adjusted Cost

| Model | Monthly cost | Expected avatar loss rate | Replacement cost | True monthly cost |
|-------|-------------|-------------------------|-----------------|-------------------|
| Proxy only | $314 | 5-10% (2-5 avatars/mo) | $200-500 per avatar warming | $714-2,814 |
| Mobile only | $2,400 | 1-2% (0-1 avatar/mo) | $100-200 | $2,400-2,600 |
| Hybrid | $1,000 | 2-3% (1-2 avatars/mo) | $150-300 | $1,150-1,600 |

**Hybrid wins on risk-adjusted basis** — lower detection rate means fewer avatars lost, which means less warming cost to replace them.

---

## 12. Implementation Priority (Revised)

```
Week 1-2:  Proxy posting engine (automated last-mile)
Week 3:    PWA posting interface (human last-mile)  
Week 4:    Hybrid mode (per-avatar posting_mode in admin)
Week 5:    Anti-correlation basics (subreddit staggering, lifecycle offsets)
Week 6+:   Passive behavior simulation, semantic diversity
```

Both systems share 80% of backend:
- EPG scheduling (already built)
- Safety gates (shared)
- Audit logging (shared)
- Kill switches (shared)
- Admin UI (shared dashboard)

The difference is the last mile:
- Proxy: Celery task → PRAW → Reddit API
- Mobile: Push notification → Human → Reddit browser → Confirm callback

Building both: ~10-12 days total (shared infrastructure).

---

## 13. Open Questions for Future Analysis

1. **Semantic fingerprint detection** — How detectable is Claude Sonnet output specifically? Should we mix Gemini/Claude/GPT per avatar to diversify linguistic patterns?

2. **Passive behavior ROI** — Does adding browse/vote sessions measurably reduce detection? No data yet. Need to A/B test with a small cohort.

3. **Warming duration optimization** — Is 4 weeks manual warming enough? Or do we need 8 weeks for high-risk subreddits? Need data from first 10 avatars.

4. **Cross-platform signals** — Does Reddit correlate accounts that share proxy IPs with other platforms? If so, proxy isolation must extend beyond Reddit.

5. **Reddit's ML investment** — How aggressively is Reddit investing in coordinated behavior detection? Their 2024 IPO + AI data deals suggest increasing platform integrity investment.

6. **Legal boundary** — At what scale does "content scheduling platform" become legally indistinguishable from "coordinated inauthentic behavior"? Need legal opinion at 100+ avatars.
