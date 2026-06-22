"""Update client-manager.md and client-viewer.md with new review workflow docs."""

# === client-manager.md ===
path = '/Volumes/2SSD/Projects/ReddirSaaS/docs/kb/roles/client-manager.md'
with open(path, 'r') as f:
    content = f.read()

content = content.replace('> **Last updated:** 2026-05-28', '> **Last updated:** 2026-06-20')

# Replace the Review Decisions section
old_text = """### Review Decisions

| Decision | When to Use | What Happens |
|----------|-------------|--------------|
| ✅ **Approve** | Comment is good as-is | Goes to posting queue |
| ✏️ **Edit** | Good idea, needs tweaking | You fix it, then approve |
| ❌ **Reject** | Wrong tone, irrelevant, or low quality | Discarded, system learns |"""

new_text = """### Review Decisions

| Decision | When to Use | What Happens |
|----------|-------------|--------------|
| **✓ Approve** | Comment is good as-is | Goes to posting queue, AI reinforced |
| **✎ Edit → Save & Approve** | Good idea, needs tweaking | You fix it, one click saves + approves + teaches AI |
| **✗ Reject** | Wrong tone, irrelevant, or low quality | Discarded, AI learns to avoid this style |

> **Edit is one step:** Click ✎, modify text, click "Save & Approve ✓" — done. No separate approve needed."""

content = content.replace(old_text, new_text, 1)

# Replace the Editing Tips section
old_text = """## Editing Tips

When you edit a draft, the system captures your changes and learns from them. This means:

1. **Be consistent** — if you always shorten comments, the AI will learn to write shorter
2. **Fix patterns, not just instances** — if the tone is wrong, the system will adjust for future drafts
3. **Don't rewrite completely** — if you need to rewrite from scratch, it's better to reject and let the AI try again

### Common Edits
- Shortening (Reddit prefers concise)
- Adding a personal anecdote marker ("In my experience...")
- Removing overly formal language
- Adding a question at the end (drives engagement)
- Fixing technical accuracy"""

new_text = """## Editing & The Learning Loop

When you edit and approve a draft, the system captures your changes and learns from them automatically.

### How Learning Works

1. You edit + approve → system records before/after pair
2. After 5+ similar edits → system detects a pattern (e.g., "always shortens to under 60 words")
3. Pattern gets injected into future AI prompts → fewer edits needed over time

### Tips for Effective Learning

1. **Be consistent** — if you always shorten comments, the AI will learn to write shorter
2. **Fix patterns, not just instances** — if the tone is wrong, the system will adjust for future drafts
3. **Don't rewrite completely** — if you need to rewrite from scratch, it's better to reject and let the AI try again

### Common Edits
- Shortening (Reddit prefers concise)
- Adding a personal anecdote marker ("In my experience...")
- Removing overly formal language
- Adding a question at the end (drives engagement)
- Fixing technical accuracy

**Full guide:** [Content Review & Self-Learning Loop](../guides/content-review-and-learning.md)"""

content = content.replace(old_text, new_text, 1)

# Update the FAQ about improving AI quality
old_faq = """**Q: How do I improve the AI output quality?**  
A: Edit consistently. The system learns from your edits. After 5-10 edits with a consistent pattern, you'll see improvement in future drafts."""

new_faq = """**Q: How do I improve the AI output quality?**  
A: Use Edit → Save & Approve consistently. The system learns from every correction. After 5-10 edits with a consistent pattern (e.g., always shortening, always removing formal words), you'll see measurable improvement. See [Learning Loop guide](../guides/content-review-and-learning.md)."""

content = content.replace(old_faq, new_faq, 1)

with open(path, 'w') as f:
    f.write(content)
print(f'Updated {path}')


# === client-viewer.md ===
path = '/Volumes/2SSD/Projects/ReddirSaaS/docs/kb/roles/client-viewer.md'
with open(path, 'r') as f:
    content = f.read()

content = content.replace('> **Last updated:** 2026-05-28', '> **Last updated:** 2026-06-20')

# Replace the draft approval section
old_text = """## If Draft Approval Is Enabled

Your admin may grant you the ability to approve/reject drafts. If so:

1. Go to Review Queue
2. Review pending drafts
3. Actions available:
   - ✅ Approve — sends to posting queue
   - ✏️ Edit — modify then approve
   - ❌ Reject — discard

Same review guidelines as [Client Manager](./client-manager.md#review-decisions)."""

new_text = """## If Draft Approval Is Enabled

Your admin may grant you the ability to approve/reject drafts. If so:

1. Go to Review Queue
2. Review pending drafts
3. Actions available:
   - **✓ Approve** — sends to posting queue (AI learns "this was good")
   - **✎ Edit → Save & Approve** — modify text, one click saves and approves
   - **✗ Reject** — discard (AI learns to avoid this style)

> **Edit is one step:** Click ✎, modify text, click "Save & Approve ✓" — saves, approves, and teaches the AI in one action.

Same review guidelines as [Client Manager](./client-manager.md#review-decisions).  
Full learning loop details: [Content Review & Self-Learning Loop](../guides/content-review-and-learning.md)."""

content = content.replace(old_text, new_text, 1)

with open(path, 'w') as f:
    f.write(content)
print(f'Updated {path}')


# === avatar-owner.md ===
path = '/Volumes/2SSD/Projects/ReddirSaaS/docs/kb/roles/avatar-owner.md'
with open(path, 'r') as f:
    content = f.read()

content = content.replace('> **Last updated:** 2026-05-28', '> **Last updated:** 2026-06-20')

with open(path, 'w') as f:
    f.write(content)
print(f'Updated {path} (date only - avatar owners don\'t review drafts)')

print('\nAll role docs updated.')
