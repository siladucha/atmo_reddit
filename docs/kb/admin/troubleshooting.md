# Troubleshooting Guide

> **Audience:** Owner (Max)  
> **Last updated:** 2026-06-23

---

## Quick Diagnostics

```bash
# Check all services running
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml ps"

# Check health
ssh ramp "curl -s http://localhost/health | python3 -m json.tool"

# Check recent errors
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=100 app | grep -i error"

# Check Celery worker
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=50 celery_worker"

# Check disk space
ssh ramp "df -h"

# Check memory
ssh ramp "free -h"
```

---

## Common Issues

### App Not Responding (502/504)

**Symptoms:** Browser shows 502 Bad Gateway or timeout

**Check:**
```bash
# Is the app container running?
ssh ramp "docker ps | grep app"

# Check app logs for crash
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=100 app"
```

**Common causes:**
- App crashed (check logs for Python traceback)
- Out of memory (check `free -h`)
- Database connection pool exhausted

**Fix:**
```bash
# Restart app
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml restart app"

# If OOM, restart everything
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml down && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
```

---

### Pipeline Not Running (No New Drafts)

**Symptoms:** No new drafts appearing, activity feed empty

**Check:**
1. Kill switches: `/admin/settings` → all enabled?
2. Celery worker running?
```bash
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=20 celery_worker"
```
3. Celery Beat running?
```bash
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=20 celery_beat"
```
4. Redis connected?
```bash
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec redis redis-cli ping"
```

**Common causes:**
- Kill switch accidentally toggled OFF
- Celery worker crashed (check logs)
- Redis connection lost
- All clients deactivated
- All avatars frozen

**Fix:**
```bash
# Restart workers
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml restart celery_worker celery_beat"
```

---

### Database Connection Errors

**Symptoms:** "connection refused" or "too many connections" in logs

**Check:**
```bash
# Is PostgreSQL running?
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec db pg_isready"

# Check connection count
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec db psql -U reddit_saas_user -d reddit_saas -c 'SELECT count(*) FROM pg_stat_activity;'"
```

**Fix:**
```bash
# Restart database (careful — brief downtime)
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml restart db"

# Wait 10s, then restart app
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml restart app celery_worker"
```

---

### Redis Connection Issues

**Symptoms:** Tasks not executing, locks not working

**Check:**
```bash
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec redis redis-cli ping"
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec redis redis-cli info memory"
```

**Fix:**
```bash
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml restart redis"
# Then restart workers (they need to reconnect)
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml restart celery_worker celery_beat"
```

---

### LLM API Errors

**Symptoms:** "API error", "rate limit", "authentication failed" in logs

**Check:**
```bash
# Look for LLM-related errors
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=200 celery_worker | grep -i 'litellm\|anthropic\|gemini\|openrouter'"
```

**Common causes:**
- API key expired or invalid
- Rate limit hit (too many concurrent requests)
- Provider outage
- Billing quota exceeded

**Fix:**
- Check provider status pages
- Verify API keys in `.env`
- If rate limited: system retries automatically (3x with backoff)
- If provider down: toggle `generation_enabled` OFF, wait, toggle back

---

### Alembic Migration Errors

**Symptoms:** App won't start, "alembic" errors in logs

**Check:**
```bash
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec app alembic current"
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec app alembic history --verbose"
```

**Fix:**
```bash
# If migration failed mid-way, stamp to known good revision
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec app alembic stamp head"

# Then restart
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml restart app"
```

---

### Disk Space Full

**Symptoms:** Write errors, container crashes

**Check:**
```bash
ssh ramp "df -h"
ssh ramp "docker system df"
```

**Fix:**
```bash
# Clean Docker (unused images, containers, volumes)
ssh ramp "docker system prune -f"
ssh ramp "docker image prune -a -f"

# Check log sizes
ssh ramp "du -sh /var/lib/docker/containers/*/\*.log | sort -h"

# Truncate large container logs
ssh ramp "truncate -s 0 /var/lib/docker/containers/CONTAINER_ID/*-json.log"
```

---

### Scraping Stuck (Subreddits Not Updating)

**Symptoms:** `last_scraped_at` not updating, stale indicators on subreddits page

**Check:**
1. Is `scrape_enabled` ON?
2. Is queue_tick running? (check celery_beat logs)
3. Are there active client assignments for the subreddit?
4. Is the rate limiter blocking? (check Redis)

**Fix:**
- Manual scrape: Subreddits page → "Scrape Now" button
- If rate limiter stuck:
```bash
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec redis redis-cli DEL scrape_rate_limiter"
```

---

### Avatar Health Check Failing

**Symptoms:** Health status stuck on "unknown", no updates

**Check:**
- Is the health check task running? (celery_beat logs)
- Reddit API accessible?
- Avatar credentials valid?

**Fix:**
- Manual trigger: Avatar detail → "Refresh from Reddit"
- If Reddit API issue: wait and retry
- If credentials invalid: update in avatar settings

---

---

### GEO Execution History — "Details" Shows Empty or Batch Stuck

**Symptoms:** Clicking "Details →" in GEO Execution History shows empty area or "This batch failed to complete"

**Root cause:** GEO batch was triggered (manually or via test) but never completed. Batch stays in `running` status forever with 0 successful queries.

**Check:**
```bash
# See batch statuses
ssh ramp "docker exec app-db-1 psql -U reddit_saas_user -d reddit_saas -c \"SELECT id, status, total_queries, successful_queries, triggered_by, started_at FROM geo_execution_batches WHERE client_id = 'CLIENT_UUID' ORDER BY started_at DESC LIMIT 5;\""
```

**Common causes:**
- Perplexity API key not configured (`geo_perplexity_api_key` in System Settings)
- API timeout during execution
- Test batch that was never meant to complete
- `geo_monitoring_enabled` was OFF when batch was triggered

**Fix:**
```bash
# Mark stale running batches as failed (older than 1 hour)
ssh ramp "docker exec app-db-1 psql -U reddit_saas_user -d reddit_saas -c \"UPDATE geo_execution_batches SET status = 'failed' WHERE status = 'running' AND started_at < NOW() - INTERVAL '1 hour';\""
```

- Then click "Run Now" on the GEO page to trigger a fresh batch
- Verify `geo_perplexity_api_key` is set in `/admin/settings`

**Note:** The "Details →" button works via HTMX — it loads results into a panel below the history table. If the batch has no metrics (failed/stuck), it shows an appropriate status message.

## Nuclear Options (Last Resort)

### Full Stack Restart

```bash
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml down && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
```

### Rebuild Everything

```bash
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml down && docker compose -f docker-compose.yml -f docker-compose.prod.yml build --no-cache && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
```

### Database Reset (DESTRUCTIVE)

⚠️ Only if database is corrupted and you have a backup:
```bash
# Stop everything
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml down"

# Remove DB volume
ssh ramp "cd /app && docker volume rm app_postgres_data"

# Start fresh (entrypoint will create schema)
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"

# Restore from backup
scp /path/to/backup.custom root@161.35.27.165:/tmp/
ssh ramp "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db pg_restore -U reddit_saas_user -d reddit_saas --clean --if-exists --no-owner /tmp/backup.custom"
```
