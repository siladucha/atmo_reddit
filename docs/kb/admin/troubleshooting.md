# Troubleshooting Guide

> **Audience:** Owner (Max)  
> **Last updated:** 2026-05-28

---

## Quick Diagnostics

```bash
# Check all services running
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml ps"

# Check health
ssh root@161.35.27.165 "curl -s http://localhost/health | python3 -m json.tool"

# Check recent errors
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=100 app | grep -i error"

# Check Celery worker
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=50 celery_worker"

# Check disk space
ssh root@161.35.27.165 "df -h"

# Check memory
ssh root@161.35.27.165 "free -h"
```

---

## Common Issues

### App Not Responding (502/504)

**Symptoms:** Browser shows 502 Bad Gateway or timeout

**Check:**
```bash
# Is the app container running?
ssh root@161.35.27.165 "docker ps | grep app"

# Check app logs for crash
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=100 app"
```

**Common causes:**
- App crashed (check logs for Python traceback)
- Out of memory (check `free -h`)
- Database connection pool exhausted

**Fix:**
```bash
# Restart app
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml restart app"

# If OOM, restart everything
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml down && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
```

---

### Pipeline Not Running (No New Drafts)

**Symptoms:** No new drafts appearing, activity feed empty

**Check:**
1. Kill switches: `/admin/settings` → all enabled?
2. Celery worker running?
```bash
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=20 celery_worker"
```
3. Celery Beat running?
```bash
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=20 celery_beat"
```
4. Redis connected?
```bash
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec redis redis-cli ping"
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
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml restart celery_worker celery_beat"
```

---

### Database Connection Errors

**Symptoms:** "connection refused" or "too many connections" in logs

**Check:**
```bash
# Is PostgreSQL running?
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec db pg_isready"

# Check connection count
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec db psql -U reddit_saas_user -d reddit_saas -c 'SELECT count(*) FROM pg_stat_activity;'"
```

**Fix:**
```bash
# Restart database (careful — brief downtime)
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml restart db"

# Wait 10s, then restart app
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml restart app celery_worker"
```

---

### Redis Connection Issues

**Symptoms:** Tasks not executing, locks not working

**Check:**
```bash
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec redis redis-cli ping"
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec redis redis-cli info memory"
```

**Fix:**
```bash
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml restart redis"
# Then restart workers (they need to reconnect)
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml restart celery_worker celery_beat"
```

---

### LLM API Errors

**Symptoms:** "API error", "rate limit", "authentication failed" in logs

**Check:**
```bash
# Look for LLM-related errors
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=200 celery_worker | grep -i 'litellm\|anthropic\|gemini\|openrouter'"
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
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec app alembic current"
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec app alembic history --verbose"
```

**Fix:**
```bash
# If migration failed mid-way, stamp to known good revision
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec app alembic stamp head"

# Then restart
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml restart app"
```

---

### Disk Space Full

**Symptoms:** Write errors, container crashes

**Check:**
```bash
ssh root@161.35.27.165 "df -h"
ssh root@161.35.27.165 "docker system df"
```

**Fix:**
```bash
# Clean Docker (unused images, containers, volumes)
ssh root@161.35.27.165 "docker system prune -f"
ssh root@161.35.27.165 "docker image prune -a -f"

# Check log sizes
ssh root@161.35.27.165 "du -sh /var/lib/docker/containers/*/\*.log | sort -h"

# Truncate large container logs
ssh root@161.35.27.165 "truncate -s 0 /var/lib/docker/containers/CONTAINER_ID/*-json.log"
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
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec redis redis-cli DEL scrape_rate_limiter"
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

## Nuclear Options (Last Resort)

### Full Stack Restart

```bash
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml down && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
```

### Rebuild Everything

```bash
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml down && docker compose -f docker-compose.yml -f docker-compose.prod.yml build --no-cache && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
```

### Database Reset (DESTRUCTIVE)

⚠️ Only if database is corrupted and you have a backup:
```bash
# Stop everything
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml down"

# Remove DB volume
ssh root@161.35.27.165 "cd /app && docker volume rm app_postgres_data"

# Start fresh (entrypoint will create schema)
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"

# Restore from backup
scp /path/to/backup.custom root@161.35.27.165:/tmp/
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db pg_restore -U reddit_saas_user -d reddit_saas --clean --if-exists --no-owner /tmp/backup.custom"
```
