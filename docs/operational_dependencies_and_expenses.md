# RAMP Platform — Operational Dependencies & Expenses

**Date:** May 20, 2026  
**Prepared by:** Max Breger (CTO)  
**Purpose:** Full transparency on what the platform depends on and what it costs to run.

---

## 1. AI / LLM Dependencies

The platform relies on external AI model APIs for its core pipeline. No AI runs locally — all calls go to cloud providers.

### Active AI Providers

| Provider | Model | Used For | Pricing Model |
|----------|-------|----------|---------------|
| Google (Vertex / AI Studio) | Gemini 2.5 Flash Lite | Thread scoring, hobby comments | Pay-per-token |
| Anthropic | Claude Sonnet 4 | Comment generation, persona selection, comment editing, post drafts | Pay-per-token |

### AI Cost Per Client Per Day (standard volume)

| Operation | Model | Calls/day | Cost/call | Cost/day |
|-----------|-------|-----------|-----------|----------|
| Thread scoring | Gemini Flash | 20 | $0.0003 | $0.006 |
| Persona selection | Claude Sonnet | 15 | $0.020 | $0.30 |
| Comment generation | Claude Sonnet | 15 | $0.039 | $0.59 |
| Comment editing | Claude Sonnet | 15 | $0.018 | $0.27 |
| Hobby comments | Gemini Flash | 15 | $0.0003 | $0.005 |
| **Total per client** | | | | **$1.17/day** |

### Monthly AI Cost by Scale

| Clients | AI Cost/month | Notes |
|---------|--------------|-------|
| 1 | ~$35 | Minimum viable |
| 3 | ~$105 | Pilot phase |
| 10 | ~$351 | First growth target |
| 50 | ~$1,755 | Scales linearly |
| 100 | ~$3,510 | Still linear |

### AI Dependency Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Anthropic API outage | Generation stops | Retry with backoff (3 attempts, 60×2^n seconds) |
| Google API outage | Scoring stops | Same retry logic |
| Price increase | Margin compression | LiteLLM abstraction allows model swap in config |
| Rate limiting | Pipeline slows | Built-in rate limiter + queue-based processing |
| Model deprecation | Prompt rework needed | Pydantic schema validation catches output format changes |

### AI Routing Layer

- **LiteLLM** — unified API wrapper. Allows switching between providers (OpenAI, Anthropic, Google, etc.) by changing a config string. No vendor lock-in.

---

## 2. Server & Infrastructure Dependencies

### Current Production (DigitalOcean)

| Component | Spec | Cost/month |
|-----------|------|-----------|
| Droplet (app + DB + workers) | 2 vCPU, 4 GB RAM, 60 GB SSD | $23 |
| Weekly backups | Automated by DigitalOcean | Included |
| **Total** | | **$23/mo** |

**Location:** Frankfurt, Germany (FRA1)  
**Access:** `161.35.27.165:8000`  
**Stack:** Docker Compose (FastAPI + PostgreSQL + Redis + Celery)

### Planned AWS Migration (when needed)

| Component | Service | Cost/month |
|-----------|---------|-----------|
| Application server | EC2 t3.small (2 vCPU, 2 GB) | $20.43 |
| Task queue | AWS SQS Standard | $0.30 |
| Cache & locks | ElastiCache Serverless Valkey | $6.14 |
| Database (initial) | PostgreSQL in Docker on EC2 | $0 |
| Database (5+ clients) | RDS db.t4g.small | $24.00 |
| Static IP | Elastic IP | $3.65 |
| Storage | EBS 20 GB gp3 | $1.60 |
| Backups | S3 (~100 MB) | $0.02 |
| SSL certificates | ACM | $0 (free) |
| Monitoring | CloudWatch basic | $0 (free) |
| **Total (MVP)** | | **~$27/mo** |
| **Total (with RDS)** | | **~$54/mo** |

**Migration trigger:** Enterprise client requirement OR 100+ avatars OR ops burden > 4h/week.  
**AWS credits available:** $7,000 (covers ~2 years of operation).

---

## 3. External Service Dependencies

### Reddit API

| Item | Details | Cost |
|------|---------|------|
| Reddit API (PRAW) | OAuth2 app, 60 req/min | **Free** |
| Reddit accounts (avatars) | Pre-warmed accounts with karma | Acquisition cost (one-time) |

### Domain & Networking

| Item | Details | Cost/month |
|------|---------|-----------|
| Domain (TBD) | Not yet purchased | ~$12/year ($1/mo) |
| SSL certificate | Let's Encrypt or ACM | Free |
| Cloudflare (optional) | DNS + CDN + DDoS protection | Free tier |

### Telegram Bot API

| Item | Details | Cost |
|------|---------|------|
| Telegram Bot API | For posting workforce notifications | **Free** |
| Telegram bot hosting | Runs inside main app (webhook mode) | $0 (shared server) |

---

## 4. Development Tools (Monthly)

These are tools used to build and maintain the platform. Cost stays flat regardless of client count.

| Tool | Purpose | Cost/month |
|------|---------|-----------|
| Kiro IDE Pro | Primary AI coding environment | $39 |
| Claude Pro + API | Code generation, architecture, complex logic | $80–100 |
| Cursor Pro | Secondary AI coding tool | $20 |
| GPT Plus / API | Prompt engineering, alternative perspectives | $20 |
| Gemini API (dev) | Testing scoring prompts | $5–10 |
| Other dev tools | Linters, formatters, testing | $20 |
| **Total** | | **~$200–220/mo** |

