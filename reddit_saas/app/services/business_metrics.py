"""Business metrics service — aggregates revenue, trial, and client health data.

Powers the Partner "Business Cockpit" dashboard with MRR, trial funnel,
client health indicators, and cost-to-revenue ratio.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, func as sa_func
from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.ai_usage import AIUsageLog


# ---------------------------------------------------------------------------
# Plan pricing (list price, no Stripe yet)
# ---------------------------------------------------------------------------

PLAN_PRICES: dict[str, int] = {
    "trial": 0,
    "seed": 149,
    "starter": 399,
    "growth": 799,
    "scale": 1499,
}


# ---------------------------------------------------------------------------
# Client health scoring
# ---------------------------------------------------------------------------

def _compute_client_health(
    client: Client,
    posts_this_week: int,
    frozen_avatars: int,
    total_avatars: int,
    is_trial_expired: bool,
) -> str:
    """Determine client health: green/yellow/red.

    Red: 0 posts in 7 days OR all avatars frozen OR trial expired
    Yellow: <3 posts this week OR some avatars frozen
    Green: everything normal
    """
    if is_trial_expired:
        return "red"
    if total_avatars > 0 and frozen_avatars == total_avatars:
        return "red"
    if posts_this_week == 0 and total_avatars > 0:
        return "red"
    if posts_this_week < 3 or frozen_avatars > 0:
        return "yellow"
    return "green"


# ---------------------------------------------------------------------------
# Main business metrics
# ---------------------------------------------------------------------------

def get_business_metrics(db: Session) -> dict[str, Any]:
    """Aggregate business KPIs for the Partner dashboard."""
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Active paying clients (exclude trial)
    active_paying = (
        db.query(sa_func.count(Client.id))
        .filter(Client.is_active.is_(True), Client.plan_type != "trial")
        .scalar()
    ) or 0

    # Active trials
    active_trials = (
        db.query(sa_func.count(Client.id))
        .filter(Client.is_active.is_(True), Client.plan_type == "trial")
        .scalar()
    ) or 0

    # MRR calculation (active paying clients × plan price)
    mrr_rows = (
        db.query(Client.plan_type, sa_func.count(Client.id))
        .filter(Client.is_active.is_(True), Client.plan_type != "trial")
        .group_by(Client.plan_type)
        .all()
    )
    mrr = sum(PLAN_PRICES.get(plan, 0) * count for plan, count in mrr_rows)

    # AI spend this month
    ai_spend = (
        db.query(sa_func.sum(AIUsageLog.cost_usd))
        .filter(AIUsageLog.created_at >= month_start)
        .scalar()
    ) or 0.0

    # Margin
    margin_pct = round((1 - float(ai_spend) / mrr) * 100) if mrr > 0 else 0

    # Churn this month (clients deactivated)
    # We don't have deactivated_at field yet, so count inactive clients
    # created before this month (rough approximation)
    total_inactive = (
        db.query(sa_func.count(Client.id))
        .filter(Client.is_active.is_(False))
        .scalar()
    ) or 0

    # Pending reviews (partner may review)
    pending_reviews = (
        db.query(sa_func.count(CommentDraft.id))
        .filter(CommentDraft.status == "pending")
        .scalar()
    ) or 0

    return {
        "mrr": mrr,
        "active_paying": active_paying,
        "active_trials": active_trials,
        "total_clients": active_paying + active_trials,
        "ai_spend_month": round(float(ai_spend), 2),
        "margin_pct": max(0, margin_pct),
        "churn_count": 0,  # TODO: track when deactivated_at is added
        "pending_reviews": pending_reviews,
    }


# ---------------------------------------------------------------------------
# Client health table
# ---------------------------------------------------------------------------

def get_client_health_table(db: Session) -> list[dict[str, Any]]:
    """Per-client health table for the Partner dashboard.

    Returns: name, plan, avatars, posted/week, health indicator, trial days left.
    """
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    clients = (
        db.query(Client)
        .filter(Client.is_active.is_(True))
        .order_by(Client.client_name)
        .all()
    )

    if not clients:
        return []

    client_ids = [c.id for c in clients]

    # Batch: posts this week per client
    posts_rows = (
        db.query(CommentDraft.client_id, sa_func.count(CommentDraft.id))
        .filter(
            CommentDraft.client_id.in_(client_ids),
            CommentDraft.status == "posted",
            CommentDraft.posted_at >= week_ago,
        )
        .group_by(CommentDraft.client_id)
        .all()
    )
    posts_map = {row[0]: row[1] for row in posts_rows}

    # Batch: total active avatars per client
    # Avatar.client_ids is JSONB array, need to check each
    avatar_counts: dict[uuid.UUID, int] = {}
    frozen_counts: dict[uuid.UUID, int] = {}
    for cid in client_ids:
        total = (
            db.query(sa_func.count(Avatar.id))
            .filter(Avatar.active.is_(True), Avatar.client_ids.any(str(cid)))
            .scalar()
        ) or 0
        frozen = (
            db.query(sa_func.count(Avatar.id))
            .filter(
                Avatar.active.is_(True),
                Avatar.client_ids.any(str(cid)),
                Avatar.is_frozen.is_(True),
            )
            .scalar()
        ) or 0
        avatar_counts[cid] = total
        frozen_counts[cid] = frozen

    # Batch: generated this week per client
    generated_rows = (
        db.query(CommentDraft.client_id, sa_func.count(CommentDraft.id))
        .filter(
            CommentDraft.client_id.in_(client_ids),
            CommentDraft.created_at >= week_ago,
        )
        .group_by(CommentDraft.client_id)
        .all()
    )
    generated_map = {row[0]: row[1] for row in generated_rows}

    rows: list[dict[str, Any]] = []
    for client in clients:
        posts_week = posts_map.get(client.id, 0)
        total_avatars = avatar_counts.get(client.id, 0)
        frozen = frozen_counts.get(client.id, 0)
        generated_week = generated_map.get(client.id, 0)

        # Trial expiry
        is_trial = client.plan_type == "trial"
        trial_days_left = None
        is_expired = False
        if is_trial and client.created_at:
            days_elapsed = (now - client.created_at).days
            trial_days_left = max(0, 14 - days_elapsed)
            is_expired = days_elapsed > 14

        health = _compute_client_health(
            client, posts_week, frozen, total_avatars, is_expired
        )

        rows.append({
            "client_id": str(client.id),
            "client_name": client.client_name,
            "plan_type": client.plan_type or "starter",
            "plan_price": PLAN_PRICES.get(client.plan_type or "starter", 0),
            "avatars_active": total_avatars,
            "avatars_frozen": frozen,
            "posts_week": posts_week,
            "generated_week": generated_week,
            "health": health,
            "is_trial": is_trial,
            "trial_days_left": trial_days_left,
            "is_expired": is_expired,
        })

    # Sort: red first, then yellow, then green
    health_order = {"red": 0, "yellow": 1, "green": 2}
    rows.sort(key=lambda r: (health_order.get(r["health"], 3), r["client_name"]))

    return rows


# ---------------------------------------------------------------------------
# Trial funnel
# ---------------------------------------------------------------------------

def get_trial_funnel(db: Session) -> dict[str, Any]:
    """Trial conversion funnel metrics.

    Stages: active trials → onboarding complete → first draft generated → converted to paid.
    """
    now = datetime.now(timezone.utc)

    # All trial clients (active or not)
    all_trials = db.query(Client).filter(Client.plan_type == "trial").all()

    active_trials = [c for c in all_trials if c.is_active]
    onboarding_complete = [c for c in active_trials if c.onboarding_completed_at is not None]

    # Trials that got at least one draft
    trial_ids_with_drafts: set[uuid.UUID] = set()
    if active_trials:
        active_trial_ids = [c.id for c in active_trials]
        draft_rows = (
            db.query(CommentDraft.client_id)
            .filter(CommentDraft.client_id.in_(active_trial_ids))
            .distinct()
            .all()
        )
        trial_ids_with_drafts = {row[0] for row in draft_rows}

    # Converted: clients that were trial and are now paying (plan_type changed)
    # We don't track plan history yet, so this is 0 for now
    converted_count = 0

    # Expiring soon (< 3 days)
    expiring_soon = []
    for c in active_trials:
        if c.created_at:
            days_left = 14 - (now - c.created_at).days
            if 0 < days_left <= 3:
                expiring_soon.append({
                    "client_name": c.client_name,
                    "days_left": days_left,
                    "client_id": str(c.id),
                })

    return {
        "active_trials": len(active_trials),
        "onboarding_complete": len(onboarding_complete),
        "first_draft_generated": len(trial_ids_with_drafts),
        "converted": converted_count,
        "expiring_soon": expiring_soon,
    }


# ---------------------------------------------------------------------------
# Attention items (what needs partner action)
# ---------------------------------------------------------------------------

def get_attention_items(db: Session) -> list[dict[str, Any]]:
    """Items that need the partner's attention today.

    Priority ordered: expiring trials → clients with 0 posts → pending reviews → frozen avatars.
    """
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    items: list[dict[str, Any]] = []

    # 1. Expiring trials (< 3 days left)
    trial_clients = (
        db.query(Client)
        .filter(Client.is_active.is_(True), Client.plan_type == "trial")
        .all()
    )
    for c in trial_clients:
        if c.created_at:
            days_left = 14 - (now - c.created_at).days
            if 0 < days_left <= 3:
                items.append({
                    "type": "trial_expiring",
                    "severity": "high",
                    "message": f'Trial "{c.client_name}" expires in {days_left} day{"s" if days_left != 1 else ""}',
                    "link": f"/admin/clients/{c.id}",
                    "icon": "⏰",
                })

    # 2. Clients with 0 posts this week (paying only)
    paying_clients = (
        db.query(Client)
        .filter(Client.is_active.is_(True), Client.plan_type != "trial")
        .all()
    )
    for c in paying_clients:
        posts = (
            db.query(sa_func.count(CommentDraft.id))
            .filter(
                CommentDraft.client_id == c.id,
                CommentDraft.status == "posted",
                CommentDraft.posted_at >= week_ago,
            )
            .scalar()
        ) or 0
        if posts == 0:
            items.append({
                "type": "zero_posts",
                "severity": "high",
                "message": f'"{c.client_name}" has 0 posts this week',
                "link": f"/admin/clients/{c.id}",
                "icon": "⚠️",
            })

    # 3. Pending reviews count
    pending = (
        db.query(sa_func.count(CommentDraft.id))
        .filter(CommentDraft.status == "pending")
        .scalar()
    ) or 0
    if pending > 0:
        items.append({
            "type": "pending_reviews",
            "severity": "medium",
            "message": f"{pending} draft{'s' if pending != 1 else ''} pending review",
            "link": "/admin/review",
            "icon": "📥",
        })

    # 4. Frozen avatars
    frozen_count = (
        db.query(sa_func.count(Avatar.id))
        .filter(Avatar.active.is_(True), Avatar.is_frozen.is_(True))
        .scalar()
    ) or 0
    if frozen_count > 0:
        items.append({
            "type": "frozen_avatars",
            "severity": "medium",
            "message": f"{frozen_count} avatar{'s' if frozen_count != 1 else ''} frozen",
            "link": "/admin/avatars",
            "icon": "🧊",
        })

    return items
