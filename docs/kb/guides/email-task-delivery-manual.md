# EPG Email Task Delivery — User Manual (v2)

## What Is This

RAMP delivers approved posting tasks to human executors via email. Instead of (or alongside) automated posting via proxies, the system sends a clear email with all details needed to post manually on Reddit — then independently verifies the result.

**Flow:**
```
EPG generates slot → Human approves → Email sent to executor → Executor posts manually → RAMP verifies via Reddit API → Confirmed
```

**Trust model:** RAMP does NOT trust the executor's self-report. The only source of truth is independent Reddit API verification (PRAW read-back: correct author, correct subreddit, text similarity >60%).

---

## For Admin (Owner / Partner)

### Setup (one-time)

1. Go to **Admin Panel → System Settings** (`/admin/settings`)
2. Find the **email_tasks** section (scroll down or search)
3. Configure all fields:

| Setting | What to enter | Example |
|---------|---------------|---------|
| `email_tasks_enabled` | `true` to activate the system | `true` |
| `smtp_host` | SMTP server | `mail.gorampit.com` |
| `smtp_port` | Port (587=STARTTLS, 465=SSL) | `587` |
| `smtp_user` | SMTP login | `tasks@gorampit.com` |
| `smtp_password` | SMTP password (auto-encrypted in DB) | `*****` |
| `smtp_from_email` | Sender address | `tasks@gorampit.com` |
| `smtp_from_name` | Display name | `RAMP Task System` |
| `smtp_use_tls` | TLS encryption | `true` |
| `email_tasks_default_recipient` | Who receives tasks by default | `max@gorampit.com` |
| `email_tasks_max_resends` | Max resend attempts (anti-spam) | `3` |
| `email_tasks_cooldown_minutes` | Min minutes between resends | `10` |
| `email_tasks_deadline_hours` | Hours before task expires | `4` |

4. **Save.** System is now active — every approved draft creates an email task.

### Turning it ON/OFF

- **ON:** Set `email_tasks_enabled` = `true` in System Settings
- **OFF:** Set `email_tasks_enabled` = `false`. No new tasks will be created. Existing active tasks expire at their deadline.

### What happens automatically when enabled

When anyone (admin, client, or autopilot) approves a draft:
1. System creates an `ExecutionTask` record (status: `generated`)
2. Email is sent to `email_tasks_default_recipient` within 30 seconds
3. Task status transitions to `emailed`
4. Task appears in `/admin/tasks`

### Monitoring tasks

Go to **Admin Panel → Execution Tasks** (`/admin/tasks`)

You see:
- **Task list** with columns: Code, Client, Avatar, Subreddit, Status, Recipient, Deadline
- **Filter tabs**: All | Active | Verified | Expired
- **SLA Metrics** button (top right)

#### Status badges

| Color | Statuses | Meaning |
|-------|----------|---------|
| 🔵 Blue | emailed, accepted | Waiting for executor |
| 🟡 Yellow | submitted, url_verified | Verification in progress |
| 🟢 Green | verified | Done — comment confirmed on Reddit |
| 🔴 Red | failed, expired | Problem — needs attention |
| ⚫ Gray | cancelled | Manually cancelled |

### Actions you can take

| Action | Where | When to use | Limits |
|--------|-------|-------------|--------|
| **Resend email** | Task row → "Resend" button | Executor didn't receive email | Max 3 resends, 10 min cooldown |
| **Verify URL** | Task detail → "Verify URL" form | You or executor posted, have the permalink | Runs two-stage verification |
| **Cancel** | Task detail → "Cancel Task" | Thread died, strategy changed, duplicate | Requires reason. Permanent (soft delete). |
| **View detail** | Click task code link | See full content, delivery log, status history | — |

### Verification (what it checks)

When a URL is submitted (by executor or admin), the system runs two stages:

**Stage 1 — URL verification:**
- Comment exists on Reddit (not 404)
- Not [removed] by moderators
- Not [deleted] by author
- Correct subreddit (matches task)
- Correct author (matches avatar username)

**Stage 2 — Content verification:**
- Text similarity >60% (allows minor edits by executor)
- Fetches actual comment body from Reddit API

**Security guards:**
- **URL reuse prevention** — same permalink cannot verify two different tasks
- **Slot race guard** — if automated posting already posted this slot, task auto-cancels
- **Author validation** — prevents claiming someone else's comment

### SLA Metrics

Go to `/admin/tasks/metrics` (or "SLA Metrics" button on task list)

| Metric | Formula | What it tells you |
|--------|---------|-------------------|
| Accept rate | accepted / emailed | Do executors acknowledge tasks? |
| Submit rate | submitted / accepted | Do they actually post? |
| Verification pass rate | verified / submitted | Do submissions pass verification? |
| Median execution time | median(emailed → submitted) | How fast are executors? |
| Expired task rate | expired / total | % of tasks that hit deadline |

Use these to evaluate executor reliability and tune deadlines.

### Error scenarios

