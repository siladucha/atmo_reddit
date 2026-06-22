# Trial Flow — State Machine Analysis

**Date:** June 20, 2026
**Author:** Max (tech audit)
**Status:** Architecture gap documented

---

## State Machine Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         TRIAL ONBOARDING FLOW                            │
└──────────────────────────────────────────────────────────────────────────┘

[START]
   │
   ▼
┌──────────────────────┐
│ 1. TRIAL_SIGNUP      │ POST /onboard/trial/signup
│                      │ • Validate work email (blocks Gmail etc.)
│                      │ • Honeypot check
│                      │ • Creates Client(plan_type="trial", max_avatars=1,
│                      │   max_comments_per_month=30, is_active=True)
│                      │ • Creates User(role=client_admin, client_id=client.id)
│                      │ • Login cookie → redirect /onboard
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ 2. WIZARD_STEP_1     │ Website URL → AI scrapes → ICP extraction
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ 3. WIZARD_STEP_2     │ Keywords generation (high/medium/low)
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ 4. WIZARD_STEP_3     │ Subreddit suggestions + manual add
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ 5. WIZARD_STEP_4     │ Brand voice calibration (tone samples)
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ 6. WIZARD_STEP_5     │ Avatar config (PLACEHOLDER — no avatar created!)
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ 7. WIZARD_STEP_6     │ Quality gate check → Activate
│    (ACTIVATION)      │ • client.is_active = True
│                      │ • client.onboarding_completed_at = now()
│                      │ • Emit "client_onboarded" activity event
│                      │ • Trigger Day 1 scraping (subreddits)
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ 8. COMPLETE          │ Confirmation page. Client in portal.
│    ⚠️ NO AVATARS!    │ Client activated, BUT execution layer is EMPTY.
└──────┬───────────────┘
       │
       │  ← GAP: manual step, NOT part of wizard flow
       ▼
┌──────────────────────┐
│ 9. AVATAR_ONBOARD    │ GET /clients/{id}/avatar-onboard
│    (MANUAL!)         │ • User enters reddit username
│                      │ • PRAW fetches profile
│                      │ • Claude AI classifies (voice, strategy, bio)
│                      │ • User approves → Avatar created + assigned
│                      │ • Trial limit: max 1 avatar
└──────┬───────────────┘
       │
       │  ← trigger_avatar_onboarding()
       ▼
┌──────────────────────┐
│ 10. POST-ALLOCATION  │ Discovery session → Entity extraction →
│     ONBOARDING       │ Strategy generation → First pipeline run
└──────┬───────────────┘
       │
       ▼
┌──────────────────────┐
│ 11. EPG GENERATION   │ build_and_generate_epg_all_avatars (08:15, 14:15)
│                      │ • Finds avatar by client_ids
│                      │ • is_trial_expired() check
│                      │ • 14-day window
└──────────────────────┘
```

---

## Question-by-Question Analysis

### 1. When is the Tenant (trial client) created?

**At `POST /onboard/trial/signup`** — immediately upon email/password submission. The Client record is created BEFORE entering the wizard:

```python
# routes/onboarding.py — trial_signup()
trial_client = Client(
    client_name=company_name or email.split("@")[0],
    brand_name=company_name or email.split("@")[0],
    plan_type="trial",
    max_avatars=1,
    max_comments_per_month=30,
    is_active=True,          # ← NOTE: active immediately!
    current_onboarding_step=1,
)
```

**Issue:** `is_active=True` is set at creation, then redundantly set again at step 6 activation. Should be `is_active=False` until step 6.

---

### 2. Where should provisioning of execution layer (avatars/workers) happen?

**Currently exists in two places, both manual:**

1. **Avatar onboard UI** (`routes/avatar_onboard.py`) — user enters Reddit username → PRAW analysis → AI classification → user approves → avatar created.

2. **Admin assign** (`services/admin.py: assign_avatars_to_client()`) — admin manually assigns farm avatar to client. After assignment, auto-triggers `run_avatar_onboarding.delay()` if `client.onboarding_completed_at is not None`.

**There is NO automatic provisioning trigger.**

---

### 3. Is it automatic, manual, or partial?

**Fully manual.** There is no automatic trigger that allocates an avatar to a new trial client. Two paths exist:

- Trial user navigates to avatar onboard UI and onboards their own Reddit account
- Admin/partner enters admin panel and manually assigns a farm avatar

---

### 4. Why isn't this step a mandatory stage of trial onboarding flow?

**Because the wizard was designed as "client profile setup", not as "execution layer launch".**

Step 5 (Avatar config) is a UI placeholder — it does NOT create a real avatar. The quality gate in step 6 checks for subreddits and keywords but **does NOT check for avatar existence**.

This is an architectural gap: a client can complete all 6 steps, be "activated", but the pipeline will never execute a single action because there is no avatar.

---

### 5. Where is the logic "which avatars should a new trial client get"?

**Nowhere as an explicit template.** Only these constraints exist:

| Location | What it defines |
|----------|-----------------|
| `Client.max_avatars = 1` | Quantity limit |
| `_check_trial_limit()` in `avatar_onboard.py` | Blocks adding 2nd avatar |
| `DEFAULT_PHASE1_HOBBY_SUBREDDITS` in `sanitize.py` | Fallback hobbies: `["NewToReddit", "AskReddit", "CasualConversation"]` |

There is no concept of "template avatar set", "default configuration per plan", or "what should a trial avatar look like".

---

### 6. Is there a "default avatar set per trial plan"?

**No. Does not exist.** Reasons:

1. Historically RAMP was built as managed-service (agency model) — admin assigns avatars to clients manually.
2. Self-service onboarding was added later, but execution layer remained manual.
3. Pre-warmed avatars are inventory assets (Silver $199, Gold $499) — automatic allocation contradicts the business model of charging for them.

---

### 7. What happens if admin never adds avatars?

**Dead client.** Specifically:

```
run_full_pipeline_all_clients
  → iterates all active clients
  → dispatches score_threads(client_id)
    → inside: queries avatars WHERE client_ids CONTAINS client.id
    → finds 0 avatars
    → returns 0
  → generate_comments finds 0 scored threads → returns 0
  → EPG finds 0 eligible avatars → skips

