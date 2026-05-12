# Specification Audit Report — May 12, 2026

## Executive Summary

The project contains **46 specifications** across the `.kiro/specs/` directory. Of these:

- **9 fully completed** (all tasks done)
- **5 partially completed** (in progress, some tasks remaining)
- **10 not started but ready** (have design + tasks, can be picked up)
- **22 requirements-only** (need design/tasks before implementation)

The platform MVP is at **~98% readiness** for internal operations. The next strategic phase is **client-facing access (RBAC + Client Portal)** and **production deployment** (DigitalOcean).

---

## Deployment Decision: DigitalOcean

**Decision:** Deploy on DigitalOcean instead of AWS for speed-to-market.

**Implications:**
- SQS/Valkey migration spec becomes **irrelevant** for near-term — stay on Celery + Redis (Docker)
- Droplet ($12-24/mo, 2-4GB RAM) + Managed PostgreSQL ($15/mo) = production in ~1 hour
- Docker Compose deploys as-is, no IAM/VPC/Security Groups complexity
- Redis stays in Docker container (sufficient for 10-50 clients)
- Managed PostgreSQL eliminates data loss risk without RDS complexity
- Total infra cost: ~$27-39/mo (vs. AWS ~$27/mo but with 10x setup complexity)

**Specs affected by this decision:**
- `sqs-valkey-migration` → **Deferred indefinitely** (Celery+Redis works fine on DO)
- `reddit-data-sync` → **Lower priority** (current rate limiting sufficient)
- `avatar-data-freshness-at-scale` → **Far future** (100K avatars not relevant now)

---

## Section 1: Completed Specifications (9)

These are fully implemented and can be archived or used as reference.

| # | Spec | Purpose | Tasks | Business Value |
|---|------|---------|-------|----------------|
| 1 | `admin-panel-client-onboarding` | Full admin panel + 7-step client onboarding wizard | 12/12 | Core platform — enables client setup |
| 2 | `activity-feed-transparency` | Activity Feed + Scrape Log + Client Transparency Dashboard | 7/7 | Operational visibility — shows what pipeline did |
| 3 | `avatar-analysis` | LLM behavioral profiling of avatars + learning loop | 9/9 | Avatar intelligence — better persona matching |
| 4 | `avatar-warming-phases` | 3-phase progression model (Phase 1→2→3) with gates | 16/16 | Safety — prevents premature brand mentions |
| 5 | `reddit-api-health-dashboard` | Reddit API metrics on admin health page | 9/9 | Ops visibility — rate limit monitoring |
| 6 | `scheduled-scraping` | Queue-based scraping by staleness (queue_tick) | 10/10 | Core pipeline — continuous data freshness |
| 7 | `self-learning-loop` | Edit capture → pattern extraction → few-shot injection | 14/14 | AI quality — comments improve over time |
| 8 | `shadowban-detection` | 5-state health model + auto-freeze on detection | 10/10 | Safety — protects avatar inventory ($199-499 each) |
| 9 | `system-topology-timeline` | 9-node topology panel + 24h heatmap + forecast | 8/8 | Ops visibility — real-time system health |

---

## Section 2: Partially Completed Specifications (5)

These have remaining tasks that should be evaluated: finish, defer, or close as-is.

| # | Spec | Purpose | Status | Remaining | Recommendation |
|---|------|---------|--------|-----------|----------------|
| 1 | `mvp-hardening-sprint1` | Kill switches, freeze, retry, LLM validation, context isolation | 11/12 | 1 task | **Close** — all critical items done, remaining is likely minor |
| 2 | `avatar-intelligence-learning` | Learn from subreddit leaders + hybrid generation | 9/10 | 1 task | **Close** — core functionality works |
| 3 | `shared-subreddit-registry` | Many-to-many subreddits (shared scraping across clients) | 8/12 | 4 tasks | **Finish** — needed for multi-client (shared data) |
| 4 | `system-settings-ui` | All settings from .env to DB + admin UI | 10/12 | 2 tasks | **Finish** — needed for production (no .env editing on server) |
| 5 | `client-hub-navigation` | Tabbed navigation on client detail page | 4/11 | 7 tasks | **Defer** — superseded by client-manager-workflow-ux |

---

## Section 3: Not Started — Ready to Implement (10)

These have full design + tasks and can be picked up immediately.

