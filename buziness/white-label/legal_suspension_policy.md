# RAMP White Label — Platform Suspension Policy

## Document Purpose

This document defines **when and how RAMP can suspend a White Label Partner's platform access**. It provides clear triggers, processes, and escalation paths for the operations team.

**Status:** DRAFT — For internal review and legal counsel input only.
**Referenced by:** Term Sheet §7.3 (Immediate Suspension), §3.4 (Payment Terms), §4.1 (Minimum Activity)

---

## 1. Immediate Suspension Triggers (No Prior Notice)

These triggers represent existential threats to RAMP's infrastructure, other partners, or legal standing. Suspension is effective immediately upon detection — no cure period before suspension.

| # | Trigger | Definition | Detection Method |
|---|---------|-----------|-----------------|
| 1 | **Systemic Risk** | 3+ avatars assigned to the partner receive Reddit bans within a rolling 7-day window | Automated: health_checker service flags ban cluster |
| 2 | **Mechanism Exposure** | Partner publicly describes the platform as "bots," "fake accounts," "automated accounts," or equivalent terminology in any external communication | Manual: monitoring + partner/client reports |
| 3 | **Illegal Activity** | Platform used for fraud, defamation, harassment, illegal content distribution, or any activity that violates applicable law | Manual: content review + external reports |
| 4 | **Security Breach** | Partner's credentials compromised, unauthorized access detected, or partner shares access with unauthorized third parties | Automated: anomalous login patterns, IP changes, credential sharing indicators |
| 5 | **Threat to Other Partners** | Partner's actions create enforcement risk against shared infrastructure (e.g., Reddit flags IP ranges, subreddit-level bans affecting multiple partners) | Automated: cross-partner correlation in health monitoring |

### Immediate Suspension — Key Rules

- **No advance warning required.** RAMP suspends first, notifies within 24 hours.
- **Written notification** sent within 24 hours of suspension (email + Slack if applicable).
- **Partner has 15 days to cure** (for curable violations — see §4 below).
- **Non-curable violations** (illegal activity, repeated mechanism exposure) → immediate termination right.

---

## 2. Suspension with Notice (10-Day Cure Period)

These triggers are serious but curable. RAMP provides **10 calendar days written notice** before suspension takes effect. If the partner cures within the notice period, no suspension occurs.

| # | Trigger | Definition | Threshold | Notice Method |
|---|---------|-----------|-----------|---------------|
| 1 | **Payment Default** | Outstanding invoice balance exceeds 60 days overdue | ≥60 days past due date | Email + Slack |
| 2 | **Minimum Activity Failure** | Partner fails to maintain minimum active client slots (first occurrence only) | <3 active slots after 90 days from Effective Date | Email |
| 3 | **Content Safety Violations** | Repeated bypass or override of platform safety guardrails (phase gates, brand ratio, promotional language detection) | 3+ documented violations within 30 days | Email + Slack |
| 4 | **Excessive Support Burden** | Unreasonable support demands outside tier entitlement (e.g., Starter tier partner demanding dedicated AM response times) | Documented pattern over 30+ days | Email |

### Notice Period — Key Rules

- **10 calendar days** from date of written notice.
- **Cure = no suspension.** If partner resolves the issue within 10 days, access continues uninterrupted.
- **Failure to cure = suspension** on day 11, followed by standard suspension process (§3).
- **Second occurrence of same trigger** → escalates to immediate suspension (no notice period).

---

## 3. Suspension Process

### Step-by-Step

