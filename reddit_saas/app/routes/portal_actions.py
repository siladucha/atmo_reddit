"""Client Portal Actions — rate-limited pipeline triggers for client_manager/client_admin.

Endpoints:
- POST /clients/{client_id}/actions/pipeline — trigger full pipeline
- POST /clients/{client_id}/actions/epg-rebuild — rebuild EPG
- POST /clients/{client_id}/actions/strategy/{avatar_id} — generate strategy
- POST /clients/{client_id}/actions/regenerate/{draft_id} — regenerate single draft
- GET  /clients/{client_id}/actions/status — get rate limit status for all actions
"""

from app.logging_config import get_logger
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.permissions import (
    get_current_user,
    verify_client_access_from_path,
)
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.user import User
from app.models.user_role import UserRole
from app.services.client_action_limiter import (
    check_rate_limit,
    get_action_status,
    log_action,
)

logger = get_logger(__name__)

router = APIRouter(
    dependencies=[Depends(verify_client_access_from_path)],
    tags=["client-portal-actions"],
)

# Roles allowed to trigger actions
TRIGGER_ROLES = (
    UserRole.owner,
    UserRole.partner,
    UserRole.client_admin,
    UserRole.client_manager,
)


def _require_trigger_role(user: User) -> None:
    """Raise 403 if user cannot trigger pipeline actions."""
    if user.user_role not in TRIGGER_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions to trigger actions")


# --- Status endpoint ---


