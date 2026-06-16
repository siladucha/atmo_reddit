# Requirements Document

## Introduction

The XM Cyber Post Strategy is a client-specific configuration that plugs into the Post Generation Engine (defined in `.kiro/specs/post-generation-engine/`). XM Cyber is a cybersecurity company focused on exposure management and attack path analysis. This configuration defines the strategic themes, forbidden terms, content mix ratios, allowed post types, worldview concepts, anti-pattern filters, personas, and writing rules that the Post Generation Engine uses when generating Reddit posts for the XM Cyber client.

This is NOT a new engine — it is a Client_Post_Config record and associated validation/enforcement logic that drives the existing 10-step pipeline specifically for XM Cyber's marketing objectives. The goal is to position XM Cyber's concepts in practitioner communities through authentic, frustration-driven posts written from the perspective of security operations professionals dealing with real problems.

## Glossary

- **XM_Cyber_Post_Config**: The Client_Post_Config instance containing all XM Cyber-specific post generation parameters loaded by the Post Generation Engine
- **Strategic_Theme**: A keyword cluster representing a topic area that XM Cyber wants to seed in practitioner communities
- **Forbidden_Term**: A word or phrase that must never appear in any generated post for XM Cyber, enforced by the Anti_Pattern_Filter
- **Content_Mix**: The target percentage distribution of post categories for XM Cyber (Community/Karma, Operational Frustrations, Worldview Seeding, Direct XM Narrative)
- **Worldview_Concept**: A brand-adjacent term that may be naturally injected into posts (max 1 per post) to build association between XM Cyber's philosophy and practitioner problems
- **Anti_Pattern_Word**: A term whose presence in a generated post triggers automatic rejection by the Anti_Pattern_Filter
- **Persona**: A named avatar identity with defined professional background, tone, and topical expertise used to author posts
- **Authenticity_Test**: The XM Cyber-specific version of the tired-engineer test: "Would a tired engineer write this at 10PM?"
- **Anti_LinkedIn_Filter**: A detection layer that rejects posts sounding like keynote speeches, consultant blogs, vendor marketing, or LinkedIn thought leadership
- **ICP**: Ideal Customer Profile — the target audience segments whose problems and language the posts must reflect
- **Post_Generation_Engine**: The generic 10-step pipeline (defined in the post-generation-engine spec) that consumes this configuration

## Requirements

### Requirement 1: Strategic Theme Configuration

**User Story:** As a platform operator, I want XM Cyber's strategic themes configured as keyword clusters in the Post Generation Engine, so that generated posts align with XM Cyber's marketing objectives while targeting real practitioner pain points.

#### Acceptance Criteria

1. THE XM_Cyber_Post_Config SHALL define the following 9 strategic theme keyword clusters: "Identity Risk", "Exposure Prioritization", "Remediation Efficiency", "Cloud Drift", "Hybrid Infrastructure", "Security Operations", "Continuous Validation", "Attack Paths", "Exposure Validation"
2. WHEN the Theme_Selector runs for XM Cyber, THE Theme_Selector SHALL select themes only from the configured 9 keyword clusters stored in the XM_Cyber_Post_Config allowed_themes field
3. THE XM_Cyber_Post_Config SHALL store each strategic theme as a keyword cluster entry compatible with the Post Generation Engine's allowed_themes list format (list of string entries, maximum 50)
4. WHEN a new strategic theme is added to or removed from XM Cyber's configuration, THE Post_Generation_Engine SHALL apply the updated theme list on the next Pipeline_Run without requiring a system restart

### Requirement 2: Forbidden Terms Enforcement

**User Story:** As a platform operator, I want XM Cyber's forbidden terms enforced across all generated posts, so that no post contains marketing jargon or vendor language that would break authenticity.

#### Acceptance Criteria

