# QA Focus for Monday — June 5, 2026

Hi Fredo,

Thanks for the update. Your feedback has already helped improve many areas of the product.

For Monday's review, I'd like to narrow the scope and focus on what matters most for our next customer demos.

---

## User Journey to Test

Please walk through this flow as if you're onboarding a new client's avatar:

1. **Create or update an avatar profile**
2. **Configure strategy and goals**
3. **Configure subreddit targeting**
4. **Review generated recommendations and EPG**
5. **Review generated drafts**
6. **Understand what actions the system expects from the user**
7. **Identify anything confusing or difficult to explain to a new customer**

---

## Quick Paths (where to find each step)

| Step | Path in Admin Panel |
|------|-------------------|
| Avatar list | `/admin/avatars` |
| Create avatar | `/admin/avatars` → "New Avatar" button |
| Avatar detail (all tabs) | `/admin/avatars/{id}` |
| Edit avatar profile | Avatar detail → "Edit" button |
| Strategy | Avatar detail → "Strategy" tab → "Generate Strategy" |
| Subreddit targeting | `/admin/clients/{id}` → Subreddits section |
| EPG (daily plan) | Avatar detail → "EPG" tab → "Build EPG" |
| Review drafts | `/admin/review` (or Avatar detail → drafts section) |
| Approve/reject | Review page → approve/reject buttons per draft |

---

## Important: Avatar Pool

If you see **"Avatar pool 'warm' excluded from EPG"** — this is expected.

**Why:** Avatars with pool = `warm` are unassigned (no client). EPG needs a client context (keywords, subreddits, brand goals) to generate recommendations.

**Fix:** Assign the avatar to a client first:
1. Go to avatar edit page
2. Change pool from `warm` to `b2b`
3. OR: assign the avatar to a client via `/admin/clients/{id}` → Avatars section

After that, EPG will work.

---

## What I'm Looking For

I'm less concerned about visual polish. What matters:

- Anything that would **confuse a customer**
- Anything that would **block onboarding**
- Anything that would **prevent someone from understanding how the platform works**
- Any **missing information** that makes decision-making difficult

---

## The Key Question

> "Would you be comfortable showing the current platform to a potential customer and explaining how it works?"

If not — please identify the specific blockers. Be as concrete as possible: which screen, which step, what's missing or unclear.

The goal is to get the platform demo-ready by midweek so I can shift primary focus to mobile app development.

Thanks and have a great weekend.

— Max
