# RAMP Platform — Operational Budget

**Date:** May 11, 2026  
**Period covered:** May 1–11 (actuals) + May–June 2026 (forecast)  
**Prepared by:** Max Breger (CTO / Technical Co-Founder)

---

## Part 1: Already Spent (May 1–11, 2026)

Expenses incurred during the initial 10-day development sprint. All paid from personal funds.

| Item | Details | Amount |
|------|---------|--------|
| Kiro IDE (Pro subscription) | AI-assisted development — primary coding tool | $200 |
| Claude Pro / API credits | Anthropic API for coding assistance + pipeline testing | $60-80 |
| Cursor / other AI tools | Secondary coding assistants | $20-40 |
| Gemini API | Testing scoring pipeline prompts | $5-10 |
| Misc (domain research, utilities) | DNS, local infra, testing tools | $10-15 |
| **TOTAL SPENT** | | **~$250-380** |

> **Note:** No AWS costs yet — development has been local (Docker). Server deployment starts this week.

---

## Part 2: Monthly Operational Budget (10 avatars, active development + production)

### Budget Structure

The platform has **three cost layers** that run simultaneously:

```
┌─────────────────────────────────────────────────────┐
│  Layer 1: DEVELOPMENT                               │
│  AI tools that write code + iterate on prompts      │
│  (investment in speed — builds in days, not months)  │
├─────────────────────────────────────────────────────┤
│  Layer 2: TESTING                                   │
│  Running pipeline with real AI models to validate   │
│  (investment in quality — catches bugs before prod)  │
├─────────────────────────────────────────────────────┤
│  Layer 3: PRODUCTION                                │
│  AI generating comments for real clients            │
│  (COGS — scales with clients, covered by revenue)   │
└─────────────────────────────────────────────────────┘
```

### Detailed Breakdown

#### Layer 1: Development Tools — $220/mo

| Item | What it does | Cost/mo |
|------|-------------|---------|
| Kiro IDE Pro | Primary AI coding environment (writes 70%+ of code) | $39 |
| Claude Pro + API overages | Code generation, architecture decisions, complex logic | $80-100 |
| Cursor Pro | Secondary AI coding tool (parallel workflows) | $20 |
| GPT Plus / API | Prompt engineering, alternative perspectives | $20 |
| Other dev tools | Linters, formatters, testing utilities | $20 |
| **Subtotal** | | **~$200-220** |

**Why this matters:** Without AI coding tools, the 10-day sprint would have taken 2-3 months. This is the single biggest force multiplier.

#### Layer 2: Testing & Prompt Calibration — $50-80/mo

| Item | What it does | Cost/mo |
|------|-------------|---------|
| Claude Sonnet API (testing) | Running generation pipeline during development | $30-40 |
| Gemini Flash API (testing) | Running scoring pipeline during development | $5-10 |
| Integration test runs | Full pipeline end-to-end with real models | $15-20 |
| Prompt iteration cycles | Tuning voice profiles, scoring accuracy | $10-15 |
| **Subtotal** | | **~$60-80** |

**Why this matters:** Every prompt change needs validation with real models. Mocking doesn't catch quality regressions. This prevents shipping broken AI to clients.

#### Layer 3: Production AI Pipeline — $80-120/mo (at 10 avatars)

| Operation | Model | Calls/day | Cost/call | Cost/mo |
|-----------|-------|-----------|-----------|---------|
| Thread scoring | Gemini Flash | 200 | $0.0003 | $1.80 |
| Persona selection | Claude Sonnet | 50 | $0.020 | $30.00 |
| Comment generation | Claude Sonnet | 50 | $0.036 | $54.00 |
| Comment editing | Claude Sonnet | 50 | $0.018 | $27.00 |
| Hobby comments | Gemini Flash | 30 | $0.002 | $1.80 |
| **Subtotal** | | | | **~$115/mo** |

> Based on: 10 avatars, ~5 professional + 3 hobby comments/day each.  
> Source: `docs/ai_cost_benchmark.md` — validated against Ori's actual token usage.

**Scaling note:** This cost is linear per client. Each new client adds ~$36-80/mo in AI costs depending on volume.

#### Layer 4: Infrastructure — $50-70/mo

| Item | What it does | Cost/mo |
|------|-------------|---------|
| AWS EC2 t3.small | Application server (app + workers + DB) | $20.43 |
| AWS SQS | Task queue (scraping, AI pipeline) | $0.30 |
| AWS ElastiCache Valkey | Distributed locks, rate limiting, caching | $6.14 |
| Domain + SSL | Production URL for admin access | $5-10 |
| S3 (backups) | Database backups | $0.50 |
| CloudWatch | Monitoring and alerts | $0 (free tier) |
| Buffer (EBS, data transfer) | Storage growth, unexpected usage | $10-15 |
| **Subtotal** | | **~$45-55** |

> Source: `docs/aws_budget_may2026.md` — detailed calculation with ECPU/request breakdown.

---

### Monthly Total

| Layer | Cost/mo | % of total |
|-------|---------|-----------|
| Development tools | $220 | 44% |
| Testing & calibration | $70 | 14% |
| Production AI pipeline | $115 | 23% |
| Infrastructure | $50 | 10% |
| Contingency (10%) | $45 | 9% |
| **TOTAL** | **$500/mo** | 100% |

---

## Part 3: Revenue vs. Cost — Path to Self-Sustaining

| Milestone | Revenue/mo | Costs/mo | Net |
|-----------|-----------|---------|-----|
| Pre-revenue (now) | $0 | $500 | -$500 |
| 1 client (Seed plan) | $399 | $500 | -$101 |
| 1 client (Starter plan) | $799 | $500 | +$299 |
| 2 clients (mixed) | $800-1,200 | $550 | +$250-650 |
| 3 clients | $1,200-2,400 | $620 | +$580-1,780 |
| 5 clients | $2,000-4,000 | $750 | +$1,250-3,250 |

**Break-even: 1 client on Starter plan ($799/mo) or 2 clients on Seed plan.**

> Note: Development tools cost ($220) stays flat regardless of client count.  
> Production AI scales at ~$36-80 per additional client.  
> Infrastructure stays at $27-54 until 50+ clients.

---

## Part 4: What Happens Without This Budget

| If blocked | Consequence |
|-----------|-------------|
| No AI dev tools | Development speed drops 5-10x. 2-week sprints become 2-month sprints. |
| No testing budget | Ship untested prompts → bad comments → client churn → reputation damage |
| No production AI | Pipeline doesn't run. No comments generated. No value delivered. |
| No server | System exists only on my laptop. Tzvi can't test. No pilot possible. |

---

## Part 5: Budget Request Summary

| Request | Amount | When |
|---------|--------|------|
| Reimburse May 1–11 expenses | $175 | Immediate |
| Monthly operational budget | $500/mo | Starting May 12 |
| **First payment needed** | **$675** | **This week** |

Subsequent months: $500/mo until revenue covers costs (expected: June-July 2026).

---

## Appendix: Cost Optimization Already Applied

These decisions save $200+/mo compared to naive approaches:

1. **Gemini Flash for scoring** (not Claude) — saves $150/mo at 10 avatars
2. **Docker PostgreSQL** (not RDS) — saves $24/mo
3. **SQS + Valkey Serverless** (not managed Redis cluster) — saves $30/mo
4. **Single EC2 instance** (not ECS/Fargate) — saves $50/mo
5. **LiteLLM routing** (direct API, not OpenRouter) — saves 10-15% markup

---

*Document version: 1.0*  
*Next review: When first client revenue arrives*
