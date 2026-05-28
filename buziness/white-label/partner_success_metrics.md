# RAMP White Label — Partner Success Metrics & Reporting Cadence

## Document Purpose

Defines the metrics RAMP tracks for each white-label partner, the reporting cadence, KPI targets, and success milestones. Used internally for partner health monitoring and externally for partner-facing performance reporting.

---

## 1. Partner Health Metrics (Tracked by RAMP Internally)

These metrics are monitored by the RAMP operations team to assess partner health, identify at-risk accounts, and optimize platform performance.

### 1.1 Slot Utilization

| Metric | Definition | KPI Target | Alert Threshold |
|--------|-----------|-----------|-----------------|
| Active client slots | Clients with ≥1 approved draft in last 30 days | ≥60% of tier limit | <40% utilization for 30+ days |
| Slot utilization rate | Active slots / max slots per tier | ≥75% by Month 3 | <50% after 60 days |
| Slot overage requests | Additional slots beyond tier limit | Track only | N/A (revenue opportunity) |

**Tier limits:**
- Starter: 3 slots
- Growth: 8 slots
- Scale: 20 slots
- Enterprise: Custom (negotiated)

### 1.2 Avatar Utilization

| Metric | Definition | KPI Target | Alert Threshold |
|--------|-----------|-----------|-----------------|
| Avatar utilization rate | Active avatars / total allocated | ≥80% | <50% for 14+ days |
| Avatars in warming | Avatars in Phase 1-2 (not yet producing brand content) | ≤30% of total | >50% after 90 days |
| Idle avatars | Avatars with 0 posts in 14 days | 0 | ≥2 idle avatars |
| Avatar purchases (monthly) | New pre-warmed avatars bought | 1-2/month (Growth tier) | 0 for 60+ days (expansion stall) |

### 1.3 Pipeline Volume

| Metric | Definition | KPI Target | Alert Threshold |
|--------|-----------|-----------|-----------------|
| Drafts generated/week | Total comment + post drafts created | 80-120 per partner (Growth) | <40/week (pipeline underperforming) |
| Drafts approved/week | Drafts moved to approved status | ≥60% of generated | <40% (quality issue or review bottleneck) |
| Drafts posted/week | Approved drafts successfully posted to Reddit | ≥90% of approved | <70% (posting failures) |
| Review queue latency | Avg time from generated → approved/rejected | <24 hours | >48 hours (partner not reviewing) |
| Pipeline throughput | End-to-end: thread scored → comment posted | 48-72 hours avg | >5 days (systemic bottleneck) |

### 1.4 Content Quality Score

| Metric | Definition | KPI Target | Alert Threshold |
|--------|-----------|-----------|-----------------|
| Approval rate | Approved / (Approved + Rejected) | ≥70% | <50% (generation quality issue) |
| Edit rate | Drafts edited before approval / total approved | ≤30% | >50% (voice mismatch) |
| Rejection rate | Rejected / total reviewed | ≤20% | >40% (serious quality problem) |
| Self-learning improvement | Month-over-month approval rate change | +5% per month | Declining for 2+ months |
| Removal rate (Reddit) | Posted comments removed by mods | ≤5% | >15% (subreddit rule violations) |

### 1.5 Avatar Health

| Metric | Definition | KPI Target | Alert Threshold |
|--------|-----------|-----------|-----------------|
| Frozen avatar count | Avatars currently frozen (any reason) | 0 | ≥2 frozen simultaneously |
| Shadowban incidents/month | New shadowban detections | 0 | ≥1 (immediate investigation) |
| CQS scores (avg) | Average Contributor Quality Score across partner's avatars | "Good" or above | Any avatar at "Lowest" |
| Health check pass rate | Avatars passing bi-daily health check | 100% | <90% |
| Avatar recovery time | Time from frozen → active again | <72 hours | >7 days |

### 1.6 LLM Cost Per Partner

| Metric | Definition | KPI Target | Alert Threshold |
|--------|-----------|-----------|-----------------|
| Actual LLM cost/month | Total API spend attributed to partner | ≤$280/mo (Growth, 8 clients) | >$350/mo (20%+ over budget) |
| Cost per draft | LLM cost / drafts generated | ≤$1.50/draft | >$2.50/draft |
| Cost vs. budget variance | (Actual - Budget) / Budget | ±10% | >+25% (cost overrun) |
| Cost per posted comment | Total LLM cost / successfully posted comments | ≤$3.00 | >$5.00 |

