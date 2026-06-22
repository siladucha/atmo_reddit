# Troubleshooting: Client Not Generating Comments

**Role required:** Owner or Partner (admin panel access)

**Applies to:** Any client that stopped receiving new comment drafts.

---

## Step 1 — Check Client Status

**Go to:** Admin → Clients → [Client Name]

| Field | Expected | Problem if |
|-------|----------|------------|
| is_active | true | false = pipeline skips this client entirely |
| plan_type | "paid", "growth", "scale", etc. | "trial" + created >14 days ago = expired, pipeline skips |

**Fix:** If plan_type is "trial" — change it to "paid" (or the correct plan).

---

## Step 2 — Check Avatars

**Go to:** Admin → Clients → [Client Name] → Avatars section

For each avatar assigned to the client, check:

| Field | Expected | Problem if |
|-------|----------|------------|
| is_frozen | false | true = avatar excluded (check freeze_reason) |
| is_shadowbanned | false | true = avatar excluded |
| health_status | "active" | "shadowbanned" or "suspended" = excluded |
| cqs_level | anything except "lowest" | "lowest" = only hobby comments, no brand |
| warming_phase | 1, 2, or 3 | 0 (Mentor) = excluded from all pipelines |
| pool | b2b, b2c, or warm | other = excluded |

**If ALL avatars are excluded** → system has no one to generate comments for.

**Fix:** Unfreeze an avatar, or assign a healthy avatar to the client.

---

## Step 3 — Check Kill Switches

**Go to:** Admin → Settings

| Setting | Expected |
|---------|----------|
| pipeline_enabled | true |
| generation_enabled | true |

If either is false → generation is OFF for ALL clients globally.

---

## Step 4 — Check Activity Feed

**Go to:** Admin → Clients → [Client Name] → Transparency tab

Look for recent events:
- **"score" events** — means scoring ran (shows engage/monitor/skip counts)
- **"generate" events** — means drafts were created
- **"safety_block" events** — means generation was attempted but blocked by safety gates

**If no events in 2-3 days** → pipeline is being skipped (most likely Step 1 or Step 3).

**If scoring shows "0 engage"** → no relevant threads found. Check that subreddits are being scraped (Step 5).

---

## Step 5 — Check Subreddits

**Go to:** Admin → Clients → [Client Name] → Subreddits tab

Verify:
- At least one subreddit is assigned and **active**
- last_scraped_at is recent (within last 24h)

**If not scraping** → check that scrape_enabled is true in Settings.

---

## Quick Summary

| # | Check | Where | Most common fix |
|---|-------|-------|-----------------|
| 1 | Plan type not "trial" (or trial not expired) | Client page | Change plan_type to "paid" |
| 2 | At least one healthy avatar | Client → Avatars | Unfreeze or assign new avatar |
| 3 | Kill switches ON | Admin → Settings | Set to true |
| 4 | Activity events exist | Client → Transparency | Fix steps 1-3, wait for next run |
| 5 | Subreddits being scraped | Client → Subreddits | Activate subreddit assignments |

---

## When Does the Pipeline Run?

The AI pipeline (score → generate) runs automatically at **08:00** and **14:00** (Israel time).

After fixing any issue above, the next scheduled run will pick up the client and generate new drafts.