```
┌─────────────────────────────────────────────────────────────────────┐
│  SUSPENSION PROCESS                                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  1. TRIGGER DETECTED                                                 │
│     ├── Immediate trigger? → Suspend NOW → Go to Step 2             │
│     └── Notice trigger? → Send 10-day notice → Wait for cure        │
│         ├── Cured within 10 days? → Close. No suspension.           │
│         └── Not cured? → Suspend on day 11 → Go to Step 2          │
│                                                                      │
│  2. SUSPENSION EXECUTED                                              │
│     • Partner portal access revoked                                  │
│     • Pipeline paused (no new content generated or posted)           │
│     • API keys deactivated                                           │
│     • Mobile app tokens invalidated                                  │
│                                                                      │
│  3. WRITTEN NOTIFICATION (within 24 hours)                           │
│     • Email to partner's registered contact                          │
│     • Slack notification (if channel exists)                         │
│     • Notification includes: trigger, evidence, cure path, deadline  │
│                                                                      │
│  4. CURE PERIOD (15 calendar days from suspension)                   │
│     ├── Partner cures? → Restore access within 24 hours             │
│     └── Partner does not cure? → Agreement terminates automatically  │
│                                                                      │
│  5. POST-RESOLUTION                                                  │
│     • Suspension logged in partner record                            │
│     • Incident report filed internally                               │
│     • Escalation rules updated (see §5)                              │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Timelines Summary

| Event | Timeline |
|-------|----------|
| Immediate suspension → notification | Within 24 hours |
| Notice trigger → suspension (if not cured) | 10 calendar days |
| Suspension → cure deadline | 15 calendar days |
| Cure confirmed → access restored | Within 24 hours |
| Cure deadline missed → termination | Automatic on day 16 |

---

## 4. During Suspension — What Happens

| System Component | Status During Suspension |
|-----------------|------------------------|
| Partner portal | **Inaccessible** — login returns suspension notice page |
| Content pipeline | **Paused** — no new scraping, scoring, generation, or posting for partner's clients |
| Existing posted content | **Remains on Reddit** — RAMP does not remove previously posted content |
| Partner data | **Preserved** — no deletion during suspension period |
| End-client access | **Blocked** — end-clients cannot access partner-branded portal |
| Mobile app | **Tokens invalidated** — app shows "service unavailable" |
| Billing | **Continues** — unless suspension is RAMP-caused (platform outage, RAMP error) |
| Avatar assignments | **Frozen** — avatars remain assigned but inactive |
| Audit logs | **Continue recording** — all access attempts logged |

### Billing During Suspension

- **Partner-caused suspension:** Billing continues. Partner owes fees for the suspension period.
- **RAMP-caused suspension** (platform error, false positive): Billing paused for suspension duration. Credit issued on next invoice.
- **Disputed suspension:** Billing continues pending resolution. Credit issued retroactively if dispute resolved in partner's favor.

---

## 5. Post-Suspension Escalation Rules

| Occurrence | Consequence |
|-----------|-------------|
| **First suspension** (any cause) | Warning documented + standard 15-day cure period |
| **Second suspension** (same cause) | RAMP has immediate termination right (no cure period required) |
| **Second suspension** (different cause) | Standard cure period applies, but partner placed on "watch" status |
| **Third suspension** (any cause) | Immediate termination right regardless of cause |

### Suspension History

- All suspensions tracked in partner record with: date, trigger, evidence, cure status, resolution date.
- Suspension history survives contract renewal — does not reset annually.
- Partner may request suspension history review after 12 months of clean operation (RAMP may, at its discretion, remove first-offense records).

---

## 6. Curable vs. Non-Curable Violations

| Trigger | Curable? | Cure Action |
|---------|----------|-------------|
| Systemic risk (mass bans) | Yes | Root cause analysis submitted + remediation plan approved by RAMP |
| Mechanism exposure | Conditional | Retraction + NDA re-acknowledgment (first offense only). Second offense = non-curable. |
| Illegal activity | No | Immediate termination. No cure path. |
| Security breach | Yes | Credential rotation + security audit + incident report |
| Threat to other partners | Conditional | Depends on severity. RAMP determines curability case-by-case. |
| Payment default | Yes | Full payment of outstanding balance + late fees |
| Minimum activity failure | Yes | Activate minimum 3 client slots within cure period |
| Content safety violations | Yes | Acknowledge violations + implement additional review controls |
| Excessive support burden | Yes | Acknowledge tier limits + reduce support requests to entitlement |

---

## 7. Ops Team Decision Tree

Use this decision tree when evaluating a potential suspension trigger.

```
START: Potential suspension trigger identified
│
├─ Q1: Is this an IMMEDIATE trigger? (§1: systemic risk, mechanism exposure,
│       illegal activity, security breach, threat to others)
│   │
│   ├── YES → Q2: Is there clear evidence?
│   │   │
│   │   ├── YES → SUSPEND IMMEDIATELY
│   │   │         • Revoke portal access
│   │   │         • Pause pipeline
│   │   │         • Notify partner within 24h
│   │   │         • Log in partner record
│   │   │         • Escalate to legal if illegal activity
│   │   │
│   │   └── NO → INVESTIGATE (48h max)
│   │             • Gather evidence
│   │             • Do NOT suspend yet
│   │             • If confirmed → suspend
│   │             • If not confirmed → close, no action
│   │
│   └── NO → Q3: Is this a NOTICE trigger? (§2: payment, activity,
│               content safety, support burden)
│       │
│       ├── YES → Q4: Is this a FIRST occurrence?
│       │   │
│       │   ├── YES → SEND 10-DAY NOTICE
│       │   │         • Email + Slack notification
│       │   │         • Document trigger + evidence
│       │   │         • Set calendar reminder for day 10
│       │   │         • If cured → close, log warning
│       │   │         • If not cured → suspend on day 11
│       │   │
│       │   └── NO (repeat offense, same cause) → SUSPEND IMMEDIATELY
│       │             • Escalation rule applies (§5)
│       │             • RAMP has termination right
│       │             • Notify partner within 24h
│       │
│       └── NO → NOT A SUSPENSION TRIGGER
│                 • Log concern in partner notes
│                 • Monitor for pattern
│                 • Consider informal outreach
│
POST-SUSPENSION:
│
├─ Q5: Has partner cured within 15 days?
│   │
│   ├── YES → RESTORE ACCESS
│   │         • Re-enable portal within 24h
│   │         • Resume pipeline
│   │         • Reactivate API keys + mobile tokens
│   │         • Log resolution in partner record
│   │         • Send confirmation email
│   │
│   └── NO → TERMINATE AGREEMENT
│             • Send termination notice
│             • Begin 30-day data export window
│             • Revoke all access permanently
│             • Avatars revert to RAMP inventory
│             • Outstanding invoices due immediately
│             • Log termination in partner record
│
END
```

---

## 8. Communication Templates

### Immediate Suspension Notice

> **Subject:** [URGENT] Platform Access Suspended — Action Required
>
> Dear [Partner Name],
>
> Your access to the RAMP platform has been suspended effective [date/time] due to:
>
> **Trigger:** [Specific trigger from §1]
> **Evidence:** [Brief description of evidence]
>
> **What this means:**
> - Your partner portal is inaccessible
> - Content pipeline is paused for all your clients
> - Existing posted content remains on Reddit (not removed)
> - Your data is preserved (not deleted)
>
> **To restore access:**
> You have 15 calendar days (until [deadline date]) to cure this violation.
> Required cure action: [Specific action required]
>
> **If not cured by [deadline date]:**
> Your agreement will terminate automatically per §7.3 of the Partner Agreement.
>
> Please respond to this email within 48 hours to acknowledge receipt and discuss next steps.
>
> — RAMP Operations Team

### 10-Day Cure Notice

> **Subject:** Platform Access — 10-Day Notice of Potential Suspension
>
> Dear [Partner Name],
>
> We are writing to notify you of a compliance issue that requires your attention:
>
> **Issue:** [Specific trigger from §2]
> **Details:** [Description + evidence]
>
> **Required action:** [Specific cure action]
> **Deadline:** [Date — 10 calendar days from today]
>
> If this issue is resolved by [deadline date], no further action will be taken.
>
> If not resolved, your platform access will be suspended on [suspension date] per the Partner Agreement.
>
> Please contact us if you need clarification or assistance resolving this issue.
>
> — RAMP Operations Team

---

## 9. Internal Escalation Matrix

| Trigger Type | First Responder | Escalation (if needed) | Final Authority |
|-------------|----------------|----------------------|----------------|
| Systemic risk (mass bans) | Ops team | CTO (Max) | CEO (Tzvi) |
| Mechanism exposure | Ops team | CEO (Tzvi) | Legal counsel |
| Illegal activity | Ops team | Legal counsel immediately | CEO (Tzvi) + Legal |
| Security breach | CTO (Max) | Ops team | CEO (Tzvi) |
| Threat to other partners | Ops team | CTO (Max) | CEO (Tzvi) |
| Payment default | Finance/Ops | CEO (Tzvi) | — |
| Minimum activity failure | Ops team | Account manager | CEO (Tzvi) |
| Content safety violations | Ops team | CTO (Max) | CEO (Tzvi) |
| Excessive support burden | Account manager | Ops team | CEO (Tzvi) |

---

## 10. Metrics & Monitoring

### Automated Detection (Built into Platform)

| Trigger | Detection Method | Alert Channel |
|---------|-----------------|---------------|
| Mass bans (3+ in 7 days) | `health_checker` service correlates ban events per partner | Slack #ops-alerts + email to ops |
| Security anomaly | Login from new IP + country change + rapid API calls | Slack #security + email to CTO |
| Pipeline safety violations | `safety.py` guardrail firing rate per partner | Dashboard metric + weekly report |

### Manual Monitoring (Ops Team Responsibility)

| Trigger | Check Frequency | Source |
|---------|----------------|--------|
| Mechanism exposure | Weekly | Google Alerts on partner name + "Reddit bots" |
| Payment default | Weekly | Invoice aging report |
| Minimum activity | Monthly | Partner dashboard metrics |
| Support burden | Monthly | Support ticket volume per partner vs. tier |

---

## Key Principles

1. **Suspend first, investigate later** — for immediate triggers only. Protecting the platform takes priority over partner convenience.
2. **Always document** — every suspension, notice, and cure must be logged with timestamps and evidence.
3. **Proportional response** — notice triggers get notice periods. Only existential threats get immediate action.
4. **Cure is preferred** — RAMP wants partners to succeed. Suspension is a protective measure, not a punishment.
5. **Consistency** — same rules apply to all partners regardless of tier or revenue. No exceptions without CEO approval.

---

*Document version: 1.0*
*Last updated: Suspension policy framework for legal counsel review*
*Referenced by: Term Sheet §7.3, Tasks 5.5*
*Next step: Legal counsel review + integration into final Partner Agreement*
