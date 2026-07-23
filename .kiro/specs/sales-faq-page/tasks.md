# Implementation Plan: Sales FAQ Page

## Overview

Add a compliance-vetted FAQ accordion to the RAMP marketing site. The implementation creates a shared FAQ data module, a reusable Jinja2 partial, a standalone `/faq` route, and modifies the existing `/pricing` page to embed the accordion. All FAQ content adheres to RAMP's strict language rules (no prohibited terms, approved phrases required). Tests cover route responses and compliance properties.

## Tasks

- [ ] 1. Create FAQ data module and shared partial
  - [ ] 1.1 Create `app/data/faq_data.py` with 7 FAQ entries
    - Create `marketing_site/app/data/__init__.py` (empty)
    - Create `marketing_site/app/data/faq_data.py` with `FAQ_ITEMS: list[dict[str, str]]`
    - Write all 7 question-answer entries covering: voice protection (Req 3), human-in-the-loop differentiation (Req 4), results expectations (Req 5), existing accounts audit (Req 6), content authorship (Req 7), plan inclusions (Req 8), cancellation policy (Req 9)
    - Each answer must contain at least one approved phrase: "community engagement management", "persona-driven content strategy", or "human-in-the-loop"
    - Each answer must avoid all prohibited terms per Requirement 11
    - Answers may contain safe inline HTML (`<strong>`, `<br>`, `<ul>`/`<li>`) for formatting
    - _Requirements: 1.2, 3.1–3.5, 4.1–4.5, 5.1–5.4, 6.1–6.4, 7.1–7.6, 8.1–8.6, 9.1–9.4, 11.1–11.6_

  - [ ] 1.2 Create `partials/faq_section.html` Jinja2 partial
    - Create `marketing_site/app/templates/partials/faq_section.html`
    - Iterate over `faq_items` context variable using `{% for item in faq_items %}`
    - Each item renders as a `<button>` (question) + hidden `<div>` (answer)
    - Include `aria-expanded="false"`, `aria-controls`, `role="region"`, `aria-labelledby` attributes
    - Use Tailwind CSS classes for styling (border, rounded, padding, colors matching dark theme)
    - Touch targets: `py-5 px-6` ensuring ≥44px height
    - Chevron SVG icon with rotation transition on expand
    - Inline `<style>` block for `.faq-content` max-height transition and chevron rotation
    - Inline `<script>` block with `toggleFaq(btn)` function toggling `aria-expanded` and `.open` class
    - Answer rendered with `{{ item.answer | safe }}`
    - _Requirements: 1.3, 1.4, 1.5, 1.7, 10.1–10.5, 12.2, 12.3_

- [ ] 2. Implement standalone FAQ page and modify pricing route
  - [ ] 2.1 Create `marketing_faq.html` template
    - Create `marketing_site/app/templates/marketing_faq.html`
    - Extend `marketing_base.html`
    - Set `<title>` block: "FAQ — RAMP Community Engagement" (≤60 chars, contains "FAQ")
    - Set `<meta name="description">` block: summarize FAQ content (≤155 chars)
    - Render heading "FREQUENTLY ASKED QUESTIONS" (uppercase, bold, white text)
    - `{% include "partials/faq_section.html" %}`
    - CTA below FAQ linking to `/onboard/trial` ("Start Your Free Trial →")
    - Responsive: `max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-20`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 12.1_

  - [ ] 2.2 Register `/faq` route in `pages.py` and modify `/pricing` handler
    - Import `FAQ_ITEMS` from `app.data.faq_data` in `pages.py`
    - Add `/faq` route as async handler returning `templates.TemplateResponse` with `response_class=HTMLResponse`, passing `{"faq_items": FAQ_ITEMS}` in context
    - Modify existing `/pricing` handler to pass `{"faq_items": FAQ_ITEMS}` in context
    - _Requirements: 2.1, 2.5, 12.4, 12.5_

  - [ ] 2.3 Modify `marketing_pricing.html` to embed FAQ partial
    - Replace the existing hardcoded "COMMON QUESTIONS" section with the dynamic accordion
    - Add section with heading "FREQUENTLY ASKED QUESTIONS" (h2, uppercase, bold, white)
    - `{% include "partials/faq_section.html" %}`
    - Position between Agency Plans section and Bottom CTA (same location as current Q&A)
    - _Requirements: 1.1, 1.6, 10.1–10.5_

- [ ] 3. Checkpoint - Verify FAQ renders correctly
  - Ensure the marketing site starts without errors, `/faq` returns 200, `/pricing` contains the FAQ accordion. Ask the user if questions arise.

