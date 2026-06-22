# System Settings Reference

> **Audience:** Owner only  
> **Last updated:** 2026-06-20

---

## Access

`/admin/settings` — Owner role required.

Settings are stored in the `system_settings` table as key-value pairs, grouped by category.

---

## Pipeline Controls

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `pipeline_enabled` | bool | `true` | Master kill switch. OFF = no scraping, scoring, or generation. |
| `generation_enabled` | bool | `true` | AI generation kill switch. OFF = no new drafts created. |
| `scrape_enabled` | bool | `true` | Scraping kill switch. OFF = no Reddit API calls for data collection. |

---

## Scoring Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `scoring_threshold` | float | `0.6` | Minimum score to tag thread as "engage" |
| `scoring_max_threads_per_run` | int | `50` | Max threads scored per pipeline run per client |
| `scoring_freshness_hours` | int | `72` | Only score threads newer than this |
| `llm_scoring_model` | string | `gemini/gemini-2.5-flash-lite` | Model used for scoring |

---

## Generation Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `llm_generation_model` | string | `claude-sonnet-4-20250514` | Model used for comment generation |
| `max_drafts_per_avatar_per_day` | int | `8` | Daily budget per avatar |
| `min_minutes_between_comments` | int | `45` | Minimum gap between posts for same avatar |
| `generation_max_retries` | int | `3` | LLM call retry attempts |

---

## Scraping Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `scrape_freshness_window_hours` | int | `12` | How often each subreddit is scraped |
| `scrape_rate_limit_rpm` | int | `15` | Max scrape requests per minute (Reddit allows 60) |
| `scrape_posts_per_subreddit` | int | `25` | Posts fetched per scrape |

---

## Repurpose Scraping

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `repurpose_min_score` | int | `50` | Minimum upvotes for evergreen thread harvest |
| `repurpose_limit_per_sub` | int | `25` | Max threads per subreddit per repurpose run |

---

## Health Check Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `health_check_interval_hours` | int | `12` | How often health checks run per avatar |
| `cqs_check_interval_days` | int | `7` | Days between CQS checks per avatar |
| `cqs_check_rate_limit_delay_seconds` | int | `3` | Delay between CQS API calls (rate limiting) |

---

## Reddit API Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `reddit_client_id` | string | — | Reddit OAuth app client ID |
| `reddit_client_secret` | string | — | Reddit OAuth app secret |
| `reddit_user_agent` | string | — | User agent string for API calls |

---

## Presence Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `presence_scan_interval_days` | int | `7` | Days between presence scans per avatar |
| `presence_stale_threshold_days` | int | `7` | Days before presence data marked stale |

---

## Phase Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `phase1_min_karma` | int | `100` | Karma needed to promote from Phase 1 → 2 |
| `phase1_min_days` | int | `60` | Account age needed for Phase 1 → 2 |
| `phase2_min_karma` | int | `300` | Karma needed for Phase 2 → 3 |
| `phase2_min_days` | int | `120` | Account age needed for Phase 2 → 3 |

---

## Safety Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `brand_ratio_max_percent` | int | `15` | Max % of avatar's weekly comments mentioning brand |
| `max_posts_per_subreddit_per_day` | int | `3` | Posting frequency cap per subreddit |
---

## Automated Posting

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `auto_posting_enabled` | bool | `true` | Global kill switch for automated (proxy) posting |
| `auto_posting_daily_cap` | int | `8` | Max automated posts per avatar per day |

---

## Email Task Delivery

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `email_tasks_enabled` | bool | `false` | Enable email-based task delivery on draft approval |
| `email_tasks_default_recipient` | string | — | Default executor email (who receives tasks) |
| `email_tasks_max_resends` | int | `3` | Anti-spam: max email resend attempts per task |
| `email_tasks_cooldown_minutes` | int | `10` | Anti-spam: min minutes between resends |
| `email_tasks_deadline_hours` | int | `4` | Hours before task expires if not completed |

### SMTP Configuration

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `smtp_host` | string | — | SMTP server hostname (e.g. `mail.gorampit.com`) |
| `smtp_port` | int | `587` | SMTP port (587=STARTTLS, 465=SSL) |
| `smtp_user` | string | — | SMTP authentication username |
| `smtp_password` | secret | — | SMTP password (encrypted in DB via Fernet) |
| `smtp_from_email` | string | `tasks@gorampit.com` | Sender email address |
| `smtp_from_name` | string | `RAMP Task System` | Sender display name |
| `smtp_use_tls` | bool | `true` | Use TLS for SMTP connection |

### How to activate

1. Fill in all SMTP fields (host, port, user, password)
2. Set `email_tasks_default_recipient` to the executor's email
3. Set `email_tasks_enabled` = `true`
4. Save — approved drafts now generate email tasks

### Monitoring

- Task list: `/admin/tasks`
- SLA metrics: `/admin/tasks/metrics`
- Delivery log: visible in task detail page

---

## Notes

- Changes take effect on the next pipeline run (no restart needed)
- All setting changes are logged in the audit trail
- Invalid values are rejected with validation errors
- Settings can be viewed but not changed by Partner role