1. THE XM_Cyber_Post_Config SHALL define the following forbidden terms: "CTEM", "Exposure Management", "Digital Twin", "Risk Reduction Platform", "Cyber Resilience Framework", "holistic", "strategic", "visibility", "ecosystem", "transformation", "framework", "maturity", "journey", "operating model"
2. WHEN the Theme_Selector evaluates candidate themes for XM Cyber, THE Theme_Selector SHALL reject any theme containing a forbidden term as a case-insensitive substring match
3. WHEN the Anti_Pattern_Filter evaluates a post generated for XM Cyber, THE Anti_Pattern_Filter SHALL check against all 14 forbidden terms using case-insensitive substring matching
4. IF a generated post contains one or more forbidden terms, THEN THE Anti_Pattern_Filter SHALL reject the post and trigger regeneration with an explicit instruction to avoid the detected terms
5. THE XM_Cyber_Post_Config SHALL store forbidden terms in the forbidden_terms field as a list of strings compatible with the Post Generation Engine's forbidden_terms format (maximum 500 entries)

### Requirement 3: Content Mix Ratio Configuration

**User Story:** As a platform operator, I want XM Cyber's content mix ratios enforced over rolling windows, so that post output maintains the correct balance between community value and brand seeding.

#### Acceptance Criteria

1. THE XM_Cyber_Post_Config SHALL define content mix ratios as: Community/Karma at 60%, Operational Frustrations at 25%, Worldview Seeding at 10%, Direct XM Narrative at 5%
2. THE XM_Cyber_Post_Config SHALL map each content mix category to the Post Generation Engine's strategic tier system: Community/Karma maps to "community_value", Operational Frustrations maps to "problem_awareness", Worldview Seeding maps to "worldview", Direct XM Narrative maps to "brand_narrative"
3. WHEN the Theme_Selector selects a theme for XM Cyber, THE Theme_Selector SHALL weight selection based on the configured content mix ratios and maintain the target distribution within a rolling 30-day window with a tolerance of plus or minus 10 percentage points per category
4. THE XM_Cyber_Post_Config SHALL store content_mix_ratios as a dictionary mapping category names to integer percentages that sum to exactly 100
5. IF the rolling 30-day distribution for any category deviates by more than 10 percentage points from the target ratio, THEN THE Theme_Selector SHALL prioritize the underrepresented category in the next theme selection

### Requirement 4: Allowed and Forbidden Post Types

**User Story:** As a platform operator, I want only practitioner-style post types allowed for XM Cyber, so that no post reads like thought leadership, vendor commentary, or strategic reflection.

#### Acceptance Criteria

1. THE XM_Cyber_Post_Config SHALL define the allowed post types as: "War_Story", "Observation", "Frustration", "Discussion_Question", "Contrarian_Insight"
2. THE XM_Cyber_Post_Config SHALL store the allowed post types in the allowed_post_types field as a subset of the Post Generation Engine's 5 supported types
3. WHEN the Post_Type_Selector chooses a post type for XM Cyber, THE Post_Type_Selector SHALL select only from the 5 allowed types configured in XM_Cyber_Post_Config
4. THE Post_Generation_Engine SHALL reject at the Post_Writer step any post that structurally resembles a forbidden post pattern: thought leadership (opening with an opinion or industry trend), vendor commentary (referencing specific products or solutions), strategic reflection (using leadership lessons or operating model language), or industry trend analysis (citing market reports or analyst predictions)
5. IF the Post_Writer produces a post matching a forbidden post pattern, THEN THE Anti_Pattern_Filter SHALL reject the post and log the specific forbidden pattern detected

### Requirement 5: Worldview Concept Injection Rules

**User Story:** As a platform operator, I want XM Cyber's worldview concepts injected naturally and sparingly, so that brand-adjacent thinking enters practitioner discussions without sounding promotional.

#### Acceptance Criteria

