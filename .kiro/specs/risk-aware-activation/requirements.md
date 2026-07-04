# Requirements — Risk-Aware Avatar Activation

## Problem Statement

Current Phase 0→1→2 progression is time-based with fixed safe subreddits. Avatars spend 4-6 weeks in generic warming (AskReddit, CasualConversation) before reaching client's target subreddits. This is:

1. **Slow** — no thematic footprint built during warming
2. **Wasteful** — karma from generic subs doesn't establish authority in target niche
3. **Blind to risk** — all subs treated equally regardless of moderation aggressiveness
4. **Not adaptive** — same path for all avatars regardless of their profile or client needs

## Solution

Risk-Aware Activation Strategy — uses SubredditRiskProfile data to create personalized activation routes that move avatars toward target subreddits through progressively riskier "bridge" zones.

## Architecture Model

```
Avatar Created / Demoted to Phase 0
    ↓
ActivationRouter.plan_route(avatar, client)
    ↓
┌──────────────────────────────────────────────────────┐
│  SAFE ZONE (risk 0-25)         1-2 comments/day      │
│  Universal safe subs            Goal: karma ≥ 10     │
├──────────────────────────────────────────────────────┤
│  BRIDGE ZONE (risk 25-50)      1-2 comments/day      │
│  Thematic, low-moderation       Goal: niche footprint│
├──────────────────────────────────────────────────────┤
│  TARGET ZONE (risk 50-80)      Phase 2+ normal ops   │
│  Client's actual subreddits     Goal: client value   │
└──────────────────────────────────────────────────────┘
```

---

## Requirements

### R1 — Zone Classification

- R1.1: Every subreddit with a SubredditRiskProfile is classified into a zone:
  - Safe: risk_score 0-25
  - Bridge: risk_score 26-50
  - Target: risk_score 51-80
  - Dangerous: risk_score 81-100 (blocked for Phase 0-1)
- R1.2: Subreddits without a risk profile default to Bridge zone (conservative).
- R1.3: Zone thresholds configurable via system settings.
- R1.4: UNIVERSAL_SAFE_LIST maintained as fallback (AskReddit, CasualConversation, TodayILearned, etc.)

### R2 — Activation Route Planning

- R2.1: On avatar creation or demotion to Phase 0, `ActivationRouter` generates a route.
- R2.2: Route contains: `phase0_subs` (safe zone), `phase1_subs` (bridge zone), `phase2_subs` (target zone).
- R2.3: Bridge zone selection uses thematic proximity to client's target subreddits:
  - Same category/topic but lower moderation
  - AvatarSubredditCompatibility score ≥ 50
  - Risk score 26-50
- R2.4: Route stored on avatar (JSONB field `activation_route`).
- R2.5: Route regenerated if client subreddits change or risk profiles update significantly.
- R2.6: Max 5 subs per zone in route (prevents spread-too-thin).

### R3 — Zone-Aware Budget Allocation

- R3.1: EPG Portfolio Manager respects zone when building slots for Phase 0-1 avatars.
- R3.2: Budget per zone per day:

| Zone | Phase 0 | Phase 1 |
|------|---------|---------|
| Safe | 2 comments | 1 comment |
| Bridge | 1 comment | 2-3 comments |
| Target | 0 | 0 (Phase 2+ only) |

- R3.3: Total daily budget still respects phase caps (Phase 0: 1-3, Phase 1: 3-5).
- R3.4: Priority: Bridge > Safe within Phase 1 (build niche, not just karma).
- R3.5: If bridge sub unavailable (no fresh threads), fall back to safe zone.

### R4 — Dangerous Hours Avoidance

