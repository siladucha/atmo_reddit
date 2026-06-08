from app.logging_config import get_logger

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.dependencies.admin import require_superuser
from app.models.ai_usage import AIUsageLog
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.avatar import Avatar
from app.models.user import User

logger = get_logger(__name__)
router = APIRouter()


@router.get("/stats")
def admin_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Admin dashboard stats: clients, drafts, AI costs."""
    try:
        total_clients = db.query(func.count(Client.id)).scalar()
        total_drafts = db.query(func.count(CommentDraft.id)).scalar()
        total_avatars = db.query(func.count(Avatar.id)).filter(Avatar.active.is_(True)).scalar()

        # AI costs this month
        ai_cost = db.query(func.sum(AIUsageLog.cost_usd)).scalar() or 0
        ai_calls = db.query(func.count(AIUsageLog.id)).scalar()
        total_input_tokens = db.query(func.sum(AIUsageLog.input_tokens)).scalar() or 0
        total_output_tokens = db.query(func.sum(AIUsageLog.output_tokens)).scalar() or 0
    except Exception as e:
        logger.error(f"Database error in admin_stats: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable") from e

    return {
        "clients": total_clients,
        "active_avatars": total_avatars,
        "comment_drafts": total_drafts,
        "ai": {
            "total_calls": ai_calls,
            "total_cost_usd": float(ai_cost),
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
        },
    }


@router.get("/ai-usage")
def ai_usage_by_client(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """AI usage breakdown by client."""
    try:
        results = (
            db.query(
                Client.client_name,
                func.count(AIUsageLog.id).label("calls"),
                func.sum(AIUsageLog.cost_usd).label("cost"),
                func.sum(AIUsageLog.input_tokens).label("input_tokens"),
                func.sum(AIUsageLog.output_tokens).label("output_tokens"),
            )
            .join(AIUsageLog, AIUsageLog.client_id == Client.id)
            .group_by(Client.client_name)
            .all()
        )
    except Exception as e:
        logger.error(f"Database error in ai_usage_by_client: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable") from e

    return [
        {
            "client": r.client_name,
            "calls": r.calls,
            "cost_usd": float(r.cost or 0),
            "input_tokens": r.input_tokens or 0,
            "output_tokens": r.output_tokens or 0,
        }
        for r in results
    ]