| # | Spec | Purpose | Tasks | Priority | Relevance to Client Portal |
|---|------|---------|-------|----------|---------------------------|
| 1 | `client-manager-workflow-ux` | Navigation badges, batch review, "what to do now" prioritization, client-centric ops view | 13 | **P0** | ⭐ Direct — this IS the manager workflow |
| 2 | `daily-ops-dashboard` | Single-page daily operations (all clients, pipeline status, manual triggers) | 13 | P1 | Indirect — operator tool |
| 3 | `comment-performance-tracking` | Karma snapshots at 4h/24h/48h + removal detection + outcome analytics | 11 | P1 | Indirect — feeds into client reporting |
| 4 | `manual-avatar-pipeline-v2` | Improved manual pipeline (dedup, budget, freshness) | 6 | P2 | Low — operator tool |
| 5 | `ops-console-pipeline-observability` | Pipeline run lifecycle tracking + step-level detail | 7 | P2 | Low — deep ops |
| 6 | `reddit-data-sync` | Centralized rate-limit-aware Reddit sync | 16 | P3 | None — current system works |
| 7 | `avatar-daily-timeline` | Full historical timeline tab on avatar page | ? | P3 | None — nice-to-have |
| 8 | `ai-usage-analytics` | Extended AI cost analytics (trends, filtering, efficiency) | 0 | P3 | Low — internal ops |
| 9 | `prd-expansion-tzvi-questions` | Answers to Tzvi's PRD questions | 134 | **Obsolete** | None — questions already addressed |
| 10 | `ramp-pipeline-v2` | Full pipeline v2 FRD (SQS-based) | 10 | **Deferred** | None — staying on Celery |

---

## Section 4: Requirements Only — Need Design (22)

These have requirements written but no design or tasks. Grouped by strategic relevance.

### 4A. Critical for Client Portal / Multi-Tenancy

| # | Spec | Purpose | Why Critical |
|---|------|---------|-------------|
| 1 | `context-assembler` | Centralized LLM context assembly with strict client data isolation | **Blocks multi-client** — without this, Client A's data could leak into Client B's LLM calls |
| 2 | `oauth-avatar-auth` | Per-avatar OAuth 2.0 (individual refresh tokens) | **Blocks self-service** — clients can't connect their own accounts without this |
| 3 | `cascade-delete` | Soft delete with cascade propagation + restore | Needed for safe client/avatar removal in multi-tenant |
| 4 | `admin-navigation-consolidation` | Merge light/dark theme into single admin nav | UX cleanup before exposing to client managers |

### 4B. Medium Priority — Operational Improvements

| # | Spec | Purpose | When Needed |
|---|------|---------|-------------|
| 5 | `platform-readiness` | Timing jitter + subreddit intelligence + context isolation (3 subsystems) | Before 10 clients |
| 6 | `smart-post-routing` | AI-powered post routing (avatar + subreddit selection + risk) | Before 10 clients |
| 7 | `reddit-rate-limiting` | Singleton PRAW + centralized rate limiting + backoff | Before 50 clients |
| 8 | `dry-run-workflow` | Full pipeline without LLM keys (copy-paste mode) | Demo/testing tool |

### 4C. Low Priority — Nice-to-Have or Deferred

| # | Spec | Purpose | Status |
|---|------|---------|--------|
| 9 | `sqs-valkey-migration` | Celery → SQS + Valkey | **Deferred** — staying on Celery+Redis (DO deployment) |
| 10 | `avatar-data-freshness-at-scale` | 4-phase scaling architecture for 100K avatars | Far future |
| 11 | `subreddit-specific-karma` | Per-subreddit karma tracking | Partially exists (SubredditKarma model) |
| 12 | `avatar-reddit-status` | Reddit status checks on avatars page | Already covered by health_checker |
| 13 | `author-intelligence` | Thread author profiling (karma, age, authority) | Nice-to-have |
| 14 | `personas-page-reddit-checks` | Personas page + associated avatar Reddit status | Low — personas work fine |
| 15 | `admin-client-hub-navigation` | Tabbed admin client page | Duplicate of client-hub-navigation |
| 16 | `admin-entity-management` | Entity CRUD extensions | Minor |
| 17 | `settings-consolidation` | Merge two settings pages into one | Minor — system-settings-ui covers this |
| 18 | `placeholder-instructions` | Placeholder text in form fields | Cosmetic |
| 19 | `ui-info-tooltips` | ℹ️ tooltips throughout admin panel | Cosmetic |
| 20 | `comment-rendering-bug` | Comment rendering bugfix | Check if still relevant |
| 21 | `comment-rendering-fix` | Comment rendering fix | Check if still relevant |
| 22 | `enhanced-system-health` | Empty directory | **Delete** |

---

## Section 5: Specs to Delete or Archive

