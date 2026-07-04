# RAMP Community Module — Full Specification, Operating Model & Cost Analysis

**Date:** July 4, 2026
**Author:** Max (CTO)
**For:** Tzvi (CEO) — proposal preparation for real estate lead
**Status:** Ready for business decision

---

## Context

### Business Trigger

A real estate lead (7 US metros, budget-conscious) is interested in RAMP. During proposal preparation, Tzvi identified an opportunity to offer **client-owned subreddit management** as an add-on service. The client would own/moderate a subreddit and use RAMP to manage community operations.

### What RAMP Already Does

RAMP is a Reddit marketing platform that manages **outbound** content — AI-trained avatars post comments in third-party subreddits to build brand authority. The pipeline: scrape → score → generate → review → post → measure → learn.

### What This Module Adds

A new **inbound** capability: AI-assisted operations for the client's OWN subreddit. Moderation support, intent signal detection, community health monitoring, and content scheduling — all through the same RAMP dashboard the client already uses.

### The Closed Loop

This creates a unique value proposition no competitor offers:

```
OUTBOUND (existing RAMP):
  Avatars post in r/RealEstate, r/FirstTimeHomeBuyer → build authority

INBOUND (new Community Module):
  Client's own r/MiamiHomeBuyers → detect buyer intent, support moderation

SYNERGY:
  Avatars seed engagement IN client's sub → organic users respond →
  RAMP detects intent signals → client gets qualified leads
```

---

## Operating Model (Human-in-the-Loop)

### Core Principle

**RAMP does NOT manage subreddits.** Subreddit ownership and moderation authority ALWAYS belong to the human client (moderator/owner). RAMP is an AI-assisted decision and execution system that supports human moderation workflows.

### Responsibility Boundaries

#### Human (Client / Moderator) — THE AUTHORITY

Responsible for:
- Final approval of moderation actions
- Subreddit governance and policy decisions
- Bans, removals, appeals, enforcement decisions
- Risk ownership under Reddit rules
- Strategic content direction

Human is the only authority that can define "truth" in moderation decisions.

#### RAMP Intelligence Layer (Agent System)

RAMP is responsible for:
- Monitoring subreddit activity (posts, comments, mod queue)
- Detecting signals: spam / low quality / rule violations / purchase intent / research intent / engagement anomalies
- Producing structured recommendations: approve / remove / flag / escalate + intent classification
- Generating content suggestions for scheduled posts
- Tracking community health metrics

**RAMP does NOT execute irreversible actions autonomously by default.**

#### Execution Layer (Tooling)

RAMP provides execution tools under human authority. Two modes:

**A) Human-triggered execution (primary)**
- Human clicks action in RAMP UI
- RAMP executes via Reddit API (PRAW)
- Action is logged as human-approved

**B) Scheduled limited automation (restricted scope)**
- Only allowed for: scheduled content posts (content calendar) and pre-approved rule-based actions (opt-in)
- Auto-approve only for items matching client-configured whitelist (e.g., account_age > 1 year AND karma > 1000)
- Auto-remove is NEVER enabled by default — requires explicit client opt-in with signed acknowledgment
- No autonomous moderation removals without explicit configuration

### Browser Extension Role (IMPORTANT)

The browser extension is NOT part of subreddit moderation. It is used exclusively for outbound avatar execution (posting comments/posts as avatars). It does NOT: manage moderation, make governance decisions, or process intent signals.

Extension MAY be used for avatar posting INTO client's sub (as part of outbound seeding strategy). This is content pipeline, not moderation.

### Execution Safety Rule (Non-negotiable)

RAMP MUST NEVER:
- Claim ownership of subreddit decisions
- Execute moderation actions without human trigger (except explicitly scheduled posts)
- Present itself as autonomous moderator
- Bypass human review in moderation workflows

Every action (human-triggered or scheduled) is logged with: actor (human/scheduled_rule), timestamp, item_id, action_type, AI_confidence_at_time. Client can review full mod action history.

### Degraded Mode

If RAMP backend is unavailable, mod queue accumulates in Reddit natively. Client can always use Reddit's built-in mod tools directly. RAMP is an enhancement layer, not a dependency.

### Correct System Definition

> "An AI-assisted subreddit operations workspace that enhances human moderation and decision-making through intelligence, recommendations, and controlled execution tools."

NOT: "An AI system that manages or moderates subreddits."

---

## Architecture Decision

### PRAW API Path (not extension, not Devvit)

