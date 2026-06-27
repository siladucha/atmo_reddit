# Auto Competitor Discovery + Post-Onboarding Automation

## Context

After client completes 6-step onboarding, the system has enough data to automatically:
1. Discover competitors by querying AI chatbots (ChatGPT, Gemini, Perplexity)
2. Present discovered competitors to client for review
3. Once confirmed → auto-start Discovery Engine + GEO/AEO monitoring

Currently both Discovery and GEO are started manually by operator. Tzvi wants this automated from onboarding data.

## Problem Statement

- Client finishes onboarding → nothing happens until operator manually starts Discovery
- Client may not know all their competitors (only names 2-3, AI search sees 5-10)
- GEO prompts are created manually — should be seeded from onboarding data
- Gap between "onboarding complete" and "pipeline producing value" is 1-3 days (operator bottleneck)

## Requirements

### FR-1: AI Competitor Discovery (post-onboarding)

After `onboarding_completed_at` is set:
1. System automatically queries AI platforms with prompts like:
   - "What are the best {industry} {product_category} tools?"
   - "What are alternatives to {brand_name}?"
   - "{problem_description} — what solutions exist?"
2. Parse AI responses to extract brand names mentioned
3. Cross-reference with `client.competitive_landscape` (client-provided)
4. Store as `DiscoveredCompetitor` records (name, source, confidence, confirmed=null)

### FR-2: Client Review (before activation)

1. Client portal shows notification: "We found X potential competitors in AI search — please review"
2. Client sees list: each competitor with source ("mentioned by ChatGPT in response to..."), confidence
3. Client actions per competitor: Confirm / Remove / "Not a competitor"
4. Client can add more manually
5. Only confirmed competitors proceed to GEO monitoring

### FR-3: Auto-Start Discovery Engine

After client confirms competitors (or after 48h timeout if client ignores):
1. Create DiscoverySession automatically with:
   - Brief from: `company_profile + worldview + problem + competitive_landscape + confirmed_competitors`
   - Skip entity extraction step (use onboarding data directly)
2. Run research phase automatically
3. Generate report → make available in portal

### FR-4: Auto-Start GEO/AEO Monitoring

After competitor confirmation:
1. Create `GeoCompetitor` records for each confirmed competitor
2. Auto-generate `GeoPrompt` records:
   - "best {category} tools" (brand visibility)
   - "{brand} vs {competitor}" (head-to-head, per competitor)
   - "alternatives to {competitor}" (per competitor)
   - "{problem} solutions" (category query)
3. Run first batch execution immediately
4. Schedule recurring monitoring (weekly)

### FR-5: Human-in-the-Loop Guarantee

- System NEVER runs GEO monitoring without client seeing the competitor list
- If client doesn't review within 48h → operator notification (not auto-start)
- Client can always add/remove competitors later from portal
- All auto-generated prompts are visible and editable by client

## Non-Functional Requirements

### NFR-1: Cost
- AI competitor discovery: 3-5 Gemini Flash calls per client (~$0.002)
- Must not run discovery if client already has 3+ confirmed competitors from onboarding

### NFR-2: Timing
- Competitor discovery triggers within 5 minutes of `onboarding_completed_at`
- Should not block or slow down onboarding completion UX

### NFR-3: Idempotency
- If onboarding triggers twice (race condition), only one discovery runs
- DistributedLock on `auto_discovery:{client_id}`

## Data Available from Onboarding

| Field | Source | Useful For |
|-------|--------|-----------|
| `company_profile` | Step 1 (AI scrape) | Category inference |
| `industry` | Step 1 | Query construction |
| `company_worldview` | Step 2 | Problem framing |
| `company_problem` | Step 2 | Solution category |
| `competitive_landscape` | Step 2 | Known competitors (seed) |
| `icp_profiles` | Step 3 | Audience context |
| `keywords` | Step 4 | Topic terms |
| `brand_name` / `client_name` | Step 1 | Brand identity |

## Out of Scope

- Multi-platform GEO (only Gemini Flash for MVP — cheapest)
- Real-time monitoring (weekly batch is fine)
- Automatic competitor removal if they go out of business
- Competitor website scraping (just names + AI mentions)

## Success Criteria

1. New trial client completes onboarding → within 10 min sees "X competitors discovered"
2. Client confirms → within 1 hour, GEO first run complete + Discovery report available
3. Zero operator intervention needed for standard flow
4. Cost per new client: < $0.01 for competitor discovery
