# Welcome to RAMP — Avatar Manager Guide

## Hey Fredo! 👋

Welcome to the team. You're joining as **Avatar Manager** — the person responsible for building and maintaining our Reddit avatar inventory. This is a critical role: the avatars you warm up today become the revenue-generating assets our clients use tomorrow.

This guide covers everything you need to know to get started.

---

## Table of Contents

1. [What You'll Be Doing](#what-youll-be-doing)
2. [Your Access](#your-access)
3. [Avatar Lifecycle — The Phases](#avatar-lifecycle--the-phases)
4. [Daily Workflow](#daily-workflow)
5. [Key Actions — How To](#key-actions--how-to)
6. [Rules — Never Break These](#rules--never-break-these)
7. [Metrics That Matter](#metrics-that-matter)
8. [Communication](#communication)
9. [Quick Reference](#quick-reference)

---

## What You'll Be Doing

Your job is the **full lifecycle of Reddit avatars**:

1. **Create** new avatar accounts (Reddit registration, email setup)
2. **Configure** their personality in the platform (voice, tone, subreddits)
3. **Warm them up** — build karma by posting genuine hobby comments
4. **Monitor health** — check for shadowbans, CQS drops, suspensions
5. **Maintain quality** — review AI-generated comments, approve/reject before posting

Think of it like raising digital personas from scratch. Each avatar needs to look, sound, and behave like a real Reddit user before it can ever mention a client's brand.

---

## Your Access

**Platform URL:** `http://161.35.27.165/admin/avatars`  
**Role:** Avatar Manager  
**Login:** (credentials sent separately)

### What you can see:
- ✅ **Avatars** — full list of unassigned avatars, all details, all actions
- ✅ **Review Queue** — approve/reject/edit generated comments
- ✅ **Audit Logs** — history of all actions in the system
- ✅ **Export/Reports** — download avatar data

### What you won't see:
- ❌ Client business data (their keywords, billing)
- ❌ Client strategy documents (positioning, competitive intel)
- ❌ System settings / kill switches
- ❌ User management
- ❌ Pipeline triggers for all clients

This is by design — you focus on avatars, we handle the business side. Strategy is set by us and shapes what the AI generates, but you don't need to see the underlying client briefs.

---

## Avatar Lifecycle — The Phases

Every avatar goes through warming phases before it can be used for client work:

| Phase | Name | Duration | What Happens |
|-------|------|----------|--------------|
| 0 | Mentor | Permanent | High-karma accounts excluded from automation. Reputation assets only. |
| 1 | Credibility | Months 1-2 | **Zero brand mentions.** Hobby subreddits only. Build karma organically. |
| 2 | Content Seeding | Months 3-4 | Professional subreddits. External citations. No direct brand links yet. |
| 3 | Brand Integration | Month 5+ | Can mention brands — only when karma is sufficient and thread is relevant. |
| Expert | AI-Native Expert | Ongoing | Authority score > 75. Content gets cited by AI chatbots (ChatGPT, Gemini, Perplexity). Premium status. |

**Your primary focus is Phase 1 avatars** — getting them from 0 karma to a credible Reddit presence.

---

## The Big Picture — Why This Matters

The ultimate goal of avatar warming is NOT just karma. It's building **AI-Native Experts**.

Here's what that means: when someone asks ChatGPT, Google Gemini, or Perplexity a question, these AI systems look for authoritative sources to cite. Reddit is one of their top sources. If our avatar consistently posts high-quality, expert-level content in a specific niche — the AI chatbots will start **citing our avatar's posts as trusted answers**.

This is the real value we sell to clients: their brand gets mentioned by AI chatbots as a recommended solution.

**How you contribute to this:**

1. **Niche focus** — each avatar should be an expert in ONE topic area (cybersecurity, yoga, home automation, etc.). Don't spread thin across random subreddits.

2. **Quality content** — write like a real expert. Use first-hand experience markers ("In my tests...", "We deployed this on 5k users..."). Use structured formats (lists, step-by-step guides, comparisons).

3. **Avoid AI-tell phrases** — never use words like "Delve", "Crucial", "In conclusion", "It's important to note". These signal AI-generated content and reduce citability.

4. **Provoke discussions** — comments that get replies and deep threads signal authority to AI systems. Ask follow-up questions, share controversial (but defensible) opinions.

5. **Build entity associations** — naturally connect the client's brand with problem-solution patterns. Example: someone asks "how to detect lateral movement?" → avatar shares expertise → mentions the client's tool as one option among several.

The metrics that matter for Expert status:
- **Authority Score** (0-100) — computed from karma quality, thread depth, saves, cross-references
- Upvote-to-character ratio (quality karma, not just volume)
- Thread depth (how many replies your comment generates)
- Saves and cross-references by other users

*Note: AI citation tracking (whether ChatGPT/Perplexity actually cites our content) is not yet fully measurable — we're working on integrations with tracking tools. For now, focus on the proxy signals above: if the content is authoritative and well-structured, citations will follow.*

---

## Daily Workflow

### Morning Routine (15-20 min)

1. **Open Avatars page** → check for any health alerts (🔴 red badges)
2. **Check Review Queue** → approve/reject pending hobby comments
3. **Build EPG** for each active avatar → generates today's comment plan

### Throughout the Day

4. **Post approved comments** manually on Reddit:
   - Open the avatar's Workflow tab
   - See approved drafts with thread links
   - Open Reddit in browser → paste comment → post
   - Mark as "Posted" in the platform

5. **Monitor** for issues:
   - Shadowban alerts (auto-detected twice daily)
   - CQS drops (checked daily at 06:30)
   - Frozen avatars (check freeze reason, report to Tzvi)

### Weekly

6. **Review avatar progress** — karma growth, phase eligibility
7. **Add new avatars** if inventory is running low
8. **Update voice profiles** if comments feel off-brand

---

## Key Actions — How To

### Create a New Avatar

1. Go to `/admin/avatars` → click **"+ New Avatar"**
2. Fill in:
   - **Reddit Username** — must match the actual Reddit account
   - **Email** — the email linked to the Reddit account
   - **Hobby Subreddits** — comma-separated (e.g. `homelab, selfhosted, sysadmin`)
3. Save → the system will start scraping those subreddits for content

### Configure Voice Profile

1. Open avatar → **Profile & Safety** tab
2. Fill in ALL fields (the system shows completeness %):
   - **Voice Profile** — full personality description (2000-5000 chars)
   - **Tone Principles** — how they write (warm? direct? technical?)
   - **Speech Patterns** — characteristic phrases, sentence structure
   - **Hill I Die On** — strong opinions (makes avatar feel real)
   - **Helpful Mode Topics** — where they naturally help others
   - **Constraints** — things they NEVER do
   - **Vocabulary Lean** — preferred words, jargon level

⚠️ **Incomplete profiles = bad AI comments.** Fill everything before generating.

### Build EPG (Daily Publishing Program)

1. Open avatar → **Workflow** tab (or Overview → EPG panel)
2. Click **"▶ Build"** — generates today's comment slots
3. System picks threads from hobby subreddits, assigns time slots
4. AI generates comments → they appear in Review Queue

### Approve/Reject Comments

1. Go to **Review Queue** (left menu)
2. For each pending comment:
   - ✅ **Approve** — ready to post
   - ✏️ **Edit** — fix something, then approve
   - ❌ **Reject** — bad quality, wrong tone, irrelevant
3. Approved comments appear in the avatar's Workflow tab for posting

### Post on Reddit (Manual)

1. Open avatar → **Workflow** tab
2. Find an approved draft
3. Click the thread link → opens Reddit
4. Copy the comment text
5. Paste into Reddit's comment box → Submit
6. Back in RAMP → mark as "Posted"

**Important:** Always post from the avatar's own Reddit account. Never post from your personal account.

### Freeze/Unfreeze an Avatar

- **Freeze** — if something is wrong (shadowban suspected, weird behavior). Click Freeze button, enter reason.
- **Unfreeze** — when issue is resolved. Click Unfreeze.
- Frozen avatars are excluded from ALL automated pipelines.

### Check Health

- **Refresh from Reddit** button → fetches latest karma, status, CQS
- Health states: `active` (good), `limited` (watch), `shadowbanned` (freeze immediately), `suspended` (account banned by Reddit)

---

## Rules — Never Break These

1. **Never mention any brand in Phase 1.** Zero tolerance. The system blocks it, but don't try.
2. **Never post from your own device/IP for multiple avatars.** One avatar = one browser profile (we'll set up proxies later).
3. **Never copy-paste the same comment to multiple threads.** Each comment is unique.
4. **Never use the words:** "bot", "fake account", "automated posting" — anywhere, ever. We say "avatar", "persona", "community engagement".
5. **If an avatar gets shadowbanned** — freeze it immediately, report to Max. Don't try to "fix" it.
6. **Quality over quantity.** 5 great comments > 20 mediocre ones. Reddit users detect low-effort instantly.

---

## Metrics That Matter

| Metric | Good | Warning | Bad |
|--------|------|---------|-----|
| Comment karma/week | 10+ | 3-9 | 0-2 |
| CQS level | moderate+ | low | lowest (auto-freeze) |
| Removal rate | <10% | 10-20% | >20% |
| Shadowban | No | — | Yes (freeze!) |

---

## Communication

- **Questions about the platform** → message Max (Telegram/WhatsApp)
- **Questions about avatar behavior & natural engagement** → message Tzvi — he's the expert on how avatars should behave to look natural and build credibility
- **Questions about strategy/clients** → message Tzvi
- **Something broken** → screenshot + description → Max
- **Avatar got banned** → freeze immediately → notify Max

---

## Quick Reference

| Action | Where |
|--------|-------|
| See all avatars | `/admin/avatars` |
| Avatar details | Click any avatar → all tabs |
| Build daily plan | Avatar → Workflow → "▶ Build" |
| Approve comments | `/admin/review` |
| Check health | Avatar → Performance → Refresh |
| Download report | Avatar → Actions → Export |
| View audit history | `/admin/audit-logs` |

---

Welcome aboard, Fredo. Let's build some credible avatars. 🚀

— Max
