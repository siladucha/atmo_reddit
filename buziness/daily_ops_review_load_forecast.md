# Daily Ops Review — Load Forecast (Detailed)

## Summary

The Daily Ops Review adds **negligible load** to the system. It runs once per day for 60-90 minutes, performs read-only SQL queries against existing tables, and optionally makes 4-6 LLM calls (budget-capped at $1/day).

**Impact on existing infrastructure:** < 1% additional load.

---

## Database Load (PostgreSQL)

### Snapshot Collection (once at session start)

| Query | Tables Hit | Rows Scanned | Estimated Time |
|-------|-----------|-------------|----------------|
| Error count (24h) | activity_events | ~1,440 (24h × 60/min heartbeats + events) | <50ms |
| Failed tasks (24h) | activity_events WHERE type='task_failure' | ~50 | <20ms |
| AI cost totals (24h) | ai_usage_log | ~200-400 | <30ms |
| Scrape freshness | subreddits + scrape_log | ~50 subs | <20ms |
| Posting stats (24h) | posting_events | ~50-100 | <20ms |
| Avatar health | avatars | ~50 | <10ms |
| Queue depth | comment_drafts WHERE status='pending' | ~50 | <20ms |
| Karma outcomes (48h) | karma_snapshots | ~200 | <30ms |
| 7-day averages (each metric) | Same tables, 7-day window | ~7x above | <200ms |
| **Total snapshot collection** | | | **<500ms** |

### During Session (per section load)

| Section | Queries | Time |
|---------|---------|------|
| Health (read cached snapshot) | 0 (from cache) | 0ms |
| Changes (compare 24h vs prev 24h) | 2-4 queries on activity_events | <100ms |
| Decisions (open from 7d) | 1 query on review_decisions | <10ms |
| **Total per section** | | **<110ms** |

### Writes

| Operation | Frequency | Rows | Time |
|-----------|-----------|------|------|
| Create snapshot | 1x/day | 1 row (JSONB) | <10ms |
| Create session | 1x/day | 1 row | <5ms |
| Auto-save inputs | Every 2s during typing (~100x/session) | UPDATE 1 row | <5ms each |
| Create decision | 1-3x/day | 1-3 rows | <5ms |
| Create report | 1x/day | 1 row (JSONB) | <10ms |
| **Total writes/day** | ~105 operations | | **<600ms total** |

### Connection Pool Impact

- Current pool: 20 connections, max overflow 10
- Daily Review uses: 1 connection during session (synchronous)
- Auto-save: 1 short-lived connection per 2s = negligible
- **Impact: 0 additional persistent connections**

### Storage Growth

| Table | Growth/day | Growth/month | Growth/year |
|-------|-----------|-------------|------------|
| review_snapshots | ~20 KB | ~600 KB | ~7 MB |
| daily_review_sessions | ~5 KB | ~150 KB | ~2 MB |
| review_decisions | ~1 KB | ~30 KB | ~360 KB |
| intelligence_reports | ~15 KB | ~450 KB | ~5 MB |
| **Total** | **~41 KB/day** | **~1.2 MB/month** | **~15 MB/year** |

**At 60 GB disk:** 15 MB/year is 0.025% of disk. Irrelevant.

---

## LLM API Load (External)

### Phase 1 (no LLM) — $0/day

Phase 1 uses template-based analysis only. Zero LLM calls.

### Phase 2+ (with LLM) — Target $0.20-0.40/day

| Call | Model | Input Tokens | Output Tokens | Cost | Frequency |
|------|-------|-------------|---------------|------|-----------|
| Health classification | Gemini 2.0 Flash | 2,000 | 200 | $0.01 | 1x/day |
| Change categorization | Gemini 2.0 Flash | 3,000 | 500 | $0.02 | 1x/day |
| Trend classification | Gemini 2.0 Flash | 2,000 | 400 | $0.02 | 1x/day |
| Hypothesis generation | Claude 3.5 Haiku | 4,000 | 800 | $0.08 | 1x/day |
| Forecast (7 domains) | Gemini 2.0 Flash | 3,000 | 600 | $0.02 | 1x/day |
| Narrative report | Claude 3.5 Haiku | 3,000 | 500 | $0.05 | 1x/day |
| **Total** | | **17,000** | **3,000** | **$0.20** | |

### Comparison to Existing Pipeline Load

| System | LLM calls/day | Cost/day | % of total |
|--------|--------------|---------|-----------|
| Client pipeline (10 clients) | ~150-300 | $11.70 | 97% |
| Daily Ops Review (Phase 2) | 4-6 | $0.20 | 1.7% |
| Monitoring/alerts (Phase 3) | 2-4 | $0.10 | 0.8% |
| **Agent total** | **6-10** | **$0.30** | **2.5%** |

