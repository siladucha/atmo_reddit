---
inclusion: manual
---

# Community Module — Operating Model & Architecture

## What This Is

RAMP Community Module = AI-assisted subreddit operations workspace for client-owned communities. Enhances human moderation through intelligence, recommendations, and controlled execution tools.

## Core Principle

**RAMP does NOT manage subreddits.** Subreddit ownership and moderation authority ALWAYS belong to the human client. RAMP is a decision-support and execution system under human authority.

## Responsibility Model

| Layer | Role | Authority |
|-------|------|-----------|
| Human (client/moderator) | Final decisions, governance, policy, risk ownership | THE authority |
| RAMP Intelligence | Monitoring, classification, recommendations, signals | Advisory only |
| RAMP Execution | API calls (PRAW) triggered by human or pre-approved rules | Tools under human control |

## Architecture

### Execution Path: PRAW (not extension, not Devvit)

- Client adds RAMP bot account (`u/ramp_community_bot`) as moderator
- RAMP executes mod actions via Reddit API (PRAW)
- No browser extension needed for moderation
- No Devvit app review process
- Upgrade path: Devvit at 10+ community clients

### Data Flow

```
INBOUND (Reddit → RAMP):
  PRAW polling (every 5 min): mod queue, new posts, new comments
  → AI classify (Gemini Flash): spam/intent/quality
  → Store signals, surface in dashboard

OUTBOUND (RAMP → Reddit):
  Client clicks action in UI → PRAW executes
  Scheduled content → PRAW submits post
  → Every action logged with actor + timestamp
```

### Extension Boundary (IMPORTANT)

Browser extension is NOT part of subreddit moderation. It is outbound avatar execution only.
Extension MAY post avatars INTO client's sub (content seeding). This is NOT moderation.

## Components

| # | Component | What It Does | Status |
|---|-----------|-------------|--------|
| 0 | Strategy Generation | AI generates community rules, flairs, content pillars on onboarding | Foundation |
| 1 | Mod Queue Assistant | AI-triaged queue + one-click actions | Decision support |
| 2 | Intent Signals | Detect buyer/research intent from posts/comments | Analytics only |
| 3 | Content Calendar | Scheduled recurring community threads | Semi-automated publishing |
| 4 | Community Health | Growth, engagement, spam rate metrics | Observability only |

## Execution Safety Rules (Non-negotiable)

1. RAMP MUST NEVER execute moderation removals without human trigger (except explicitly configured auto-approve whitelist rules)
2. Auto-approve: ONLY for items matching client-configured whitelist (account_age + karma thresholds). Opt-in.
3. Auto-remove: NEVER enabled by default. Requires explicit client opt-in with signed acknowledgment.
4. Every action logged: actor, timestamp, item_id, action_type, AI_confidence
5. Client can always use Reddit's native mod tools directly (RAMP = enhancement, not dependency)

## Avatar Synergy

Avatars posting IN client's sub:
- Tracked by existing `SubredditKarma` + avatar_performance system
- Organic replies to avatar posts → scanned for intent signals
- Attribution: "Avatar post → 15 comments → 3 intent signals"
- Client sees avatar activity transparently (not hidden)

## Cost Model (per client subreddit)

| Phase | Subscribers | AI Cost/mo | Human Time | Revenue | Margin |
|-------|------------|-----------|-----------|---------|--------|
| Cold (1-3 mo) | <100 | $1 | 20 min | $249-499 | >99% |
| Growing (4-8 mo) | 100-1K | $5 | 2h | $249-499 | 97% |
| Active (9-18 mo) | 1K-10K | $15 | 4h | $249-499 | 94% |
| High-traffic (18+ mo) | 10K+ | $35 | 8h | $249-499 | 87% |

## Development Status

- **Spec:** `buziness/community_module_full_spec_en.md`
- **ETA:** 5-6 weeks total (Phase 1 in 2-3 weeks)
- **Dependencies:** None blocking. Bot account creation + client mod invite only prerequisites.
- **Feature flag:** `community_module_enabled` (default: false)

## Relationship to Existing Systems

| System | Reused | Adapted | Purpose |
|--------|--------|---------|---------|
| Discovery Engine | ✅ | Strategy generation for community context | Community strategy |
| Scoring (Gemini Flash) | ✅ | Mod queue classification prompt | Spam/quality triage |
| PRAW factory | ✅ | Separate bot account OAuth | Mod action execution |
| Activity Events | ✅ | Log mod actions | Audit trail |
| Client Portal | ✅ | New tabs (Mod Queue, Signals, Calendar, Health) | Client self-service |
| Notifications (SSE) | ✅ | "N posts need review" alerts | Client engagement |
| Celery Beat | ✅ | 3 new tasks (poll, scan, health) | Periodic operations |
| SubredditKarma | ✅ | Avatar tracking in client's sub | Performance measurement |
| community_leaders | ✅ | Spam/bot/promo detection for community users | Community intelligence |

## Key Invariant

**Human = authority. RAMP = intelligence + tooling. API = execution channel. Moderation = human responsibility assisted by AI.**
