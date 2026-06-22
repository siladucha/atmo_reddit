# Trial Execution Gap — Architecture Brief for Tzvi

**Date:** June 20, 2026  
**From:** Max  
**Priority:** Critical (blocks all self-serve trial conversion)

---

## TL;DR

Every self-service trial client currently enters a **silent dead state** after completing onboarding. The system is "active" but produces zero output because no avatar exists. This is not a UI bug — it's a structural gap between onboarding and execution.

---

## The Problem in Simple Terms

A client signs up for trial, completes the 6-step wizard (website, keywords, subreddits, voice, avatar config, activate). The system says "You're live!" and starts scraping Reddit data.

**But nothing happens.** No scoring. No comment generation. No EPG. Empty dashboard. For 14 days. Trial expires. Client leaves.

Why? Because "avatar config" (Step 5) is a placeholder — it doesn't actually create or assign an avatar. And without an avatar, the entire pipeline does nothing.

---

## Why This Matters (Business Impact)

| Metric | Current State | Expected State |
|--------|--------------|----------------|
| Trial → First Value | Never (0 avatars → 0 output) | < 24 hours |
| Trial → Conversion | ~0% for self-serve | Target: 15-25% |
| Support overhead | Admin must manually intervene | Zero-touch |
| Scraping cost wasted | $0.06/day per dead client (AI scoring attempted) | $0 (no pipeline if no avatar) |

Every self-serve trial that goes through the wizard today is a lost lead.

---

## What's Broken (Non-Technical)

Two systems that should be connected are not:

```
ONBOARDING SYSTEM          EXECUTION SYSTEM
────────────────           ────────────────
✅ Client created           ❌ No avatar
✅ Keywords set             ❌ No one to post as
✅ Subreddits chosen        ❌ Pipeline skips
✅ Voice configured         ❌ EPG skips
✅ "Active" flag set        ❌ Zero output
✅ Scraping started         ❌ Data unused
```

The onboarding wizard creates a **configured but non-functional** client.

---

## Decision Required

**Question:** What should happen when a trial client completes onboarding?

### Option 1: Client Brings Their Own Reddit Account (BYOA)

- Step 5 becomes mandatory: "Enter your Reddit username"
- System analyzes their account, classifies their voice, creates avatar
- Wizard won't complete without a real avatar
- **Cost to us:** $0
- **Friction:** High (user needs Reddit account, may hesitate to connect it)
- **Risk:** User's account is the one posting (they carry the risk)

### Option 2: We Assign a Pre-Warmed Avatar Automatically

- After wizard completion → system assigns a warm-pool avatar
- Client immediately sees pipeline output (comments generated, EPG built)
- We absorb the avatar cost as customer acquisition cost
- **Cost to us:** ~$50-100 per trial (avatar depreciation + AI costs for 14 days)
- **Friction:** Zero
- **Risk:** We carry avatar risk; need inventory management

### Option 3: Hybrid — User Chooses (Recommended)

- Step 5 shows two paths:
  - "Connect your Reddit account" (free, instant)
  - "Use our managed avatar" (included in trial, pre-warmed)
- Either way, wizard won't complete without a real avatar attached
- **Cost to us:** $0-100 depending on user choice
- **Friction:** Low (choice feels empowering)
- **Risk:** Split between user and us depending on path

---

## What I Need From You

1. **Which option?** (1, 2, or 3) — this determines the engineering work
2. **If Option 2 or 3:** Are we willing to "spend" a warm-pool avatar per trial? Or should managed avatars be limited to paid plans only?
3. **Avatar cost model for trials:** Should trial avatars be:
   - Cheapest from warm pool (Silver-tier)
   - Shared/time-limited (revoked if trial expires without conversion)
   - New Phase-1 accounts (cheapest, no pre-existing karma)

---

## Timeline Impact

| Option | Engineering Effort | Ship Date |
|--------|-------------------|-----------|
| Option 1 (BYOA mandatory) | 2-3 days | This week |
| Option 2 (Auto-assign) | 4-5 days | Next week |
| Option 3 (Hybrid) | 5-7 days | Next week |

Until this is fixed, self-serve trials are architecturally broken. The marketing site can drive signups, but they all hit a dead end.

---

## Technical Details (Skip If Not Interested)

The critical missing invariant:

```
SYSTEM_READY = client.is_active AND avatar_count(client) > 0
```

Currently the system allows:
```
client.is_active = True
avatar_count = 0
pipeline = RUNNING
output = 0
```

This is equivalent to a configured but empty printer queue — the system is "on" but has no paper.

Full technical analysis: `docs/trial_flow_state_machine.md`
