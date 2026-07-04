# Visibility Intelligence Report — Design

## Architecture Overview

```
GEO Batch (Tue+Fri)
    ↓ writes
geo_query_results (existing)
    ↓ aggregated by
Visibility Report Service (NEW)
    ↓ serves
API endpoint → Portal template (live)
    ↓ also informs
Demo HTML (static, manually updated with real baseline)
```

---

## Component 1: Demo Report (Static HTML)

**File:** `reddit_saas/demo/share-of-voice.html`

**Data source:** Real Ono baseline (hardcoded from Jun 29 batch) + S-curve projection.

**Sections:**
1. Hero: Brand name, baseline rate, projected Month 6 rate, delta arrow
2. Engine cards (3): Perplexity (10%), Claude (0%), ChatGPT (pending)
3. Trend chart (24 weeks): 4 real data points + 20 projected (S-curve with noise)
4. Query examples: 5 actual prompts with ✅/❌ per engine
5. AI Response excerpts: 2 real quotes from Perplexity responses
6. Competitor benchmark: bar chart (top 6 institutions)
7. Category breakdown: table with rates per category

**Growth model (S-curve with noise):**
```python
def projected_rate(week, baseline=7.7, ceiling=40, midpoint=12, steepness=0.4):
    """Logistic S-curve for visibility growth projection"""
    import random
    raw = baseline + (ceiling - baseline) / (1 + math.exp(-steepness * (week - midpoint)))
    noise = random.uniform(-2.5, 2.5)  # weekly variance
    return round(max(baseline, min(ceiling, raw + noise)), 1)
```

**Per-engine multipliers:**
- Perplexity: 1.4x (Reddit-heavy, fastest growth)
- ChatGPT: 1.0x (baseline)
- Claude: 0.65x (slowest Reddit adoption)

---

## Component 2: Visibility Report Service

**File:** `app/services/visibility_report.py`

**Methods:**
```python
class VisibilityReportService:
    async def get_report(self, db, client_id) -> VisibilityReport:
        """Aggregate all GEO data into structured report"""

    async def get_baseline(self, db, client_id) -> BaselineMetrics:
        """First batch results (earliest execution)"""

    async def get_latest(self, db, client_id) -> LatestMetrics:
        """Most recent batch results"""

    async def get_trend_weekly(self, db, client_id) -> list[WeeklyPoint]:
        """Week-by-week brand mention rate (from batch history)"""

    async def get_by_engine(self, db, client_id) -> dict[str, float]:
        """Brand mention rate per engine"""

    async def get_by_category(self, db, client_id) -> list[CategoryMetrics]:
        """Brand mention rate per prompt category"""

    async def get_top_queries(self, db, client_id, limit=10) -> list[QueryResult]:
        """Prompts with hit/miss per engine"""

    async def get_competitor_share(self, db, client_id, limit=6) -> list[CompetitorShare]:
        """Competitor mention frequency (sorted desc)"""

    async def get_excerpts(self, db, client_id, limit=5) -> list[ResponseExcerpt]:
        """AI response excerpts where brand was mentioned"""
```

**Data models (Pydantic):**
```python
class BaselineMetrics(BaseModel):
    rate: float  # brand mention rate %
    date: date
    total_queries: int
    brand_mentions: int

class WeeklyPoint(BaseModel):
    week_start: date
    rate: float
    queries: int
    mentions: int

class QueryResult(BaseModel):
    prompt_text: str
    category: str
    engines: dict[str, bool]  # {"perplexity": True, "anthropic": False}

class CompetitorShare(BaseModel):
    name: str
    mention_rate: float  # % of queries mentioning this competitor
    mention_count: int

class ResponseExcerpt(BaseModel):
    prompt_text: str
    engine: str
    excerpt: str  # first 200 chars of response where brand appears
    date: date

class CategoryMetrics(BaseModel):
    category: str
    total_queries: int
    brand_mentions: int
    rate: float
```

---

## Component 3: API Endpoint

**Route:** `GET /api/clients/{id}/visibility-report`
**Auth:** require_client_access (RBAC)
**File:** add to `app/routes/admin_geo.py` or new `app/routes/visibility_report.py`

Returns full `VisibilityReport` JSON. Used by portal template (HTMX) and potentially by external integrations.

---

## Component 4: Portal Template Update

**File:** `app/templates/client/visibility.html`

Current state: basic text about "3 engines monitored". Update to:
- Hero metrics section (rate + delta)
- Engine cards (3, color-coded)
- Trend chart (Chart.js, same as demo)
- Query table (HTMX partial, lazy-loaded)
- Excerpt cards (accordion)
- Competitor bar chart

All sections load via HTMX partials from the API endpoint (fast initial page, progressive enhancement).

---

## Data Flow

```
1. GEO batch runs (Tue/Fri 09:30)
   → geo_query_results rows created
   
2. Client opens portal /clients/{id}/visibility
   → page loads with skeleton
   → HTMX requests /api/clients/{id}/visibility-report
   → service aggregates from geo_query_results
   → JSON returned
   → Chart.js renders

3. Admin opens /admin/geo (existing)
   → same data, different view (operational, not client-facing)
```

---

## Migration Requirements

None — `geo_prompts.category` already populated. No schema changes needed.

---

## Demo HTML Update Plan

1. Replace fake round numbers with real Ono baseline (7.7%)
2. Replace linear trend with S-curve projection (24 weeks, noise)
3. Add "AI Response Examples" section with real excerpts
4. Add "Query Examples" section with real prompts + ✅/❌
5. Update competitor chart with real names (TAU, HUJI, Technion, Bar-Ilan, BGU, Reichman)
6. Add hero delta metric at top
7. Update "Last batch" date to actual date
8. Keep `noindex` + favicon

---

## File Changes Summary

| File | Action | Priority |
|------|--------|----------|
| `reddit_saas/demo/share-of-voice.html` | Rewrite with real data | HIGH |
| `app/services/visibility_report.py` | NEW — aggregation service | HIGH |
| `app/routes/visibility_report.py` | NEW — API endpoint | HIGH |
| `app/templates/client/visibility.html` | Update — add report sections | MEDIUM |
| `app/templates/partials/visibility_*.html` | NEW — HTMX partials | MEDIUM |
