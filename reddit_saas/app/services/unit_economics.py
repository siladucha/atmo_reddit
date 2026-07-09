"""Unit Economics Service — computes $/client, $/avatar, $/draft metrics.

Used by AI Costs dashboard for business-friendly cost visibility.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, cast, Date
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.ai_usage import AIUsageLog
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft

logger = get_logger(__name__)


def get_unit_economics(db: Session) -> dict:
    """Compute trailing 30-day unit economics.

    Returns:
        {
            "cost_per_client_month": float | None,
            "cost_per_avatar_month": float | None,
            "cost_per_draft": float | None,
            "total_cost_30d": float,
            "active_clients": int,
            "active_avatars": int,
            "total_drafts_30d": int,
            "period_start": str (ISO date),
            "period_end": str (ISO date),
        }
    """
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=30)

    # Total AI cost in trailing 30 days
    total_cost = float(
        db.query(func.coalesce(func.sum(AIUsageLog.cost_usd), 0))
        .filter(AIUsageLog.created_at >= period_start)
        .scalar()
    )

    # Active clients
    active_clients = (
        db.query(func.count(Client.id))
        .filter(Client.is_active == True)
        .scalar() or 0
    )

    # Active avatars (not frozen)
    active_avatars = (
        db.query(func.count(Avatar.id))
        .filter(Avatar.is_frozen == False)
        .scalar() or 0
    )

    # Total drafts generated in 30 days
    total_drafts = (
        db.query(func.count(CommentDraft.id))
        .filter(CommentDraft.created_at >= period_start)
        .scalar() or 0
    )

    return {
        "cost_per_client_month": round(total_cost / active_clients, 4) if active_clients else None,
        "cost_per_avatar_month": round(total_cost / active_avatars, 4) if active_avatars else None,
        "cost_per_draft": round(total_cost / total_drafts, 4) if total_drafts else None,
        "total_cost_30d": round(total_cost, 2),
        "active_clients": active_clients,
        "active_avatars": active_avatars,
        "total_drafts_30d": total_drafts,
        "period_start": period_start.strftime("%Y-%m-%d"),
        "period_end": now.strftime("%Y-%m-%d"),
    }


def get_provider_budget_status(db: Session) -> list[dict]:
    """Compute current month spend vs budget per provider.

    Returns list of dicts with: provider, spent_usd, budget_usd,
    percent_used, projected_month_end, status, days_elapsed.
    """
    import calendar
    from app.services.settings import get_setting_float

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    days_elapsed = (now - month_start).days + 1  # include today
    days_in_month = calendar.monthrange(now.year, now.month)[1]

    # Provider model patterns for grouping
    providers = [
        {
            "name": "Anthropic",
            "pattern": "anthropic/%",
            "budget_key": "provider_budget_anthropic_usd",
            "default_budget": 50.0,
        },
        {
            "name": "Perplexity",
            "pattern": "perplexity/%",
            "budget_key": "provider_budget_perplexity_usd",
            "default_budget": 20.0,
        },
        {
            "name": "Gemini",
            "pattern": "gemini/%",
            "budget_key": "provider_budget_gemini_usd",
            "default_budget": 300.0,
        },
    ]

    results = []
    for prov in providers:
        budget_usd = get_setting_float(db, prov["budget_key"], prov["default_budget"])

        # Sum cost for this provider this month
        spent = float(
            db.query(func.coalesce(func.sum(AIUsageLog.cost_usd), 0))
            .filter(
                AIUsageLog.created_at >= month_start,
                AIUsageLog.model.like(prov["pattern"]),
            )
            .scalar()
        )

        percent_used = (spent / budget_usd * 100) if budget_usd > 0 else 0

        # Project month-end spend
        if days_elapsed >= 3:
            projected_month_end = (spent / days_elapsed) * days_in_month
        else:
            projected_month_end = spent  # too early to project

        # Determine status
        projected_pct = (projected_month_end / budget_usd * 100) if budget_usd > 0 else 0
        if days_elapsed < 3:
            status = "normal"  # too early for thresholds
        elif projected_pct > 90:
            status = "red"
        elif projected_pct > 70:
            status = "amber"
        else:
            status = "normal"

        results.append({
            "provider": prov["name"],
            "spent_usd": round(spent, 2),
            "budget_usd": budget_usd,
            "percent_used": round(percent_used, 1),
            "projected_month_end": round(projected_month_end, 2),
            "status": status,
            "days_elapsed": days_elapsed,
        })

    return results


def get_client_forecast(
    db: Session,
    target_clients: list[int] | None = None,
) -> list[dict]:
    """Project monthly cost at N clients using trailing cost_per_client.

    Returns list of: {"clients": N, "projected_monthly": float}
    """
    if target_clients is None:
        target_clients = [5, 10, 25, 50]

    economics = get_unit_economics(db)
    cost_per_client = economics["cost_per_client_month"]

    if cost_per_client is None:
        return [{"clients": n, "projected_monthly": None} for n in target_clients]

    return [
        {"clients": n, "projected_monthly": round(cost_per_client * n, 2)}
        for n in target_clients
    ]


def get_daily_burn_data(db: Session, days: int = 30) -> list[dict]:
    """Daily cost breakdown by operation type for burn chart.

    Returns list of dicts with date + cost per operation category + has_geo flag.
    """
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=days)

    # Map operations to display categories
    CATEGORY_MAP = {
        "scoring": "scoring",
        "scoring_batch": "scoring",
        "generation": "generation",
        "editing": "editing",
        "persona_select": "persona",
        "geo_query": "geo",
        "geo_generate_prompts": "geo",
        "geo_suggest_competitors": "geo",
        "hobby_comment_epg": "hobby",
        "hobby_comment_pipeline": "hobby",
        "hobby_comment_workflow": "hobby",
    }

    # Query daily aggregates by operation
    rows = (
        db.query(
            cast(AIUsageLog.created_at, Date).label("date"),
            AIUsageLog.operation,
            func.sum(AIUsageLog.cost_usd).label("cost"),
        )
        .filter(AIUsageLog.created_at >= period_start)
        .group_by(cast(AIUsageLog.created_at, Date), AIUsageLog.operation)
        .all()
    )

    # Aggregate by date → category
    daily: dict[str, dict] = {}
    for row in rows:
        date_str = str(row.date)
        if date_str not in daily:
            daily[date_str] = {
                "date": date_str,
                "scoring": 0.0,
                "generation": 0.0,
                "editing": 0.0,
                "persona": 0.0,
                "geo": 0.0,
                "hobby": 0.0,
                "other": 0.0,
                "has_geo": False,
            }

        category = CATEGORY_MAP.get(row.operation, "other")
        daily[date_str][category] += float(row.cost or 0)
        if category == "geo":
            daily[date_str]["has_geo"] = True

    # Sort by date and return
    return sorted(daily.values(), key=lambda x: x["date"])
