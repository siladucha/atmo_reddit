# Reddit Platform Uncertainty Principle

## Core Principle

Reddit is a black box. Its anti-spam, anti-evil, and trust systems are opaque, undocumented, and change without notice. All architectural decisions in RAMP must account for **irreducible uncertainty** about platform behavior.

---

## What We KNOW (Confirmed — Use in Detection Logic)

| Fact | Source | Confirmed | Impact on Code |
|------|--------|-----------|----------------|
| Global shadowban = profile 404 at API level | PRAW docs + empirical (June 28) | Yes | If `redditor.comments.new()` returns ANY data → not shadowbanned |
| Shadowban recovery is possible without appeal | Observed: Flaky_Finder_13 + connor_lloyd (June 28) | Yes | Never assume shadowban is permanent. Continue monitoring. |
| CQS level can improve while shadowban active | Observed: Flaky_Finder_13 LOWEST→LOW (June 26) | Yes | CQS and shadowban are independent Reddit mechanisms |
| Subreddit rules extractable via sidebar/wiki | PRAW API + empirical (June 23) | Yes | `rule_extractor.py` → structured rules (min_karma, min_age, frequency limits) |
| Moderation aggressiveness varies by subreddit and time of day | Empirical: `SubredditDailyStats` analysis | Yes | `moderation_profiler.py` → dangerous_hours, aggressiveness classification |
| Low-karma accounts on hot threads get disproportionately removed | r/sysadmin, r/networking, r/devops patterns (June 2026) | Yes | Hot thread filter (>200 ups + avatar karma <100 → skip) + fitness_gate extreme aggressiveness block |
| Subreddits with risk_score 0-25 have near-zero removal rates for new accounts | SubredditRiskProfile data (June-July 2026) | Yes | `activation_router.py` uses these as "safe zone" for Phase 0-1 warming. Universal safe list: AskReddit, CasualConversation, TodayILearned, etc. |
| Risk_score 26-50 subs tolerate low-karma accounts when content is topical | Empirical: survival rate analysis in bridge zone subs | Partial (small sample) | `zone_evaluator.py` requires 90%+ survival in safe before allowing bridge entry. Conservative. |

---

## What We Do NOT Know (and cannot know)

| Unknown | Impact | How we compensate |
|---------|--------|-------------------|
| Exact shadowban trigger criteria | Cannot prevent 100% of bans | Safety margins + rapid detection + recovery paths |
| Whether "trust score at birth" exists | Cannot guarantee clean accounts | Diversify infrastructure per account |
| How Reddit links accounts (full fingerprint model) | Cannot guarantee isolation | Assume worst case (IP + device + timing + email) |
| CQS algorithm internals | Cannot optimize for CQS directly | Optimize for proxy signals (survival rate, karma velocity) |
| Shadowban recovery timeline | Cannot promise recovery SLA | Monitor continuously, never assume permanent |
| Whether r/WhatIsMyCQS is monitored | Cannot safely use as first action | CQS check only after organic activity |
| AutoMod rules per subreddit (hidden/dynamic) | Cannot predict ALL removals in advance | Learn from removals via `moderation_profiler` + adapt per-sub strategy. Extracted sidebar rules cover ~60-70% of explicit rules; hidden AutoMod configs remain opaque |
| Reddit batch processing schedule | Cannot predict when bans will land | Continuous monitoring, not point-in-time |
| Whether subreddit rules in sidebar match actual AutoMod config | Extracted rules ≠ full enforcement. Mods may have undocumented AutoMod rules | Fitness gate uses extracted rules as minimum bar; `moderation_profiler` detects empirical patterns (deletions, dangerous hours) independent of stated rules |
| Rate at which subreddit rules change | Weekly extraction may miss mid-week rule changes | 30-day rolling moderation window smooths out short-term noise; spike detection flags sudden changes |
| Whether "bridge zone" subs have stable moderation over time | Bridge subs (risk 26-50) may shift moderation up/down mid-week | Zone demotion on survival <70% + weekly risk profile refresh. Conservative: require 90% survival before bridge, 85% before target |
| Optimal zone graduation speed | Too fast = removal spike in bridge/target. Too slow = wasted warming time | Min sample size (5 posted) prevents premature graduation. 7-day minimum in safe zone. Can tune thresholds via constants without deploy |

---

## Decision Framework Under Uncertainty

### 1. Assume worst case for account linkage

When in doubt about whether Reddit can link two accounts — **assume it can**. Design for:
- IP isolation (unique per account, not per session)
- Device isolation (unique fingerprint per account)
- Temporal isolation (no cluster creation patterns)
- Behavioral isolation (no identical first-actions)

### 2. Safety margins must be wider than "necessary"

Because we don't know exact thresholds:
- If hot thread threshold might be 100 or 300 ups → filter at 200 (conservative middle)
- If daily posting cap might trigger at 5 or 15 → cap at 8 (well below risk)
- If account age safety is 30 or 90 days → treat <90d as "young" (wider margin)
- **Use risk-aware zone routing** — don't place avatars in high-risk subs until proven in lower-risk thematic bridges (spec: `.kiro/specs/risk-aware-activation/`)

### 3. Every avatar is expendable

No business logic should depend on a specific avatar surviving. Architecture must handle:
- Instant loss of any single avatar (shadowban, suspension)
- Loss of entire cohort (Reddit batch action)
- Permanent loss with no recovery (identity-based ban)

### 4. Detection > Prevention

We cannot prevent all bans (we don't control Reddit's algorithm). Therefore:
- **Fast detection** (hours, not days) is more valuable than **perfect prevention**
- Health checks, CQS monitoring, submission probes — continuous, independent of avatar state
- Human notification pipeline must be reliable (operator knows within 4h)

