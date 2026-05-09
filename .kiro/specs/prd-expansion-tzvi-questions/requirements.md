# Requirements Document

## Introduction

This specification addresses three gaps identified by Tzvi during PRD review of the RAMP (Reddit Avatar Management Platform):

1. **Avatar Lifecycle Formalization** — The 3-phase warming system exists in basic form but lacks formal phase transition rules, inventory classification, and eligibility gating logic.
2. **Client-Side Compliance Framework** — The system enforces technical guardrails, but the client-facing contractual obligations, acceptance flows, and liability transfer mechanisms need formalization in the platform.
3. **Client-Facing Success Metrics** — Internal ops KPIs exist, but clients need visibility into engagement performance, avatar health, and ROI indicators through a dedicated reporting interface.

Additionally, this spec covers new PRD elements that need formalization:
4. **Content Workflow Inputs** — The 4-input content generation system (Persona Layer, Subreddit Historical Intelligence, Subreddit Tone Fingerprint, External Intelligence Layer).
5. **Personal Brand Module** (Phase 2) — Individual professionals connecting their own Reddit accounts.
6. **Competitor & Mentor Intelligence** (Phase 2) — Monitoring public Reddit activity of competitors and thought leaders.
7. **Budgeting & Billing Enforcement** — Tier-based action limits, usage tracking, and budget alerts.

## Glossary

- **RAMP**: Reddit Avatar Management Platform — the overall system
- **Avatar**: A managed Reddit account used for community engagement (legally: "Digital Asset")
- **Warming_Phase**: One of three lifecycle stages an avatar progresses through (Credibility, Seeding, Integration)
- **Phase_Gate**: The set of conditions that must be met before an avatar transitions to the next warming phase
- **Inventory_Tier**: Classification of avatar readiness (Silver or Gold) based on karma and account age
- **Client_Portal**: The client-facing interface showing performance metrics and compliance status
- **Compliance_Acceptance**: The digital record of a client acknowledging platform terms and liability split
- **Guardrail**: A system-enforced content rule that prevents policy violations
- **Brand_Mention_Ratio**: The percentage of an avatar's recent comments that reference the client's brand
- **Tone_Fingerprint**: A statistical profile of writing style characteristics for a subreddit (length, formality, humor, jargon)
- **Historical_Intelligence**: A 12-month lookback analysis of top-performing content in a subreddit
- **External_Intelligence_Layer**: Optional client-provided context (blog posts, whitepapers, product updates) used to inform content generation
- **Personal_Brand_Module**: A feature allowing individual professionals to connect their own Reddit account for AI-assisted engagement
- **Tracked_Avatar**: A read-only avatar type used for monitoring competitor/mentor Reddit activity without posting
- **Budget_Alert**: A notification triggered when a client approaches or exceeds their plan's action limits
- **Genuine_Community_Member_Score**: A rubric-based quality score evaluating whether generated content reads as authentic community participation

---

## Requirements

### Requirement 1: Avatar Phase Transition Rules

**User Story:** As an operations manager, I want the system to enforce formal phase transition rules for avatars, so that no avatar engages in brand-related activity before it has sufficient credibility.

#### Acceptance Criteria

