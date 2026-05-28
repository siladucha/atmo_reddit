# User Manual — Client Admin

> **Audience:** Client company administrators  
> **Last updated:** 2026-05-28

---

## Your Role

As **Client Admin**, you manage your company's Reddit marketing operation within RAMP. You can configure avatars, manage your team, review content, and monitor performance — all scoped to your company's data only.

---

## What You Can Do

| Area | Access |
|------|--------|
| View your company's data | ✅ |
| Manage avatars (create, configure, freeze) | ✅ (up to max_avatars limit) |
| Approve/reject/edit drafts | ✅ |
| Manage subreddits (add, assign, remove) | ✅ |
| Manage keywords | ✅ |
| Create team members (manager, viewer) | ✅ |
| Edit/deactivate team members | ✅ |
| Trigger pipeline for your company | ✅ |
| View activity events | ✅ |
| View rented avatars | ✅ (active rentals only) |
| System settings | ❌ |
| Other companies' data | ❌ |
| AI cost analytics | ❌ |
| Audit logs (platform-wide) | ❌ |

---

## Getting Started

### First Login

1. You'll receive login credentials from your RAMP account manager
2. Go to the platform URL → Login
3. You'll see your company's dashboard with:
   - Active avatars and their status
   - Recent activity (drafts generated, posted)
   - Review queue (pending approvals)

### Your Dashboard

The dashboard shows:
- **Avatars** — health status, phase, karma growth
- **Pipeline activity** — what's been scraped, scored, generated today
- **Review queue** — pending drafts awaiting your decision
- **Performance** — posted comments, engagement metrics

---

## Team Management

### Adding Team Members

1. Navigate to team/users section
2. Click **"+ Add Team Member"**
3. Choose role:
   - **Client Manager** — can review/approve drafts, manage subreddits and keywords
   - **Client Viewer** — read-only access to dashboard and reports
4. Enter email and name → send invite

### Role Differences

| Action | Client Admin (you) | Client Manager | Client Viewer |
|--------|-------------------|----------------|---------------|
| Approve/reject drafts | ✅ | ✅ | Only if enabled* |
| Add/remove subreddits | ✅ | ✅ | ❌ |
| Manage keywords | ✅ | ✅ | ❌ |
| Create avatars | ✅ | ❌ | ❌ |
| Delete avatars | ✅ | ❌ | ❌ |
| Manage team | ✅ | ❌ | ❌ |
| View dashboard | ✅ | ✅ | ✅ |

*Client Viewer can approve drafts only if `draft_approval_enabled` is turned on for your account.

---

## Avatar Management

### Viewing Your Avatars

Your avatar list shows:
- **Name** — Reddit username
- **Phase** — current warming stage (1-3 or Expert)
- **Health** — active / limited / shadowbanned / suspended
- **Karma** — current Reddit karma
- **Subreddits** — where this avatar participates

### Configuring an Avatar

1. Click on an avatar → opens detail view
2. Key tabs:
   - **Overview** — status, confidence score, learned patterns
   - **Profile & Safety** — voice profile, tone, constraints
   - **Performance** — removal rate, what works/fails
   - **Presence** — subreddit activity map
   - **Workflow** — today's EPG, pending drafts

### Voice Profile (Critical)

The voice profile determines how AI writes as this avatar. Fill in ALL fields:

| Field | What It Does | Example |
|-------|-------------|---------|
| Voice Profile | Full personality (2000-5000 chars) | "Senior DevOps engineer, 12 years experience..." |
| Tone Principles | How they communicate | "Direct, slightly sarcastic, data-driven" |
| Speech Patterns | Characteristic phrases | "Starts with 'Look,...', uses 'IMHO'" |
| Hill I Die On | Strong opinions | "Kubernetes is overkill for 90% of startups" |
| Helpful Mode Topics | Where they naturally help | "CI/CD pipelines, Docker, monitoring" |
| Constraints | What they NEVER do | "Never recommends specific vendors unprompted" |
| Vocabulary Lean | Jargon level | "Heavy technical jargon, no marketing speak" |

⚠️ **Incomplete profiles produce poor AI output.** The more detail you provide, the better the generated comments.

---

## Content Review

### Review Queue

1. Navigate to Review Queue
2. Each pending draft shows:
   - Avatar name
   - Target subreddit and thread
   - Generated comment text
   - Comment approach used
3. Actions:
   - ✅ **Approve** — ready for posting
   - ✏️ **Edit** — modify text, then approve
   - ❌ **Reject** — discard (with optional reason)

### Review Best Practices

- **Check tone** — does it sound like the avatar's personality?
- **Check relevance** — is the comment actually helpful to the thread?
- **Check brand mentions** — appropriate for the avatar's phase?
- **Check length** — Reddit users prefer concise, valuable comments
- **Edit freely** — the system learns from your edits and improves over time

---

## Subreddit Management

### Adding Subreddits

1. Go to subreddits section
2. Click **"+ Add Subreddit"**
3. Enter subreddit name (without r/)
4. Assign type:
   - **Target** — professional subreddits relevant to your brand
   - **Hobby** — for avatar warming (Phase 1 karma building)
5. Assign to specific avatars

### Monitoring Subreddits

- **Last scraped** — when data was last collected
- **Thread count** — how many threads are tracked
- **Engage rate** — % of threads that score high enough for engagement

---

## Keywords

Keywords determine which threads are relevant to your company.

### Structure
```
High priority:   Terms directly about your product/problem space
Medium priority: Related industry terms
Low priority:    Broad topic terms
```

### Managing Keywords
1. Go to keywords section
2. Add/remove terms in each priority tier
3. Changes take effect on next scoring run

---

## Pipeline Trigger

You can manually trigger the pipeline for your company:
1. Dashboard → **"Run Pipeline"** button
2. This will: scrape your subreddits → score new threads → generate drafts
3. New drafts appear in Review Queue within 5-10 minutes

Use this when:
- You just added new subreddits or keywords
- You want fresh content before a review session
- Testing after configuration changes

---

## Understanding the Activity Feed

The activity feed shows everything that happened:

| Event | Meaning |
|-------|---------|
| `scrape_completed` | Subreddit data refreshed |
| `threads_scored` | New threads evaluated |
| `draft_generated` | AI wrote a comment |
| `draft_approved` | You/team approved a draft |
| `draft_rejected` | You/team rejected a draft |
| `draft_posted` | Comment posted on Reddit |
| `avatar_frozen` | Avatar excluded from pipeline (issue detected) |

---

## FAQ

**Q: Why are some avatars showing "Phase 1 — Hobby Only"?**  
A: New avatars must build karma in hobby subreddits before they can engage professionally. This takes 1-2 months. It's a safety measure to build credibility.

**Q: Can I see what other companies are doing?**  
A: No. All data is strictly isolated. You only see your company's avatars, drafts, and activity.

**Q: What happens if I reject a draft?**  
A: The system learns from rejections. Over time, it generates fewer comments of that type. Always reject low-quality drafts — it improves the AI.

**Q: How do I get more avatars?**  
A: Contact your RAMP account manager. Additional avatars may be available from the avatar farm (pre-warmed) or can be created fresh.

**Q: What's the "Confidence Score" on an avatar?**  
A: A 0-100 metric combining presence data, removal rate, and subreddit diversity. Higher = more reliable avatar.
