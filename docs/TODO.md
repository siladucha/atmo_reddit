# RAMP — Development Backlog

_Last updated: 2026-05-21_

---

## 🎯 Goal: Exit to Sales

Everything below is prioritized by one question: **what blocks the next sale?**

---

## Sprint Status

| Sprint | Dates | Focus | Status |
|--------|-------|-------|--------|
| Sprint 1 | May 14–20 | Deploy + XM Cyber validation | ✅ Done |
| Sprint 2 | May 21–28 | Client Portal (7-day sprint) | 🔲 Current |
| Sprint 3 | May 29–Jun 4 | Portal Polish + Settings | 🔲 Planned |

---

## 🔴 P0 — Blocks First Sale

These items must be done before Tzvi can close a deal.

### 1. Flutter Mobile App (Posting)
**Spec:** `.kiro/specs/mobile-posting-app/` (requirements ✅, design ✅, tasks ✅)
**Effort:** Max builds separately (parallel)
**Why:** Without this, posting is manual copy-paste (2-5 min each). Mobile app = 15-30 sec per post.
**Owner:** Max (Flutter/Dart)

| Phase | Tasks | Status |
|-------|-------|--------|
| Core | Login, queue screen, detail screen, post confirmation | 🔲 In progress |
| Push | FCM notifications on draft approval | 🔲 |
| Stats | Posting stats per avatar owner | 🔲 |

### 2. Client Portal (Client-Facing UI)
**Spec:** `.kiro/specs/client-portal-redesign/` (requirements ✅, design ✅, tasks ✅)
**Effort:** 5-6 days (P0 phase)
**Why:** This is what Tzvi shows prospects. Current UI is admin-only. Clients need their own polished portal.

| Phase | Tasks | Status |
|-------|-------|--------|
| P0: Sales-Ready | Design tokens, sidebar, home screen, review queue, safety blocks, toast, API allowlist | 🔲 |
| P1: Client Experience | Avatars screen, banners, filters, settings, empty states, onboarding wizard | 🔲 |
| P2: Deferred | Insights, mobile, batch approve, upsell | ⏸ Later |

### 3. Timing Jitter (Anti-Detection)
**Spec:** `.kiro/specs/platform-readiness/` (requirements ✅, design ✅, tasks ✅)
**Effort:** 2.5 days
**Why:** Fixed intervals = detectable patterns = Reddit bans. Must randomize before running real client campaigns.

| Task | Status |
|------|--------|
| Jitter service (TimingWindow, CSPRNG) | 🔲 |
| Comment gap jitter (replace fixed constant) | 🔲 |
| Scraping interval jitter (vary per subreddit) | 🔲 |
| Daily activity window (per-avatar, varies daily) | 🔲 |
| SystemSettings seed + validators | 🔲 |
| Tests | 🔲 |

### 4. Production Deployment
**Spec:** None needed (operational task)
**Effort:** 1 day
**Why:** Can't demo without a live URL.

