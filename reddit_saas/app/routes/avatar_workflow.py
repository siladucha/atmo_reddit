"""Avatar Workflow routes — unified EPG → Generate → Post flow.

Provides the Workflow tab on the avatar detail page:
- GET  /admin/avatars/{id}/workflow          — load workflow panel (HTMX partial)
- POST /admin/avatars/{id}/workflow/rebuild-epg — rebuild EPG and reload
- POST /admin/avatars/{id}/workflow/generate-hobby — generate one hobby comment
- POST /admin/avatars/{id}/workflow/drafts/{id}/approve — approve inline
- POST /admin/avatars/{id}/workflow/drafts/{id}/reject  — reject inline
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_superuser
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.thread import RedditThread
from app.models.user import User
from app.services import audit as audit_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/avatars/{avatar_id}/workflow")
templates = Jinja2Templates(directory="app/templates")


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
        item = {"draft": draft, "thread": thread}
        if draft.status == "pending":
            pending.append(item)
        elif draft.status == "approved":
            approved.append(item)
        elif draft.status == "posted":
            posted.append(item)

    return pending, approved, posted


# ---------------------------------------------------------------------------
# Main workflow panel
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def workflow_panel(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial: render the unified workflow panel."""
    from app.services.epg import build_daily_epg

    avatar, client = _get_avatar_and_client(db, avatar_id)
    if not avatar:
        return HTMLResponse("<div class='text-red-400 text-sm p-4'>Avatar not found</div>", status_code=404)

    epg = build_daily_epg(db, avatar, client)
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
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Rebuild EPG and return the full workflow panel."""
    from app.services.epg import build_daily_epg

    avatar, client = _get_avatar_and_client(db, avatar_id)
    if not avatar:
        return HTMLResponse("<div class='text-red-400 text-sm p-4'>Avatar not found</div>", status_code=404)

    epg = build_daily_epg(db, avatar, client)
    pending_drafts, approved_drafts, posted_drafts = _get_today_drafts(db, avatar)

    audit_service.log_action(
        db=db,
        user_id=current_user.id,
        action="rebuild_epg",
        entity_type="avatar",
        entity_id=avatar_id,
        details={"status": epg.status, "total_slots": epg.total_slots},
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
    current_user: User = Depends(require_superuser),
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
# Approve / Reject (inline, returns updated card)
# ---------------------------------------------------------------------------


@router.post("/drafts/{draft_id}/approve", response_class=HTMLResponse)
def workflow_approve(
    request: Request,
    avatar_id: uuid.UUID,
    draft_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Approve a draft and return it as an 'approved' card with post actions."""
    draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
    if not draft:
        return HTMLResponse('<div class="text-red-400 text-xs p-2">Draft not found</div>')

    draft.status = "approved"
    db.commit()

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
    thread_url = thread.url if thread else ""

    # Return the approved card HTML
    return HTMLResponse(f'''
    <div id="wf-draft-{draft.id}" class="rounded-lg border border-green-700/30 bg-slate-800/40 p-3">
        <div class="flex items-center gap-2 mb-2">
            <span class="text-[10px] text-indigo-400 font-medium">r/{thread.subreddit if thread else "?"}</span>
            <span class="text-[10px] text-gray-500 truncate flex-1">{(thread.post_title[:60] if thread else "")}</span>
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
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Reject a draft and return a dismissed card."""
    draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
    if not draft:
        return HTMLResponse('<div class="text-red-400 text-xs p-2">Draft not found</div>')

    draft.status = "rejected"
    db.commit()

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