**Budget by tier:**
- Starter (3 clients): $105/mo
- Growth (8 clients): $280/mo
- Scale (20 clients): $700/mo
- Enterprise: Custom allocation

### 1.7 Support Metrics

| Metric | Definition | KPI Target | Alert Threshold |
|--------|-----------|-----------|-----------------|
| Ticket volume/month | Support requests from partner | ≤5/month (Growth) | >10/month (training gap or platform issue) |
| First response time | Time to first meaningful reply | <4 hours (business hours) | >8 hours |
| Resolution time | Time from ticket open → resolved | <24 hours | >48 hours |
| Escalation rate | Tickets requiring engineering involvement | ≤10% | >25% |
| Partner satisfaction (CSAT) | Post-resolution survey score | ≥4.5/5 | <3.5/5 |

---

## 2. Partner-Facing Metrics (Shared with Partner)

These metrics are visible to the partner via their dashboard and included in periodic reports. Designed to demonstrate value and ROI.

### 2.1 Client Activity

| Metric | Definition | Displayed As |
|--------|-----------|-------------|
| Monthly active clients | Clients with ≥1 post in last 30 days | Number + trend arrow |
| Total clients onboarded | Cumulative clients ever created | Number |
| Client engagement score | Composite: review frequency + approval rate | Green/Yellow/Red per client |

### 2.2 Content Performance

| Metric | Definition | Displayed As |
|--------|-----------|-------------|
| Total content published (month) | Comments + posts successfully posted | Number + month-over-month % |
| Total content published (all-time) | Cumulative posts across all clients | Number |
| Content by type | Comments vs. posts breakdown | Pie chart / ratio |
| Top-performing content | Highest karma comments this month | List (top 5) |

### 2.3 Growth & Impact

| Metric | Definition | Displayed As |
|--------|-----------|-------------|
| Aggregate karma growth | Net karma gained across all partner's avatars | Number + trend (weekly) |
| Karma growth rate | Week-over-week karma increase | Percentage |
| Top-performing subreddits | Subreddits with highest engagement | Ranked list (top 10) |
| Community authority score | Avg authority across partner's avatars | Score 0-100 + tier label |

### 2.4 Avatar Inventory Status

| Metric | Definition | Displayed As |
|--------|-----------|-------------|
| Available avatars | Ready to assign (Phase 3+, not in use) | Number (green) |
| In-use avatars | Currently assigned to clients | Number (blue) |
| Warming avatars | In Phase 1-2, building credibility | Number (amber) + ETA |
| Total inventory | All avatars allocated to partner | Number |

### 2.5 Platform Reliability

| Metric | Definition | KPI Target | Displayed As |
|--------|-----------|-----------|-------------|
| Platform uptime | % time partner portal accessible | 99.5% (SLA) | Percentage + status badge |
| Pipeline uptime | % time content pipeline operational | 99.0% | Percentage |
| Posting success rate | % approved drafts posted without error | ≥95% | Percentage |
| Avg posting latency | Time from approval → posted on Reddit | <30 minutes | Duration |

---

## 3. Reporting Cadence

### 3.1 Real-Time: Partner Dashboard (Live Metrics)

**Access:** Partner logs into their branded portal at any time.

**Displayed live:**
- Active client count and slot utilization gauge
- Review queue depth (pending drafts awaiting action)
- Today's pipeline activity (generated / approved / posted)
- Avatar health status (all green / warnings)
- Last 7 days karma trend (sparkline)
- Platform status indicator (operational / degraded / maintenance)

**Refresh rate:** Every 60 seconds (HTMX auto-refresh)

### 3.2 Weekly: Automated Email Summary

**Delivery:** Every Monday at 09:00 partner's local timezone
**Format:** HTML email, partner-branded (their logo, colors)
**Recipients:** Partner admin + designated contacts

**Contents:**
| Section | Metrics Included |
|---------|-----------------|
| Headline stats | Posts this week, karma gained, approval rate |
| Pipeline summary | Generated → Approved → Posted funnel |
| Top content | Best-performing comment (highest karma) |
| Avatar status | Any health alerts, frozen avatars, new warnings |
| Action items | Pending reviews >48h, idle clients, stale avatars |
| Week-over-week trend | Key metrics vs. previous week (↑↓) |

**Alerts included (if triggered):**
- Avatar frozen or shadowbanned
- Review queue >48h backlog
- Client slot utilization <40%
- Posting failures >10%

### 3.3 Monthly: Detailed Performance Report

