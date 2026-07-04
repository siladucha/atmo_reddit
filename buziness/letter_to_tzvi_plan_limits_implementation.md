# Plan Limits Implementation — Approval Request

**To:** Tzvi  
**From:** Max  
**Date:** July 2, 2026  
**Subject:** Need your sign-off on plan limits before I implement enforcement

---

## Context

Right now the system has plan_type on each client (trial/seed/starter/growth/scale) and max_comments_per_month as a number — but **enforcement is minimal**. Clients can technically exceed their plan limits because we never built hard gates. Before I code the enforcement layer, I need you to confirm the exact numbers and behavior.

---

## What I'm Implementing

A plan enforcement system that:
1. Caps monthly actions (comments + posts) per plan
2. Caps avatars per plan
3. Caps subreddits per plan
4. Gates features by plan tier (competitor monitoring, Slack alerts, report frequency, etc.)
5. Shows usage meters + contextual upgrade CTAs (per your UX spec)

---

## Plan Limits — Please Confirm or Correct

Based on the Business Brief (May 2026):

| | **Trial** | **Seed** | **Starter** | **Growth** | **Scale** |
|--|-----------|----------|-------------|------------|-----------|
| **Price/mo** | $0 (14 days) | $149 | $399 | $799 | $1,499 |
| **Avatars** | 1 (BYOA only) | 1 | 3 | 7 | 15 |
| **Professional subreddits** | 1 | 1 | 2 | 5 | Unlimited |
| **Hobby subreddits** | — | 1 | included | included | included |
| **Comments/month** | 0 (read-only drafts) | 30 | 60 | 150 | 400 |
| **Posts/month** | 0 | 0 | 3 | 10 | included in 400 |
| **Competitor monitoring** | ❌ | ❌ | ❌ | ✅ (3 competitors) | ✅ (unlimited) |
| **Share of Voice widget** | ❌ | ❌ | ❌ | ✅ | ✅ |
| **Slack alerts** | ❌ | ❌ | ❌ | ✅ | ✅ |
| **Report frequency** | — | Monthly | Monthly | Bi-weekly | Weekly |
| **AEO/GEO monitoring** | ❌ | ✅ (basic) | ✅ (basic) | ✅ (full) | ✅ (full) |
| **Content Strategy Briefs** | ❌ | ❌ | ❌ | ✅ | ✅ |
| **Pre-warmed avatars** | ❌ | Purchase | Purchase | Purchase | Purchase |

---

## Questions That Need Your Answer

### 1. Trial — what exactly can they do?

The Business Brief says:
- AI drafts = "read-only" (visible but can't post)
- 1 edit/re-generate per day
- 1 subreddit for discovery
- No avatar activation

**Question:** Does this mean we generate drafts for them but mark them as "preview only"? Or we don't generate at all and just show scoring/monitoring?

**My recommendation:** Generate real drafts (shows value), but block the approval button. Display: "Upgrade to activate posting." This gives the strongest aha moment.

---

### 2. Seed — 3-month POC?

The brief says "Seed is a 3-month proof-of-concept, capped. System auto-prompts upgrade."

**Question:** Is Seed literally a 3-month plan that auto-expires? Or is it a monthly plan where after 3 months you push an upgrade conversation?

**My recommendation:** Monthly billing, but at month 3 the system shows a strong upgrade nudge ("You've been on Seed for 3 months — your avatar is ready for more subreddits. Upgrade to Starter for 3× the coverage."). No hard expiration.

---

### 3. Actions count — comments + posts combined?

Scale says "400 actions." Growth says "150 comments + 10 posts."

**Question:** For Growth, are posts counted separately (150 + 10 = 160 total actions)? Or is it a single pool of 160 where posts cost more?

**My recommendation:** Single pool. 1 comment = 1 action. 1 post = 1 action. Growth = 160 actions/month total. Scale = 400 actions total. This is simpler to implement, simpler to explain, and the UX spec already shows one meter ("Monthly actions: X / Y").

---

### 4. Subreddit limit — what counts?

"2 professional + hobbies" for Starter.

**Question:** Do hobby subreddits count against the limit? Or are they free/unlimited and only professional subs are capped?

**My recommendation:** Only professional subreddits count against the plan limit. Hobby subs are unlimited (they're for warming, not client value). This matches how we route content — Phase 1 hobby subs aren't in the "subreddits" table at all.

---

### 5. Hard cap vs soft cap?

**Question:** When a client hits their monthly action limit — do we hard-stop (zero drafts generated) or soft-stop (continue generating but block approval, show upgrade CTA)?

**My recommendation:** Soft-stop with warning at 80%, hard-stop at 100%. At 100% generation stops (no wasted LLM cost), review queue shows "Monthly limit reached. Upgrade to continue." All monitoring/intelligence continues.

---

### 6. Work email requirement for trial?

The brief says "Require work email to sign up. No gmail/hotmail."

**Current state:** We removed domain restriction in July because it was blocking signups. Anyone can register.

**Question:** Do you want me to re-add domain filtering? Or keep open registration + email verification (current)?

**My recommendation:** Keep it open. Email verification already filters bots. Domain filtering kills conversion for freelancers, consultants, and startup founders who use gmail. We can add it later if abuse becomes a problem.

---

### 7. AEO/GEO — what's "basic" vs "full"?

The brief lists AEO reporting as both included and as an upsell ($149/mo). The UX spec shows it locked for Seed/Starter.

**Question:** Is GEO/AEO monitoring included in Seed/Starter (basic = fewer queries, less frequent) or completely locked?

**My recommendation:** Include basic monitoring for all paid plans (2 queries/week, Perplexity only). Growth+ gets full monitoring (20+ queries, multi-provider, Tue+Fri schedule). This way every client sees their "0% visibility" from day 1 — strongest upgrade motivator.

---

## What I'll Build (Once You Confirm)

1. **`PLAN_LIMITS` config dict** — single source of truth for all limits per plan
2. **Pipeline gate** — generation skipped when monthly cap reached (saves LLM cost)
3. **Portal usage meters** — actions, avatars, subreddits (per UX spec: amber at 80%, red at 95%)
4. **Feature gates** — competitor dashboard, Slack, reports locked by plan
5. **Contextual upgrade CTAs** — per your upsell placement map (max 1 per screen)
6. **Admin override** — `max_comments_per_month` on client model overrides plan default (for custom deals)

Estimated effort: 3-4 days (mostly UI gates + the enforcement logic in pipeline).

---

## Timeline Pressure

Without enforcement, a single aggressive trial user could burn $50+ in LLM costs. With 3 trial signups this week, this is becoming real. I'd like to ship limits within a week of your confirmation.

---

**Please reply with:**
1. Confirmed / corrected numbers table
2. Answers to questions 1-7
3. Any changes to the upsell ladder

Thanks.
