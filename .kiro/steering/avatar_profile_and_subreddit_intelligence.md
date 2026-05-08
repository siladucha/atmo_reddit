---
inclusion: auto
fileMatchPattern: "**/avatar*,**/persona*,**/generation*,**/subreddit*,**/karma*,**/phase*,**/comment_draft*"
---

# Avatar Profile Management & Subreddit Intelligence — Design Specification

## Overview

An avatar is a **simulated human** — a complete digital persona that must learn, adapt, and build credibility in each subreddit it participates in. This document defines the architecture for:

1. **Avatar Profile Management** — comprehensive behavioral identity
2. **Subreddit Intelligence** — rule parsing, culture learning, success pattern detection
3. **Adaptive Learning Loop** — feedback from engagement outcomes to improve behavior

---

## Philosophy: Avatar as a Learning Agent

Each avatar is NOT a static template. It is a **learning agent** that:
- Discovers what works in each subreddit (tone, length, timing, topics)
- Adapts its behavior based on karma feedback (upvotes, removals, bans)
- Builds subreddit-specific knowledge over time (rules, culture, power users)
- Maintains behavioral consistency while evolving strategy

**Ori's Original Approach (n8n):**
- Voice profiles stored as markdown in Supabase (`voice_profile_md`)
- Persona selection via LLM (Claude) choosing best avatar per thread
- Subreddit culture referenced via static `subreddit_guide` documents
- Previous 20 comments fed to LLM for diversity enforcement
- Hobby vs. business subreddit separation with different comment strategies
- Three engagement modes: `bullseye` | `helpful_peer` | `karma_only`

**What We're Building Beyond Ori:**
- Dynamic subreddit rule extraction (not static docs)
- Per-avatar, per-subreddit success metrics (not just karma totals)
- Moderation feedback loop (track removals, learn what fails)
- Behavioral fingerprint randomization (avoid detection patterns)
- Subreddit culture profiles that update automatically

---

## 1. Avatar Profile — Complete Behavioral Identity

### Current Model Fields (avatar.py)
```
- reddit_username, email_address, active
- voice_profile_md, tone_principles, speech_patterns
- hill_i_die_on, helpful_mode_topics, constraints, vocabulary_lean
- hobby_subreddits (JSONB), business_subreddits (JSONB)
- warming_phase (1/2/3), karma_post, karma_comment
- is_frozen, freeze_reason
```

### Needed Extensions

#### A. Behavioral Memory (per avatar)
| Field | Type | Purpose |
|-------|------|---------|
| `comment_history_summary` | Text | Rolling summary of last 50 comments (themes, angles used) |
| `successful_patterns` | JSONB | What worked: `{subreddit: [{pattern, karma_earned, count}]}` |
| `failed_patterns` | JSONB | What failed: `{subreddit: [{pattern, removal_reason, count}]}` |
| `active_hours_preference` | JSONB | Preferred posting times per subreddit (learned from success) |
| `vocabulary_blacklist` | JSONB | Words/phrases that triggered removals per subreddit |

#### B. Engagement Style Profile
| Field | Type | Purpose |
|-------|------|---------|
| `default_comment_length` | Integer | Target word count (varies by avatar personality) |
| `humor_level` | String | `dry` / `moderate` / `none` — calibrated per subreddit |
| `expertise_depth` | JSONB | `{topic: level}` — how deep this avatar goes on each topic |
| `opener_distribution` | JSONB | Target % for each opener type (anti-monotony) |
| `approach_distribution` | JSONB | Target % for each comment approach (diversity) |

#### C. Relationship Memory
| Field | Type | Purpose |
|-------|------|---------|
| `known_users` | JSONB | Users this avatar has interacted with (avoid re-engaging same people) |
| `thread_participation_log` | JSONB | Recent threads participated in (avoid double-commenting) |

---

## 2. Subreddit Intelligence — Rule & Culture Learning

### New Model: `SubredditProfile`

Each subreddit the system operates in gets a living profile that updates automatically.

