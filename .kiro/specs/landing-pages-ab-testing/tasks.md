# Implementation Plan: Landing Pages A/B Testing

## Overview

Implement a standalone marketing website as a separate Docker container (`marketing_site/`) with A/B testing on pricing variants, waitlist signup collection, and client-side analytics tracking. The site connects to the shared PostgreSQL database via Docker networking but is completely independent from the main `reddit_saas/` application.

## Tasks

- [x] 1. Project scaffolding and core infrastructure
  - [x] 1.1 Create directory structure, pyproject.toml, and configuration
    - Create `marketing_site/` directory with full project structure: `app/`, `app/models/`, `app/schemas/`, `app/services/`, `app/routes/`, `app/templates/`, `app/templates/partials/`, `app/static/js/`, `app/static/css/`, `app/static/images/`, `alembic/`, `alembic/versions/`, `tests/`
    - Create `marketing_site/pyproject.toml` with minimal dependencies (fastapi, uvicorn, sqlalchemy, psycopg2-binary, alembic, jinja2, pydantic, pydantic-settings, python-multipart) and dev dependencies (pytest, pytest-asyncio, httpx, hypothesis)
    - Create `marketing_site/app/__init__.py`, `marketing_site/app/models/__init__.py`, `marketing_site/app/schemas/__init__.py`, `marketing_site/app/services/__init__.py`, `marketing_site/app/routes/__init__.py`
    - Create `marketing_site/app/config.py` with pydantic-settings `Settings` class (database_url, app_name, debug)
    - Create `marketing_site/.env.example` with DATABASE_URL template
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 1.2 Create database.py and SQLAlchemy base model
    - Create `marketing_site/app/database.py` with SQLAlchemy engine creation from `settings.database_url`, SessionLocal factory, and `get_db` dependency
    - Create `marketing_site/app/models/base.py` with `Base = declarative_base()`
    - _Requirements: 7.1_

  - [x] 1.3 Create Dockerfile, entrypoint.sh, and Docker Compose service
    - Create `marketing_site/Dockerfile` (python:3.11-slim, install deps, copy app, non-root user, expose 8000)
    - Create `marketing_site/entrypoint.sh` (wait for PostgreSQL with nc, run alembic upgrade head, start uvicorn with 2 workers)
    - Add `marketing` service to `reddit_saas/docker-compose.yml` (build context: ../marketing_site, port 8001:8000, DATABASE_URL env, depends_on db with service_healthy, resource limits 256M/0.5 CPU)
    - _Requirements: 10.1_

  - [x] 1.4 Create FastAPI application entry point
    - Create `marketing_site/app/main.py` with FastAPI app (title from settings, docs_url=None, redoc_url=None)
    - Mount static files at `/static`
    - Register page and API routers
    - Add `/health` endpoint returning `{"status": "ok", "service": "marketing"}`
    - Add custom 404 exception handler returning `marketing_404.html` template
    - _Requirements: 1.1, 1.6, 10.1_

- [x] 2. Database models and Alembic migration
  - [x] 2.1 Create SQLAlchemy models for all three tables
    - Create `marketing_site/app/models/waitlist_signup.py` — WaitlistSignup model with id (UUID PK), email (VARCHAR 320, unique, indexed), company, role, accounts_count, price_tier, feedback (Text), variant_shown (JSONB), source_page, created_at, updated_at (with onupdate)
    - Create `marketing_site/app/models/ab_test_assignment.py` — ABTestAssignment model with id (UUID PK), visitor_id (UUID, indexed), test_name (VARCHAR 100), variant_name (VARCHAR 100), assigned_at, converted (Boolean default False), converted_at (nullable)
    - Create `marketing_site/app/models/analytics_event.py` — AnalyticsEvent model with id (UUID PK), visitor_id (UUID, indexed), event_type (VARCHAR 100), event_data (JSONB), page_path (VARCHAR 500), timestamp
    - All models import Base from `app.models.base`
    - Add composite indexes: ab_test_assignments(test_name, variant_name), analytics_events(event_type, timestamp), waitlist_signups(created_at)
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [x] 2.2 Set up Alembic configuration and initial migration
    - Create `marketing_site/alembic.ini` with `version_table = alembic_version_marketing` and script_location pointing to `alembic/`
    - Create `marketing_site/alembic/env.py` importing Base metadata and settings.database_url
    - Create initial migration `marketing_site/alembic/versions/001_create_marketing_tables.py` creating all three tables with indexes
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [x] 3. Checkpoint - Verify infrastructure builds
  - Ensure Docker builds successfully (`docker compose build marketing`), Alembic migration runs, and `/health` endpoint responds. Ask the user if questions arise.

