"""Avatar Onboarding Routes — analyze Reddit profile + AI classification + approval.

Accessible to: owner, partner, client_admin, client_manager (with client access guard).
Entry points:
- From admin panel: /admin/avatar-onboard/{client_id}
- From client portal: /clients/{client_id}/avatar-onboard

Flow:
1. User enters Reddit username
2. System fetches Reddit profile (PRAW) + runs AI classification (Claude)
3. Shows pre-filled card: classification, voice, strategy, display_name, persona_bio
4. User edits inline → approves
5. Avatar created + assigned to client + pipeline triggered
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.permissions import get_current_user, verify_client_access_from_path
from app.logging_config import get_logger
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.user import User
from app.models.user_role import UserRole

logger = get_logger(__name__)

router = APIRouter(tags=["avatar-onboard"])

# Use direct Jinja2 Environment (same pattern as onboarding.py)
from jinja2 import Environment, FileSystemLoader

_jinja_env = Environment(loader=FileSystemLoader("app/templates"), autoescape=True)

from app.version import __version__ as app_version

_jinja_env.globals["app_version"] = app_version

from app.template_filters import register_filters

register_filters(_jinja_env)


def _render(template_name: str, **context) -> HTMLResponse:
    """Render template using direct Jinja2 (bypass Starlette cache bug)."""
    tmpl = _jinja_env.get_template(template_name)
    html = tmpl.render(**context)
    return HTMLResponse(content=html)


def _require_avatar_onboard_access(user: User) -> None:
    """Check that user has permission to onboard avatars.

    Allowed: owner, partner, avatar_manager, client_admin, client_manager.
    """
    allowed_roles = (
        UserRole.owner,
        UserRole.partner,
        UserRole.avatar_manager,
        UserRole.client_admin,
        UserRole.client_manager,
    )
    if user.user_role not in allowed_roles and not user.is_superuser:
        raise HTTPException(status_code=403, detail="Access Denied")


def _get_client_with_access(client_id: uuid.UUID, user: User, db: Session) -> Client:
    """Load client and verify user has access to it."""
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Platform-level roles can access any client
    if user.user_role in (UserRole.owner, UserRole.partner, UserRole.avatar_manager):
        return client
    if user.is_superuser:
        return client

    # Client-scoped roles must match
    if user.client_id != client_id:
        raise HTTPException(status_code=403, detail="Access Denied")

    return client


def _check_trial_limit(client: Client, db: Session) -> str | None:
    """Check if trial client already has max avatars. Returns error or None."""
    if client.plan_type != "trial":
        return None

    # Trial = max 1 avatar
    existing_count = (
        db.query(Avatar)
        .filter(Avatar.client_ids.any(str(client.id)), Avatar.active.is_(True))
        .count()
    )
    if existing_count >= 1:
        return "Trial accounts are limited to 1 voice. Upgrade to add more."
    return None


# ---------------------------------------------------------------------------
# Entry: GET — show the username input form
# ---------------------------------------------------------------------------


@router.get("/clients/{client_id}/avatar-onboard", response_class=HTMLResponse)
def avatar_onboard_start(
    request: Request,
    client_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Show avatar onboarding start page — username input."""
    _require_avatar_onboard_access(user)
    client = _get_client_with_access(client_id, user, db)

    trial_error = _check_trial_limit(client, db)

    # Count existing avatars for context
    existing_avatars = (
        db.query(Avatar)
        .filter(Avatar.client_ids.any(str(client.id)), Avatar.active.is_(True))
        .count()
    )

    return _render(
        "avatar_onboard/start.html",
        request=request,
        client=client,
        client_id=str(client_id),
        existing_avatars=existing_avatars,
        trial_error=trial_error,
        user_role=user.user_role.value,
        is_portal=user.user_role.is_client_scoped,
    )


# ---------------------------------------------------------------------------
# HTMX: POST — analyze Reddit username (fetch + AI)
# ---------------------------------------------------------------------------


