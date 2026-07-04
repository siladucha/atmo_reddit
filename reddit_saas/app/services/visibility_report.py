"""AI Visibility Report data service.

Collects GEO batch data and computes per-engine metrics, category breakdowns,
competitor share-of-voice, query hit/miss maps, and response excerpts.
Used by both admin GEO page and client portal visibility page.
"""

import math
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.geo_execution import GeoExecutionBatch, GeoQueryResult
from app.models.geo_competitor import GeoCompetitor
from app.models.geo_prompt import GeoPrompt
from app.logging_config import get_logger

logger = get_logger(__name__)


# S-curve projection parameters (from steering doc)
S_CURVE_CEILING = 40.0
S_CURVE_MIDPOINT = 12  # weeks
S_CURVE_STEEPNESS = 0.4
ENGINE_MULTIPLIERS = {
    "perplexity": 1.4,
    "openai": 1.0,
    "anthropic": 0.65,
}


def _s_curve(week: float, baseline: float, ceiling: float, midpoint: float, steepness: float) -> float:
    """Logistic S-curve projection."""
    return baseline + (ceiling - baseline) / (1 + math.exp(-steepness * (week - midpoint)))


def compute_visibility_report(db: Session, client_id, *, include_excerpts: bool = True) -> dict[str, Any]:
    """Compute full visibility report data for a client.

    Returns dict with:
      - summary: overall brand rate, delta, batch info
      - engines: per-engine measured rates
      - projected: per-engine 6-month projections
      - trend: weekly data points for chart (measured + projected)
      - competitors: share-of-voice ranking
      - queries: per-query hit/miss map
      - categories: per-category breakdown
      - excerpts: actual AI response quotes where brand mentioned
    """
    from uuid import UUID
    client_id_val = client_id if isinstance(client_id, UUID) else UUID(str(client_id))

    # --- Get all completed batches ---
    all_batches = (
        db.query(GeoExecutionBatch)
        .filter(
            GeoExecutionBatch.client_id == client_id_val,
            GeoExecutionBatch.status.in_(["completed", "partial"]),
        )
        .order_by(GeoExecutionBatch.started_at.asc())
        .all()
    )

    if not all_batches:
        return _empty_report()

    latest_batch = all_batches[-1]
    baseline_batch = next((b for b in all_batches if b.is_baseline), all_batches[0])

    # --- Per-engine rates from LATEST batch ---
    engine_data = _compute_engine_rates(db, latest_batch.id)

    # Overall rate
    total_runs = sum(e["total_runs"] for e in engine_data.values())
    total_brand = sum(e["brand_appearances"] for e in engine_data.values())
    latest_brand_rate = round(total_brand / total_runs * 100, 1) if total_runs > 0 else 0.0

    # Baseline rate
    baseline_engine_data = _compute_engine_rates(db, baseline_batch.id)
    baseline_total_runs = sum(e["total_runs"] for e in baseline_engine_data.values())
    baseline_total_brand = sum(e["brand_appearances"] for e in baseline_engine_data.values())
    baseline_brand_rate = round(baseline_total_brand / baseline_total_runs * 100, 1) if baseline_total_runs > 0 else 0.0

    # --- Trend history (per-batch brand rates) ---
    trend_history = []
    for batch in all_batches:
        batch_engines = _compute_engine_rates(db, batch.id)
        tr = sum(e["total_runs"] for e in batch_engines.values())
        tb = sum(e["brand_appearances"] for e in batch_engines.values())
        rate = round(tb / tr * 100, 1) if tr > 0 else 0.0

        # Per-engine rates for this batch
        per_engine = {}
        for eng_name, eng_vals in batch_engines.items():
            eng_rate = round(eng_vals["brand_appearances"] / eng_vals["total_runs"] * 100, 1) if eng_vals["total_runs"] > 0 else 0.0
            per_engine[eng_name] = eng_rate

        trend_history.append({
            "date": batch.started_at.strftime("%m/%d"),
            "date_full": batch.started_at.strftime("%Y-%m-%d"),
            "rate": rate,
            "per_engine": per_engine,
            "is_baseline": batch.is_baseline,
        })

    # --- Projections (S-curve, 24 weeks) ---
    projected = {}
    for engine_name, eng_vals in engine_data.items():
        eng_rate = round(eng_vals["brand_appearances"] / eng_vals["total_runs"] * 100, 1) if eng_vals["total_runs"] > 0 else 0.0
        multiplier = ENGINE_MULTIPLIERS.get(engine_name, 1.0)
        proj_6mo = _s_curve(24, eng_rate, S_CURVE_CEILING * multiplier, S_CURVE_MIDPOINT, S_CURVE_STEEPNESS)
        projected[engine_name] = round(proj_6mo, 1)

    # --- Generate 24-week trend chart data ---
    # Use measured data points where available, project the rest
    weeks_elapsed = len(all_batches)  # approximate
    trend_chart = _build_trend_chart(engine_data, weeks_elapsed)

    # --- Competitor share of voice ---
    competitor_sov = _compute_competitor_sov(db, client_id_val, latest_batch.id)

    # --- Query hit/miss map ---
    query_map = _compute_query_map(db, client_id_val, latest_batch.id)

    # --- Category breakdown ---
    categories = _compute_category_breakdown(db, client_id_val, latest_batch.id)

    # --- Excerpts ---
    excerpts = []
    if include_excerpts:
        excerpts = _get_brand_excerpts(db, client_id_val, limit=5)

    # --- Engines summary for cards ---
    engines_summary = {}
    for eng_name, eng_vals in engine_data.items():
        eng_rate = round(eng_vals["brand_appearances"] / eng_vals["total_runs"] * 100, 1) if eng_vals["total_runs"] > 0 else 0.0
        engines_summary[eng_name] = {
            "rate": eng_rate,
            "queries_checked": eng_vals["total_runs"],
            "brand_mentions": eng_vals["brand_appearances"],
            "status": "active" if eng_vals["total_runs"] > 0 else "pending",
        }

    return {
        "has_data": True,
        "summary": {
            "latest_brand_rate": latest_brand_rate,
            "baseline_brand_rate": baseline_brand_rate,
            "brand_rate_delta": round(latest_brand_rate - baseline_brand_rate, 1),
            "latest_batch_date": latest_batch.started_at.strftime("%b %d, %Y"),
            "latest_batch_time": latest_batch.started_at.strftime("%H:%M"),
            "baseline_date": baseline_batch.started_at.strftime("%b %d, %Y") if baseline_batch else None,
            "total_batches": len(all_batches),
            "total_queries_latest": latest_batch.successful_queries,
        },
        "engines": engines_summary,
        "projected": projected,
        "trend_history": trend_history,
        "trend_chart": trend_chart,
        "competitors": competitor_sov,
        "queries": query_map,
        "categories": categories,
        "excerpts": excerpts,
    }


