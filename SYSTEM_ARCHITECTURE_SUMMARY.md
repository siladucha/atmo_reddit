# RAMP — System Architecture Summary for Analysts

**Version:** 1.0 | **Date:** June 25, 2026 | **Status:** Production (gorampit.com)

---

## 1. What RAMP Is

RAMP (Reddit Attention Management Platform) is a **closed-loop reputation execution system** that:

- Discovers high-value Reddit discussions matching client business goals
- Generates persona-calibrated responses via AI (Claude Sonnet / Gemini Flash)
- Routes execution tasks to human operators (avatar owners) for manual posting
- Collects engagement signals (karma, deletions, replies) and adapts strategy

**Core property:** Human-in-the-Loop. No content reaches Reddit without human approval. The system proposes; humans decide; the system learns from decisions.

**System classification:** Not a pipeline. A self-updating behavioral model of distributed agents in external social systems.

---

## 2. System Identity

| Dimension | Value |
|-----------|-------|
| Category | Managed Persona Intelligence Platform (Category 5 — new market segment) |
| Deployment | DigitalOcean Droplet (2 vCPU, 4GB RAM), Docker Compose, Frankfurt DE |
| Stack | Python 3.11 / FastAPI / PostgreSQL 16 (pgvector) / Redis 7 / Celery |
| AI Models | Claude Sonnet (generation), Gemini Flash (scoring/analysis) |
| Current scale | 10 clients, 50 avatars, ~200 scrapes/day, ~150 generations/day |
| Revenue model | SaaS $149-$1,499/mo + managed service + pre-warmed avatar fees |
| Operating margin | >90% at all projected scales |
| Domain | gorampit.com (SSL, Let's Encrypt) |

---

## 3. Core Behavioral Loop

```
Discovery --> Planning --> Execution --> Signal Collection
    ^                                          |
    |         Adaptation <-- Evaluation <------+
    +----------------------------------------------
```

**Cycle frequency:** 2x daily (08:00 + 14:00 pipeline runs) + continuous signal collection (every 4h).

**Key distinction from linear pipelines:** System corrects its own behavior. Human edits teach the AI; karma outcomes adjust opportunity scoring; removal patterns update risk models. The system at month 6 produces fundamentally different output than at month 1 — for the same client and same subreddits.

---

## 4. Entity Model

### 4.1 Primary Entities (7 core)

| Entity | Purpose | Lifecycle |
|--------|---------|-----------|
| **Client** | Business objective holder | Created > active > (trial_expired) > deactivated |
| **Avatar** | Execution identity | Created > Phase 1 > Phase 2 > Phase 3 > (Expert) or (Frozen/Suspended) |
| **Subreddit** | Target environment | Added > profiled > risk-scored > (high_risk flagged) |
| **CommentDraft** | Generated content unit | pending > approved/rejected > posted |
| **EPGSlot** | Scheduled execution unit | planned > generated > approved > posted/skipped/expired |
| **ExecutionTask** | Delivery to human executor | generated > emailed > accepted > submitted > verified/expired |
| **Opportunity** | Scored engagement target | Created (per EPG build) > allocated/skipped |

### 4.2 Relationship Model

- Client 1:N Avatar (via client_ids JSONB — one avatar may serve multiple clients)
- Client 1:N Subreddit (via ClientSubredditAssignment with priority + engagement_approach)
- Avatar 1:N EPGSlot (daily schedule)
- Avatar 1:N CommentDraft (generated content per-client)
- Avatar 1:N SubredditKarma (reputation per environment)
- Avatar 1:N KarmaSnapshot (outcome time-series: 4h/24h/48h/7d)
- Avatar 1:1 ExecutorEmail (human posting operator)
- Subreddit 1:1 SubredditRiskProfile (moderation intelligence)
- Subreddit 1:N RedditThread (scraped content)

### 4.3 Multi-Tenancy and Isolation

| Layer | Mechanism |
|-------|-----------|
| Data access | query_scope.py — client boundary enforced at ORM query level |
| LLM context | isolation.py — runtime assertion that avatar belongs to requesting client |
| Admin access | RBAC 7 roles with permission guards on every endpoint |
| Credential storage | Fernet AES-128 encryption for passwords, tokens, proxy URLs |

**Unresolved:** Two clients in same niche sharing an avatar — no conflict detection mechanism.

---

## 5. Seven-Layer Architecture

### Layer 1: Discovery

**Purpose:** Find relevant conversations in target environments.

| Component | Mechanism | Schedule |
|-----------|-----------|----------|
| Subreddit scraping | PRAW API (25 posts/scrape) | Every 60s (gated by per-sub interval) |
| Smart Scoring | Budget-aware: remaining_budget x 3 threads, HARD_CAP=15 | 2x/day |
| Opportunity scoring | 6 dimensions: visibility, competition, trust, karma, risk, strategic | During EPG |

**Output:** Ranked opportunity set per avatar. ~90% cost reduction vs scoring all threads.

### Layer 2: Planning (EPG — Electronic Program Guide)

**Purpose:** Allocate limited attention budget across opportunities.

| Component | Mechanism |
|-----------|-----------|
| Portfolio Manager | Investment-style allocation (AttentionBudget + ReturnWeights) |
| Risk Engine | 6-factor assessment (age, karma, frequency, moderation, content_type, health) + phase multiplier |
| Return Engine | Expected karma/trust/visibility/influence prediction |
| Timing Engine | +/-30% jitter, min 45 min interval, active hours 08:00-23:00, peak hour bias |
| Fitness Gate | Pre-generation safety check (subreddit rules, avatar eligibility) |

**Output:** Daily schedule of EPG slots per avatar. Budget = min(phase_limit, daily_cap).

### Layer 3: Generation

**Purpose:** Produce persona-calibrated content.

| Pipeline | Model | Phase | Output |
|----------|-------|-------|--------|
| Professional | Claude Sonnet (~12K input + 200 output tokens) | Phase 2+ | 5-15 drafts/day |
| Hobby | Gemini Flash (~4K tokens) | Phase 1+ | 1-3 drafts/day |

**Intelligence injection:** Self-learning loop injects few-shot examples from prior human edits + correction patterns. Strategy context shapes angle selection. Voice profile calibrates tone.

### Layer 4: Human Gate (Critical Differentiator)

**Purpose:** Quality control + training signal generation.

| Function | Mechanism |
|----------|-----------|
| Review | Admin/client approves, rejects, or edits each draft |
| Auto-approve | Per-avatar opt-in flag (explicit, not default) |
| Learning capture | Every edit > EditRecord > CorrectionPattern > future prompt injection |

**Architectural significance:** Human edits are NOT corrections of AI mistakes. They are the primary training signal that creates the compounding moat. After 6 months of edits, the system produces client-specific output no competitor can replicate.

### Layer 5: Transport (Email Task Delivery)

**Purpose:** Route approved content to human executors for posting.

| State | Meaning |
|-------|---------|
| generated | Task created, waiting for send window |
| emailed | Email delivered to executor (~30 min before slot time) |
| accepted | Executor acknowledged |
| submitted | Executor posted + submitted Reddit URL |
| verified | System verified URL matches expected content |
| expired | Deadline passed without execution |

**Controls:** Max 3 delivery attempts per task, min 10 min between resends, 4h deadline (configurable).

### Layer 6: Signal Collection

**Purpose:** Observe outcomes in external environment.

| Signal | Collection method | Frequency |
|--------|-------------------|-----------|
| Karma (per comment) | PRAW comment.score | 4h/24h/48h/7d after posting |
| Deletion | PRAW comment removed detection | Same schedule |
| Reply count | PRAW comment.replies | Same schedule |
| Shadowban | Profile accessibility check | 2x/day (07:30, 13:30) |
| Account suspension | Reddit API response code | 2x/day |

**Bonus:** Draft reconciliation — auto-links manually-posted comments to approved drafts (3-pass matching: exact body 98%, fuzzy 85%+, thread+timing 75%).

### Layer 7: Evaluation and Adaptation

**Purpose:** Close the loop. Update system behavior based on observed outcomes.

| Mechanism | What it updates | Frequency |
|-----------|----------------|-----------|
| Feedback loop | EPG subreddit weights, approach effectiveness | Daily 02:00 |
| Phase evaluation | Avatar phase (promotion/demotion) | Daily 06:00 |
| Learning loop | Generation prompts (few-shot injection) | On each human edit |
| Risk scoring | Subreddit risk profiles | Weekly |
| Emotional profiling | Subreddit tone models + avatar compatibility | Weekly |

---

## 6. Safety Architecture

### 6.1 Nine Posting Safety Gates (Sequential)

| # | Gate | Blocks if |
|---|------|-----------|
| 0 | POSTING_DISABLED env var | Server-level kill (immutable at runtime) |
| 1 | auto_posting_enabled setting | Admin disabled auto-posting |
| 2 | posting_mode check | Avatar not in "auto" mode |
| 3 | is_frozen check | Avatar frozen (manual or auto) |
| 4 | health check | Shadowbanned or suspended |
| 5 | Phase 0 exclusion | Mentor avatars never auto-post |
| 6 | Daily cap | Budget exhausted: min(phase_limit, cap) |
| 7 | Proxy configured | No proxy when required |
| 8 | User-agent configured | Missing browser fingerprint |
| 9 | /24 subnet consistency | IP range mismatch |

### 6.2 Content Safety

| Gate | Function |
|------|----------|
| Phase gate | No brand mentions in Phase 1 (zero tolerance) |
| Brand ratio | Max % brand mentions per avatar per week |
| Promotional detection | Blocks overt advertising language |
| Hot thread filter | Skip >200 ups when avatar karma <100 in sub |
| Link/video filter | Skip posts with external URLs |
| Fitness gate | Subreddit-specific eligibility (karma, age, frequency) |

### 6.3 Kill Switch Hierarchy

- ENV level: POSTING_DISABLED=true (only changed via server SSH)
- DB level: pipeline_enabled, generation_enabled, scrape_enabled, auto_posting_enabled, email_tasks_enabled
- Entity level: avatar.is_frozen, client.is_active

### 6.4 Avatar Phase System

- Phase 0 (Mentor) — excluded from ALL automation, manual only
- Phase 1 (Warming) — hobby pipeline only, 1-3/day, zero brand
- Phase 2 (Seeding) — professional + hobby, external citations, no direct brand
- Phase 3 (Integration) — brand allowed (ratio-gated)
- Expert (score > 75) — quality over quantity, AEO-optimized content

**Demotion:** Shadowban > Phase 1. Survival rate <70% (7d, min 5 samples) > current-1. Karma avg < -2 (14d) > current-1.

---

## 7. Dual Pipeline Architecture

| Attribute | Professional Pipeline | Hobby Pipeline |
|-----------|----------------------|----------------|
| Target | Client business goals | Avatar warming/credibility |
| Phase | 2+ only | 1+ (all avatars) |
| Scraping | queue_tick > subreddits table | scrape_hobby_subreddits > PRAW |
| Storage | reddit_threads | hobby_subreddits |
| Scoring | Smart Scoring (Claude) | None (all eligible) |
| Generation | Claude Sonnet | Gemini Flash |
| Output | 5-15 drafts/day/avatar | 1-3 drafts/day/avatar |
| Brand content | Phase 2: external. Phase 3: direct | Never |

**Critical implication:** When avatar is demoted Phase 2 to 1, professional pipeline halts entirely. Only hobby (1-3/day) continues. ~80% output reduction by design.

---

## 8. Economic Model

### 8.1 Cost Structure (10 clients)

| Cost center | Monthly | % |
|-------------|---------|---|
| LLM APIs (Claude Sonnet + Gemini Flash) | $336 | 93% |
| Infrastructure (DO droplet + Docker) | $27 | 7% |
| **Total opex** | **$363** | 100% |

### 8.2 Unit Economics

| Metric | Value |
|--------|-------|
| Cost per client per day | $1.17 (LLM only) |
| Cost per generated comment | ~$0.04 (Claude Sonnet) |
| Cost per scored thread | ~$0.0003 (Gemini Flash) |
| Revenue per client (avg) | $500/mo |
| Gross margin | >90% at all scales |

### 8.3 Margin at Scale

| Clients | Total cost/mo | Revenue/mo | Margin |
|---------|--------------|------------|--------|
| 3 | $132 | $1,500 | 91% |
| 10 | $378 | $5,000 | 92% |
| 50 | $1,809 | $25,000 | 93% |
| 100 | $3,640 | $50,000 | 93% |

---

## 9. Temporal Model

### Daily Timeline (Asia/Jerusalem)

- 01:00 Performance metrics aggregation
- 02:00 Feedback loop (outcome > model correction)
- 05:20 Profile analytics snapshots
- 06:00 Phase evaluation (promotion/demotion)
- 06:30 CQS batch check (auto-freeze on lowest)
- 07:30 Health check #1 (shadowban/suspension)
- 07:45 Hobby scraping (before EPG)
- 08:00 **PIPELINE RUN #1** (score > generate > posts)
- 08:15 EPG build + generate
- 12:15 Karma outcome check (4h window)
- 13:30 Health check #2
- 13:45 Hobby scraping
- 14:00 **PIPELINE RUN #2** (score > generate > posts)
- 14:15 EPG build + generate
- 18:15 Karma outcome check
- 23:30 Expire overdue execution tasks

### Continuous Tasks

| Task | Interval |
|------|----------|
| queue_tick (scrape scheduling) | 60s |
| system_heartbeat | 60s |
| execute_pending_posts | 5 min |
| dispatch_due_email_tasks | 5 min |
| karma tracking | 4h |
| outcome snapshots | 4h |

### Weekly (Sunday)

- 03:00 Evergreen content harvest
- 04:00 Continuous discovery (market research)
- 04:30 Subreddit emotional profile refresh
- 05:00-05:30 Rule extraction + moderation + risk scoring

---

## 10. Observability

### Data Collection

| Model | Captures |
|-------|----------|
| ActivityEvent | Pipeline actions (scrape, score, generate, post) |
| PostingEvent | Every posting attempt (IP, proxy, UA, result, duration) |
| AIUsageLog | Token usage + cost per LLM call |
| KarmaSnapshot | Comment karma at 4h/24h/48h/7d |
| DeliveryAttempt | Email delivery audit |
| ScrapeLog | Per-subreddit metrics |
| AuditLog | Admin/user actions |

### Alert System

| Alert | Severity |
|-------|----------|
| Worker offline (heartbeat expired) | Critical |
| Kill switch active | High |
| Frozen avatars >30% | High |
| Stale scrapes >12h | Medium |
| Trial expiring <3d | Medium |
| Paying client 0 posts in 7d | High |

### Traceability

Full lifecycle per comment: Thread > Score > Draft > EPGSlot > ExecutionTask > PostingEvent > KarmaSnapshot[]

---

## 11. Security

| Domain | Implementation | Status |
|--------|---------------|--------|
| Authentication | JWT (python-jose + passlib) | Production |
| Authorization | 7 roles + permission guards + query scoping | Production |
| Data isolation | Client-scoped queries at ORM layer | Production |
| Credential encryption | Fernet AES-128-CBC | Production |
| HTTP headers | X-Frame-Options, HSTS, nosniff | Production |
| Rate limiting | 5 auth/15min/IP + 100 req/60s/IP | Production |
| Session timeout | 10-min auto-logout | Production |
| LLM isolation | Runtime assertions | Production |
| GDPR erasure | NOT IMPLEMENTED | Gap |
| Key rotation | NOT IMPLEMENTED | Gap |

---

## 12. Gaps and Risks

### Architecture Gaps

| # | Gap | Severity | Impact |
|---|-----|----------|--------|
| 1 | No idempotency keys | Medium | Duplicate posting on retry |
| 2 | No cross-avatar dedup | Medium | Two avatars on same thread |
| 3 | EPG rebuild race condition | Medium | Duplicate slots |
| 4 | No adversarial adaptation | High | Reddit changes undetected |
| 5 | No knowledge freshness | Medium | Stale strategies |
| 6 | No formal SLI/SLO | Medium | Health unmeasurable |
| 7 | No GDPR erasure | Medium | Compliance risk |
| 8 | Single-server | High | No failover |
| 9 | No simulation mode | Low | Cannot test safely |

### Operational Risks

| Risk | Mitigation | Residual |
|------|-----------|----------|
| Reddit enforcement | Phase system + cadence | Medium-High |
| LLM outage | LiteLLM fallback | Low |
| Server failure | Weekly backups | Medium |
| Mass avatar ban | Isolation | Medium |
| Cost spike | Budget + governor | Low |

---

## 13. System Invariants

1. No content posted without human approval (unless explicit auto-approve)
2. No brand mentions in Phase 1 (enforced, not advisory)
3. Client data isolation (A cannot see B through any path)
4. Freeze = immediate halt (no queued bypass)
5. Kill switch = instant global stop
6. Daily cap = hard limit (never exceeded)
7. Phase gates are earned (promotion requires metrics)

---

## 14. Competitive Position

| RAMP Property | vs Generic Posters | vs Thread Finders | vs Agencies |
|---------------|-------------------|-------------------|-------------|
| Persona depth | Unique | Unique | Comparable |
| Phase safety | Unique | Unique | Unique |
| Self-learning | Unique | Unique | Unique |
| AEO/GEO | Unique | Unique | Unique |
| Execution abstraction | Both | RAMP | Both |
| Scalability | RAMP | Both | RAMP |
| Outcome tracking | Unique | Unique | Unique |

**Moat:** After 6 months, avatar learned patterns + karma + community standing = unreplicable.

---

## 15. Maturity

| Capability | Level |
|------------|-------|
| Core pipeline | Production |
| Planning (EPG 2.0) | Production |
| Human gate + learning | Production |
| Execution delivery | Production |
| Signal collection | Production |
| Adaptation | Production |
| Safety | Production |
| Observability | Adequate |
| Disaster recovery | Basic |
| Horizontal scaling | Not ready |

---

## 16. Audit Answers Summary

| Priority | Question | Status |
|----------|----------|--------|
| 1 | Layer protocol | Answered (Celery async, DB state) |
| 2 | Adaptation mechanism | Answered (rule-based + patterns + stats, no ML) |
| 3 | Entity identification | Answered (UUID v4, FK cascade) |
| 4 | State machines | Answered (3 FSMs: Draft, Slot, Task) |
| 5 | External contracts | Answered (PRAW 60/min, Redis limiter) |
| 6 | Credentials | Answered (Fernet AES-128, no rotation) |
| 7 | SLI monitoring | GAP (no formal SLI/SLO) |
| 8 | Integration tests | Partial (50+ test files, no full E2E) |
| 9 | CI/CD | Basic (rsync + docker rebuild) |
| 10 | Cost per operation | Answered ($1.17/client/day) |

---

## 17. Recommendations

### Before 10 Clients (Immediate)

1. Proxy integration (residential IP per avatar)
2. Idempotency keys
3. Cross-avatar deduplication
4. Formal SLI/SLO definitions

### Before 50 Clients

5. AI-Native Expert system (spec ready)
6. Adversarial detection layer
7. Managed DB migration
8. GDPR compliance

### Before 100 Clients

9. Horizontal scaling (SQS + Valkey)
10. Stripe billing
11. Agency white-label
12. Key rotation

---

## 18. Verdict

RAMP is architecturally sound for 3-10 clients. The closed-loop design works and compounds value.

**Strengths:** Safety (9 gates + phases), self-learning moat, >90% margins, human-in-the-loop enforced architecturally.

**Risks:** Single-server, no adversarial adaptation, no idempotency, GDPR gap.

**Readiness:** Gaps are operational and compliance, not architectural. Core behavioral loop is production-proven.

---

*Generated from live codebase analysis, June 25, 2026.*