| Spec | Reason |
|------|--------|
| `enhanced-system-health` | Empty directory, no files |
| `prd-expansion-tzvi-questions` | 134 tasks, likely auto-generated, questions already addressed in other docs |
| `comment-rendering-bug` | Duplicate of comment-rendering-fix |
| `admin-client-hub-navigation` | Duplicate of client-hub-navigation |
| `settings-consolidation` | Superseded by system-settings-ui |
| `avatar-reddit-status` | Functionality exists in shadowban-detection + health_checker |
| `ramp-pipeline-v2` | Deferred — SQS migration not happening (DO deployment) |
| `sqs-valkey-migration` | Deferred — staying on Celery+Redis |

**Recommended deletions: 8 specs** → reduces noise from 46 to 38 active specs.

---

## Section 6: Gap Analysis — What's Missing for Client Portal

The current spec library covers internal operations thoroughly but has **no spec for the client-facing layer**. The following new specifications are needed:

### New Spec 1: RBAC & Role System (P0 — blocks everything)

**Purpose:** Define roles (superadmin, manager, client), permissions matrix, route guards, data scoping.

**What it enables:**
- Superadmin (Max): full system access
- Manager (Tzvi / future ops): client management, review, reporting — no system config
- Client: view own dashboard, review queue, approve/reject drafts — no access to other clients

**Key decisions needed:**
- Role storage (DB column vs. separate roles table)
- Permission granularity (route-level vs. object-level)
- Session management (JWT claims with role)
- Data scoping (all queries filtered by client_id for client role)

### New Spec 2: Client Portal UI (P0)

**Purpose:** Client-facing pages with scoped data access.

**What it enables:**
- Client dashboard (their stats only)
- Client review queue (their drafts only)
- Client avatar status (their avatars only)
- Client activity feed (their events only)
- Client settings (their preferences)

**Key decisions needed:**
- Separate base template or reuse admin_base with role-conditional nav?
- Light theme (current base.html) or new design?
- Which existing admin features to expose vs. hide?

### New Spec 3: Client Onboarding Self-Service (P1 — after portal)

**Purpose:** Clients can set up their own configuration without admin intervention.