1. WHILE an Avatar is in Warming_Phase 1 (Credibility), THE RAMP SHALL restrict that Avatar to posting only in subreddits tagged as hobby or general_professional in the system configuration, with zero brand mentions.
2. WHEN an Avatar has accumulated at least 500 karma AND has an account age of at least 3 months, THE Phase_Gate SHALL evaluate eligibility for transition to Warming_Phase 2 (Seeding).
3. WHEN an Avatar has accumulated at least 2000 karma AND has an account age of at least 6 months AND has maintained a removal rate below 5% over the trailing 30-day window, THE Phase_Gate SHALL evaluate eligibility for transition to Warming_Phase 3 (Integration).
4. WHILE an Avatar is in Warming_Phase 2 (Seeding), THE RAMP SHALL permit external source citations but SHALL reject any content containing direct brand links or brand mentions.
5. WHILE an Avatar is in Warming_Phase 3 (Integration), WHEN a thread contains at least one of the client's configured keywords, THE RAMP SHALL permit brand mentions only IF the Brand_Mention_Ratio for that Avatar is below 15% for the trailing 7-day window.
6. WHEN a phase transition evaluation succeeds, THE RAMP SHALL log the transition event with timestamp, previous phase, new phase, and qualifying metrics to the activity feed.
7. IF an Avatar's karma decreases by 100 or more within a 24-hour period, THEN THE RAMP SHALL flag the Avatar for manual review and pause its content generation.
8. IF a phase transition evaluation determines that the Avatar does not meet all required thresholds for the next phase, THEN THE Phase_Gate SHALL retain the Avatar in its current phase and log the failed evaluation attempt with the unmet criteria to the activity feed.
9. WHILE an Avatar is in Warming_Phase 3 (Integration), IF the Brand_Mention_Ratio for that Avatar reaches or exceeds 15% for the trailing 7-day window, THEN THE RAMP SHALL reject further brand-mentioning content until the ratio falls below 15%.

---

### Requirement 2: Avatar Inventory Classification

**User Story:** As a sales manager, I want avatars classified into inventory tiers, so that I can price and allocate pre-warmed avatars to clients based on their readiness level.

#### Acceptance Criteria

1. THE RAMP SHALL classify avatars with combined karma (post karma + comment karma) of 500–1999 and account age of 3–5 months as Silver Inventory_Tier.
2. THE RAMP SHALL classify avatars with combined karma (post karma + comment karma) of 2000 or more and account age of 6 months or more as Gold Inventory_Tier.
3. THE RAMP SHALL classify avatars that do not meet Silver Inventory_Tier thresholds (combined karma below 500 or account age below 3 months) as Unclassified, indicating they are not available for client assignment.
4. WHEN the RAMP completes a periodic avatar health check or karma snapshot, THE RAMP SHALL re-evaluate the avatar's Inventory_Tier classification within 24 hours of the data update.
5. IF an avatar's combined karma drops below the minimum threshold for its current Inventory_Tier, THEN THE RAMP SHALL downgrade the avatar to the appropriate lower tier and log the tier change with timestamp, previous tier, new tier, and triggering metric values.
6. THE RAMP SHALL display the current Inventory_Tier on the avatar detail page in the admin panel, including the tier label, qualifying karma value, and account age.
7. WHEN a client is onboarded, THE RAMP SHALL allow assignment of avatars from the available inventory pool where the avatar's Inventory_Tier is equal to or higher than the tier included in the client's plan (Seed and Starter plans require Silver or above; Growth and Scale plans require Gold).
8. IF no avatars matching the required Inventory_Tier are available in the pool at assignment time, THEN THE RAMP SHALL display a notification indicating insufficient inventory and prevent assignment until matching avatars become available.

---

### Requirement 3: Client Compliance Acceptance Flow

**User Story:** As a business owner, I want clients to digitally accept compliance terms before service activation, so that liability is formally transferred and documented.

#### Acceptance Criteria

1. WHEN a new client record is created and the client logs in for the first time, THE RAMP SHALL present a Compliance_Acceptance screen requiring acknowledgment of platform risk terms before pipeline activation.
2. THE Compliance_Acceptance SHALL present each of the following as a separate acknowledgment item requiring individual confirmation: platform enforcement risk (account actions are force majeure), avatars as service access (not property), content approval as liability transfer, FTC/advertising compliance as client responsibility, and NDA on engagement mechanism. All items must be confirmed before the acceptance is considered complete.
3. WHEN a client confirms all acknowledgment items and submits the Compliance_Acceptance, THE RAMP SHALL store the acceptance timestamp, client identity, IP address, and document version in an append-only audit record that does not permit update or deletion operations.
4. IF a client has not completed Compliance_Acceptance, THEN THE RAMP SHALL block pipeline activation for that client and display a pending compliance status.
5. WHEN compliance terms are updated to a new version, THE RAMP SHALL mark all active clients as requiring re-acceptance and suspend pipeline execution for any client who has not re-accepted within 30 days of the version update or before their next billing cycle, whichever comes later.
6. THE RAMP SHALL provide an admin view showing compliance acceptance status for all clients with timestamps and document versions.
7. IF a client's pipeline is suspended due to pending re-acceptance of updated compliance terms, THEN THE RAMP SHALL display a notification to the client indicating that updated terms require acceptance before pipeline operations resume.