- [ ] 4. Write tests for routes and compliance
  - [ ] 4.1 Create `tests/test_marketing_faq.py` with route and data tests
    - Create `marketing_site/tests/test_marketing_faq.py`
    - Test `GET /faq` returns HTTP 200 and contains FAQ content (title, meta description, accordion items, CTA link)
    - Test `GET /pricing` returns HTTP 200 and contains FAQ accordion section
    - Test `FAQ_ITEMS` has 3 ≤ len ≤ 10 items
    - Test each item in `FAQ_ITEMS` has `"question"` and `"answer"` keys with non-empty string values
    - Test content parity: verify both routes use the same `FAQ_ITEMS` data source
    - Use pytest + httpx AsyncClient pattern matching existing marketing site test setup
    - _Requirements: 1.2, 2.1, 2.2, 12.4_

  - [ ]* 4.2 Write property test for compliance prohibited terms exclusion
    - **Property 1: Compliance Prohibited Terms Exclusion**
    - Test that no FAQ item (question or answer) contains any prohibited term (whole-word, case-insensitive): "fake accounts", "fake account", "bot", "bots", "automated posting", "evading detection", "avatar", "avatars", "VPN", "multi-IP", "karma farming", "karma farm", "account warming", "account warm-up", "proxy", "residential IP", "rotating IP", "terms of service", "ToS", "Reddit rules", "platform rules", "rule violation", "policy violation", "against the rules", "ban", "shadowban", "suspended"
    - Verify compound words containing prohibited substrings (e.g., "robot", "chatbot") are NOT flagged
    - Use Hypothesis to generate random FAQ item structures and verify the compliance checker correctly identifies violations
    - **Validates: Requirements 3.3, 3.4, 4.4, 6.4, 7.4, 7.5, 8.6, 11.1, 11.2, 11.3, 11.5**

  - [ ]* 4.3 Write property test for approved phrase inclusion
    - **Property 2: Approved Phrase Inclusion**
    - Test that every FAQ item answer contains at least one approved phrase: "community engagement management", "persona-driven content strategy", or "human-in-the-loop"
    - Use Hypothesis to verify the checker correctly validates presence/absence of approved phrases
    - **Validates: Requirements 4.5, 11.4**

  - [ ]* 4.4 Write property test for no numerical performance guarantees
    - **Property 3: No Numerical Performance Guarantees**
    - Test that no FAQ item answer contains specific numerical performance metrics (patterns like "X karma", "X followers", "X% conversion", "guaranteed Y results")
    - Use Hypothesis to generate answer strings with numerical patterns and verify detection
    - **Validates: Requirements 5.4**

- [ ] 5. Update SEO references
  - [ ] 5.1 Add `/faq` to `robots.txt` Allow list and `sitemap.xml`
    - Add `Allow: /faq` to the robots.txt response in `pages.py`
    - Add FAQ URL entry to `sitemap.xml` response with `changefreq=monthly` and `priority=0.7`
    - Add FAQ to `llms.txt` pages list
    - _Requirements: 2.3_

- [ ] 6. Final checkpoint - Ensure all tests pass
  - Run `pytest marketing_site/tests/ -x -q` and ensure all tests pass. Ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties (compliance language rules)
- The FAQ data module (`app/data/faq_data.py`) is the single source of truth — both routes import from it, guaranteeing content parity (Property 4)
- No `app/data/` directory exists yet in marketing_site — task 1.1 creates it
- The existing "COMMON QUESTIONS" section in `marketing_pricing.html` will be replaced by the dynamic accordion

## Task Dependency Graph

Задачи сгруппированы в "волны" (waves). Задачи внутри одной волны независимы друг от друга и могут выполняться параллельно. Каждая следующая волна запускается только после завершения всех задач предыдущей.

| Wave | Задачи | Что делает | Зависит от |
|------|--------|-----------|------------|
| 0 | 1.1 | FAQ data module (контент) | — |
| 1 | 1.2, 2.2 | Partial template + route registration | Wave 0 (нужен data module) |
| 2 | 2.1, 2.3 | FAQ page template + pricing modification | Wave 1 (нужны partial и route) |
| 3 | 4.1, 5.1 | Route тесты + SEO | Wave 2 (нужны работающие страницы) |
| 4 | 4.2, 4.3, 4.4 | Property-based тесты (опционально) | Wave 3 (основные тесты готовы) |

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.2"] },
    { "id": 2, "tasks": ["2.1", "2.3"] },
    { "id": 3, "tasks": ["4.1", "5.1"] },
    { "id": 4, "tasks": ["4.2", "4.3", "4.4"] }
  ]
}
```
