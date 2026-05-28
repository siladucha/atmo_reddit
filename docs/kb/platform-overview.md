# Platform Overview

> **Audience:** Everyone (new team members, clients, partners)  
> **Last updated:** 2026-05-28

---

## What is RAMP?

RAMP (Reddit Avatar Marketing Platform) is a managed Reddit marketing platform. It helps B2B companies build authentic brand presence on Reddit through AI-powered content strategy and persona-driven engagement.

**In simple terms:** We monitor relevant Reddit conversations, generate expert-level comments from carefully built personas (avatars), and post them after human approval.

---

## How It Works — The Big Picture

```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐     ┌──────────────┐     ┌──────────┐
│  1. SCRAPE  │────▶│  2. SCORE    │────▶│  3. GENERATE   │────▶│  4. REVIEW   │────▶│  5. POST │
│             │     │              │     │                │     │              │     │          │
│ Monitor     │     │ AI rates     │     │ AI writes      │     │ Human        │     │ Avatar   │
│ subreddits  │     │ relevance    │     │ comment as     │     │ approves/    │     │ posts on │
│ for new     │     │ & quality    │     │ avatar persona │     │ edits/       │     │ Reddit   │
│ threads     │     │              │     │                │     │ rejects      │     │          │
└─────────────┘     └──────────────┘     └────────────────┘     └──────────────┘     └──────────┘
```

### Step by Step

1. **Scrape** — System monitors configured subreddits every few hours, collecting new threads
2. **Score** — AI (Gemini Flash) evaluates each thread for relevance, quality, and strategic value
3. **Generate** — For top-scoring threads, AI (Claude Sonnet) writes a comment in the avatar's voice
4. **Review** — Human reviewer approves, edits, or rejects each draft
5. **Post** — Approved comments are posted on Reddit from the avatar's account

**Key principle:** Human-in-the-loop. No content is ever posted without explicit human approval.

---

## Core Concepts

### Avatars

An avatar is a Reddit account managed by the platform. Each avatar has:
- A unique personality (voice profile, tone, opinions)
- Assigned subreddits (where it participates)
- A warming phase (determines what it can do)
- Health status (monitored for bans/restrictions)

Avatars are the core asset. They take months to build credibility.

### Clients

A client is a B2B company using RAMP. Each client has:
- Keywords (what topics matter to them)
- Assigned avatars (who speaks for them)
- Subreddits (where their audience lives)
- A strategy document (tone, goals, positioning)

### EPG (Electronic Program Guide)

Like a TV schedule, each avatar gets a daily publishing program:
- Which threads to engage with
- What time to post (with natural timing variation)
- How many comments per day (budget)

The EPG is generated fresh each morning and respects all safety limits.

### Phases (Avatar Warming)

Every avatar goes through warming phases before it can mention a brand:

| Phase | Name | Duration | Rules |
|-------|------|----------|-------|
| 0 | Mentor | Permanent | High-karma accounts. Not in automated pipelines. |
| 1 | Credibility | Months 1-2 | Zero brand mentions. Hobby subreddits only. |
| 2 | Content Seeding | Months 3-4 | Professional subreddits. External citations. No brand links. |
| 3 | Brand Integration | Month 5+ | Can mention brands when appropriate. |
| Expert | AI-Native Expert | Ongoing | Authority score > 75. Premium status. |

### Self-Learning Loop

The system learns from human edits:
1. Reviewer edits a draft → system captures the change
2. After enough edits, patterns are extracted (e.g., "always shorter", "avoid jargon")
3. Future generations include these patterns as guidance
4. Result: AI output improves over time for each avatar

---

## Who Does What

| Role | Responsibility |
|------|---------------|
| **Owner** (Max) | Platform development, system settings, infrastructure |
| **Partner** (Tzvi) | Client relationships, strategy, business operations |
| **Client Admin** | Manages their company's team, avatars, settings |
| **Client Manager** | Daily review and approval of content |
| **Client Viewer** | Read-only access to dashboards and reports |
| **Avatar Owner** | Posts approved content on Reddit (mobile app) |

---

## Safety & Compliance

### What the System Enforces
- Phase gates (no brand mentions before Phase 3)
- Brand mention ratio limits
- Posting frequency limits per subreddit
- Content safety checks (no defamatory claims)
- Promotional language detection
- Shadowban detection (auto-freeze)

### What Humans Control
- All content approval (approve/edit/reject)
- Strategy direction
- Avatar freeze/unfreeze decisions
- Client onboarding and configuration

---

## Technology (Non-Technical Summary)

- **Web app** accessible via browser (no installation needed)
- **Mobile app** (Flutter) for avatar owners to post from their phones
- **AI models**: Gemini Flash (fast scoring), Claude Sonnet (quality writing)
- **Hosted** on DigitalOcean (Frankfurt, Germany)
- **Automated tasks** run on schedule (scraping, scoring, health checks)

---

## Key URLs

| What | URL |
|------|-----|
| Admin Panel | `http://161.35.27.165/admin/` |
| Review Queue | `http://161.35.27.165/admin/review` |
| Avatars | `http://161.35.27.165/admin/avatars` |
| Dashboard | `http://161.35.27.165/admin/dashboard` |
| Marketing Site | `http://161.35.27.165/` |

*Note: Domain name coming soon. Currently accessed via IP address.*
