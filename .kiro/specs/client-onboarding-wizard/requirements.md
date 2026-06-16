# Requirements Document

## Introduction

Build a client-facing AI-driven onboarding wizard that replaces manual client setup. The wizard collects company intelligence, ICP, voice/tone, keywords, and subreddits through a conversational AI-assisted flow. On completion, the system triggers avatar allocation (ops), discovery session (auto), avatar strategy generation, GEO baseline, and first pipeline run. Target: 20-25 minutes to complete. Must feel like a senior strategist intake, not a form.

Two flows: (1) Managed onboarding — ops triggers for new paying clients, (2) Free trial — self-serve intelligence-only trial (14 days, work email required, no posting).

Reference documents:
- `buziness/RAMP_UX_Developer_Spec_v3.txt` — Full UX spec (Section 03: Onboarding Flow)
- `buziness/RAMP_Client_Portal_Implementation_Plan.md` — Implementation phases
- `buziness/Reddit_Avatar_Army_Business_Brief.docx.txt` — Business model + trial flow

## Glossary

- **Onboarding_Wizard**: 6-step client-facing AI-driven setup flow at `/onboard`
- **Company_Intelligence**: Auto-built company profile from URL scraping + AI synthesis
- **Tone_Calibration_Loop**: Iterative process where client rates AI-generated sample sentences (1-5) until 3+ score 4+
- **Quality_Gate**: Server-side check preventing activation if brief is too thin (missing required fields or failed tone calibration)
- **Avatar_Allocation**: Ops process (behind scenes) of assigning pre-warmed or new avatars to a client
- **Avatar_Onboarding**: Automated post-allocation flow: Discovery → Strategy → GEO Baseline → First Pipeline Run
- **Day_1_Report**: Auto-generated Reddit landscape report (competitor presence, share of voice baseline, subreddit map)
- **Intelligence_Trial**: 14-day free trial with full intelligence access (monitoring, scoring, drafts read-only) but no posting
- **Profile_Synthesizer**: AI service that converts scraped website data into structured client profile fields

## Requirements

### Requirement 1: Website Scraping & AI Profile Synthesis (Step 1)

**User Story:** As a new client, I want to enter my company URL and see an auto-generated profile card, so I can verify and correct rather than type from scratch.

#### Acceptance Criteria

1. WHEN the client enters a URL and clicks "Analyze", THE system SHALL scrape the website (home page, about page, product pages) and extract text content within 15 seconds
2. THE Profile_Synthesizer SHALL call an LLM (Gemini Flash) to generate: company_name, product_description, value_proposition, key_differentiators, industry, company_size_estimate from the scraped text
3. THE system SHALL display the synthesized profile as an editable card (not a form) — client reviews and corrects inline
4. IF scraping fails or returns insufficient data, THE system SHALL fall back to manual entry fields with a message "We couldn't auto-detect your profile. Please fill in below."
5. THE client SHALL be able to optionally add a LinkedIn company URL for supplementary data
6. ALL scraped and synthesized data SHALL be stored in the Client model fields (company_profile, brand_domain, industry)

### Requirement 2: Problem & Competitive Landscape (Step 2)

**User Story:** As a new client, I want to answer conversational prompts about my product's unique value, so the AI understands my positioning.

#### Acceptance Criteria

1. THE wizard SHALL present 3 conversational prompts (not form labels): "What does your best customer say their life was like before using you?", "What does your product do that competitors cannot?", "Name your 2-3 main competitors"
2. THE client SHALL answer in free-text (textarea, no character limit enforced in UI, 5000 char server limit)
3. ON proceeding to next step, THE system SHALL call LLM to extract: pain_language, positioning_claims, competitor_names, differentiators from the answers
4. THE system SHALL display an AI-generated summary for client review and inline editing before proceeding
5. EXTRACTED data SHALL populate: company_worldview, company_problem, competitive_landscape fields on the Client model

### Requirement 3: ICP Definition (Step 3)

**User Story:** As a new client, I want to define my ideal customer profile, so the AI targets the right Reddit communities.

#### Acceptance Criteria

1. THE wizard SHALL present a B2B/B2C toggle at the top of the step (prominent, affects visible fields)
2. FOR B2B: THE wizard SHALL collect: job titles (multi-select + free text), seniority level, day-to-day frustration, "what they search before finding you"
3. FOR B2C: THE wizard SHALL collect: demographics, interests, "what they search before finding you"
4. THE wizard SHALL support Primary ICP (required) and Adjacent ICP (optional) — max 2 ICPs
5. THE "what they search" answer SHALL be used as keyword seed for Step 5
6. ON proceeding, THE system SHALL synthesize answers into structured icp_profiles text and store on Client model

### Requirement 4: Voice, Tone & Guardrails (Step 4)

**User Story:** As a new client, I want the AI to understand my brand voice through document upload and tone calibration, so generated comments sound like my brand.

#### Acceptance Criteria

