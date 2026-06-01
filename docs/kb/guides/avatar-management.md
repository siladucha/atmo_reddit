# Guide — Avatar Management

> **Audience:** Owner, Partner, Avatar Manager  
> **Last updated:** 2026-05-29

---

## Avatar Lifecycle

```
Create → Configure → Warm (Phase 1) → Seed (Phase 2) → Brand (Phase 3) → Expert
                                                                              │
                                                              ┌───────────────┘
                                                              ▼
                                                    Retire / Replace
```

---

## Creating a New Avatar

### 1. Create Reddit Account (Outside Platform)

1. Use a unique email (not linked to other avatars)
2. Choose a username that fits the persona (e.g., `DevOpsDaily_Mike`, `YogaWithSarah`)
3. Complete Reddit onboarding (join a few subreddits, set avatar image)
4. Make 2-3 manual comments to establish the account

### 2. Register in Platform

Go to `/admin/avatars` → **"+ New Avatar"**

| Field | Description |
|-------|-------------|
| Reddit Username | Exact match to Reddit account |
| Email | Email linked to the Reddit account |
| Display Name | Internal name for the team |
| Hobby Subreddits | Comma-separated list for Phase 1 warming |
| Client Assignment | Which client this avatar serves (or "Farm" for unassigned) |

### 3. Configure Voice Profile

This is the most important step. A detailed voice profile = good AI output.

#### Required Fields

| Field | Length | Purpose |
|-------|--------|---------|
| **Voice Profile** | 2000-5000 chars | Full personality description |
| **Tone Principles** | 200-500 chars | Communication style rules |
| **Speech Patterns** | 200-500 chars | Characteristic phrases and structure |
| **Hill I Die On** | 100-300 chars | Strong opinions (makes avatar feel real) |
| **Helpful Mode Topics** | 100-300 chars | Where they naturally help others |
| **Constraints** | 100-300 chars | Things they NEVER do |
| **Vocabulary Lean** | 100-200 chars | Jargon level and preferred words |

#### Voice Profile Template

```
Background: [Job title], [years of experience], [company type/size]
Expertise: [Primary skill], [secondary skills]
Personality: [2-3 adjectives describing communication style]
Reddit behavior: [How they typically engage — long posts? short quips? questions?]
Unique angle: [What makes their perspective different from generic advice]
Personal details: [Hobbies, location hints, life situation — makes them feel real]
```

#### Example (Cybersecurity Avatar)

```
Voice Profile:
Senior SOC analyst, 8 years in enterprise security. Started in helpdesk,
worked up through incident response. Currently at a mid-size fintech (won't
name it). Burned out on vendor hype — prefers open-source tools when possible
but pragmatic about enterprise needs. Has strong opinions about SIEM pricing
and alert fatigue. Mentors junior analysts on the side.

Tone Principles:
Direct and slightly cynical about vendor marketing. Warm toward junior
professionals asking genuine questions. Uses humor (dry, not mean). Never
condescending. Admits when they don't know something.

Speech Patterns:
Starts responses with "Honestly," or "Look," when giving strong opinions.
Uses "FWIW" and "YMMV" frequently. Writes in short paragraphs. Often ends
with a practical tip or resource link.

Hill I Die On:
"Most SIEM vendors are selling you a dashboard, not security. If your team
can't write detection rules, no tool will save you."

Helpful Mode Topics:
Alert triage workflows, SIEM comparison (Elastic vs Splunk vs Wazuh),
SOC team scaling, incident response playbooks, career advice for junior analysts.

Constraints:
Never recommends specific vendors unprompted. Never claims expertise in
offensive security (stays in blue team lane). Never dismissive of beginners.

Vocabulary Lean:
Heavy technical jargon when talking to peers. Simplifies for beginners.
Uses acronyms freely (IOC, TTPs, MITRE ATT&CK) without explaining them
in professional subs. Avoids marketing buzzwords.
```

---

## Avatar Warming (Phase 1)

### Goal
Build 100+ karma through genuine hobby participation. Make the account look like a real, active Reddit user.

### Strategy
- Post in hobby subreddits only (no professional content)
- 3-5 comments per day
- Focus on helpful, genuine responses
- Build comment karma (not post karma)
- Participate in discussions (reply to replies)

### What Works in Phase 1
- Answering questions with personal experience
- Sharing tips and recommendations
- Asking follow-up questions (shows genuine interest)
- Disagreeing respectfully (shows personality)

### What to Avoid
- Generic one-liner responses
- Posting too frequently (looks automated)
- Only posting in one subreddit (looks suspicious)
- Any mention of brands or products (even casually)

### Phase 1 → Phase 2 Promotion Criteria
- Minimum karma threshold met
- Account age > 60 days
- Consistent posting history (not all in one day)
- No health issues (no shadowban, CQS not lowest)
- System evaluates daily at 06:00

---

## Avatar Health Monitoring

### Health States

| State | Meaning | Action |
|-------|---------|--------|
| `active` | Everything normal | Continue operations |
| `limited` | Minor restrictions detected | Monitor closely, reduce posting frequency |
| `shadowbanned` | Posts invisible to others | **Freeze immediately**, likely unrecoverable |
| `suspended` | Account banned by Reddit | **Freeze immediately**, account is dead |
| `unknown` | Can't determine status | Check manually, may be temporary |

### Automated Health Checks

The system runs health checks at 07:30 and 13:30 daily:
1. Checks if avatar's posts are visible (shadowban detection)
2. Checks account status (suspension detection)
3. Checks CQS level (quality score)
4. Auto-freezes on: shadowban, suspension, CQS "lowest"

### Manual Health Check