| Task | Status |
|------|--------|
| Domain + SSL (Let's Encrypt) | 🔲 |
| Docker Compose prod config verified | 🔲 |
| Nginx routing (marketing + app) | ✅ Done |
| Health check endpoint | ✅ Done |

### 5. XM Cyber Validation
**Spec:** None (manual task with Tzvi)
**Effort:** 0.5 day
**Why:** First real client data test. Proves pipeline works end-to-end.

| Task | Status |
|------|--------|
| Load XM Cyber subreddits + keywords | 🔲 |
| Run scoring pipeline on real data | 🔲 |
| Generate sample drafts for Tzvi review | 🔲 |
| Validate quality with Tzvi | 🔲 |

---

## 🟡 P1 — Needed Within 2 Weeks of First Sale

### 6. Comment Performance Tracking
**Spec:** `.kiro/specs/comment-performance-tracking/` (requirements ✅, design ✅, tasks ✅)
**Effort:** 3-4 days
**Why:** Proves ROI to clients. "Your comments earned X upvotes, Y replies."

### 7. Subreddit Intelligence (Rule Parsing)
**Spec:** Part of `.kiro/specs/platform-readiness/` (Requirements 4-7, design deferred)
**Effort:** 3-4 days
**Why:** Comments get removed by mods when they violate subreddit rules. Need to parse rules and inject into generation prompt.

### 8. Budget Engine (Daily Limits)
**Spec:** Not yet created
**Effort:** 2 days
**Why:** Prevents over-posting. Clients on Seed plan shouldn't get 100 comments/day.

### 9. Cross-Avatar Deduplication
**Spec:** Not yet created
**Effort:** 1 day
**Why:** Two avatars commenting on the same thread looks suspicious.

---

## 🟢 P2 — Before 10 Clients (June-July 2026)

| Item | Spec Status | Effort |
|------|-------------|--------|
| Context Assembly Service (unified LLM context) | Req in platform-readiness | 3 days |
| Conversation Memory (avatar remembers past comments) | Req in platform-readiness | 2 days |
| Pagination on all list endpoints | No spec needed | 2 days |
| Idempotency keys (prevent duplicate tasks) | No spec needed | 1 day |
| Prompt versioning (DB/files, A/B testing) | No spec needed | 2 days |
| Strategy Questions feedback loop | No spec needed | 2 days |
| Queue observability (DLQ + metrics) | No spec needed | 1 day |
| Client Portal P1 (avatars, settings, wizard) | In client-portal-redesign | 4-5 days |

---

## ⚪ P3 — Before 100 Clients (Q3-Q4 2026)

| Item | Trigger |
|------|---------|
| Trust engine (per-avatar decay scores) | 10+ clients |
| Billing integration (Stripe) | Self-service launch |
| Horizontal scaling (separate worker pools) | CPU > 80% sustained |
| SQS + Valkey migration | 100+ avatars OR enterprise |
| Client self-service portal | 5+ self-service clients |
| Vector memory (long-term avatar context) | After learning loop proves ROI |
| AWS migration (EC2 → ECS, RDS) | Enterprise requirement |
| White-label (custom domain, branding) | Agency demand |
| PDF reports (auto-generated) | Client request |
| Agency multi-tenant workspace | 3+ agency clients |

---

## ✅ Done (Completed Specs)

| Spec | Completed |
|------|-----------|
| RBAC & Client Data Isolation | May 13 |
| Self-Learning Loop | May 11 |
| Avatar Analysis | May 10 |
| Avatar Subreddit Presence | May 10 |
| Thread Liveness Protection | May 8 |
| System Topology Dashboard | May 7 |
| Shadowban Detection | May 10 |
| MVP Hardening Sprint 1 | May 11 |
| Comment Approach Diversity | May 14 |
| Repurpose Scraping | May 14 |
| Marketing Site Roadmap | May 15 |
| CQS Automated Monitoring | May 12 |
| Mentor Phase | May 12 |
| Avatar Intelligence UI | May 12 |
| Scraping Architecture | May 11 |

---

## Execution Order (Recommended)

```
Week 1 (May 21-25):
  Day 1-2: Timing Jitter (2.5 days) ← smallest, unblocks safe operation
  Day 2-3: Telegram Bot Phase 1 (models + bot setup + handlers)
  Day 4-5: Telegram Bot Phase 2 (notifications) + Phase 3 (stats)

Week 2 (May 26-30):
  Day 1-3: Client Portal P0 (tokens + sidebar + home + review queue)
  Day 4-5: Client Portal P0 (safety blocks + toast + polish)

Week 3 (Jun 1-4):
  Day 1: Production deployment (domain + SSL)
  Day 2: XM Cyber validation with Tzvi
  Day 3-4: Comment Performance Tracking (proves ROI)
```

**Total to first sale: ~12-14 working days**

---

## Architecture Diagrams

### Comment Generation Pipeline

```
Reddit Post → Score (Gemini Flash) → Thread alive? → Persona Router → Strategy-Aware Generation (Claude Sonnet) → Human Review → Telegram Bot → Posted
                                                                              ↑
                                                              Self-learning loop (few-shot + patterns)
```

### Safety Layer (4 layers)

```
Layer 1: Content Safety (brand ratio, phase gate, promotional detection)
Layer 2: Avatar Health (shadowban, CQS, karma tracking)
Layer 3: Operational Controls (kill switch, freeze, liveness, locks, JITTER)
Layer 4: Access Control (6-role RBAC, query scoping, LLM isolation)
```

### Cost Structure (10 clients)

```
LLM APIs (Claude + Gemini):  93%  ($351/mo)
AWS/DO Infrastructure:         7%  ($27/mo)
─────────────────────────────────────────
Total:                              $378/mo
Revenue (avg $500/client):        $5,000/mo
Margin:                              92%
```

---

## Future: Provider-Level Request Queues (added June 17, 2026)

**Problem:** When 100+ clients trigger GEO/scoring/generation simultaneously, all requests hit the same provider API at once. This causes:
- 429 rate limits from Gemini/Anthropic/Perplexity
- Cascading failures (one provider down → all clients affected)
- No fairness — first client to trigger gets all the capacity

**Solution: Per-provider request queues with backpressure**

```
Client triggers GEO → Celery task → Provider Queue (Redis sorted set) → Worker pool → API call
                                         ↓
                              - Max concurrency per provider (e.g. Gemini: 10 parallel)
                              - Fair scheduling (round-robin across clients)
                              - Circuit breaker (5 consecutive 503 → pause 60s)
                              - Overflow → next provider in fallback chain
```

**Architecture:**
- One Redis sorted set per provider: `provider_queue:gemini`, `provider_queue:perplexity`, `provider_queue:anthropic`
- Worker pool per provider (configurable concurrency: 5-20 parallel calls)
- Circuit breaker state in Redis: `provider_circuit:gemini` = {failures: 5, open_until: timestamp}
- Client-level fairness: weighted round-robin based on plan tier
- Overflow routing: if queue depth > threshold → spill to fallback provider

**When to build:** Before 50+ clients OR when provider rate limits become weekly occurrence.

**Current mitigation (good enough for 10 clients):**
- GeoRateLimiter (per-provider sliding window in Redis)
- Retry with exponential backoff inside tasks
- Fallback chain in call_llm() (Perplexity → Gemini → Sonnet)
- Per-query circuit breaker in GEO batch (consecutive_failures threshold)

