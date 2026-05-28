# RAMP White Label — Liability Allocation Model

## Document Purpose

This document defines the **three-layer liability allocation model** for the RAMP white-label partnership structure. It establishes who is responsible for what, when liability transfers between parties, and how specific real-world scenarios are handled.

**Status:** DRAFT — For internal review and legal counsel input only.
**Referenced by:** Task 5.2, Requirements 14.1–14.5
**Depends on:** `legal_term_sheet.md` (Section 6: Liability & Indemnification)

---

## Three-Layer Liability Structure

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│   RAMP (Technology Provider)                                        │
│   ─────────────────────────                                         │
│   Liable for:                                                       │
│     • Platform availability (99.5% SLA)                             │
│     • Data security (reasonable measures)                           │
│     • IP non-infringement (platform code itself)                    │
│                                                                     │
│   Cap: 3 months of fees paid by Partner                             │
│   Excludes: consequential damages, lost profits,                    │
│             Platform Enforcement Events                             │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                          ↓ licenses to                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   Partner (Platform Operator)                                       │
│   ───────────────────────────                                       │
│   Liable for:                                                       │
│     • Content approved through the platform                         │
│     • End-Client relationship management                            │
│     • Compliance with local advertising regulations                 │
│     • Mechanism confidentiality (NDA on how it works)               │
│     • Maintaining proper End-Client agreements                      │
│                                                                     │
│   Cap: Defined in Partner's own End-Client agreement                │
│   Indemnifies RAMP for: all claims arising from                     │
│   Partner's or End-Client's actions                                 │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                          ↓ sells to                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   End-Client (Service Buyer)                                        │
│   ─────────────────────────                                         │
│   Liable for:                                                       │
│     • Content strategy decisions                                    │
│     • Brand guideline compliance                                    │
│     • FTC/advertising disclosure (if applicable)                    │
│     • Acceptance of platform risk (via Partner agreement)           │
│                                                                     │
│   No direct relationship with RAMP.                                 │
│   All claims flow through Partner.                                  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Detailed Liability Breakdown

### Layer 1: RAMP (Technology Provider) — Limited Liability

RAMP's liability is narrowly scoped to the technology it provides. RAMP does not interact with End-Clients and has no visibility into content strategy decisions.

| Category | RAMP's Obligation | Liability Trigger | Cap |
|----------|------------------|-------------------|-----|
| Platform uptime | Maintain 99.5% monthly availability (excl. scheduled maintenance) | Sustained failure below SLA for 3+ consecutive months | 3 months of fees |
| Data security | Implement reasonable security measures (encryption at rest, access controls, audit logs) | Data breach caused by RAMP's failure to maintain reasonable measures | 3 months of fees |
| IP non-infringement | Platform code does not infringe third-party IP | Third-party IP claim against the platform itself (not content) | 3 months of fees |
| Platform bugs | Fix critical bugs within SLA response times | Only if bug causes data loss or security exposure | 3 months of fees |

**RAMP is NOT liable for:**

- Content published through the platform (once approved by Partner/End-Client)
- Platform Enforcement Events (Reddit bans, suspensions, content removals)
- Reddit API changes, rate limit changes, or ToS updates
- Partner's misrepresentation of platform capabilities to End-Clients
- End-Client's failure to comply with FTC/advertising regulations
- Consequential damages (lost profits, lost business opportunities, lost revenue)
- Indirect, incidental, special, or punitive damages

**Liability cap:** RAMP's total aggregate liability SHALL NOT exceed the fees paid by Partner in the **3 months immediately preceding** the event giving rise to the claim.

---

### Layer 2: Partner (Platform Operator) — Operational Liability

The Partner is the operational layer. They approve content, manage End-Clients, and represent the platform to the market. This is where most operational liability sits.

| Category | Partner's Obligation | Liability Trigger | Direction |
|----------|---------------------|-------------------|-----------|
| Content approval | Review and approve all content before publication | Approved content causes harm (defamation, false claims, regulatory violation) | Indemnifies RAMP |
| End-Client management | Maintain proper service agreements with End-Clients | End-Client claim reaches RAMP due to missing/inadequate Partner agreement | Indemnifies RAMP |
| Advertising compliance | Ensure compliance with local advertising regulations (FTC, ASA, etc.) | Regulatory action due to non-disclosure or misleading content | Indemnifies RAMP |
| Mechanism confidentiality | Never describe platform as "bots," "fake accounts," or similar | Breach of NDA exposes RAMP's methodology | Indemnifies RAMP + immediate suspension |
| Platform representation | Not misrepresent capabilities or make performance guarantees | End-Client claim based on Partner's false promises | Indemnifies RAMP |
| End-Client agreements | Ensure End-Clients accept platform risk, content liability, and NDA | End-Client sues RAMP directly (should be impossible if agreements are proper) | Indemnifies RAMP |

