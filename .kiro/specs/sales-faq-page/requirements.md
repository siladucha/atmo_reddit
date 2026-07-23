# Requirements Document

## Introduction

A comprehensive FAQ section for the RAMP marketing site that addresses common sales objections encountered before and after demo calls. The FAQ lives as an accordion/collapsible component on the `/pricing` page and is also accessible as a standalone `/faq` route. All content must comply with strict compliance language rules — never referencing bots, fake accounts, automation mechanics, or operational details.

## Glossary

- **FAQ_Section**: The collapsible accordion UI component containing question-answer pairs
- **FAQ_Page**: The standalone `/faq` route that renders the full FAQ content
- **Pricing_Page**: The existing `/pricing` marketing page where the FAQ section is embedded
- **Marketing_Site**: The separate FastAPI application in `marketing_site/` serving public-facing pages
- **Compliance_Copy**: Client-facing text that adheres to RAMP's language rules (no "bot", "fake accounts", "automated posting", "avatar", "VPN", "karma farming", or operational mechanics)
- **Accordion_Item**: A single question-answer pair with expand/collapse behavior
- **FAQ_Content**: The structured data (question + answer pairs) displayed in the FAQ section

## Requirements

### Requirement 1: FAQ Accordion on Pricing Page

**User Story:** As a prospective client visiting the pricing page, I want to see a section of frequently asked questions in an expandable accordion format, so that I can quickly find answers to common concerns without leaving the pricing context.

#### Acceptance Criteria

1. WHEN a visitor loads the `/pricing` page, THE FAQ_Section SHALL render below the existing pricing content and above the bottom CTA section
2. THE FAQ_Section SHALL display a minimum of 3 and a maximum of 10 FAQ items, all in a collapsed state by default
3. WHEN a visitor activates an Accordion_Item question (via click or keyboard Enter/Space), THE FAQ_Section SHALL expand that item to reveal the answer and display a visual indicator distinguishing the expanded state from collapsed state
4. WHEN a visitor activates an already-expanded Accordion_Item question (via click or keyboard Enter/Space), THE FAQ_Section SHALL collapse that item to hide the answer and return the visual indicator to the collapsed state
5. THE FAQ_Section SHALL allow multiple Accordion_Items to be expanded simultaneously
6. THE FAQ_Section SHALL include a heading "FREQUENTLY ASKED QUESTIONS" using the same typographic style as other section headings on the pricing page (uppercase, bold, white text)
7. THE FAQ_Section SHALL be keyboard-accessible, allowing users to navigate between Accordion_Item questions using Tab and activate them using Enter or Space keys

### Requirement 2: Standalone FAQ Route

**User Story:** As a prospective client who received a link to the FAQ page (e.g., in a follow-up email after a demo call), I want to access a standalone `/faq` page, so that I can review all objection-handling answers without needing to scroll through pricing details.

#### Acceptance Criteria

1. WHEN a visitor navigates to `/faq`, THE FAQ_Page SHALL return HTTP 200 and render the full FAQ content using the `marketing_base.html` template, including the site header, navigation, and footer
2. THE FAQ_Page SHALL display all FAQ question-answer pairs present in the pricing page FAQ_Section, in the same order and with identical text content
3. THE FAQ_Page SHALL include a unique page `<title>` of 60 characters or fewer containing the word "FAQ" and a `<meta name="description">` of 155 characters or fewer summarizing the page content
4. THE FAQ_Page SHALL include a CTA below the last FAQ item that links to the trial signup page (`/onboard/trial`)
5. IF a visitor navigates to `/faq` and the page fails to render, THEN THE FAQ_Page SHALL return an appropriate HTTP error status without exposing internal server details

### Requirement 3: Shadowban Remedy FAQ Entry

**User Story:** As a prospective client worried about account risk, I want to understand what happens if a community voice gets restricted, so that I feel confident RAMP protects my investment.

#### Acceptance Criteria

1. THE FAQ_Content SHALL include a question-and-answer entry where the question asks what happens if a community voice account becomes restricted or limited
2. THE FAQ_Content SHALL state in the answer that client-owned accounts restricted due to RAMP-managed activity receive 30 days of continued service at no additional charge as a remedy, and that the restriction must be attributable to RAMP-managed activity to qualify
3. THE FAQ_Content SHALL use the heading "Community Voice Protection Policy" and SHALL NOT use the words "ban", "shadowban", or "suspended" as standalone terms anywhere in the entry — using "restricted" or "limited" instead (compound words or quotations referencing external platform terminology are permitted only if immediately followed by the preferred term)
4. THE Compliance_Copy SHALL NOT mention detection evasion, VPN usage, or multi-IP infrastructure
5. IF the FAQ entry references account status terminology from external platforms, THEN THE FAQ_Content SHALL immediately reframe using "restricted" or "limited" within the same sentence