| Problem | What you see | What to do |
|---------|-------------|------------|
| Email not delivered | Task stuck at `generated` | Check SMTP config. Resend. |
| Executor didn't post by deadline | Task → `expired` | Resend with new deadline, or cancel. |
| Verification failed: wrong author | Status: `failed` | Executor used wrong Reddit account. Instruct them. |
| Verification failed: wrong subreddit | Status: `failed` | Executor posted in wrong thread. |
| Verification failed: text too different | url_verified (stuck) | Executor edited too heavily. Ask to re-post. |
| Duplicate: auto-posting won | Task → `cancelled` (auto) | Normal — "first wins" design. No action needed. |

### Coexistence with automated posting

Both paths can run simultaneously for the same approved slot:
- **Email task:** fires immediately on approval (if enabled)
- **Auto-posting:** Celery Beat every 5 min finds approved slots with proxy configured

**First to succeed wins:**
- If auto-posting posts first → slot.status="posted" → email task auto-expires at deadline (or auto-cancels on next verify attempt)
- If executor submits URL first → verification marks "posted" → auto-posting sees slot.status="posted", skips it

**No double-posting at system level.** However, if executor posts manually before auto-posting fires AND auto-posting posts before executor submits the URL — two Reddit comments will exist. This is mitigated by:
- Auto-posting fires every 5 min (fast)
- Verification checks slot.status before confirming
- Only one path gets billing credit (future marketplace)

### State machine

```
generated ─→ emailed ─→ accepted ─→ submitted ─→ url_verified ─→ verified ✓
    │            │           │           │              │
    │            │           │           │              └─→ failed (content mismatch)
    │            │           │           └─→ failed (hard verification failure)
    │            │           │
    └────────────┴───────────┴─→ expired (deadline passed, no URL submitted)
                                  cancelled (admin cancelled / slot posted by other channel)
```

**Terminal states** (no transitions out): verified, expired, cancelled
**Retry allowed:** failed → submitted (executor can try again)
**Guards:** Cannot expire a task that already has a submitted URL (race protection)

---

## For Client (Client Admin / Client Manager / Client Viewer)

### What changes for you

**Nothing in your daily workflow.** You continue to:
1. Review drafts in your portal (`/clients/{id}/review`)
2. Approve or reject comments as usual
3. See posted results and notifications

### What happens behind the scenes

When you approve a draft:
- If `email_tasks_enabled = true`: system also sends the task to a human executor via email
- Whichever path succeeds first (automated or manual) — the comment appears as "posted"
- You get the same notification: "Comment posted on r/..."

### What you see

| Screen | Changes |
|--------|---------|
| Review Queue | No changes — approve/reject as usual |
| EPG Schedule | Slots show status (approved → posted). No change. |
| Notifications | "Comment posted on r/..." when verified (same as before) |
| Avatars | No change |

### What you DON'T see (by design)

- Execution tasks (ops detail, not client-facing)
- Who executed the task
- Email delivery logs
- Verification details

### FAQ

**Q: Will comments take longer to appear?**
A: Potentially 30-120 minutes with email tasks vs. minutes with auto-posting. The deadline ensures max 4 hours. If auto-posting is also configured, it runs in parallel and usually wins.

**Q: What if nobody posts my approved comment?**
A: The task expires after 4 hours. Admin can resend or the next EPG cycle generates new opportunities.

**Q: Can I choose only automated posting?**
A: This is configured by the platform admin. Both systems coexist — the fastest path wins.

---

## For Executor (person receiving the email)

### What you receive

An email with subject:
```
[RAMP Task] XM Cyber / Hot-Thought2408 / r/cybersecurity / Comment / 18:30
```

Contents:
- Task code (e.g. TASK-20260620-003)
- Client and avatar info
- Target thread URL
- Exact comment text to post
- Timing and deadline
- **Action Link** (unique to you, no login required)

### Step-by-step

1. **Click the Action Link** in the email
   - Opens a task page at `https://gorampit.com/tasks/TASK-20260620-003/{your-token}`
   - Shows full task details

2. **Click "Accept Task"**
   - Confirms you'll do it (optional but recommended)

3. **Log in to Reddit** as the specified avatar (u/username in the task)

4. **Navigate to the thread URL** from the task

5. **Post the comment**
   - Copy text from the task page
   - Paste into Reddit's reply box
   - Minor wording adjustments OK (system allows 40% deviation)
   - Press "Comment" on Reddit

6. **Copy the permalink**
   - Under your posted comment: "Share" → "Copy Link"
   - Or right-click timestamp → "Copy Link Address"

7. **Submit the permalink** on the task page
   - Paste URL in the "Reddit Permalink" field
   - Click "Submit & Verify"

8. **See result immediately**
   - ✅ "Verified" — done, you're confirmed
   - ❌ "Verification failed: [reason]" — fix and try again

### Rules

| Rule | Why |
|------|-----|
| Post from the **exact** Reddit account specified | System checks author name |
| Post in the **exact** thread linked | System checks subreddit |
| Don't change more than ~40% of the text | System checks text similarity |
| Post before the deadline | Task expires after deadline |
| Don't forward the email/link | Token is unique to you |
| Don't reuse a URL from another task | System detects URL reuse |

### What the system verifies (you cannot fake)