def _empty_report() -> dict[str, Any]:
    """Return empty report structure when no data available."""
    return {
        "has_data": False,
        "summary": {
            "latest_brand_rate": 0,
            "baseline_brand_rate": 0,
            "brand_rate_delta": 0,
            "latest_batch_date": None,
            "latest_batch_time": None,
            "baseline_date": None,
            "total_batches": 0,
            "total_queries_latest": 0,
        },
        "engines": {},
        "projected": {},
        "trend_history": [],
        "trend_chart": {"weeks": [], "engines": {}},
        "competitors": [],
        "queries": [],
        "categories": [],
        "excerpts": [],
    }


def _compute_engine_rates(db: Session, batch_id) -> dict[str, dict]:
    """Compute brand mention rates per engine for a batch."""
    # Get distinct providers in this batch
    providers = (
        db.query(GeoQueryResult.provider)
        .filter(
            GeoQueryResult.execution_batch_id == batch_id,
            GeoQueryResult.status == "success",
        )
        .distinct()
        .all()
    )

    engine_data = {}
    for (provider,) in providers:
        total = (
            db.query(func.count(GeoQueryResult.id))
            .filter(
                GeoQueryResult.execution_batch_id == batch_id,
                GeoQueryResult.status == "success",
                GeoQueryResult.provider == provider,
            )
            .scalar()
        ) or 0

        brand_count = (
            db.query(func.count(GeoQueryResult.id))
            .filter(
                GeoQueryResult.execution_batch_id == batch_id,
                GeoQueryResult.status == "success",
                GeoQueryResult.provider == provider,
                GeoQueryResult.brand_mentioned.is_(True),
            )
            .scalar()
        ) or 0

        engine_data[provider] = {
            "total_runs": total,
            "brand_appearances": brand_count,
        }

    return engine_data