- Client adds a RAMP bot account as moderator on their subreddit
- RAMP executes all mod actions programmatically via Reddit API (PRAW)
- No extension needed for mod tasks. No Devvit app review process. Works immediately.
- Upgrade path to Devvit exists when scaling to 10+ clients

### Why Not Extension?

The browser extension is designed for avatar posting (one account per browser profile). Moderation requires a different account (the mod bot) which conflicts with the avatar execution flow. API path is cleaner: direct PRAW calls, no DOM dependencies, no executor needed.

### Why Not Devvit (Yet)?

Devvit is the ideal long-term platform (real-time triggers, zero credential management, Reddit-endorsed) but requires 5-6 weeks including Reddit app review. PRAW delivers same functionality faster. Rate limits not a concern at current scale (0.5 req/min per client vs. 60 req/min limit). Devvit becomes the upgrade path at 10+ community clients.

### Rate Limit Analysis

| Clients | Req/min (community) | Total RAMP req/min | Limit | Margin |
|---------|---------------------|-------------------|-------|--------|
| 1 (7 subs) | ~3.5 | ~12 | 60 | 5x |
| 5 clients | ~10 | ~18 | 60 | 3x |
| 10 clients | ~20 | ~28 | 60 | 2x |
| 20+ clients | ~40+ | ~48+ | 60 | ⚠️ Need second token or Devvit |

---

## Product Scope: 5 Components

### Component 0: Subreddit Strategy Generation (Foundation)

**What:** AI generates community strategy document during onboarding — moderation rules, flair taxonomy, content pillars, audience definition, intent signal types to detect.

**How:** Adapts existing Discovery Engine + Strategy Generator to community context:
1. Client provides: business type, target audience, subreddit topic
2. AI analyzes: similar subreddits, competitor communities, engagement patterns
3. Output: structured strategy document (moderation_rules, flair_taxonomy, content_pillars, forbidden_topics, intent_types)

**Reuses:** `discovery/strategy_generator.py`, `discovery/reddit_researcher.py`, `discovery/entity_extractor.py`

**When refreshed:** Monthly auto-refresh based on community health data + intent signal patterns.

---

### Component 1: Mod Queue Assistant

**What:** Displays mod queue with AI-suggestions. Client clicks to execute.

**Data Flow:**
```
PRAW poll (every 5 min) → subreddit.mod.modqueue(limit=50)
    → AI classify (Gemini Flash): spam/rule_violation/legitimate
    → Display with confidence badge
    → Client clicks Approve/Remove → PRAW executes
    → Action logged
```

**Actions available:**
| Action | PRAW Call | Reversible |
|--------|-----------|-----------|
| Approve | `item.mod.approve()` | Yes |
| Remove (spam) | `item.mod.remove(spam=True)` | Yes (can re-approve) |
| Remove (rule) | `item.mod.remove()` + removal message | Yes |
| Flair | `item.mod.flair(text=category)` | Yes |
| Lock | `item.mod.lock()` | Yes |

**Status:** Decision support system, not autonomous moderator.

---

### Component 2: Intent Signal System

**What:** AI detects buying/research/comparison intent in posts and comments.

**Data Flow:**
```
PRAW scan (every 30 min) → subreddit.new(25) + subreddit.comments(100)
    → Intent classifier (Gemini Flash)
    → Store IntentSignal record
    → Surface in dashboard feed
```

**Intent types:** purchase_intent, research, comparison, timeline, budget, location, objection, other

**Status:** Analytics layer only, no direct action authority.

---

### Component 3: Content Calendar

**What:** Scheduled recurring community threads posted by bot account.

**Data Flow:**
```
Content template (client configures) → Cron fires
    → AI fills template with context → PRAW subreddit.submit()
    → Auto-sticky + auto-flair → Track performance
```

**Status:** Semi-automated publishing tool under human configuration. Client defines WHAT and WHEN. AI generates the content. PRAW executes.

---

### Component 4: Community Health

**What:** Daily vital signs — growth, engagement, spam rate, response time.

**Data Flow:**
```
PRAW daily snapshot (subscribers, activity) → Aggregate → Store
    → Weekly delta calculation → Alerts on anomalies
```

**Status:** Observability layer only. No actions — just metrics and alerts.

---

## Avatar Tracking in Client's Sub

When RAMP avatars post in the client's subreddit (as part of outbound seeding):
- RAMP already tracks karma, removal rate, engagement per avatar per sub
- Devvit/PRAW observes organic replies to avatar's posts
- Intent signals from replies are attributed to avatar's seeding activity
- Dashboard shows ROI: "Avatar's market update → 15 comments → 3 high-intent signals"

