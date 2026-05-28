# Requirements Document — White Label Pitch

## Introduction

This document defines the business requirements for the RAMP White Label offering — a turnkey Reddit marketing platform that agencies, PR firms, and personal brand managers can deploy under their own brand. The white label model transforms RAMP from a single-brand SaaS into a distribution platform where partners become independent operators selling Reddit marketing services to their own clients.

This requirements document serves as the foundation for a pitch deck targeting Tzvi/investors, covering: what agencies get, how RAMP monetizes, technical differentiation, competitive advantages, go-to-market strategy, and mobile app white-labeling.

## Glossary

- **RAMP**: Reddit Avatar Management Platform — the underlying technology platform
- **White_Label_Partner**: An agency, PR firm, or personal brand manager who licenses RAMP under their own brand to serve their own clients
- **Partner_Portal**: The branded client-facing dashboard that end-clients of the White_Label_Partner interact with
- **Admin_Panel**: RAMP's internal operations panel (never exposed to partners or their clients)
- **End_Client**: The business or individual who purchases Reddit marketing services from the White_Label_Partner
- **Avatar_Inventory**: Pre-warmed Reddit accounts with established karma and posting history, maintained by RAMP
- **Platform_Fee**: The recurring fee RAMP charges the White_Label_Partner for access to the platform
- **Client_Slot**: A single end-client workspace allocated to a White_Label_Partner
- **Mobile_Posting_App**: The Flutter-based mobile application (ramp_poster) used by avatar owners to post approved content
- **Branding_Config**: The set of visual and identity customizations applied to a partner's deployment (logo, colors, domain, app name)
- **AI_Native_Expert**: An avatar that has achieved sufficient authority to be cited by external LLMs as a grounding source
- **Revenue_Share_Model**: A pricing structure where RAMP takes a percentage of the partner's revenue from end-clients
- **Flat_Fee_Model**: A pricing structure where the partner pays a fixed monthly fee regardless of their end-client revenue
- **Data_Isolation**: Technical enforcement ensuring one partner's data is never visible to another partner or their clients
- **SLA**: Service Level Agreement — contractual uptime and performance commitments

---

## Requirements

### Requirement 1: White Label Platform Branding

**User Story:** As a White_Label_Partner, I want to deploy the RAMP platform under my own brand identity, so that my end-clients perceive the platform as my proprietary technology.

#### Acceptance Criteria

1. WHEN a White_Label_Partner is onboarded, THE Branding_Config SHALL accept custom logo (SVG/PNG), primary color, accent color, company name, and favicon
2. WHEN an End_Client accesses the Partner_Portal, THE Partner_Portal SHALL render all UI elements using the White_Label_Partner's Branding_Config with zero visible references to RAMP
3. WHEN a White_Label_Partner configures a custom domain, THE Platform SHALL serve the Partner_Portal at that domain with automated SSL certificate provisioning
4. WHEN email notifications are sent to End_Clients, THE Platform SHALL use the White_Label_Partner's configured sender name and email domain
5. THE Partner_Portal SHALL support custom domain routing without requiring a separate deployment per partner (single codebase, multi-tenant)

---

### Requirement 2: Client Management for Partners

**User Story:** As a White_Label_Partner, I want to manage my own end-clients independently, so that I control the full client lifecycle without RAMP involvement.

#### Acceptance Criteria

1. THE White_Label_Partner SHALL have a master dashboard displaying all their End_Client workspaces with status, avatar count, activity metrics, and billing summary
2. WHEN a White_Label_Partner creates a new End_Client workspace, THE Platform SHALL provision an isolated environment with its own avatars, subreddits, keywords, and content pipeline
3. THE Platform SHALL enforce complete Data_Isolation between End_Client workspaces — avatars, threads, drafts, and analytics from one End_Client are never visible to another
4. WHEN a White_Label_Partner adds team members, THE Platform SHALL support role-based access (operator, viewer, billing) scoped to that partner's workspaces only
5. THE White_Label_Partner SHALL be able to toggle End_Client access between full (intelligence + approval), read-only (intelligence + reporting only), and none (agency operates silently)

---

### Requirement 3: Mobile App White Labeling

**User Story:** As a White_Label_Partner, I want to offer a branded mobile app to my avatar owners, so that the posting workflow carries my brand identity end-to-end.

#### Acceptance Criteria