- R4.1: Before posting to any sub, check `dangerous_hours` from SubredditRiskProfile.
- R4.2: If current hour (in sub's timezone) is in dangerous_hours → defer to next safe window.
- R4.3: Deferred slots shift by 1-3 hours (not skipped).
- R4.4: Applies to all zones, all phases.

### R5 — Zone Graduation (Transitions)

- R5.1: **Safe → Bridge** graduation criteria:
  - total_karma ≥ 10
  - cqs_level ≠ "lowest"
  - survival_rate(7d) ≥ 90%
  - account age ≥ 7 days
  - ≥ 3 comments posted, 0 deleted
- R5.2: **Bridge → Target** graduation criteria:
  - karma ≥ 15 in at least 2 bridge subreddits
  - survival_rate(14d) ≥ 85%
  - total_karma ≥ 50
  - compatibility_score ≥ 60 for target subs
  - fitness_gate passes for target subs
- R5.3: Graduation checked daily at 06:00 (alongside phase evaluation).
- R5.4: Zone graduation ≠ phase promotion. Zone is subreddit routing; phase is content type.
  - Phase 0 avatar graduating Safe→Bridge stays Phase 0 (still 1/day, safe content)
  - Phase 1 avatar graduating Bridge→Target triggers Phase 2 evaluation
- R5.5: Minimum sample size for survival rate: 5 posted comments (same as phase demotion).

### R6 — Demotion Within Zones

- R6.1: If survival_rate drops below 70% in bridge zone → demote to safe zone.
- R6.2: If avatar gets per-subreddit ban in bridge sub → remove from route, find alternative.
- R6.3: Demotion preserves karma (avatar keeps earned reputation).
- R6.4: Re-graduation requires fresh 7-day window of clean activity.

### R7 — Bridge Subreddit Discovery

- R7.1: For each client target subreddit, system identifies 3-5 bridge candidates.
- R7.2: Bridge candidates are subreddits that:
  - Share topic/category with target
  - Have risk_score 26-50
  - Have compatibility_score ≥ 50 for this avatar
  - Are NOT in another client's exclusive subreddit list
- R7.3: Bridge discovery uses existing SubredditRiskProfile + emotional profile data.
- R7.4: If insufficient bridges found → use generic hobby subs from avatar's hobby_subreddits.
- R7.5: Bridge candidates refreshed weekly (when risk profiles update).

### R8 — Integration with Existing Systems

- R8.1: EPG Portfolio Manager reads `activation_route` when building slots for Phase 0-1.
- R8.2: FitnessGate still applies (hard block if avatar doesn't meet sub requirements).
- R8.3: Hot thread filter still applies (>200 ups with low karma → skip).
- R8.4: Smart Scoring uses route subs for thread candidate selection.
- R8.5: Phase evaluator uses zone data for promotion decisions.
- R8.6: Health checker not affected (runs independently of zone).

### R9 — Observability

- R9.1: Activity events emitted: `zone_graduation`, `zone_demotion`, `route_planned`, `route_updated`.
- R9.2: Admin UI shows current zone + route for each avatar.
- R9.3: Portal shows simplified progress ("Building niche presence" vs "Ready for target").
- R9.4: Zero-day report includes zone context (why no opportunities in current zone).

---

## Non-Functional Requirements

### NF1 — Performance
- Route planning: < 2s per avatar (DB queries, no LLM).
- Zone graduation check: < 500ms per avatar.
- No additional Reddit API calls (uses existing risk profile data).

### NF2 — Safety
- Dangerous zone (81-100) is absolute block — no override except admin manual.
- Bridge subs still subject to all safety gates (liveness, fitness, rate limits).
- Fallback: if risk profile stale (>14d), treat sub as Bridge (conservative).

### NF3 — Backward Compatibility
- Avatars without activation_route continue working (legacy path: hobby_subreddits only).
- Route is optional enhancement, not mandatory gate.
- Existing Phase evaluation unchanged — zone is an additional signal.

---

## Out of Scope (MVP)

- LLM-based bridge discovery (manual/rules only for now)
- Cross-avatar coordination (two avatars avoiding same bridge sub)
- Dynamic zone thresholds per subreddit category
- Client-facing route configuration (admin only)
- Automated route optimization based on historical outcomes

## Dependencies

- SubredditRiskProfile (DONE — weekly batch)
- AvatarSubredditCompatibility (DONE — weekly refresh)
- FitnessGate (DONE — pre-generation check)
- EPG Portfolio Manager (DONE — needs route integration)
- Phase Evaluator (DONE — needs zone signal)

## Success Metrics

- Time to Phase 2: 4-6 weeks → 2-3 weeks (with pre-warmed bridge karma)
- Survival rate in target subs: +15% (avatar arrives with relevant karma)
- Demotion rate: -30% (avatar has niche footprint, not cold-start)
- Zero-day reports for Phase 1: -50% (bridge subs provide opportunities)
