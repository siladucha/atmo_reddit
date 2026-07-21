"""Avatar Workflow routes — unified EPG → Generate → Post flow.

Provides the Workflow tab on the avatar detail page:
- GET  /admin/avatars/{id}/workflow              — load workflow panel (HTMX partial)
- POST /admin/avatars/{id}/workflow/rebuild-epg  — rebuild EPG and reload
- POST /admin/avatars/{id}/workflow/generate-slot/{slot_id} — generate one slot
- POST /admin/avatars/{id}/workflow/generate-all — generate all planned slots
- POST /admin/avatars/{id}/workflow/drafts/{id}/approve — approve inline
- POST /admin/avatars/{id}/workflow/drafts/{id}/reject  — reject inline
"""

from app.logging_config import get_logger
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from app.templating import Jinja2Templates
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_avatar_admin
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.hobby import HobbySubreddit
from app.models.thread import RedditThread
from app.models.user import User
from app.services import audit as audit_service

logger = get_logger(__name__)

router = APIRouter(prefix="/admin/avatars/{avatar_id}/workflow")
templates = Jinja2Templates(directory="app/templates")
from app.version import __version__ as app_version
from app.config import get_settings as _get_settings
templates.env.globals["app_version"] = app_version
templates.env.globals["posting_disabled"] = lambda: _get_settings().posting_disabled
templates.env.globals["app_env"] = _get_settings().app_env

from app.template_filters import register_filters
register_filters(templates.env)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_avatar_and_client(db: Session, avatar_id: uuid.UUID):
    """Load avatar and its first assigned client."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return None, None
    client = None
    if avatar.client_ids:
        client = db.query(Client).filter(Client.id == uuid.UUID(avatar.client_ids[0])).first()
    return avatar, client


def _get_today_drafts(db: Session, avatar: Avatar):
    """Get today's drafts grouped by status."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    drafts = (
        db.query(CommentDraft)
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.created_at >= today_start,
        )
        .order_by(CommentDraft.created_at.desc())
        .all()
    )

    pending = []
    approved = []
    posted = []

    for draft in drafts:
        thread = draft.thread
        # For hobby drafts, resolve subreddit info from HobbySubreddit
        if thread is None and draft.hobby_post_id:
            hobby_post = draft.hobby_post  # use relationship (eager-loaded or lazy)
            if not hobby_post:
                hobby_post = db.query(HobbySubreddit).filter(HobbySubreddit.id == draft.hobby_post_id).first()
            if hobby_post:
                from app.services.hobby_proxy import HobbyThreadProxy
                thread = HobbyThreadProxy(hobby_post)
        item = {"draft": draft, "thread": thread}
        if draft.status == "pending":
            pending.append(item)
        elif draft.status == "approved":
            approved.append(item)
        elif draft.status == "posted":
            posted.append(item)

    return pending, approved, posted


def _has_approved_strategy(db: Session, avatar: Avatar) -> bool:
    """Check if the avatar has an approved current strategy document."""
    from app.models.strategy_document import StrategyDocument

    current_strategy = (
        db.query(StrategyDocument)
        .filter(StrategyDocument.avatar_id == avatar.id, StrategyDocument.is_current.is_(True))
        .first()
    )
    return bool(current_strategy and current_strategy.is_approved)


