"""Portal routes for Subreddit Risk Profile page.

Client-scoped risk profile view: scopes daily history and avatar fitness
to avatars owned by the current user's client only. Reuses admin partials.

Accessible to: client_admin, client_manager, client_viewer (via require_client_access).
Also accessible to owner/partner for debugging.
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
from app.models.comment_draft import CommentDraft
from app.models.subreddit import ClientSubredditAssignment, Subreddit
from app.models.subreddit_daily_stats import SubredditDailyStats
from app.models.subreddit_risk_profile import SubredditRiskProfile
from app.models.user import User
from app.models.user_role import UserRole

router = APIRouter(prefix="/portal/subreddits", tags=["portal-risk-profile"])
templates = Jinja2Templates(directory="app/templates")

# Roles allowed to view portal risk profile
_PORTAL_ROLES = {
    UserRole.owner,
    UserRole.partner,
    UserRole.client_admin,
    UserRole.client_manager,
    UserRole.client_viewer,
}


def _require_portal_risk_profile_access(user: User) -> None:
    """Verify user has one of the allowed roles for portal risk profile access."""
    if user.user_role not in _PORTAL_ROLES and not user.is_superuser:
        raise HTTPException(status_code=403, detail="Access Denied")


def _get_user_client_id(user: User) -> uuid.UUID | None:
    """Get client_id for the current user. Owner/partner see all (returns None)."""
    if user.user_role in (UserRole.owner, UserRole.partner) or user.is_superuser:
        return None  # No client scoping for platform admins
    return user.client_id


def _get_subreddit_or_404(db: Session, subreddit_id: uuid.UUID) -> Subreddit:
    """Load subreddit by ID or raise 404."""
    subreddit = db.query(Subreddit).filter(Subreddit.id == subreddit_id).first()
    if not subreddit:
        raise HTTPException(status_code=404, detail="Subreddit not found")
    return subreddit


def _verify_client_subreddit_access(
    db: Session, subreddit_id: uuid.UUID, client_id: uuid.UUID | None
) -> None:
    """Verify the subreddit is assigned to the user's client.

    Owner/partner (client_id=None) always have access.
    Client-scoped users must have an active assignment.
    """
    if client_id is None:
        return  # Platform admin — unrestricted

    assignment = (
        db.query(ClientSubredditAssignment)
        .filter(
            ClientSubredditAssignment.subreddit_id == subreddit_id,
            ClientSubredditAssignment.client_id == client_id,
            ClientSubredditAssignment.is_active.is_(True),
        )
        .first()
    )
    if not assignment:
        raise HTTPException(status_code=404, detail="Subreddit not found")


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


def _get_client_avatars_fitness(
    db: Session, subreddit_name: str, client_id: uuid.UUID | None
) -> list:
    """Get avatar fitness scores scoped to the user's client.

    If client_id is None (owner/partner), returns all avatars.
    Otherwise, filters to only avatars assigned to that client.
    """
    query = (
        db.query(AvatarSubredditCompatibility, Avatar)
        .join(Avatar, Avatar.id == AvatarSubredditCompatibility.avatar_id)
        .filter(
            AvatarSubredditCompatibility.subreddit_name == subreddit_name,
            AvatarSubredditCompatibility.fitness_score.isnot(None),
            Avatar.is_frozen == False,  # noqa: E712
            Avatar.warming_phase >= 1,
        )
    )

    if client_id is not None:
        query = query.filter(Avatar.client_ids.any(str(client_id)))

    compatibilities = query.all()

    results = []
    for compat, avatar in compatibilities:
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
def portal_subreddit_risk_profile(
    request: Request,
    subreddit_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Client-scoped risk profile page."""
    _require_portal_risk_profile_access(current_user)

    client_id = _get_user_client_id(current_user)
    subreddit = _get_subreddit_or_404(db, subreddit_id)

    # Verify client has access to this subreddit
    _verify_client_subreddit_access(db, subreddit_id, client_id)

    # Load risk profile (may be None)
    profile = (
        db.query(SubredditRiskProfile)
        .filter(SubredditRiskProfile.subreddit_id == subreddit_id)
        .first()
    )

    # Determine data status
    no_profile = profile is None
    insufficient_data = no_profile or profile.confidence_level == "insufficient_data"

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

    # Avatar fitness scores — scoped to client
    avatar_fitness = _get_client_avatars_fitness(db, subreddit.subreddit_name, client_id)

    # Risk score history for sparkline (up to 12 weeks)
    risk_score_history = profile.risk_score_history if profile else []

    # Next computation date — use adaptive next_check_at if set, otherwise next Sunday
    now = datetime.now(timezone.utc)
    if profile and profile.next_check_at:
        nc = profile.next_check_at
        if nc <= now:
            next_computation = "within 24 hours (due)"
        else:
            nc_days = (nc - now).total_seconds() / 86400
            if nc_days < 1:
                next_computation = f"in ~{int(nc_days * 24)} hours"
            else:
                next_computation = f"{nc.strftime('%Y-%m-%d')} (in {int(nc_days)} days)"
    else:
        days_until_sunday = (6 - now.weekday()) % 7
        if days_until_sunday == 0 and now.hour >= 5:
            days_until_sunday = 7
        next_computation = (now + timedelta(days=days_until_sunday)).strftime("%Y-%m-%d")

    # Resolve effective client_id for sidebar
    effective_client_id = client_id or current_user.client_id
    # For owner/partner without client_id — resolve from subreddit assignment
    if not effective_client_id:
        assignment = (
            db.query(ClientSubredditAssignment)
            .filter(
                ClientSubredditAssignment.subreddit_id == subreddit_id,
                ClientSubredditAssignment.is_active.is_(True),
            )
            .first()
        )
        if assignment:
            effective_client_id = assignment.client_id

    # Emotional profile (community tone) — stored as JSONB on subreddits table
    emotional_profile = subreddit.emotional_profile if subreddit.emotional_profile else None

    # Community stats — basic subreddit info from scraped data
    community_stats = None
    try:
        from app.models.scrape_log import ScrapeLog
        from sqlalchemy import func as sa_func, text as sa_text

        # Get average posts/day from last 30 days of scrape logs
        thirty_days_ago = now - timedelta(days=30)
        scrape_agg = db.execute(
            sa_text("""
                SELECT
                    COUNT(*) as total_scrapes,
                    COALESCE(SUM(posts_new), 0) as total_new_posts,
                    COALESCE(AVG(posts_found), 0) as avg_found
                FROM scrape_log
                WHERE subreddit_name = :name AND scraped_at >= :since
            """),
            {"name": subreddit.subreddit_name, "since": thirty_days_ago},
        ).fetchone()

        if scrape_agg and scrape_agg[0] > 0:
            total_scrapes = scrape_agg[0]
            total_new = int(scrape_agg[1])
            # Estimate posts/day: total new posts / 30 days
            posts_per_day = round(total_new / 30, 1) if total_new > 0 else 0

            community_stats = {
                "posts_per_day": posts_per_day,
                "avg_comments": None,  # Would need thread data
                "subscribers": None,
                "subscribers_display": None,
                "active_users": None,
                "active_users_display": None,
            }

            # Try to get subscriber count from subreddit model
            if hasattr(subreddit, 'subscribers') and subreddit.subscribers:
                subs_count = subreddit.subscribers
                community_stats["subscribers"] = subs_count
                if subs_count >= 1_000_000:
                    community_stats["subscribers_display"] = f"{subs_count / 1_000_000:.1f}M"
                elif subs_count >= 1_000:
                    community_stats["subscribers_display"] = f"{subs_count / 1_000:.0f}K"
                else:
                    community_stats["subscribers_display"] = str(subs_count)
    except Exception:
        db.rollback()

    # Build full sidebar context (same as _portal_render in portal.py)
    from app.routes.portal import _get_sidebar_context
    sidebar_ctx = _get_sidebar_context(effective_client_id, db) if effective_client_id else {
        "client_id": "",
        "client_name": "",
        "pending_count": 0,
        "has_shadowbanned": False,
        "is_trial": False,
        "trial_days_remaining": None,
    }

    # User info from request state (set by auth middleware)
    user_name = getattr(request.state, "user_full_name", "") or ""
    user_email = getattr(request.state, "user_email", "") or ""
    user_role = getattr(request.state, "user_role", "") or ""

    # App env
    from app.config import get_settings as _get_settings
    app_env = _get_settings().app_env

    ctx = {
        "request": request,
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
        "emotional_profile": emotional_profile,
        "community_stats": community_stats,
        "active_page": "subreddits",
        # Sidebar context
        "user_name": user_name,
        "user_email": user_email,
        "user_role": user_role,
        "app_env": app_env,
        # Budget/usage defaults (not critical for risk profile page)
        "budget_warning": False,
        "budget_exhausted": False,
        "usage_pct": 0,
        "month_generated": 0,
        "action_limit": 999,
        "hidden_actions": set(),
        "approval_actions": set(),
        "pending_requests_count": 0,
    }
    ctx.update(sidebar_ctx)

    return templates.TemplateResponse(
        request,
        "client/subreddit_risk_profile.html",
        ctx,
    )


