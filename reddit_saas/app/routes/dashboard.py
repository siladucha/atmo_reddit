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


@router.get("/trace/{draft_id}")
def trace_comment_chain(
    draft_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Full traceability: reconstruct the entire reasoning chain for a comment.

    Returns the complete lifecycle: Discovery → Strategy → EPG → Draft →
    Posting → KarmaSnapshots → Feedback adjustments.

    Satisfies: "A human operator must be able to reconstruct the full
    reasoning chain at any time."
    """
    from uuid import UUID as UUIDType
    from app.services.traceability import trace_comment_json

    try:
        draft_uuid = UUIDType(draft_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid draft ID format")

    result = trace_comment_json(db, draft_uuid)

    if not result.get("chain"):
        raise HTTPException(status_code=404, detail="Draft not found or no trace data")

    return result


@router.get("/feedback/{avatar_id}")
def get_avatar_feedback(
    avatar_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
):
    """Get outcome feedback packet for an avatar.

    Returns the full feedback analysis: subreddit signals, approach effectiveness,
    EPG adjustments, hypothesis confidence updates.
    """
    from uuid import UUID as UUIDType
    from app.services.outcome_analysis import compute_avatar_outcome_profile
    from app.services.feedback_loop import get_all_epg_adjustments, get_performance_context

    try:
        avatar_uuid = UUIDType(avatar_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid avatar ID format")

    profile = compute_avatar_outcome_profile(db, avatar_uuid)
    adjustments = get_all_epg_adjustments(db, avatar_uuid)
    perf_ctx = get_performance_context(db, avatar_uuid)

    return {
        "avatar_id": avatar_id,
        "outcome_profile": {
            "total_posted": profile.total_posted,
            "total_karma": profile.total_karma,
            "avg_karma": round(profile.avg_karma, 1),
            "removal_rate": round(profile.removal_rate, 3),
            "avg_reply_count": round(profile.avg_reply_count, 1),
            "karma_velocity": round(profile.karma_velocity, 1),
            "top_subreddits": profile.top_performing_subreddits,
            "underperforming_subreddits": profile.underperforming_subreddits,
        },
        "subreddit_signals": [
            {
                "subreddit": s.subreddit,
                "total_comments": s.total_comments,
                "avg_karma": round(s.avg_karma, 1),
                "removal_rate": round(s.removal_rate, 3),
                "avg_reply_count": round(s.avg_reply_count, 1),
                "karma_trend": round(s.karma_trend, 3),
                "recommendation": s.recommendation,
                "confidence": round(s.confidence, 2),
            }
            for s in profile.subreddit_signals
        ],
        "approach_signals": [
            {
                "approach": s.approach,
                "total_comments": s.total_comments,
                "avg_karma": round(s.avg_karma, 1),
                "removal_rate": round(s.removal_rate, 3),
            }
            for s in profile.approach_signals
        ],
        "epg_adjustments": adjustments,
        "performance_context": perf_ctx,
    }