def _build_action_items(db: Session, avatar: Avatar) -> list[dict]:
    """Build list of actionable issues for the Workflow tab.

    Each item: {severity: 'critical'|'warning'|'info', title, description, action_tab}
    """
    from app.models.strategy_document import StrategyDocument
    from datetime import timedelta

    items = []

    # --- Strategy not approved ---
    current_strategy = (
        db.query(StrategyDocument)
        .filter(StrategyDocument.avatar_id == avatar.id, StrategyDocument.is_current.is_(True))
        .first()
    )
    if current_strategy and not current_strategy.is_approved:
        days_since = (datetime.now(timezone.utc) - current_strategy.generated_at).days if current_strategy.generated_at else 0
        items.append({
            "severity": "critical" if days_since > 7 else "warning",
            "title": "Strategy not approved",
            "description": f"AI generates without strategic direction ({days_since} days). Approve or regenerate.",
            "action_tab": "strategy",
        })
    elif not current_strategy:
        items.append({
            "severity": "warning",
            "title": "No strategy generated",
            "description": "Generate a strategy to guide AI comment quality and tone.",
            "action_tab": "strategy",
        })

    # --- Phase overdue ---
    PHASE_DURATIONS = {1: 60, 2: 60, 3: None}  # days per phase (None = no limit)
    phase_duration = PHASE_DURATIONS.get(avatar.warming_phase)
    if phase_duration and avatar.phase_changed_at:
        days_in_phase = (datetime.now(timezone.utc) - avatar.phase_changed_at).days
        if days_in_phase > phase_duration:
            items.append({
                "severity": "warning",
                "title": f"Phase {avatar.warming_phase} overdue",
                "description": f"Day {days_in_phase}/{phase_duration} — check if promotion criteria are met.",
                "action_tab": "overview",
            })

    # --- CQS lowest ---
    if avatar.cqs_level == "lowest":
        items.append({
            "severity": "critical",
            "title": "CQS at lowest level",
            "description": "Reddit rates this account as low quality. Excluded from professional pipeline.",
            "action_tab": "overview",
        })

    # --- Frozen ---
    if avatar.is_frozen:
        items.append({
            "severity": "critical",
            "title": f"Avatar frozen",
            "description": f"Reason: {avatar.freeze_reason or 'unknown'}. All pipelines paused.",
            "action_tab": "profile-safety",
        })

    # --- Health: shadowbanned/suspended ---
    if avatar.health_status in ("shadowbanned", "suspended"):
        items.append({
            "severity": "critical",
            "title": f"Health: {avatar.health_status}",
            "description": "This avatar cannot post on Reddit. Investigate or retire.",
            "action_tab": "overview",
        })

    # --- Posting: missing proxy/credentials (only if posting_mode=auto) ---
    if avatar.posting_mode == "auto":
        if not avatar.proxy_url_encrypted:
            items.append({
                "severity": "warning",
                "title": "No proxy configured",
                "description": "Auto-posting requires a residential proxy for safety.",
                "action_tab": "posting",
            })
        if not (avatar.reddit_password_encrypted or getattr(avatar, 'refresh_token_encrypted', None)):
            items.append({
                "severity": "warning",
                "title": "No credentials configured",
                "description": "Auto-posting requires Reddit password or OAuth token.",
                "action_tab": "posting",
            })

    return items