### Requirement 4: Human-in-the-Loop Differentiation FAQ Entry

**User Story:** As a prospective client skeptical about automated marketing tools, I want to understand how RAMP differs from a bot, so that I feel confident the engagement is authentic and safe.

#### Acceptance Criteria

1. THE FAQ_Content SHALL include a question addressing how RAMP differs from automated tools
2. THE FAQ_Content SHALL explain the human-in-the-loop approval workflow by stating all three steps: (1) AI generates drafts, (2) a human reviews and approves content, (3) only approved content is published
3. THE FAQ_Content SHALL state in a dedicated sentence that no content is ever published without explicit human approval
4. THE Compliance_Copy SHALL NOT use the words "bot", "automated posting", or "evading detection" in either the question or answer text of the FAQ entry
5. THE Compliance_Copy SHALL include each of the phrases "community engagement management" and "persona-driven content strategy" at least once verbatim within the answer text

### Requirement 5: Results Expectations FAQ Entry

**User Story:** As a prospective client evaluating ROI, I want to understand what results are realistic and when to expect them, so that I can set proper internal expectations.

#### Acceptance Criteria

1. THE FAQ_Content SHALL include a question that explicitly asks about expected results or outcome guarantees (e.g., "What results can I expect?" or "Do you guarantee specific outcomes?")
2. THE FAQ_Content SHALL state within the answer body that no specific numerical results (karma scores, follower counts, conversion rates, or revenue figures) are guaranteed
3. THE FAQ_Content SHALL describe a phased timeline with the following stages: months 1-2 for community credibility building, months 3-4 for content presence expansion, and month 5+ for brand integration opportunities, with a brief description of the observable activities in each phase
4. THE FAQ_Content SHALL frame outcomes using qualitative community indicators (such as community recognition, expert reputation, discussion participation, and brand association) and SHALL NOT reference numerical performance metrics (such as specific karma thresholds, follower counts, upvote targets, or conversion percentages)

### Requirement 6: Existing Accounts Audit FAQ Entry

**User Story:** As a prospective client with existing Reddit presence, I want to understand how RAMP handles my current accounts, so that I know my existing presence is respected and assessed.

#### Acceptance Criteria

1. THE FAQ_Content SHALL include a question that explicitly asks what happens when a client already has existing Reddit accounts
2. THE FAQ_Content SHALL explain that RAMP conducts a pre-engagement audit of existing community presence and that existing accounts are incorporated into the strategy rather than replaced or discarded
3. THE FAQ_Content SHALL describe the intake process by mentioning all three assessment dimensions (current standing, community health, and strategic alignment) without referencing karma levels, account age thresholds, warming phases, or automation tools
4. THE Compliance_Copy SHALL NOT mention karma levels, account age requirements, or warming mechanics

### Requirement 7: Content Authorship FAQ Entry

**User Story:** As a prospective client concerned about quality and authenticity, I want to understand who writes the community engagement content, so that I trust the output represents genuine expertise.

#### Acceptance Criteria

1. THE FAQ_Content SHALL include a question that explicitly asks who creates or writes the community engagement content
2. THE FAQ_Content SHALL explain that AI generates initial drafts tailored to each community voice's persona and expertise
3. THE FAQ_Content SHALL explicitly state that every draft is reviewed and approved by a human before publication, and that no content is published without this human approval step
4. THE Compliance_Copy SHALL use "voice" or "voices" instead of "avatar" in all answer text
5. THE Compliance_Copy SHALL NOT reference "karma farming", "warming", "account management", "bot", "automated posting", or any terms describing internal account operations or platform-mechanics processes
6. THE FAQ_Content SHALL state that each voice is backed by real subject-matter knowledge in their domain, conveying that the expertise represented is genuine rather than fabricated

### Requirement 8: Plan Inclusions FAQ Entry

**User Story:** As a prospective client comparing plans, I want a concise summary of what each pricing tier includes, so that I can quickly identify the right plan for my needs.

#### Acceptance Criteria

1. THE FAQ_Content SHALL include a question addressing what is included in each plan
2. THE FAQ_Content SHALL list all four direct plans (Seed, Starter, Growth, Scale) and for each plan state at minimum: the number of voices, the number of communities, and the monthly action limit (comments and/or posts)
3. THE FAQ_Content SHALL NOT repeat exact dollar pricing for each tier — instead referencing the pricing section for current rates
4. THE FAQ_Content SHALL mention the managed service add-on by stating its availability for clients who want hands-off operation, without specifying add-on pricing in the answer
5. THE FAQ_Content SHALL include a navigational reference (anchor link or textual directive) to the detailed pricing section for full plan comparison
6. THE FAQ_Content SHALL use the term "voices" (not "avatar") and "communities" (not "subreddits") consistent with Requirement 11 compliance rules

