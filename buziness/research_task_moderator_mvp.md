# Research Task: Moderator Task Types MVP — Scope & Feasibility

## Context for Analyst

We have a new lead — real estate company operating in 7 US metros, budget-conscious, strong product fit. Tzvi is assembling a modular proposal and wants to include **client-owned subreddit management + moderator capabilities** as an optional add-on.

We need concrete answers to two questions for the proposal:

1. **Timeline:** How long to ship moderator task types to a working MVP?
2. **Operational cost:** Any recurring overhead per client using this feature, or purely incremental dev?

---

## What RAMP Already Has (Existing Infrastructure)

RAMP is a Reddit marketing platform with the following execution flow:

```
Backend generates task → Task Queue → Browser Extension picks up → Executor approves in popup → Extension performs action on Reddit → Reports result back
```

Key components already built:
- **Browser Extension (Chrome MV3)** — auto-executes tasks on Reddit via chrome.debugger (trusted clicks). Deployed, working in production.
- **ExecutionTask model** — supports `task_type` field (currently: `comment`, `cqs_check`, `post`). Easily extensible.
- **Task lifecycle** — CREATED → DELIVERED → APPROVED → EXECUTING → COMPLETED/FAILED. Full audit trail.
- **Delivery channels** — email fallback + extension polling (30s).
- **HMAC-signed tasks** — integrity protection against tampering.
- **Popup UI** — executor sees tasks, approves/skips, extension auto-executes.
- **OAuth flow** — Reddit OAuth callback exists at `/api/oauth/reddit/callback`. Currently requests basic scopes.

---

## What Needs to Be Built (Moderator MVP)

### New Task Types

| Task Type | Reddit Action | UI Complexity | OAuth Scope Needed |
|-----------|--------------|---------------|-------------------|
| `mod_approve_post` | Approve a post/comment from mod queue | Low — click "Approve" button | `modposts` |
| `mod_remove_post` | Remove a post/comment (with optional reason) | Low-Medium — click "Remove", select reason | `modposts` |
| `mod_sticky_post` | Sticky/pin a post in subreddit | Low — click "Sticky Post" in mod tools | `modposts` |
| `mod_reply_modmail` | Reply to a ModMail thread | Medium — navigate to modmail, compose reply | `modmail` |
| `mod_lock_thread` | Lock comments on a thread | Low — click "Lock" | `modposts` |
| `mod_flair_post` | Assign flair to a post | Low — select flair from dropdown | `flair` |

### Technical Changes Required

1. **Content script additions** — new DOM interaction handlers for mod actions (approve button selector, remove modal, sticky toggle, modmail composer)
2. **Task type routing in executor.js** — switch on `task_type` to select correct execution flow
3. **Backend task creation** — new service/route for creating moderator tasks (manual trigger from admin or scheduled)
4. **OAuth scope upgrade** — existing OAuth flow needs additional scopes: `modposts`, `modmail`, `flair`, `modconfig`
5. **Re-authorization UX** — users with existing OAuth tokens need prompt to re-authorize with new scopes
6. **Mod queue polling (optional, Phase 2)** — PRAW `subreddit.mod.modqueue()` to surface pending items automatically

### What Does NOT Need to Change

- Task queue infrastructure (same Celery + Redis)
- Extension polling mechanism (same `/api/extension/tasks`)
- Delivery channel logic (same extension/email/both)
- HMAC verification (same signing)
- Audit trail (same event stream)
- Avatar/executor assignment model

---

## Research Questions for Analyst

### 1. Reddit Moderator API Capabilities

- What specific Reddit API endpoints / PRAW methods are available for each moderator action?
- Are there rate limits specific to moderator actions (separate from regular API limits)?
- Does Reddit's mod API work differently for "invited moderators" vs "subreddit creators"?
- What minimum moderator permissions are needed per action type? (Reddit has granular mod permissions: posts, mail, flair, config, etc.)
- Can moderator actions be performed via browser DOM (extension path) without API calls?

### 2. OAuth Scopes — Exact Requirements

- Full list of OAuth scopes needed for each moderator task type
- Is there a way to request additional scopes incrementally (without revoking existing token)?
- What is the user experience of re-authorization? (Reddit shows "this app is requesting additional permissions...")
- Any approval/review process from Reddit for apps requesting mod scopes?

### 3. Devvit (Reddit Developer Platform) — Relevant Context

- What is Devvit and what capabilities does it offer for subreddit management?
- Can Devvit apps perform moderator actions programmatically?
- Is Devvit a viable alternative to the browser extension for mod tasks? (faster, more reliable, no DOM parsing)
- What are Devvit's limitations and approval requirements?
- Is there overlap between our extension approach and Devvit that we should address in the proposal?

### 4. Competitive Landscape — Moderator Tools

- What existing tools offer subreddit moderation automation? (Toolbox, Automod, third-party bots)
- How do competitors (if any) handle client-owned subreddit management as a service?
- Is "subreddit management as a service" an established offering in the market, or is this novel?
- Pricing benchmarks for community management tools/services

### 5. Compliance & Risk

- Does Reddit's Moderator Code of Conduct restrict delegation of mod actions to third parties?
- Any precedent of Reddit removing moderators for using automation tools?
- How does Reddit view "moderator assistants" / delegation tooling in their ToS?
- Risk of subreddit being quarantined/banned if moderation is partially automated?

### 6. Real Estate Vertical Specifics

- Examples of successful real estate communities on Reddit (r/RealEstate, r/FirstTimeHomeBuyer, local metro subs)
- What engagement patterns work in real estate subreddits?
- Is owning a branded subreddit (e.g., r/[CompanyName]Homes) realistic for this use case, or would they moderate an existing niche sub?
- What content types drive engagement in real estate communities? (market updates, Q&A, listings, neighborhood guides)

---

## Expected Output

A structured document answering each question group above, with:
- Sources cited (Reddit docs, Devvit docs, PRAW docs, competitor sites)
- Risk assessment (low/medium/high) per area
- Recommendation on approach (extension-first vs. Devvit vs. hybrid)
- Timeline estimate validation (confirm or adjust "3-5 days for basic mod tasks, 2-4 weeks for Devvit pilot")
- Cost analysis (one-time dev effort + any recurring per-client overhead)

---

## Deadline

Tzvi needs answers within **24-48 hours** to finalize proposal for the real estate lead.

---

## Key Constraints for Proposal

- Client is **budget-conscious** — solution must be positioned as low-overhead add-on, not expensive custom build
- 7 US metros = potentially 7 local subreddits or 1 national + metro flairs
- Moderator capabilities are an **optional add-on**, not core offering
- MVP first, Community Hub product expansion later (only if demand validates)
