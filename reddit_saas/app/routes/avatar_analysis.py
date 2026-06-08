"""Avatar behavioral analysis REST endpoint."""

from app.logging_config import get_logger
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_superuser
from app.models.avatar import Avatar
from app.models.user import User
from app.schemas.avatar_analysis import (
    AnalysisEditSubmission,
    AvatarAnalysisRequest,
    BehavioralProfile,
    AnalysisErrorResponse,
)
from app.services.avatar_analysis import AnalysisError, analyze_avatar
from app.services.learning_loop import store_edit

logger = get_logger(__name__)

router = APIRouter(prefix="/api/avatars")


@router.post("/{avatar_id}/analyze", response_model=BehavioralProfile)
def analyze_avatar_endpoint(
    avatar_id: UUID,
    request: AvatarAnalysisRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
) -> BehavioralProfile:
    """Run LLM-based behavioral analysis for an avatar.

    Returns a structured BehavioralProfile on success.
    - 404 if avatar not found
    - 422 on validation error
    - 502 if all analysis attempts fail
    """
    # Verify avatar exists
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    try:
        profile = analyze_avatar(db, avatar_id, request)
        return profile
    except AnalysisError as e:
        logger.error(
            "AVATAR_ANALYSIS | action=endpoint_failure | avatar_id=%s | "
            "attempts=%d | reason=%s",
            avatar_id, e.attempts, e.last_failure_reason,
        )
        error_response = AnalysisErrorResponse(
            error="All analysis attempts failed",
            attempts=e.attempts,
            last_failure_reason=e.last_failure_reason,
        )
        raise HTTPException(
            status_code=502,
            detail=error_response.model_dump(),
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=422,
            detail=e.errors(),
        )


@router.post("/{avatar_id}/analysis-edits", status_code=201)
def submit_analysis_edit(
    avatar_id: UUID,
    edit: AnalysisEditSubmission,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_superuser),
) -> dict:
    """Submit a human edit to an LLM-generated analysis.

    Returns 201 on success, 404 if avatar not found, 422 if no changes detected.
    """
    # Verify avatar exists
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")

    try:
        record = store_edit(db, avatar_id, edit.llm_output, edit.human_edited)
    except ValueError:
        raise HTTPException(status_code=422, detail="No changes detected")

    return {"status": "stored", "id": str(record.id)}