- [x] 4. Pydantic schemas and service layer
  - [x] 4.1 Create Pydantic request/response schemas
    - Create `marketing_site/app/schemas/marketing.py` with:
      - `WaitlistSignupRequest` — email (required, max 254, format validator), company, role, accounts_count (1-10000), price_tier, feedback (max 1000), variant_shown (dict), source_page
      - `ABAssignmentRecord` — test_name, variant_name
      - `RecordAssignmentsRequest` — visitor_id (UUID), assignments (list of ABAssignmentRecord)
      - `AnalyticsEventPayload` — visitor_id (UUID), event_type, event_data (optional dict), page_path, timestamp
      - `AnalyticsBatchRequest` — events (list, max_length=100)
    - Email validator: regex `^[^@\s]+@[^@\s]+\.[^@\s]+$`, strip + lowercase
    - _Requirements: 5.1, 5.4, 6.5, 6.6_

  - [x] 4.2 Implement A/B test configuration service
    - Create `marketing_site/app/services/ab_tests.py` with:
      - `Variant` and `ABTest` dataclasses
      - `ACTIVE_TESTS` list with 4 tests: mobile_pricing (3 variants), mobile_model (3 variants), proxy_pricing (3 variants), proxy_guarantee (2 variants)
      - `get_tests_for_page(page)` — filter tests by page
      - `get_default_variants()` — return first variant of each test (no-JS fallback)
      - `is_valid_variant(test_name, variant_name)` — validate variant exists
    - _Requirements: 4.4, 4.6, 10.2_

  - [x] 4.3 Implement waitlist service
    - Create `marketing_site/app/services/waitlist.py` with:
      - `process_signup(db, email, company, role, accounts_count, price_tier, feedback, variant_shown, source_page, visitor_id)` — create or update (upsert by email), mark conversions if visitor_id present
      - `mark_conversions(db, visitor_id)` — set converted=True and converted_at on all ab_test_assignments for visitor
    - _Requirements: 5.2, 5.5, 7.5_

  - [x] 4.4 Implement analytics service
    - Create `marketing_site/app/services/analytics.py` with:
      - `validate_event(payload)` — check required fields (visitor_id, event_type, timestamp), return EventPayload or None
      - `store_events(db, events)` — bulk insert validated AnalyticsEvent records, return count
    - _Requirements: 6.5, 6.6_

  - [ ]* 4.5 Write property tests for schemas and services (Properties 1-8)
    - **Property 1: Variant configuration lookup is consistent**
    - **Property 2: Assignment always produces valid output**
    - **Property 3: Existing valid assignments are idempotent**
    - **Property 4: New test assignment preserves existing**
    - **Property 5: Email validation rejects invalid formats**
    - **Property 6: Waitlist signup upsert produces exactly one record per email**
    - **Property 7: Conversion marking updates all visitor assignment records**
    - **Property 8: Analytics event validation accepts iff required fields present**
    - Create `marketing_site/tests/conftest.py` with test DB fixtures and test client
    - Create `marketing_site/tests/test_marketing_properties.py`
    - **Validates: Requirements 2.5, 3.5, 4.1, 4.3, 4.6, 4.9, 5.2, 5.4, 5.5, 6.1, 6.5, 6.6, 7.5**

- [x] 5. Routes and API endpoints
  - [x] 5.1 Implement page routes
    - Create `marketing_site/app/routes/pages.py` with:
      - `GET /` — render `marketing_home.html`
      - `GET /mobile` — render `marketing_mobile.html` with default variant context
      - `GET /proxy` — render `marketing_proxy.html` with default variant context
      - `GET /thank-you` — render `marketing_thank_you.html`
    - Pass default variants from `get_default_variants()` to template context for no-JS fallback
    - _Requirements: 1.1, 1.2, 1.3, 2.3, 3.3, 8.4, 10.2_

  - [x] 5.2 Implement API routes
    - Create `marketing_site/app/routes/api.py` with:
      - `POST /waitlist/signup` — parse form data, validate with WaitlistSignupRequest, call process_signup, redirect to /thank-you on success, re-render page with errors on failure
      - `POST /api/analytics/events` — parse JSON body as AnalyticsBatchRequest, validate events, store valid ones, return count
      - `POST /api/ab/record` — parse JSON body as RecordAssignmentsRequest, validate each assignment with is_valid_variant, insert new records (skip existing visitor+test pairs), return 200
    - Handle DB errors on signup: catch SQLAlchemyError, return form with error message and retained data
    - _Requirements: 5.2, 5.3, 5.4, 5.5, 5.7, 6.5, 6.6, 4.5_

  - [ ]* 5.3 Write unit tests for routes
    - Test homepage returns 200 with expected content
    - Test mobile/proxy pages render with default pricing
    - Test thank-you page displays confirmation
    - Test 404 handler returns custom page
    - Test signup with valid data redirects to /thank-you
    - Test signup with invalid email shows inline error
    - Test signup with duplicate email updates record
    - Test analytics batch with valid events returns count
    - Test analytics batch with missing fields returns 422
    - Test AB record with valid assignments returns 200
    - Test AB record with invalid variant returns error
    - Create `marketing_site/tests/test_marketing_unit.py`
    - _Requirements: 1.1, 1.6, 5.2, 5.3, 5.4, 5.5, 6.5, 6.6, 8.1_