Result: Day 1 scraping executes (subreddits exist), data accumulates unused.
Client sees empty dashboard. After 14 days trial expires. Conversion = 0.
```

---

### 8. Should a system trigger auto-create avatars? (Event-driven: TrialCreated → ProvisionAvatars)

**Depends on business model of the trial:**

| Model | Trigger Needed | What Gets Created |
|-------|---------------|-------------------|
| BYOA (bring your own account) | No auto-provision needed. But need **mandatory wizard step** | Nothing — user onboards themselves |
| Pre-warmed allocation | `TrialCreated → ProvisionAvatars` | Farm avatar (warmest from `warm` pool) auto-assigned |
| Hybrid | Wizard step: "Bring yours OR get ours" | Depends on user choice |

Current architecture **supports none of these models cleanly** — wizard doesn't require avatar creation, and no automatic allocation exists.

---

### 9. Where is the gap between TrialCreated event and EPG task generation?

```
TrialCreated (signup)
       │
       ├── Client created ✅
       ├── User created ✅
       ├── (wizard steps 1-6) → subreddits, keywords, voice configured ✅
       ├── Day 1 scraping triggered ✅
       │
       ╳── ← GAP ← no avatar exists
       │
       ├── Orchestrator (08:00/14:00): score_threads → finds avatars → 0 → skip
       ├── EPG (08:15/14:15): build_and_generate_epg → finds avatars → 0 → skip
       │
       ╳── DEAD STATE: scrape data accumulates, no pipeline output
       │
       │   ... after N hours/days, IF user discovers avatar onboard UI ...
       │
       ├── Avatar created + assigned → trigger_avatar_onboarding()
       ├── Discovery + Strategy + First pipeline ✅
       └── Next EPG cycle picks up avatar ✅
```

**Core problem**: between step 6 (activation) and avatar creation there is no CTA, no reminder, no mandatory step. This is a **silent dead-end** — the client may think everything is working (dashboard shows empty cards) without understanding another step is needed.

---

## Recommendations

### Option A: Make Avatar Onboard a Mandatory Wizard Step

- Step 5 becomes real avatar onboard: "Enter your Reddit username" → PRAW analysis → approve → avatar created
- Quality gate (step 6) adds check: `avatar_count >= 1`
- Pros: simplest fix, no inventory management needed
- Cons: requires user to have a Reddit account

### Option B: Auto-Allocate Pre-Warmed Avatar on Activation

- After step 6 activation → system allocates cheapest farm avatar from `warm` pool
- `assign_avatars_to_client()` → `trigger_avatar_onboarding()`
- Upsell Gold avatar later
- Pros: instant time-to-value, zero friction
- Cons: requires avatar inventory management, cost per trial

### Option C: Hybrid (Recommended)

- Step 5 wizard: "Bring your Reddit account OR we'll assign one from our network"
- If BYOA: inline avatar onboard (username → analysis → approve)
- If managed: auto-allocate from warm pool
- Quality gate enforces `avatar_count >= 1` regardless of path
- Pros: supports both models, mandatory step, no dead state possible

### Option D: Post-Activation Nudge (Minimal Fix)

- Keep current flow but add:
  - After step 6 redirect → "Next: Add your Reddit avatar" CTA (not skippable)
  - If no avatar after 2h → SSE notification + email reminder
  - Dashboard shows prominent "Setup incomplete" banner until avatar exists
- Pros: least code change
- Cons: still possible to reach dead state

---

## Related Files

| File | Role |
|------|------|
| `app/routes/onboarding.py` | Trial signup + 6-step wizard |
| `app/routes/avatar_onboard.py` | Avatar onboarding UI |
| `app/services/onboarding/avatar_onboarding.py` | Post-allocation orchestrator |
| `app/services/onboarding/quality_gate.py` | Step 6 validation |
| `app/services/trial_guard.py` | 14-day expiry check |
| `app/services/admin.py` (assign_avatars_to_client) | Manual avatar assignment |
| `app/tasks/orchestrator.py` | Pipeline orchestration (skips 0-avatar clients) |
| `app/tasks/epg.py` | EPG generation (skips 0-avatar clients) |
| `app/tasks/ai_pipeline.py` | Scoring/generation (skips 0-avatar clients) |

---

## Decision Needed

**Business question for Tzvi:** What is the trial model?

1. **BYOA only** — trial users must bring their own Reddit account (free, but higher friction)
2. **Pre-warmed allocation** — we give them a Silver avatar from inventory (cost: ~$50 per trial in avatar depreciation)
3. **Hybrid** — user chooses (recommended for conversion optimization)

This decision determines the engineering fix. Until decided, the gap persists and trial conversion will remain near zero for self-service signups.
