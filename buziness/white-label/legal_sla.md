# RAMP White Label — Service Level Agreement (SLA) Commitments

## Document Purpose

This document defines the Service Level Agreement commitments for each white-label partner tier. It serves as the content for **Schedule B** referenced in the Partner Agreement Term Sheet.

**Status:** DRAFT — For internal review and legal counsel input only.

---

## SLA Tier Summary

| Commitment Level | Tiers | Financial Penalties |
|-----------------|-------|---------------------|
| Best-Effort (no contractual SLA) | Starter, Growth | None |
| Committed Targets (no financial penalties) | Scale | None |
| Contractual SLA (with service credits) | Enterprise | Yes — credit schedule applies |

---

## Starter & Growth Tiers — Best-Effort, No Contractual SLA

### Uptime

| Metric | Target |
|--------|--------|
| Monthly uptime target | 99.5% |
| Contractual guarantee | None — best-effort only |
| Financial penalties | None |

### Response Times

| Priority | Target Response | Target Resolution |
|----------|----------------|-------------------|
| Critical (platform down) | Starter: 24h / Growth: 4h (business hours) | Starter: 48h / Growth: 24h |
| High (feature broken, workaround exists) | Starter: 24h / Growth: 4h (business hours) | Starter: 5 business days / Growth: 3 business days |
| Normal (questions, config, how-to) | Starter: 48h / Growth: 8h (business hours) | Starter: 10 business days / Growth: 5 business days |
| Low (feature requests, suggestions) | Starter: 5 business days / Growth: 2 business days | Backlog |

Response times are targets, not guarantees. No financial remedy for missed targets.

### Maintenance & Notifications

| Item | Commitment |
|------|-----------|
| Scheduled maintenance notice | 48 hours advance notice |
| Emergency maintenance notice | As soon as reasonably practicable |
| Status page access | Yes — shared platform status page (real-time monitoring) |
| Incident reports | Not included |

### What This Means for Partners

- RAMP will make commercially reasonable efforts to maintain 99.5% uptime
- Partners have visibility into platform status via the shared status page
- No contractual remedy if targets are missed — escalation path is through support channels
- Suitable for partners whose end-clients do not require formal SLA pass-through

---

## Scale Tier — Committed Targets, No Financial Penalties

### Uptime

| Metric | Commitment |
|--------|-----------|
| Monthly uptime commitment | 99.5% |
| Contractual guarantee | Yes — committed target (written into agreement) |
| Financial penalties | None |
| Breach remedy | Written incident report + escalation to account manager |

### Response Times

| Priority | Committed Response | Committed Resolution |
|----------|-------------------|---------------------|
| Critical (platform down) | 2 hours (business hours) | 12 hours |
| High (feature broken, revenue impact) | 2 hours (business hours) | 24 hours |
| Normal (questions, config, optimization) | 4 hours (business hours) | 3 business days |
| Low (feature requests, enhancements) | 1 business day | Scheduled (roadmap review) |

Response times are committed targets documented in the partner agreement. Repeated failure to meet targets constitutes grounds for escalation review, but does not trigger financial penalties.

### Maintenance & Notifications

| Item | Commitment |
|------|-----------|
| Scheduled maintenance notice | 72 hours advance notice |
| Emergency maintenance notice | As soon as reasonably practicable |
| Status page access | Yes — dedicated partner-specific status page with partner metrics |
| Incident reports | Written report for any outage exceeding 30 minutes |
| Incident report delivery | Within 5 business days of incident resolution |

### What This Means for Partners

- RAMP formally commits to 99.5% uptime in the partner agreement
- Partners receive written incident reports they can share with their end-clients
- Dedicated status page allows partners to monitor their specific environment
- No financial credits — but sustained failure (3 consecutive months below target) constitutes material breach per Section 7.1 of the term sheet
- Suitable for partners who need to demonstrate reliability to end-clients but don't require financial SLA pass-through

---

## Enterprise Tier — Contractual SLA with Service Credits

### Uptime Guarantee

| Metric | Commitment |
|--------|-----------|
| Monthly uptime guarantee | 99.5% |
| Contractual guarantee | Yes — legally binding with financial remedy |
| Measurement period | Calendar month |
| Measurement method | External monitoring (shared dashboard with partner) |

