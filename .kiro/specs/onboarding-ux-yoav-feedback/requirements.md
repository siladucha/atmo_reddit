# Onboarding UX Improvements — Yoav Feedback (July 3, 2026)

## Context

Yoav Machlin (prospect, first external trial user) completed the self-service onboarding flow on July 3, 2026 and provided detailed feedback. His feedback validates the overall flow ("really impressive") while identifying specific friction points that would block conversions from other self-serve users.

**Source:** Email from Yoav → Tzvi → Max (July 3, 2026)
**Priority:** High — this is the critical path for self-serve growth. Every friction point here = lost trial conversions.

---

## Requirements

### REQ-1: Website Scraper Resilience (Bug — P0)

**Problem:** When entering atera.com, the scraper returned 403 and showed error "Could not auto-detect your profile". User confused.

**Requirement:**
- Scraper must handle 403/401/429 gracefully with at least 2 retry attempts using different User-Agent headers
- If all retries fail, show manual fields immediately WITHOUT an error banner. Just pre-populate with what we CAN detect (company name from domain)
- Company name field should default to domain-derived name (e.g., "Atera" from atera.com), NOT from user's email address

**Acceptance:**
- atera.com → scraper retries → if still fails → fields appear with "Atera" pre-filled as company name
- No scary red error message — just a gentle "We'll need a few details" transition

---

### REQ-2: Company Name from URL, Not Email (Bug — P0)

**Problem:** Company name was populated from email prefix (yoav.machlin) instead of from the URL domain.

**Requirement:**
- Step 1 auto-detection: company name derived from URL domain (strip TLD, capitalize)
- If URL scrape fails: company name = domain-derived, NOT email-derived
- If user didn't enter URL: company name left blank (user fills manually)

**Acceptance:**
- Enter "atera.com" → company_name pre-filled as "Atera"
- Signup with yoav.machlin@gmail.com, enter atera.com → name is "Atera" not "Yoav Machlin"

---

### REQ-3: Graceful AI Fallback on Step 2 (UX — P1)

**Problem:** AI suggestions failed initially on Step 2 (Problem/Positioning). User had to go back to Step 1 and re-fill data before it worked.

**Requirement:**
- If AI suggestion fails (timeout, LLM error, missing context): immediately show empty manual fields with helpful placeholders
- Add "Try AI again" button (not auto-retry to avoid cost)
- Show context-aware placeholders even when AI fails (from industry detection or URL domain)
- Never block the user from proceeding — manual path always available

**Acceptance:**
- AI fails → fields appear empty with good placeholders → user can fill manually OR click "Try AI again"
- No page navigation required to recover from AI failure

---

### REQ-4: Manual Fill Option Per Block (UX — P1)

**Problem:** User wants ability to fill some fields manually and leave others AI-generated.

**Requirement:**
- Each AI-generated content block has a "Fill manually" toggle/button below it
- Clicking it converts that specific block to an editable empty field
- Other blocks remain AI-filled
- "Regenerate" button available to get AI suggestion back for that block

**Acceptance:**
- Step 2: "Problem you solve" has AI suggestion + "Edit manually" link
- Click → field becomes editable with AI text as starting point
- Other fields (Advantage, Competitors) remain AI-generated

---

### REQ-5: Subreddit Finder Visibility (UX — P1)

**Problem:** User didn't notice the AI subreddit finder in Step 4.

**Requirement:**
- Make subreddit AI suggestion more prominent in Step 4
- Add explicit "Find subreddits with AI" button with explanation text
- Show results as selectable cards (not just a list)
- Add visual distinction between AI-suggested and manually entered subreddits

**Acceptance:**
- Step 4 shows prominent "🔍 Find relevant subreddits" CTA above the manual input
- Results appear as cards with subreddit description + member count

---

### REQ-6: Strategy Page Structured Layout (UX — P2)

**Problem:** Strategy page shows a raw paragraph. Not self-explanatory.

**Requirement:**
- Transform strategy display from paragraph to structured sections:
  - Subreddits to prioritize (list with engagement approach)
  - Tone to use (with examples)
  - Posting frequency (per week)
  - Hooks & approaches (what works in these communities)
  - Content themes (pillars)
  - Forbidden zones (what to avoid)
- Each section collapsible with header
- "Regenerate Strategy" button at bottom

**Acceptance:**
- Strategy page renders as organized card layout, not wall of text
- User can scan structure at a glance

---

### REQ-7: Sidebar Navigation to Onboarding Settings (UX — P2)

**Problem:** Left sidebar doesn't make it easy to go back and fine-tune onboarding areas.

**Requirement:**
- Add "Configuration" or "Setup" section to portal sidebar with links to:
  - Company Profile (Step 1-2 data)
  - Target Audience / ICP (Step 3 data)
  - Voice & Keywords (Step 4 data)
  - Subreddits (already exists)
- Each link opens the relevant settings/edit page (not re-enters wizard)

**Acceptance:**
- Sidebar has "Setup" section with direct links
- Clicking "Voice & Keywords" opens settings page pre-populated with current data

---

### REQ-8: Report Empty State with CTA (UX — P1)

**Problem:** Report page without data shows nothing useful.

**Requirement:**
- When visibility report has no data, show:
  - Explanation of what the report will show once data accumulates
  - Timeline expectation ("First results appear after 1-2 weeks of activity")
  - CTA: "Schedule a call to review your configuration" (mailto link to Tzvi)
  - Visual progress indicators showing what's active vs pending

**Acceptance:**
- New trial user visiting /visibility sees helpful empty state, not blank page
- Clear expectation setting on when data will appear

---

### REQ-9: Step 3 (ICP) Streamlining (UX — P3, needs design decision)

**Problem:** User found Step 3 (Ideal Customer Profile) repetitive with Step 2.

**Requirement (evaluate):**
- Option A: Merge Step 2 and Step 3 into single longer step
- Option B: Keep separate but reduce overlap (Step 2 = your solution, Step 3 = your buyer)
- Option C: Make Step 3 optional ("Skip — use defaults from Step 2")

**Decision needed:** Which approach to take. For now, keep separate but add "auto-fill from previous step" intelligence so it's less repetitive.

---

### REQ-10: Keyword AI Suggestion Prominence (UX — P2)

**Problem:** Same discoverability issue as subreddits — AI keyword suggestion exists but not prominent.

**Requirement:**
- Step 4 keyword section: prominent "✨ Suggest keywords with AI" button
- Show AI suggestions as selectable chips (accept/reject individually)
- Group by priority (high/medium/low) visually

**Acceptance:**
- Keywords section shows big "Generate AI suggestions" button
- Results appear as colored chips grouped by priority

---

## Priority Summary

| Priority | Requirements | Effort |
|----------|-------------|--------|
| P0 (bugs) | REQ-1, REQ-2 | 1-2 hours |
| P1 (core UX) | REQ-3, REQ-4, REQ-5, REQ-8 | 4-6 hours |
| P2 (polish) | REQ-6, REQ-7, REQ-10 | 4-6 hours |
| P3 (design decision) | REQ-9 | TBD |

Total estimated: 1-2 days focused work for P0+P1.

## Overall Sentiment

> "All in all - really impressive - I can't wait to see it working and recommend colleagues to do the same!"

The foundation is solid. These are polish items that will significantly improve conversion rate for self-serve trials.