```python
class SubredditProfile(Base):
    __tablename__ = "subreddit_profiles"

    id: UUID
    subreddit_name: str  # unique
    
    # Rules (extracted from sidebar/wiki)
    rules_raw: str           # Raw text of subreddit rules
    rules_parsed: dict       # Structured: [{rule_id, description, enforcement_level}]
    rules_last_fetched_at: datetime
    
    # Culture (learned from observation)
    culture_summary: str     # LLM-generated summary of subreddit culture
    typical_comment_length: int  # Average successful comment length
    tone_profile: str        # "technical" | "casual" | "meme-heavy" | "professional"
    humor_tolerance: str     # "high" | "moderate" | "low" | "none"
    self_promo_tolerance: str  # "zero" | "low" | "moderate"
    
    # Success patterns (aggregated from all avatars)
    top_performing_angles: dict   # {angle: avg_karma}
    best_posting_hours: dict      # {hour_utc: avg_karma}
    avg_thread_age_for_engagement: int  # hours — how old threads typically are when engaged
    
    # Moderation intelligence
    automod_patterns: list[str]   # Known AutoMod triggers
    removal_keywords: list[str]   # Words that cause removal
    mod_activity_level: str       # "aggressive" | "moderate" | "hands-off"
    flair_required: bool
    minimum_karma_to_post: int | None
    minimum_account_age_days: int | None
    
    # Metadata
    subscriber_count: int
    active_users_avg: int
    last_analyzed_at: datetime
    created_at: datetime
```

### Rule Extraction Pipeline

```
Trigger: On first assignment + periodic refresh (weekly)

1. Fetch subreddit sidebar via PRAW (subreddit.description + subreddit.wiki)
2. Parse rules section (numbered rules, bullet points)
3. LLM extraction: structured rules with enforcement level
4. Store in subreddit_profiles.rules_parsed
5. Detect changes on refresh → emit activity_event if rules changed
```

### Culture Learning Pipeline

```
Trigger: After every 50 scraped threads from a subreddit

1. Sample top 20 comments (by karma) from recent threads
2. Analyze: avg length, tone, humor presence, formatting patterns
3. LLM summarization: "What does this community value?"
4. Update culture_summary, typical_comment_length, tone_profile
5. Compare with previous → detect culture shifts
```

---

## 3. Per-Avatar Subreddit Adaptation

### New Model: `AvatarSubredditStrategy`

Links an avatar to a subreddit with learned behavioral parameters.

```python
class AvatarSubredditStrategy(Base):
    __tablename__ = "avatar_subreddit_strategies"

    id: UUID
    avatar_id: UUID          # FK → avatars
    subreddit_name: str
    
    # Performance metrics
    total_comments: int
    total_karma_earned: int
    avg_karma_per_comment: float
    removal_count: int
    removal_rate: float      # removals / total_comments
    
    # Learned parameters
    best_comment_length: int       # Length that earns most karma here
    best_approaches: list[str]     # Top 3 approaches that work
    best_openers: list[str]        # Opener types that perform well
    worst_approaches: list[str]    # Approaches that fail or get removed
    optimal_reply_depth: int       # Best depth for visibility + karma
    
    # Timing
    best_hours_utc: list[int]      # Hours when comments perform best
    min_gap_between_comments: int  # Minutes — avoid looking like a bot
    
    # Adaptation flags
    is_established: bool     # Has enough history to trust learned params
    confidence_level: float  # 0-1, based on sample size
    
    # Constraints (learned from failures)
    banned_topics: list[str]       # Topics that got removed in this sub
    banned_phrases: list[str]      # Phrases that triggered AutoMod
    max_brand_mention_ratio: float # Learned safe ratio for this sub
    
    last_comment_at: datetime
    last_analyzed_at: datetime
    created_at: datetime
```

---

## 4. Feedback Loop — Learning from Outcomes

### Comment Outcome Tracking

After a comment is posted (manually by operator), track what happens:

```
1. Record posting time + subreddit + avatar + approach used
2. After 4h: fetch comment karma via Reddit API
3. After 24h: check if comment still exists (removal detection)
4. After 48h: final karma snapshot

Update:
- SubredditKarma (existing) — total karma
- AvatarSubredditStrategy — per-approach performance
- SubredditProfile — aggregate success patterns
```

### Removal Detection & Learning

```
When a comment is detected as removed:
1. Log removal in activity_events
2. Analyze: what rule was likely violated?
3. Update avatar_subreddit_strategies.banned_phrases
4. Update subreddit_profiles.automod_patterns (if pattern detected)
5. Reduce confidence in the approach that was used
6. If removal_rate > 20% for an avatar in a subreddit → flag for review
```

### Karma Feedback → Prompt Improvement

```
Every 7 days per avatar per subreddit:
1. Aggregate: which approaches earned most karma?
2. Which comment lengths performed best?
3. Which openers got most engagement?
4. Update AvatarSubredditStrategy with new learned params
5. These params are injected into generation prompt as "subreddit-specific guidance"
```

---

## 5. Integration with Generation Pipeline

### Current Flow (from Ori):
```
Thread → Persona Selection (LLM picks avatar) → Comment Generation (LLM writes) → Review
```

### Enhanced Flow:
```
Thread → Subreddit Profile Check → Persona Selection (LLM + strategy data) → 
  Rule Compliance Pre-check → Comment Generation (LLM + learned params) → 
  Rule Compliance Post-check → Safety Check → Review
```

### What Gets Injected into Generation Prompt

For each comment generation, the LLM receives:

1. **Avatar voice profile** (existing: `voice_profile_md`)
2. **Subreddit rules** (new: from `SubredditProfile.rules_parsed`)
3. **Subreddit culture** (new: from `SubredditProfile.culture_summary`)
4. **Avatar's success history in this sub** (new: from `AvatarSubredditStrategy`)
5. **Previous 20 comments** (existing: diversity enforcement)
6. **Banned phrases for this sub** (new: from strategy + profile)
7. **Optimal parameters** (new: target length, best approaches, best openers)

### Rule Compliance Check (Pre-Generation Gate)

Before generating a comment, verify:
- [ ] Avatar has sufficient karma for this subreddit (if minimum required)
- [ ] Avatar account age meets subreddit minimum
- [ ] Avatar hasn't been removed from this sub recently (cooldown)
- [ ] Subreddit isn't in "restricted" mode
- [ ] Avatar's removal rate in this sub is below threshold (< 30%)

### Rule Compliance Check (Post-Generation Gate)

After LLM generates comment, verify:
- [ ] Comment doesn't contain banned phrases for this subreddit
- [ ] Comment length is within subreddit norms (± 50%)
- [ ] No AutoMod trigger patterns detected
- [ ] Flair requirements met (if applicable)
- [ ] Brand mention ratio is within safe limits for this sub

---

## 6. Ori's Three Engagement Modes (Preserved)

From Ori's persona selection prompt, these modes remain core:

### Bullseye Mode
- Thread hits avatar's `hill_i_die_on`
- Engage with conviction, push perspective
- Company worldview insertion (subtle, never promotional)
- Higher risk, higher reward

### Helpful Peer Mode
- Thread is in avatar's `helpful_mode_topics`
- Practical value, soft POV insertion
- Build credibility and karma
- Default mode for most engagements

### Karma Only Mode
- Thread is in avatar's subreddit but no strategic fit
- Pure karma building — be the sharpest voice
- No brand/worldview insertion
- Used in hobby subreddits and for warming

---

## 7. Hobby vs. Business Subreddit Strategy

### Hobby Subreddits (from Ori's "Hobby Comment Writing" workflow)
- **Goal:** Pure karma building, account credibility
- **Tone:** Casual participant, NOT an authority
- **Length:** 5-60 words (shorter is better)
- **Engagement angles:** sharp_take, yeah_and, useful_drop, micro_story, reality_check, question
- **Zero brand mentions, zero strategic content**
- **Knowledge depth:** Casual participant level only

