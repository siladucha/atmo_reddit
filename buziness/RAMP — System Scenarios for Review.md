# RAMP — System Scenarios

**Date:** May 20, 2026  
**Prepared for:** Tzvi Vaknin  
**From:** Maxim Breger  
**Purpose:** Walk through the key system scenarios so you understand what happens at each stage, what you'll see, and what decisions you need to make.

---

## How to Read This Document

Each scenario describes:
- **Who** triggers it (you, the system, or a client)
- **What** happens step by step
- **What you see** in the admin panel
- **What can go wrong** and how the system handles it
- **Your decision points** — where you need to act

---

## Scenario 1: New Client Onboarding

**Who triggers:** You (Tzvi) or a partner admin

**Steps:**

1. You open `/admin/onboarding` and start the 7-step wizard
2. **Step 1 — Client Profile:** Enter client name, brand name, website, industry, plan tier
3. **Step 2 — Subreddits:** Add target subreddits (professional) + hobby subreddits (for avatar warming)
4. **Step 3 — Keywords:** Define high/medium/low priority keywords for scoring
5. **Step 4 — Avatars:** Assign existing avatars to this client (or create new ones)
6. **Step 5 — Personas:** Configure voice profiles for each avatar (tone, constraints, vocabulary)
7. **Step 6 — Pipeline Config:** Set scrape interval, generation limits, safety thresholds
8. **Step 7 — Test Run:** System runs a dry pipeline (scrape → score → generate one draft) to validate everything works

**What you see:**
- Each step has a form with validation
- Step 7 shows a sample generated comment for your review
- After completion, client appears in `/admin/clients` list

**Decision points:**
- Which plan tier? (affects avatar count, comment limits)
- Which subreddits are professional vs. hobby?
- How aggressive should the avatar voice be?

**What can go wrong:**
- Reddit API can't find a subreddit → system shows error, you fix the name
- No avatars available → you need to assign or create one first
- Test run generates low-quality comment → adjust persona voice and re-run

---

## Scenario 2: Daily Pipeline Execution (Automated)

**Who triggers:** System (Celery Beat schedule, twice daily at 08:00 and 14:00 Israel time)

**Steps:**

1. **Scraping** (continuous, every 60 seconds): System checks which subreddits are stale → scrapes new threads from Reddit → saves to database
2. **Scoring** (08:00 + 14:00): For each client, system scores unscored threads using Gemini Flash AI. Each thread gets relevance + quality + strategic score. Top threads tagged "engage"
3. **Generation** (immediately after scoring): For "engage" threads, system selects best avatar (by subreddit karma), picks a rhetorical approach, generates a comment draft using Claude Sonnet
4. **Review queue fills up**: Drafts appear in your review queue, waiting for human approval

**What you see:**
- `/admin/dashboard` → Activity Feed shows each step completing
- `/admin/dashboard` → Topology panel shows which nodes are active (green = running, gray = idle)
- Review queue counter increases after generation completes

