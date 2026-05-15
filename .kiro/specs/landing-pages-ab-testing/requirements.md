# Requirements Document

## Introduction

A marketing website for the Reddit SaaS platform (RAMP) designed to measure market interest in two business models before building both products. The website presents two distinct landing pages — one for personal brand owners (Mobile/White solution) and one for agencies/enterprises (Proxy/Grey solution) — with A/B testing on pricing and business model variants. The goal is to collect waitlist signups and determine clear market preference between the two products within 2-4 weeks.

## Glossary

- **Marketing_Website**: The public-facing marketing website separate from the admin panel, serving landing pages and collecting waitlist signups
- **Landing_Page**: A product-specific page presenting value proposition, pricing, and a waitlist signup form
- **AB_Test_Engine**: The client-side JavaScript module responsible for assigning visitors to test variants via cookies and tracking variant exposure
- **Waitlist_Form**: The signup form component that captures visitor information and associates it with the displayed A/B test variant
- **Analytics_Tracker**: The client-side module that records page views, click events, CTR, and variant assignments
- **Variant**: A specific configuration of pricing or business model shown to a visitor as part of an A/B test
- **Homepage**: The root page (/) presenting a hero section and navigation cards to both product landing pages
- **Thank_You_Page**: The confirmation page (/thank-you) displayed after successful waitlist signup
- **Mobile_Page**: The landing page (/mobile) targeting personal brand owners for the mobile app solution
- **Proxy_Page**: The landing page (/proxy) targeting agencies and enterprises for the fully managed proxy solution

## Requirements

### Requirement 1: Website Structure and Navigation

**User Story:** As a visitor, I want to navigate between the homepage and product landing pages, so that I can learn about the product that fits my needs.

#### Acceptance Criteria

1. THE Marketing_Website SHALL serve four pages: Homepage (/), Mobile_Page (/mobile), Proxy_Page (/proxy), and Thank_You_Page (/thank-you)
2. WHEN a visitor loads the Homepage, THE Marketing_Website SHALL display a hero section containing a headline, a subheadline describing the product benefit, and two product navigation cards linking to Mobile_Page and Proxy_Page
3. WHEN a visitor clicks a product card on the Homepage, THE Marketing_Website SHALL navigate the visitor to the corresponding Landing_Page within 1 second
4. THE Marketing_Website SHALL render all pages using Jinja2 templates with a shared base layout that includes a consistent header and footer across all four pages
5. THE Marketing_Website SHALL apply a visual design using Tailwind CSS with consistent typography, spacing, and color scheme across all pages
6. IF a visitor navigates to a URL not matching any defined route, THEN THE Marketing_Website SHALL return a 404 page that includes a link back to the Homepage

### Requirement 2: Mobile Landing Page Content

**User Story:** As a personal brand owner, I want to see a landing page tailored to my needs, so that I can understand how the mobile solution helps me grow on Reddit safely.

#### Acceptance Criteria

1. WHEN a visitor loads the Mobile_Page, THE Marketing_Website SHALL display the headline "Grow your personal brand on Reddit without risking your account"
2. WHEN a visitor loads the Mobile_Page, THE Marketing_Website SHALL present the value proposition for personal brand owners including at least 3 key benefits, at least 3 numbered how-it-works steps, and at least 1 social proof element (testimonial, statistic, or trust indicator)
3. WHEN a visitor loads the Mobile_Page, THE Marketing_Website SHALL render content sections in the following order: headline, key benefits, how-it-works steps, social proof, pricing section, Waitlist_Form
4. THE Mobile_Page SHALL include a Waitlist_Form positioned directly after the pricing section with no intervening content sections between them
5. WHILE a visitor has an assigned A/B test variant for the Mobile pricing or Mobile model tests, THE Mobile_Page SHALL display pricing information matching the assigned variant values

### Requirement 3: Proxy Landing Page Content

**User Story:** As an agency or enterprise decision-maker, I want to see a landing page tailored to my scale needs, so that I can evaluate the fully managed Reddit marketing service.

#### Acceptance Criteria

1. WHEN a visitor loads the Proxy_Page, THE Marketing_Website SHALL display the headline "Scale your Reddit marketing — we manage everything"
2. WHEN a visitor loads the Proxy_Page, THE Marketing_Website SHALL present the value proposition for agencies and enterprises including at least 3 key benefits, at least 3 managed service details, and at least 1 social proof element (testimonial, statistic, or trust indicator)
3. WHEN a visitor loads the Proxy_Page, THE Marketing_Website SHALL render content sections in the following order: headline, key benefits, managed service details, social proof, pricing section, Waitlist_Form
4. THE Proxy_Page SHALL include a Waitlist_Form positioned directly after the pricing section with no intervening content sections between them
5. WHILE a visitor has an assigned A/B test variant for the Proxy pricing or Proxy guarantee tests, THE Proxy_Page SHALL display pricing information matching the assigned variant values

