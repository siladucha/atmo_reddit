# Guide — Onboarding a New Client

> **Audience:** Owner, Partner  
> **Last updated:** 2026-05-28

---

## Prerequisites

Before starting:
- [ ] Client has signed contract
- [ ] Payment received (setup fee)
- [ ] You know: company name, brand, industry, target audience
- [ ] You have: 3-5 target subreddits identified
- [ ] You have: 10-20 keywords (high/medium/low)
- [ ] Avatar(s) available (farm or new)

---

## Step-by-Step: 7-Step Wizard

### Step 1: Company Profile

Navigate to `/admin/clients` → **"+ New Client"**

Fill in:
| Field | What to Enter |
|-------|--------------|
| Company Name | Official name |
| Brand Name | How they're known on Reddit |
| Industry | Primary industry vertical |
| Website | Company URL |
| Plan Type | seed / starter / growth / scale |
| Max Avatars | Based on plan (1 / 3 / 7 / 15) |

### Step 2: Subreddits

Add subreddits where the client's audience lives:

- **Target subreddits** (3-10): Professional communities relevant to the brand
- **Hobby subreddits** (2-5): For avatar warming (Phase 1)

Tips:
- Check subreddit activity (should have daily posts)
- Check moderation strictness (avoid heavily moderated subs for new avatars)
- Look at where competitors' audience hangs out

### Step 3: Keywords

Configure keyword priorities:

```json
{
  "high": ["exact product terms", "direct problem terms"],
  "medium": ["industry terms", "related technologies"],
  "low": ["broad topic terms", "career/community terms"]
}
```

Start conservative:
- 5-8 high priority
- 8-12 medium priority
- 10-15 low priority

You can always add more after seeing initial scoring results.

### Step 4: Avatars

Assign avatars to this client:

**Option A: From Farm (pre-warmed)**
- Select available farm avatars matching the client's niche
- Create rental record
- Avatar immediately available for Phase 2+ work

**Option B: New Avatar**
- Create fresh Reddit account (separate process)
- Configure in platform
- Starts at Phase 1 (2 months of warming before brand work)

**Option C: Client's Existing Accounts**
- Import credentials
- Assess current karma/history
- Assign appropriate phase

### Step 5: Personas (Voice Profiles)

For each assigned avatar, configure:
- Voice profile (personality, background, expertise)
- Tone principles
- Speech patterns
- Constraints

See [Avatar Management Guide](./avatar-management.md) for detailed voice profile instructions.

### Step 6: Pipeline Config

Set operational parameters:
| Setting | Recommended Default |
|---------|-------------------|
| Scoring threshold | 0.6 (engage if score > 0.6) |
| Max drafts per day | 5-8 per avatar |
| Scrape interval | 6 hours |
| Generation model | Claude Sonnet (default) |

### Step 7: Test Run (Dry Run)

1. Click **"Run Test"** — triggers pipeline without posting
2. Wait 2-3 minutes
3. Check results:
   - Were relevant threads found? (scoring working)
   - Are generated comments on-brand? (voice profile working)
   - Is the tone right? (persona configured correctly)
4. Adjust keywords/voice profile if needed
5. Run again until satisfied

---

## Post-Wizard Setup

### Create Client Users

1. Create `client_admin` account for client's main contact
2. Optionally create `client_manager` / `client_viewer` accounts
3. Send credentials

### Strategy Document

Write initial strategy document for each avatar:
- Engagement goals (what we're trying to achieve)
- Brand positioning (how to mention the brand)
- Competitive landscape (what NOT to say)
- Content themes (recurring topics to address)

### First Pipeline Run

1. Activate client (`is_active = true`)
2. Pipeline will run on next scheduled cycle (08:00 or 14:00)
3. Or trigger manually: Dashboard → "Run Pipeline"
4. Review first batch of drafts carefully
5. Adjust voice profiles based on initial output quality

---

## Onboarding Checklist

```
□ Client created in system
□ Subreddits configured (target + hobby)
□ Keywords set (high/medium/low)
□ Avatar(s) assigned
□ Voice profiles complete (all fields filled)
□ Strategy document written
□ Test run successful
□ Client user accounts created
□ Client activated
□ First real pipeline run reviewed
□ Client briefed on review process (if they review)
```

---

## Timeline

| Day | Activity |
|-----|----------|
| Day 1 | Wizard setup, voice profiles, test run |
| Day 2 | Strategy document, first real pipeline run |
| Day 3-5 | Review first drafts, adjust voice profiles |
| Week 2 | Stable operation, hand off review to client (if applicable) |
| Month 1 | Phase 1 avatars warming, hobby content only |
| Month 3 | Phase 2 avatars start professional engagement |
| Month 5 | Phase 3 avatars can mention brand |

---

## Common Issues During Onboarding

| Issue | Solution |
|-------|----------|
| No threads scored "engage" | Keywords too narrow → add more medium/low terms |
| Comments sound generic | Voice profile too short → add more detail, examples |
| Wrong subreddits suggested | Research client's audience better, ask client directly |
| Avatar has no karma | Normal for new avatars — Phase 1 warming takes time |
| Client wants immediate brand mentions | Explain warming phases — rushing = account bans |
