# User Manual — Client Viewer

> **Audience:** Client executives and stakeholders with read-only access  
> **Last updated:** 2026-06-20

---

## Your Role

As **Client Viewer**, you have read-only access to your company's Reddit marketing dashboard. You can see what's happening — avatars, drafts, activity — but you don't make changes.

If your account has `draft_approval_enabled`, you can also approve/reject/edit drafts.

---

## What You Can Do

| Area | Access |
|------|--------|
| View dashboard | ✅ |
| View avatars and their status | ✅ |
| View drafts (pending, approved, posted) | ✅ |
| View activity events | ✅ |
| View subreddits and threads | ✅ |
| Approve/reject drafts | Only if enabled by admin |
| Edit anything | ❌ |
| Manage team | ❌ |
| Change configuration | ❌ |

---

## What You'll See

### Dashboard

Your dashboard provides a snapshot of:
- **Active avatars** — how many, their health status
- **This week's activity** — drafts generated, approved, posted
- **Pipeline status** — is everything running normally

### Avatars

For each avatar you can see:
- Current phase and karma
- Health status (active/limited/issues)
- Subreddits where it participates
- Performance metrics (removal rate, confidence score)

### Drafts

Browse all drafts:
- **Pending** — awaiting review by your team
- **Approved** — ready for posting
- **Posted** — live on Reddit (with link)
- **Rejected** — discarded

### Activity Feed

Timeline of all events:
- When subreddits were scraped
- When drafts were generated
- When content was approved/posted
- Any issues (frozen avatars, health alerts)

---

## If Draft Approval Is Enabled

Your admin may grant you the ability to approve/reject drafts. If so:

1. Go to Review Queue
2. Review pending drafts
3. Actions available:
   - **✓ Approve** — sends to posting queue (AI learns "this was good")
   - **✎ Edit → Save & Approve** — modify text, one click saves and approves
   - **✗ Reject** — discard (AI learns to avoid this style)

> **Edit is one step:** Click ✎, modify text, click "Save & Approve ✓" — saves, approves, and teaches the AI in one action.

Same review guidelines as [Client Manager](./client-manager.md#review-decisions).  
Full learning loop details: [Content Review & Self-Learning Loop](../guides/content-review-and-learning.md).

---

## FAQ

**Q: Why can't I change anything?**  
A: Your role is designed for oversight and reporting. If you need edit access, ask your company's Client Admin to upgrade your role to Client Manager.

**Q: How often is data updated?**  
A: Pipeline runs at 08:00 and 14:00 daily. Scraping is continuous. Dashboard data refreshes on page load.

**Q: Can I export reports?**  
A: Check if export buttons are available on your dashboard. If not, ask your Client Admin or RAMP account manager.

**Q: Who do I contact if something looks wrong?**  
A: Your company's Client Admin, or your RAMP account manager (Tzvi).