# ---------------------------------------------------------------------------
# Main workflow panel
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def workflow_panel(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """HTMX partial: render the unified workflow panel."""
    from app.services.epg import build_daily_epg

    avatar, client = _get_avatar_and_client(db, avatar_id)
    if not avatar:
        return HTMLResponse("<div class='text-red-400 text-sm p-4'>Avatar not found</div>", status_code=404)

    epg = build_daily_epg(db, avatar, client)
    pending_drafts, approved_drafts, posted_drafts = _get_today_drafts(db, avatar)
    action_items = _build_action_items(db, avatar)

    return templates.TemplateResponse(
        name="partials/avatar_workflow.html",
        context={
            "request": request,
            "avatar": avatar,
            "epg": epg,
            "pending_drafts": pending_drafts,
            "approved_drafts": approved_drafts,
            "posted_drafts": posted_drafts,
            "action_items": action_items,
            "strategy_approved": _has_approved_strategy(db, avatar),
            "now_utc": datetime.now(timezone.utc),
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# Rebuild EPG
# ---------------------------------------------------------------------------


@router.post("/rebuild-epg", response_class=HTMLResponse)
def workflow_rebuild_epg(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """Rebuild EPG (plan + generate) and return the full workflow panel."""
    from app.services.epg import build_daily_epg
    from app.services.epg_executor import generate_all_planned_slots
    from app.services.portfolio_manager import build_portfolio
    from app.services.settings import get_setting

    avatar, client = _get_avatar_and_client(db, avatar_id)
    if not avatar:
        return HTMLResponse("<div class='text-red-400 text-sm p-4'>Avatar not found</div>", status_code=404)

    # Step 1: Build slots (Portfolio Manager if enabled, else legacy)
    epg2_enabled = get_setting(db, "epg2_enabled") == "true"
    if epg2_enabled:
        result = build_portfolio(db=db, avatar=avatar, client=client)
        total_slots = result.get("planned", 0) if isinstance(result, dict) else 0
    else:
        epg = build_daily_epg(db, avatar, client)
        total_slots = epg.total_slots if epg else 0

    # Step 2: Generate drafts for all planned slots
    generated = generate_all_planned_slots(db, avatar.id)

    pending_drafts, approved_drafts, posted_drafts = _get_today_drafts(db, avatar)

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="rebuild_epg",
        entity_type="avatar",
        entity_id=avatar_id,
        details={"total_slots": total_slots, "generated": generated},
    )

    return templates.TemplateResponse(
        name="partials/avatar_workflow.html",
        context={
            "request": request,
            "avatar": avatar,
            "epg": epg,
            "pending_drafts": pending_drafts,
            "approved_drafts": approved_drafts,
            "posted_drafts": posted_drafts,
            "strategy_approved": _has_approved_strategy(db, avatar),
            "now_utc": datetime.now(timezone.utc),
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# Generate hobby comment (one at a time)
# ---------------------------------------------------------------------------


@router.post("/generate-hobby", response_class=HTMLResponse)
def workflow_generate_hobby(
    request: Request,
    avatar_id: uuid.UUID,
    hobby_post_id: str = Form(...),
    subreddit: str = Form(""),
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """Generate a single hobby comment for an EPG slot.

    Returns a small inline result (success badge or error).
    """
    from app.models.hobby import HobbySubreddit
    from app.services.ai import call_llm_json, log_ai_usage
    from app.config import get_config

    avatar, client = _get_avatar_and_client(db, avatar_id)
    if not avatar:
        return HTMLResponse('<span class="text-red-400 text-xs">Avatar not found</span>')

    # Find the hobby post
    hobby_post = db.query(HobbySubreddit).filter(HobbySubreddit.id == hobby_post_id).first()
    if not hobby_post:
        # Try by post_id
        hobby_post = (
            db.query(HobbySubreddit)
            .filter(
                HobbySubreddit.post_id == hobby_post_id,
                HobbySubreddit.avatar_username == avatar.reddit_username,
            )
            .first()
        )
    if not hobby_post:
        return HTMLResponse('<span class="text-red-400 text-xs">Post not found</span>')

    if hobby_post.ai_comment:
        return HTMLResponse('<span class="text-green-400 text-xs">✓ Already generated</span>')

    # Skip image-only posts — LLM cannot see images
    if not hobby_post.post_body or len(hobby_post.post_body.strip()) < 20:
        return HTMLResponse('<span class="text-amber-400 text-xs">⊘ Image-only post (skipped)</span>')

    # Get previous comments for diversity
    previous = (
        db.query(CommentDraft.ai_draft)
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.ai_draft.isnot(None),
        )
        .order_by(CommentDraft.created_at.desc())
        .limit(10)
        .all()
    )
    prev_comments = [p[0] for p in previous if p[0]]

    try:
        voice = avatar.voice_profile_md or "Casual, helpful community member"
        system_prompt = f"""You are writing a Reddit comment as a regular community member.
Your voice: {voice}

Rules:
- Be SHORT (20-60 words, max 80)
- Be genuine and helpful — this is a hobby subreddit
- No brand mentions, no marketing, no self-promotion
- Match the tone of the subreddit
- Never use em-dashes (—)

Previous comments (avoid repetition):
{chr(10).join(f'- {c[:80]}' for c in prev_comments[:5])}

Output JSON:
{{"comment": "the exact comment text"}}"""

        user_prompt = f"""Subreddit: r/{hobby_post.subreddit}
Post title: {hobby_post.post_title}
Post body: {(hobby_post.post_body or '')[:500]}
Upvotes: {hobby_post.post_ups or 0}"""

        gen_model = get_config("llm_scoring_model") or get_config("llm_generation_model")

        result = call_llm_json(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=gen_model,
            temperature=0.85,
            max_tokens=300,
        )

        log_ai_usage(
            db, None, "hobby_comment_workflow", result,
            avatar_id=str(avatar.id),
            subreddit_name=hobby_post.subreddit,
        )

        data = result.get("data", {})
        comment_text = data.get("comment", result.get("content", ""))

        # Save to hobby post
        hobby_post.ai_comment = comment_text
        hobby_post.status = "pending"
        db.commit()

        # Also create CommentDraft for client Review Queue
        try:
            import uuid as uuid_mod
            draft_client_id = None
            if avatar.client_ids:
                draft_client_id = avatar.client_ids[0]
            draft = CommentDraft(
                id=uuid_mod.uuid4(),
                thread_id=None,
                hobby_post_id=hobby_post.id,
                avatar_id=avatar.id,
                client_id=draft_client_id,
                type="hobby",
                ai_draft=comment_text,
                status="pending",
                comment_approach="hobby_engagement",
            )
            db.add(draft)
            db.commit()
        except Exception as draft_err:
            logger.warning(f"Failed to create CommentDraft for hobby: {draft_err}")

        return HTMLResponse(f'''
        <span class="text-green-400 text-xs font-medium">✓ Done</span>
        ''')

    except Exception as e:
        logger.error(f"Hobby generation failed: {e}")
        return HTMLResponse(f'<span class="text-red-400 text-xs">Error: {str(e)[:60]}</span>')


# ---------------------------------------------------------------------------
# Generate EPG slot (one at a time — replaces generate-hobby for new flow)
# ---------------------------------------------------------------------------


@router.post("/generate-slot/{slot_id}", response_class=HTMLResponse)
def workflow_generate_slot(
    request: Request,
    avatar_id: uuid.UUID,
    slot_id: uuid.UUID,
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """Generate a comment for a specific EPG slot.

    Works for both hobby and professional slots.
    Returns inline result (success badge or error).
    """
    from app.services.epg_executor import generate_epg_slot
    from app.models.epg_slot import EPGSlot

    slot = db.query(EPGSlot).filter(EPGSlot.id == slot_id).first()
    if not slot:
        return HTMLResponse('<span class="text-red-400 text-xs">Slot not found</span>')

    if slot.status != "planned":
        status_label = slot.status
        if slot.status == "generated":
            return HTMLResponse('<span class="text-green-400 text-xs font-medium">✓ Already generated</span>')
        return HTMLResponse(f'<span class="text-gray-400 text-xs">Status: {status_label}</span>')

    draft = generate_epg_slot(db, slot_id)

    if draft:
        audit_service.log_action(
            db=db,
            user_id=current_user.id,
            action="generate_epg_slot",
            entity_type="epg_slot",
            entity_id=slot_id,
            details={"slot_type": slot.slot_type, "subreddit": slot.subreddit, "draft_id": str(draft.id)},
        )
        return HTMLResponse('<span class="text-green-400 text-xs font-medium">✓ Done</span>')
    else:
        # Reload slot to get skip reason
        db.refresh(slot)
        reason = slot.skip_reason or "unknown error"
        return HTMLResponse(f'<span class="text-red-400 text-xs">Skipped: {reason[:60]}</span>')


@router.post("/generate-all", response_class=HTMLResponse)
def workflow_generate_all(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """Generate all planned EPG slots for this avatar today.

    Returns the full workflow panel (refreshed).
    Does NOT rebuild the plan — use the Rebuild button for that.
    """
    from app.services.epg import build_daily_epg
    from app.services.epg_executor import generate_all_planned_slots

    avatar, client = _get_avatar_and_client(db, avatar_id)
    if not avatar:
        return HTMLResponse("<div class='text-red-400 text-sm p-4'>Avatar not found</div>", status_code=404)

    generated = generate_all_planned_slots(db, avatar_id)

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="generate_all_epg_slots",
        entity_type="avatar",
        entity_id=avatar_id,
        details={"generated": generated},
    )

    # Show current state WITHOUT rebuilding the plan.
    # build_daily_epg would delete "planned" slots and create new ones,
    # which causes slot accumulation when generation fails (skipped don't
    # count toward budget, so new planned slots keep being created).
    # Just load the existing EPG slots for display.
    from app.models.epg_slot import EPGSlot
    from app.services.epg import EPGResult, _get_daily_budget
    from app.services.epg_executor import get_budget_used_today
    from datetime import date

    today = date.today()
    existing_slots = (
        db.query(EPGSlot)
        .filter(
            EPGSlot.avatar_id == avatar.id,
            EPGSlot.plan_date == today,
        )
        .order_by(EPGSlot.scheduled_at.asc().nullslast())
        .all()
    )

    # Build a minimal EPGResult for display
    epg = EPGResult(avatar)
    epg.daily_budget = _get_daily_budget(avatar)
    epg.used_today = get_budget_used_today(db, avatar.id, today)
    epg.remaining = max(0, epg.daily_budget - epg.used_today)

    for slot in existing_slots:
        slot_dict = {
            "slot_id": str(slot.id),
            "subreddit": slot.subreddit,
            "title": slot.thread_title,
            "ups": slot.thread_ups or 0,
            "scheduled_at": slot.scheduled_at.isoformat() if slot.scheduled_at else None,
            "status": slot.status,
            "draft_id": str(slot.draft_id) if slot.draft_id else None,
        }
        if slot.slot_type == "hobby":
            slot_dict["hobby_post_id"] = str(slot.hobby_post_id) if slot.hobby_post_id else None
            slot_dict["post_id"] = None
            slot_dict["comment_type"] = "hobby"
            epg.hobby_slots.append(slot_dict)
        else:
            slot_dict["thread_id"] = str(slot.thread_id) if slot.thread_id else None
            slot_dict["comment_type"] = "professional"
            epg.business_slots.append(slot_dict)

    pending_drafts, approved_drafts, posted_drafts = _get_today_drafts(db, avatar)

    return templates.TemplateResponse(
        name="partials/avatar_workflow.html",
        context={
            "request": request,
            "avatar": avatar,
            "epg": epg,
            "pending_drafts": pending_drafts,
            "approved_drafts": approved_drafts,
            "posted_drafts": posted_drafts,
            "strategy_approved": _has_approved_strategy(db, avatar),
            "now_utc": datetime.now(timezone.utc),
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# Approve / Reject (inline, returns updated card)
# ---------------------------------------------------------------------------


@router.post("/drafts/{draft_id}/approve", response_class=HTMLResponse)
def workflow_approve(
    request: Request,
    avatar_id: uuid.UUID,
    draft_id: uuid.UUID,
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """Approve a draft and return it as an 'approved' card with post actions."""
    draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
    if not draft:
        return HTMLResponse('<div class="text-red-400 text-xs p-2">Draft not found</div>')

    draft.status = "approved"
    db.commit()

    # Sync EPG slot status
    try:
        from app.services.epg_executor import sync_slot_status
        sync_slot_status(db, draft.id, "approved")
        db.commit()
    except Exception:
        logger.warning("Failed to sync EPG slot for draft %s", draft_id, exc_info=True)

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="approve",
        entity_type="comment_draft",
        entity_id=draft.id,
        client_id=draft.client_id,
        details={"source": "workflow_tab"},
    )

    # Self-learning
    try:
        from app.services.learning import LearningService
        thread = draft.thread
        if thread:
            status = "approved_unchanged" if (not draft.edited_draft or draft.edited_draft == draft.ai_draft) else "approved"
            LearningService().capture_edit_record(db=db, draft=draft, thread=thread, status=status)
            db.commit()
    except Exception:
        logger.warning("Learning capture failed for draft %s", draft_id, exc_info=True)

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    thread = draft.thread
    # Resolve hobby post info if no thread
    if thread is None and draft.hobby_post_id:
        hobby_post = draft.hobby_post
        if not hobby_post:
            hobby_post = db.query(HobbySubreddit).filter(HobbySubreddit.id == draft.hobby_post_id).first()
        if hobby_post:
            from app.services.hobby_proxy import HobbyThreadProxy
            thread = HobbyThreadProxy(hobby_post)
    thread_url = thread.url if thread else ""
    thread_subreddit = thread.subreddit if thread else "?"
    thread_title = (thread.post_title[:60] if thread else "")

    # Return the approved card HTML
    return HTMLResponse(f'''
    <div id="wf-draft-{draft.id}" class="rounded-lg border border-green-700/30 bg-slate-800/40 p-3">
        <div class="flex items-center gap-2 mb-2">
            <span class="text-[10px] text-indigo-400 font-medium">r/{thread_subreddit}</span>
            <span class="text-[10px] text-gray-500 truncate flex-1">{thread_title}</span>
            <span class="px-1.5 py-0.5 rounded text-[10px] bg-green-900/50 text-green-300 border border-green-700">approved</span>
        </div>
        <div class="relative group/copy mb-2">
            <div data-copy-text class="p-2.5 bg-slate-900 rounded border border-slate-600 text-sm text-white leading-relaxed whitespace-pre-wrap select-all">{draft.edited_draft or draft.ai_draft}</div>
            <button onclick="navigator.clipboard.writeText(this.closest('.group\\/copy').querySelector('[data-copy-text]').innerText).then(()=>{{this.textContent='✓';setTimeout(()=>this.textContent='📋',1200)}})"
                    class="absolute top-2 right-2 text-xs text-gray-500 hover:text-white bg-slate-800 px-1.5 py-0.5 rounded border border-slate-600">
                📋
            </button>
        </div>
        <div class="flex flex-wrap items-center gap-2">
            {"<a href='" + thread_url + "' target='_blank' rel='noopener' class='inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium bg-indigo-600 hover:bg-indigo-500 text-white transition-colors'>Reddit ↗</a>" if thread_url else ""}
            <form hx-post="/admin/avatars/{avatar_id}/pipeline/drafts/{draft.id}/posted"
                  hx-target="#wf-draft-{draft.id}"
                  hx-swap="outerHTML"
                  class="inline-flex items-center gap-1.5">
                <input type="url" name="reddit_comment_url" placeholder="URL (optional)"
                       class="px-2 py-1 bg-slate-900 border border-slate-600 text-gray-200 rounded text-[11px] w-36 focus:outline-none focus:border-indigo-500">
                <button type="submit"
                        class="px-2.5 py-1 rounded text-xs font-medium bg-purple-600 hover:bg-purple-500 text-white transition-colors">
                    📤 Posted
                </button>
            </form>
        </div>
    </div>
    ''')


@router.post("/drafts/{draft_id}/reject", response_class=HTMLResponse)
def workflow_reject(
    request: Request,
    avatar_id: uuid.UUID,
    draft_id: uuid.UUID,
    current_user: User = Depends(require_avatar_admin),
    db: Session = Depends(get_db),
):
    """Reject a draft and return a dismissed card."""
    draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
    if not draft:
        return HTMLResponse('<div class="text-red-400 text-xs p-2">Draft not found</div>')

    draft.status = "rejected"
    db.commit()

    # Sync EPG slot status (frees budget)
    try:
        from app.services.epg_executor import sync_slot_status
        sync_slot_status(db, draft.id, "rejected")
        db.commit()
    except Exception:
        logger.warning("Failed to sync EPG slot for draft %s", draft_id, exc_info=True)

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="reject",
        entity_type="comment_draft",
        entity_id=draft.id,
        client_id=draft.client_id,
        details={"source": "workflow_tab"},
    )

    # Self-learning
    try:
        from app.services.learning import LearningService
        thread = draft.thread
        if thread:
            LearningService().capture_edit_record(db=db, draft=draft, thread=thread, status="rejected")
            db.commit()
    except Exception:
        logger.warning("Learning capture failed for draft %s", draft_id, exc_info=True)

    return HTMLResponse(f'''
    <div id="wf-draft-{draft.id}" class="rounded-lg border border-red-700/20 bg-slate-800/20 p-2 opacity-50">
        <span class="text-[10px] text-red-400">✗ Rejected</span>
        <span class="text-[10px] text-gray-500 ml-2">Draft discarded</span>
    </div>
    ''')
