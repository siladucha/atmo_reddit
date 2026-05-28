# User Manual — Client Manager

> **Audience:** Client team members responsible for daily content review  
> **Last updated:** 2026-05-28

---

## Your Role

As **Client Manager**, you're the daily operator. Your main job is reviewing AI-generated content, approving what's good, editing what needs work, and rejecting what doesn't fit. You also manage subreddits and keywords.

---

## What You Can Do

| Area | Access |
|------|--------|
| View your company's dashboard | ✅ |
| Approve/reject/edit drafts | ✅ |
| Add/assign subreddits | ✅ |
| Manage keywords | ✅ |
| View avatars (read-only) | ✅ |
| View activity events | ✅ |
| Create/delete avatars | ❌ |
| Manage team members | ❌ |
| Delete subreddits | ❌ |
| System settings | ❌ |

---

## Daily Workflow

### Morning Review (15-20 min)

1. **Login** → go to Review Queue
2. **Review pending drafts** — the system generates new drafts overnight and at 14:00
3. For each draft:
   - Read the target thread (click link to see context on Reddit)
   - Read the generated comment
   - Decide: Approve / Edit / Reject

### Review Decisions

| Decision | When to Use | What Happens |
|----------|-------------|--------------|
| ✅ **Approve** | Comment is good as-is | Goes to posting queue |
| ✏️ **Edit** | Good idea, needs tweaking | You fix it, then approve |
| ❌ **Reject** | Wrong tone, irrelevant, or low quality | Discarded, system learns |

### What Makes a Good Comment?

✅ **Approve if:**
- Sounds natural (like a real person wrote it)
- Actually answers the thread's question or adds value
- Matches the avatar's personality
- Appropriate length (usually 2-5 sentences)
- No brand mention in Phase 1/2 avatars

❌ **Reject if:**
- Sounds robotic or generic
- Doesn't address the thread topic
- Too promotional or salesy
- Contains factual errors
- Thread is clearly dead or irrelevant

✏️ **Edit if:**
- Good direction but too long/short
- Slightly off-tone (fix a word or two)
- Missing a key point that would make it better
- Has a minor factual issue you can fix

---

## The Review Queue

### Layout

Each draft card shows:
- **Avatar** — which persona is "speaking"
- **Subreddit** — where this would be posted
- **Thread title** — what the conversation is about
- **Thread score** — how popular the thread is (↑ upvotes)
- **Comment text** — the AI-generated response
- **Approach** — the rhetorical technique used (e.g., "reframe_drop", "contrarian")

### Filters

- By avatar
- By subreddit
- By status (pending / approved / rejected)
- By date

### Bulk Actions

- Review one at a time (recommended for quality)
- Use keyboard shortcuts if available (check UI)

---

## Editing Tips

When you edit a draft, the system captures your changes and learns from them. This means:

1. **Be consistent** — if you always shorten comments, the AI will learn to write shorter
2. **Fix patterns, not just instances** — if the tone is wrong, the system will adjust for future drafts
3. **Don't rewrite completely** — if you need to rewrite from scratch, it's better to reject and let the AI try again

### Common Edits
- Shortening (Reddit prefers concise)
- Adding a personal anecdote marker ("In my experience...")
- Removing overly formal language
- Adding a question at the end (drives engagement)
- Fixing technical accuracy

---

## Subreddit Management

### Adding a Subreddit

1. Go to subreddits section
2. Click **"+ Add"**
3. Enter the subreddit name (e.g., `cybersecurity`, not `r/cybersecurity`)
4. Choose type: Target (professional) or Hobby (warming)
5. Assign to avatars

### What to Look For in Subreddits

Good target subreddits:
- Active community (posts daily)
- Your audience participates there
- Questions get asked that your brand can answer
- Moderate moderation (not too strict, not too loose)

Avoid:
- Dead subreddits (< 1 post/day)
- Heavily moderated (comments removed frequently)
- Off-topic for your brand
- Subreddits that ban commercial accounts aggressively

---

## Keywords

Keywords tell the scoring AI what's relevant to your company.

### Priority Levels

| Level | What Goes Here | Example (Cybersecurity) |
|-------|---------------|------------------------|
| **High** | Direct product/problem terms | "lateral movement detection", "attack surface" |
| **Medium** | Related industry terms | "SOC team", "SIEM alternatives", "zero trust" |
| **Low** | Broad topic terms | "cybersecurity career", "infosec", "pentesting" |

### Tips
- High-priority keywords trigger more aggressive scoring (more drafts generated)
- Too many high-priority keywords = too many drafts to review
- Start with 5-10 high, 10-15 medium, 15-20 low
- Adjust based on what you're seeing in the review queue

---

## Understanding What You See

### Avatar Phases (Why Some Avatars Only Do Hobby)

| Phase | What It Means for You |
|-------|----------------------|
| Phase 1 | Avatar only posts in hobby subs. You'll see hobby drafts only. Normal — building credibility. |
| Phase 2 | Avatar posts in professional subs. No brand mentions yet. You'll see industry-relevant drafts. |
| Phase 3 | Full capability. Brand mentions allowed when appropriate. |

You can't change phases — they're managed by the system based on karma and time.

### Draft Statuses

```
pending → (you review) → approved → posted
                       → rejected (discarded)
```

### Activity Feed

Shows what happened and when. Useful for:
- Checking if today's pipeline ran
- Seeing which drafts were posted
- Tracking avatar activity

---

## FAQ

**Q: How many drafts should I expect per day?**  
A: Depends on your configuration. Typically 10-20 drafts per day across all avatars. More subreddits + more keywords = more drafts.

**Q: What if I don't review drafts for a few days?**  
A: They stay in the queue. Old drafts for locked/removed threads are auto-rejected by the system. Review at least daily for best results.

**Q: Can I see what was posted on Reddit?**  
A: Yes — approved and posted drafts show the Reddit thread link. You can click through to see the live comment.

**Q: Why was a draft auto-rejected?**  
A: The system auto-rejects drafts when the target thread gets locked, removed, or archived. This is a safety feature.

**Q: How do I improve the AI output quality?**  
A: Edit consistently. The system learns from your edits. After 5-10 edits with a consistent pattern, you'll see improvement in future drafts.

**Q: Can I add a new avatar?**  
A: No — that requires Client Admin access. Ask your company's admin or your RAMP account manager.