**Content Approval = Liability Transfer Point:**

```
Draft generated by AI
        ↓
Human reviews in platform
        ↓
┌─────────────────────────────────────────┐
│  APPROVAL CLICK = LIABILITY TRANSFERS   │
│                                         │
│  Before approval: RAMP's system output  │
│  After approval: Partner's content      │
│                                         │
│  Audit log records:                     │
│    • Who approved (user_id, role)       │
│    • When (timestamp, UTC)              │
│    • What (draft content hash)          │
│    • Context (thread_id, subreddit)     │
└─────────────────────────────────────────┘
        ↓
Content published → Partner liable
```

---

### Layer 3: End-Client (Service Buyer) — Content Liability

End-Clients are responsible for their content strategy decisions. They have no relationship with RAMP — all interactions flow through the Partner.

| Category | End-Client's Obligation | Mechanism |
|----------|------------------------|-----------|
| Content strategy | Decisions about what topics, tone, and messaging to pursue | Partner's service agreement |
| Brand guidelines | Ensuring content aligns with their brand standards | Partner's service agreement |
| FTC compliance | Advertising disclosures where required (sponsored content, endorsements) | Partner's service agreement |
| Platform risk acceptance | Acknowledging that Reddit enforcement actions are possible and not compensable | Partner's service agreement (risk acceptance clause) |
| Truthfulness | Content does not contain false claims about competitors or products | Partner's service agreement |

**End-Client has NO direct claim against RAMP.** The contractual chain is:

```
End-Client → claims against → Partner → (Partner indemnifies) → RAMP
```

---

## Five Key Principles

### 1. Liability Flows Downstream

```
RAMP ← indemnified by ← Partner ← indemnified by ← End-Client
```

Each party indemnifies the one above for their own actions. Claims flow upstream (End-Client → Partner → RAMP), but liability allocation pushes responsibility downstream to the party that made the decision.

### 2. Content Approval Is the Liability Transfer Point

The moment a human clicks "Approve" in the platform, liability for that content transfers from RAMP (as system output) to the Partner (as approved content). The Partner's agreement with their End-Client should further transfer content liability to the End-Client.

