# Guide — Content Review & Self-Learning Loop

> **Audience:** Owner, Partner, Client Admin, Client Manager, Client Viewer (with approval enabled)  
> **Last updated:** 2026-06-20

---

## Overview

Every AI-generated comment draft goes through human review before posting. The review process is not just a quality gate — it's also how the system **learns your preferences**. Every approval, edit, and rejection teaches the AI to write better comments for your specific avatars.

---

## Where to Review

| Role | Location | URL |
|------|----------|-----|
| Owner / Partner | Avatar Detail → Content tab → Decision Queue | `/admin/avatars/{id}#tab=content` |
| Owner / Partner | Decision Center (all avatars) | `/admin/decision-center` |
| Client Admin / Manager | Client Portal → Review | `/clients/{id}/review` |

---

## The Three Actions

### ✓ Approve

**When:** The comment is good as-is (no edits needed).

**What happens:**
- Draft status → `approved`
- EPG slot synced → automated posting picks it up at scheduled time
- Learning Loop records "AI got it right" (`approved_unchanged`)

### ✗ Reject

**When:** The comment is off-topic, wrong tone, low quality, or irrelevant.

**What happens:**
- Draft status → `rejected`
- Draft discarded (will not be posted)
- Learning Loop records the rejection as a **negative example** — AI avoids this style in future

### ✎ Edit → Save & Approve

**When:** The comment is 70-90% good but needs tweaking.

**This is one action** — clicking "Save & Approve" does everything in one step:
1. Saves your edited text
2. Approves the draft (moves to posting queue)
3. Triggers the Learning Loop with the strongest signal (before/after pair)

**No separate Approve needed after editing.** Save & Approve = done.

---

## Recommended Workflow

```
1. Read the thread (click Reddit link to see context)
2. Read the AI-generated comment
3. Decide:

   Good as-is?   →  Click ✓ Approve
   Needs tweaks?  →  Click ✎ Edit → modify text → Save & Approve ✓
   Bad quality?   →  Click ✗ Reject
```

---

## How Learning Is Triggered

| Action | Learning Status | What the System Records |
|--------|----------------|------------------------|
| ✓ Approve (no edits) | `approved_unchanged` | "AI got it right" — reinforces current style |
| ✎ Edit → Save & Approve | `approved` | Before/after diff — **strongest learning signal** |
| ✗ Reject | `rejected` | Negative example — "avoid this style" |

---

## The Self-Learning Loop

### What Gets Captured

Every approval/rejection creates an `EditRecord` with:
- Original AI draft text (before)
- Your edited version (after, if any)
- Computed edit summary (e.g., "shortened 85→62 words; removed 'crucial'; added 'IMHO'")
- Context: subreddit, engagement mode, thread title
- Status: approved / approved_unchanged / rejected

### Pattern Extraction (Automatic)

After every **5 edit records** for an avatar-client pair, the system automatically:

1. Analyzes all accumulated diffs
2. Detects recurring patterns across 6 categories:

| Pattern Type | Example Rule Generated |
|-------------|----------------------|
| `length_adjustment` | "Keep responses concise, aim for under 60 words" |
| `tone_shift` | "Use a casual, conversational tone" |
| `vocabulary_change` | "Avoid using: crucial, delve" |
| `structure_change` | "Restructure responses for better flow and readability" |
| `content_removal` | "Remove unnecessary filler and redundant content" |
| `content_addition` | "Add more substantive content and supporting details" |

A pattern must appear in **2+ edit summaries** to be considered recurring (avoids noise from one-off edits).

### How Patterns Improve Future Comments

When generating a new comment, the AI prompt includes:
- **Up to 3 correction rules** (imperative instructions from detected patterns)
- **Up to 3 few-shot examples** (real before/after pairs from your edits)
  - Max 2 positive examples (approved edits)
  - Max 1 negative example (rejected draft)
  - Selected by relevance: same subreddit (+2), same engagement mode (+1)

### Timeline to See Improvement

