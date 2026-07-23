"""Admin routes for Subreddit Risk Profile page.

Provides full risk profile view for admin roles: risk score badge,
trend chart, extracted rules, moderation insights, recommendations,
avatar fitness table, and daily history (HTMX lazy-loaded).

Accessible to: owner, partner, client_admin, client_manager, client_viewer, avatar_manager.
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from app.templating import Jinja2Templates
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.permissions import get_current_user
from app.models.avatar import Avatar
from app.models.avatar_subreddit_compatibility import AvatarSubredditCompatibility
from app.models.subreddit import ClientSubredditAssignment, Subreddit
from app.models.subreddit_daily_stats import SubredditDailyStats
from app.models.subreddit_risk_profile import SubredditRiskProfile
from app.models.user import User
from app.models.user_role import UserRole

router = APIRouter(prefix="/admin/subreddits", tags=["admin-risk-profile"])
templates = Jinja2Templates(directory="app/templates")

from app.version import __version__ as app_version
from app.config import get_settings as _get_settings
templates.env.globals["app_version"] = app_version
templates.env.globals["posting_disabled"] = lambda: _get_settings().posting_disabled
templates.env.globals["app_env"] = _get_settings().app_env

# Roles allowed to view risk profile page
_ALLOWED_ROLES = {
    UserRole.owner,
    UserRole.partner,
    UserRole.client_admin,
    UserRole.client_manager,
    UserRole.client_viewer,
    UserRole.avatar_manager,
}


def _require_risk_profile_access(user: User) -> None:
    """Verify user has one of the allowed roles for risk profile access."""
    if user.user_role not in _ALLOWED_ROLES and not user.is_superuser:
        raise HTTPException(status_code=403, detail="Access Denied")


def _get_subreddit_or_404(db: Session, subreddit_id: uuid.UUID) -> Subreddit:
    """Load subreddit by ID or raise 404."""
    subreddit = db.query(Subreddit).filter(Subreddit.id == subreddit_id).first()
    if not subreddit:
        raise HTTPException(status_code=404, detail="Subreddit not found")
    return subreddit


def _risk_color(score: int) -> dict:
    """Return color classes for a risk score badge."""
    if score <= 30:
        return {"bg": "bg-green-500/10", "text": "text-green-500", "label": "Low"}
    elif score <= 60:
        return {"bg": "bg-yellow-500/10", "text": "text-yellow-500", "label": "Medium"}
    elif score <= 80:
        return {"bg": "bg-orange-500/10", "text": "text-orange-500", "label": "High"}
    else:
        return {"bg": "bg-red-500/10", "text": "text-red-500", "label": "Critical"}


def _get_eligible_avatars(db: Session, subreddit_name: str) -> list:
    """Get avatars assigned to subreddit that are eligible for fitness display.

    Eligible: not frozen, not Phase 0 (Mentor), warming_phase >= 1.
    """
    # Get all avatars that have a compatibility record for this subreddit
    compatibilities = (
        db.query(AvatarSubredditCompatibility, Avatar)
        .join(Avatar, Avatar.id == AvatarSubredditCompatibility.avatar_id)
        .filter(
            AvatarSubredditCompatibility.subreddit_name == subreddit_name,
            AvatarSubredditCompatibility.fitness_score.isnot(None),
            Avatar.is_frozen == False,  # noqa: E712
            Avatar.warming_phase >= 1,
        )
        .all()
    )

    results = []
    for compat, avatar in compatibilities:
        # Skip Phase 0 (Mentor) avatars
        if avatar.warming_phase == 0:
            continue
        results.append({
            "avatar_name": avatar.display_name or avatar.reddit_username or "Unknown",
            "fitness_score": compat.fitness_score,
            "mismatch_reasons": compat.mismatch_reasons or [],
            "computed_at": compat.fitness_computed_at,
        })

    return results


@router.get("/{subreddit_id}/risk-profile", response_class=HTMLResponse)
def admin_subreddit_risk_profile(
    request: Request,
    subreddit_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full risk profile page (admin roles)."""
    _require_risk_profile_access(current_user)

    subreddit = _get_subreddit_or_404(db, subreddit_id)

    # Load risk profile (may be None)
    profile = (
        db.query(SubredditRiskProfile)
        .filter(SubredditRiskProfile.subreddit_id == subreddit_id)
        .first()
    )

    # Determine if we have sufficient data
    no_profile = profile is None
    insufficient_data = (
        no_profile or profile.confidence_level == "insufficient_data"
    )

    # Moderation profile not computed
    moderation_not_computed = no_profile or not profile.moderation_profile or (
        profile.last_profile_computed_at is None
    )

    # Risk score and color
    risk_score = profile.risk_score if profile else 50
    risk_color = _risk_color(risk_score)

    # Extracted rules
    extracted_rules = profile.extracted_rules if profile else []
    extraction_date = profile.last_rule_extraction_at if profile else None

    # Moderation insights
    moderation_profile = profile.moderation_profile if profile else {}
    dangerous_hours = profile.dangerous_hours if profile else []
    dominant_timezone = profile.dominant_timezone if profile else "UTC"

    # Recommendations (max 5)
    recommendations = (profile.recommendations if profile else [])[:5]

    # Avatar fitness scores
    avatar_fitness = _get_eligible_avatars(db, subreddit.subreddit_name)

    # Risk score history for sparkline (up to 12 weeks)
    risk_score_history = profile.risk_score_history if profile else []

    # Next computation date (next Sunday 05:30)
    now = datetime.now(timezone.utc)
    days_until_sunday = (6 - now.weekday()) % 7
    if days_until_sunday == 0 and now.hour >= 5:
        days_until_sunday = 7
    next_computation = (now + timedelta(days=days_until_sunday)).strftime("%Y-%m-%d")

    return templates.TemplateResponse(
        request,
        "admin_subreddit_risk_profile.html",
        {
            "user": current_user,
            "subreddit": subreddit,
            "subreddit_id": str(subreddit_id),
            "profile": profile,
            "no_profile": no_profile,
            "insufficient_data": insufficient_data,
            "moderation_not_computed": moderation_not_computed,
            "risk_score": risk_score,
            "risk_color": risk_color,
            "extracted_rules": extracted_rules,
            "extraction_date": extraction_date,
            "moderation_profile": moderation_profile,
            "dangerous_hours": dangerous_hours,
            "dominant_timezone": dominant_timezone,
            "recommendations": recommendations,
            "avatar_fitness": avatar_fitness,
            "risk_score_history": risk_score_history,
            "next_computation": next_computation,
            "active_nav": "subreddits",
        },
    )