### 5. Experiments over assumptions

When facing a Reddit behavior question:
- Don't assume based on community folklore
- Design a safe experiment (canary account, A/B on timing, etc.)
- Record result in `docs/ops/reddit_platform_intelligence.md`
- Update steering only after confirmed observation

---

## Relationship to Other Docs

| Document | Role |
|----------|------|
| `docs/ops/reddit_platform_intelligence.md` | Evidence registry (what we observed) |
| This file (`.kiro/steering/reddit_uncertainty.md`) | Principles (how we act under uncertainty) |
| `.kiro/steering/shadowban_detection.md` | Detection mechanics (how we detect bans) |
| `.kiro/steering/pipeline_safety_architecture.md` | Safety gates (how we prevent damage) — includes Subreddit Risk Profile & Fitness Gate & Risk-Aware Activation |
| `app/services/rule_extractor.py` | Extracts explicit rules from sidebar/wiki (what subs SAY) |
| `app/services/moderation_profiler.py` | Learns empirical patterns from deletions (what subs DO) |
| `app/services/risk_scorer.py` | Combines rules + empirical data → composite risk score |
| `app/services/fitness_gate.py` | Pre-generation gate that blocks dangerous avatar×subreddit combinations |
| `app/services/activation_router.py` | Zone-based subreddit routing for Phase 0-1 (uses risk_score for zone classification) |
| `app/services/zone_evaluator.py` | Graduation/demotion criteria for zone transitions (uses survival rate + karma) |

---

## Anti-Patterns (what NOT to do)

1. **Don't treat Reddit rules as stable.** What worked last month may not work today.
2. **Don't optimize for a single signal.** CQS, karma, survival rate — all are proxies, none is ground truth.
3. **Don't assume human behavior = safe behavior.** Reddit's anti-evil detects patterns humans also make.
4. **Don't promise clients timeline certainty.** Warming timelines are estimates, not guarantees. Reddit can invalidate any avatar at any moment.
5. **Don't batch operations across accounts.** Any shared infrastructure (IP, timing, pattern) = linkage risk.
6. **Don't trust "nothing happened = safe."** Reddit uses deferred action. Silence ≠ approval.

---

## For Client Communication (Tzvi)

When explaining to clients why timelines are uncertain:
- "Reddit's trust systems are opaque and change without notice"
- "We optimize for maximum safety but cannot guarantee zero incidents"
- "Our detection and recovery systems minimize downtime when issues occur"
- Never promise: "this account won't be banned"
- Always frame: "outputs (drafts/week) are guaranteed; outcomes (visibility) depend on platform"


---

## What We KNOW (Added July 4, 2026)

| Fact | Source | Confirmed | Impact on Code |
|------|--------|-----------|----------------|
| New Reddit uses reCAPTCHA Enterprise on comment submit | Intercepted `CreateCaptchaToken` GQL mutation (July 4) | Yes | API/GraphQL posting approach blocked — need DOM interaction |
| New Reddit submit goes through `faceplate-form` web component, NOT fetch() | Interceptor didn't catch submit (July 4) | Yes | Can't monkey-patch fetch to intercept/replay submit |
| `faceplate-textarea-input` has open shadowRoot with `#innerTextArea` | Confirmed via console query (July 4) | Yes | Element exists and accessible, width=358px, BUT requires trusted click to expand |
| Old Reddit has plain `<textarea>` + `.save` button, no reCAPTCHA visible | Known from old.reddit.com DOM | Yes | Old Reddit = simplest posting path |
| Reddit session cookies work on both old.reddit.com and www.reddit.com | Same auth domain | Yes | Switching to old reddit doesn't require re-login |

## What We Do NOT Know (Added July 4, 2026)

| Unknown | Impact | How we compensate |
|---------|--------|-------------------|
| Whether Reddit has server-side heuristics for "programmatic posting" on old reddit | Could silently flag accounts | A/B test comparing old_reddit vs manual posting (spec ready) |
| Whether reCAPTCHA Enterprise score affects post visibility (not just submit) | Low-score sessions might get shadowban | Old reddit may bypass this entirely (no reCAPTCHA observed) |
| Whether Reddit correlates "always uses old.reddit.com for commenting" as bot signal | Unlikely (millions use old reddit) but unknown | Monitor via A/B test health metrics |
| How long until Reddit retires old.reddit.com | Announced multiple times, never executed | Fallback plan: debugger v2 or email delivery |

## Prepared Countermeasure: Human Typing Simulation (July 4, 2026)

**Module:** `ramp_extension/background/human-typing.js` (DORMANT — not imported, not active)

**What it provides:**
- `humanType(tabId, text)` — CDP keystroke dispatch, 55-180ms per char, typo rate 1.2%, adjacent-key errors
- `ghostMove(tabId, from, to)` — Bézier mouse curves via CDP `Input.dispatchMouseEvent`
- `ghostClick(tabId, from, target)` — move + hover pause + press/release

**Activation trigger:** A/B test shows old_reddit group has shadowban rate ≥2σ above manual_email for ≥2 consecutive weeks.

**Integration steps when activating:**
1. Import `humanType` from `./human-typing.js` in `executor-old-reddit.js`
2. Replace `sendMsg(tabId, { type: 'OLD_REDDIT_INSERT_TEXT', text })` with debugger-attach → focus textarea → `humanType(tabId, text)` → debugger-detach
3. Typing a 200-char comment takes ~25-35s (vs instant bulk insert). Adjust task timeout accordingly.
4. `ghostClick` can replace `sendMsg(tabId, { type: 'OLD_REDDIT_SUBMIT' })` for submit button.

**Risk:** `R-PLATFORM-012` in risk registry.