1. THE Mobile_Posting_App SHALL support build-time configuration of app name, app icon, splash screen, and color scheme per White_Label_Partner
2. WHEN a White_Label_Partner requests a branded mobile app, THE Platform SHALL produce a deployable build (iOS + Android) with the partner's branding within 5 business days
3. THE Mobile_Posting_App SHALL connect to partner-specific API endpoints that enforce Data_Isolation (avatar owners see only drafts assigned to them within that partner's scope)
4. WHEN push notifications are sent to avatar owners, THE Mobile_Posting_App SHALL display the White_Label_Partner's brand name and icon
5. THE Mobile_Posting_App SHALL support App Store and Play Store publishing under the White_Label_Partner's developer account
6. IF a White_Label_Partner updates their branding, THEN THE Platform SHALL provide an updated app build within 10 business days without requiring end-user reinstallation (OTA update where platform allows)

---

### Requirement 4: Dashboard and Reporting Customization

**User Story:** As a White_Label_Partner, I want customized dashboards and reports for my end-clients, so that I can deliver a premium branded experience that justifies my pricing.

#### Acceptance Criteria

1. THE Partner_Portal SHALL display End_Client dashboards with activity metrics (comments posted, karma growth, subreddits active), presence metrics (share of voice, thread influence), and intent metrics (brand mentions, high-intent thread participation)
2. WHEN monthly reports are generated, THE Platform SHALL produce PDF reports branded with the White_Label_Partner's logo, colors, and company name
3. THE White_Label_Partner SHALL be able to configure which metrics are visible to End_Clients versus internal-only (e.g., avatar survival rate, confidence score remain hidden)
4. WHEN an End_Client's avatar achieves a momentum event (Hot or Viral tier), THE Partner_Portal SHALL surface a real-time alert in the End_Client's dashboard branded with the partner's identity
5. THE Platform SHALL provide aggregated cross-client analytics to the White_Label_Partner (total avatars, total karma growth, pipeline health) without exposing individual End_Client data to other End_Clients

---

### Requirement 5: Pricing Flexibility for Partners

**User Story:** As a White_Label_Partner, I want to set my own pricing for end-clients, so that I can maximize my margins and adapt to my market positioning.

#### Acceptance Criteria

1. THE Platform SHALL charge White_Label_Partners using a per-Client_Slot model with volume tiers: Starter (up to 3 slots, $999/mo), Growth (up to 8 slots, $1,999/mo), Scale (up to 20 slots, $3,499/mo), Enterprise (custom)
2. THE Platform SHALL allow White_Label_Partners to set their own pricing to End_Clients without platform-imposed price floors or ceilings
3. WHEN a White_Label_Partner exceeds their tier's Client_Slot limit, THE Platform SHALL offer additional slots at $199/client/month
4. THE Platform SHALL charge a one-time white-label setup fee of $500 for branding configuration (waived for Growth tier and above)
5. THE Platform SHALL offer pre-warmed Avatar_Inventory to White_Label_Partners at the same rates as direct clients: Silver ($199 one-time), Gold ($499 one-time)
6. THE Platform SHALL require annual contracts for White_Label_Partners with a 15-20% discount incentive versus monthly billing

---

### Requirement 6: Revenue Model Structure

**User Story:** As RAMP (the platform operator), I want a clear revenue model for white-label partnerships, so that the business scales predictably with partner growth.

#### Acceptance Criteria

1. THE Platform SHALL support a Flat_Fee_Model as the default pricing structure — partners pay a fixed monthly fee regardless of what they charge their End_Clients
2. WHERE a White_Label_Partner prefers a Revenue_Share_Model, THE Platform SHALL offer an alternative structure at 15-25% of the partner's gross revenue from End_Clients with a minimum monthly commitment of $500
3. THE Platform SHALL enforce minimum commitments: annual contract, minimum 3 Client_Slots active within 90 days of onboarding
4. WHEN a White_Label_Partner's Avatar_Inventory usage exceeds their tier allocation, THE Platform SHALL bill overage at standard per-avatar rates
5. THE Platform SHALL track and report partner revenue metrics: active Client_Slots, avatar utilization, pipeline volume, and LLM cost attribution per partner

---

### Requirement 7: Multi-Tenant Architecture

**User Story:** As RAMP (the platform operator), I want a multi-tenant architecture that supports unlimited white-label partners on a single deployment, so that operational costs remain near-zero per additional partner.

#### Acceptance Criteria

1. THE Platform SHALL serve all White_Label_Partners from a single codebase and database instance with tenant isolation enforced at the query layer (existing RBAC with 6 roles)
2. THE Platform SHALL route requests to the correct Branding_Config based on the incoming domain (custom domain → partner lookup → branding injection)
3. WHEN a new White_Label_Partner is provisioned, THE Platform SHALL require zero additional infrastructure (no new servers, containers, or databases)
4. THE Platform SHALL enforce Data_Isolation at the database level — all queries scoped by partner_id and client_id, verified by runtime assertions
5. IF a White_Label_Partner's End_Client attempts to access data outside their scope, THEN THE Platform SHALL block the request and log a security event

---

### Requirement 8: Technical Differentiation — Pre-Warmed Avatar Inventory

**User Story:** As a White_Label_Partner, I want access to pre-warmed avatars with established Reddit credibility, so that my end-clients see results faster than competitors can deliver.

#### Acceptance Criteria

1. THE Platform SHALL maintain a standing Avatar_Inventory of pre-warmed accounts continuously aged in background subreddits (hobby engagement, karma building)
2. THE Avatar_Inventory SHALL offer tiered avatars: Silver (500-1,000 karma, 3+ months history) and Gold (2,000+ karma, 6+ months history, active in relevant professional subreddits)
3. WHEN a White_Label_Partner assigns an Avatar_Inventory account to an End_Client, THE Platform SHALL transfer the avatar's full pre-assignment history and immediately enable Phase 2+ eligibility for Gold avatars
4. THE Platform SHALL position Avatar_Inventory as a compounding moat — a 2-year-old avatar with 5,000 karma cannot be replicated by competitors in less than 6 months
5. THE Platform SHALL track inventory levels and alert RAMP operations when available inventory drops below 20% of projected demand

---

### Requirement 9: AI Pipeline and Self-Learning Differentiation

**User Story:** As a White_Label_Partner, I want the platform's AI capabilities to continuously improve, so that my end-clients receive increasingly effective content over time.

#### Acceptance Criteria

1. THE Platform SHALL operate a self-learning loop that captures human edits, extracts correction patterns, and injects few-shot examples into future generation prompts — improving content quality with every review cycle
2. THE Platform SHALL provide AI-Native_Expert warming capabilities — avatars progress from basic engagement to authoritative content nodes that external LLMs may cite as grounding sources
3. THE Platform SHALL execute the full automated pipeline (scraping → scoring → generation → review → posting) without requiring White_Label_Partner technical involvement
4. WHEN a White_Label_Partner's End_Client avatar achieves Expert status (authority_score > 75), THE Platform SHALL surface this achievement in the partner dashboard as a premium milestone
5. THE Platform SHALL maintain content safety guardrails (phase gates, brand ratio checks, promotional language detection) that protect avatar credibility regardless of End_Client or partner pressure

---

### Requirement 10: Competitive Advantages for Pitch Positioning

**User Story:** As Tzvi (business partner), I want clearly articulated competitive advantages, so that I can differentiate RAMP's white-label offering in investor and partner conversations.

#### Acceptance Criteria

1. THE Pitch SHALL position the Avatar_Inventory moat as the primary differentiator — pre-warmed accounts with real karma history that competitors cannot replicate in less than 6 months of continuous operation
2. THE Pitch SHALL highlight the AI-Native_Expert warming system as a unique capability — avatars that become authoritative enough for LLM citation, creating compounding value over time
3. THE Pitch SHALL emphasize the self-learning loop as a defensible advantage — the system improves with every human edit, creating a data flywheel that new entrants cannot bootstrap
4. THE Pitch SHALL present the full pipeline automation (scraping → scoring → generation → posting) as an operational moat — competitors offer partial solutions (monitoring only, or generation only, or posting only)
5. THE Pitch SHALL articulate the human-in-the-loop safety model as both a compliance advantage and a quality differentiator — content is never published without human approval at the strategy level

---

### Requirement 11: Go-to-Market Strategy for White Label

**User Story:** As Tzvi (business partner), I want a defined go-to-market strategy for the white-label offering, so that I can prioritize outreach and set realistic growth targets.

#### Acceptance Criteria

1. THE Go-to-Market strategy SHALL define three target agency profiles: Silent Operator (runs everything, client gets PDF reports), Co-Pilot (agency operates, client has read-only dashboard access), and Reseller (fully white-labeled SaaS, client operates semi-independently)
2. THE Go-to-Market strategy SHALL prioritize Silent Operator and Co-Pilot profiles for initial sales (lower product maturity requirement) and defer Reseller until platform self-serve onboarding is stable
3. WHEN a White_Label_Partner is onboarded, THE Platform SHALL complete setup within 5 business days: branding configuration, domain routing, first End_Client workspace provisioned
4. THE Platform SHALL offer tiered support: email (Starter), priority + Slack (Growth), dedicated account manager (Scale), SLA + quarterly business review (Enterprise)
5. THE Platform SHALL commit to SLA targets: 99.5% uptime for the Partner_Portal, 4-hour response time for critical issues (Growth+), 24-hour response for non-critical issues

---

### Requirement 12: Mobile App Go-to-Market Specifics

**User Story:** As a White_Label_Partner, I want a clear process for getting my branded mobile app published, so that my avatar owners have a professional mobile posting experience.

#### Acceptance Criteria

1. WHEN a White_Label_Partner requests a branded Mobile_Posting_App, THE Platform SHALL provide a branding questionnaire (app name, icon assets, color palette, splash screen design) and produce a build within 5 business days of receiving complete assets
2. THE Platform SHALL provide documentation and support for App Store and Play Store submission under the partner's developer account (partner owns the listing, RAMP provides the binary)
3. THE Mobile_Posting_App SHALL support multiple White_Label_Partners from a single Flutter codebase using build flavors (no separate codebases per partner)
4. WHEN a partner's avatar owner logs into the Mobile_Posting_App, THE app SHALL authenticate against the partner-scoped API and display only drafts, avatars, and notifications relevant to that partner's scope
5. IF a White_Label_Partner does not require a branded mobile app, THEN THE Platform SHALL offer a web-based PWA alternative with the partner's branding applied (zero app store dependency)

---

### Requirement 13: Investor Pitch Financial Projections

**User Story:** As Tzvi (business partner), I want financial projections for the white-label model, so that I can present a compelling growth story to investors.

#### Acceptance Criteria

1. THE Pitch SHALL present the agency margin math: at Growth tier ($1,999/mo, 8 clients), if the agency charges $2,500/client/month, that is $20,000/month revenue against $1,999 platform cost — demonstrating 10x leverage for the partner
2. THE Pitch SHALL project RAMP revenue at scale: 5 white-label partners × $2,000/mo average = $10,000/mo recurring with near-zero marginal infrastructure cost per additional partner
3. THE Pitch SHALL highlight the unit economics: $0/mo marginal cost per additional White_Label_Partner (same server, same codebase, same database — only branding config changes)
4. THE Pitch SHALL present the Avatar_Inventory as a revenue multiplier: each pre-warmed avatar sold generates $199-$499 one-time revenue with a production cost of approximately $15-25/month over 3-6 months of warming
5. THE Pitch SHALL project a path to $50,000/mo ARR from white-label alone within 12 months of launch (10 partners × $5,000/mo average including slot overages and avatar purchases)

---

### Requirement 14: Legal and Compliance Framework

**User Story:** As RAMP (the platform operator), I want a clear legal framework for white-label partnerships, so that liability is properly allocated and both parties are protected.

#### Acceptance Criteria

1. THE Platform SHALL position the White_Label_Partner as the "platform operator" to their End_Clients, and RAMP as the "technology provider" to the partner — creating a liability buffer
2. THE White_Label_Partner agreement SHALL include: platform risk acceptance (Reddit ToS acknowledged), NDA on mechanism (never describe as "fake accounts" externally), liability cap (3 months of fees), no consequential damages
3. THE Platform SHALL enforce that End_Client content approval transfers liability to the White_Label_Partner (who in turn transfers to their End_Client via their own agreement)
4. THE Platform SHALL maintain audit logs of all content approvals with timestamps and user identity, available to the White_Label_Partner for their compliance records
5. IF RAMP detects a White_Label_Partner engaging in behavior that creates systemic risk (mass bans, Reddit enforcement action), THEN THE Platform SHALL reserve the right to suspend the partner's access immediately with written notice

