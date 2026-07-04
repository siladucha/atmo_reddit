# Visibility Intelligence Report — Steering

## What This Is

A client-facing and sales-facing presentation of GEO/AEO monitoring data. Transforms raw batch results (brand_mentioned true/false per query) into an actionable, visual intelligence report showing AI search visibility status, trends, and competitive position.

## Two Artifacts

1. **Demo Report** (`/demo/share-of-voice.html`) — static HTML for sales calls. Real baseline + projected growth. `noindex`. No auth.
2. **Live Report** (portal `/clients/{id}/visibility`) — dynamic, real-time data from GEO batches. Auth required. HTMX lazy-load.

## Real Baseline Data (Ono, Jun 29 2026)

From production GEO batches (3 executions, best batch: 26 successful queries):

| Metric | Value |
|--------|-------|
| Brand mention rate (overall) | 7.7% (2/26) |
| Perplexity mention rate | 10% (2/20) |
| Claude mention rate | 0% (0/6) |
| ChatGPT mention rate | N/A (not yet enabled) |
| Top competitors in answers | Tel Aviv Uni (90%+), Hebrew Uni (85%+), Technion (60%), Bar-Ilan (55%), BGU (50%), Reichman (45%) |
| Categories with brand mention | "category" (1/10), "problem" (1/8) |
| Categories without brand mention | "use_case" (0/6), "comparison" (0/1), "opinion" (0/1) |

## Growth Projection Model

S-curve (logistic) with per-engine multipliers:

```
rate(week) = baseline + (ceiling - baseline) / (1 + exp(-steepness * (week - midpoint)))
```

Parameters:
- baseline = 7.7 (real)
- ceiling = 40 (realistic max after 6 months of active Reddit content)
- midpoint = 12 weeks (inflection point)
- steepness = 0.4
- Per-engine: Perplexity ×1.4, ChatGPT ×1.0, Claude ×0.65
- Weekly noise: ±2.5pp (uniform random)

Rationale: Perplexity cites Reddit most aggressively. ChatGPT Search uses web grounding but less Reddit-specific. Claude web search is newest and least Reddit-dependent.

## Competitive Differentiation (vs ReddGrow)

Key points for sales positioning:

| Their weakness | Our strength |
|---------------|-------------|
| One-time snapshot, no history | Continuous monitoring Tue+Fri, 12-week trend |
| 242 domains dumped, no context | Top-5 focused competitors with % |
| No excerpts ("5 of 48 mentioned") | Actual AI response quotes shown |
| Equal engine weighting (25% each) | Per-engine analysis with realistic growth rates |
| Zero actionable recommendations | Category gaps + query-level hit/miss map |
| No execution layer | Reddit content → LLM citation → visibility growth (proof of ROI) |
| Generic lead magnet (one-time free) | Part of continuous paid service |

## Key Principles

1. **Real data first.** Never show round fake numbers. Use actual batch results as baseline, project realistically from there.
2. **Show the gap.** Most powerful sales moment: "Your competitor is at 85%, you're at 7.7%. Here's the plan to close that gap."
3. **Excerpts > numbers.** Seeing "Ono offers programs for English speakers" in a ChatGPT answer is worth more than "34% visibility score".
4. **Delta > absolute.** "+30pp in 6 months" sells better than "38% by month 6". Show the journey.
5. **Per-engine matters.** Clients care about ChatGPT more than Perplexity. Show each engine separately.
6. **Category breakdown = action plan.** "You're visible for academic programs but invisible for career outcomes" → immediate content direction.

## Spec Location

`.kiro/specs/visibility-intelligence-report/` (requirements.md, design.md, tasks.md)

## Forecast & Reporting Layer (July 2, 2026 → Updated July 4, 2026)

The visibility report has been formalized into a 5-layer truth-separated architecture. **Status: 85% implemented.**

| Layer | Purpose | Label | Status |
|-------|---------|-------|--------|
| 1 — Observed Reality | Validated measurements from GEO batches + Reddit metrics | 📍 | ✅ `observed_reality.py` |
| 2 — Execution Intent | Planned actions (EPG, drafts, schedule) | 📋 | ✅ `intent_snapshot.py` |
| 3 — Forecasting | S-curve projection with scenarios + risk discount | 📈 | ✅ `visibility_forecaster.py` |
| 4 — Report Composition | Structured JSONB combining all layers with provenance | — | ✅ `report_composer.py` |
| 5 — Business Impact | Category rank, gap-to-leader, ROI framing | 💰 | ✅ `business_impact.py` |

**Additional services:** `platform_risk.py` (multi-factor risk assessment), `accuracy_tracker.py` (predicted vs actual).

**Client-facing page:** `/clients/{id}/visibility` — LIVE with hero metric, per-engine cards, trend chart (solid/dashed), competitor bars, category breakdown, AI excerpts, high-intent participation.

**Spec:** `.kiro/specs/forecast-reporting-layer/` (requirements.md, design.md, tasks.md)

**Key invariant:** Observed ≠ Projected. These are NEVER conflated in any client communication.

**Remaining:** Auto-generation Celery task hookup for `ClientIntelligenceReport`, admin accuracy review UI.

## Related Systems

- `app/services/geo_query_runner.py` — runs the batches
- `app/services/geo_providers.py` — multi-provider abstraction
- `app/services/geo_brand_detection.py` — brand mention detection
- `app/services/visibility_report.py` — computes full visibility data for client portal
- `app/services/forecast/observed_reality.py` — Layer 1 collector (GEO + Reddit + execution metrics)
- `app/services/forecast/visibility_forecaster.py` — Layer 3 S-curve engine (3 scenarios, per-engine)
- `app/services/forecast/report_composer.py` — Layer 4 full report assembly (5-layer JSONB)
- `app/services/forecast/platform_risk.py` — risk assessment (discount factor for ceiling)
- `app/services/forecast/business_impact.py` — Layer 5 ROI calculator
- `app/services/forecast/accuracy_tracker.py` — predicted vs actual logging
- `app/routes/admin_geo.py` — admin batch management
- `app/routes/intelligence_report.py` — client-facing weekly report view
- `app/routes/admin_intelligence_report.py` — admin report management
- `app/templates/client/visibility.html` — rich client visibility dashboard (Chart.js, per-engine, competitors, excerpts)
- `app/models/geo_prompt.py` — GeoPrompt (has `category` field)
- `app/models/geo_execution.py` — GeoQueryResult (has response_text, brand_mentioned, competitors_mentioned)
- `app/models/intelligence_report.py` — ClientIntelligenceReport (5-layer JSONB), IntelligenceReport (ops)
- `app/models/observed_snapshot.py` — ObservedSnapshot (immutable metric collection)
- `app/models/forecast_accuracy.py` — ForecastAccuracyLog (predicted vs actual tracking)