---

### Requirement 4: Client Guardrail Override Acknowledgment

**User Story:** As an operations manager, I want guardrail overrides to require explicit client acknowledgment, so that risk acceptance is documented per-instance.

#### Acceptance Criteria

1. WHEN a client requests a guardrail override (e.g., increasing Brand_Mention_Ratio threshold, posting in a restricted subreddit), THE RAMP SHALL present a confirmation screen displaying the specific guardrail being overridden, the current default value, the requested new value, and a plain-language description of the associated risk, and SHALL require the client to provide explicit consent (e.g., typing their name or checking a confirmation box) before activating the override.
2. IF a client does not complete the override acknowledgment within 30 minutes of initiating the request, THEN THE RAMP SHALL expire the pending request and retain the existing default guardrail value.
3. THE RAMP SHALL log each guardrail override with: client identity, override type, previous value, new value, acknowledgment timestamp, and expiration date, and SHALL retain override logs for a minimum of 24 months.
4. WHEN a guardrail override is activated, THE RAMP SHALL enforce a maximum override duration of 90 days, requiring the client to set an expiration date no later than 90 days from activation.
5. WHILE a guardrail override is active, THE RAMP SHALL display a persistent, non-dismissible indicator on the client's dashboard and in the admin panel showing the override type and expiration date.
6. WHEN a guardrail override expiration date is reached, THE RAMP SHALL automatically revert to the default guardrail value within 60 seconds and notify the client via in-app notification and email that the override has expired and the default value has been restored.
7. WHEN an admin or the client revokes a guardrail override before its expiration date, THE RAMP SHALL immediately revert to the default guardrail value, log the early revocation with the revoking user's identity and timestamp, and notify the client via in-app notification and email.

---

### Requirement 5: Client-Facing Performance Dashboard

**User Story:** As a client, I want to see engagement performance metrics for my campaign, so that I can evaluate ROI and make informed decisions about content strategy.

#### Acceptance Criteria

1. THE Client_Portal SHALL display per-avatar engagement metrics including: total karma earned, comments posted, average karma per comment, and comment survival rate (percentage of comments not removed by moderators).
2. THE Client_Portal SHALL display per-subreddit performance metrics including: threads engaged, average comment score, and top 5 performing comments ranked by karma earned.
3. THE Client_Portal SHALL display campaign-level metrics including: total engagements this period, brand mention count (Phase 3 only), and estimated reach calculated as the sum of upvote counts on all engaged threads.
4. WHEN a reporting period ends (weekly, Monday 00:00 UTC to Sunday 23:59 UTC), THE RAMP SHALL generate a performance summary accessible in the Client_Portal with week-over-week trend indicators showing percentage change and directional classification (up/down/flat).
5. THE Client_Portal SHALL display avatar health indicators including: current Warming_Phase, Inventory_Tier, days until next phase eligibility, and any active flags or pauses.
6. IF a comment is removed by a moderator, THEN THE Client_Portal SHALL reflect the removal in the survival rate metric within 24 hours.
7. THE Client_Portal SHALL enforce client data isolation such that each client can only view metrics for their own avatars and campaigns.
8. IF a client has no engagement data for the current period, THEN THE Client_Portal SHALL display an empty state with a message indicating no activity has been recorded and showing the date range of the current period.

---

### Requirement 6: Client ROI Indicators

**User Story:** As a client, I want to understand the return on my investment, so that I can justify continued spend on the engagement service.

#### Acceptance Criteria

