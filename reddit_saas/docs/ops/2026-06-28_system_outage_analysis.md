# Ops Session Log — June 28, 2026

## Trigger

Tzvi emails (June 26-27) reporting multiple XM Cyber issues.
Investigation revealed 17-day system outage.

## Findings

### Root Cause: Celery Worker Death (~June 11)

- **Last successful scrape:** June 11, 2026
- **Last hobby scrape:** June 11, 2026
- **Last scoring:** June 11, 2026
- **Workers revived briefly June 13-14:** produced only errors (phantom subreddit IDs)
- **After June 14:** complete silence (no task execution at all)
- **Duration of outage:** 17 days (June 11 → June 28)
- **Detection:** Tzvi email June 27 (not automated detection!)

### SBM Violations

| Property | Status | Duration |
|----------|--------|----------|
| **P1** (Monotonic Progress) | VIOLATED | 17 days — XM Cyber received 0 drafts |
| **P10** (Graceful Degradation) | VIOLATED | Single component death → total system death |
| **P9** (Diagnostic Independence) | Secondary effect — health checks also dead |

### Why It Wasn't Detected

1. **alert_aggregation.py** only renders in admin UI — no push notification
2. **signal_collector** is a Celery task — dead with Celery
3. **heartbeat task** is a Celery task — dead with Celery
4. **/health endpoint** checked only DB+Redis, not worker liveness
5. **No external monitor** (UptimeRobot, cron) watching the system
6. **Max didn't log into admin** for extended period (normal — working on code locally)

### Cascade Effect on Other Symptoms

| Tzvi's reported symptom | Root cause |
|------------------------|------------|
| No professional comments | No scraping → no fresh threads → scoring/generation returns 0 |
| 24-25 day old content | Hobby posts from before outage still had status="new" |
| 25 vs 4 tasks in queue | 496 stale pending drafts accumulated, never expired |
| connor_lloyd "shadowbanned" | health_check ran during outage → probe found old post → false positive |
| AI Visibility empty | GEO monitoring not configured for XM Cyber |

### Shadowban False Positives

**Tzvi confirmed (email June 27 22:56):** Neither connor_lloyd nor Flaky_Finder_13 are shadowbanned.

**Mechanism of false positive:**
1. Workers die → avatar stops generating submissions
2. Last submission ages (days/weeks old)
3. Health check (if it ran at all) calls `check_submission_visibility()`
4. Probe looks for submission in subreddit's top-100 new posts
5. Old post not in top-100 → classified as "shadowban" 
6. Avatar frozen → further compounds the problem

**Fix deployed:** Probe now returns `inconclusive` for submissions older than 24h.

## Code Fixes Deployed (Local — pending prod deploy)

| File | Fix | Tension |
|------|-----|---------|
| `app/services/health_checker.py` | Submission probe age check (>24h = inconclusive) | T-2026-06-28-005 |
| `app/tasks/ai_pipeline.py` | Hobby pipeline 7-day freshness filter | T-2026-06-28-001a |
| `app/services/opportunity_engine.py` | EPG Source 2 hobby 7-day freshness filter | T-2026-06-28-001a |
| `app/routes/portal.py` | Sidebar count: frozen/active + 14-day cap; pending tab age filter | T-2026-06-28-001b |
| `app/main.py` | /health returns worker_alive + pipeline_alive + scrape_stale_hours | T-2026-06-28-004 |
| `app/services/alert_aggregation.py` | New "pipeline_dead" critical alert (no scrape in 24h) | T-2026-06-28-006 |

## Actions Needed (Production)

### IMMEDIATE (today)

1. SSH to prod → check container status (`docker compose ps`)
2. Restart Celery workers if dead
3. Verify scraping resumes (`docker compose logs celery --tail=50`)
4. Deploy code fixes (rsync + rebuild)
5. Batch-reject stale pending drafts:
   ```sql
   UPDATE comment_drafts SET status = 'rejected' 
   WHERE status = 'pending' AND created_at < NOW() - interval '14 days';
   ```

### SHORT-TERM (this week)

6. Set up UptimeRobot or BetterUptime on `https://gorampit.com/health`
   - Alert condition: `status != "ok"` OR `pipeline_alive == false`
   - Notify: Max + Tzvi via email/Telegram
7. Add docker restart policy (`restart: unless-stopped`) on all worker containers
8. Verify connor_lloyd and Flaky_Finder_13 are active on prod (should be per local DB)

### MEDIUM-TERM (next sprint)

9. Implement standalone cron watchdog (outside Docker) that checks container health
10. Add Telegram notification bot for critical alerts
11. Implement `_generate_css.py` for automated state snapshots

## Lessons Learned

1. **Self-monitoring is not monitoring.** If the observer lives inside the observed system, failure of the system = failure of observation. External watchdog is mandatory.

2. **"No output" must be distinguishable from "no work to do."** Zero drafts for a paying client is never acceptable silently. Pipeline components need to assert "I expected input but got none."

3. **Health probes must be bounded in time.** A test that checks "is this post visible in a feed?" must account for post age. Otherwise, system's own failures (no new posts) trigger false health alerts that compound the original problem.

4. **CSS/documentation is only as good as its refresh rate.** Manual CSS generation means human must remember to reconcile. Automating this removes one more human-dependency point.

5. **Celery Beat + Docker Compose = invisible death.** When Beat dies, scheduled tasks silently stop. No error, no log, no alert. External heartbeat monitoring is the only reliable detection mechanism.