---

## 5. Complete Monthly Expense Summary

### At Current Scale (pre-revenue, development + 1 test client)

| Category | Cost/month | % of total |
|----------|-----------|-----------|
| **AI Pipeline (production)** | $35–80 | 10–16% |
| **AI Pipeline (testing/calibration)** | $60–80 | 12–16% |
| **Server infrastructure** | $23 | 5% |
| **Development tools** | $200–220 | 44% |
| **Domain & networking** | $1–5 | 1% |
| **Contingency (10%)** | $35–45 | 9% |
| **TOTAL** | **~$400–500/mo** | 100% |

### At 3 Clients (pilot phase)

| Category | Cost/month |
|----------|-----------|
| AI Pipeline (production) | $105 |
| AI Pipeline (testing) | $40 |
| Server infrastructure | $27 |
| Development tools | $200 |
| Domain & networking | $5 |
| Contingency | $40 |
| **TOTAL** | **~$420/mo** |

### At 10 Clients (growth target)

| Category | Cost/month |
|----------|-----------|
| AI Pipeline (production) | $351 |
| AI Pipeline (testing) | $30 |
| Server infrastructure | $27–54 |
| Development tools | $200 |
| Domain & networking | $5 |
| Contingency | $65 |
| **TOTAL** | **~$680–710/mo** |

### At 50 Clients

| Category | Cost/month |
|----------|-----------|
| AI Pipeline (production) | $1,755 |
| Server infrastructure | $54–130 |
| Development tools | $200 |
| Domain & networking | $10 |
| Contingency | $200 |
| **TOTAL** | **~$2,220–2,300/mo** |

---

## 6. Revenue vs. Expenses — Margin Analysis

| Scale | Revenue/mo | Expenses/mo | Net Profit | Margin |
|-------|-----------|------------|-----------|--------|
| 0 clients (now) | $0 | $450 | -$450 | — |
| 1 client (Starter) | $799 | $480 | +$319 | 40% |
| 3 clients | $1,200–2,400 | $420 | +$780–1,980 | 65–83% |
| 10 clients | $5,000 | $700 | +$4,300 | 86% |
| 50 clients | $25,000 | $2,250 | +$22,750 | 91% |
| 100 clients | $50,000 | $4,200 | +$45,800 | 92% |

**Break-even:** 1 client on Starter plan ($799/mo) or 2 clients on Seed plan ($149×2 + managed upsell).

**Key insight:** Margins improve with scale because infrastructure costs are sub-linear while revenue is linear. AI costs scale linearly but remain a small fraction of per-client revenue.

---

## 7. Cost Distribution Visualization

### At 10 Clients

```
AI APIs (Claude + Gemini):     51%  ████████████████████████████
Development tools:             29%  ████████████████
Server infrastructure:          4%  ██
Testing & calibration:          4%  ██
Contingency:                    9%  █████
Domain & networking:            1%  █
```

### At 50 Clients

```
AI APIs (Claude + Gemini):     77%  ██████████████████████████████████████████
Server infrastructure:          5%  ███
Development tools:              9%  █████
Contingency:                    9%  █████
```

---

## 8. What Breaks If We Don't Pay

| Dependency | If unpaid | Impact | Recovery time |
|-----------|-----------|--------|---------------|
| Anthropic API | Generation stops | No new comments produced | Instant on payment |
| Google AI API | Scoring stops | No thread evaluation | Instant on payment |
| DigitalOcean / AWS | Server goes offline | Entire platform down | 1–4 hours |
| Domain registrar | Domain expires (30-day grace) | URL stops working | 1–24 hours |
| Dev tools (Kiro, Claude Pro) | Development slows 5–10× | No new features, slow bug fixes | Instant on payment |
| Reddit API | Free, no payment risk | — | — |
| Telegram API | Free, no payment risk | — | — |

---

## 9. Cost Optimization Already Applied

These decisions save $200+/mo compared to naive approaches:

| Optimization | Savings/mo |
|-------------|-----------|
| Gemini Flash for scoring (not Claude) | ~$150 |
| Docker PostgreSQL (not managed RDS) | $24 |
| SQS + Valkey Serverless (not Redis cluster) | $30 |
| Single instance (not ECS/Fargate) | $50 |
| LiteLLM direct API (not OpenRouter markup) | 10–15% on AI |
| Single-avatar clients skip persona selection | ~$30/client |
| Scoring volume cap (50 threads/run) | Prevents runaway costs |

---

## 10. Future Cost Triggers

| Event | New Expense | When Expected |
|-------|------------|---------------|
| Domain purchase | +$12/year | May 2026 |
| SSL (if not free ACM) | +$0–10/year | May 2026 |
| RDS migration | +$24/mo | At 5+ clients |
| Second server instance | +$15–30/mo | At 100+ clients |
| Proxy rotation (Reddit) | +$50–100/mo | At 500+ avatars |
| Stripe payment processing | 2.9% + $0.30/txn | When billing goes live |
| Legal / compliance review | One-time $2,000–5,000 | Before enterprise clients |

---

*Document version: 1.0*  
*Sources: docs/ai_cost_benchmark.md, docs/aws_budget_may2026.md, docs/budget_operational_may2026.md*  
*Next review: When first paid client onboards*