1. THE Client_Portal SHALL display a cost-per-engagement metric calculated as monthly subscription fee divided by total successful engagements (comments not removed) within the most recent rolling 30-day window, rounded to 2 decimal places.
2. IF a client has zero successful engagements in the rolling 30-day window, THEN THE Client_Portal SHALL display the cost-per-engagement as the full monthly subscription fee with an indication that no engagements have been recorded.
3. THE Client_Portal SHALL display an engagement quality score as a numeric ratio of average karma earned per comment (rolling 30 days) divided by the subreddit median karma per comment, where a value of 1.0 equals subreddit-average performance.
4. WHEN an avatar reaches Phase 3 (Integration), THE Client_Portal SHALL display brand visibility metrics including: brand mention impressions (calculated as the sum of thread view counts at the time each brand-mentioning comment was posted) and brand mention sentiment classified as positive, neutral, or negative per mention, aggregated over the most recent rolling 30-day window.
5. THE Client_Portal SHALL display a month-over-month growth chart covering the most recent 6 months, showing cumulative karma, total engagement count, and avatar maturity expressed as the count of avatars in each phase (Phase 1, Phase 2, Phase 3).

---

### Requirement 7: Content Generation Multi-Input System

**User Story:** As an operations manager, I want content generation to incorporate multiple intelligence inputs simultaneously, so that generated comments are contextually appropriate and high-quality.

#### Acceptance Criteria