**What can go wrong:**
- Reddit API rate limit hit → system backs off automatically, retries in 60 seconds
- LLM API error → retries 3 times with exponential backoff (60s, 120s, 240s)
- All retries fail → task goes to failed state, logged in Activity Feed
- Kill switch is ON → pipeline skips that stage entirely (you'll see "pipeline_enabled: false" warning)

**Your decision points:** None during normal operation. System is fully automated. You only intervene if something breaks (see Scenario 8: Emergency).

---

## Scenario 3: Human Review & Approval

**Who triggers:** You (or a client_manager reviewing their own drafts)

**Steps:**

1. Open review queue (`/admin/review` or client hub → Review tab)
2. See list of pending drafts, each showing:
   - Thread title + subreddit
   - Avatar name + approach used
   - Generated comment text
   - Thread liveness indicator (🟢 alive / 🔒 locked)
3. For each draft, choose:
   - **Approve** → draft moves to "approved" status → notification sent to avatar owner (Telegram)
   - **Edit** → modify the text → system captures your edit for learning → then approve
   - **Reject** → draft discarded, reason logged

**What you see:**
- Comment text with the avatar's voice
- Debug view (expandable): shows which strategy was used, which few-shot examples were injected, which approach was selected
- If thread is locked (🔒): system auto-rejects, you don't need to act

**What can go wrong:**
- Thread gets locked between generation and your review → system detects this automatically, shows 🔒 badge, auto-rejects
- Comment quality is poor → edit it. System learns from your edit and improves next time
- Too many drafts piling up → this means generation is outpacing review. Consider reducing generation limits in pipeline config

**Decision points:**
- Is this comment good enough to post?
- Does the tone match the avatar's voice?
- Is the approach appropriate for this subreddit?

**Learning effect:** Every edit you make is stored. After 5 edits, system recomputes correction patterns. Future drafts will be better. This is the competitive moat — 6 months of accumulated learning cannot be replicated.

---

## Scenario 4: Avatar Owner Posts via Telegram

**Who triggers:** Avatar owner (hired worker) after you approve a draft

**Steps:**

1. You approve a draft (Scenario 3)
2. System sends Telegram notification to the avatar owner: "New comment ready for posting"
3. Owner opens Telegram bot → sees the approved draft with:
   - Comment text (ready to copy)
   - "Open Reddit" button (direct link to the thread)
   - "Confirm Posted" button
4. Owner long-presses text → copies to clipboard
5. Owner taps "Open Reddit" → Reddit opens in browser at the exact thread
6. Owner pastes comment → submits on Reddit
7. Owner returns to Telegram → taps "Confirm Posted"
8. System marks draft as `posted`, records timestamp and posting speed

**What you see:**
- In admin panel: draft status changes from "approved" → "posted"
- Posting speed tracked (time between notification and confirmation)
- If owner doesn't post within 4 hours → system sends a reminder

**What can go wrong:**
- Owner doesn't respond → reminder at 4h, escalation to you at 24h
- Owner reports "thread is locked" → you reject the draft, system marks thread as locked
- Owner's Reddit account is suspended → they can't post. You freeze the avatar (Scenario 7)

**Decision points:**
- How many avatar owners do you need? (1 owner can handle ~20-30 posts/day)
- Payment model for owners: per-post ($0.50-2.00) or monthly salary?

**Legal protection:** Owner posts from their own device, their own IP, their own Reddit account. No programmatic Reddit API posting. Human confirms every single post. This is the key legal defense.

---

## Scenario 5: New Avatar Onboarding

**Who triggers:** You (when adding a new Reddit account to the system)

**Steps:**

1. You add avatar username in admin panel (`/admin/avatars/new`)
2. System fetches Reddit profile data via PRAW:
   - Account age, total karma, post/comment history
   - Active subreddits, posting frequency
   - Tone analysis (formal/casual, technical/emotional)
3. System proposes classification:
   - Type: client avatar / personal / inventory
   - Synthetic likelihood score (0-100%)
   - Suggested phase (1/2/3 based on karma + age)
4. You review and approve/edit the classification
5. System generates voice profile proposal (tone, vocabulary, constraints)
6. You review and approve/edit the voice profile
7. Avatar enters the pipeline at assigned phase

**What you see:**
- Avatar detail page with all Reddit data
- Confidence score (0-100) based on presence + history
- Phase indicator with progress bar (Phase 1 → 2 → 3)
- Subreddit presence map (where this avatar has karma)

**Phase rules:**
- **Phase 0 (Mentor):** Pre-warmed high-karma accounts. Excluded from ALL automated pipelines. Used for reputation presence only.
- **Phase 1** (months 1-2): Zero brand mentions. Hobby + general professional subs only. Building credibility.
- **Phase 2** (months 3-4): External source citations allowed. No direct brand links yet.
- **Phase 3** (month 5+): Brand integration. Only when karma is sufficient + thread is relevant + brand ratio below threshold.

**Decision points:**
- What phase should this avatar start at? (System suggests, you decide)
- Which client(s) should this avatar serve?
- Is the voice profile accurate? Does it match the real person's Reddit history?

---

## Scenario 6: Avatar Health Problem Detected

**Who triggers:** System (automated health checks at 07:30 and 13:30 Israel time)

**Steps:**

1. System checks each active avatar's Reddit status:
   - Shadowban check (external API)
   - CQS (Contributor Quality Score) check
   - Suspension detection
2. If problem detected:
   - **Shadowbanned** → Avatar auto-frozen immediately. All pending drafts cancelled.
   - **CQS lowest** (Phase 2+) → Avatar auto-frozen. Needs manual investigation.
   - **Suspended** → Avatar auto-frozen. Account may be permanently banned.

**What you see:**
- `/admin/avatars/{id}` → Health status badge changes to red
- Dashboard → notification/alert about frozen avatar
- Activity Feed → "avatar_frozen" event with reason
- All pending drafts for this avatar → auto-rejected

**What can go wrong:**
- False positive (Reddit API glitch) → unfreeze manually after verification
- Multiple avatars hit simultaneously → could indicate IP/pattern detection. Pause everything (Scenario 8)

**Decision points:**
- Is this a false positive? → Unfreeze
- Is the account recoverable? → Wait and re-check in 48h
- Is the account permanently banned? → Remove from system, assign replacement
- Pattern detected (multiple bans)? → Review posting strategy, reduce aggression

**Recovery options:**
- Unfreeze: Admin panel → Avatar detail → "Unfreeze" button
- Replace: Assign a different avatar to the client
- Investigate: Check posting history — was the avatar too aggressive? Too frequent?

---

## Scenario 7: Per-Avatar Freeze (Manual)

**Who triggers:** You (manual decision)

**When to use:**
- Client asks to pause one avatar temporarily
- You notice suspicious activity on an avatar
- Avatar owner is unavailable for a week
- You want to test something without this avatar participating

**Steps:**

1. Go to `/admin/avatars/{id}`
2. Click "Freeze" button
3. Enter reason (required — for audit trail)
4. Avatar immediately excluded from all pipelines:
   - No new drafts generated
   - No scoring for this avatar
   - No hobby content
   - Existing approved drafts remain (owner can still post them)

**What you see:**
- Blue "FROZEN" badge on avatar
- Freeze reason + timestamp visible
- Activity Feed logs the freeze event

**Unfreezing:**
- Same page → "Unfreeze" button
- Avatar returns to pipeline on next cycle (within 60 seconds for scraping, next scheduled run for AI)

---

## Scenario 8: Emergency — Stop Everything

**Who triggers:** You (when something goes seriously wrong)

**When to use:**
- Multiple avatars banned simultaneously
- Reddit changes their detection algorithm
- Client demands immediate stop
- You discover a bug in generation quality
- Legal concern raised

**Steps:**

1. Go to `/admin/dashboard`
2. Toggle **Global Kill Switch** → OFF
3. Entire pipeline stops immediately:
   - Scraping continues (data collection is harmless)
   - Scoring stops
   - Generation stops
   - No new drafts created
   - Existing approved drafts can still be posted manually (owner's choice)

**Granular controls:**
- `pipeline_enabled` = false → stops scoring + generation
- `generation_enabled` = false → stops only generation (scoring continues)
- `scrape_enabled` = false → stops even scraping

**What you see:**
- Dashboard shows red warning banner: "PIPELINE PAUSED"
- All scheduled tasks skip execution (logged in Activity Feed)
- System remains healthy — just not producing new content

**Recovery:**
- Toggle switch back ON
- Pipeline resumes on next scheduled cycle
- No data lost, no state corrupted

**Decision points:**
- Pause everything or just generation?
- How long to pause? (No automatic resume — you must manually re-enable)
- Do you need to freeze specific avatars too?

---

## Scenario 9: Client Deactivation

**Who triggers:** You (when a client churns or pauses their subscription)

**Steps:**

1. Go to `/admin/clients/{id}`
2. Set `is_active = false`
3. Cascade effect (automatic):
   - All client's subreddit assignments → deactivated
   - All client's avatar assignments → unassigned
   - All pending drafts → remain (but no new ones generated)
   - Pipeline skips this client entirely on next run

**What you see:**
- Client row in list: strikethrough name + "inactive" badge + dimmed
- Subreddits page: ⏸ icon + opacity for this client's assignments
- Red warning banner on client detail: "Pipeline skips all scraping, scoring, and generation"

**Reactivation:**
- Same page → "Activate" button
- All assignments restored
- Pipeline includes client on next run
- Audit log records both deactivation and reactivation

**Decision points:**
- Temporary pause or permanent removal?
- Should avatars be reassigned to another client?
- Are there approved but unposted drafts? (Owner can still post them)

---

## Scenario 10: Self-Learning in Action

**Who triggers:** System (automatically after human edits)

**What happens behind the scenes:**

1. You edit a draft before approving (Scenario 3)
2. System stores: original AI text + your edited version + context (subreddit, approach, avatar)
3. After every 5 new edits per avatar, system recomputes correction patterns
4. Patterns are categorized into 6 types:
   - Length adjustment ("shorten to 200 chars")
   - Tone shift ("less formal, more casual")
   - Structure change ("add specific example")
   - Vocabulary ("avoid guru-speak")
   - Content ("always mention personal experience")
   - Format ("no bullet points in Reddit comments")
5. Max 3 active patterns per avatar (most frequent win)
6. Next generation: system injects these patterns + 2-3 relevant few-shot examples into the prompt

**What you see:**
- Avatar detail → "Learned Patterns" panel shows active patterns
- Avatar detail → "What Works / What Fails" shows approach performance
- Debug view on drafts shows which patterns were injected

**Expected improvement:**
- Month 1: ~60% of drafts need editing
- Month 3: ~30% need editing
- Month 6: ~15% need editing (system has learned your style)

**Decision points:** None — this is fully automatic. But you can:
- View patterns to understand what the system learned
- If a pattern is wrong, edit more drafts to override it
- Patterns auto-expire after 180 days if not reinforced

---

## Scenario 11: Evergreen Content Harvest

**Who triggers:** System (weekly, Sunday 03:00 Israel time)

**What happens:**

1. System scrapes `top/year` posts from all active subreddits
2. Filters: only posts with 50+ upvotes (proven engagement magnets)
3. Deduplicates against existing threads in database
4. Saves new threads with type = "repurpose"
5. These threads flow through the normal pipeline: scoring → generation → review

**Why this matters:**
- Evergreen threads are lower risk (community already validated the topic)
- Provides steady content flow even when fresh threads are scarce
- High-upvote threads attract more readers → more visibility for comments

**What you see:**
- Threads in review queue marked as "repurpose" type
- These are older threads but still active (Reddit threads stay open for 6 months)

**Decision points:**
- Min score threshold (default: 50 upvotes, configurable in settings)
- How many per subreddit per week (default: 25)

---

## Scenario 12: Multi-Client Data Isolation

**Who triggers:** Automatic (RBAC system enforces at all times)

**What the system guarantees:**

1. **Client A never sees Client B's data** — queries are scoped by client_id at the database level
2. **Avatars can serve multiple clients** — but each client only sees "their" avatars
3. **LLM context isolation** — when generating a comment for Client A, the AI never receives Client B's keywords, strategy, or brand info
4. **Farm avatars** — shared inventory avatars can be rented to clients temporarily
5. **Audit trail** — every action logged with user identity and client context

**Roles:**
| Role | What they can do |
|------|-----------------|
| Owner (you) | Everything. Full platform access. |
| Partner | Same as owner (Tzvi's role) |
| Client Admin | Manage their own client: avatars, subreddits, review drafts |
| Client Manager | Review and approve drafts for their client |
| Client Viewer | Read-only access to their client's data |
| B2C User | Single avatar, limited features |

**What you see:**
- When logged in as Owner: you see all clients, all avatars, all data
- When a client_manager logs in: they only see their client's hub

---

## Scenario 13: Cost Monitoring

**Who triggers:** You (checking operational costs)

**Where to look:**
- `/admin/dashboard` → AI Costs panel (daily/weekly/monthly breakdown)
- Costs broken down by: client, operation type (scoring/generation/editing), model used

**Current cost structure (per client per month):**
| Operation | Model | Cost |
|-----------|-------|------|
| Scoring | Gemini Flash | $0.18 |
| Persona selection | Claude Sonnet | $9.00 |
| Comment generation | Claude Sonnet | $17.00 |
| Comment editing | Claude Sonnet | $8.00 |
| Hobby comments | Gemini Flash | $0.14 |
| **Total per client** | | **~$35/mo** |

**Revenue per client:** $399–$1,499/mo → **Margin: 90%+**

**What can spike costs:**
- Too many subreddits per client → more scoring calls
- High engage rate → more generation calls
- Many edits → more editing calls (but this improves over time via learning)

**Decision points:**
- If a client's costs exceed their plan value → discuss upsell or reduce scope
- If total LLM costs spike → check if a model was misconfigured (happened once — scoring ran on Sonnet instead of Flash, wasted $6.50)

---

## Scenario 14: First Pilot Run (XM Cyber)

**Who triggers:** You + Max together

**Steps:**

1. Verify XM Cyber data in system:
   - 7 avatars configured with correct usernames
   - 33 subreddits assigned (professional + hobby)
   - 100+ keywords in high/medium/low priority
   - Voice profiles reviewed and approved
2. Enable pipeline for XM Cyber client
3. Wait for next scheduled run (08:00 or 14:00)
4. Review generated drafts in queue
5. Approve 3-5 drafts as a test
6. Avatar owners post via Telegram
7. Monitor: check Reddit in 4h/24h — are comments still up? Getting upvotes?

**Success criteria:**
- Comments stay up (not removed by mods)
- Comments get 1+ upvotes within 24h
- No shadowban triggered
- Voice sounds natural (not AI-generated)
- Brand mentions only in Phase 3 avatars

**What can go wrong:**
- Comments removed by subreddit mods → need subreddit rule compliance (Sprint 2 feature)
- Comments sound robotic → edit voice profile, system learns from your edits
- Avatar gets shadowbanned → freeze, investigate, replace

---

## Summary: Your Daily Workflow

| Time | What you do | Where |
|------|-------------|-------|
| Morning (09:00) | Check dashboard — any alerts? Frozen avatars? | `/admin/dashboard` |
| Morning (09:30) | Review queue — approve/edit/reject drafts | `/admin/review` |
| Midday (13:00) | Quick check — any new drafts from morning pipeline? | `/admin/review` |
| Afternoon (15:00) | Review afternoon batch | `/admin/review` |
| Weekly (Sunday) | Check costs, avatar health, client performance | `/admin/dashboard` |
| As needed | Onboard new client, add avatar, handle emergency | Various |

**Time commitment:** 30-60 minutes/day for 10 clients. Scales sub-linearly — 50 clients won't take 5x longer because the system learns and improves.

---

## Questions for You (Tzvi)

1. **Pipeline triggers:** Should clients be able to trigger their own pipeline runs, or is this admin-only?
2. **Review delegation:** Will you review all drafts yourself, or will client_managers review their own?
3. **Avatar owner management:** How many owners do you plan to hire initially? Payment model?
4. **Posting speed SLA:** What's acceptable time from approval to posted? (Current reminder: 4 hours)
5. **Emergency protocol:** If multiple avatars get banned — do we pause all clients or just the affected one?
6. **Evergreen content:** Should repurpose threads be mixed with fresh threads in review, or separated?
7. **Client visibility:** Should clients see their own costs breakdown, or only results?

---

*Ready to walk through any of these scenarios live on a call. Let me know which ones need more detail.*

— Max