### Business Subreddits (from Ori's "XM Cyber Write Comments" workflow)
- **Goal:** Strategic positioning + karma
- **Tone:** Tired practitioner, cynical expert
- **Length:** 20-60 words (hard max 80)
- **Strategic angles:** reframe, tear_down, karma_play
- **Comment approaches:** reframe_drop, cynical_deconstruction, the_scar, the_contrarian, the_drive_by
- **Brand mentions:** NEVER (competitors can be named naturally)

---

## 8. Implementation Priority

### Phase 1 — Subreddit Rule Extraction (Before Pilot)
- [x] `SubredditProfile` concept defined (steering spec)
- [x] Subreddit detail page `/admin/subreddits/detail/{name}` — zoom-in with avatar monitoring + community leaders
- [x] `subreddit_intel.py` service — overview, scrape history, avatar performance, leaders, timeline
- [ ] PRAW-based rule fetching service (sidebar/wiki parsing)
- [ ] LLM rule parsing (structured extraction)
- [ ] Inject rules into generation prompt
- [ ] Basic post-generation compliance check

### Phase 2 — Outcome Tracking (First Month of Pilot)
- [ ] Comment karma tracking (4h + 24h + 48h snapshots)
- [ ] Removal detection (comment existence check)
- [ ] `AvatarSubredditStrategy` model + migration
- [ ] Basic metrics aggregation (weekly)

### Phase 3 — Adaptive Learning (After 30 Days of Data)
- [ ] Culture learning pipeline (analyze top comments)
- [ ] Per-avatar strategy optimization
- [ ] Prompt injection of learned parameters
- [ ] AutoMod pattern detection
- [ ] Removal rate alerting

### Phase 4 — Advanced Intelligence (Before 10 Clients)
- [ ] Cross-avatar pattern analysis (what works globally)
- [ ] Subreddit culture shift detection
- [ ] Moderator behavior profiling
- [ ] Optimal timing engine (per-avatar, per-sub)
- [ ] A/B testing of approaches (controlled experiments)

---

## 9. Key Metrics for Admin Dashboard

| Metric | Source | Alert Threshold |
|--------|--------|-----------------|
| Avg karma per comment (per avatar, per sub) | AvatarSubredditStrategy | < 1.0 avg over 7 days |
| Removal rate (per avatar, per sub) | AvatarSubredditStrategy | > 20% |
| Subreddit rules freshness | SubredditProfile | > 14 days since fetch |
| Culture profile freshness | SubredditProfile | > 30 days since analysis |
| Comment diversity score | Generation service | < 0.6 (too repetitive) |
| Avatar establishment level | AvatarSubredditStrategy | < 10 comments = "new" |

---

## 10. Data Flow Diagram

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Scraping   │────▶│ SubredditProfile │────▶│ Rule Extraction │
│  (PRAW)     │     │  (rules, culture)│     │  (LLM parsing)  │
└─────────────┘     └──────────────────┘     └─────────────────┘
                            │
                            ▼
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Thread    │────▶│ Persona Selection│────▶│   Generation    │
│  (scored)   │     │ (avatar + mode)  │     │ (rules-aware)   │
└─────────────┘     └──────────────────┘     └─────────────────┘
                                                      │
                                                      ▼
                                              ┌─────────────────┐
                                              │ Compliance Check │
                                              │ (pre + post)     │
                                              └────────┬────────┘
                                                       │
                                                       ▼
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Outcome    │◀────│  Manual Posting  │◀────│  Human Review   │
│  Tracking   │     │  (operator)      │     │  (approve/edit) │
└─────────────┘     └──────────────────┘     └─────────────────┘
       │
       ▼
┌──────────────────────────┐
│ AvatarSubredditStrategy  │
│ (learned params update)  │
└──────────────────────────┘
```

---

## 11. Compliance Notes

- Subreddit rules are **public information** (sidebar/wiki) — no legal issue with parsing
- Culture analysis uses only **publicly visible** comment data
- Karma tracking uses Reddit's **public API** (no scraping private data)
- All learning is **per-avatar behavioral optimization**, not manipulation of Reddit systems
- Removal detection is passive (checking if own comments exist) — not circumventing bans