**Delivery:** 3rd business day of each month
**Format:** PDF, partner-branded (logo, colors, partner name)
**Recipients:** Partner admin + business stakeholders

**Contents:**
| Section | Details |
|---------|---------|
| Executive summary | 3-sentence overview of month's performance |
| Client breakdown | Per-client metrics table (posts, karma, approval rate) |
| Content analytics | Volume trends, top subreddits, content type mix |
| Avatar performance | Per-avatar karma growth, health status, phase progress |
| Quality metrics | Approval rate trend, edit rate, removal rate |
| Growth indicators | New karma milestones, authority score changes |
| Inventory status | Avatar allocation, warming pipeline, availability forecast |
| Recommendations | AI-generated suggestions (add clients, buy avatars, adjust strategy) |
| SLA compliance | Uptime %, posting success rate, response times |

**KPI targets highlighted:** Green (met), Yellow (within 10%), Red (missed)

### 3.4 Quarterly: Business Review (Scale/Enterprise Tiers Only)

**Delivery:** Scheduled call + pre-read document (Week 1 of each quarter)
**Format:** Slide deck (PDF) + live 45-minute call with RAMP account manager
**Eligible tiers:** Scale ($3,499/mo) and Enterprise (custom)

**Agenda:**
| Topic | Duration | Content |
|-------|----------|---------|
| Quarter in review | 10 min | Key metrics, wins, challenges |
| ROI analysis | 10 min | Partner's revenue vs. platform cost, margin validation |
| Growth planning | 10 min | Expansion opportunities, tier upgrade discussion |
| Product roadmap | 10 min | Upcoming features, partner input on priorities |
| Action items | 5 min | Agreed next steps, timeline |

**Deliverables post-QBR:**
- Written summary with action items and owners
- Updated success plan for next quarter
- Tier upgrade recommendation (if applicable)

---

## 4. Success Milestones

### 4.1 First 30 Days — "First Value"

| Milestone | Target | KPI | Health Indicator |
|-----------|--------|-----|-----------------|
| Partner portal live | Day 5 | Onboarding complete | ✅ Portal accessible |
| First client workspace created | Day 7 | 1 client configured | ✅ Client active |
| First content generated | Day 10 | ≥10 drafts in review queue | ✅ Pipeline running |
| First content published | Day 14 | ≥1 comment posted to Reddit | ✅ End-to-end working |
| First karma earned | Day 21 | ≥10 karma across all posts | ✅ Content resonating |
| Partner reviews regularly | Day 30 | Review queue latency <24h | ✅ Partner engaged |

**30-day health score:** 6/6 milestones = Healthy, 4-5 = At Risk, <4 = Intervention needed

### 4.2 First 60 Days — "Proving ROI"

| Milestone | Target | KPI | Health Indicator |
|-----------|--------|-----|-----------------|
| 3+ clients active | Day 45 | ≥3 clients with posted content | ✅ Scaling usage |
| Positive ROI demonstrated | Day 60 | Partner revenue > platform cost | ✅ Economics validated |
| Approval rate >60% | Day 60 | Content quality acceptable | ✅ AI learning working |
| Avatar utilization >50% | Day 60 | Allocated avatars in active use | ✅ Inventory utilized |
| No critical incidents | Day 60 | 0 shadowbans, 0 frozen avatars | ✅ Operations stable |
| Partner refers prospect | Day 60 | ≥1 referral conversation | ✅ Partner satisfied |

**60-day health score:** 6/6 = Healthy, 4-5 = On Track, <4 = Account review needed

### 4.3 First 90 Days — "Minimum Commitment Met"

| Milestone | Target | KPI | Health Indicator |
|-----------|--------|-----|-----------------|
| Minimum commitment met | Day 90 | ≥3 active client slots (Starter minimum) | ✅ Contract fulfilled |
| Consistent pipeline | Day 90 | ≥50 posts/month sustained | ✅ Steady-state reached |
| Self-learning effective | Day 90 | Approval rate >70% | ✅ Quality improving |
| Partner self-sufficient | Day 90 | Support tickets <5/month | ✅ Low-touch operation |
| Karma growth positive | Day 90 | Net positive karma every week | ✅ Community traction |
| Expansion discussion initiated | Day 90 | Partner asks about more slots/avatars | ✅ Growth signal |

**90-day health score:** 6/6 = Expand, 4-5 = Maintain, <4 = Retention risk

### 4.4 Six Months — "Growth Phase"

