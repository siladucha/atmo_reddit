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
from app.dependencies.permission_guard import (
    require_permission,
    PermissionRequiresApproval,
)
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.user import User
from app.services.action_request import create_action_request
from app.services.client_action_limiter import (
    check_rate_limit,
    get_action_status,
    log_action,
)
from app.services.trial_guard import is_trial_expired

logger = get_logger(__name__)


def _check_trial_not_expired_actions(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Block portal actions for expired trial clients."""
    if not user.client_id:
        return
    client = db.query(Client).filter(Client.id == user.client_id).first()
    if client and is_trial_expired(client):
        raise HTTPException(
            status_code=403,
            detail="Trial expired. Please upgrade to continue using RAMP.",
        )


router = APIRouter(
    dependencies=[Depends(verify_client_access_from_path), Depends(_check_trial_not_expired_actions)],
    tags=["client-portal-actions"],
)


# --- Status endpoint ---


@router.get("/clients/{client_id}/actions/status")
def portal_action_status(
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get rate limit status for all action types (for UI display)."""
    # Status view: accessible to anyone who can access the client portal
    # (router-level verify_client_access_from_path covers this)

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
    user: User = Depends(require_permission("trigger_pipeline")),
    db: Session = Depends(get_db),
):
    """Trigger full pipeline (scrape -> score -> generate) for this client.

    Rate limited: 2 per day per client.
    """

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

    # Trial signal: pipeline triggered (engagement)
    try:
        from app.services.trial_signal_hooks import record_trial_signal_background
        record_trial_signal_background(
            client_id=client_id,
            signal_type="pipeline_triggered",
            signal_category="engagement",
            signal_value={"source": "portal"},
        )
    except Exception:
        pass


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
    user: User = Depends(require_permission("trigger_epg_rebuild")),
    db: Session = Depends(get_db),
):
    """Rebuild EPG (daily publishing program) for this client's avatars.

    Rate limited: 1 per day per client.
    """

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


    # Trial signal: EPG rebuilt (engagement)
    try:
        from app.services.trial_signal_hooks import record_trial_signal_background
        record_trial_signal_background(
            client_id=client_id,
            signal_type="epg_rebuilt",
            signal_category="engagement",
            signal_value={"slots_generated": total_generated},
        )
    except Exception:
        pass

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
    user: User = Depends(require_permission("trigger_strategy")),
    db: Session = Depends(get_db),
):
    """Generate a new strategy document for a specific avatar.

    Rate limited: 1 per week per avatar.
    """

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


    # Trial signal: strategy requested (value_realization)
    try:
        from app.services.trial_signal_hooks import record_trial_signal_background
        record_trial_signal_background(
            client_id=client_id,
            signal_type="strategy_requested",
            signal_category="value_realization",
            signal_value={"avatar_id": str(avatar_id)},
        )
    except Exception:
        pass

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
    user: User = Depends(require_permission("regenerate_draft")),
    db: Session = Depends(get_db),
    note: str = Form(""),
):
    """Regenerate a single comment draft (new LLM call with learning context).

    No rate limit (single call ~$0.04). Old draft marked as 'regenerated'.
    """

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

    # Load thread (professional) or hobby post
    from app.models.thread import RedditThread
    from app.models.hobby import HobbySubreddit

    thread = None
    hobby_post = None

    if draft.thread_id:
        thread = db.query(RedditThread).filter(RedditThread.id == draft.thread_id).first()
    elif draft.hobby_post_id:
        hobby_post = db.query(HobbySubreddit).filter(HobbySubreddit.id == draft.hobby_post_id).first()

    if not thread and not hobby_post:
        return JSONResponse(
            status_code=422,
            content={"message": "Thread not found for regeneration"},
        )

    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Generate new comment
    try:
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

        if thread:
            # Professional draft — use full generation service
            from app.services.generation import generate_comment

            new_draft = generate_comment(
                db=db,
                thread=thread,
                client=client,
                avatar=avatar,
                persona_selection=persona_selection,
            )
        else:
            # Hobby draft — generate inline (same as ai_pipeline hobby flow)
            from app.services.ai import call_llm, log_ai_usage
            from app.config import get_config
            from app.tasks.ai_pipeline import _build_hobby_system_prompt, _build_hobby_user_prompt
            import json as json_mod
            import uuid as uuid_mod

            # --- Self-Learning Loop: retrieve learning context ---
            learning_context = ""
            learning_metadata = None
            try:
                from app.services.learning import LearningService
                learning_service = LearningService()

                examples = learning_service.select_few_shot_examples(
                    db,
                    avatar_id=avatar.id,
                    client_id=client_id,
                    subreddit=hobby_post.subreddit if hasattr(hobby_post, "subreddit") else "",
                    engagement_mode="hobby_engagement",
                )
                patterns = learning_service.get_correction_patterns(
                    db, avatar_id=avatar.id, client_id=client_id
                )

                if examples or patterns:
                    learning_context = learning_service.format_learning_context(examples, patterns)
                    learning_metadata = {
                        "edit_record_ids": [str(ex.id) for ex in examples],
                        "correction_patterns": [p.rule_text for p in patterns],
                        "learning_token_count": len(learning_context) // 4,
                    }
            except Exception:
                logger.warning("Learning context failed for hobby regeneration — proceeding without")

            system_prompt = _build_hobby_system_prompt(avatar, [])
            if learning_context:
                system_prompt = system_prompt + "\n\n" + learning_context

            user_prompt = _build_hobby_user_prompt(hobby_post)

            gen_model = get_config("llm_scoring_model") or get_config("llm_generation_model")

            result = call_llm(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=gen_model,
                temperature=0.85,
                max_tokens=300,
            )

            log_ai_usage(
                db, str(client_id), "hobby_comment_workflow", result,
                avatar_id=str(avatar.id),
                subreddit_name=hobby_post.subreddit if hasattr(hobby_post, "subreddit") else None,
            )

            content = result["content"].strip()
            try:
                parsed = json_mod.loads(content)
                comment_text = parsed.get("comment", content)
            except (json_mod.JSONDecodeError, TypeError):
                comment_text = content

            # Create new draft
            new_draft = CommentDraft(
                id=uuid_mod.uuid4(),
                thread_id=None,
                hobby_post_id=hobby_post.id,
                avatar_id=avatar.id,
                client_id=client_id,
                type="hobby",
                ai_draft=comment_text,
                status="pending",
                comment_approach="hobby_engagement",
                learning_metadata=learning_metadata,
            )
            db.add(new_draft)
            db.commit()

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