### Credit Schedule

| Monthly Uptime | Service Credit |
|---------------|---------------|
| 99.0% – 99.5% | 10% of monthly fee |
| 95.0% – 99.0% | 25% of monthly fee |
| Below 95.0% | 50% of monthly fee |

**Credit cap:** Total credits in any calendar month SHALL NOT exceed 50% of that month's platform fee.

**Credit application:** Approved credits applied to the next month's invoice automatically.

### Response Times (Contractual)

| Priority | Guaranteed Response | Guaranteed Resolution | Coverage |
|----------|--------------------|--------------------|----------|
| Critical (platform down, data loss risk) | 1 hour | 4 hours | 24/7 |
| High (feature broken, revenue impact) | 2 hours | 12 hours | Business hours |
| Normal (questions, config, optimization) | 4 hours | 2 business days | Business hours |
| Low (feature requests, enhancements) | 1 business day | Per roadmap agreement | Business hours |

### Incident Response

| Item | Commitment |
|------|-----------|
| Root Cause Analysis (RCA) | Within 72 hours for all P1 (Critical) incidents |
| Prevention plan | Within 1 week of P1 incident resolution |
| Status updates during P1 | Every 30 minutes until resolution |
| Post-incident review meeting | Available upon partner request |

### Maintenance Windows

| Item | Commitment |
|------|-----------|
| Scheduled maintenance notice | 72 hours advance notice |
| Maximum scheduled maintenance | 4 hours per calendar month |
| Maintenance window | Agreed upon with partner (default: Sunday 02:00–06:00 UTC) |
| Emergency maintenance notice | As soon as reasonably practicable (target: 1 hour advance) |
| Status page access | Dedicated status page with real-time partner-specific metrics |

### Credit Request Process

1. Partner identifies potential SLA breach and submits credit request via email within **30 days** of the incident
2. RAMP validates the claim against external monitoring data within **5 business days**
3. Approved credits applied to next invoice automatically
4. Disputed credits escalated to executive review within **10 business days**
5. If dispute is not resolved within 20 business days, either party may invoke the arbitration clause

### What This Means for Partners

- Full contractual SLA with financial teeth — partners can pass through SLA commitments to their own end-clients
- 24/7 coverage for critical issues ensures partner operations are never blocked overnight
- RCA documents provide transparency partners can share with their end-clients
- Credit cap at 50% protects RAMP from catastrophic credit exposure while providing meaningful remedy
- Suitable for partners serving enterprise end-clients who require formal SLA guarantees in their own contracts

---

## Definitions

### Uptime Calculation

```
Uptime % = (Total minutes in month − Downtime minutes) / Total minutes in month × 100
```

### Uptime Scope

"Platform availability" means the Partner Portal and API endpoints are accessible and returning 2xx/3xx HTTP responses to authenticated requests.

Specifically includes:
- Partner Portal web application (dashboard, client management, reporting)
- API endpoints used by the Mobile Posting App
- Webhook delivery endpoints
- Authentication and authorization services

### Downtime Definition

**Downtime** is defined as **5 or more consecutive minutes** during which the Partner Portal or API returns 5xx errors or is unreachable from the external monitoring endpoint.

Isolated errors (less than 5 consecutive minutes) or intermittent timeouts do not constitute downtime.

### Exclusions from Uptime Calculation

The following are **excluded** from downtime calculations:

| Exclusion | Description |
|-----------|-------------|
| Scheduled maintenance | Pre-announced maintenance windows (per advance notice requirements above) |
| Force majeure | Events beyond RAMP's reasonable control (natural disasters, war, government action) |
| Platform Enforcement Events | Reddit API restrictions, rate limit changes, or access limitations imposed by Reddit |
| Partner infrastructure | Issues with partner's custom domain DNS, SSL certificates managed by partner, or partner's own network |
| Third-party services | Outages of external services not operated by RAMP (email providers, CDN, DNS registrars) |
| Partner-caused issues | Downtime resulting from partner's API misuse, excessive load, or configuration errors |

### Incident Severity Definitions