1. THE wizard SHALL provide a document upload zone (drag-and-drop, PDF/DOCX/TXT/MD) for brand guidelines, messaging frameworks, tone of voice docs
2. UPLOADED documents SHALL be parsed (text extraction) and processed by LLM to extract tone characteristics
3. THE wizard SHALL ask 3 required guardrail questions: "3 things brand should NEVER be associated with", "Claims you legally cannot make", "Brand/person whose communication style you admire"
4. AFTER upload + answers processed, THE system SHALL run Tone_Calibration_Loop: generate 5 sample Reddit-style sentences in the brand voice, client rates each 1-5
5. IF 3+ sentences score 4+: proceed. OTHERWISE: regenerate new sentences and repeat (max 3 loops)
6. IF client fails tone calibration 3 times: display CTA "Book a 30-minute onboarding call with our team" (not a failure state, premium service moment)
7. SENTENCES rated 4-5 SHALL be stored as few-shot anchors for future AI generation
8. GUARDRAIL answers SHALL populate brand_voice and constraints fields

### Requirement 5: AI Keyword & Subreddit Suggestion (Step 5)

**User Story:** As a new client, I want the AI to suggest relevant keywords and subreddits based on my profile, so I don't have to research Reddit manually.

#### Acceptance Criteria

1. THE system SHALL use Entity Extraction (reuse `discovery/entity_extractor.py`) on the combined client profile to generate keyword suggestions with priority tiers (high/medium/low)
2. THE client SHALL confirm, remove, or add keywords (autocomplete from existing keyword database)
3. THE system SHALL generate ranked subreddit suggestions with rationale per subreddit: size, audience match, moderation strictness, competitor presence
4. THE client SHALL promote or reject each suggested subreddit (explanations shown per subreddit)
5. SUBREDDIT limit SHALL be shown based on plan tier ("You have X subreddit slots on your plan")
6. IF client wants more subreddits than plan allows: inline upsell tooltip (non-blocking)
7. CONFIRMED keywords SHALL be stored in client.keywords JSONB, subreddits as ClientSubredditAssignment records

### Requirement 6: Review & Quality Gate (Step 6)

**User Story:** As a new client, I want to review everything before activating, so I'm confident the AI understood me correctly.

#### Acceptance Criteria

1. THE wizard SHALL display all generated outputs: Company Profile, ICP(s), Voice Profile, Keyword Map, Subreddit Map — each section editable inline
2. THE system SHALL calculate a quality score across all sections (internal, not shown as number to client)
3. IF quality is sufficient: show "Activate" CTA button — "Start Building Your Presence"
4. IF quality is too low (thin brief, vague answers, tone calibration not passed): highlight specific incomplete fields in red, block activation
5. ON activation: set client.is_active = True, client.onboarding_completed_at = now(), emit activity event "client_onboarded"
6. DISPLAY confirmation: "Your setup is complete. We are now configuring your avatars. Check back in 24-48 hours."
7. SEND email confirmation with timeline and what to expect

### Requirement 7: Avatar Onboarding (Post-Allocation, Automated)

**User Story:** As an ops team member, after I assign avatars to a client, I want the system to automatically run discovery, generate strategy, create GEO baseline, and trigger the first pipeline run.

#### Acceptance Criteria

1. WHEN an avatar is assigned to a client (via admin panel), THE system SHALL auto-create a Discovery session using the client's profile as the brief
2. THE Discovery session SHALL run entity extraction → hypothesis generation → Reddit research (automated, no human confirmation needed for auto-triggered sessions)
3. ON Discovery completion, THE system SHALL auto-trigger Strategy Generation for the avatar, injecting discovery_context (communities found, entry points, competitor presence)
4. ON Strategy Generation completion, THE system SHALL create GeoPrompt records from client keywords + competitors and trigger initial GEO batch run (Day 1 Report)
5. ON Strategy + GEO completion, THE system SHALL trigger the first full pipeline run (scrape → score → generate → EPG) for the client
6. THE system SHALL send client notification: "Your avatars are active. Check your Review Queue for the first drafts."
7. IF any step fails, THE system SHALL log the error, continue with remaining steps, and alert ops via activity event

### Requirement 8: Free Trial Flow (Intelligence-Only)

**User Story:** As a prospect, I want to try RAMP's intelligence layer for free for 14 days, so I can evaluate the product before committing.

#### Acceptance Criteria

1. THE trial signup SHALL require a work email (reject gmail, hotmail, yahoo, outlook personal domains)
2. THE trial SHALL grant full access to: onboarding wizard, subreddit discovery, thread monitoring, scoring, AI comment drafts (read-only)
3. THE trial SHALL NOT grant access to: avatar activation, posting, EPG execution
4. ON trial completion (wizard done), THE system SHALL auto-generate Day 1 Reddit Landscape Report: competitor presence baseline, share of voice at 0%, top threads where brand is absent
5. THE trial SHALL expire after 14 days with a conversion CTA: "Upgrade to start posting"
6. TRIAL data (profile, keywords, subreddits, drafts) SHALL be preserved and carried over on conversion to paid plan
7. TRIAL clients SHALL have plan_type = "trial", max_avatars = 0, posting_disabled = true

### Requirement 9: Onboarding Progress Persistence

**User Story:** As a client, I want my onboarding progress saved automatically, so I can leave and come back without losing work.

#### Acceptance Criteria

1. EACH step completion SHALL be saved to the database immediately (no "submit all at end")
2. THE system SHALL track current_onboarding_step on the Client model
3. IF the client returns to an incomplete onboarding, THE wizard SHALL resume at the last incomplete step with all previous data pre-filled
4. THE wizard SHALL show a progress bar (step X of 6) visible throughout
5. THE client SHALL be able to navigate back to previous steps to edit (without losing later progress)
