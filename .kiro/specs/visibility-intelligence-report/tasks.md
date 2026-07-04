# Visibility Intelligence Report — Tasks

## Task 1: Rewrite Demo Report with Real Data
- [ ] Replace fake numbers with Ono baseline (7.7% brand mention rate)
- [ ] Implement S-curve growth projection (24 weeks, per-engine multipliers, noise)
- [ ] Replace competitor names: Tel Aviv Uni, Hebrew Uni, Technion, Bar-Ilan, BGU, Reichman
- [ ] Add hero delta metric section ("7.7% → 38% projected = +30pp growth")
- [ ] Add "AI Response Examples" accordion with 2 real Perplexity excerpts
- [ ] Add "Top Queries" section with 5 real prompts + ✅/❌ indicators per engine
- [ ] Add category breakdown table (category, problem, use_case, comparison, opinion)
- [ ] Update competitor bar chart with real mention rates from batch data
- [ ] Fix date display ("Last batch: Jun 29, 2026 20:07")
- [ ] Deploy to production (`rsync + docker compose up -d nginx`)

## Task 2: Visibility Report Service
- [ ] Create `app/services/visibility_report.py`
- [ ] Implement `get_baseline()` — first batch brand_mentioned rate
- [ ] Implement `get_latest()` — most recent batch rate
- [ ] Implement `get_trend_weekly()` — group batches by week, compute rate per week
- [ ] Implement `get_by_engine()` — brand mention rate per provider
- [ ] Implement `get_by_category()` — rate per geo_prompts.category
- [ ] Implement `get_top_queries()` — prompts with per-engine hit/miss
- [ ] Implement `get_competitor_share()` — competitor mention frequency
- [ ] Implement `get_excerpts()` — response text snippets where brand mentioned

## Task 3: API Endpoint
- [ ] Create `app/routes/visibility_report.py`
- [ ] Add `GET /api/clients/{id}/visibility-report` endpoint
- [ ] Add RBAC guard (require_client_access)
- [ ] Wire service methods to JSON response
- [ ] Register router in `main.py`

## Task 4: Portal Template — Visibility Page Enhancement
- [ ] Update `app/templates/client/visibility.html` — add chart containers + HTMX triggers
- [ ] Create `app/templates/partials/visibility_hero.html` — hero metrics + delta
- [ ] Create `app/templates/partials/visibility_engines.html` — 3 engine cards
- [ ] Create `app/templates/partials/visibility_trend.html` — Chart.js trend graph
- [ ] Create `app/templates/partials/visibility_queries.html` — query table with ✅/❌
- [ ] Create `app/templates/partials/visibility_excerpts.html` — AI response quotes
- [ ] Create `app/templates/partials/visibility_competitors.html` — bar chart
- [ ] Create `app/templates/partials/visibility_categories.html` — category breakdown table

## Task 5: Admin GEO — Category Management
- [ ] Ensure `category` field visible in admin prompt create/edit form
- [ ] Add category filter/group in admin GEO batch detail view
- [ ] Add category breakdown stats in batch summary

## Task 6: Citation Source Matching (Future — deferred)
- [ ] In `geo_brand_detection.py`: check if citation_url matches any avatar's posted Reddit comment
- [ ] If match: mark as "RAMP-generated citation" in query result
- [ ] Show in report: "This citation was created by your RAMP avatar"