@router.get("/{subreddit_id}/risk-profile/daily-history", response_class=HTMLResponse)
def admin_risk_profile_daily_history(
    request: Request,
    subreddit_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """HTMX partial: daily stats table (lazy-loaded)."""
    _require_risk_profile_access(current_user)
    _get_subreddit_or_404(db, subreddit_id)

    # Get last 30 days of daily stats (only days with at least 1 posted comment)
    thirty_days_ago = datetime.now(timezone.utc).date() - timedelta(days=30)
    daily_stats = (
        db.query(SubredditDailyStats)
        .filter(
            SubredditDailyStats.subreddit_id == subreddit_id,
            SubredditDailyStats.date >= thirty_days_ago,
            SubredditDailyStats.comments_posted > 0,
        )
        .order_by(desc(SubredditDailyStats.date))
        .all()
    )

    return templates.TemplateResponse(
        request,
        "partials/risk_profile_daily_history.html",
        {
            "daily_stats": daily_stats,
        },
    )


@router.get("/{subreddit_id}/risk-profile/trend-chart", response_class=HTMLResponse)
def admin_risk_profile_trend_chart(
    request: Request,
    subreddit_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """HTMX partial: 12-week risk score trend (lazy-loaded)."""
    _require_risk_profile_access(current_user)
    _get_subreddit_or_404(db, subreddit_id)

    profile = (
        db.query(SubredditRiskProfile)
        .filter(SubredditRiskProfile.subreddit_id == subreddit_id)
        .first()
    )

    risk_score_history = profile.risk_score_history if profile else []

    return templates.TemplateResponse(
        request,
        "partials/risk_profile_trend_chart.html",
        {
            "risk_score_history": risk_score_history,
            "current_score": profile.risk_score if profile else 50,
        },
    )
