"""Decision Center routes — HTMX partials for per-avatar Content tab.

Provides:
- GET /admin/decision-center — redirects to /admin/avatars
- GET /admin/decision-center/live-pulse/{avatar_id} — HTMX partial: live pulse panel
- GET /admin/decision-center/queue — HTMX partial: decision queue
- GET /admin/decision-center/insights/{avatar_id} — HTMX partial: AI insights panel
- POST /admin/decision-center/bulk-approve — bulk approve high-confidence drafts
- POST /admin/decision-center/execute-action/{avatar_id} — execute prescriptive action
"""

from app.logging_config import get_logger
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_superuser
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.strategy_document import StrategyDocument
from app.models.user import User
from app.services.risk_prediction import (
    compute_risk_prediction,
    get_avatar_risk_summary,
    get_decision_queue,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/admin/decision-center")
templates = Jinja2Templates(directory="app/templates")
templates.env.cache = {}
from app.version import __version__ as app_version
from app.config import get_settings as _get_settings
templates.env.globals["app_version"] = app_version
templates.env.globals["posting_disabled"] = lambda: _get_settings().posting_disabled
templates.env.globals["app_env"] = _get_settings().app_env

from app.template_filters import register_filters
register_filters(templates.env)


@router.get("")
def decision_center_page(
    request: Request,
    avatar_id: str | None = None,
    client_id: str | None = None,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Redirect — global Decision Center removed, use per-avatar Content tab."""
    from fastapi.responses import RedirectResponse
    if avatar_id:
        return RedirectResponse(
            url=f"/admin/avatars/{avatar_id}#tab=content", status_code=302
        )
    return RedirectResponse(url="/admin/avatars", status_code=302)


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

    # Operational alerts (strategy approval, etc.)
    operational_alerts = []

    # Check strategy approval status
    current_strategy = (
        db.query(StrategyDocument)
        .filter(
            StrategyDocument.avatar_id == avatar_id,
            StrategyDocument.is_current.is_(True),
        )
        .first()
    )
    if current_strategy and not current_strategy.is_approved:
        operational_alerts.append({
            "type": "warning",
            "icon": "📋",
            "title": "Strategy not approved",
            "description": f"Strategy v{current_strategy.version} generated {current_strategy.generated_at.strftime('%d.%m.%Y %H:%M') if current_strategy.generated_at else 'N/A'} — pipeline runs without strategy guidance",
            "action_url": f"/admin/avatars/{avatar_id}#tab=strategy",
            "action_label": "Review Strategy",
        })
    elif not current_strategy:
        operational_alerts.append({
            "type": "info",
            "icon": "📋",
            "title": "No strategy generated",
            "description": "This avatar has no strategy document — generation runs without strategic context",
            "action_url": f"/admin/avatars/{avatar_id}#tab=strategy",
            "action_label": "Generate Strategy",
        })

    return templates.TemplateResponse(
        name="partials/dc_live_pulse.html",
        context={
            "request": request,
            "avatar": avatar,
            "risk": risk,
            "sparkline_data": sparkline_data,
            "badges": badges,
            "operational_alerts": operational_alerts,
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

            # Sync EPG slot status
            try:
                from app.services.epg_executor import sync_slot_status
                sync_slot_status(db, draft.id, "approved")
            except Exception:
                pass

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