**The agent adds 2.5% to total LLM spend. Negligible.**

---

## CPU/Memory Load (DigitalOcean Droplet)

### Current baseline: 2 vCPU, 4 GB RAM

| Component | CPU Impact | Memory Impact | When |
|-----------|-----------|--------------|------|
| Snapshot SQL queries | 5-10% for 500ms | +2 MB (result set) | Once at start |
| Section loading | 1-2% for 100ms | +1 MB per partial | On section click |
| Auto-save writes | <0.1% per write | 0 | Every 2s during typing |
| LLM API calls (external) | <1% (waiting on network) | +0.5 MB per response | 4-6 calls total |
| Template rendering | 1-2% for 50ms | +0.5 MB | Per section |
| **Peak during session** | **~12% for 1s** | **+5 MB** | At session start |
| **Sustained during session** | **<2%** | **+3 MB** | 60-90 min |

### Comparison to Pipeline Peaks

| Event | CPU Peak | Duration |
|-------|---------|----------|
| Pipeline run (08:00/14:00) | 60-80% | 30 min |
| Health check batch | 30-40% | 5 min |
| Daily Review start | 10-12% | 1 second |
| Daily Review sustained | 1-2% | 60-90 min |

**Daily Review is invisible next to pipeline spikes.** If you do the review at 09:00-10:30 (between pipeline peaks), zero contention.

---

## Redis Load

| Operation | Frequency | Impact |
|-----------|-----------|--------|
| Session cache (if needed) | 1 SET at start | +20 KB memory |
| Budget accumulator read | Per LLM call (6x) | 6 GET commands |
| **Total Redis commands/day** | ~10 | **0.001% of daily Redis load** |

Current Redis load: ~8,644 commands/day from pipeline.
Daily Review adds: ~10 commands/day.

---

## Network I/O

| Direction | Data | When |
|-----------|------|------|
| Browser → Server (HTMX) | ~2 KB per section load | 6x per session |
| Server → Browser (HTML partials) | ~5 KB per section | 6x per session |
| Server → LLM API (external) | ~20 KB per call | 4-6 calls |
| LLM API → Server | ~5 KB per response | 4-6 calls |
| **Total network per session** | **~200 KB** | Once per day |

Current daily network: ~50 MB (scraping + LLM + admin UI).
Daily Review adds: 200 KB = 0.4% increase.

---

## Celery Worker Impact

**Zero.** Daily Review does NOT use Celery tasks. All operations are synchronous within the HTTP request/response cycle:

- Snapshot collection: sync SQL (< 1s)
- LLM calls: async httpx within FastAPI handler (< 5s each)
- Report generation: sync Python (< 100ms)
- Auto-save: sync DB write (< 5ms)

No queue messages, no background tasks, no worker contention.

---

## Scaling Projections

### At 10 clients (current target)

- Daily Review: 1 session/day, 500ms SQL, 4-6 LLM calls, 200 KB network
- **Zero scaling concern.** System won't notice.

### At 50 clients

- Still 1 session/day (operator is one person)
- Snapshot SQL might take 1-2s (more data in tables)
- LLM calls same (analysis is platform-level, not per-client)
- **Still zero concern.**

### At 100 clients

- Snapshot SQL: 2-5s (larger tables, more events)
- Might want to pre-aggregate daily metrics (add a Beat task at 07:00)
- LLM input tokens grow (more signals to classify): $0.20 → $0.40/session
- **Within budget. Optimize SQL with materialized views if needed.**

### At 500 clients (theoretical)

- Snapshot SQL: 5-10s without optimization
- Need: pre-aggregated daily_metrics table (Beat task at 01:00)
- LLM: batch signals (classify top-50 only, not all 2000)
- Budget: still $0.50-0.80/session if batched well
- **Still within $1/day cap.**

---

## Conclusion

| Metric | Current System | + Daily Review | % Increase |
|--------|---------------|---------------|-----------|
| DB queries/day | ~9,350 | +115 | +1.2% |
| DB storage/month | ~500 MB | +1.2 MB | +0.24% |
| LLM cost/day | $11.70 | +$0.20 | +1.7% |
| CPU peak | 60-80% (pipeline) | +12% for 1s | 0% sustained |
| Redis commands/day | 8,644 | +10 | +0.12% |
| Network/day | ~50 MB | +200 KB | +0.0004% |
| Celery tasks/day | ~1,662 | +0 | 0% |

**The Daily Ops Review is architecturally free.** It reads existing data, produces a small artifact, and costs $0.20/day in LLM. The system literally won't notice it exists.