# --- Keyword Management (Self-Service) ---


@router.post("/clients/{client_id}/actions/keywords/add")
async def portal_add_keyword(
    request: Request,
    client_id: UUID,
    user: User = Depends(require_permission("add_keyword")),
    db: Session = Depends(get_db),
    keyword: str = Form(...),
    priority: str = Form("medium"),
):
    """Add a keyword to the client's keyword list (self-service).

    Permission guard handles role/tier checks. Self-service tier executes immediately.
    """
    from sqlalchemy.orm.attributes import flag_modified

    client_obj = db.query(Client).filter(Client.id == client_id).first()
    if not client_obj:
        raise HTTPException(status_code=404, detail="Client not found")

    keyword = keyword.strip()
    if not keyword:
        return HTMLResponse(
            '<span class="text-red-400 text-sm">Keyword cannot be empty</span>',
            status_code=422,
        )
    if priority not in ("high", "medium", "low"):
        return HTMLResponse(
            '<span class="text-red-400 text-sm">Invalid priority</span>',
            status_code=422,
        )

    # Plan limit check — keywords
    from app.services.plan_limits import check_keyword_limit
    allowed, limit_msg, _current, _limit = check_keyword_limit(db, client_id)
    if not allowed:
        return HTMLResponse(
            f'<span class="text-red-400 text-sm">{limit_msg}</span>',
            status_code=400,
            headers={"HX-Trigger": '{"showToast": {"type": "error", "message": "' + limit_msg + '"}}'},
        )

    # Duplicate check
    keywords = client_obj.keywords or {}
    all_existing = []
    for p in ("high", "medium", "low"):
        all_existing.extend([k.lower() for k in keywords.get(p, [])])
    if keyword.lower() in all_existing:
        return HTMLResponse(
            '<span class="text-yellow-400 text-sm">Keyword already exists</span>',
            status_code=409,
        )

    # Add keyword
    if priority not in keywords:
        keywords[priority] = []
    keywords[priority].append(keyword)
    client_obj.keywords = keywords
    flag_modified(client_obj, "keywords")
    db.commit()

    logger.info("Portal: keyword added | client=%s | keyword=%s | user=%s", client_id, keyword, user.email)

    return HTMLResponse(
        content='<span class="text-green-400 text-sm">Keyword added</span>',
        headers={
            "HX-Trigger": '{"showToast": {"type": "success", "message": "Keyword added"}}'
        },
    )


