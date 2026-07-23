"""Posting Dashboard routes — admin panel for posting operations visibility.

Shows: posting events log, per-avatar stats, success/failure rates,
daily posting volume, and links to full traceability.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from app.templating import Jinja2Templates
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_superuser
from app.models.avatar import Avatar
from app.models.epg_slot import EPGSlot
from app.models.karma_snapshot import KarmaSnapshot
from app.models.posting_event import PostingEvent
from app.models.user import User

router = APIRouter(prefix="/admin/posting", tags=["posting-dashboard"])
templates = Jinja2Templates(directory="app/templates")

from app.version import __version__ as app_version
from app.config import get_settings as _get_settings
templates.env.globals["app_version"] = app_version
templates.env.globals["posting_disabled"] = lambda: _get_settings().posting_disabled
templates.env.globals["app_env"] = _get_settings().app_env


@router.get("", response_class=HTMLResponse)
def posting_dashboard(
    request: Request,
    days: int = 7,
    avatar_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Main posting dashboard — overview of all posting activity."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Base query
    events_query = db.query(PostingEvent).filter(PostingEvent.posted_at >= cutoff)
    if avatar_id:
        try:
            events_query = events_query.filter(PostingEvent.avatar_id == uuid.UUID(avatar_id))
        except ValueError:
            pass

    # Stats
    total_events = events_query.count()
    success_count = events_query.filter(PostingEvent.outcome == "success").count()
    failure_count = events_query.filter(PostingEvent.outcome == "failure").count()
    refused_count = events_query.filter(PostingEvent.outcome.in_(["refused", "skipped"])).count()

    # Recent events (latest 50)
    recent_events = (
        events_query
        .order_by(PostingEvent.posted_at.desc())
        .limit(50)
        .all()
    )

    # Per-avatar breakdown
    avatar_stats = (
        db.query(
            PostingEvent.avatar_id,
            sa_func.count(PostingEvent.id).label("total"),
            sa_func.count(PostingEvent.id).filter(PostingEvent.outcome == "success").label("success"),
            sa_func.avg(PostingEvent.duration_ms).label("avg_duration"),
        )
        .filter(PostingEvent.posted_at >= cutoff)
        .group_by(PostingEvent.avatar_id)
        .all()
    )

    # Enrich with avatar usernames
    avatar_ids = [row[0] for row in avatar_stats]
    avatars_map = {}
    if avatar_ids:
        avatars = db.query(Avatar).filter(Avatar.id.in_(avatar_ids)).all()
        avatars_map = {a.id: a for a in avatars}

    avatar_breakdown = []
    for row in avatar_stats:
        avatar = avatars_map.get(row[0])
        avatar_breakdown.append({
            "avatar_id": str(row[0]),
            "username": avatar.reddit_username if avatar else "unknown",
            "total": row.total,
            "success": row.success,
            "success_rate": (row.success / row.total * 100) if row.total > 0 else 0,
            "avg_duration_ms": int(row.avg_duration) if row.avg_duration else 0,
        })

    # EPG slots today
    today = date.today()
    slots_today = db.query(EPGSlot).filter(EPGSlot.plan_date == today).count()
    slots_posted = db.query(EPGSlot).filter(
        EPGSlot.plan_date == today, EPGSlot.status == "posted"
    ).count()
    slots_approved = db.query(EPGSlot).filter(
        EPGSlot.plan_date == today, EPGSlot.status == "approved"
    ).count()

    # Karma snapshots count (to show feedback loop is working)
    snapshots_total = db.query(sa_func.count(KarmaSnapshot.id)).scalar() or 0

    # All active avatars for filter dropdown
    all_avatars = (
        db.query(Avatar)
        .filter(Avatar.active == True)
        .order_by(Avatar.reddit_username)
        .all()
    )

    return templates.TemplateResponse(
        request,
        "admin_posting_dashboard.html",
        {
            "days": days,
            "avatar_id_filter": avatar_id or "",
            "total_events": total_events,
            "success_count": success_count,
            "failure_count": failure_count,
            "refused_count": refused_count,
            "success_rate": (success_count / total_events * 100) if total_events > 0 else 0,
            "recent_events": recent_events,
            "avatar_breakdown": avatar_breakdown,
            "slots_today": slots_today,
            "slots_posted": slots_posted,
            "slots_approved": slots_approved,
            "snapshots_total": snapshots_total,
            "all_avatars": all_avatars,
            "avatars_map": avatars_map,
            "current_user": current_user,
        },
    )


@router.get("/events/{event_id}/trace")
def posting_event_trace(
    event_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Get full trace for a posting event — links to draft, EPG slot, karma snapshots."""
    from app.services.traceability import trace_comment_json

    event = db.query(PostingEvent).filter(PostingEvent.id == uuid.UUID(event_id)).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    if event.draft_id:
        return trace_comment_json(db, event.draft_id)

    # If no draft linked, return event-only data
    return {
        "posting_event": {
            "id": str(event.id),
            "avatar_id": str(event.avatar_id),
            "outcome": event.outcome,
            "posted_at": event.posted_at.isoformat() if event.posted_at else None,
            "reddit_comment_url": event.reddit_comment_url,
            "duration_ms": event.duration_ms,
            "error_message": event.error_message,
        }
    }