### Requirement 4: A/B Test Variant Assignment

**User Story:** As a product owner, I want visitors to be randomly assigned to pricing and model variants, so that I can measure which pricing resonates best with each audience.

#### Acceptance Criteria

1. WHEN a visitor loads a Landing_Page for the first time and has no existing variant cookie, THE AB_Test_Engine SHALL assign the visitor to exactly one variant per active test using uniform random distribution
2. WHEN a variant is assigned, THE AB_Test_Engine SHALL store the assignment in a browser cookie with a 30-day expiration
3. WHILE a visitor has an existing valid variant cookie, THE AB_Test_Engine SHALL display the same variant on subsequent visits without re-randomizing
4. THE AB_Test_Engine SHALL support four concurrent tests: Mobile pricing ($99 vs $149 vs $199/month), Mobile model (subscription vs pay-per-comment vs hybrid), Proxy pricing ($999 vs $1999 vs "contact sales"), and Proxy guarantee (no guarantee/lower price vs free replacement/higher price)
5. WHEN a variant is assigned, THE AB_Test_Engine SHALL record the assignment in the ab_test_assignments database table within 2 seconds of assignment
6. IF a visitor's cookie is corrupted or references a variant identifier not present in the active test configuration, THEN THE AB_Test_Engine SHALL assign a new valid variant using uniform random distribution and overwrite the cookie
7. IF the assignment recording fails after 3 retry attempts, THEN THE AB_Test_Engine SHALL still display the assigned variant to the visitor and log the recording failure for later reconciliation
8. WHEN a visitor's variant cookie has expired and the visitor loads a Landing_Page, THE AB_Test_Engine SHALL retrieve the visitor's previous assignment from the ab_test_assignments table and restore the cookie, or assign a new variant if no prior record exists
9. WHEN a new test is added to the active configuration and a returning visitor loads a Landing_Page, THE AB_Test_Engine SHALL assign the visitor to a variant for the new test only, preserving existing assignments for other tests

### Requirement 5: Waitlist Signup Form

**User Story:** As a visitor, I want to sign up for the waitlist with my details, so that I can be notified when the product launches.

#### Acceptance Criteria

1. THE Waitlist_Form SHALL capture the following fields: email (required, maximum 254 characters), company name (optional, maximum 100 characters), role (optional, maximum 100 characters), number of Reddit accounts (optional, integer between 1 and 10,000), selected price tier (auto-populated from displayed variant), free-text feedback (optional, maximum 1,000 characters), and variant shown (auto-populated, hidden)
2. WHEN a visitor submits the Waitlist_Form with a valid email address conforming to the format local-part@domain where domain contains at least one dot, THE Marketing_Website SHALL store the signup data in the waitlist_signups PostgreSQL table
3. WHEN a signup is stored successfully, THE Marketing_Website SHALL redirect the visitor to the Thank_You_Page
4. IF a visitor submits the Waitlist_Form with an email that is missing, exceeds 254 characters, or does not conform to the required email format, THEN THE Marketing_Website SHALL display an inline validation error below the email field indicating the issue without clearing any entered form data
5. IF a visitor submits the Waitlist_Form with an email that already exists in waitlist_signups, THEN THE Marketing_Website SHALL update the existing record's company, role, accounts_count, price_tier, feedback, and variant_shown fields with the new submission data and redirect to Thank_You_Page
6. THE Waitlist_Form SHALL include the visitor's A/B test variant identifiers (test_name and variant_name for each active test) as hidden fields submitted with the form data
7. IF the database is unreachable or the write operation fails when processing a Waitlist_Form submission, THEN THE Marketing_Website SHALL display an error message indicating the signup could not be completed and retain all entered form data

### Requirement 6: Analytics and Event Tracking

**User Story:** As a product owner, I want to track visitor behavior and variant performance, so that I can make data-driven decisions about which product and pricing to pursue.

#### Acceptance Criteria

1. WHEN a visitor loads any page, THE Analytics_Tracker SHALL record a page view event including the visitor UUID, page path, timestamp, and assigned variant identifiers (or an empty object if no variants are assigned yet)
2. WHEN a visitor clicks a CTA button or product card, THE Analytics_Tracker SHALL record a click event including the visitor UUID, a data attribute identifier of the clicked element, page path, and timestamp
3. WHEN a visitor submits the Waitlist_Form, THE Analytics_Tracker SHALL record a signup event including the visitor UUID, the variant identifiers, and page path
4. THE Analytics_Tracker SHALL store all events in a local queue of no more than 100 events and batch-send them to the server endpoint within 5 seconds of occurrence or when the queue reaches 20 events, whichever comes first
5. THE Marketing_Website SHALL expose an API endpoint that accepts analytics events, validates that each event contains a visitor_id, event_type, and timestamp, and stores valid events in the analytics_events PostgreSQL table
6. IF the API endpoint receives an event missing required fields (visitor_id, event_type, or timestamp), THEN THE Marketing_Website SHALL reject the request and return an error response indicating the missing fields without storing the event