- Comment exists on Reddit (fetched via API)
- Author matches avatar username
- Subreddit matches target
- Text is >60% similar to generated text
- URL not already used for another task
- Comment not deleted/removed

### Error recovery

| Problem | Solution |
|---------|----------|
| Didn't get the email | Check spam. Ask admin to resend. |
| Action link gives "410 Gone" | Task expired or cancelled. Contact admin. |
| Verification failed: wrong author | You logged into wrong Reddit account. Re-post from correct one. |
| Verification failed: wrong subreddit | You posted in wrong thread. Re-post in correct one. |
| Verification failed: text too different | You edited too much. Re-post closer to original. |
| Can't find my posted comment | Go to your Reddit profile → Comments → find it → copy permalink. |
| Thread is locked | Don't post. Contact admin — they'll cancel the task. |

### Timeline example

```
18:30  Email arrives: "[RAMP Task] XM Cyber / Hot-Thought2408 / r/cybersecurity / Comment / 18:30"
18:32  You click action link, see task, click "Accept"
18:35  You log into Reddit as u/Hot-Thought2408
18:36  You navigate to thread, paste comment, hit "Comment"
18:37  You copy permalink, paste into task page, click "Submit & Verify"
18:37  System: ✅ "Verified! Comment confirmed (match: 95%)"
18:37  Done. Client gets notification.
```

---

## Technical Reference

### Architecture

```
System Settings: email_tasks_enabled = true
         │
         ▼
[Approval event: draft.status → approved, slot.status → approved]
         │
         ▼
sync_slot_status() → _dispatch_email_task_if_enabled()
         │
         ▼
create_execution_task(db, slot.id)
  → ExecutionTask created (UNIQUE on epg_slot_id)
  → executor_token = UUID4
         │
         ▼
deliver_execution_task.delay(task.id, 1)  [Celery async]
  → dispatch_delivery() → compose_task_email() → send_email() [SMTP]
  → DeliveryAttempt created (UNIQUE on task_id + attempt_number)
         │
         ▼
[Email arrives → executor opens token link]
  GET /tasks/{code}/{token}  [no auth required]
         │
         ▼
[Executor posts on Reddit → submits URL]
  POST /tasks/{code}/{token}/submit
         │
         ▼
verify_full(db, task_id, reddit_url)
  1. URL reuse check (audit patch)
  2. Slot already-posted check (race guard)
  3. Stage 1: PRAW fetch → exists, not removed, correct sub, correct author
  4. Stage 2: text similarity via difflib.SequenceMatcher
         │
         ▼
[All pass] → task=verified, draft=posted, slot=posted, client notified
```

### Database tables

| Table | Purpose | Key constraints |
|-------|---------|----------------|
| `execution_tasks` | One per approved EPG slot | UNIQUE(epg_slot_id), UNIQUE(task_code), UNIQUE(executor_token) |
| `delivery_attempts` | One per send attempt | UNIQUE(task_id, attempt_number) |

### API endpoints

| Path | Auth | Method | Purpose |
|------|------|--------|---------|
| `/admin/tasks` | Admin | GET | Task list with filters |
| `/admin/tasks/{id}` | Admin | GET | Task detail + delivery log |
| `/admin/tasks/{id}/resend` | Admin | POST | Resend email (HTMX) |
| `/admin/tasks/{id}/verify` | Admin | POST | Submit URL for verification (HTMX) |
| `/admin/tasks/{id}/cancel` | Admin | POST | Cancel with reason (HTMX) |
| `/admin/tasks/metrics` | Admin | GET | SLA dashboard |
| `/tasks/{code}/{token}` | Token | GET | Executor views task |
| `/tasks/{code}/{token}/accept` | Token | POST | Executor accepts |
| `/tasks/{code}/{token}/submit` | Token | POST | Executor submits URL → verify |

### Settings (System Settings → email_tasks group)

| Key | Default | Description |
|-----|---------|-------------|
| email_tasks_enabled | false | Master switch |
| email_tasks_default_recipient | (empty) | Default email recipient |
| email_tasks_max_resends | 3 | Anti-spam: max resend attempts |
| email_tasks_cooldown_minutes | 10 | Anti-spam: min minutes between sends |
| email_tasks_deadline_hours | 4 | Default deadline offset |
| smtp_host | (empty) | SMTP server |
| smtp_port | 587 | SMTP port |
| smtp_user | (empty) | SMTP login |
| smtp_password | (empty) | SMTP password (encrypted) |
| smtp_from_email | tasks@gorampit.com | From address |
| smtp_from_name | RAMP Task System | From display name |
| smtp_use_tls | true | Use TLS |

### Security model

| Threat | Defense |
|--------|---------|
| Token guessing | UUID4 = 122 bits entropy |
| URL reuse (double billing) | DB check: no other verified task with same URL |
| Fake permalink | PRAW fetch + author + subreddit + text validation |
| Race: auto + human both post | Slot status check before verification confirms |
| Race: expire vs submit | Atomic UPDATE skips tasks with submitted_url |
| Executor spam (resend flood) | max_resends + cooldown + terminal state guard |
| Invalid state transitions | ALLOWED_TRANSITIONS dict validated in _transition_status() |