@router.post("/clients/{client_id}/avatar-onboard/analyze", response_class=HTMLResponse)
def avatar_onboard_analyze(
    request: Request,
    client_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    reddit_username: str = Form(...),
):
    """HTMX endpoint: fetch Reddit profile + run AI analysis, return editable card."""
    _require_avatar_onboard_access(user)
    client = _get_client_with_access(client_id, user, db)

    trial_error = _check_trial_limit(client, db)
    if trial_error:
        return HTMLResponse(
            f'<div class="surface" style="padding:16px;border:1px solid var(--color-red);border-radius:8px;">'
            f'<p style="color:var(--color-red);">{trial_error}</p></div>'
        )

    # Clean username
    username = reddit_username.strip().replace("u/", "").replace("/u/", "")
    if not username:
        return HTMLResponse(
            '<p style="color:var(--color-red);font-size:var(--text-small);">Please enter a username</p>'
        )

    # Check if avatar already exists in system
    existing = db.query(Avatar).filter(Avatar.reddit_username == username).first()
    if existing:
        # Already exists — check if assigned to this client
        if existing.client_ids and str(client_id) in existing.client_ids:
            return HTMLResponse(
                f'<div class="surface" style="padding:16px;border:1px solid var(--color-orange);border-radius:8px;">'
                f'<p style="color:var(--color-orange);">u/{username} is already assigned to this client.</p></div>'
            )
        else:
            return HTMLResponse(
                f'<div class="surface" style="padding:16px;border:1px solid var(--color-orange);border-radius:8px;">'
                f'<p style="color:var(--color-orange);">u/{username} already exists in the system. '
                f'Contact admin to reassign.</p></div>'
            )

    # Run full analysis
    from app.services.avatar_onboard_analysis import run_avatar_onboard_analysis

    result = run_avatar_onboard_analysis(username, client=client, db=db)

    if result.get("error"):
        return HTMLResponse(
            f'<div class="surface" style="padding:16px;border:1px solid var(--color-red);border-radius:8px;">'
            f'<p style="color:var(--color-red);">Analysis failed: {result["error"]}</p>'
            f'<p style="color:var(--color-muted);font-size:var(--text-small);margin-top:8px;">'
            f'Check that the username is correct and the account is not suspended.</p></div>'
        )

    profile = result["profile"]
    analysis = result["analysis"]["data"]

    # --- Compatibility check: run emotional profile scoring for suggested subreddits ---
    compatibility_warnings = []
    try:
        from app.services.emotional_profile import get_avatar_compatibility_context
        from app.models.subreddit import Subreddit
        from sqlalchemy import func as sa_func

        # Collect all suggested subreddits from AI analysis
        suggested_subs = []
        if analysis.get("subreddits"):
            suggested_subs.extend(analysis["subreddits"].get("hobby", []))
            suggested_subs.extend(analysis["subreddits"].get("business", []))

        for sub_name in suggested_subs:
            sub_name_clean = sub_name.strip().lower().replace("r/", "")
            if not sub_name_clean:
                continue

            # Check if subreddit has an emotional profile
            subreddit = (
                db.query(Subreddit)
                .filter(sa_func.lower(Subreddit.subreddit_name) == sub_name_clean)
                .first()
            )
            if subreddit and subreddit.emotional_profile:
                profile_data = subreddit.emotional_profile
                punished = profile_data.get("punished_tones", [])
                temperament = profile_data.get("community_temperament", "")
                formality = profile_data.get("formality_level", "moderate")

                # Simple heuristic check (without full LLM call):
                # Flag if community punishes promotional/marketing tones
                risky_tones = [t for t in punished if any(
                    kw in t.get("name", "").lower() or kw in t.get("description", "").lower()
                    for kw in ["promot", "market", "sell", "advert", "shill", "spam"]
                )]
                if risky_tones:
                    compatibility_warnings.append({
                        "subreddit": sub_name_clean,
                        "warning": f"Community punishes: {risky_tones[0].get('name', 'promotional content')}",
                        "severity": "high",
                    })
                elif formality == "formal" and profile_data.get("humor_tolerance") == "none":
                    compatibility_warnings.append({
                        "subreddit": sub_name_clean,
                        "warning": "Very formal community — no humor or casual tone allowed",
                        "severity": "medium",
                    })
    except Exception as e:
        logger.warning("Compatibility check during onboarding failed: %s", e)

    # Render the editable approval card
    return _render(
        "avatar_onboard/analysis_card.html",
        request=request,
        client_id=str(client_id),
        username=username,
        profile=profile,
        analysis=analysis,
        cost_usd=result["analysis"].get("cost_usd", 0),
        duration_ms=result["analysis"].get("duration_ms", 0),
        compatibility_warnings=compatibility_warnings,
    )


# ---------------------------------------------------------------------------
# POST — approve and create avatar
# ---------------------------------------------------------------------------