Avatar detail → Performance tab → **"Refresh from Reddit"**
- Fetches latest karma, CQS, account status
- Updates health state immediately

### CQS (Contributor Quality Score)

| Level | Meaning | System Action |
|-------|---------|---------------|
| highest | Excellent contributor | — |
| high | Good contributor | — |
| moderate | Average | — |
| low | Below average | Warning (monitor) |
| lowest | Poor quality | **Auto-freeze** (Phase 2+ only) |

Phase 1 avatars are NOT auto-frozen on low CQS (they're still warming up).

---

## Freezing & Unfreezing

### When to Freeze

- Shadowban detected
- Suspicious activity on the account
- Client requests pause
- Avatar posting in wrong subreddits
- Removal rate > 30%

### How to Freeze

1. Avatar detail → click **"Freeze"**
2. Enter reason (required — logged in audit)
3. Avatar immediately excluded from ALL pipelines

### How to Unfreeze

1. Verify the issue is resolved
2. Avatar detail → click **"Unfreeze"**
3. Avatar returns to pipeline on next scheduled run

### What Freeze Does

- Excluded from scoring pipeline
- Excluded from generation pipeline
- Excluded from hobby pipeline
- Excluded from health checks (already known issue)
- EPG not generated
- Existing pending drafts remain (not auto-rejected)

---

## Phase Management

### Phase Override (Admin Only)

In special cases, you can manually set an avatar's phase:
- Avatar detail → Phase section → **"Override Phase"**
- Select target phase (0-3)
- Enter reason

Use cases:
- Setting Phase 0 (Mentor) for high-karma acquired accounts
- Promoting early if avatar has exceptional karma growth
- Demoting if avatar was promoted too early

### Phase Evaluation (Automated)

Runs daily at 06:00:
- Checks karma thresholds
- Checks account age
- Checks posting consistency
- Promotes or demotes as appropriate
- Phase 0 (Mentor) avatars are never evaluated

---

## Avatar Intelligence (Dashboard)

### Confidence Score (0-100)

Computed from:
- Subreddit presence diversity
- Draft removal rate (lower = better)
- Posting consistency
- Karma growth rate

### Removal Rate Analytics

- Per-subreddit breakdown
- Color coded: ≤10% green, ≤20% amber, >20% red
- High removal rate = voice profile needs adjustment OR subreddit too strict

### Pattern Performance (What Works / What Fails)

- Groups posted drafts by comment approach
- Shows which approaches get upvotes vs removals
- Use this to adjust strategy

### Learned Patterns

- Active correction patterns extracted from human edits
- Shows what the AI has "learned" for this avatar
- Review periodically — remove outdated patterns if needed

---

## Best Practices

### Voice Profile Maintenance

- Review every 2-4 weeks
- Update if removal rate increases
- Add new speech patterns observed in successful comments
- Remove constraints that are too restrictive

### Subreddit Rotation

- Don't post in the same subreddit every day
- Rotate across 3-5 subreddits per avatar
- Match posting frequency to subreddit activity level
- Drop subreddits with consistently high removal rates

### Karma Growth Targets

| Phase | Weekly Karma Target | Monthly Target |
|-------|-------------------|----------------|
| Phase 1 | 15-30 | 60-120 |
| Phase 2 | 20-50 | 80-200 |
| Phase 3 | 30-100 | 120-400 |

### Red Flags

- Karma not growing for 2+ weeks → check if comments are being removed
- Sudden karma drop → possible mass-downvote or mod action
- CQS dropping → reduce posting frequency, improve quality
- Multiple avatars frozen simultaneously → systemic issue, check IP/proxy

---

## Checking Posted Comments (Daily Verification)

### Where to Find Posted Comment Links

1. **Admin → Review page** — filter by status "posted", shows `reddit_comment_url` for each
2. **Avatar detail → Performance tab** — removal rate analytics with per-subreddit breakdown
3. **Database directly** — `comment_drafts` table, `status = 'posted'`, `reddit_comment_url` column

### Daily Posting Verification Checklist

```
□ Open Activity Feed — look for "Karma tracking complete" event
□ Check: any new deletions detected? (count in event metadata)
□ Open Avatar detail → Performance → Removal Rate
□ Spot-check 2-3 posted URLs manually (open in incognito, verify visible)
□ If removal rate > 20% for any subreddit → investigate (voice mismatch? rule violation?)
```

### What the System Tracks Automatically

| Metric | How | When |
|--------|-----|------|
| Karma score per comment | Fetches from Reddit API | Every 4h |
| Comment removal | Checks body for `[removed]`/`[deleted]` | Every 4h |
| Comment disappearance | Not found in avatar's last 100 comments | Every 4h |
| Per-subreddit karma totals | Aggregated from individual comments | Every 4h |

### What Requires Manual Verification

| Check | Why Manual | How Often |
|-------|-----------|-----------|
| Comment actually visible to others | Shadowban may hide it | Weekly (incognito spot-check) |
| Comment not auto-collapsed | Low karma or new account | Weekly |
| Thread still active | Thread may be archived | Before posting |
| Subreddit rules compliance | Rules change, AI may miss nuances | When removal detected |

### Interpreting Karma Scores

| Score | Meaning | Action |
|-------|---------|--------|
| 1 | Default (no votes) | Normal for niche subs |
| 2-5 | Mild positive reception | Good — avatar fits the community |
| 5+ | Strong engagement | Excellent — note what worked |
| 0 | Neutral or 1 up + 1 down | Monitor — may indicate borderline content |
| Negative | Downvoted | Investigate — voice mismatch or off-topic |

> **Note:** In niche subreddits (< 50K members), scores of 1-2 are completely normal. High scores (10+) are rare and indicate exceptional content fit.
