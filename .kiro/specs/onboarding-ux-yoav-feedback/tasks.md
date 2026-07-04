# Tasks — Onboarding UX (Yoav Feedback)

## Task 1: Fix website scraper 403 handling [REQ-1] — P0
- [ ] In `app/services/onboarding/website_scraper.py`: add retry with 2 different User-Agent strings (Chrome, Firefox)
- [ ] On final failure: return partial result (company_name from domain) instead of raising error
- [ ] In `app/routes/onboarding.py` `step1_save`: if scrape returns partial/failed, show fields pre-filled with domain-derived name
- [ ] Remove scary error banner — replace with subtle "We'll need a few details manually" message
- [ ] Test with atera.com, cloudflare.com (known 403 sites)

## Task 2: Fix company name derivation [REQ-2] — P0
- [ ] In `step1_save`: derive company_name from URL domain (strip TLD, capitalize first letter)
- [ ] Remove fallback to email-derived name
- [ ] If no URL provided: leave company_name blank
- [ ] Verify: signup with gmail → enter atera.com → name shows "Atera"

## Task 3: AI failure graceful fallback on Step 2 [REQ-3] — P1
- [ ] In Step 2 template: if AI call fails, render empty fields immediately (no redirect needed)
- [ ] Add "✨ Try AI again" button (hx-post to re-generate)
- [ ] Set context-aware placeholders from industry/domain even without AI
- [ ] Manual path always works regardless of AI state

## Task 4: Per-block manual edit toggle [REQ-4] — P1
- [ ] Add "Edit manually" link below each AI-generated text block in Steps 2, 3, 4
- [ ] JS: clicking toggle makes field editable (pre-filled with AI text)
- [ ] Add "↺ Regenerate" small button to get AI suggestion back
- [ ] Each block is independent (editing one doesn't affect others)

## Task 5: Subreddit finder prominence [REQ-5] — P1
- [ ] Step 4: move "Find subreddits with AI" button to prominent position (above manual input)
- [ ] Add explanatory text: "We'll find communities where your audience discusses problems you solve"
- [ ] Show results as cards with description (not plain list)
- [ ] Visual badge distinguishing AI-suggested vs manually entered

## Task 6: Report empty state CTA [REQ-8] — P1
- [ ] In `client/visibility.html`: enhance "no data" state with:
  - Timeline explanation ("Results appear after 1-2 weeks")
  - What's being set up (monitoring queries, competitor tracking)
  - CTA mailto link to account manager
- [ ] In `client/home.html` (report card): same empty state messaging

## Task 7: Strategy page structured layout [REQ-6] — P2
- [ ] In `client/strategy.html`: parse strategy text into sections
- [ ] Render as collapsible cards: Subreddits, Tone, Frequency, Hooks, Themes, Forbidden
- [ ] Add "Regenerate Strategy" button at bottom
- [ ] If strategy is raw paragraph (legacy): display as-is with upgrade prompt

## Task 8: Sidebar setup links [REQ-7] — P2
- [ ] In `partials/client/sidebar.html`: add "Setup" section with:
  - Company Profile → /clients/{id}/settings (profile section)
  - Voice & Keywords → /clients/{id}/keywords
  - Target Audience → /clients/{id}/settings (ICP section)
- [ ] Highlight items that are incomplete/empty

## Task 9: Keyword suggestion prominence [REQ-10] — P2
- [ ] Step 4: prominent "✨ Generate keyword suggestions" button
- [ ] Results as colored chips (green=high, yellow=medium, gray=low)
- [ ] One-click accept/reject per chip
- [ ] Accepted chips auto-populate keyword fields

## Task 10: Evaluate Step 2+3 merge [REQ-9] — P3
- [ ] Document overlap between Step 2 (Problem/Positioning) and Step 3 (ICP)
- [ ] Prototype Option B: reduce Step 3 to only buyer-specific fields (title, pain, buying triggers)
- [ ] Add "auto-fill from Step 2" pre-population for shared fields
- [ ] Decision: merge or keep separate (after 5+ trial user feedback)