@router.get("/{subreddit_id}/risk-profile/daily-history", response_class=HTMLResponse)
def portal_risk_profile_daily_history(
    request: Request,
    subreddit_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """HTMX partial: client-scoped daily stats table (lazy-loaded).

    Scopes daily history to only comments from the user's client's avatars.
    """
    _require_portal_risk_profile_access(current_user)

    client_id = _get_user_client_id(current_user)
    _get_subreddit_or_404(db, subreddit_id)
    _verify_client_subreddit_access(db, subreddit_id, client_id)

    subreddit = db.query(Subreddit).filter(Subreddit.id == subreddit_id).first()

    if client_id is None:
        # Owner/partner: show all daily stats (same as admin)
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
    else:
        # Client-scoped: compute daily stats from comment drafts for client's avatars only
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        from sqlalchemy import cast, case, Date as SQLDate, func

        # Get daily stats from CommentDraft for client's avatars in this subreddit
        from app.models.thread import RedditThread

        daily_rows = (
            db.query(
                cast(CommentDraft.posted_at, SQLDate).label("date"),
                func.count(CommentDraft.id).label("comments_posted"),
                func.sum(
                    case(
                        (CommentDraft.is_deleted == False, 1),  # noqa: E712
                        else_=0,
                    )
                ).label("comments_survived"),
            )
            .join(Avatar, CommentDraft.avatar_id == Avatar.id)
            .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
            .filter(
                Avatar.client_ids.any(str(client_id)),
                RedditThread.subreddit == subreddit.subreddit_name,
                CommentDraft.status == "posted",
                CommentDraft.posted_at.isnot(None),
                CommentDraft.posted_at >= thirty_days_ago,
            )
            .group_by(cast(CommentDraft.posted_at, SQLDate))
            .order_by(desc(cast(CommentDraft.posted_at, SQLDate)))
            .all()
        )

        # Convert to objects matching the template expectations
        daily_stats = []
        for row in daily_rows:
            posted = row.comments_posted or 0
            survived = row.comments_survived or 0
            removal_rate = (1 - survived / posted) if posted > 0 else None
            daily_stats.append(type("DailyStat", (), {
                "date": row.date,
                "comments_posted": posted,
                "comments_survived": survived,
                "removal_rate": removal_rate,
            })())

    return templates.TemplateResponse(
        request,
        "partials/risk_profile_daily_history.html",
        {
            "daily_stats": daily_stats,
        },
    )


@router.get("/{subreddit_id}/risk-profile/trend-chart", response_class=HTMLResponse)
def portal_risk_profile_trend_chart(
    request: Request,
    subreddit_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """HTMX partial: 12-week risk score trend (lazy-loaded)."""
    _require_portal_risk_profile_access(current_user)

    client_id = _get_user_client_id(current_user)
    _get_subreddit_or_404(db, subreddit_id)
    _verify_client_subreddit_access(db, subreddit_id, client_id)

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