@router.post("/clients/{client_id}/actions/keywords/remove")
async def portal_remove_keyword(
    request: Request,
    client_id: UUID,
    user: User = Depends(require_permission("remove_keyword")),
    db: Session = Depends(get_db),
    keyword: str = Form(...),
    priority: str = Form(...),
):
    """Remove a keyword from the client's keyword list (self-service).

    Permission guard handles role/tier checks. Self-service tier executes immediately.
    """
    from sqlalchemy.orm.attributes import flag_modified

    client_obj = db.query(Client).filter(Client.id == client_id).first()
    if not client_obj:
        raise HTTPException(status_code=404, detail="Client not found")

    keywords = client_obj.keywords or {}
    if priority in keywords and keyword in keywords[priority]:
        keywords[priority].remove(keyword)
        client_obj.keywords = keywords
        flag_modified(client_obj, "keywords")
        db.commit()

    logger.info("Portal: keyword removed | client=%s | keyword=%s | user=%s", client_id, keyword, user.email)

    return HTMLResponse(
        content='<span class="text-green-400 text-sm">Keyword removed</span>',
        headers={
            "HX-Trigger": '{"showToast": {"type": "success", "message": "Keyword removed"}}'
        },
    )


# --- Subreddit Management (Approval-Tier) ---


@router.post("/clients/{client_id}/actions/subreddits/add")
async def portal_add_subreddit(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    subreddit_name: str = Form(...),
):
    """Add a subreddit to the client's list.

    Default tier: approval_required — creates an ActionRequest.
    If overridden to self_service, executes immediately.
    """
    subreddit_name = subreddit_name.strip()
    if subreddit_name.startswith("r/"):
        subreddit_name = subreddit_name[2:]
    subreddit_name = subreddit_name.strip()

    if not subreddit_name:
        return HTMLResponse(
            '<span class="text-red-400 text-sm">Subreddit name cannot be empty</span>',
            status_code=422,
        )

    # Manual permission check (approval-tier needs to create request)
    try:
        guard = require_permission("add_subreddit")
        await guard(request=request, user=user, db=db)
    except PermissionRequiresApproval as e:
        ar = create_action_request(
            db=db,
            client_id=e.client_id,
            user_id=e.user.id,
            action_type=e.action_id,
            payload={"subreddit_name": subreddit_name},
        )
        if ar is None:
            return HTMLResponse(
                '<span class="text-yellow-400 text-sm">Request already pending</span>',
                status_code=409,
            )
        db.commit()
        return HTMLResponse(
            '<span class="text-yellow-400 text-sm">Request submitted for approval</span>',
            headers={
                "HX-Trigger": '{"showToast": {"type": "info", "message": "Subreddit request submitted for approval"}}'
            },
        )

    # Self-service: execute immediately (create subreddit assignment)
    from app.models.subreddit import Subreddit, ClientSubredditAssignment

    # Plan limit check — subreddits
    from app.services.plan_limits import check_subreddit_limit
    allowed, limit_msg, _current, _limit = check_subreddit_limit(db, client_id)
    if not allowed:
        return HTMLResponse(
            f'<span class="text-red-400 text-sm">{limit_msg}</span>',
            status_code=400,
            headers={"HX-Trigger": '{"showToast": {"type": "error", "message": "' + limit_msg + '"}}'},
        )

    # Find or create subreddit
    subreddit = db.query(Subreddit).filter(
        Subreddit.subreddit_name.ilike(subreddit_name)
    ).first()
    if not subreddit:
        subreddit = Subreddit(subreddit_name=subreddit_name, is_active=True)
        db.add(subreddit)
        db.flush()

    # Check if assignment already exists
    existing = db.query(ClientSubredditAssignment).filter(
        ClientSubredditAssignment.client_id == client_id,
        ClientSubredditAssignment.subreddit_id == subreddit.id,
    ).first()
    if existing:
        if not existing.is_active:
            existing.is_active = True
            db.commit()
            return HTMLResponse(
                '<span class="text-green-400 text-sm">Subreddit re-activated</span>',
                headers={
                    "HX-Trigger": '{"showToast": {"type": "success", "message": "Subreddit added"}}'
                },
            )
        return HTMLResponse(
            '<span class="text-yellow-400 text-sm">Subreddit already assigned</span>',
            status_code=409,
        )

    assignment = ClientSubredditAssignment(
        client_id=client_id,
        subreddit_id=subreddit.id,
        is_active=True,
    )
    db.add(assignment)
    db.commit()

    logger.info("Portal: subreddit added | client=%s | sub=%s | user=%s", client_id, subreddit_name, user.email)

    return HTMLResponse(
        content='<span class="text-green-400 text-sm">Subreddit added</span>',
        headers={
            "HX-Trigger": '{"showToast": {"type": "success", "message": "Subreddit added"}}'
        },
    )


