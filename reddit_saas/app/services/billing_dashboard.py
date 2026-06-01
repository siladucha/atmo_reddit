"""Billing Dashboard Service — comprehensive cost & usage analytics.

Aggregates AI costs, posting quotas, client plan usage, and infrastructure
estimates into a single view for the /admin/billing page.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, case, and_
from sqlalchemy.orm import Session

from app.models.ai_usage import AIUsageLog
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.epg_slot import EPGSlot
from app.models.posting_event import PostingEvent


# ---------------------------------------------------------------------------
# Plan definitions (from business brief)
# ---------------------------------------------------------------------------

PLAN_LIMITS: dict[str, dict[str, Any]] = {
    "seed": {
        "label": "Seed",
        "price_usd": 149,
        "max_avatars": 1,
        "max_comments_month": 30,
        "max_subreddits": 1,
    },
    "starter": {
        "label": "Starter",
        "price_usd": 399,
        "max_avatars": 3,
        "max_comments_month": 60,
        "max_subreddits": 2,
    },
    "growth": {
        "label": "Growth",
        "price_usd": 799,
        "max_avatars": 7,
        "max_comments_month": 150,
        "max_subreddits": 5,
    },
    "scale": {
        "label": "Scale",
        "price_usd": 1499,
        "max_avatars": 15,
        "max_comments_month": 400,
        "max_subreddits": 999,
    },
    "agency": {
        "label": "Agency",
        "price_usd": 2000,
        "max_avatars": 999,
        "max_comments_month": 9999,
        "max_subreddits": 999,
    },
}


# ---------------------------------------------------------------------------
# Infrastructure cost estimates (from steering doc)
# ---------------------------------------------------------------------------

INFRA_COSTS: dict[str, dict[str, Any]] = {
    "digitalocean_droplet": {
        "label": "DigitalOcean Droplet (2 vCPU / 4 GB)",
        "monthly_usd": 23.0,
        "category": "compute",
    },
    "domain_ssl": {
        "label": "Domain + SSL (gorampit.com)",
        "monthly_usd": 1.5,
        "category": "network",
    },
    "redis_docker": {
        "label": "Redis (Docker on Droplet)",
        "monthly_usd": 0.0,
        "category": "cache",
    },
    "postgres_docker": {
        "label": "PostgreSQL (Docker on Droplet)",
        "monthly_usd": 0.0,
        "category": "database",
    },
    "backups": {
        "label": "DO Weekly Backups",
        "monthly_usd": 4.6,
        "category": "storage",
    },
}


def get_infra_summary() -> dict[str, Any]:
    """Return infrastructure cost summary."""
    total = sum(item["monthly_usd"] for item in INFRA_COSTS.values())
    return {
        "line_items": list(INFRA_COSTS.values()),
        "total_monthly": total,
    }


# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------

def get_period_range(month: str | None = None) -> tuple[datetime, datetime, int, str]:
    """Parse month string (YYYY-MM) into (start, end, days_elapsed, label).

    If month is None or 'current', uses the current calendar month.
    Returns timezone-aware UTC datetimes.
    """
    now = datetime.now(timezone.utc)

    if not month or month == "current":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now
        days_elapsed = max((now - start).days, 1)
        label = now.strftime("%B %Y")
    else:
        try:
            year, mon = month.split("-")
            year, mon = int(year), int(mon)
        except (ValueError, AttributeError):
            # Fallback to current month
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end = now
            days_elapsed = max((now - start).days, 1)
            label = now.strftime("%B %Y")
            return start, end, days_elapsed, label

        start = datetime(year, mon, 1, tzinfo=timezone.utc)
        # End of month
        days_in_month = calendar.monthrange(year, mon)[1]
        end = datetime(year, mon, days_in_month, 23, 59, 59, tzinfo=timezone.utc)

        # If it's the current month, end = now
        if start.year == now.year and start.month == now.month:
            end = now
            days_elapsed = max((now - start).days, 1)
        else:
            days_elapsed = days_in_month

        label = start.strftime("%B %Y")

    return start, end, days_elapsed, label


def get_available_months(db: Session) -> list[dict[str, str]]:
    """Return list of months that have AI usage data."""
    first_record = db.query(func.min(AIUsageLog.created_at)).scalar()
    if not first_record:
        now = datetime.now(timezone.utc)
        return [{"value": now.strftime("%Y-%m"), "label": now.strftime("%B %Y")}]

    now = datetime.now(timezone.utc)
    months = []
    current = now.replace(day=1)

    # Go back from current month to first record month
    first_month = first_record.replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)

    while current >= first_month:
        months.append({
            "value": current.strftime("%Y-%m"),
            "label": current.strftime("%B %Y"),
        })
        # Go to previous month
        if current.month == 1:
            current = current.replace(year=current.year - 1, month=12)
        else:
            current = current.replace(month=current.month - 1)

    return months


# ---------------------------------------------------------------------------
# AI Cost Summary
# ---------------------------------------------------------------------------

def get_monthly_ai_summary(db: Session, start: datetime, end: datetime, days_elapsed: int) -> dict[str, Any]:
    """AI cost summary for the given period."""
    row = (
        db.query(
            func.coalesce(func.sum(AIUsageLog.cost_usd), 0).label("total_cost"),
            func.count(AIUsageLog.id).label("total_calls"),
            func.coalesce(func.sum(AIUsageLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(AIUsageLog.output_tokens), 0).label("output_tokens"),
        )
        .filter(AIUsageLog.created_at >= start, AIUsageLog.created_at <= end)
        .one()
    )

    total_cost = float(row.total_cost)
    daily_avg = total_cost / days_elapsed if days_elapsed > 0 else 0
    monthly_projection = daily_avg * 30

    return {
        "total_cost": total_cost,
        "total_calls": row.total_calls,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "daily_avg": daily_avg,
        "monthly_projection": monthly_projection,
        "days_elapsed": days_elapsed,
    }


# ---------------------------------------------------------------------------
# Cost by Client — with plan context
# ---------------------------------------------------------------------------

def get_client_cost_breakdown(db: Session, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Per-client cost breakdown with plan limits and usage."""
    # AI costs per client this period
    cost_rows = (
        db.query(
            Client.id.label("client_id"),
            Client.client_name,
            Client.brand_name,
            Client.plan_type,
            Client.max_avatars,
            Client.is_active,
            func.coalesce(func.sum(AIUsageLog.cost_usd), 0).label("ai_cost"),
            func.count(AIUsageLog.id).label("ai_calls"),
        )
        .outerjoin(
            AIUsageLog,
            and_(
                AIUsageLog.client_id == Client.id,
                AIUsageLog.created_at >= start,
                AIUsageLog.created_at <= end,
            ),
        )
        .group_by(Client.id)
        .order_by(func.coalesce(func.sum(AIUsageLog.cost_usd), 0).desc())
        .all()
    )

    # Comments posted this period per client
    posted_counts = dict(
        db.query(
            CommentDraft.client_id,
            func.count(CommentDraft.id),
        )
        .filter(
            CommentDraft.status == "posted",
            CommentDraft.posted_at >= start,
            CommentDraft.posted_at <= end,
        )
        .group_by(CommentDraft.client_id)
        .all()
    )

    # Active avatars per client
    avatar_counts: dict = {}
    avatars = db.query(Avatar).filter(Avatar.active == True).all()  # noqa: E712
    for av in avatars:
        if av.client_ids:
            for cid in av.client_ids:
                avatar_counts[cid] = avatar_counts.get(cid, 0) + 1

    result = []
    for row in cost_rows:
        plan = PLAN_LIMITS.get(row.plan_type, PLAN_LIMITS["starter"])
        cid_str = str(row.client_id)
        comments_posted = posted_counts.get(row.client_id, 0)
        active_avatars = avatar_counts.get(cid_str, 0)

        result.append({
            "client_id": str(row.client_id),
            "client_name": row.client_name,
            "brand_name": row.brand_name,
            "plan_type": row.plan_type,
            "plan_label": plan["label"],
            "plan_price": plan["price_usd"],
            "is_active": row.is_active,
            "ai_cost": float(row.ai_cost),
            "ai_calls": row.ai_calls,
            # Usage vs limits
            "comments_posted": comments_posted,
            "comments_limit": plan["max_comments_month"],
            "comments_pct": min(100, int(comments_posted / plan["max_comments_month"] * 100)) if plan["max_comments_month"] > 0 else 0,
            "avatars_active": active_avatars,
            "avatars_limit": row.max_avatars,
            "avatars_pct": min(100, int(active_avatars / row.max_avatars * 100)) if row.max_avatars > 0 else 0,
            # Profitability
            "margin": plan["price_usd"] - float(row.ai_cost),
            "margin_pct": int((1 - float(row.ai_cost) / plan["price_usd"]) * 100) if plan["price_usd"] > 0 else 0,
        })

    return result


