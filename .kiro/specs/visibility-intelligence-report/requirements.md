# Visibility Intelligence Report — Requirements

## Problem Statement

Current GEO/AEO monitoring produces raw batch data (brand_mentioned true/false, competitor lists, response excerpts). This data is not presented in a way that:
1. Clients can understand their AI search visibility status
2. Sales team (Tzvi) can use as proof-of-value on calls
3. Shows progress over time (trend, before/after)
4. Provides actionable context (what queries work, what doesn't, who's winning)

ReddGrow competitor offers a superficial one-time snapshot (no trends, no recommendations, 242 domains dumped without context). We need to be demonstrably better: continuous monitoring, real excerpts, category breakdown, and progress tracking.

## Scope

Two deliverables:
1. **Demo Report** (`/demo/share-of-voice.html`) — static HTML with real baseline data + realistic projected growth curve. Used by Tzvi on sales calls. No auth required. `noindex` meta.
2. **Live Client Report** (portal: `/clients/{id}/visibility`) — dynamic, data-driven from GEO batches. Shows real data, real trends, real excerpts. Requires auth.

---

## Requirements

### R1: Real Baseline Data in Demo Report

**Priority: HIGH**

The demo report must use actual data from Ono's GEO batches as the starting point:
- Baseline brand mention rate: **7.7%** (2/26 queries, Perplexity only, Jun 29 2026)
- Competitors present in 90%+ answers: Tel Aviv University, Hebrew University, Technion, Bar-Ilan, BGU, Reichman
- Ono mentioned by: Perplexity (2/20 = 10%), Claude (0/6 = 0%)
- Categories tested: category (academic programs), problem (immigration/integration), use_case (career), comparison, opinion

### R2: Realistic Growth Projection (6-month)

**Priority: HIGH**

Project visibility growth from baseline using S-curve model:
- Month 1 (current): 7.7% (real data)
- Month 2: 12-15% (early Reddit content indexed)
- Month 3: 20-25% (avatar authority building)
- Month 4: 28-32% (entity linking taking effect)
- Month 5: 33-38% (steady state approaching)
- Month 6: 35-42% (plateau zone)

Growth is NOT linear — add realistic weekly variance (±2-4pp). Different engines grow at different rates:
- Perplexity: fastest (cites Reddit heavily, ~1.5x base rate)
- ChatGPT: medium (web search grounding, ~1.0x)
- Claude: slowest (less Reddit dependency, ~0.7x)

### R3: AI Response Excerpts (Demo + Live)

**Priority: HIGH**

Show 2-3 actual AI response excerpts per category where brand IS mentioned:
- Quote from LLM response (first 150 chars of relevant section)
- Engine badge (Perplexity/ChatGPT/Claude)
- Whether brand was mentioned (✅/❌)
- Date of check

For demo: use real excerpts from Ono batch (2 brand mentions exist).
For categories without mentions: show "Not yet cited — this is your opportunity" with the competitor who IS cited.

### R4: Top Queries with Hit/Miss Indicator

**Priority: HIGH**

Show the actual prompts used, grouped by category, with clear ✅ (brand mentioned) / ❌ (not mentioned) per engine:
- "Academic programs for English speakers in Israel" → ✅ Perplexity, ❌ Claude
- "Guide to higher education for new olim" → ✅ Perplexity, ❌ Claude
- "Career placement for English speakers in Israel" → ❌ all engines

This immediately shows the client WHERE they're visible and WHERE they're not.

### R5: Competitor Benchmark (Top 5 only)

**Priority: MEDIUM**

Replace the 242-domain dump with focused top-5 competitor comparison:
- Tel Aviv University: mentioned in X% of queries
- Hebrew University: mentioned in Y% of queries
- Technion: mentioned in Z% of queries
- Bar-Ilan University: mentioned in W% of queries
- Reichman University: mentioned in V% of queries
- **Ono: mentioned in 7.7%** (highlighted, shown as growth opportunity)

Bar chart. Color-coded. Ono in brand color, competitors in grey.

### R6: Category-Level Breakdown

**Priority: MEDIUM**

Break down brand mention rate by prompt category:
| Category | Queries | Brand Mentioned | Rate |
|----------|---------|-----------------|------|
| category (academic programs) | 10 | 1 | 10% |
| problem (immigration/olim) | 8 | 1 | 12.5% |
| use_case (career/job) | 6 | 0 | 0% |
| comparison | 1 | 0 | 0% |
| opinion | 1 | 0 | 0% |

Shows client exactly which content themes need work.

### R7: Before/After Delta (Hero Metric)

**Priority: HIGH**

Large, prominent delta display at top of report:
- "Week 1: 7.7% → Projected Month 6: 38% = +30pp growth"
- Show as hero metric with arrow indicator
- In live report: actual delta between first and latest batch

### R8: `category` Field on GeoPrompt

**Priority: HIGH (system prerequisite)**

GeoPrompt already has `category` field (confirmed in DB). Ensure it's:
- Populated on all prompts (already done for Ono)
- Exposed in admin UI (prompt creation/edit form)
- Used for grouping in visibility report API

### R9: Visibility Report API Endpoint

**Priority: HIGH (for live portal)**

New endpoint: `GET /api/clients/{id}/visibility-report`

Returns aggregated data from GeoExecution batches:
```json
{
  "baseline": {"rate": 7.7, "date": "2026-06-29", "queries": 26},
  "latest": {"rate": ..., "date": "...", "queries": ...},
  "delta_pp": ...,
  "by_engine": {"perplexity": 10.0, "anthropic": 0.0, "chatgpt": null},
  "by_category": [...],
  "top_queries": [...],
  "competitors": [...],
  "excerpts": [...],
  "trend_weekly": [...]
}
```

### R10: Demo Page Polish

**Priority: MEDIUM**

- Favicon (done ✅)
- `<meta name="robots" content="noindex, nofollow">` (done ✅)
- RAMP logo/wordmark in header
- "Prepared for [Client Name]" personalization
- Footer: "Data from RAMP AI Search Monitoring · Updated [date]"
- Print-friendly CSS (@media print)

---

## Out of Scope (Deferred)

- LLM-generated recommendations per category (have Strategy Document for this)
- Manual event annotations on timeline (Блок 6 from brief)
- PDF export (use browser print for now)
- Real-time refresh (batches run Tue+Fri, report updates accordingly)

---

## Success Criteria

1. Tzvi can show demo report on a call and prospect says "this looks real" (not "this is fake data")
2. Client portal shows actual GEO data in structured, understandable format
3. Before/After delta visible within 2 weeks of monitoring start
4. Report loads in <2s (no heavy computation on page load — pre-aggregated)

---

## Competitive Differentiation vs ReddGrow

| Aspect | ReddGrow | RAMP |
|--------|----------|------|
| Data freshness | One-time snapshot | Continuous (Tue+Fri) |
| Engines | 4 engines, equal weight | 3 engines with realistic per-engine analysis |
| Competitor context | 242 domains dumped | Top-5 focused comparison |
| Actionable | Zero recommendations | Category gaps + query-level hit/miss |
| Proof of execution | None (monitoring only) | Shows OUR Reddit posts in citations |
| History | None | 12-week trend with weekly data points |
| Personalization | Generic template | Client name, real prompts, real competitors |