### Requirement 9: Cancellation Policy FAQ Entry

**User Story:** As a prospective client concerned about commitment risk, I want to know the cancellation terms, so that I feel confident there is no long-term lock-in.

#### Acceptance Criteria

1. THE FAQ_Content SHALL include a question that explicitly asks about cancellation terms and long-term commitment obligations
2. THE FAQ_Content SHALL state that direct plans (Seed, Starter, Growth, Scale) have no long-term lock-in, can be cancelled at any time, and that service access ends at the close of the current billing period
3. THE FAQ_Content SHALL state that community reputation built by voices during the subscription (including posted content, karma earned, and authority established in subreddits) persists on the platform after cancellation
4. IF the question references agency plans, THEN THE FAQ_Content SHALL state that agency plans operate on annual contracts

### Requirement 10: Mobile Responsiveness

**User Story:** As a prospective client browsing on a mobile device, I want the FAQ section to be fully usable on small screens, so that I can read answers without horizontal scrolling or broken layouts.

#### Acceptance Criteria

1. THE FAQ_Section SHALL render without content overflow, text truncation, or overlapping elements on viewport widths from 320px to 1440px
2. THE Accordion_Item questions SHALL have touch-friendly tap targets with a minimum height of 44px
3. THE FAQ_Section SHALL not introduce horizontal scroll on any supported viewport width
4. WHILE the viewport width is below 768px, THE FAQ_Section SHALL use full-width layout with a minimum of 16px horizontal padding
5. WHEN an Accordion_Item answer is expanded, THE answer content SHALL wrap within its container without introducing horizontal overflow at any supported viewport width

### Requirement 11: Compliance Language Enforcement

**User Story:** As the RAMP legal/business team, I want all FAQ content to comply with our language rules, so that we never expose operational mechanics or use prohibited terminology in client-facing materials.

#### Acceptance Criteria

1. THE FAQ_Content SHALL NOT contain any of the following exact phrases (case-insensitive, whole-word match): "fake accounts", "fake account", "bot", "bots", "automated posting", or "evading detection" — in either question text or answer text
2. THE FAQ_Content SHALL NOT contain the word "avatar" or "avatars" (case-insensitive, whole-word match) in either question text or answer text — using "voice" or "voices" instead
3. THE FAQ_Content SHALL NOT contain any of the following terms or phrases (case-insensitive): "VPN", "multi-IP", "karma farming", "karma farm", "account warming", "account warm-up", "proxy", "residential IP", or "rotating IP"
4. THE FAQ_Content SHALL describe RAMP services using at least one of the following approved phrases per answer that explains what RAMP does: "community engagement management", "persona-driven content strategy", or "human-in-the-loop"
5. THE FAQ_Content SHALL NOT contain any of the following phrases (case-insensitive): "terms of service", "ToS", "Reddit rules", "platform rules", "rule violation", "policy violation", or "against the rules"
6. IF FAQ_Content contains a word where a prohibited term appears as a substring within a larger word (e.g., "robot", "chatbot", "botany"), THEN THE FAQ_Content SHALL treat these compound words as acceptable and not flag them as violations

### Requirement 12: Template and Tech Stack Consistency

**User Story:** As a developer maintaining the marketing site, I want the FAQ feature to follow existing patterns (FastAPI + Jinja2 + Tailwind CSS CDN + marketing_base.html), so that the codebase remains consistent and maintainable.

#### Acceptance Criteria

1. THE FAQ_Page template SHALL extend `marketing_base.html` and be named following the existing convention (`marketing_faq.html`)
2. THE FAQ_Section SHALL use Tailwind CSS utility classes from the CDN (no additional CSS frameworks or custom stylesheets beyond inline `<style>` blocks within the template)
3. THE Accordion_Item expand/collapse behavior SHALL be implemented with vanilla JavaScript (no additional JS libraries), using the same toggle pattern as the existing roadmap page (`togglePhase`-style click handler with `aria-expanded` attribute management)
4. THE FAQ route SHALL be registered in the marketing site's `pages.py` router as an async handler at the `/faq` URL path, returning `templates.TemplateResponse` with `response_class=HTMLResponse`, matching the structure of existing page routes
5. THE FAQ_Content SHALL be defined as a list of dictionaries (each containing at minimum a `question` string and an `answer` string) in the route handler or a dedicated data module, passed to the template via the Jinja2 context (not hardcoded in the template HTML)