def _build_trend_chart(engine_data: dict, weeks_elapsed: int) -> dict:
    """Build 24-week trend chart data with S-curve projections."""
    weeks = [f"W{i+1}" for i in range(24)]
    engines_chart = {}

    for eng_name, eng_vals in engine_data.items():
        eng_rate = round(eng_vals["brand_appearances"] / eng_vals["total_runs"] * 100, 1) if eng_vals["total_runs"] > 0 else 0.0
        multiplier = ENGINE_MULTIPLIERS.get(eng_name, 1.0)

        data_points = []
        for i in range(24):
            val = _s_curve(i, eng_rate, S_CURVE_CEILING * multiplier, S_CURVE_MIDPOINT, S_CURVE_STEEPNESS)
            data_points.append(round(val, 1))

        engines_chart[eng_name] = {
            "data": data_points,
            "measured_weeks": min(weeks_elapsed, 24),
        }

    return {
        "weeks": weeks,
        "engines": engines_chart,
    }


def _compute_competitor_sov(db: Session, client_id, batch_id) -> list[dict]:
    """Compute competitor share-of-voice from latest batch."""
    # Get all successful results from latest batch
    results = (
        db.query(GeoQueryResult)
        .filter(
            GeoQueryResult.execution_batch_id == batch_id,
            GeoQueryResult.status == "success",
        )
        .all()
    )

    if not results:
        return []

    total_results = len(results)

    # Count competitor mentions
    competitor_counts: dict[str, int] = {}
    for r in results:
        if r.competitors_mentioned and isinstance(r.competitors_mentioned, dict):
            for comp_name in r.competitors_mentioned.keys():
                competitor_counts[comp_name] = competitor_counts.get(comp_name, 0) + 1

    # Sort by count descending, take top 10
    sorted_comps = sorted(competitor_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Get competitor domains from DB
    competitors_db = (
        db.query(GeoCompetitor)
        .filter(GeoCompetitor.client_id == client_id, GeoCompetitor.is_active.is_(True))
        .all()
    )
    domain_map = {c.competitor_name.lower(): c.competitor_domain for c in competitors_db}

    sov_list = []
    for comp_name, count in sorted_comps:
        rate = round(count / total_results * 100, 1)
        sov_list.append({
            "name": comp_name,
            "domain": domain_map.get(comp_name.lower(), ""),
            "appearance_rate": rate,
            "mentions": count,
        })

    return sov_list


def _compute_query_map(db: Session, client_id, batch_id) -> list[dict]:
    """Compute per-query brand mention status across engines."""
    # Get prompts
    prompts = (
        db.query(GeoPrompt)
        .filter(GeoPrompt.client_id == client_id, GeoPrompt.is_active.is_(True))
        .all()
    )
    prompt_map = {p.id: p for p in prompts}

    # Get results grouped by prompt and provider
    results = (
        db.query(GeoQueryResult)
        .filter(
            GeoQueryResult.execution_batch_id == batch_id,
            GeoQueryResult.status == "success",
        )
        .all()
    )

    # Build map: prompt_id -> { provider -> [brand_mentioned booleans] }
    query_data: dict[str, dict[str, list[bool]]] = {}
    for r in results:
        pid = str(r.prompt_id)
        if pid not in query_data:
            query_data[pid] = {}
        if r.provider not in query_data[pid]:
            query_data[pid][r.provider] = []
        query_data[pid][r.provider].append(r.brand_mentioned)

    # Build output
    query_map = []
    for pid, providers in query_data.items():
        from uuid import UUID
        prompt = prompt_map.get(UUID(pid))
        if not prompt:
            continue

        engines_status = {}
        for provider, mentions in providers.items():
            # If ANY run mentioned brand, mark as hit
            engines_status[provider] = any(mentions)

        query_map.append({
            "prompt_text": prompt.prompt_text,
            "category": prompt.category or "general",
            "engines": engines_status,
        })

    # Sort: hits first, then alphabetical
    query_map.sort(key=lambda x: (-sum(x["engines"].values()), x["prompt_text"]))
    return query_map


def _compute_category_breakdown(db: Session, client_id, batch_id) -> list[dict]:
    """Compute brand mention rates grouped by prompt category."""
    # Get all prompts with their categories
    prompts = (
        db.query(GeoPrompt)
        .filter(GeoPrompt.client_id == client_id, GeoPrompt.is_active.is_(True))
        .all()
    )

    # Get results from batch
    results = (
        db.query(GeoQueryResult)
        .filter(
            GeoQueryResult.execution_batch_id == batch_id,
            GeoQueryResult.status == "success",
        )
        .all()
    )

    # Group results by category
    prompt_category = {p.id: (p.category or "general") for p in prompts}
    cat_stats: dict[str, dict] = {}  # category -> {total, brand_hits}

    for r in results:
        cat = prompt_category.get(r.prompt_id, "general")
        if cat not in cat_stats:
            cat_stats[cat] = {"total": 0, "brand_hits": 0, "prompts": set()}
        cat_stats[cat]["total"] += 1
        cat_stats[cat]["prompts"].add(r.prompt_id)
        if r.brand_mentioned:
            cat_stats[cat]["brand_hits"] += 1

    # Build output
    categories = []
    for cat, stats in cat_stats.items():
        rate = round(stats["brand_hits"] / stats["total"] * 100, 1) if stats["total"] > 0 else 0.0
        categories.append({
            "category": cat,
            "total_queries": stats["total"],
            "brand_hits": stats["brand_hits"],
            "unique_prompts": len(stats["prompts"]),
            "rate": rate,
        })

    # Sort by rate descending
    categories.sort(key=lambda x: -x["rate"])
    return categories


def _get_brand_excerpts(db: Session, client_id, limit: int = 5) -> list[dict]:
    """Get actual AI response excerpts where brand was mentioned."""
    results = (
        db.query(GeoQueryResult)
        .join(GeoPrompt, GeoQueryResult.prompt_id == GeoPrompt.id)
        .filter(
            GeoQueryResult.client_id == client_id,
            GeoQueryResult.brand_mentioned.is_(True),
            GeoQueryResult.status == "success",
            GeoQueryResult.response_text.isnot(None),
        )
        .order_by(GeoQueryResult.executed_at.desc())
        .limit(limit)
        .all()
    )

    excerpts = []
    for r in results:
        # Get the prompt text
        prompt = db.query(GeoPrompt).filter(GeoPrompt.id == r.prompt_id).first()

        # Truncate response to first meaningful paragraph (max 300 chars)
        text = r.response_text or ""
        if len(text) > 300:
            # Find sentence end near 300 chars
            cut = text[:300].rfind(".")
            if cut > 100:
                text = text[:cut + 1]
            else:
                text = text[:300] + "..."

        excerpts.append({
            "provider": r.provider,
            "date": r.executed_at.strftime("%b %d, %Y"),
            "text": text,
            "query": prompt.prompt_text if prompt else "Unknown query",
        })

    return excerpts
