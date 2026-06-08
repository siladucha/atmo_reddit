# Bug Fix Report — June 7, 2026

**Status: All 5 issues fixed and deployed to production.**

---

## Bug 1: Thread Date Shows Wrong Time

**Problem:** Review queue showed "2d ago" for a thread that was actually 10 days old on Reddit.

**Root cause:** The system was displaying the date when the *draft was created in our database*, not when the Reddit post was actually published.

**Fix:** Now displays the real Reddit post creation date. If a thread was posted 10 days ago on Reddit, it shows "10d ago" — regardless of when we scraped it.

---

## Bug 2: Edit & Approve Gets Stuck

**Problem:** After editing a comment and clicking "Save & Approve", the screen freezes — the card doesn't disappear and the edited text isn't saved.

**Root cause:** Two issues:
1. Server-side: The learning loop call had a broken function signature (wrong import). Although wrapped in try/except, it could cause cascading session issues.
2. Client-side: No error handling on the fetch request. If the server returned any unexpected response, the card would stay frozen forever with no user feedback.

**Fix:**
- Fixed the server-side learning loop call (now uses correct `LearningService().capture_edit_record()`)
- Added proper error handling to all JavaScript fetch calls — if anything goes wrong, the user sees an alert and the card recovers

---

## Bug 3: No Way to Mark Comments as Posted

**Problem:** After approving a comment, it just disappears. No way to track what's been posted, what's waiting to be posted, or mark things as done.

**Fix:** Complete Review Queue redesign with three tabs:

| Tab | Purpose |
|-----|---------|
| **✍ Pending** | Drafts waiting for approval (same as before) |
| **📋 Ready to Post** | Approved comments with Copy button + "Mark as Posted" |
| **✓ Posted** | History of posted comments (last 30 days) |

**Workflow:**
1. Review & approve drafts in "Pending" tab
2. Switch to "Ready to Post" — see approved comments ready to go
3. Click Copy, open thread on Reddit, paste & post manually
4. Come back, click "Mark as Posted" → done

---

## Bug 4: Only One Subreddit Gets Content

**Problem:** Lena_Gupta19 has 3 hobby subreddits configured (homelab, marathontraining, opensource), but the review queue only showed drafts from r/homelab.

**Root cause:** The AI generation pipeline grabbed the first 10 available posts without any subreddit rotation. Since r/homelab has far more posts (159 scraped vs 2 for marathontraining), it dominated the queue.

**Fix:** Implemented round-robin distribution — the system now generates comments evenly across all subreddits. With 3 subs and max 10 comments per run: ~3-4 comments from each sub.

---

## Bug 5: Inactive/Banned Avatars in Filter

**Problem:** The avatar filter pills in the review queue showed inactive and banned avatars (emma_richardson, leon_grant10, etc.) — cluttering the UI with useless options.

**Fix:** Filter now only shows active, non-frozen avatars. Also, drafts from inactive/frozen avatars are excluded from the review queue entirely — no point reviewing content for avatars that can't post.

---

## Deployment

- All fixes deployed to production (161.35.27.165)
- Health check: ✅ OK
- No regressions detected (652 tests passing)
- App, Celery worker, and Celery Beat all restarted

---

## What Wasn't Changed

- No database migrations required
- No changes to the admin panel (only client portal affected)
- No changes to the posting system, pipeline, or scheduling
- Avatar configurations remain unchanged