### Requirement 7: Database Schema for Waitlist and A/B Testing

**User Story:** As a developer, I want a well-structured database schema, so that I can query signups and A/B test results efficiently.

#### Acceptance Criteria

1. THE Marketing_Website SHALL create a waitlist_signups table with columns: id (UUID primary key), email (VARCHAR(320), NOT NULL, UNIQUE), company (VARCHAR(200)), role (VARCHAR(100)), accounts_count (INTEGER, range 1 to 10,000), price_tier (VARCHAR(50)), feedback (TEXT, max 2000 characters), variant_shown (JSONB), source_page (VARCHAR(500)), created_at (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT now), updated_at (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT now)
2. THE Marketing_Website SHALL create an ab_test_assignments table with columns: id (UUID primary key), visitor_id (UUID, NOT NULL), test_name (VARCHAR(100), NOT NULL), variant_name (VARCHAR(100), NOT NULL), assigned_at (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT now), converted (BOOLEAN, NOT NULL, DEFAULT false), converted_at (TIMESTAMP WITH TIME ZONE, nullable)
3. THE Marketing_Website SHALL create an analytics_events table with columns: id (UUID primary key), visitor_id (UUID, NOT NULL), event_type (VARCHAR(100), NOT NULL), event_data (JSONB), page_path (VARCHAR(500)), timestamp (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT now)
4. THE Marketing_Website SHALL create indexes on: waitlist_signups(email), waitlist_signups(created_at), ab_test_assignments(visitor_id), ab_test_assignments(test_name, variant_name), analytics_events(visitor_id), and analytics_events(event_type, timestamp)
5. WHEN a waitlist signup is created and a visitor_id cookie is present in the request, THE Marketing_Website SHALL set converted to true and converted_at to the current timestamp on all ab_test_assignments records matching that visitor_id

### Requirement 8: Thank You Page

**User Story:** As a visitor who signed up, I want confirmation that my signup was received, so that I feel confident I will be contacted.

#### Acceptance Criteria

1. WHEN a visitor is redirected to the Thank_You_Page, THE Marketing_Website SHALL display a confirmation message acknowledging the signup including the text "You're on the list"
2. THE Thank_You_Page SHALL include navigation links back to the Homepage and to the Landing_Page the visitor signed up from
3. THE Thank_You_Page SHALL use the same shared base layout (header, footer, typography, color scheme) as all other pages
4. IF a visitor navigates directly to /thank-you without a prior form submission, THE Marketing_Website SHALL display the confirmation page without error

### Requirement 9: Cookie-Based Visitor Identity

**User Story:** As a product owner, I want to track individual visitors across sessions, so that I can correlate page views, variant assignments, and signups to the same person.

#### Acceptance Criteria

1. WHEN a visitor loads any page and no valid visitor UUID cookie is present, THE AB_Test_Engine SHALL generate a UUID v4 visitor identifier and store it in a browser cookie named "visitor_id" with a 30-day expiration from the time of creation
2. WHILE a visitor has an existing valid visitor UUID cookie, THE AB_Test_Engine SHALL use the stored UUID for all subsequent tracking and variant assignment operations and SHALL reset the cookie expiration to 30 days from the current visit
3. THE AB_Test_Engine SHALL include the visitor UUID in all analytics events and A/B test assignment records
4. IF the visitor UUID cookie is missing or does not conform to UUID v4 format (8-4-4-4-12 hexadecimal pattern), THEN THE AB_Test_Engine SHALL generate a new UUID v4 and set a new cookie with a 30-day expiration
5. THE AB_Test_Engine SHALL set the visitor UUID cookie with path "/" so that it is accessible across all pages of the application

### Requirement 10: Performance and Reliability

**User Story:** As a visitor, I want the landing pages to load quickly and reliably, so that I have a positive first impression of the product.

#### Acceptance Criteria

1. THE Marketing_Website SHALL render the Largest Contentful Paint (LCP) within 2 seconds on a 10 Mbps connection with 50ms latency
2. IF JavaScript is disabled in the visitor's browser, THEN THE Marketing_Website SHALL display all static content including default pricing (first variant) without layout breakage or missing text
3. IF the analytics API endpoint is unreachable, THEN THE Analytics_Tracker SHALL queue up to 50 events in local storage and retry sending them on the next page load
4. THE Marketing_Website SHALL serve all static assets (CSS, JS, images) with a Cache-Control max-age of at least 7 days and include content-based hash fingerprints in filenames for cache busting
5. IF the analytics retry on next page load fails, THEN THE Analytics_Tracker SHALL discard events older than 72 hours from the local queue
