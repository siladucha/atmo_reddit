# Glossary

> **Audience:** Everyone  
> **Last updated:** 2026-05-28

---

## Terminology Rules

**Never use** these terms in any written communication:
- ❌ "fake accounts", "bot", "bots", "bot ring"
- ❌ "automating Reddit", "automated posting"
- ❌ "evading detection", "bypassing"
- ❌ "violating ToS", "against Reddit rules"

**Always use** these terms instead:
- ✅ "avatar" (not "fake account")
- ✅ "community engagement management"
- ✅ "persona-driven content strategy"
- ✅ "managed brand presence"
- ✅ "Digital Assets" (legal term for avatars in contracts)

---

## A

**Activity Event** — A logged record of something that happened in the pipeline (scrape completed, draft generated, comment posted). Used for transparency and debugging.

**Authority Score** — Composite metric (0-100) measuring an avatar's credibility in its niche. Based on karma quality, thread depth, saves, and cross-references.

**Avatar** — A Reddit account managed through the platform. Has a unique personality, assigned subreddits, and warming phase. The core revenue-generating asset.

**Avatar Farm** — Inventory of pre-warmed avatars not yet assigned to any client. Available for rental.

**Avatar Owner** — A person (employee/freelancer) who physically posts approved content on Reddit from an avatar's account. Uses the mobile app.

---

## B

**Brand Ratio** — The percentage of an avatar's recent comments that mention a client's brand. Capped by the system to avoid detection.

**Budget** — Daily limit on how many comments an avatar can post. Varies by phase and plan tier.

---

## C

**Client** — A B2B company using RAMP for Reddit marketing. Has keywords, avatars, subreddits, and a strategy.

**Client Deactivation** — Setting `is_active=false` on a client. Cascades: all assignments deactivated, avatars unassigned, pipeline skips all tasks for this client.

**Comment Draft** — AI-generated comment text awaiting human review. Statuses: `pending` → `approved`/`rejected` → `posted`.

**CQS (Contributor Quality Score)** — Reddit's internal quality metric for accounts. Levels: highest, high, moderate, low, lowest. Avatars with "lowest" CQS are auto-frozen.

**Correction Pattern** — A recurring edit pattern extracted from human reviews (e.g., "always shorten to 2 sentences"). Injected into future AI prompts.

---

## D

**Digital Assets** — Legal/contractual term for avatars. Used in client agreements.

**Draft** — See "Comment Draft" or "Post Draft".

**Dry Run** — Testing the pipeline without actually posting. Generates drafts but marks them as test data.

---

## E

**Edit Record** — Captured diff between AI-generated draft and human-edited version. Used by the self-learning loop.

**EPG (Electronic Program Guide)** — Daily publishing schedule for an avatar. Lists which threads to engage with, at what time, and in what order. Generated fresh each morning.

**EPG Slot** — A single entry in the EPG. Represents one planned comment with a target thread, time, and status.

**Expert** — Highest avatar tier. Authority score > 75. Content structured to be cited by AI chatbots (ChatGPT, Gemini, Perplexity).

---

## F

**Few-Shot Examples** — Real examples of good edits injected into AI prompts to guide generation quality. Selected by relevance to current context.

**Freeze** — Temporarily disabling an avatar. Frozen avatars are excluded from all automated pipelines. Used when issues are detected (shadowban, CQS drop, suspicious activity).

---

## G

**Generation** — The AI process of writing a comment in an avatar's voice for a specific thread.

---

## H

**Health Check** — Automated verification of avatar account status. Detects shadowbans, suspensions, and CQS drops. Runs twice daily.

**Health Status** — One of 5 states: `active`, `limited`, `shadowbanned`, `suspended`, `unknown`.

**Hobby Subreddit** — A subreddit where an avatar participates purely for karma building (Phase 1). No brand relevance.

---

## K

**Karma** — Reddit's reputation points. Earned by receiving upvotes. Critical for avatar credibility.

**Keywords** — Terms that define what's relevant to a client. Categorized as high/medium/low priority. Used in thread scoring.

**Kill Switch** — Global toggle that immediately stops a pipeline component. Three switches: `pipeline_enabled`, `generation_enabled`, `scrape_enabled`.

---

## L

**Learning Loop** — See "Self-Learning Loop".

**Liveness Check** — Verification that a Reddit thread is still active (not locked, removed, or archived) before generating or posting.

---

## M

**Mentor (Phase 0)** — Pre-warmed high-karma avatar excluded from all automated pipelines. Used for reputation presence only.

---

## N

**Niche** — The specific topic area an avatar specializes in (e.g., cybersecurity, yoga, home automation). Each avatar focuses on one niche for authority building.

---

## P

**Persona** — The complete personality profile of an avatar: voice, tone, opinions, vocabulary, constraints.

**Persona Routing** — AI selecting the best avatar to respond to a specific thread based on subreddit karma and voice fit.

**Phase** — See "Phases (Avatar Warming)" in [Platform Overview](./platform-overview.md).

**Pipeline** — The full automated workflow: Scrape → Score → Generate → Review → Post.

**Post Draft** — AI-generated Reddit post (not comment). Used for content seeding in Phase 2+.

**Proxy** — Residential IP address assigned to an avatar for posting. Each avatar gets a dedicated IP to avoid detection patterns.

---

## Q

**Query Scoping** — RBAC mechanism that automatically filters database queries to show only data the current user is authorized to see.

---

## R

**RAMP** — Reddit Avatar Marketing Platform. The product name.

**RBAC** — Role-Based Access Control. 6 roles with different permission levels.

**Removal Rate** — Percentage of posted comments that get removed by subreddit moderators. Target: < 10%.

**Repurpose Scraping** — Weekly harvest of evergreen high-upvote posts (top/year) for engagement opportunities.

**Review Queue** — UI where humans approve, edit, or reject AI-generated drafts before posting.

---

## S

**Scoring** — AI evaluation of a thread's relevance, quality, and strategic value for a client. Tags: `engage` (generate comment), `monitor` (watch), `skip` (ignore).

**Scraping** — Automated collection of new threads from configured subreddits.

**Self-Learning Loop** — System that captures human edits, extracts patterns, and injects them into future AI prompts. Improves generation quality over time.

**Shadowban** — Reddit silently hiding an account's posts/comments from other users. Detected by health checks, triggers auto-freeze.

**Strategy Document** — Per-avatar document defining engagement goals, tone, cadence, and positioning. Injected into generation prompts.

---

## T

**Thread** — A Reddit post (the original submission). Contains title, body, subreddit, score, comments.

**Thread Liveness** — Whether a thread is still accepting new comments (not locked, removed, or archived).

**Topology** — System health dashboard showing the state of all 9 pipeline nodes.

---

## V

**Voice Profile** — Detailed personality description for an avatar (2000-5000 chars). Defines how the AI writes as this persona.

---

## W

**Warming** — The process of building an avatar's credibility over months through genuine participation before any brand work.
