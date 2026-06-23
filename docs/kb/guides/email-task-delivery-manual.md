# EPG Email Task Delivery — Operational Manual

> **Audience:** Owner, Partner, Avatar Manager
> **Last updated:** 2026-06-23

## Status: LIVE

Email delivery of EPG tasks is operational. Per-avatar routing implemented June 23, 2026.

## Routing Logic (Updated June 23)

Each avatar has its own executor email. Tasks are ONLY sent when:

1. `email_tasks_enabled = true` (system setting)
2. Avatar has `executor_email` configured
3. Avatar's `executor_email_verified = true`

If any condition fails, the task is NOT created and the reason is logged.

**There is no global fallback.** Every avatar must have its own verified email.

## Configuration

| Setting | Value | Location |
|---------|-------|----------|
| `email_tasks_enabled` | `true` | System Settings (DB) |
| `brevo_api_key` | (masked) | System Settings (DB) |
| `smtp_from_email` | `tasks@gorampit.com` | System Settings (DB) |
| `smtp_from_name` | `RAMP Task System` | System Settings (DB) |
| Delivery method | Brevo HTTP API (port 443) | Code |
| Per-avatar email | Avatar > Posting tab > Email Task Routing | Admin UI |

## Setting Up an Avatar for Email Tasks

1. Go to Admin > Avatars > select avatar > **Posting** tab
2. Scroll to "Email Task Routing" section
3. Enter executor email (the person who posts from this Reddit account)
4. Click Save
5. Click "Mark as Verified" (confirms you verified this person owns the email)
6. Done — approved drafts for this avatar will now be emailed to them

## How It Works

```
Draft approved (any approval path)
  -> sync_slot_status(db, draft_id, "approved")
    -> _dispatch_email_task_if_enabled()
      -> Check: email_tasks_enabled = true
      -> Check: avatar.executor_email is set
      -> Check: avatar.executor_email_verified = true
      -> create_execution_task(db, slot.id)
        -> dispatch_delivery() -> Brevo HTTP API -> executor inbox
```

## Trigger Points

Email is sent when a draft is approved in any of these locations:
- `/admin/review` — admin review queue
- `/review/{id}/approve` — review API
- Decision Center bulk approve
- `pages.py` approve button
- `avatar_workflow.py` approve

All paths call `sync_slot_status(db, draft.id, "approved")` which triggers the email hook.

## Email Content

```
Subject: [RAMP Task] {ClientName} / {AvatarUsername} / r/{subreddit} / {type} / {time}

Body:
- Task Code: TASK-YYYYMMDD-NNN
- Client: {name}
- Avatar: u/{username}
- Subreddit: r/{name}
- Thread: {title} ({url})
- Scheduled: {time}
- Deadline: {time + 4h}
- Generated Text: {full comment text}
- Action Link: /tasks/{code}/{token} (accept/submit without login)
```

## Task Lifecycle

```
generated -> emailed -> accepted -> submitted -> url_verified -> content_verified -> verified
                                                                                 -> failed
                                              -> expired (deadline passed)
                                              -> cancelled (admin)
```

## Multi-Avatar Owners

One person can manage multiple avatars. They receive separate emails per avatar task.
The email subject includes the avatar username so they know which Reddit account to use.

Example: Worker manages u/TechGuru42 and u/CloudExpert99 — gets separate task emails for each.

## Anti-Spam

- Max 3 resends per task
- 10 minute cooldown between resends
- UNIQUE constraint prevents duplicate tasks per EPG slot

## Why a Task Was NOT Sent (Troubleshooting)

| Symptom | Cause | Fix |
|---------|-------|-----|
| No task created after approval | email_tasks_enabled = false | System Settings -> enable |
| No task created after approval | Avatar has no executor_email | Posting tab -> set email |
| No task created after approval | executor_email_verified = false | Posting tab -> Mark as Verified |
| Email not delivered | Brevo API key invalid/expired | System Settings -> update key |
| Email in spam | gorampit.com not verified in Brevo | Add DKIM DNS records |

Check logs for: `Skipping email task for slot ... : no executor email` or `executor email not verified`

## Known Limitations

1. **Manual verification only** — admin marks email as verified (no magic link yet)
2. **Sender shows brevosend.com** — domain gorampit.com not verified in Brevo (needs DKIM DNS records)
3. **DO blocks SMTP ports** — cannot use direct SMTP, using HTTP API as workaround
4. **No bulk email assignment** — each avatar configured individually

## Admin UI Location

Admin > Avatars > [avatar] > **Posting** tab > "Email Task Routing" section

Shows:
- Current email + verification status (green checkmark / amber warning)
- Form to set/change email (resets verification on change)
- Verify / Revoke Verification buttons
- Explanation text for each state
