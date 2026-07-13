"""Plan limits — centralized enforcement for per-plan resource caps.

Single source of truth for all plan-based limits. Every resource that costs
AI compute or creates system load MUST be gated here.

Architecture:
- PLAN_LIMITS dict defines hard caps per plan_type
- check_* functions return (is_allowed: bool, message: str, current: int, limit: int)
- Admin overrides: if a client has an explicit field set (e.g. max_comments_per_month),
  it takes precedence over PLAN_LIMITS defaults.
- Owner/partner roles bypass all limits (they manage the system).

Usage:
    from app.services.plan_limits import check_subreddit_limit
    allowed, msg, current, limit = check_subreddit_limit(db, client_id)
    if not allowed:
        raise HTTPException(status_code=400, detail=msg)
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.client import Client
from app.models.geo_prompt import GeoPrompt
from app.models.subreddit import ClientSubredditAssignment

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Plan definitions — THE canonical source of all per-plan limits
# ---------------------------------------------------------------------------

PLAN_LIMITS: dict[str, dict[str, Any]] = {
    "trial": {
        "label": "Trial (14 days)",
        "price_usd": 0,
        "max_avatars": 0,             # Trial: 5-comment burst only, no persistent avatar
        "max_comments_month": 5,      # One-time burst (not daily drip)
        "max_subreddits": 1,          # Single subreddit for aha moment
        "max_keywords": 999,          # Unlimited — internal infrastructure, not client-facing
        "max_geo_prompts": 3,         # Minimal visibility check
        "max_geo_competitors": 999,   # Unlimited internally, top 3-5 shown to client
    },
    "seed": {
        "label": "Seed",
        "price_usd": 149,
        "max_avatars": 1,
        "max_comments_month": 30,
        "max_subreddits": 2,          # Tight — upgrade pressure by design (Tzvi)
        "max_keywords": 999,          # Unlimited — not a client-facing limit
        "max_geo_prompts": 10,        # Basic AEO
        "max_geo_competitors": 999,   # Unlimited internally, top 3-5 shown to client
    },
    "starter": {
        "label": "Starter",
        "price_usd": 399,
        "max_avatars": 3,
        "max_comments_month": 60,
        "max_subreddits": 4,          # Step up from Seed
        "max_keywords": 999,          # Unlimited — not a client-facing limit
        "max_geo_prompts": 20,        # Basic AEO
        "max_geo_competitors": 999,   # Unlimited internally, top 3-5 shown to client
    },
    "growth": {
        "label": "Growth",
        "price_usd": 799,
        "max_avatars": 7,
        "max_comments_month": 150,
        "max_subreddits": 8,          # Comfortable coverage
        "max_keywords": 999,          # Unlimited — not a client-facing limit
        "max_geo_prompts": 40,        # Full AEO
        "max_geo_competitors": 999,   # Unlimited internally, top 3-5 shown to client
    },
    "scale": {
        "label": "Scale",
        "price_usd": 1499,
        "max_avatars": 15,
        "max_comments_month": 400,
        "max_subreddits": 999,        # Unlimited — $1,499 client shouldn't hit walls
        "max_keywords": 999,          # Unlimited — not a client-facing limit
        "max_geo_prompts": 60,        # Full AEO
        "max_geo_competitors": 999,   # Unlimited internally, top 3-5 shown to client
    },
    "agency": {
        "label": "Agency",
        "price_usd": 2000,
        "max_avatars": 999,
        "max_comments_month": 9999,
        "max_subreddits": 999,
        "max_keywords": 999,
        "max_geo_prompts": 100,
        "max_geo_competitors": 999,
    },
}


# ---------------------------------------------------------------------------
# Helper: get limit for a client (respects explicit overrides)
# ---------------------------------------------------------------------------

def get_plan_limit(client: Client, limit_key: str) -> int:
    """Get the limit value for a client, checking explicit override fields first.

    Override mapping:
    - max_comments_month → client.max_comments_per_month
    - max_avatars → client.max_avatars
    - Others: no per-client override, plan default only.
    """
    plan = client.plan_type or "starter"
    plan_config = PLAN_LIMITS.get(plan, PLAN_LIMITS["starter"])
    plan_default = plan_config.get(limit_key, 999)

    # Client-level overrides (admin can set higher/lower for custom deals)
    if limit_key == "max_comments_month" and client.max_comments_per_month is not None:
        return client.max_comments_per_month
    if limit_key == "max_avatars":
        return client.max_avatars or plan_default

    return plan_default


def get_plan_limits_for_client(db: Session, client_id: UUID) -> dict[str, int] | None:
    """Get all limits for a client. Returns None if client not found."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return None
    return {key: get_plan_limit(client, key) for key in (
        "max_avatars", "max_comments_month", "max_subreddits",
        "max_keywords", "max_geo_prompts", "max_geo_competitors",
    )}


# ---------------------------------------------------------------------------
# Check functions — each returns (allowed, message, current, limit)
# ---------------------------------------------------------------------------