This closes the loop: content seeding → community engagement → detectable leads.

Client knows which avatars are "theirs" (transparency, not hidden).

---

## Development Timeline

### Full scope: 5-6 weeks

| Week | Deliverable |
|------|-------------|
| 1 | Strategy generation (prompts, integration with Discovery) + PRAW mod queue integration |
| 2 | Mod Queue UI + AI classifier + action execution |
| 3 | Intent Signal system (classifier, model, scanning task, UI) |
| 4 | Content Calendar (model, scheduler, AI generation, UI) |
| 5 | Community Health (aggregation, metrics, alerts) + Portal view |
| 6 | Testing, bot account setup, documentation, deploy |

### Detailed effort

| Component | Hours | Days |
|-----------|-------|------|
| Subreddit Strategy Generation | 20h | 3-4 |
| Mod Queue (PRAW + AI + UI + actions) | 28h | 5-6 |
| Intent Signals (classifier + model + task + UI) | 24h | 4-5 |
| Content Calendar (model + scheduler + AI + UI) | 24h | 4-5 |
| Community Health (aggregation + UI + alerts) | 18h | 3-4 |
| Portal view (client-facing, scoped) | 11h | 2-3 |
| Integration (bot setup, testing, docs, deploy) | 15h | 2-3 |
| **Total** | **140h** | **24-30 days ≈ 5-6 weeks** |

### Phased delivery option

| Phase | Scope | ETA | Value |
|-------|-------|-----|-------|
| Phase 1 | Strategy + Mod Queue + Health | 2-3 weeks | Core ops value |
| Phase 2 | Intent Signals + Calendar | +2 weeks | Intelligence + content |
| Phase 3 | Portal + Polish | +1 week | Client self-service |

---

## Operational Cost: Lifecycle Model

A subreddit evolves through phases. Cost scales with activity:

### Phase 1: Cold Start (months 1-3) — Sub < 100 subscribers

| Cost Type | Amount | Monthly |
|-----------|--------|---------|
| AI (classify + intent) | ~15 calls/day | $0.30 |
| PRAW API | 0.2 req/min | $0 |
| Content calendar | 3 posts/week | $0.01 |
| Human attention | 20 min/mo | — |
| **Total** | | **~$1/mo** |

### Phase 2: Growing (months 4-8) — Sub 100-1,000 subscribers

| Cost Type | Amount | Monthly |
|-----------|--------|---------|
| AI (classify + intent + modmail) | ~80-150 calls/day | $3-5 |
| PRAW API | 0.5 req/min | $0 |
| Content calendar | 5 posts/week | $0.02 |
| Human attention | 2h/mo | — |
| **Total** | | **~$4-6/mo** |

### Phase 3: Active (months 9-18) — Sub 1,000-10,000 subscribers

| Cost Type | Amount | Monthly |
|-----------|--------|---------|
| AI (all operations) | ~300-600 calls/day | $8-15 |
| PRAW API | 2 req/min | $0 |
| Content calendar | 7 posts/week | $0.03 |
| Strategy refresh | Monthly | $0.05 |
| Human attention | 4h/mo | — |
| **Total** | | **~$10-18/mo** |

### Phase 4: High-Traffic (18+ months) — Sub 10,000+ subscribers

| Cost Type | Amount | Monthly |
|-----------|--------|---------|
| AI (heavy volume) | ~1000+ calls/day | $20-35 |
| PRAW API | 5-8 req/min | $0 (may need dedicated token) |
| Auto-approve rules | Reduces AI load 50-60% | Savings ~$10-15 |
| Content calendar | 10-14 posts/week | $0.05 |
| Human attention | 8h/mo | — |
| **Total** | | **~$25-40/mo** |

### Cost Summary Table

| Phase | Subscribers | AI Cost/mo | Human Time/mo | Total Cost/mo |
|-------|------------|-----------|---------------|---------------|
| Cold Start | <100 | $0.30 | 20 min | ~$1 |
| Growing | 100-1K | $3-5 | 2h | ~$5 |
| Active | 1K-10K | $8-15 | 4h | ~$15 |
| High-Traffic | 10K+ | $20-35 | 8h | ~$35 |

**Key insight:** Cost grows linearly with activity but NEVER exceeds $40/mo even for a 10K+ subscriber community. Revenue is fixed ($249-499/mo). Margin stays above 90% at all phases.