# ---------------------------------------------------------------------------
# Posting Quotas (today)
# ---------------------------------------------------------------------------

def get_posting_quotas(db: Session) -> dict[str, Any]:
    """Posting quota usage for today across all avatars."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Posts today (successful)
    posts_today = (
        db.query(func.count(PostingEvent.id))
        .filter(
            PostingEvent.posted_at >= today_start,
            PostingEvent.outcome == "success",
        )
        .scalar()
    ) or 0

    # Posts today by avatar
    avatar_posts = (
        db.query(
            Avatar.reddit_username,
            Avatar.warming_phase,
            func.count(PostingEvent.id).label("count"),
        )
        .join(PostingEvent, PostingEvent.avatar_id == Avatar.id)
        .filter(
            PostingEvent.posted_at >= today_start,
            PostingEvent.outcome == "success",
        )
        .group_by(Avatar.id)
        .all()
    )

    # Failed attempts today
    failures_today = (
        db.query(func.count(PostingEvent.id))
        .filter(
            PostingEvent.posted_at >= today_start,
            PostingEvent.outcome == "failure",
        )
        .scalar()
    ) or 0

    # EPG slots status for today
    today_date = now.date()
    slot_stats = (
        db.query(
            EPGSlot.status,
            func.count(EPGSlot.id),
        )
        .filter(EPGSlot.plan_date == today_date)
        .group_by(EPGSlot.status)
        .all()
    )
    slot_breakdown = {status: count for status, count in slot_stats}

    # Avatars with posting enabled
    posting_avatars = (
        db.query(func.count(Avatar.id))
        .filter(Avatar.posting_mode == "auto", Avatar.active == True)  # noqa: E712
        .scalar()
    ) or 0

    return {
        "posts_today": posts_today,
        "failures_today": failures_today,
        "posting_avatars": posting_avatars,
        "epg_slots": {
            "planned": slot_breakdown.get("planned", 0),
            "generated": slot_breakdown.get("generated", 0),
            "approved": slot_breakdown.get("approved", 0),
            "posted": slot_breakdown.get("posted", 0),
            "skipped": slot_breakdown.get("skipped", 0),
            "expired": slot_breakdown.get("expired", 0),
            "total": sum(slot_breakdown.values()),
        },
        "avatar_posts": [
            {
                "username": row.reddit_username,
                "phase": row.warming_phase,
                "posts_today": row.count,
            }
            for row in avatar_posts
        ],
    }


# ---------------------------------------------------------------------------
# Cost Trend (period days)
# ---------------------------------------------------------------------------

def get_cost_trend(db: Session, start: datetime, end: datetime, days: int) -> list[dict[str, Any]]:
    """Daily cost totals for the given period."""
    rows = (
        db.query(
            func.date_trunc("day", AIUsageLog.created_at).label("day"),
            func.coalesce(func.sum(AIUsageLog.cost_usd), 0).label("cost"),
            func.count(AIUsageLog.id).label("calls"),
        )
        .filter(AIUsageLog.created_at >= start, AIUsageLog.created_at <= end)
        .group_by("day")
        .order_by("day")
        .all()
    )

    # Build lookup
    daily_data = {row.day.date(): {"cost": float(row.cost), "calls": row.calls} for row in rows}

    # Fill gaps for all days in range
    result = []
    for i in range(days):
        d = (start + timedelta(days=i)).date()
        if d > end.date():
            break
        entry = daily_data.get(d, {"cost": 0.0, "calls": 0})
        result.append({
            "date": d,
            "date_str": d.strftime("%b %d"),
            "cost": entry["cost"],
            "calls": entry["calls"],
        })

    return result


# ---------------------------------------------------------------------------
# Cost by Model
# ---------------------------------------------------------------------------

def get_model_costs(db: Session, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Cost breakdown by LLM model for the period."""
    rows = (
        db.query(
            AIUsageLog.model,
            func.count(AIUsageLog.id).label("calls"),
            func.coalesce(func.sum(AIUsageLog.cost_usd), 0).label("cost"),
            func.coalesce(func.sum(AIUsageLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(AIUsageLog.output_tokens), 0).label("output_tokens"),
        )
        .filter(AIUsageLog.created_at >= start, AIUsageLog.created_at <= end)
        .group_by(AIUsageLog.model)
        .order_by(func.sum(AIUsageLog.cost_usd).desc())
        .all()
    )

    total_cost = sum(float(r.cost) for r in rows) or 1.0
    return [
        {
            "model": row.model or "unknown",
            "calls": row.calls,
            "cost": float(row.cost),
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            "pct": float(row.cost) / total_cost * 100,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Cost by Operation
# ---------------------------------------------------------------------------

def get_operation_costs(db: Session, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Cost breakdown by pipeline operation for the period."""
    rows = (
        db.query(
            AIUsageLog.operation,
            func.count(AIUsageLog.id).label("calls"),
            func.coalesce(func.sum(AIUsageLog.cost_usd), 0).label("cost"),
        )
        .filter(AIUsageLog.created_at >= start, AIUsageLog.created_at <= end)
        .group_by(AIUsageLog.operation)
        .order_by(func.sum(AIUsageLog.cost_usd).desc())
        .all()
    )

    # Map to friendly names
    op_labels = {
        "scoring": "🔍 Scoring",
        "scoring_batch": "🔍 Scoring (batch)",
        "generation": "✍️ Generation",
        "persona_select": "🎭 Persona Selection",
        "editing": "📝 AI Editor",
        "hobby_comment": "🎨 Hobby Comments",
        "post_topic": "📰 Post Topics",
        "post_brief": "📋 Post Briefs",
        "post_generation": "📝 Post Generation",
        "strategy_generation": "🧠 Strategy",
    }

    total_cost = sum(float(r.cost) for r in rows) or 1.0
    return [
        {
            "operation": row.operation,
            "label": op_labels.get(row.operation, row.operation),
            "calls": row.calls,
            "cost": float(row.cost),
            "pct": float(row.cost) / total_cost * 100,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Revenue vs Cost (P&L summary)
# ---------------------------------------------------------------------------

def get_revenue_vs_cost(db: Session, ai_summary: dict[str, Any]) -> dict[str, Any]:
    """Simple P&L: estimated revenue vs actual costs."""
    # Revenue estimate: sum of plan prices for active clients
    clients = db.query(Client).filter(Client.is_active == True).all()  # noqa: E712
    total_revenue = 0.0
    for c in clients:
        plan = PLAN_LIMITS.get(c.plan_type, PLAN_LIMITS["starter"])
        total_revenue += plan["price_usd"]

    # Costs
    infra = get_infra_summary()
    total_cost = ai_summary["monthly_projection"] + infra["total_monthly"]

    return {
        "revenue_monthly": total_revenue,
        "ai_cost_projected": ai_summary["monthly_projection"],
        "infra_cost": infra["total_monthly"],
        "total_cost": total_cost,
        "profit": total_revenue - total_cost,
        "margin_pct": int((1 - total_cost / total_revenue) * 100) if total_revenue > 0 else 0,
        "active_clients": len(clients),
    }


# ---------------------------------------------------------------------------
# Full Dashboard Data
# ---------------------------------------------------------------------------

def get_billing_dashboard(db: Session, month: str | None = None) -> dict[str, Any]:
    """Aggregate all billing dashboard data in one call.

    Args:
        db: Database session.
        month: Optional month filter as 'YYYY-MM'. None = current month.
    """
    from app.services.settings import get_setting

    budget_str = get_setting(db, "monthly_budget_usd")
    budget = float(budget_str) if budget_str else 100.0

    start, end, days_elapsed, period_label = get_period_range(month)
    ai_summary = get_monthly_ai_summary(db, start, end, days_elapsed)
    budget_pct = (ai_summary["monthly_projection"] / budget * 100) if budget > 0 else 0

    available_months = get_available_months(db)

    return {
        "ai_summary": ai_summary,
        "budget": budget,
        "budget_pct": min(budget_pct, 999),
        "period_label": period_label,
        "selected_month": month or available_months[0]["value"] if available_months else "",
        "available_months": available_months,
        "clients": get_client_cost_breakdown(db, start, end),
        "posting": get_posting_quotas(db),
        "trend": get_cost_trend(db, start, end, days_elapsed),
        "models": get_model_costs(db, start, end),
        "operations": get_operation_costs(db, start, end),
        "infra": get_infra_summary(),
        "pnl": get_revenue_vs_cost(db, ai_summary),
    }