1. WHEN generating a comment, THE RAMP SHALL assemble context from four input layers: Persona Layer (avatar voice profile), Subreddit Historical_Intelligence (12-month top content analysis), Subreddit Tone_Fingerprint (style calibration), and External_Intelligence_Layer (optional client-provided materials). IF one or more non-optional layers contain insufficient data (fewer than 10 historical comments available), THEN THE RAMP SHALL proceed with available layers and log a warning indicating which layers were incomplete.
2. THE RAMP SHALL maintain a Historical_Intelligence profile per subreddit containing: top 50 comments by karma from the past 12 months, up to 10 common topic clusters derived from those comments, and up to 5 successful argument patterns (defined as patterns appearing in comments with karma above the subreddit median). THE RAMP SHALL refresh this profile at least once every 7 days.
3. THE RAMP SHALL maintain a Tone_Fingerprint per subreddit containing: median comment length in words, formality level on a 1–5 scale (1 = highly informal, 5 = highly formal), humor frequency as a percentage of sampled comments containing humor, jargon density as a percentage of domain-specific terms per comment, and citation patterns (percentage of comments referencing external sources).
4. WHERE a client provides External_Intelligence_Layer materials, THE RAMP SHALL incorporate them into generation context only for Phase 2+ avatars and only when the thread topic shares at least one keyword or topic cluster with the provided materials.
5. WHEN a comment is generated, THE RAMP SHALL score it against a Genuine_Community_Member_Score rubric evaluating five dimensions each scored 1–10: natural language flow (absence of repetitive structures and AI-typical phrasing), topic relevance (comment addresses the thread's subject), length appropriateness (within ±50% of the subreddit Tone_Fingerprint median length), absence of promotional framing (no brand names, CTAs, or marketing language), and factual accuracy (claims are consistent with provided intelligence layers). The overall score SHALL be the unweighted average of the five dimension scores.
6. IF a generated comment scores below 7.0 on the Genuine_Community_Member_Score, THEN THE RAMP SHALL reject it and trigger regeneration with an increased temperature parameter (incremented by 0.1 per attempt from the base value). IF regeneration fails to produce a score of 7.0 or above after 3 attempts, THEN THE RAMP SHALL discard the comment, log the failure with the thread ID and highest score achieved, and skip generation for that thread.

---

### Requirement 8: Content Output Rules

**User Story:** As a compliance officer, I want strict output rules enforced on all generated content, so that comments do not violate platform norms or create legal exposure.

#### Acceptance Criteria

1. THE RAMP SHALL calibrate generated comment length to match the target subreddit's Tone_Fingerprint median length within a 20% tolerance. IF the subreddit has fewer than 10 comments in its Tone_Fingerprint profile, THEN THE RAMP SHALL use a default length range of 50–200 words.
2. WHILE an Avatar is in Warming_Phase 1 or Warming_Phase 2, THE RAMP SHALL reject any generated content containing brand names, product names, or promotional framing (defined as: calls to action, superlative claims about a product/service, discount/offer language, or direct comparisons positioning the client favorably) associated with the client.
3. THE RAMP SHALL reject any generated content containing factual claims about competitors that cannot be attributed to a public source via URL or citation.
4. THE RAMP SHALL reject any generated content containing direct links to client properties unless the Avatar is in Warming_Phase 3 and the Brand_Mention_Ratio is below 15% for the trailing 7-day window.
5. WHEN content is rejected by an output rule, THE RAMP SHALL log the rejection reason, the triggering rule identifier, and the original content for audit purposes.

---

### Requirement 9: Personal Brand Module

**User Story:** As an individual professional, I want to connect my own Reddit account and receive AI-assisted engagement suggestions, so that I can build my professional presence without managing it manually.

#### Acceptance Criteria

1. THE Personal_Brand_Module SHALL allow an individual professional to connect their own Reddit account via OAuth with read and identity scopes.
2. IF the OAuth connection attempt fails or is denied, THEN THE Personal_Brand_Module SHALL display an error message indicating the failure reason and allow the professional to retry without losing previously entered configuration.
3. WHEN a professional connects their account, THE Personal_Brand_Module SHALL prompt the professional to configure up to 10 expertise topics, a preferred tone selection, and up to 10 target subreddits before activating suggestions.
4. WHEN a scheduled scan completes (every 6 hours), THE Personal_Brand_Module SHALL identify thread opportunities matching the professional's expertise topics and present up to 20 suggestions per day, each with a draft response.
5. THE Personal_Brand_Module SHALL track up to 5 mentor accounts (public Reddit users) and include threads where mentors have engaged within the suggestion list.
6. WHEN a reporting period ends (weekly), THE Personal_Brand_Module SHALL generate a performance digest including: threads suggested, responses published, karma earned, and engagement trend comparison against the prior 4-week average.
7. THE Personal_Brand_Module SHALL default to auto-publishing OFF, requiring manual approval for each suggested response.
8. WHERE a professional enables auto-publishing, THE Personal_Brand_Module SHALL enforce a daily cap of 5 auto-published responses, halt auto-publishing for the remainder of the day once the cap is reached, and require re-confirmation every 30 days.

---

### Requirement 10: Competitor and Mentor Intelligence

**User Story:** As a client, I want to monitor competitor and thought leader activity on Reddit, so that I can identify strategic opportunities and understand market positioning.

#### Acceptance Criteria

1. THE RAMP SHALL support a Tracked_Avatar type that monitors public Reddit activity (posts and comments) of specified accounts without posting, polling each monitored account at least once every 6 hours.
2. WHEN a Tracked_Avatar's monitored account posts or comments, THE RAMP SHALL record the activity with: subreddit, timestamp, content summary (maximum 300 characters), karma received, and thread title.
3. WHEN a reporting period ends (weekly, every 7 calendar days), THE RAMP SHALL generate a competitor/mentor intelligence digest including: activity count per subreddit, topics mentioned (extracted from post/comment content), average karma per activity, and subreddits where activity overlaps with the client's configured subreddits.
4. WHEN a Tracked_Avatar's monitored account engages in a thread where at least one of the client's configured keywords (any priority level) appears in the thread title or body, THE RAMP SHALL generate an opportunity alert containing: the matched keyword(s), the monitored account's activity, the thread link, and a suggested engagement angle.
5. THE RAMP SHALL limit Tracked_Avatars to read-only operations and SHALL reject any attempt to post or comment from a Tracked_Avatar, returning an error indication that the avatar is read-only.
6. IF a Tracked_Avatar's monitored account is deleted, suspended, or returns no public activity for 30 consecutive days, THEN THE RAMP SHALL mark the Tracked_Avatar as inactive and notify the client in the next intelligence digest.
7. THE RAMP SHALL support up to 10 Tracked_Avatars per client on Growth tier and above, and SHALL reject creation of a Tracked_Avatar for clients on Seed or Starter tiers with an error indicating the feature requires Growth tier or above.
8. WHEN a client attempts to add a Tracked_Avatar beyond their tier limit, THE RAMP SHALL reject the request with an error indicating the maximum number of Tracked_Avatars has been reached.

---

### Requirement 11: Budget and Usage Tracking

**User Story:** As a client, I want to see my usage against plan limits, so that I can manage my budget and understand when I'm approaching capacity.

#### Acceptance Criteria

1. THE RAMP SHALL track per-client usage metrics per calendar month including: comments generated, comments posted, posts created, LLM tokens consumed, and Reddit API calls made, resetting all counters to zero at 00:00 UTC on the first day of each calendar month.
2. THE RAMP SHALL enforce plan-tier action limits per calendar month: Seed (30 comments), Starter (60 comments), Growth (150 comments + 10 posts), Scale (400 combined actions where each comment, post, or generation counts as one action).
3. WHEN a client reaches 80% of any individual plan limit, THE RAMP SHALL send a Budget_Alert notification to the client and the account manager within 5 minutes of the threshold being crossed.
4. WHEN a client reaches 100% of a plan limit, THE RAMP SHALL pause new comment generation and new post creation while allowing health checks, scraping, and scoring to continue.
5. IF a client exceeds their plan limit due to tasks that were already dispatched to the task queue before the limit was reached, THEN THE RAMP SHALL allow those dispatched tasks to complete but SHALL block creation of new tasks, and SHALL log each over-limit completion as a budget overage event.
6. THE Client_Portal SHALL display a usage dashboard showing: current period usage vs. limits (updated within 60 seconds of any usage change), daily usage bar chart for the current billing period, projected end-of-period usage based on linear extrapolation of the current period's daily average, and days remaining in the current calendar month.
7. WHEN a client's plan limit pause is active and a new calendar month begins, THE RAMP SHALL automatically resume all paused actions and reset usage counters to zero.
8. IF a client upgrades their plan tier mid-cycle, THEN THE RAMP SHALL apply the new tier's limits immediately while preserving the current period's accumulated usage counts.

---

### Requirement 12: Billing Tier Enforcement

**User Story:** As a business owner, I want plan limits enforced automatically, so that resource consumption matches the client's subscription level.

#### Acceptance Criteria

1. THE RAMP SHALL validate avatar count against plan limits: Seed (1 avatar), Starter (3 avatars), Growth (7 avatars), Scale (15 avatars).
2. THE RAMP SHALL validate subreddit count against plan limits: Seed (1 subreddit total), Starter (2 subreddits total combining professional and hobby), Growth (5 subreddits total combining professional and hobby), Scale (up to 50 subreddits total).
3. WHEN a client attempts to add an avatar or subreddit that would exceed their plan's limit for that resource type, THE RAMP SHALL reject the request, display the current plan's capacity for that resource type, and present an upgrade prompt showing the next available tier.
4. WHEN a client upgrades their plan tier, THE RAMP SHALL apply the new tier's resource limits within 60 seconds without requiring pipeline restart, allowing the client to add resources up to the new limits.
5. WHEN a client downgrades their plan tier, THE RAMP SHALL enforce the new tier's limits at the start of the next billing cycle, notify the client at least 7 days before the billing cycle of any resources exceeding the new limits, and deactivate excess resources starting with the most recently created ones.
6. IF a client's plan is downgraded and active comment drafts exist for avatars or subreddits that will be deactivated, THEN THE RAMP SHALL reject those pending drafts and notify the client which drafts were affected.
7. WHEN a client attempts to trigger pipeline actions (comment generation, post creation) that would exceed their plan's monthly action limit, THE RAMP SHALL reject the action and display the current month's usage count against the plan's maximum.