@router.get("/clients/{client_id}/actions/status")
def portal_action_status(
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get rate limit status for all action types (for UI display)."""
    _require_trigger_role(user)

    statuses = {
        "pipeline": get_action_status(db, client_id, "pipeline"),
        "epg_rebuild": get_action_status(db, client_id, "epg_rebuild"),
        "discovery": get_action_status(db, client_id, "discovery"),
    }

    # Strategy: get per-avatar status
    avatars = (
        db.query(Avatar)
        .filter(Avatar.client_ids.any(str(client_id)), Avatar.active.is_(True))
        .all()
    )
    strategy_statuses = {}
    for avatar in avatars:
        strategy_statuses[str(avatar.id)] = get_action_status(
            db, client_id, "strategy", avatar_id=avatar.id
        )
    statuses["strategy"] = strategy_statuses

    return statuses


# --- Pipeline trigger ---


@router.post("/clients/{client_id}/actions/pipeline")
def portal_trigger_pipeline(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trigger full pipeline (scrape -> score -> generate) for this client.

    Rate limited: 2 per day per client.
    """
    _require_trigger_role(user)

    # Rate limit check
    limit = check_rate_limit(db, client_id, "pipeline")
    if not limit["allowed"]:
        retry_str = limit["retry_after"].strftime("%H:%M") if limit["retry_after"] else "later"
        return JSONResponse(
            status_code=429,
            content={
                "message": limit["message"],
                "retry_after": retry_str,
            },
            headers={
                "HX-Trigger": f'{{"showToast": {{"type": "warning", "message": "Limit reached. Next run available at {retry_str}"}}}}'
            },
        )

    # Verify client exists and is active
    client = db.query(Client).filter(Client.id == client_id, Client.is_active.is_(True)).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found or inactive")

    # Dispatch pipeline tasks
    try:
        from app.models.subreddit import Subreddit, ClientSubredditAssignment
        from app.tasks.scraping import scrape_subreddit_shared
        from app.tasks.ai_pipeline import score_threads, generate_comments

        assignments = (
            db.query(ClientSubredditAssignment)
            .join(Subreddit, Subreddit.id == ClientSubredditAssignment.subreddit_id)
            .filter(
                ClientSubredditAssignment.client_id == client_id,
                ClientSubredditAssignment.is_active.is_(True),
                Subreddit.is_active.is_(True),
            )
            .all()
        )

        # Dispatch scrape tasks
        for assignment in assignments:
            scrape_subreddit_shared.delay(str(assignment.subreddit_id))

        # Chain score -> generate (30s delay for scrapes)
        chain = (
            score_threads.si(str(client_id), triggered_by="client_portal")
            | generate_comments.si(str(client_id), triggered_by="client_portal")
        )
        chain.apply_async(countdown=30)

    except Exception as e:
        logger.error("Portal pipeline trigger failed for client %s: %s", client_id, e)
        raise HTTPException(status_code=503, detail="Task queue unavailable") from e

    # Log the action
    log_action(db, client_id, "pipeline", user.id)

    # Audit trail
    try:
        from app.services.audit import log_action as audit_log
        audit_log(
            db=db,
            user_id=user.id,
            action="pipeline_triggered",
            entity_type="client",
            entity_id=client_id,
            details={"source": "client_portal", "subreddits": len(assignments)},
        )
    except Exception:
        pass

    logger.info(
        "Portal: pipeline triggered | client=%s | user=%s | remaining=%s",
        client_id, user.email, limit["remaining"],
    )

    return HTMLResponse(
        content='<span class="text-green-400 text-sm">Pipeline queued</span>',
        headers={
            "HX-Trigger": '{"showToast": {"type": "success", "message": "Pipeline started. Fresh content in ~10 minutes."}}'
        },
    )


# --- EPG Rebuild ---


@router.post("/clients/{client_id}/actions/epg-rebuild")
def portal_trigger_epg_rebuild(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Rebuild EPG (daily publishing program) for this client's avatars.

    Rate limited: 1 per day per client.
    """
    _require_trigger_role(user)

    # Rate limit check
    limit = check_rate_limit(db, client_id, "epg_rebuild")
    if not limit["allowed"]:
        retry_str = limit["retry_after"].strftime("%H:%M") if limit["retry_after"] else "tomorrow"
        return JSONResponse(
            status_code=429,
            content={"message": limit["message"], "retry_after": retry_str},
            headers={
                "HX-Trigger": f'{{"showToast": {{"type": "warning", "message": "EPG already rebuilt today. Next available: {retry_str}"}}}}'
            },
        )

    # Get client's avatars
    avatars = (
        db.query(Avatar)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            Avatar.active.is_(True),
            Avatar.is_frozen.is_(False),
            Avatar.warming_phase > 0,
        )
        .all()
    )

    if not avatars:
        return JSONResponse(
            status_code=422,
            content={"message": "No eligible avatars for EPG rebuild"},
        )

    # Dispatch EPG tasks per avatar
    try:
        from app.services.epg import build_daily_epg
        from app.services.epg_executor import generate_all_planned_slots
        from app.services.portfolio_manager import build_portfolio
        from app.services.settings import get_setting

        epg2_enabled = get_setting(db, "epg2_enabled").lower() in ("true", "1")
        client = db.query(Client).filter(Client.id == client_id).first()

        total_planned = 0
        total_generated = 0

        for avatar in avatars:
            if avatar.health_status in ("shadowbanned", "suspended"):
                continue

            if epg2_enabled:
                epg = build_portfolio(db, avatar, client)
            else:
                epg = build_daily_epg(db, avatar, client)

            if epg.status in ("frozen", "excluded", "budget_exhausted"):
                continue

            planned_count = len(epg.hobby_slots) + len(epg.business_slots)
            total_planned += planned_count

            generated = generate_all_planned_slots(db, avatar.id)
            total_generated += generated

    except Exception as e:
        logger.error("Portal EPG rebuild failed for client %s: %s", client_id, e)
        raise HTTPException(status_code=503, detail="EPG rebuild failed") from e

    # Log the action
    log_action(db, client_id, "epg_rebuild", user.id)

    logger.info(
        "Portal: EPG rebuilt | client=%s | user=%s | planned=%d generated=%d",
        client_id, user.email, total_planned, total_generated,
    )

    return HTMLResponse(
        content=f'<span class="text-green-400 text-sm">EPG rebuilt: {total_generated} slots</span>',
        headers={
            "HX-Trigger": f'{{"showToast": {{"type": "success", "message": "EPG rebuilt: {total_generated} comments generated"}}}}'
        },
    )


# --- Strategy Generation ---


@router.post("/clients/{client_id}/actions/strategy/{avatar_id}")
def portal_trigger_strategy(
    request: Request,
    client_id: UUID,
    avatar_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a new strategy document for a specific avatar.

    Rate limited: 1 per week per avatar.
    """
    _require_trigger_role(user)

    # Verify avatar belongs to client
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar or str(client_id) not in (avatar.client_ids or []):
        raise HTTPException(status_code=404, detail="Avatar not found")

    # Rate limit check (per-avatar)
    limit = check_rate_limit(db, client_id, "strategy", avatar_id=avatar_id)
    if not limit["allowed"]:
        return JSONResponse(
            status_code=429,
            content={"message": limit["message"]},
            headers={
                "HX-Trigger": '{"showToast": {"type": "warning", "message": "Strategy already generated this week for this avatar"}}'
            },
        )

    # Dispatch strategy generation
    try:
        from app.tasks.strategy import generate_strategy_async

        task = generate_strategy_async.delay(str(avatar_id), str(client_id), str(user.id))
    except Exception as e:
        logger.error("Portal strategy trigger failed for avatar %s: %s", avatar_id, e)
        raise HTTPException(status_code=503, detail="Task queue unavailable") from e

    # Log the action
    log_action(db, client_id, "strategy", user.id, avatar_id=avatar_id)

    logger.info(
        "Portal: strategy triggered | avatar=%s | client=%s | user=%s",
        avatar.reddit_username, client_id, user.email,
    )

    return HTMLResponse(
        content='<span class="text-green-400 text-sm">Strategy generation started</span>',
        headers={
            "HX-Trigger": '{"showToast": {"type": "success", "message": "Strategy generation started. Ready in ~2 minutes."}}'
        },
    )


# --- Draft Regeneration ---


@router.post("/clients/{client_id}/actions/regenerate/{draft_id}")
async def portal_regenerate_draft(
    request: Request,
    client_id: UUID,
    draft_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    note: str = Form(""),
):
    """Regenerate a single comment draft (new LLM call with learning context).

    No rate limit (single call ~$0.04). Old draft marked as 'regenerated'.
    """
    _require_trigger_role(user)

    # Load draft
    draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    # Verify ownership
    avatar = db.query(Avatar).filter(Avatar.id == draft.avatar_id).first()
    if not avatar or str(client_id) not in (avatar.client_ids or []):
        raise HTTPException(status_code=404, detail="Draft not found")

    # Only pending drafts can be regenerated
    if draft.status != "pending":
        return JSONResponse(
            status_code=422,
            content={"message": "Only pending drafts can be regenerated"},
        )

    # Load thread
    from app.models.thread import RedditThread
    thread = db.query(RedditThread).filter(RedditThread.id == draft.thread_id).first() if draft.thread_id else None
    if not thread:
        return JSONResponse(
            status_code=422,
            content={"message": "Thread not found for regeneration"},
        )

    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Generate new comment
    try:
        from app.services.generation import generate_comment

        # Build persona_selection context (minimal)
        persona_selection = {
            "avatar_id": str(avatar.id),
            "username": avatar.reddit_username,
            "voice_profile": avatar.voice_profile_md or "",
            "reason": note.strip() if note.strip() else "regenerated by client",
        }

        # Mark old draft as regenerated
        draft.status = "regenerated"
        db.commit()

        # Generate new draft
        new_draft = generate_comment(
            db=db,
            thread=thread,
            client=client,
            avatar=avatar,
            persona_selection=persona_selection,
        )

    except Exception as e:
        # Revert old draft status on failure
        draft.status = "pending"
        db.commit()
        logger.error("Portal regeneration failed for draft %s: %s", draft_id, e)
        return JSONResponse(
            status_code=500,
            content={"message": "Regeneration failed. Please try again."},
            headers={
                "HX-Trigger": '{"showToast": {"type": "error", "message": "Regeneration failed"}}'
            },
        )

    # Log action (for analytics, no rate limit)
    log_action(db, client_id, "regenerate", user.id, avatar_id=avatar.id)

    logger.info(
        "Portal: draft regenerated | old=%s new=%s | user=%s",
        draft_id, new_draft.id, user.email,
    )

    return HTMLResponse(
        content='<span class="text-green-400 text-sm">Regenerated</span>',
        headers={
            "HX-Trigger": '{"showToast": {"type": "success", "message": "New draft generated. Refresh to see it."}, "refreshDrafts": true}'
        },
    )