- [x] 6. Checkpoint - Verify backend functionality
  - Ensure all tests pass, API endpoints respond correctly, and database operations work. Ask the user if questions arise.

- [x] 7. Templates (Jinja2 + Tailwind CDN)
  - [x] 7.1 Create base template and shared layout
    - Create `marketing_site/app/templates/marketing_base.html` with:
      - Tailwind CSS CDN link
      - Shared header (logo + nav links to /, /mobile, /proxy)
      - Shared footer (copyright, links)
      - Content block for page-specific content
      - `marketing.js` script tag (deferred)
      - Meta tags for SEO
      - Premium light theme styling
    - Create `marketing_site/app/templates/marketing_404.html` with link back to homepage
    - _Requirements: 1.4, 1.5, 1.6_

  - [x] 7.2 Create homepage template
    - Create `marketing_site/app/templates/marketing_home.html` extending base with:
      - Hero section (headline + subheadline describing product benefit)
      - Two product navigation cards (Mobile and Proxy) with links to /mobile and /proxy
      - CTA buttons with data attributes for analytics tracking
    - _Requirements: 1.2, 1.3_

  - [x] 7.3 Create Mobile landing page template
    - Create `marketing_site/app/templates/marketing_mobile.html` extending base with:
      - Headline: "Grow your personal brand on Reddit without risking your account"
      - Content sections in order: headline, key benefits (3+), how-it-works steps (3+), social proof (1+), pricing section, waitlist form
      - Pricing section with data attributes for JS variant replacement
      - Default pricing rendered server-side (first variant values)
      - Include waitlist form partial directly after pricing
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 10.2_

  - [x] 7.4 Create Proxy landing page template
    - Create `marketing_site/app/templates/marketing_proxy.html` extending base with:
      - Headline: "Scale your Reddit marketing — we manage everything"
      - Content sections in order: headline, key benefits (3+), managed service details (3+), social proof (1+), pricing section, waitlist form
      - Pricing section with data attributes for JS variant replacement
      - Default pricing rendered server-side (first variant values)
      - Include waitlist form partial directly after pricing
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 10.2_

  - [x] 7.5 Create waitlist form partial and thank-you page
    - Create `marketing_site/app/templates/partials/marketing_waitlist_form.html` with:
      - Fields: email (required), company (optional), role (optional), accounts_count (optional), feedback (optional, textarea)
      - Hidden fields: price_tier (auto-populated from variant), variant_shown (JSON), source_page
      - Inline validation error display area below email field
      - Form action: POST /waitlist/signup
      - Data retention on error (values pre-filled from context)
    - Create `marketing_site/app/templates/marketing_thank_you.html` with:
      - Confirmation message including "You're on the list"
      - Navigation links back to homepage and source landing page
      - Same shared base layout
    - _Requirements: 5.1, 5.4, 5.6, 5.7, 8.1, 8.2, 8.3, 8.4_