| Severity | Code | Definition | Examples |
|----------|------|-----------|----------|
| Critical | P1 | Platform completely unavailable or data loss risk | Portal down for all users, API 5xx on all endpoints, database corruption |
| High | P2 | Major feature broken, revenue-impacting, no workaround | Pipeline stopped, posting failures for all avatars, login broken |
| Normal | P3 | Feature degraded, workaround available | Slow dashboard load, report generation delayed, minor UI bugs |
| Low | P4 | Enhancement request or cosmetic issue | Feature request, UI improvement, documentation update |

### Measurement Method

- **Tool:** External monitoring service (UptimeRobot or equivalent)
- **Check frequency:** Every 1 minute
- **Check endpoints:** Partner Portal login page + API health endpoint
- **Dashboard:** Shared with partner (read-only access to monitoring data)
- **Data retention:** 12 months of uptime history available to partner

### Business Hours

- **Definition:** Monday through Friday, 09:00–18:00 IST (Israel Standard Time / UTC+2 or UTC+3 during DST)
- **Excludes:** Israeli public holidays, Saturdays, Sundays
- **24/7 coverage (Enterprise Critical only):** On-call engineering rotation for P1 incidents

---

## Cross-Tier Comparison Table

| SLA Element | Starter | Growth | Scale | Enterprise |
|-------------|---------|--------|-------|-----------|
| **Uptime target** | 99.5% (best-effort) | 99.5% (best-effort) | 99.5% (committed) | 99.5% (guaranteed) |
| **Financial penalties** | None | None | None | Yes — credit schedule |
| **Credit cap** | — | — | — | 50% of monthly fee |
| **Response: Critical** | 24h (business hours) | 4h (business hours) | 2h (business hours) | 1h (24/7) |
| **Response: High** | 24h (business hours) | 4h (business hours) | 2h (business hours) | 2h (business hours) |
| **Response: Normal** | 48h (business hours) | 8h (business hours) | 4h (business hours) | 4h (business hours) |
| **Maintenance notice** | 48h | 48h | 72h | 72h |
| **Max maintenance/month** | No limit | No limit | No limit | 4 hours |
| **Incident reports** | No | No | Yes (>30 min outages) | Yes + RCA within 72h |
| **Status page** | Shared | Shared | Partner-specific | Partner-specific + real-time |
| **Monitoring dashboard** | No | No | No | Yes (shared read-only) |
| **Post-incident RCA** | No | No | No | Yes (P1 within 72h) |
| **24/7 coverage** | No | No | No | Critical issues only |
| **Contractual SLA** | No | No | Committed targets | Full SLA with credits |

---

## SLA Pass-Through Guidance

### For Partners Offering SLA to Their End-Clients

| Partner Tier | Can Pass Through SLA? | Recommended Approach |
|-------------|----------------------|---------------------|
| Starter | No — no contractual backing | Do not offer SLA to end-clients; position as "managed service" |
| Growth | No — no contractual backing | Offer "target uptime" language without financial commitment |
| Scale | Partial — committed targets | Offer committed targets to end-clients without financial penalties |
| Enterprise | Yes — full SLA | Mirror RAMP's SLA to end-clients (recommend slightly lower commitments for margin) |

### Recommended End-Client SLA (Enterprise Partners)

If an Enterprise partner wants to offer SLA to their end-clients, we recommend:

- Uptime guarantee: 99.0% (gives 0.5% buffer against RAMP's 99.5%)
- Credit schedule: 5% / 15% / 30% (lower than RAMP's credits to protect partner margin)
- Credit cap: 30% of monthly fee (lower than RAMP's 50% cap)
- Response times: Add 1 hour buffer to each tier vs. RAMP's commitments

This ensures the partner is never in a position where they owe more credits than they can recover from RAMP.

---

## Relationship to Other Documents

| Document | Relationship |
|----------|-------------|
| Partner Agreement Term Sheet (Section 5.1) | This SLA document expands on the uptime and support commitments referenced there |
| Partner Support Tiers | Defines the support channels and escalation paths that enable SLA response times |
| Suspension Policy (Task 5.5) | Defines when RAMP may suspend access — suspension periods count as downtime unless caused by partner |

---

*Document version: 1.0*
*Last updated: Schedule B draft for legal counsel review*
*Referenced by: Term Sheet Section 5.1, Schedule B*
*Next step: Legal counsel review and incorporation into formal partner agreement*
