"""Decision Center routes — unified operations workspace with prescriptive analytics.

Provides:
- GET /admin/decision-center — main Decision Center page
- GET /admin/decision-center/live-pulse/{avatar_id} — HTMX partial: live pulse panel
- GET /admin/decision-center/queue — HTMX partial: decision queue
- GET /admin/decision-center/insights/{avatar_id} — HTMX partial: AI insights panel
- POST /admin/decision-center/bulk-approve — bulk approve high-confidence drafts
- POST /admin/decision-center/execute-action/{avatar_id} — execute prescriptive action
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_superuser
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.user import User
from app.services.risk_prediction import (
    compute_risk_prediction,
    get_avatar_risk_summary,
    get_decision_queue,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/decision-center")
templates = Jinja2Templates(directory="app/templates")
templates.env.cache = {}


@router.get("", response_class=HTMLResponse)
def decision_center_page(
    request: Request,
    avatar_id: str | None = None,
    client_id: str | None = None,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Main Decision Center page — shell with HTMX lazy-loaded panels."""
    # Get list of avatars for selector
    avatars = (
        db.query(Avatar)
        .filter(Avatar.active.is_(True))
        .order_by(Avatar.reddit_username)
        .all()
    )

    # Get list of clients for filter
    clients = (
        db.query(Client)
        .filter(Client.is_active.is_(True))
        .order_by(Client.client_name)
        .all()
    )

    # Default to first avatar if none selected
    selected_avatar = None
    if avatar_id:
        try:
            selected_avatar = db.query(Avatar).filter(Avatar.id == uuid.UUID(avatar_id)).first()
        except ValueError:
            pass

    if not selected_avatar and avatars:
        # Pick the avatar with highest risk (or first active)
        selected_avatar = avatars[0]

    # Pending count for badge
    pending_count = (
        db.query(func.count(CommentDraft.id))
        .filter(CommentDraft.status == "pending")
        .scalar()
    ) or 0

    return templates.TemplateResponse(
        name="admin_decision_center.html",
        context={
            "request": request,
            "active_nav": "decision-center",
            "avatars": avatars,
            "clients": clients,
            "selected_avatar": selected_avatar,
            "selected_client_id": client_id,
            "pending_count": pending_count,
        },
        request=request,
    )


