# RAMP Platform — Quick Testing Guide for Jenny

## How to Access

**URL:** https://gorampit.com  
**Login:** https://gorampit.com/login

Ask Max for your credentials (email + password). You'll be set up as `client_manager` role with access to the client portal.

---

## What You Can Test

### 1. Client Portal — Review Queue

After login, you'll land on the dashboard. The main workflow:

1. **Dashboard** — see pending drafts count, recent activity
2. **Review Queue** — this is where the magic happens:
   - You'll see AI-generated comments waiting for human approval
   - Each draft shows: target subreddit, thread title, the AI comment, and which avatar will post it
   - Actions: **Approve** | **Reject** | **Edit + Approve** (fix the text then approve)
3. **Mark as Posted** — after you manually post an approved comment on Reddit, click "Mark as Posted" and paste the Reddit URL

### 2. Key Things to Look For

- [ ] Does the review queue load? Are drafts visible?
- [ ] Can you approve a draft? (click Approve -> should move to "approved" tab)
- [ ] Can you reject a draft? (click Reject -> disappears from pending)
- [ ] Can you edit a draft? (click Edit, change text, Save -> should approve it)
- [ ] Does the dashboard show stats correctly?
- [ ] Is the UI readable on mobile? (responsive layout)

### 3. How Comments Get Here

The pipeline runs automatically twice daily (8:00 and 14:00 Israel time):
1. System scrapes subreddits -> finds new posts
2. AI scores posts -> picks the best ones for engagement
3. AI generates a comment for each selected post (using avatar's voice/persona)
4. Comment appears in your Review Queue -> **you decide if it's good enough**

---

## Navigation

| Section | What's There |
|---------|-------------|
| Dashboard | Overview stats, activity feed |
| Review | Pending/Approved/Posted drafts |
| Threads | All scraped Reddit threads with scores |
| Avatars | Reddit accounts assigned to your client |

---

## Important Notes

- **You cannot break anything** — approve/reject actions are safe, no real posting happens automatically right now
- **Posting is manual** — after you approve a draft, someone (avatar owner) copies the text and posts it on Reddit manually. Then marks it "posted" in the system.
- **AI quality varies** — some comments will be great, some mediocre. The more you reject/edit, the better the AI learns (it tracks your corrections)
- **If something looks broken** — screenshot it and send to Max. Note the URL and what you clicked.

---

## Quick Smoke Test Checklist

Run through this in 5 minutes:

1. Open https://gorampit.com/login -> enter credentials -> lands on dashboard
2. Click "Review" in sidebar -> see pending drafts
3. Open one draft -> read the AI comment -> makes sense for the thread?
4. Approve one draft -> it moves to "Approved" tab
5. Reject one draft -> it disappears from pending
6. Edit one draft (change a word) -> save -> appears in approved
7. Check "Threads" page -> shows Reddit posts with relevance scores
8. Check "Avatars" page -> shows assigned Reddit accounts

If all 8 pass -> system is working correctly. Report any 500 errors or blank pages.

---

## Contact

Issues? -> Max (Telegram/WhatsApp)