1. THE XM_Cyber_Post_Config SHALL define the following worldview concepts: "attack path", "lateral movement", "blast radius", "ownership", "prioritization", "remediation"
2. THE XM_Cyber_Post_Config SHALL store worldview concepts in the worldview_concepts field as a list of strings (maximum 20 entries)
3. WHEN the Worldview_Injector processes a post for XM Cyber, THE Worldview_Injector SHALL inject at most one worldview concept per post
4. WHEN the Worldview_Injector evaluates a post for XM Cyber, THE Worldview_Injector SHALL inject a concept only when the post topic has direct semantic overlap with the concept and the concept can be expressed as something the practitioner naturally observes or experiences
5. IF the Worldview_Injector cannot find a natural insertion point where the concept reads as practitioner observation rather than vendor terminology, THEN THE Worldview_Injector SHALL skip injection and output "karma-only" for that post
6. THE Worldview_Injector SHALL track worldview concept usage per avatar over a rolling 30-day window and enforce the client's brand_mention_cap to prevent over-saturation

### Requirement 6: Anti-Pattern Word List and LinkedIn Filter

**User Story:** As a platform operator, I want XM Cyber posts automatically rejected if they contain anti-pattern words or sound like LinkedIn content, so that every published post passes as genuine practitioner writing.

#### Acceptance Criteria

1. THE XM_Cyber_Post_Config SHALL define the following anti-pattern words: "holistic", "strategic", "framework", "transformation", "maturity", "visibility", "ecosystem", "journey", "operating model"
2. THE XM_Cyber_Post_Config SHALL store anti-pattern words in the anti_pattern_words field as a list of strings (maximum 200 entries)
3. WHEN the Anti_Pattern_Filter evaluates a post for XM Cyber, THE Anti_Pattern_Filter SHALL reject the post if any anti-pattern word appears as a case-insensitive whole-word match in the post title or body
4. THE Anti_Pattern_Filter SHALL apply an Anti-LinkedIn detection check that rejects posts exhibiting characteristics of: keynote speaker tone (authoritative declarations about industry direction), consultant framing (prescriptive advice with methodology references), vendor blog style (solution-oriented conclusions with implied product fit), or LinkedIn post patterns (personal branding, "I learned that...", inspirational conclusions)
5. IF the Anti-LinkedIn detection flags a post, THEN THE Post_Generation_Engine SHALL trigger one rewrite with explicit instructions: "Rewrite as a tired practitioner venting about a specific incident, not as a thought leader sharing insights"
6. IF the rewritten post still fails the Anti-LinkedIn detection, THEN THE Post_Generation_Engine SHALL discard the post and log the failure with the specific LinkedIn pattern detected

### Requirement 7: Post Writing Rules and Structure

**User Story:** As a platform operator, I want XM Cyber posts to follow strict structural and tonal rules, so that every post reads as a practitioner sharing a specific experience rather than a marketer crafting content.

#### Acceptance Criteria

1. THE XM_Cyber_Post_Config SHALL configure the Post_Writer to enforce the opening rule: every post must start with either "something happened" (a specific incident or observation) or "something was observed" (a pattern noticed during work), and must never start with an opinion, lesson, trend statement, or strategic declaration
2. THE XM_Cyber_Post_Config SHALL configure the Post_Writer to enforce the structure rule: posts follow the sequence "what happened" then "why it mattered" then "what surprised me" then "question or open observation"
3. THE XM_Cyber_Post_Config SHALL set the target_post_length_range to minimum 150 words and maximum 350 words
4. THE XM_Cyber_Post_Config SHALL configure the Post_Writer tone as: practitioner, human, slightly frustrated, curious — and explicitly NOT: vendor, consultant, executive, or marketer
5. THE XM_Cyber_Post_Config SHALL enforce the global writing rule: "Do not write about cybersecurity concepts. Write about PEOPLE DEALING WITH cybersecurity problems."
6. WHEN the Post_Writer generates a post for XM Cyber, THE Post_Writer SHALL validate that the opening sentence describes a concrete event or observation before proceeding with generation
7. IF the generated post's opening sentence contains an opinion word ("I think", "I believe", "In my view"), a lesson indicator ("I learned", "The key takeaway"), or a trend reference ("The industry is", "We are seeing a shift"), THEN THE Post_Writer SHALL regenerate with an explicit constraint to open with a specific incident

