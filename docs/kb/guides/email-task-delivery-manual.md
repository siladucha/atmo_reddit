# EPG Email Task Delivery — Operational Status (June 22, 2026)

## Status: LIVE ✅

Email delivery of EPG tasks is operational as of June 22, 2026.

## Configuration

| Setting | Value | Location |
|---------|-------|----------|
| `email_tasks_enabled` | `true` | system_settings DB |
| `email_tasks_default_recipient` | `max.breger@gmail.com` | system_settings DB |
| `brevo_api_key` | `xkeysib-...` (masked) | system_settings DB |
| `smtp_from_email` | `tasks@gorampit.com` | system_settings DB |
| `smtp_from_name` | `RAMP Task System` | system_settings DB |
| Delivery method | Brevo HTTP API (port 443) | Code |
| SMTP ports | Blocked by DigitalOcean | Infrastructure |

## How It Works

```
EPG Slot (approved) 
  → sync_slot_status() 
    → _dispatch_email_task_if_enabled()
      → create_execution_task() 
        → DeliveryAttempt record
          → Brevo HTTP API → Gmail inbox
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
generated → emailed → accepted → submitted → url_verified → content_verified → verified
                                                                             → failed
                                            → expired (deadline passed)
                                            → cancelled (admin)
```

## Anti-Spam

- Max 3 resends per task
- 10 minute cooldown between resends
- UNIQUE constraint prevents duplicate tasks per EPG slot

## Delivery Stats (June 22)

- Tasks created: 12
- Emails sent: 12
- Delivery method: Brevo HTTP API
- Recipient: max.breger@gmail.com

## Known Limitations

1. **Single recipient** — all tasks go to `email_tasks_default_recipient`. No per-avatar routing yet.
2. **Sender shows brevosend.com** — domain gorampit.com not verified in Brevo (needs DKIM DNS records)
3. **DO blocks SMTP ports** — cannot use direct SMTP, using HTTP API as workaround
4. **Hobby slots skipped** — `hobby_post_not_found` when no fresh hobby content available

## Future Improvements

- Verify gorampit.com domain in Brevo (proper From address)
- Per-avatar executor email (field on Avatar model)
- Telegram channel delivery
- Auto-retry content verification
- SLA dashboard in admin UI