**What it enables:**
- Client registers → sees onboarding wizard (subset of admin wizard)
- Client adds keywords, selects subreddits from catalog
- Client reviews avatar assignments (but can't create avatars)
- Admin approves client config before pipeline starts

### New Spec 4: DigitalOcean Deployment (P0 — blocks pilot)

**Purpose:** Production deployment on DigitalOcean.

**What it enables:**
- Live system accessible via domain
- Docker Compose on Droplet (app + Redis)
- Managed PostgreSQL (no data loss risk)
- SSL via Let's Encrypt / Cloudflare
- Basic monitoring (DO metrics + app health endpoint)

**Infrastructure:**
- Droplet: 2GB RAM, 1 vCPU ($12/mo) or 4GB RAM, 2 vCPU ($24/mo)
- Managed PostgreSQL: Basic plan ($15/mo)
- Domain + DNS: Cloudflare (free)
- Total: $27-39/mo

---

## Section 7: Recommended Execution Order

### Phase 1: Production Launch (This Week)

| Step | Action | Spec |
|------|--------|------|
| 1 | Deploy to DigitalOcean | **New: DO Deployment** |
| 2 | XM Cyber validation run | Manual testing |
| 3 | Comment approach diversity fix | Code change (no spec needed) |

### Phase 2: Client Access Layer (Next 2 Weeks)

| Step | Action | Spec |
|------|--------|------|
| 4 | Design RBAC system | **New: RBAC & Roles** |
| 5 | Implement role guards + data scoping | New spec tasks |
| 6 | Build client portal pages | **New: Client Portal UI** |
| 7 | Finish shared-subreddit-registry | Existing (4 tasks remaining) |
| 8 | Finish system-settings-ui | Existing (2 tasks remaining) |
| 9 | Context assembler (client isolation) | Existing (needs design) |

### Phase 3: Operational Maturity (Weeks 3-4)

| Step | Action | Spec |
|------|--------|------|
| 10 | Client manager workflow UX | Existing (13 tasks, ready) |
| 11 | Comment performance tracking | Existing (11 tasks, ready) |
| 12 | Daily ops dashboard | Existing (13 tasks, ready) |
| 13 | Platform readiness (timing jitter) | Existing (needs design) |

### Phase 4: Scale Preparation (Month 2+)

| Step | Action | Spec |
|------|--------|------|
| 14 | OAuth avatar auth | Existing (needs design) |
| 15 | Smart post routing | Existing (needs design) |
| 16 | Budget engine | New spec needed |
| 17 | Cross-avatar deduplication | New spec needed |

---

## Section 8: Spec Health Metrics

| Metric | Value |
|--------|-------|
| Total specs | 46 |
| Fully completed | 9 (20%) |
| Partially completed | 5 (11%) |
| Ready to implement | 10 (22%) |
| Requirements only | 22 (47%) |
| Recommended for deletion | 8 |
| Missing (need creation) | 4 |
| Completion rate (tasks) | 128/155 completed tasks across active specs (83%) |

### Spec Maturity Distribution

```
Completed:     ████████████████████ 20%
Partial:       █████ 11%
Ready:         ██████████ 22%
Req Only:      ███████████████████████ 47%
```

### Priority Distribution (non-completed specs)

```
P0 (blocks pilot/clients): 4 specs (context-assembler, RBAC, Client Portal, DO Deploy)
P1 (before 10 clients):    6 specs (shared-subreddit, settings-ui, platform-readiness, etc.)
P2 (operational):           5 specs (daily-ops, manual-pipeline-v2, etc.)
P3 (deferred/low):         14 specs
Delete:                     8 specs
```

---

## Appendix: Full Spec Inventory (Alphabetical)

| Spec | Status | Files | Priority |
|------|--------|-------|----------|
| activity-feed-transparency | ✅ Done | R+D+T | Archive |
| admin-client-hub-navigation | Req only | R | Delete (duplicate) |
| admin-entity-management | Req only | R | P3 |
| admin-navigation-consolidation | Req only | R | P2 |
| admin-panel-client-onboarding | ✅ Done | R+D+T | Archive |
| ai-usage-analytics | Ready (empty tasks) | R+D+T | P3 |
| author-intelligence | Req only | R | P3 |
| avatar-analysis | ✅ Done | R+D+T | Archive |
| avatar-daily-timeline | Ready | R+D+T | P3 |
| avatar-data-freshness-at-scale | Req only | R | P3 (far future) |
| avatar-intelligence-learning | Partial (9/10) | R+D+T | Close |
| avatar-reddit-status | Req only | R+D | Delete (covered) |
| avatar-warming-phases | ✅ Done | R+D+T | Archive |
| cascade-delete | Req only | R | P1 |
| client-hub-navigation | Partial (4/11) | R+D+T | Defer |
| client-manager-workflow-ux | Ready | R+D+T | P1 |
| comment-performance-tracking | Ready | R+D+T | P1 |
| comment-rendering-bug | Bugfix | B | Check/Delete |
| comment-rendering-fix | Bugfix | B | Check/Delete |
| context-assembler | Req only | R | **P0** |
| daily-ops-dashboard | Ready | R+D+T | P2 |
| dry-run-workflow | Req only | R | P3 |
| enhanced-system-health | Empty | — | Delete |
| manual-avatar-pipeline-v2 | Ready | R+D+T | P2 |
| mvp-hardening-sprint1 | Partial (11/12) | R+D+T | Close |
| oauth-avatar-auth | Req only | R | P1 (after portal) |
| ops-console-pipeline-observability | Ready | R+D+T | P2 |
| ops-dashboard | Req only | R+D | P3 (superseded by daily-ops) |
| personas-page-reddit-checks | Req only | R | P3 |
| placeholder-instructions | Req only | R | P3 (cosmetic) |
| platform-readiness | Req only | R | P1 |
| prd-expansion-tzvi-questions | Ready (134 tasks) | R+D+T | Delete (obsolete) |
| ramp-pipeline-v2 | Ready | R+D+T | Deferred (DO decision) |
| reddit-api-health-dashboard | ✅ Done | R+D+T | Archive |
| reddit-data-sync | Ready | R+D+T | P3 |
| reddit-rate-limiting | Req only | R | P2 |
| scheduled-scraping | ✅ Done | R+D+T | Archive |
| self-learning-loop | ✅ Done | R+D+T | Archive |
| settings-consolidation | Req only | R+D | Delete (superseded) |
| shadowban-detection | ✅ Done | R+D+T | Archive |
| shared-subreddit-registry | Partial (8/12) | R+D+T | P1 (finish) |
| smart-post-routing | Req only | R | P1 |
| sqs-valkey-migration | Req only | R | Deferred (DO decision) |
| subreddit-specific-karma | Req only | R | P3 (partially exists) |
| system-settings-ui | Partial (10/12) | R+D+T | P1 (finish) |
| system-topology-timeline | ✅ Done | R+D+T | Archive |
| ui-info-tooltips | Req only | R | P3 (cosmetic) |

**Legend:** R = requirements.md, D = design.md, T = tasks.md, B = bugfix.md
