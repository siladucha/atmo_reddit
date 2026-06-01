# Reply to Tzvi — UX Feedback (May 30, 2026)

Hi Tzvi,

Thanks for the detailed feedback with screenshots — super helpful. Here's what I've done and what's the plan for each point:

---

## 1. Threads — Avatar Column ✅ DONE

Added an "Avatar" column to the Threads tab. For threads tagged "engage", it now shows which avatar has been assigned (pulled from existing draft assignments). If no avatar is assigned yet, it shows "—".

This gives you immediate visibility into which avatar will comment on which thread.

---

## 2. Competitor Keywords — New Category ✅ DONE

Added a new keyword category: **COMPETITOR**. You can now add competitor brand names (e.g., "CrowdStrike", "Tenable", "Wiz") as keywords with the "COMPETITOR" priority.

**How it works:**
- Competitor keywords are included in the scoring prompt — the AI will flag threads where competitors are mentioned
- In the EPG thread selection, competitor mentions get a weight of 2.5 (between HIGH=3.0 and MEDIUM=2.0) — so threads mentioning competitors are prioritized for engagement
- The competitive_landscape field (free text) still exists for broader context, but now you have structured competitor monitoring via keywords

**To add competitors:** Go to Client → Keywords tab → Add keyword → select "COMPETITOR" priority.

---

## 3. Thread Date + Freshness ✅ DONE

Three changes here:

### a) Thread date now visible everywhere
- **Review Queue:** Each draft card now shows the thread's age (e.g., "2h ago", "3d ago", "22d ago ⚠"). Color-coded: green (<2d), amber (2-7d), red (>7d with warning icon).
- **Threads tab:** New "Posted" column showing when the Reddit post was created.
- Threads older than 7 days are visually dimmed (opacity reduced).

### b) 7-day age filter on generation
The AI pipeline now **automatically skips threads older than 7 days** when generating comments. This prevents the exact scenario you described — no more drafts for 22-day-old posts.

### c) Scraping frequency increased
Changed the default scraping interval from **12 hours → 6 hours**. Each subreddit now gets scraped ~4 times/day instead of 2. The `queue_tick` fires every 60 seconds and picks the stalest subreddit, so fresh content flows in continuously.

**Why you saw stale data:** The system was likely not running the pipeline (either the server was down or the kill switch was off). The scraping itself runs automatically via Celery Beat — as long as the worker is up, it scrapes. I'll verify the production worker is running.

---

## 4. Decision Queue vs Professional Comments — Clarification

These are **two different views** with different purposes:

| | Decision Queue | Professional Comments |
|---|---|---|
| **Purpose** | Action queue — approve/reject/edit | Historical overview — read-only |
| **Shows** | Only PENDING drafts | ALL drafts (pending + approved + posted) |
| **Sorted by** | Risk level (high risk first) | Chronological |
| **Actions** | Approve, Reject, Edit, Copy | View only |

**Decision Queue** = "what needs my attention right now"
**Professional Comments** = "what has this avatar done historically"

I've added subtitle text to both sections to make this clearer in the UI.

---

## 5. Brand Mention Safety Warning ✅ DONE (from your second email)

**Implemented:** Real-time brand mention detection in the edit textarea.

When a reviewer edits a comment and types the client's brand name or domain, the system now shows an immediate warning:

- **Phase 1 avatar:** "⚠️ BRAND MENTION DETECTED — Phase 1 avatar: brand mentions are BLOCKED. This comment will be rejected by safety gates."
- **Phase 2 avatar:** "⚠️ BRAND MENTION DETECTED — Phase 2 avatar: brand mentions are restricted. Ensure brand ratio stays below 10% in early phase."
- **Phase 3 avatar:** "Verify brand mention is appropriate for this avatar's current phase."

This is a **client-side warning** that fires instantly as you type — no need to submit the form. The existing server-side safety gates (PhasePolicy) still enforce the rules at posting time as a second layer of protection.

**How it works technically:**
- The system knows each client's `brand_name` and `brand_domain`
- When text is entered in the edit field, it checks for case-insensitive matches
- Warning appears/disappears in real-time as you type

---

## Summary of Changes

| Change | Status | Files Modified |
|--------|--------|---------------|
| Avatar column in Threads | ✅ Done | `client_hub_threads.html`, `pages.py` |
| Competitor keyword category | ✅ Done | `client_hub_keywords.html`, `pages.py`, `epg.py` |
| Thread date in Review UI | ✅ Done | `admin_review.html`, `admin.py` |
| Thread date in Threads tab | ✅ Done | `client_hub_threads.html`, `pages.py` |
| 7-day age filter on generation | ✅ Done | `ai_pipeline.py` |
| Scraping frequency 12h→6h | ✅ Done | `settings.py` |
| Brand mention safety warning | ✅ Done | `admin_review.html` (JS) |
| Decision Queue vs Pro Comments labels | ✅ Done | `admin_avatar_detail.html` |
| Store Reddit post date | ✅ Done | `thread.py` model + all scraping locations + migration |

**DB Migration required:** `aa1b2c3d4e5f` adds `reddit_created_at` column to `reddit_threads`. Will run automatically on next deploy via entrypoint.

**Note:** Existing threads won't have `reddit_created_at` (it'll be NULL). New threads scraped after deploy will have the correct Reddit post date. The UI gracefully falls back to `created_at` (scrape time) for old threads.

---

Let me know if you want any adjustments to these changes.

Max