### Requirement 8: Persona Configuration

**User Story:** As a platform operator, I want XM Cyber's personas defined with specific professional backgrounds and tonal profiles, so that each post comes from a credible author whose experience matches the topic.

#### Acceptance Criteria

1. THE XM_Cyber_Post_Config SHALL define three personas available for post generation: Lucas Parker (security operations practitioner), Connor (infrastructure and cloud security), Leon (identity and access management)
2. WHEN the Persona_Matcher evaluates avatars for an XM Cyber post, THE Persona_Matcher SHALL match based on topic-to-persona alignment: Security Operations and Continuous Validation themes map to Lucas Parker; Cloud Drift, Hybrid Infrastructure, and Exposure Validation themes map to Connor; Identity Risk and Remediation Efficiency themes map to Leon
3. THE Persona_Matcher SHALL allow Attack Paths and Exposure Prioritization themes to be assigned to any of the three personas based on the specific situation context and subreddit fit
4. WHEN the Post_Writer generates a post for a specific XM Cyber persona, THE Post_Writer SHALL apply that persona's voice profile including vocabulary preferences, sentence structure patterns, and professional experience references consistent with the persona's defined role
5. IF no XM Cyber persona has a suitable topic match for a selected theme (due to the theme falling outside all three personas' expertise domains), THEN THE Persona_Matcher SHALL select the persona with the highest karma in the target subreddit as a fallback

### Requirement 9: Authenticity Test (XM Cyber Version)

**User Story:** As a platform operator, I want the authenticity test for XM Cyber posts to apply the "tired engineer at 10PM" standard, so that only posts passing this specific bar proceed to review.

#### Acceptance Criteria

1. WHEN the Authenticity_Tester evaluates an XM Cyber post, THE Authenticity_Tester SHALL apply the test question: "Would a tired engineer write this at 10PM?" — where passing means the post reads as something a fatigued practitioner would type after a long shift, with natural imperfections, genuine frustration, and no polished conclusions
2. THE Authenticity_Tester SHALL fail a post if it exhibits: polished paragraph structure (every paragraph serves a clear rhetorical purpose), balanced arguments (presenting multiple sides equally), clean conclusions (wrapping up with a neat lesson or insight), or professional detachment (describing problems without emotional investment)
3. THE Authenticity_Tester SHALL pass a post if it exhibits: conversational flow (thoughts connect loosely, not perfectly), emotional specificity (naming exact frustrations, not abstract challenges), incomplete resolution (ending with a question or unresolved tension, not an answer), and detail asymmetry (some parts detailed, others abbreviated, like real storytelling)
4. IF the Authenticity_Tester fails an XM Cyber post, THEN THE Post_Generation_Engine SHALL rewrite once with the instruction: "Make this sound like someone typing fast after a frustrating day — less structured, more raw, end with genuine uncertainty"
5. IF the rewritten post still fails, THEN THE Post_Generation_Engine SHALL discard the post and log the authenticity failure with the specific markers detected

### Requirement 10: ICP-Aligned Topic Targeting

**User Story:** As a platform operator, I want XM Cyber posts to target topics relevant to the defined ICP segments, so that generated content resonates with Security Operations, IAM, Cloud Security, and Infrastructure Security teams.

#### Acceptance Criteria

1. THE XM_Cyber_Post_Config SHALL define four ICP segments: Security Operations teams, Identity and Access Management teams, Cloud Security teams, Infrastructure Security teams
2. WHEN the Experience_Generator produces situations for XM Cyber, THE Experience_Generator SHALL generate situations where the practitioner role aligns with one of the four ICP segments
3. THE Experience_Generator SHALL produce situations reflecting ICP-specific pain points: for Security Operations — alert fatigue, tool sprawl, ownership ambiguity, after-hours incidents; for IAM — orphaned accounts, privilege creep, access review fatigue, identity lifecycle gaps; for Cloud Security — configuration drift, multi-cloud inconsistency, shared responsibility confusion, runtime vs. posture disconnect; for Infrastructure Security — patch prioritization paralysis, legacy system exposure, network segmentation debt, hybrid environment blind spots
4. WHEN the Worthiness_Scorer evaluates XM Cyber situations, THE Worthiness_Scorer SHALL weight the "relatability" dimension higher (0.3 instead of default 0.2) to prioritize situations that directly reflect ICP daily frustrations, redistributing the 0.1 reduction equally from "curiosity" (0.15) and "discussion_potential" (0.15)
5. IF the Experience_Generator produces situations where the practitioner role does not map to any of the four ICP segments, THEN THE Worthiness_Scorer SHALL apply a penalty of minus 2 points to the relatability dimension score for those situations

### Requirement 11: Content Mix Category Definitions

**User Story:** As a platform operator, I want clear definitions for each XM Cyber content mix category, so that the Experience_Generator produces situations matching the intended content type distribution.

#### Acceptance Criteria

1. THE XM_Cyber_Post_Config SHALL define the Community/Karma category (60%) as posts about: sysadmin frustrations with tooling and processes, Azure and cloud platform operational issues, AWS service ownership and billing problems, Kubernetes deployment and scaling headaches, vulnerability management scan noise and false positives
2. THE XM_Cyber_Post_Config SHALL define the Operational Frustrations category (25%) as posts about: ticket ownership disputes between security and IT teams, patch deployment delays and change window conflicts, identity cleanup backlogs and deprovisioning failures, cloud drift between declared infrastructure and actual state
3. THE XM_Cyber_Post_Config SHALL define the Worldview Seeding category (10%) as posts that naturally reference: prioritization of remediation efforts by impact rather than severity, attack path thinking as a mental model for understanding exposure, validation of security controls through adversary simulation concepts, remediation bottleneck analysis from a practitioner perspective
4. THE XM_Cyber_Post_Config SHALL define the Direct XM Narrative category (5%) as posts that organically introduce: continuous validation as an operational concept, exposure-centric thinking as opposed to vulnerability-centric, choke point analysis for reducing remediation scope, identity-centric risk assessment in hybrid environments
5. WHEN the Experience_Generator tags a generated situation with a content category, THE Experience_Generator SHALL assign exactly one of the four categories based on the situation's primary focus, using the definitions stored in XM_Cyber_Post_Config
6. THE Theme_Selector SHALL use the content category tags to maintain the 60/25/10/5 distribution target within the rolling 30-day window

### Requirement 12: Configuration Validation and Activation

**User Story:** As a platform operator, I want the XM Cyber configuration validated and activatable through the existing Client_Post_Config system, so that the configuration integrates cleanly with the Post Generation Engine without custom code paths.

#### Acceptance Criteria

1. WHEN the XM_Cyber_Post_Config is created or updated, THE Post_Generation_Engine SHALL validate that content_mix_ratios sum to exactly 100 (60 + 25 + 10 + 5 = 100)
2. WHEN the XM_Cyber_Post_Config is created or updated, THE Post_Generation_Engine SHALL validate that all entries in allowed_post_types are members of the supported set: War_Story, Observation, Frustration, Discussion_Question, Contrarian_Insight
3. WHEN the XM_Cyber_Post_Config is created or updated, THE Post_Generation_Engine SHALL validate that target_post_length_range minimum (150) is less than maximum (350) and both are within the engine's supported range of 50 to 2000 words
4. THE XM_Cyber_Post_Config SHALL include a `post_generation_active` flag that defaults to false, requiring explicit activation before the Post Generation Engine processes Pipeline_Runs for XM Cyber
5. WHEN `post_generation_active` is set to true on the XM_Cyber_Post_Config, THE Post_Generation_Engine SHALL include XM Cyber in the next scheduled Pipeline_Run (08:00 or 14:00)
6. IF validation fails on any field during configuration creation or update, THEN THE Post_Generation_Engine SHALL reject the entire configuration change and return specific error messages indicating which fields failed validation and why