| Milestone | Target | KPI | Health Indicator |
|-----------|--------|-----|-----------------|
| Tier upgrade discussion | Month 6 | Partner considering next tier | ✅ Revenue expansion |
| Slot utilization >75% | Month 6 | Using most of their allocation | ✅ Capacity pressure |
| Avatar inventory expanded | Month 6 | ≥2 additional avatar purchases | ✅ Investing in platform |
| Authority scores rising | Month 6 | Avg avatar authority >40/100 | ✅ Long-term value building |
| Zero churn signals | Month 6 | No contract renegotiation requests | ✅ Retention strong |
| Expansion plan agreed | Month 6 | Written plan for next 6 months | ✅ Committed long-term |

### 4.5 Twelve Months — "Renewal & Scale"

| Milestone | Target | KPI | Health Indicator |
|-----------|--------|-----|-----------------|
| Contract renewal signed | Month 12 | Annual renewal executed | ✅ Retained |
| Tier upgrade completed | Month 12 | Moved to higher tier (or expanded slots) | ✅ Revenue grown |
| Annual review completed | Month 12 | QBR with full-year retrospective | ✅ Relationship strong |
| Net revenue retention >110% | Month 12 | Partner paying more than Month 1 | ✅ Expansion revenue |
| Partner as reference | Month 12 | Willing to be named reference/case study | ✅ Advocate |
| Referral revenue generated | Month 12 | ≥1 new partner from referral | ✅ Flywheel working |

---

## 5. Internal Health Scoring

### Partner Health Score (Composite — 0-100)

Calculated weekly by RAMP operations team.

| Component | Weight | Scoring |
|-----------|--------|---------|
| Slot utilization | 20% | 100 if ≥75%, linear scale down to 0 at 0% |
| Pipeline activity | 20% | 100 if ≥80 posts/week (Growth), proportional |
| Content quality | 20% | 100 if approval rate ≥80%, linear scale |
| Avatar health | 15% | 100 if 0 frozen/shadowbanned, -25 per incident |
| Review engagement | 15% | 100 if avg latency <12h, degrades to 0 at >72h |
| Support burden | 10% | 100 if <3 tickets/month, degrades to 0 at >15 |

### Health Score Interpretation

| Score | Status | Action |
|-------|--------|--------|
| 80-100 | Healthy | Monitor, look for expansion opportunities |
| 60-79 | Attention | Proactive outreach, identify blockers |
| 40-59 | At Risk | Account manager intervention, success plan |
| 0-39 | Critical | Executive escalation, retention campaign |

### Automated Alerts (Internal)

| Trigger | Severity | Action |
|---------|----------|--------|
| Health score drops below 60 | Warning | Slack notification to account manager |
| Health score drops below 40 | Critical | Email to ops lead + account manager |
| No pipeline activity for 7 days | Warning | Automated check-in email to partner |
| No pipeline activity for 14 days | Critical | Phone call from account manager |
| Shadowban detected | Critical | Immediate partner notification + remediation |
| LLM cost >25% over budget | Warning | Internal review of usage patterns |

---

## 6. Metric Collection & Infrastructure

### Data Sources

| Metric Category | Source | Collection Method |
|----------------|--------|-------------------|
| Slot utilization | PostgreSQL (clients table) | Daily query |
| Pipeline volume | PostgreSQL (comment_drafts, post_drafts) | Real-time aggregation |
| Content quality | PostgreSQL (draft status transitions) | Event-driven |
| Avatar health | Health checker service + CQS checker | Bi-daily automated |
| LLM costs | AIUsageLog table | Per-request logging |
| Support tickets | Support system (TBD — email/Slack initially) | Manual tracking initially |
| Karma growth | Karma tracker service | Every 4 hours |
| Platform uptime | External monitoring (UptimeRobot or similar) | Every 60 seconds |

### Report Generation

| Report | Generation Method | Delivery |
|--------|------------------|----------|
| Real-time dashboard | HTMX partials, live DB queries | Partner portal |
| Weekly email | Celery Beat task (Monday 09:00) → HTML template → SMTP | Email |
| Monthly PDF | Celery Beat task (3rd business day) → WeasyPrint → S3 → Email | Email + portal download |
| Quarterly deck | Manual preparation by account manager | Scheduled call |

---

*Document version: 1.0*
*Last updated: Based on design document Success Metrics section + financial model cost data*
*Referenced by: Task 6.4 (success metrics and reporting cadence)*
*Related documents: financial_model.md (cost targets), partner_faq.md (partner expectations)*