@router.post("/clients/{client_id}/avatar-onboard/approve", response_class=HTMLResponse)
def avatar_onboard_approve(
    request: Request,
    client_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    # Avatar fields (editable by user)
    reddit_username: str = Form(...),
    display_name: str = Form(""),
    persona_bio: str = Form(""),
    voice_profile_md: str = Form(""),
    tone_principles: str = Form(""),
    hill_i_die_on: str = Form(""),
    helpful_mode_topics: str = Form(""),
    constraints: str = Form(""),
    hobby_subreddits: str = Form(""),
    business_subreddits: str = Form(""),
    suggested_phase: int = Form(1),
    # Classification metadata
    avatar_type: str = Form(""),
    synthetic_likelihood: int = Form(0),
):
    """Approve AI analysis and create avatar."""
    _require_avatar_onboard_access(user)
    client = _get_client_with_access(client_id, user, db)

    trial_error = _check_trial_limit(client, db)
    if trial_error:
        raise HTTPException(status_code=400, detail=trial_error)

    username = reddit_username.strip().replace("u/", "").replace("/u/", "")

    # Double-check uniqueness
    existing = db.query(Avatar).filter(Avatar.reddit_username == username).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Avatar u/{username} already exists")

    # Parse subreddit lists
    hobby_list = [s.strip() for s in hobby_subreddits.split(",") if s.strip()]
    business_list = [s.strip() for s in business_subreddits.split(",") if s.strip()]

    # Create avatar
    # Determine initial phase: Phase 0 (Incubation) for fresh accounts,
    # Phase 1 for pre-warmed accounts with existing karma
    from app.services.settings import get_setting
    incubation_enabled = get_setting(db, "incubation_phase_enabled") == "true"
    initial_phase = 1  # Default: skip incubation
    if incubation_enabled:
        # Check if account is fresh (low karma + young)
        reddit_karma = 0  # Will be updated on first health check
        # We don't have karma at creation time from the form — assign Phase 0
        # only for avatars explicitly marked as fresh, or default to Phase 1
        # TODO: fetch karma from PRAW during onboarding to make this smarter
        # For now: if display_name suggests it's a fresh import, use Phase 0
        # Conservative default: Phase 1 (pre-warmed assumed)
        pass

    avatar = Avatar(
        id=uuid.uuid4(),
        reddit_username=username,
        display_name=display_name.strip() or None,
        persona_bio=persona_bio.strip() or None,
        voice_profile_md=voice_profile_md.strip() or None,
        tone_principles=tone_principles.strip() or None,
        hill_i_die_on=hill_i_die_on.strip() or None,
        helpful_mode_topics=helpful_mode_topics.strip() or None,
        constraints=constraints.strip() or None,
        hobby_subreddits=hobby_list if hobby_list else None,
        business_subreddits=[{"subreddit": s, "source": "onboarding"} for s in business_list] if business_list else None,
        client_ids=[str(client_id)],
        active=True,
        warming_phase=initial_phase,
        health_status="unknown",
        posting_mode="disabled",
        pool="b2b",
    )
    db.add(avatar)
    db.flush()

    # Audit log
    from app.services.audit import log_action

    log_action(
        db=db,
        user_id=user.id,
        action="avatar_onboarded",
        entity_type="avatar",
        entity_id=avatar.id,
        client_id=client_id,
        details={
            "reddit_username": username,
            "display_name": display_name,
            "suggested_phase": suggested_phase,
            "avatar_type": avatar_type,
            "synthetic_likelihood": synthetic_likelihood,
            "created_by_role": user.user_role.value,
        },
    )

    # Activity event
    try:
        from app.services.transparency import record_activity_event

        record_activity_event(
            db=db,
            client_id=str(client_id),
            event_type="avatar_onboarded",
            description=f"Avatar '{display_name or username}' onboarded for {client.client_name}",
            details={
                "avatar_id": str(avatar.id),
                "reddit_username": username,
                "phase": suggested_phase,
                "created_by": user.email,
            },
        )
    except Exception as e:
        logger.warning("Activity event failed: %s", e)

    db.commit()

    # Plan activation route (Risk-Aware Activation)
    try:
        from app.services.activation_router import ActivationRouter
        router = ActivationRouter()
        router.plan_route(db, avatar, client)
    except Exception as e:
        logger.warning("Activation route planning failed for %s: %s", username, e)

    # Trigger post-onboarding pipeline (strategy + scraping) asynchronously
    try:
        from app.tasks.onboarding import run_avatar_onboarding

        run_avatar_onboarding.delay(str(avatar.id), str(client_id))
        logger.info(
            "Avatar onboarding pipeline triggered: avatar=%s client=%s",
            username,
            client.client_name,
        )
    except Exception as e:
        logger.warning("Failed to trigger avatar onboarding pipeline: %s", e)

    logger.info(
        "Avatar onboarded: u/%s → %s (phase=%d, by=%s)",
        username,
        client.client_name,
        suggested_phase,
        user.email,
    )

    # Determine redirect based on user role
    if user.user_role.is_client_scoped:
        # Client portal users
        redirect_url = f"/clients/{client_id}/avatars"
    else:
        # Admin users — go back to avatar onboard page (for sequential onboarding)
        redirect_url = f"/clients/{client_id}/avatar-onboard?success={username}"

    return RedirectResponse(url=redirect_url, status_code=303)