**Evidence chain:** Platform maintains immutable audit logs of every approval:
- User identity (who approved)
- Timestamp (when)
- Content hash (what was approved — proves content wasn't modified after approval)
- Thread context (where it was posted)
- IP address of approver

### 3. Platform Enforcement Events Are Force Majeure

No party is liable for Platform Enforcement Events:
- Reddit account suspensions or shadowbans
- Content removals by Reddit moderators or admins
- Reddit ToS changes affecting operations
- Reddit API access restrictions or rate limit changes
- Third-party platform outages

These are inherent operational risks that all parties accept. RAMP uses commercially reasonable efforts to mitigate (avatar health monitoring, phase gates, content safety checks) but cannot guarantee outcomes.

### 4. Each Party Indemnifies the One Above

| Indemnifying Party | Indemnified Party | For What |
|-------------------|-------------------|----------|
| End-Client | Partner | Content strategy decisions, brand guideline violations, FTC non-compliance |
| Partner | RAMP | Approved content, End-Client claims, confidentiality breaches, misrepresentation |
| RAMP | Partner | Platform IP infringement, gross negligence, security breaches caused by RAMP |

### 5. Audit Logs Provide the Evidence Chain

The platform maintains comprehensive audit logs that serve as the evidence chain for liability allocation:

| Log Type | What It Proves | Retention |
|----------|---------------|-----------|
| Content approval log | Who approved what content, when | 24 months minimum |
| Draft version history | Original AI output vs. human edits | 24 months minimum |
| Login/access log | Who accessed the platform, from where | 12 months |
| Configuration change log | Who changed settings, branding, or permissions | Indefinite |
| Platform Enforcement Event log | When Reddit took action, which avatars affected | Indefinite |
| Content safety gate log | When guardrails fired, what was blocked | 24 months |

---

## Scenario Analysis

### Scenario 1: Avatar Banned by Reddit

**Situation:** An avatar assigned to Partner's End-Client receives a permanent suspension from Reddit.

```
Timeline:
  Day 1: Avatar posting approved content in r/cybersecurity
  Day 5: Reddit suspends avatar (reason: "spam" or "platform manipulation")
  Day 5: Platform detects suspension via health check
  Day 5: Avatar auto-frozen, Partner notified

Liability analysis:
  ┌─────────────────────────────────────────────────────┐
  │ This is a Platform Enforcement Event (force majeure) │
  │                                                     │
  │ RAMP liable?    NO — force majeure                  │
  │ Partner liable? NO — force majeure                  │
  │ End-Client?     NO — force majeure                  │
  │                                                     │
  │ Resolution:                                         │
  │ • If avatar < 30 days old AND ban was platform-side │
  │   issue (not content-related): RAMP replaces at     │
  │   equivalent tier, no charge                        │
  │ • If avatar > 30 days OR ban was content-related:   │
  │   no replacement, no refund                         │
  │ • Partner communicates to End-Client per their      │
  │   own service agreement                             │
  └─────────────────────────────────────────────────────┘
```

**Key point:** The Partner's agreement with their End-Client MUST include a platform risk acceptance clause. If the Partner failed to include this clause and the End-Client demands compensation, that is the Partner's problem — not RAMP's.

---

### Scenario 2: Content Removed by Subreddit Moderators

**Situation:** A comment approved by the Partner's team is removed by subreddit moderators for violating subreddit rules.

```
Timeline:
  Hour 0: AI generates comment draft
  Hour 2: Partner's operator approves the draft
  Hour 3: Comment posted to r/marketing
  Hour 4: Moderator removes comment (reason: "self-promotion")
  Hour 6: Platform detects removal via liveness check

Liability analysis:
  ┌─────────────────────────────────────────────────────┐
  │ Content was APPROVED by Partner's operator           │
  │                                                     │
  │ RAMP liable?    NO — content was approved by human  │
  │                 (liability transferred at approval)  │
  │ Partner liable? PARTIALLY — they approved content   │
  │                 that violated subreddit rules        │
  │ End-Client?     PARTIALLY — if content strategy     │
  │                 pushed promotional messaging         │
  │                                                     │
  │ Resolution:                                         │
  │ • No financial liability (mod removal ≠ damages)    │
  │ • Platform logs the removal for analytics           │
  │ • Self-learning loop captures this as a signal      │
  │ • Future generation avoids similar patterns         │
  │ • If pattern repeats: RAMP may flag to Partner      │
  │   that their approval standards need tightening     │
  └─────────────────────────────────────────────────────┘
```

**Key point:** Moderator removals are operational friction, not liability events. No party owes damages. The platform's self-learning loop uses removals as training signal to improve future content.

---

### Scenario 3: Reddit API Change Breaks Functionality

**Situation:** Reddit changes their API rate limits or deprecates an endpoint, causing temporary platform disruption.

```
Timeline:
  Day 0: Reddit announces API changes (or implements without notice)
  Day 1: Platform scraping/posting partially disrupted
  Day 1: RAMP engineering begins adaptation
  Day 3: Platform restored to full functionality

Liability analysis:
  ┌─────────────────────────────────────────────────────┐
  │ This is a Platform Enforcement Event (force majeure) │
  │                                                     │
  │ RAMP liable?    NO — force majeure, but RAMP SHALL  │
  │                 use commercially reasonable efforts  │
  │                 to restore service                   │
  │ Partner liable? NO — force majeure                  │
  │ End-Client?     NO — force majeure                  │
  │                                                     │
  │ Resolution:                                         │
  │ • RAMP communicates disruption to Partners ASAP     │
  │ • Partners communicate to End-Clients per their     │
  │   own SLA/agreement                                 │
  │ • No SLA credits for force majeure downtime         │
  │ • If disruption > 30 days with no resolution path:  │
  │   either party may terminate without penalty        │
  └─────────────────────────────────────────────────────┘
```

**Key point:** Reddit API changes are explicitly listed as force majeure. RAMP's obligation is to adapt with reasonable speed, not to guarantee uninterrupted service through external platform changes.

---

### Scenario 4: Mass Ban Event (Systemic Risk)

**Situation:** Reddit enforcement action targets multiple avatars simultaneously across one Partner's End-Clients.

```
Timeline:
  Hour 0: Reddit bans 8 of 12 avatars assigned to Partner X's clients
  Hour 1: Platform health checks detect mass suspension
  Hour 1: RAMP operations alerted (systemic risk threshold)
  Hour 2: RAMP investigates — determines Partner's End-Client was
           approving overly promotional content in violation of
           content safety guidelines

Liability analysis:
  ┌─────────────────────────────────────────────────────┐
  │ Force majeure PLUS potential Partner negligence      │
  │                                                     │
  │ RAMP liable?    NO — force majeure + Partner was    │
  │                 approving unsafe content             │
  │ Partner liable? YES — failed to follow content      │
  │                 safety guidelines, approved content  │
  │                 that triggered enforcement           │
  │ End-Client?     YES — content strategy was overly   │
  │                 promotional                          │
  │                                                     │
  │ RAMP's rights:                                      │
  │ • Immediate suspension of Partner's access          │
  │   (systemic risk clause)                            │
  │ • Written notice within 24 hours                    │
  │ • Partner has 15 days to cure (demonstrate          │
  │   corrective action) or agreement terminates        │
  │ • No avatar replacements (content-related ban)      │
  │ • Partner indemnifies RAMP for any impact on        │
  │   other partners sharing infrastructure             │
  └─────────────────────────────────────────────────────┘
```

**Key point:** Mass bans triggered by a Partner's poor content approval practices are NOT pure force majeure — they indicate Partner negligence. RAMP can suspend immediately to protect other partners on the platform.

---

### Scenario 5: End-Client Claims Defamation

**Situation:** An End-Client's competitor claims that content posted through the platform is defamatory.

```
Timeline:
  Day 0: Comment posted comparing Competitor X unfavorably
  Day 30: Competitor X sends cease-and-desist to... whom?

Liability analysis:
  ┌─────────────────────────────────────────────────────┐
  │ Content was approved by Partner's operator           │
  │ Content strategy was End-Client's decision          │
  │                                                     │
  │ If C&D sent to RAMP:                                │
  │   → RAMP forwards to Partner                        │
  │   → Partner indemnifies RAMP (per agreement)        │
  │                                                     │
  │ If C&D sent to Partner:                             │
  │   → Partner handles directly                        │
  │   → Partner may seek indemnification from           │
  │     End-Client (per Partner's agreement)            │
  │                                                     │
  │ If lawsuit filed:                                   │
  │   → Partner indemnifies RAMP for legal costs        │
  │   → End-Client indemnifies Partner (if Partner's    │
  │     agreement includes this clause)                 │
  │                                                     │
  │ RAMP's role: provide audit logs proving content     │
  │ was approved by Partner's operator (evidence chain) │
  └─────────────────────────────────────────────────────┘
```

**Key point:** RAMP's audit logs are the critical evidence. They prove RAMP did not author or approve the content — a human at the Partner's organization did.

---

## Liability Flow Diagram

```
                    ┌──────────────────────┐
                    │   EXTERNAL EVENT     │
                    │  (ban, removal, API  │
                    │   change, lawsuit)   │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │  CLASSIFY THE EVENT  │
                    └──────────┬───────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
   │ PLATFORM     │  │ CONTENT      │  │ FORCE        │
   │ FAILURE      │  │ LIABILITY    │  │ MAJEURE      │
   │              │  │              │  │              │
   │ (RAMP bug,   │  │ (defamation, │  │ (Reddit ban, │
   │  data breach, │  │  FTC issue,  │  │  API change, │
   │  IP issue)   │  │  mod removal │  │  ToS update) │
   │              │  │  due to      │  │              │
   │              │  │  content)    │  │              │
   └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
          │                  │                  │
          ▼                  ▼                  ▼
   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
   │ RAMP LIABLE  │  │ WHO APPROVED │  │ NO PARTY     │
   │              │  │ THE CONTENT? │  │ LIABLE        │
   │ Cap: 3 months│  │              │  │              │
   │ of fees      │  │ Partner's    │  │ Each party   │
   │              │  │ operator →   │  │ bears own    │
   │ RAMP fixes + │  │ Partner      │  │ losses       │
   │ SLA credits  │  │ liable       │  │              │
   │ (if in SLA)  │  │              │  │ RAMP adapts  │
   │              │  │ End-Client   │  │ with          │
   │              │  │ strategy →   │  │ reasonable   │
   │              │  │ End-Client   │  │ speed        │
   │              │  │ liable (via  │  │              │
   │              │  │ Partner)     │  │              │
   └──────────────┘  └──────────────┘  └──────────────┘
```

---

## Contractual Chain Requirements

For the liability model to work, each layer must have proper agreements in place:

### RAMP ↔ Partner Agreement (exists: `legal_term_sheet.md`)

Must include:
- [x] Platform risk acceptance clause
- [x] Content approval = liability transfer
- [x] Force majeure definition (Platform Enforcement Events)
- [x] Liability cap (3 months of fees)
- [x] No consequential damages
- [x] Partner indemnifies RAMP for content claims
- [x] RAMP indemnifies Partner for platform IP issues
- [x] Mechanism confidentiality (NDA)
- [x] Immediate suspension right (systemic risk)
- [x] Audit log availability

### Partner ↔ End-Client Agreement (Partner's responsibility to draft)

Must include (RAMP provides template/guidance):
- [ ] Platform risk acceptance (Reddit enforcement acknowledged)
- [ ] Content approval = End-Client's liability
- [ ] Avatars are service access, not property (no refund on ban)
- [ ] Platform Enforcement Events = force majeure (not compensable)
- [ ] FTC/advertising compliance is End-Client's responsibility
- [ ] Liability cap (Partner defines their own)
- [ ] No consequential damages
- [ ] End-Client indemnifies Partner for content claims
- [ ] Confidentiality (never describe mechanism externally)
- [ ] Termination provisions

---

## Summary Table

| Liability Category | RAMP | Partner | End-Client |
|-------------------|------|---------|------------|
| Platform uptime (SLA) | ✅ LIABLE (capped) | — | — |
| Data security breach (RAMP's fault) | ✅ LIABLE (capped) | — | — |
| Platform IP infringement | ✅ LIABLE (capped) | — | — |
| Content approved and published | — | ✅ LIABLE | ✅ LIABLE (via Partner) |
| FTC/advertising compliance | — | ✅ LIABLE (territory) | ✅ LIABLE (content) |
| End-Client relationship issues | — | ✅ LIABLE | — |
| Mechanism confidentiality breach | — | ✅ LIABLE | — |
| Content strategy decisions | — | — | ✅ LIABLE |
| Brand guideline violations | — | — | ✅ LIABLE |
| Reddit account ban (force majeure) | ❌ NOT LIABLE | ❌ NOT LIABLE | ❌ NOT LIABLE |
| Reddit API change (force majeure) | ❌ NOT LIABLE | ❌ NOT LIABLE | ❌ NOT LIABLE |
| Mod content removal | ❌ NOT LIABLE | ⚠️ OPERATIONAL | ⚠️ OPERATIONAL |
| Mass ban (systemic risk) | ❌ NOT LIABLE | ✅ LIABLE (if negligent) | ✅ LIABLE (if strategy caused it) |
| Consequential damages | ❌ EXCLUDED | ❌ EXCLUDED | ❌ EXCLUDED |

---

## Implementation Notes for Legal Counsel

1. **Template End-Client Agreement:** RAMP should provide Partners with a template End-Client agreement that includes all required clauses. Partners can customize but cannot remove liability transfer provisions.

2. **Audit Log Integrity:** Audit logs must be tamper-evident (append-only, hash-chained or similar). They are the primary evidence in any liability dispute.

3. **Approval Workflow Enforcement:** The platform should not allow content to be published without going through the approval workflow. Bypassing approval (if technically possible) would break the liability transfer chain.

4. **Partner Compliance Monitoring:** RAMP should periodically verify that Partners have proper End-Client agreements in place. Failure to maintain agreements = material breach.

5. **Insurance Recommendation:** Both RAMP and Partners should carry professional liability (E&O) insurance. RAMP's policy should cover technology provider risks; Partner's policy should cover content and advertising claims.

---

*Document version: 1.0*
*Last updated: Liability allocation model for legal counsel review*
*Referenced by: Task 5.2*
*Depends on: `legal_term_sheet.md` (Section 6)*
*Next step: Review with legal counsel, then use as basis for Task 5.3 (NDA clause) and Task 5.5 (suspension policy)*