@router.post("/clients/{client_id}/actions/subreddits/remove")
async def portal_remove_subreddit(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    subreddit_name: str = Form(...),
):
    """Remove a subreddit from the client's list.

    Default tier: approval_required — creates an ActionRequest.
    If overridden to self_service, executes immediately.
    """
    subreddit_name = subreddit_name.strip()
    if subreddit_name.startswith("r/"):
        subreddit_name = subreddit_name[2:]
    subreddit_name = subreddit_name.strip()

    if not subreddit_name:
        return HTMLResponse(
            '<span class="text-red-400 text-sm">Subreddit name cannot be empty</span>',
            status_code=422,
        )

    # Manual permission check (approval-tier needs to create request)
    try:
        guard = require_permission("remove_subreddit")
        await guard(request=request, user=user, db=db)
    except PermissionRequiresApproval as e:
        ar = create_action_request(
            db=db,
            client_id=e.client_id,
            user_id=e.user.id,
            action_type=e.action_id,
            payload={"subreddit_name": subreddit_name},
        )
        if ar is None:
            return HTMLResponse(
                '<span class="text-yellow-400 text-sm">Request already pending</span>',
                status_code=409,
            )
        db.commit()
        return HTMLResponse(
            '<span class="text-yellow-400 text-sm">Request submitted for approval</span>',
            headers={
                "HX-Trigger": '{"showToast": {"type": "info", "message": "Subreddit removal request submitted for approval"}}'
            },
        )

    # Self-service: execute immediately (deactivate assignment)
    from app.models.subreddit import Subreddit, ClientSubredditAssignment

    subreddit = db.query(Subreddit).filter(
        Subreddit.subreddit_name.ilike(subreddit_name)
    ).first()
    if not subreddit:
        return HTMLResponse(
            '<span class="text-red-400 text-sm">Subreddit not found</span>',
            status_code=404,
        )

    assignment = db.query(ClientSubredditAssignment).filter(
        ClientSubredditAssignment.client_id == client_id,
        ClientSubredditAssignment.subreddit_id == subreddit.id,
        ClientSubredditAssignment.is_active.is_(True),
    ).first()
    if not assignment:
        return HTMLResponse(
            '<span class="text-yellow-400 text-sm">Subreddit not assigned to this client</span>',
            status_code=404,
        )

    assignment.is_active = False
    db.commit()

    logger.info("Portal: subreddit removed | client=%s | sub=%s | user=%s", client_id, subreddit_name, user.email)

    return HTMLResponse(
        content='<span class="text-green-400 text-sm">Subreddit removed</span>',
        headers={
            "HX-Trigger": '{"showToast": {"type": "success", "message": "Subreddit removed"}}'
        },
    )