def check_subreddit_limit(db: Session, client_id: UUID) -> tuple[bool, str, int, int]:
    """Check if client can add another subreddit.

    Counts only active professional assignments (hobby subs on avatar
    don't count against plan limit).
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return True, "", 0, 999  # fail-open for missing client

    limit = get_plan_limit(client, "max_subreddits")

    current = (
        db.query(func.count(ClientSubredditAssignment.id))
        .filter(
            ClientSubredditAssignment.client_id == client_id,
            ClientSubredditAssignment.is_active == True,
        )
        .scalar() or 0
    )

    if current >= limit:
        msg = f"Subreddit limit reached ({current}/{limit}). Upgrade plan to add more."
        logger.warning("PLAN_LIMIT | subreddits | client=%s | %d/%d", client_id, current, limit)
        return False, msg, current, limit

    return True, "", current, limit


def check_keyword_limit(db: Session, client_id: UUID) -> tuple[bool, str, int, int]:
    """Check if client can add another keyword.

    Counts total keywords across all priority tiers.
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return True, "", 0, 999

    limit = get_plan_limit(client, "max_keywords")

    # Count total keywords across all priorities
    current = 0
    if client.keywords:
        for kw_list in client.keywords.values():
            if isinstance(kw_list, list):
                current += len(kw_list)

    if current >= limit:
        msg = f"Keyword limit reached ({current}/{limit}). Upgrade plan to add more."
        logger.warning("PLAN_LIMIT | keywords | client=%s | %d/%d", client_id, current, limit)
        return False, msg, current, limit

    return True, "", current, limit


def check_geo_prompt_limit(db: Session, client_id: UUID) -> tuple[bool, str, int, int]:
    """Check if client can add another GEO/AEO monitoring prompt."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return True, "", 0, 999

    limit = get_plan_limit(client, "max_geo_prompts")

    current = (
        db.query(func.count(GeoPrompt.id))
        .filter(GeoPrompt.client_id == client_id, GeoPrompt.is_active == True)
        .scalar() or 0
    )

    if current >= limit:
        msg = f"GEO prompt limit reached ({current}/{limit}). Upgrade plan to add more."
        logger.warning("PLAN_LIMIT | geo_prompts | client=%s | %d/%d", client_id, current, limit)
        return False, msg, current, limit

    return True, "", current, limit


def check_geo_competitor_limit(db: Session, client_id: UUID) -> tuple[bool, str, int, int]:
    """Check if client can add another GEO competitor."""
    from app.models.geo_competitor import GeoCompetitor

    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return True, "", 0, 999

    limit = get_plan_limit(client, "max_geo_competitors")

    current = (
        db.query(func.count(GeoCompetitor.id))
        .filter(GeoCompetitor.client_id == client_id, GeoCompetitor.is_active == True)
        .scalar() or 0
    )

    if current >= limit:
        msg = f"Competitor limit reached ({current}/{limit}). Upgrade plan to add more."
        logger.warning("PLAN_LIMIT | geo_competitors | client=%s | %d/%d", client_id, current, limit)
        return False, msg, current, limit

    return True, "", current, limit


# ---------------------------------------------------------------------------
# Usage summary (for UI meters)
# ---------------------------------------------------------------------------

def get_usage_summary(db: Session, client_id: UUID) -> dict[str, dict[str, int]] | None:
    """Get current usage vs limits for all resource types.

    Returns dict like:
    {
        "subreddits": {"current": 3, "limit": 5},
        "keywords": {"current": 15, "limit": 30},
        "geo_prompts": {"current": 8, "limit": 20},
        "geo_competitors": {"current": 4, "limit": 10},
        "avatars": {"current": 2, "limit": 3},
        "comments_month": {"current": 25, "limit": 60},
    }
    """
    from app.models.avatar import Avatar
    from app.models.comment_draft import CommentDraft
    from datetime import datetime, timezone

    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return None

    # Subreddits
    sub_count = (
        db.query(func.count(ClientSubredditAssignment.id))
        .filter(
            ClientSubredditAssignment.client_id == client_id,
            ClientSubredditAssignment.is_active == True,
        )
        .scalar() or 0
    )

    # Keywords
    kw_count = 0
    if client.keywords:
        for kw_list in client.keywords.values():
            if isinstance(kw_list, list):
                kw_count += len(kw_list)

    # GEO prompts
    geo_count = (
        db.query(func.count(GeoPrompt.id))
        .filter(GeoPrompt.client_id == client_id, GeoPrompt.is_active == True)
        .scalar() or 0
    )

    # GEO competitors
    from app.models.geo_competitor import GeoCompetitor
    comp_count = (
        db.query(func.count(GeoCompetitor.id))
        .filter(GeoCompetitor.client_id == client_id, GeoCompetitor.is_active == True)
        .scalar() or 0
    )

    # Avatars
    avatar_count = (
        db.query(func.count(Avatar.id))
        .filter(Avatar.client_ids.any(str(client_id)), Avatar.is_active == True)
        .scalar() or 0
    )

    # Monthly comments (approved + posted this month)
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    avatar_ids = [a.id for a in db.query(Avatar.id).filter(Avatar.client_ids.any(str(client_id))).all()]
    comments_month = 0
    if avatar_ids:
        comments_month = (
            db.query(func.count(CommentDraft.id))
            .filter(
                CommentDraft.avatar_id.in_(avatar_ids),
                CommentDraft.status.in_(["approved", "posted"]),
                CommentDraft.created_at >= month_start,
            )
            .scalar() or 0
        )

    return {
        "subreddits": {"current": sub_count, "limit": get_plan_limit(client, "max_subreddits")},
        "keywords": {"current": kw_count, "limit": get_plan_limit(client, "max_keywords")},
        "geo_prompts": {"current": geo_count, "limit": get_plan_limit(client, "max_geo_prompts")},
        "geo_competitors": {"current": comp_count, "limit": get_plan_limit(client, "max_geo_competitors")},
        "avatars": {"current": avatar_count, "limit": get_plan_limit(client, "max_avatars")},
        "comments_month": {"current": comments_month, "limit": get_plan_limit(client, "max_comments_month")},
    }