---

## Unit Economics

| Pricing Tier | Revenue/mo | Worst-case cost (Phase 4) | Gross Margin |
|-------------|-----------|---------------------------|--------------|
| Basic ($149 add-on) | $149 | $40 | 73% |
| Community Ops ($299) | $299 | $40 | 87% |
| Full Hub ($499) | $499 | $40 | 92% |

**At typical Phase 2-3 (where most clients will be for 6-12 months):**

| Tier | Revenue | Typical cost | Margin |
|------|---------|-------------|--------|
| $149 | $149 | $5-15 | 90-97% |
| $299 | $299 | $5-15 | 95-97% |
| $499 | $499 | $5-15 | 97-98% |

**Development payback:**
- 140h internal development
- At market rate (~$150/h): ~$21K equivalent investment
- Break-even at $299/mo: 1 client × 6 months, or 2 clients × 3 months, or 5 clients × 1.5 months

---

## Risks

### Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| Reddit changes mod API behavior | Low | Medium | PRAW abstracts changes. Pin version, upgrade quarterly |
| AI classifier accuracy <80% initially | Medium | Low | Conservative mode (suggest only, never auto-act). Tune with real data |
| PRAW rate limit hit at 20+ clients | Low now | Medium then | Second OAuth token ($0) or Devvit migration |
| Bot account suspended | Very Low | High | Backup account. Auto-detection via heartbeat |
| Client sub banned for other reasons | Very Low | Low (not our liability) | Contract clause |

### Business Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| Client only wants moderation, not seeding | Medium | Low | Module works standalone. Seeding = upsell |
| AI accuracy disappoints client | Medium | Medium | Set expectations: "AI-assisted" not "automated". Tuning period |
| Community doesn't grow (low intent signals) | Medium | Medium | Growth is client's content responsibility. We manage ops |
| Competitor offers free alternative | Low | Medium | Our differentiation: intent signals + RAMP integration + AI backend |

### Platform Risks (Reddit July 2026)

| Question | Assessment |
|----------|-----------|
| PRAW still works? | Yes. OAuth authenticated = 60 QPM free tier. Unaffected by recent .json and old.reddit changes |
| Bots allowed as moderators? | Yes. Thousands exist. AutoModerator is a bot. Reddit endorses via Devvit mod apps |
| Commercial use approval needed? | For PRAW with legitimate mod access: No. Responsible Builder Policy "commercial approval" applies to Devvit apps and Data API commercial tier |
| Risk of Reddit blocking bot moderators? | Very Low. Would break their own AutoModerator and entire Devvit ecosystem |

---

## Competitive Positioning

| Tool | What It Does | Price | Our Advantage |
|------|-------------|-------|---------------|
| AutoModerator | Rule-based, no AI, limited | Free | We add AI intelligence + recommendations |
| Reddit Toolbox | Bulk mod actions, notes | Free | We add AI suggestions + external dashboard + intent detection |
| Agency services | Humans moderate | $2-5K/mo | 90% cheaper with AI assistance |
| **RAMP Community** | AI-assisted ops + intent detection + content + analytics | $249-499/mo | Unique: combines moderation + intent signals + avatar synergy |

**No competitor offers:** intent signal detection from community activity fed back into content strategy. This is novel.

---

## Client Onboarding Flow

1. Client creates subreddit (or has existing one)
2. Client invites RAMP bot account as moderator (permissions: posts, mail, flair)
3. RAMP operator runs Strategy Generation (AI produces rules, flairs, content pillars)
4. System starts polling mod queue + scanning for intent signals
5. Client sees new tabs in portal within 24h
6. Client configures: auto-approve thresholds, content calendar templates
7. Ongoing: client reviews AI suggestions, RAMP executes approved actions

**Client effort:** 5 minutes (invite bot). Everything else is RAMP-managed.

---

## What Tzvi Can Put in Proposal

### Safe to promise:

> "RAMP provides AI-assisted community operations for your Reddit presence. Our system monitors your subreddit's mod queue, suggests moderation actions, detects buyer intent signals from community discussions, and provides engagement analytics. All moderation decisions remain in your hands — our AI recommends, you decide. No additional infrastructure or API setup required from your side."

### Pricing: +$249-399/mo add-on

### Timeline: "Operational within 3 weeks of contract signature"

### Do NOT promise:
- Fully automated moderation
- Subscriber growth guarantees
- Zero spam
- Real-time response (<5 min cycle time)
- Custom AI behavior per client (standardized presets for MVP)