- [x] 8. Client-side JavaScript
  - [x] 8.1 Implement marketing.js — visitor identity and A/B engine
    - Create `marketing_site/app/static/js/marketing.js` as IIFE module with:
      - **Visitor Identity**: `getOrCreateVisitorId()` — generate UUID v4, store in cookie "visitor_id" with 30-day expiry and path="/", validate existing cookie format (8-4-4-4-12 hex), refresh expiry on each visit
      - **A/B Engine**: `getAssignments()` — read variant cookies; `assignVariant(testName, variants)` — uniform random selection; `applyVariants(assignments)` — update DOM elements with data-ab-test attributes; `recordAssignments(visitorId, assignments)` — POST to /api/ab/record with 3 retries and exponential backoff
      - Cookie handling: set variant cookies with 30-day expiry, detect corrupted/invalid cookies and reassign
      - On page load: get/create visitor ID, check variant cookies, assign if missing, apply to DOM, record to server
    - _Requirements: 4.1, 4.2, 4.3, 4.5, 4.6, 4.7, 9.1, 9.2, 9.3, 9.4, 9.5_

  - [x] 8.2 Implement marketing.js — analytics tracker
    - Add to `marketing_site/app/static/js/marketing.js`:
      - **Event Queue**: array with max 100 events, auto-flush at 20 events or 5-second interval
      - **Track Functions**: `trackEvent(type, data)` — add to queue with visitor_id, page_path, timestamp; auto-track page_view on load; track clicks on elements with `data-track-click` attribute; track signup event on form submit
      - **Batch Send**: `flushQueue()` — POST to /api/analytics/events, on failure store in localStorage
      - **Offline Queue**: store failed events in localStorage (max 50), retry on next page load, discard events older than 72 hours
      - **Flush on unload**: `beforeunload` event triggers flush
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 10.3, 10.5_

  - [x] 8.3 Create minimal CSS file
    - Create `marketing_site/app/static/css/marketing.css` with minimal custom styles (Tailwind CDN handles most styling)
    - Add any custom animations, transitions, or component styles not covered by Tailwind utilities
    - Create placeholder `marketing_site/app/static/images/logo.svg`
    - _Requirements: 1.5, 10.1_

- [x] 9. Checkpoint - Verify full frontend functionality
  - Ensure pages render correctly with Tailwind styling, JavaScript loads and executes (visitor ID generation, variant assignment, analytics tracking), and form submission works end-to-end. Ask the user if questions arise.

- [x] 10. Integration wiring and Docker verification
  - [x] 10.1 Wire all components together and verify Docker build
    - Verify `marketing_site/app/main.py` correctly imports and registers all routers
    - Verify static file serving works (CSS, JS, images) with proper cache headers
    - Verify Alembic migration runs successfully in Docker context
    - Verify `entrypoint.sh` waits for DB and runs migrations before starting uvicorn
    - Test `docker compose build marketing` succeeds
    - Test `docker compose up marketing` starts and `/health` responds
    - Verify marketing container can connect to shared PostgreSQL
    - _Requirements: 10.1, 10.4_

  - [ ]* 10.2 Write integration tests
    - Create `marketing_site/tests/test_marketing_integration.py` with:
      - Full signup flow: GET /mobile → POST /waitlist/signup → verify redirect to /thank-you → verify DB record
      - Analytics batch: POST valid events → verify analytics_events table
      - AB assignment recording: POST assignments → verify ab_test_assignments table
      - Conversion marking: signup with visitor_id → verify converted=True on assignments
      - Duplicate signup: submit same email twice → verify single record with updated fields
      - Health check: GET /health returns 200
    - _Requirements: 5.2, 5.3, 5.5, 6.5, 7.5, 4.5_

  - [ ]* 10.3 Write property tests for visitor identity (Properties 10, 11)
    - **Property 10: Generated visitor_id conforms to UUID v4 format**
    - **Property 11: Invalid UUID strings are correctly detected**
    - Add UUID generation and validation utility functions to a testable Python module (for server-side validation of visitor_id in API requests)
    - Add tests to `marketing_site/tests/test_marketing_properties.py`
    - **Validates: Requirements 9.1, 9.4**

- [x] 11. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, Docker container builds and runs successfully, all pages render, forms submit, and APIs respond correctly. Ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (13 properties total; Properties 9, 12, 13 are client-side JS and tested via example-based tests in task 8.2)
- Unit tests validate specific examples and edge cases
- All code lives in `marketing_site/` — completely independent from `reddit_saas/app/`
- Models import from `app.models.base` (not `app.database`)
- Alembic uses `version_table = alembic_version_marketing` to avoid conflicts with main app migrations
- Docker Compose service added to existing `reddit_saas/docker-compose.yml` with build context `../marketing_site`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["1.4", "2.1"] },
    { "id": 3, "tasks": ["2.2"] },
    { "id": 4, "tasks": ["4.1", "4.2"] },
    { "id": 5, "tasks": ["4.3", "4.4"] },
    { "id": 6, "tasks": ["4.5", "5.1"] },
    { "id": 7, "tasks": ["5.2"] },
    { "id": 8, "tasks": ["5.3", "7.1"] },
    { "id": 9, "tasks": ["7.2", "7.3", "7.4"] },
    { "id": 10, "tasks": ["7.5"] },
    { "id": 11, "tasks": ["8.1"] },
    { "id": 12, "tasks": ["8.2", "8.3"] },
    { "id": 13, "tasks": ["10.1"] },
    { "id": 14, "tasks": ["10.2", "10.3"] }
  ]
}
```