@router.get("/live-pulse/{avatar_id}", response_class=HTMLResponse)
def decision_center_live_pulse(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial: Live Pulse panel with activity sparkline and risk forecast."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("<p class='text-red-400 text-sm'>Avatar not found</p>")

    # Compute risk prediction
    risk = compute_risk_prediction(db, avatar)

    # Activity sparkline data (24 hours, hourly buckets)
    now = datetime.now(timezone.utc)
    sparkline_data = []
    for hour_offset in range(24):
        hour_start = now - timedelta(hours=23 - hour_offset)
        hour_end = hour_start + timedelta(hours=1)
        count = (
            db.query(func.count(CommentDraft.id))
            .filter(
                CommentDraft.avatar_id == avatar_id,
                CommentDraft.created_at >= hour_start,
                CommentDraft.created_at < hour_end,
            )
            .scalar()
        ) or 0
        sparkline_data.append(count)

    # Status badges
    badges = {
        "frozen": avatar.is_frozen,
        "shadowban": avatar.is_shadowbanned or avatar.health_status == "shadowbanned",
        "cqs": avatar.cqs_level or "unknown",
        "reddit_status": avatar.reddit_status or "unknown",
    }

    return templates.TemplateResponse(
        name="partials/dc_live_pulse.html",
        context={
            "request": request,
            "avatar": avatar,
            "risk": risk,
            "sparkline_data": sparkline_data,
            "badges": badges,
        },
        request=request,
    )


@router.get("/queue", response_class=HTMLResponse)
def decision_center_queue(
    request: Request,
    client_id: str | None = None,
    avatar_id: str | None = None,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial: Decision Queue — prioritized by risk level."""
    filter_client = None
    filter_avatar = None

    if client_id:
        try:
            filter_client = uuid.UUID(client_id)
        except ValueError:
            pass

    if avatar_id:
        try:
            filter_avatar = uuid.UUID(avatar_id)
        except ValueError:
            pass

    items = get_decision_queue(db, client_id=filter_client, avatar_id=filter_avatar)

    # Split into risk groups
    high_risk_items = [i for i in items if i.risk_level == "high"]
    normal_items = [i for i in items if i.risk_level == "normal"]

    return templates.TemplateResponse(
        name="partials/dc_queue.html",
        context={
            "request": request,
            "high_risk_items": high_risk_items,
            "normal_items": normal_items,
            "total_count": len(items),
        },
        request=request,
    )


@router.get("/insights/{avatar_id}", response_class=HTMLResponse)
def decision_center_insights(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial: AI Insights & Deep Drill-Down panel."""
    from app.models.avatar_subreddit_presence import AvatarSubredditPresence
    from app.models.correction_pattern import CorrectionPattern
    from app.models.edit_record import EditRecord

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("<p class='text-red-400 text-sm'>Avatar not found</p>")

    # Risk prediction for health scorecard
    risk = compute_risk_prediction(db, avatar)

    # Subreddit presence for visualization
    presence_records = (
        db.query(AvatarSubredditPresence)
        .filter(AvatarSubredditPresence.avatar_id == avatar_id)
        .order_by(AvatarSubredditPresence.total_karma.desc())
        .limit(10)
        .all()
    )

    # Learning loop data (30 days)
    now = datetime.now(timezone.utc)
    window_30d = now - timedelta(days=30)

    # Human edit rate vs AI unchanged
    total_edits_30d = (
        db.query(func.count(EditRecord.id))
        .filter(
            EditRecord.avatar_id == avatar_id,
            EditRecord.created_at >= window_30d,
        )
        .scalar()
    ) or 0

    unchanged_30d = (
        db.query(func.count(EditRecord.id))
        .filter(
            EditRecord.avatar_id == avatar_id,
            EditRecord.created_at >= window_30d,
            EditRecord.final_status == "approved_unchanged",
        )
        .scalar()
    ) or 0

    edited_30d = total_edits_30d - unchanged_30d
    ai_accuracy_30d = int((unchanged_30d / total_edits_30d * 100) if total_edits_30d > 0 else 0)

    # Self-learning patterns
    patterns = (
        db.query(CorrectionPattern)
        .filter(
            CorrectionPattern.avatar_id == avatar_id,
        )
        .order_by(CorrectionPattern.frequency.desc())
        .limit(5)
        .all()
    )

    return templates.TemplateResponse(
        name="partials/dc_insights.html",
        context={
            "request": request,
            "avatar": avatar,
            "risk": risk,
            "presence_records": presence_records,
            "learning_stats": {
                "total_edits_30d": total_edits_30d,
                "unchanged_30d": unchanged_30d,
                "edited_30d": edited_30d,
                "ai_accuracy_30d": ai_accuracy_30d,
            },
            "patterns": patterns,
        },
        request=request,
    )


@router.post("/bulk-approve", response_class=HTMLResponse)
def decision_center_bulk_approve(
    request: Request,
    min_confidence: int = Form(default=90),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Bulk approve all pending drafts with confidence score >= threshold."""
    from app.services.risk_prediction import _compute_confidence_score
    from app.services.learning import LearningService

    drafts = (
        db.query(CommentDraft)
        .filter(CommentDraft.status == "pending")
        .all()
    )

    approved_count = 0
    skipped_count = 0
    learning_service = LearningService()

    for draft in drafts:
        confidence = _compute_confidence_score(draft)
        if confidence >= min_confidence:
            # Check avatar risk — don't auto-approve high-risk avatars
            avatar = draft.avatar
            if avatar and (avatar.is_frozen or avatar.is_shadowbanned or avatar.health_status == "shadowbanned"):
                skipped_count += 1
                continue

            draft.status = "approved"
            approved_count += 1

            # Capture learning record
            try:
                thread = draft.thread
                if thread:
                    learning_service.capture_edit_record(
                        db=db, draft=draft, thread=thread, status="approved_unchanged"
                    )
            except Exception:
                pass
        else:
            skipped_count += 1

    db.commit()

    return HTMLResponse(
        f'<div class="px-4 py-2 bg-green-900/30 border border-green-700 rounded-lg text-sm text-green-300">'
        f'✓ Bulk approved {approved_count} drafts (confidence ≥ {min_confidence}%). '
        f'{skipped_count} skipped (low confidence or high risk).'
        f'</div>'
    )


@router.post("/execute-action/{avatar_id}", response_class=HTMLResponse)
def decision_center_execute_action(
    request: Request,
    avatar_id: uuid.UUID,
    action_type: str = Form(...),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Execute a prescriptive action on an avatar (freeze, reduce frequency, etc.)."""
    from app.services import audit as audit_service

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return HTMLResponse("<p class='text-red-400 text-sm'>Avatar not found</p>")

    result_message = ""

    if action_type == "freeze":
        avatar.is_frozen = True
        avatar.freeze_reason = "Decision Center: AI risk prediction triggered freeze"
        avatar.frozen_at = datetime.now(timezone.utc)
        result_message = f"✓ Avatar u/{avatar.reddit_username} frozen successfully"

        try:
            audit_service.log_action(
                db=db,
                user_id=current_user.id,
                action="avatar_frozen_by_decision_center",
                entity_type="avatar",
                entity_id=avatar.id,
                details={"reason": "AI risk prediction", "action_type": action_type},
            )
        except Exception:
            pass

    elif action_type == "reduce_frequency":
        # Log recommendation — actual frequency reduction is manual
        result_message = (
            f"⚠ Recommendation logged for u/{avatar.reddit_username}: "
            f"reduce posting to max 3/day. Operator must enforce manually."
        )
        try:
            audit_service.log_action(
                db=db,
                user_id=current_user.id,
                action="frequency_reduction_recommended",
                entity_type="avatar",
                entity_id=avatar.id,
                details={"action_type": action_type},
            )
        except Exception:
            pass

    elif action_type == "switch_subreddits":
        result_message = (
            f"⚠ Recommendation logged for u/{avatar.reddit_username}: "
            f"diversify subreddit activity. Review subreddit assignments."
        )
    else:
        result_message = f"Action '{action_type}' acknowledged for u/{avatar.reddit_username}"

    db.commit()

    color = "green" if "✓" in result_message else "amber"
    return HTMLResponse(
        f'<div class="px-4 py-2 bg-{color}-900/30 border border-{color}-700 rounded-lg text-sm text-{color}-300">'
        f'{result_message}'
        f'</div>'
    )