| Milestone | What Happens |
|-----------|-------------|
| 1-4 edits | System accumulates data, no patterns yet |
| 5 edits | First pattern extraction attempt |
| 5+ matching edits | Patterns detected and injected into prompts |
| 10+ edits | Strong patterns, measurable quality improvement |
| 20+ edits | System closely matches your review style |

---

## Confidence Score & Bulk Approve

Each draft has a **confidence score** (0-100%) based on:

| Factor | Points |
|--------|--------|
| Base score | 70 |
| Learning patterns injected | +10 |
| Few-shot examples used | +5 |
| Text length in sweet spot (30-100 words) | +5 |
| Reliable approach (helpful_expert, personal_experience, curious_question) | +5 |
| Too short (<10 words) | -15 |
| Too long (>200 words) | -10 |

**Maximum without learning data: 80.** To reach 90+ (needed for Bulk Approve), you need active learning — at least 5 edited+approved drafts with detected patterns.

### Bulk Approve (≥90%)

The "Bulk Approve (≥90%)" button auto-approves all pending drafts with confidence ≥ 90%. Drafts with lower confidence or from high-risk avatars (frozen/shadowbanned) are skipped.

**How to enable Bulk Approve:**
1. Review 5-10 drafts manually (edit and approve with consistent corrections)
2. System extracts patterns → confidence rises from 70-80 to 85-95
3. Future drafts that match learned patterns get high confidence
4. Bulk Approve starts working automatically

---

## Best Practices for Maximizing Learning

### Be Consistent

If you prefer shorter comments — **always** shorten them. Inconsistent edits (sometimes shorter, sometimes longer) confuse the pattern detector.

### Edit, Don't Rewrite

Small targeted edits produce clearer learning signals than full rewrites:
- ✅ Good: Remove one sentence, change 2 words → clear signal
- ❌ Bad: Delete everything and write from scratch → AI can't learn what was wrong

### Reject Clearly Bad Drafts

Don't edit a terrible draft into something passable. Reject it. The rejection teaches the AI "this entire approach was wrong."

### Review Regularly

The system generates fresh drafts at 08:00 and 14:00 daily. Regular review (within 8 hours) keeps the learning loop active and the posting queue flowing.

### Focus on Patterns, Not Perfection

You don't need to catch every tiny issue. Focus on **recurring problems**:
- Avatar sounds too formal? Edit to casual 3-5 times → system learns
- Comments too long? Shorten them consistently → system adapts
- AI uses words you hate? Remove them every time → system avoids them

---

## Viewing Learned Patterns

### Admin Panel (Owner/Partner)

Avatar Detail → **Content tab** → **AI Insights & Health Scorecard** section:
- Shows detected correction patterns
- Shows number of edit records accumulated

### Decision Queue Cards

Each draft card has a **Logic Peek** (expandable):
- Shows if learning patterns were injected
- Shows the comment approach and engagement mode
- Confidence Score — partially based on how well the draft matches learned patterns

---

## Review Checklist

Before approving any draft:

```
□ Sounds like the avatar's personality (voice match)
□ Relevant to the thread topic
□ Adds value (would a real user appreciate this?)
□ Appropriate length (usually 2-5 sentences for Reddit)
□ No brand mention violations (check avatar phase)
□ No AI-tell phrases ("Delve", "Crucial", "It's important to note")
□ No factual errors
□ Would you upvote this if you saw it on Reddit?
```

---

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| Approve/Reject button does nothing | Session expired or permissions issue | Refresh page, re-login |
| Edit saves but no improvement in future drafts | Need 5+ edit records for patterns | Keep reviewing consistently |
| System keeps making same mistakes | Edits too varied for pattern detection | Be more consistent in corrections |
| Confidence score always low (<80) | No learning data accumulated | Edit+Approve 5-10 drafts to bootstrap |
| Bulk Approve skips everything | All drafts below 90% confidence | Normal before learning is active. Review manually first. |

---

## Related Guides

- [Daily Operations](./daily-operations.md) — full daily workflow including review timing
- [Pipeline Explained](./pipeline-explained.md) — how drafts get generated
- [Avatar Management](./avatar-management.md) — voice profiles that influence generation
- [Emergency Controls](./emergency-controls.md) — kill switches and avatar freeze
