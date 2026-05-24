"""Manual per-avatar pipeline routes — scrape, score, select thread, generate.

Provides a step-by-step HTMX-driven flow on the avatar detail page:
1. Scrape all subreddits relevant to this avatar (hobby + business via client)
2. Score unscored threads for the avatar's client
3. Present engage threads filtered by phase eligibility
4. Generate a comment for a selected thread
5. Approve / Edit / Reject / Mark Posted / Regenerate — all inline
"""

import logging
import time
import uuid
from datetime import datetime, timezone, timedelta

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
from app.models.subreddit import ClientSubredditAssignment, Subreddit
from app.models.thread import RedditThread
from app.models.thread_score import ThreadScore
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/avatars/{avatar_id}/pipeline")
templates = Jinja2Templates(directory="app/templates")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_avatar_and_client(db: Session, avatar_id: uuid.UUID) -> tuple[Avatar | None, Client | None]:
    """Load avatar and its first assigned client."""
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return None, None
    client = None
    if avatar.client_ids:
        client = db.query(Client).filter(Client.id == uuid.UUID(avatar.client_ids[0])).first()
    return avatar, client


def _get_avatar_subreddits(db: Session, avatar: Avatar, client: Client | None) -> list[dict]:
    """Get all subreddits relevant to this avatar (hobby + business via client assignments).

    Deduplicates by subreddit name (case-insensitive). If a subreddit appears
    in both hobby and client assignments, the client assignment takes precedence.
    """
    seen: set[str] = set()
    subreddits = []

    # Business/professional subreddits first (from client assignments) — higher priority
    if client:
        assignments = (
            db.query(ClientSubredditAssignment)
            .join(Subreddit, Subreddit.id == ClientSubredditAssignment.subreddit_id)
            .filter(
                ClientSubredditAssignment.client_id == client.id,
                ClientSubredditAssignment.is_active.is_(True),
                Subreddit.is_active.is_(True),
            )
            .all()
        )
        for a in assignments:
            sub = db.query(Subreddit).filter(Subreddit.id == a.subreddit_id).first()
            if sub:
                key = sub.subreddit_name.lower()
                if key not in seen:
                    seen.add(key)
                    subreddits.append({
                        "name": sub.subreddit_name,
                        "type": a.type or "professional",
                        "subreddit_id": str(sub.id),
                        "last_scraped_at": sub.last_scraped_at,
                    })

    # Hobby subreddits (from avatar directly, with Phase 1 fallback) — only add if not already present
    from app.services.sanitize import get_avatar_hobby_subreddits
    hobby_sub_names = get_avatar_hobby_subreddits(avatar)
    for name in hobby_sub_names:
        if name.lower() not in seen:
            seen.add(name.lower())
            subreddits.append({"name": name, "type": "hobby"})

    # Business subreddits (from avatar directly) — for farm avatars without client
    if not client and avatar.warming_phase >= 2:
        business_subs_raw = avatar.business_subreddits or []
        if isinstance(business_subs_raw, str):
            business_subs_raw = [s.strip() for s in business_subs_raw.split(",")]
        for item in business_subs_raw:
            if isinstance(item, dict):
                name = item.get("subreddit") or item.get("name") or ""
            else:
                name = str(item)
            name = name.strip().replace("r/", "")
            if name and name.lower() not in seen:
                seen.add(name.lower())
                subreddits.append({"name": name, "type": "business"})

    return subreddits


# ---------------------------------------------------------------------------
# Step 0: Pipeline panel (initial load)
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def pipeline_panel(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """HTMX partial: render the pipeline panel with current state."""
    avatar, client = _get_avatar_and_client(db, avatar_id)
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    subreddits = _get_avatar_subreddits(db, avatar, client)

    # Count unscored threads (including hobby subreddits)
    unscored_count = 0
    engage_count = 0
    if client:
        from app.services.scoring import _get_all_subreddit_ids_for_scoring
        all_sub_ids = _get_all_subreddit_ids_for_scoring(db, client, avatar)

        scored_thread_ids = (
            db.query(ThreadScore.thread_id)
            .filter(ThreadScore.client_id == client.id)
        )

        if all_sub_ids:
            unscored_count = (
                db.query(sa_func.count(RedditThread.id))
                .filter(
                    RedditThread.subreddit_id.in_(all_sub_ids),
                    RedditThread.is_locked.is_(False),
                    ~RedditThread.id.in_(scored_thread_ids),
                )
                .scalar()
            ) or 0

        engage_count = (
            db.query(sa_func.count(ThreadScore.id))
            .filter(
                ThreadScore.client_id == client.id,
                ThreadScore.tag == "engage",
            )
            .scalar()
        ) or 0

    # Today's comment count for this avatar
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_comments = (
        db.query(sa_func.count(CommentDraft.id))
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.status.in_(["approved", "posted", "pending"]),
            CommentDraft.created_at >= today_start,
        )
        .scalar()
    ) or 0

    # Phase info
    phase_labels = {1: "Credibility Building", 2: "Content Seeding", 3: "Brand Integration"}

    return templates.TemplateResponse(
        name="partials/avatar_pipeline_panel.html",
        context={
            "request": request,
            "avatar": avatar,
            "client": client,
            "subreddits": subreddits,
            "unscored_count": unscored_count,
            "engage_count": engage_count,
            "today_comments": today_comments,
            "phase_label": phase_labels.get(avatar.warming_phase, "Unknown"),
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# Step 1: Scrape
# ---------------------------------------------------------------------------


@router.post("/scrape", response_class=HTMLResponse)
def pipeline_scrape(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Check scrape freshness from DB and dispatch async scrape for stale subreddits.

    Instead of blocking the HTTP request with synchronous Reddit API calls,
    this endpoint:
    1. Checks last_scraped_at for each subreddit in the shared registry
    2. Reports which are fresh vs stale
    3. Dispatches Celery tasks for stale subreddits (non-blocking)
    4. Returns immediately with freshness status

    The data is already available from background queue_tick scraping.
    This button only force-refreshes stale subreddits.
    """
    from app.services.transparency import record_activity_event

    FRESHNESS_MINUTES = 30  # Consider fresh if scraped within 30 min

    avatar, client = _get_avatar_and_client(db, avatar_id)
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    subreddits = _get_avatar_subreddits(db, avatar, client)
    results = []
    stale_count = 0
    dispatched_count = 0
    now = datetime.now(timezone.utc)

    for sub_info in subreddits:
        sub_name = sub_info["name"]

        # Look up subreddit in shared registry
        subreddit_record = (
            db.query(Subreddit)
            .filter(sa_func.lower(Subreddit.subreddit_name) == sub_name.lower())
            .first()
        )

        if not subreddit_record:
            # Subreddit not in registry yet — create it and mark as stale
            subreddit_record = Subreddit(subreddit_name=sub_name, is_active=True)
            db.add(subreddit_record)
            db.flush()

        last_scraped = subreddit_record.last_scraped_at
        if last_scraped:
            age_minutes = (now - last_scraped).total_seconds() / 60
            is_fresh = age_minutes < FRESHNESS_MINUTES
        else:
            age_minutes = None
            is_fresh = False

        # Count threads available in DB for this subreddit
        thread_count = (
            db.query(sa_func.count(RedditThread.id))
            .filter(
                RedditThread.subreddit_id == subreddit_record.id,
                RedditThread.is_locked.is_(False),
            )
            .scalar()
        ) or 0

        if is_fresh:
            results.append({
                "subreddit": sub_name,
                "type": sub_info["type"],
                "status": "fresh",
                "age_minutes": int(age_minutes) if age_minutes else 0,
                "threads_in_db": thread_count,
                "posts_new": 0,
            })
        else:
            stale_count += 1
            # Dispatch async scrape via Celery
            try:
                from app.tasks.scraping import scrape_subreddit_shared
                scrape_subreddit_shared.delay(str(subreddit_record.id))
                dispatched_count += 1
                results.append({
                    "subreddit": sub_name,
                    "type": sub_info["type"],
                    "status": "dispatched",
                    "age_minutes": int(age_minutes) if age_minutes else None,
                    "threads_in_db": thread_count,
                    "posts_new": 0,
                })
            except Exception as e:
                results.append({
                    "subreddit": sub_name,
                    "type": sub_info["type"],
                    "status": "error",
                    "error": str(e)[:100],
                    "threads_in_db": thread_count,
                    "posts_new": 0,
                })

    db.commit()

    # Record activity event
    try:
        if dispatched_count > 0:
            record_activity_event(
                db, "scrape",
                f"Manual scrape triggered for {avatar.reddit_username}: {dispatched_count} stale subs dispatched to queue",
                client_id=uuid.UUID(avatar.client_ids[0]) if avatar.client_ids else None,
                metadata={"avatar_id": str(avatar.id), "dispatched": dispatched_count, "fresh": len(results) - stale_count},
            )
    except Exception:
        pass

    return templates.TemplateResponse(
        name="partials/avatar_pipeline_scrape_result.html",
        context={
            "request": request,
            "results": results,
            "total_new": dispatched_count,
            "avatar": avatar,
            "stale_count": stale_count,
            "dispatched_count": dispatched_count,
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# Step 2: Score
# ---------------------------------------------------------------------------


@router.post("/score", response_class=HTMLResponse)
def pipeline_score(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Smart Score — avatar-centric thread scoring.

    Scores only threads this avatar can actually engage with, limited by
    the avatar's daily budget. Dramatically reduces LLM calls compared to
    the old client-wide scoring approach.

    Flow:
    1. Check avatar budget (daily limit - used today)
    2. Determine available subreddits (phase-based)
    3. Pull top threads by engagement from those subs
    4. Score only budget × 3 threads (hard cap: 15)
    5. Return engage threads ready for generation
    """
    from app.services.smart_scoring import smart_score_for_avatar

    avatar, client = _get_avatar_and_client(db, avatar_id)
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)
    if not client:
        return HTMLResponse("Avatar has no assigned client", status_code=400)

    start = time.time()
    try:
        result = smart_score_for_avatar(db, avatar, client)
    except Exception as e:
        logger.exception("Smart scoring failed for avatar %s", avatar.reddit_username)
        return HTMLResponse(
            f'<div class="p-4 bg-red-900/30 border border-red-700 rounded-lg text-red-300">'
            f'Scoring failed: {str(e)[:200]}</div>',
            status_code=200,
        )
    duration_ms = int((time.time() - start) * 1000)

    # Build thread display lists from SmartScoreResult
    engage_threads = []
    monitor_threads = []
    skip_threads_display = []

    for score in result.engage_threads:
        thread = db.query(RedditThread).filter(RedditThread.id == score.thread_id).first()
        if thread:
            engage_threads.append({"thread": thread, "score": score})

    for score in result.monitor_threads:
        thread = db.query(RedditThread).filter(RedditThread.id == score.thread_id).first()
        if thread:
            monitor_threads.append({"thread": thread, "score": score})

    for score in result.skip_threads:
        thread = db.query(RedditThread).filter(RedditThread.id == score.thread_id).first()
        if thread:
            skip_threads_display.append({"thread": thread, "score": score})

    return templates.TemplateResponse(
        name="partials/avatar_pipeline_score_result.html",
        context={
            "request": request,
            "threads_scored": result.threads_scored,
            "duration_ms": duration_ms,
            "engage_count": result.engage_count,
            "monitor_count": len(result.monitor_threads),
            "skip_count": len(result.skip_threads),
            "pre_filtered_out": 0,
            "growth_count": 0,
            "engage_threads": engage_threads,
            "monitor_threads": monitor_threads,
            "skip_threads": skip_threads_display,
            "growth_threads": [],
            "skipped_threads": [],
            "avatar": avatar,
            # Smart score budget info
            "smart_score": True,
            "daily_limit": result.daily_limit,
            "used_today": result.used_today,
            "remaining_budget": result.remaining_budget,
            "threads_considered": result.threads_considered,
            "smart_status": result.status,
            "smart_message": result.message,
        },
        request=request,
    )


@router.get("/score-summary", response_class=HTMLResponse)
def pipeline_score_summary(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Load persisted scoring summary — shows last results without re-scoring."""
    avatar, client = _get_avatar_and_client(db, avatar_id)
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)
    if not client:
        return HTMLResponse("")

    from app.services.scoring import _get_all_subreddit_ids_for_scoring

    all_sub_ids = _get_all_subreddit_ids_for_scoring(db, client, avatar)

    # Get recent scores (last 72h)
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=72)

    recent_scores = (
        db.query(ThreadScore)
        .filter(
            ThreadScore.client_id == client.id,
            ThreadScore.scored_at >= cutoff,
        )
        .order_by(ThreadScore.scored_at.desc())
        .limit(100)
        .all()
    )

    if not recent_scores:
        return HTMLResponse("")

    # Build summary
    engage_count = sum(1 for s in recent_scores if s.tag == "engage")
    monitor_count = sum(1 for s in recent_scores if s.tag == "monitor")
    skip_count = sum(1 for s in recent_scores if s.tag == "skip")
    last_scored = recent_scores[0].scored_at if recent_scores else None

    # Get engage threads for quick display
    engage_threads = []
    for score in recent_scores:
        if score.tag == "engage":
            thread = db.query(RedditThread).filter(RedditThread.id == score.thread_id).first()
            if thread and not thread.is_locked:
                engage_threads.append({"thread": thread, "score": score})

    # Count unscored
    scored_thread_ids = (
        db.query(ThreadScore.thread_id)
        .filter(ThreadScore.client_id == client.id)
    )
    unscored_count = 0
    if all_sub_ids:
        unscored_count = (
            db.query(sa_func.count(RedditThread.id))
            .filter(
                RedditThread.subreddit_id.in_(all_sub_ids),
                RedditThread.is_locked.is_(False),
                ~RedditThread.id.in_(scored_thread_ids),
            )
            .scalar()
        ) or 0

    return templates.TemplateResponse(
        name="partials/avatar_pipeline_score_summary.html",
        context={
            "request": request,
            "engage_count": engage_count,
            "monitor_count": monitor_count,
            "skip_count": skip_count,
            "total_scored": len(recent_scores),
            "last_scored": last_scored,
            "engage_threads": engage_threads[:5],
            "unscored_count": unscored_count,
            "avatar": avatar,
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# Step 3: Thread selection (filtered by phase)
# ---------------------------------------------------------------------------


@router.get("/threads", response_class=HTMLResponse)
def pipeline_threads(
    request: Request,
    avatar_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Show engage threads available for this avatar, filtered by phase rules."""
    avatar, client = _get_avatar_and_client(db, avatar_id)
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    phase = avatar.warming_phase

    # Get hobby subreddit names for this avatar (with Phase 1 fallback)
    from app.services.sanitize import get_avatar_hobby_subreddits
    hobby_subs = [s.lower() for s in get_avatar_hobby_subreddits(avatar)]

    if not client:
        # No client — farm mode: show fresh threads from hobby + business subreddits
        # Phase 1: hobby only. Phase 2+: hobby + business.
        available_subs = list(hobby_subs)
        if phase >= 2:
            business_raw = avatar.business_subreddits or []
            if isinstance(business_raw, str):
                business_raw = [s.strip() for s in business_raw.split(",")]
            for item in business_raw:
                if isinstance(item, dict):
                    name = item.get("subreddit") or item.get("name") or ""
                else:
                    name = str(item)
                name = name.strip().replace("r/", "")
                if name and name.lower() not in [s.lower() for s in available_subs]:
                    available_subs.append(name.lower())

        if not available_subs:
            return templates.TemplateResponse(
                name="partials/avatar_pipeline_threads.html",
                context={
                    "request": request,
                    "threads": [],
                    "avatar": avatar,
                    "phase": phase,
                    "client": None,
                    "hobby_mode": True,
                },
                request=request,
            )

        from datetime import timedelta
        freshness_cutoff = datetime.now(timezone.utc) - timedelta(hours=72)

        # Get threads from available subreddits directly (no scoring needed)
        existing_draft_thread_ids = (
            db.query(CommentDraft.thread_id)
            .filter(CommentDraft.avatar_id == avatar.id)
        )

        threads_raw = (
            db.query(RedditThread)
            .filter(
                sa_func.lower(RedditThread.subreddit).in_([s.lower() for s in available_subs]),
                RedditThread.is_locked.is_(False),
                RedditThread.scraped_at >= freshness_cutoff,
                ~RedditThread.id.in_(existing_draft_thread_ids),
            )
            .order_by(RedditThread.ups.desc(), RedditThread.scraped_at.desc())
            .limit(30)
            .all()
        )

        thread_list = []
        for thread in threads_raw:
            thread_list.append({
                "thread": thread,
                "score": None,
            })

        return templates.TemplateResponse(
            name="partials/avatar_pipeline_threads.html",
            context={
                "request": request,
                "threads": thread_list,
                "avatar": avatar,
                "phase": phase,
                "client": None,
                "hobby_mode": True,
            },
            request=request,
        )

    # --- Client mode: use scored threads ---

    # Phase 1 avatars have no business in the professional pipeline.
    # Their only job is karma-building via hobby comments. Block early
    # so we don't waste scoring/selection resources.
    if phase == 1:
        if hobby_subs:
            msg = (
                '<div class="p-4 bg-indigo-900/30 border border-indigo-700 rounded-lg">'
                '<p class="text-indigo-300 font-medium mb-1">'
                '\U0001f331 Phase 1 \u2014 Karma Building Only</p>'
                '<p class="text-indigo-200/70 text-sm">'
                'This avatar is in Phase 1 (credibility building). Professional client '
                'threads are not available \u2014 use the <strong>hobby pipeline</strong> '
                'to generate karma-building comments. Promotion to Phase 2 requires '
                'karma \u2265100, activity \u226520, account age \u226560 days.</p></div>'
            )
        else:
            msg = (
                '<div class="p-4 bg-red-900/30 border border-red-700 rounded-lg">'
                '<p class="text-red-300 font-medium mb-1">'
                '\u26a0\ufe0f Phase 1 \u2014 No Hobby Subreddits Configured</p>'
                '<p class="text-red-200/70 text-sm">'
                'This avatar is in Phase 1 but has no hobby subreddits assigned. '
                'It cannot build karma without them. '
                f'<a href="/admin/avatars/{avatar_id}#tab=profile-safety" '
                'class="underline text-red-300 hover:text-red-100">'
                'Configure hobby subreddits</a> in the Profile tab to unblock '
                'the pipeline.</p></div>'
            )
        return HTMLResponse(msg, status_code=200)

    # Get all engage threads for this client
    # Join with RedditThread to get subreddit info
    query = (
        db.query(RedditThread, ThreadScore)
        .join(ThreadScore, ThreadScore.thread_id == RedditThread.id)
        .filter(
            ThreadScore.client_id == client.id,
            ThreadScore.tag == "engage",
            RedditThread.is_locked.is_(False),
        )
    )

    # Phase 2: restrict to hobby + business subreddits
    if phase == 2:
        # Phase 2: hobby + business subreddits
        allowed_subs = set(hobby_subs)

        business_raw = avatar.business_subreddits or []
        if isinstance(business_raw, str):
            business_raw = [s.strip() for s in business_raw.split(",")]
        for item in business_raw:
            if isinstance(item, dict):
                name = item.get("subreddit") or item.get("name") or ""
            else:
                name = str(item)
            name = name.strip().replace("r/", "")
            if name:
                allowed_subs.add(name.lower())

        # Also include client's assigned subreddits
        assignments = (
            db.query(ClientSubredditAssignment)
            .join(Subreddit, Subreddit.id == ClientSubredditAssignment.subreddit_id)
            .filter(
                ClientSubredditAssignment.client_id == client.id,
                ClientSubredditAssignment.is_active.is_(True),
            )
            .all()
        )
        for a in assignments:
            sub = db.query(Subreddit).filter(Subreddit.id == a.subreddit_id).first()
            if sub:
                allowed_subs.add(sub.subreddit_name.lower())

        if allowed_subs:
            query = query.filter(sa_func.lower(RedditThread.subreddit).in_(allowed_subs))

    # Phase 3: all subreddits — no filter needed

    # Exclude threads that already have drafts from this avatar
    existing_draft_thread_ids = (
        db.query(CommentDraft.thread_id)
        .filter(CommentDraft.avatar_id == avatar.id)
    )
    query = query.filter(~RedditThread.id.in_(existing_draft_thread_ids))

    # Order by alert desc, composite desc, recent first
    threads = (
        query
        .order_by(
            ThreadScore.alert.desc(),
            ThreadScore.composite.desc(),
            RedditThread.scraped_at.desc(),
        )
        .limit(30)
        .all()
    )

    # Build display data
    thread_list = []
    for thread, score in threads:
        thread_list.append({
            "thread": thread,
            "score": score,
        })

    return templates.TemplateResponse(
        name="partials/avatar_pipeline_threads.html",
        context={
            "request": request,
            "threads": thread_list,
            "avatar": avatar,
            "phase": phase,
            "client": client,
            "hobby_mode": False,
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# Step 4: Generate comment for selected thread
# ---------------------------------------------------------------------------


@router.post("/generate/{thread_id}", response_class=HTMLResponse)
def pipeline_generate(
    request: Request,
    avatar_id: uuid.UUID,
    thread_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Generate a comment for the selected thread using this avatar."""
    from app.services.generation import select_persona, generate_comment, edit_comment
    from app.services.safety import check_avatar_can_post, check_subreddit_limit
    from app.services.audit import log_action

    avatar, client = _get_avatar_and_client(db, avatar_id)
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)

    thread = db.query(RedditThread).filter(RedditThread.id == thread_id).first()
    if not thread:
        return HTMLResponse("Thread not found", status_code=404)

    # --- Hobby mode (no client) ---
    if not client:
        comment_type = "hobby"
        safety = check_avatar_can_post(db, avatar, comment_type, thread.subreddit)
        if not safety:
            return HTMLResponse(
                f'<div class="p-4 bg-yellow-900/30 border border-yellow-700 rounded-lg text-yellow-300">'
                f'<span class="font-medium">⚠️ Generation blocked:</span> {safety.reason}<br>'
                f'<span class="text-xs text-yellow-400/70 mt-1 block">Avatar: {avatar.reddit_username} · r/{thread.subreddit}</span></div>',
                status_code=200,
            )

        # Get previous comments for diversity
        previous = (
            db.query(CommentDraft.ai_draft)
            .filter(
                CommentDraft.avatar_id == avatar.id,
                CommentDraft.ai_draft.isnot(None),
            )
            .order_by(CommentDraft.created_at.desc())
            .limit(20)
            .all()
        )
        prev_comments = [p[0] for p in previous if p[0]]

        try:
            from app.services.ai import call_llm, log_ai_usage
            from app.config import get_config
            from app.models.comment_draft import CommentDraft as CD
            import json as json_mod

            # Build hobby generation prompt
            voice = avatar.voice_profile_md or "Casual, helpful community member"
            system_prompt = f"""You are writing a Reddit comment as a regular community member.
Your voice: {voice}

Rules:
- Be SHORT (20-60 words, max 80)
- Be genuine and helpful — this is a hobby subreddit
- No brand mentions, no marketing, no self-promotion
- Match the tone of the subreddit
- Never use em-dashes (—)
- Never start with "I" more than 30% of the time

Previous comments (avoid repetition):
{chr(10).join(f'- {c[:80]}' for c in prev_comments[:5])}

Output JSON:
{{"comment": "the exact comment text", "comment_approach": "helpful_peer"}}"""

            user_prompt = f"""Subreddit: r/{thread.subreddit}
Post title: {thread.post_title}
Post body: {(thread.post_body or '')[:500]}
Upvotes: {thread.ups or 0}
Author: u/{thread.author}"""

            gen_model = get_config("llm_scoring_model") or get_config("llm_generation_model")

            from app.services.ai import call_llm_json
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
                db, None, "hobby_comment_pipeline", result,
                avatar_id=str(avatar.id),
                subreddit_name=thread.subreddit,
            )

            data = result.get("data", {})
            comment_text = data.get("comment", result.get("content", ""))
            comment_approach = data.get("comment_approach", "helpful_peer")

            # Create a CommentDraft so it appears in review queue
            draft = CommentDraft(
                thread_id=thread.id,
                avatar_id=avatar.id,
                client_id=None,
                ai_draft=comment_text,
                original_ai_draft=comment_text,
                status="pending",
                type="hobby",
                comment_approach=comment_approach,
            )
            db.add(draft)
            db.commit()
            db.refresh(draft)

        except Exception as e:
            logger.error(f"Hobby generation failed for avatar {avatar.reddit_username}, thread {thread_id}: {e}")
            return HTMLResponse(
                f'<div class="p-4 bg-red-900/30 border border-red-700 rounded-lg text-red-300">'
                f'<span class="font-medium">Generation failed:</span> {str(e)[:200]}</div>',
                status_code=200,
            )

        return templates.TemplateResponse(
            name="partials/avatar_pipeline_draft.html",
            context={
                "request": request,
                "draft": draft,
                "thread": thread,
                "thread_score": None,
                "avatar": avatar,
                "selection": {"mode": "hobby", "persona_username": avatar.reddit_username},
            },
            request=request,
        )

    # --- Client mode (professional pipeline) ---
    comment_type = "professional"

    # Safety check — pass client + empty comment_text so PhasePolicy enforces
    # subreddit allowlist before we pay for LLM generation. Brand checks are
    # a no-op on empty text and re-applied post-generation by content checks.
    safety = check_avatar_can_post(
        db,
        avatar,
        comment_type,
        target_subreddit=thread.subreddit,
        comment_text="",
        client=client,
    )
    if not safety:
        # Log the block so it's visible in audit logs and activity feed
        log_action(
            db=db,
            user_id=current_user.id,
            action="generation_blocked",
            entity_type="avatar",
            entity_id=avatar.id,
            client_id=client.id,
            details={
                "reason": safety.reason,
                "avatar_username": avatar.reddit_username,
                "thread_id": str(thread_id),
                "subreddit": thread.subreddit,
                "check": "avatar_can_post",
                "source": "pipeline_tab",
            },
        )
        try:
            from app.models.activity_event import ActivityEvent
            event = ActivityEvent(
                event_type="safety_block",
                client_id=client.id,
                message=f"Generation blocked for {avatar.reddit_username} in r/{thread.subreddit}: {safety.reason}",
                event_metadata={
                    "avatar_id": str(avatar.id),
                    "thread_id": str(thread_id),
                    "reason": safety.reason,
                },
            )
            db.add(event)
            db.commit()
        except Exception:
            pass

        return HTMLResponse(
            f'<div class="p-4 bg-yellow-900/30 border border-yellow-700 rounded-lg text-yellow-300">'
            f'<span class="font-medium">⚠️ Generation blocked:</span> {safety.reason}<br>'
            f'<span class="text-xs text-yellow-400/70 mt-1 block">Avatar: {avatar.reddit_username} · Subreddit: r/{thread.subreddit} · Logged to audit</span></div>',
            status_code=200,
        )

    sub_safety = check_subreddit_limit(db, avatar, thread.subreddit)
    if not sub_safety:
        log_action(
            db=db,
            user_id=current_user.id,
            action="generation_blocked",
            entity_type="avatar",
            entity_id=avatar.id,
            client_id=client.id,
            details={
                "reason": sub_safety.reason,
                "avatar_username": avatar.reddit_username,
                "thread_id": str(thread_id),
                "subreddit": thread.subreddit,
                "check": "subreddit_limit",
                "source": "pipeline_tab",
            },
        )
        return HTMLResponse(
            f'<div class="p-4 bg-yellow-900/30 border border-yellow-700 rounded-lg text-yellow-300">'
            f'<span class="font-medium">⚠️ Subreddit limit:</span> {sub_safety.reason}<br>'
            f'<span class="text-xs text-yellow-400/70 mt-1 block">Avatar: {avatar.reddit_username} · Logged to audit</span></div>',
            status_code=200,
        )

    # Get previous comments for diversity
    previous = (
        db.query(CommentDraft.ai_draft)
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.ai_draft.isnot(None),
        )
        .order_by(CommentDraft.created_at.desc())
        .limit(20)
        .all()
    )
    prev_comments = [p[0] for p in previous if p[0]]

    try:
        # Step 1: Persona selection (uses this avatar specifically)
        client_avatars = [avatar]
        selection = select_persona(db, thread, client, client_avatars)

        # Force the selected avatar to be this one
        selection["persona_username"] = avatar.reddit_username

        # Step 2: Generate comment
        draft = generate_comment(db, thread, client, avatar, selection, prev_comments)

        # Step 3: Edit/clean
        edit_comment(db, draft, thread, client)

        # Reload draft after edit
        db.refresh(draft)

    except Exception as e:
        logger.error(f"Generation failed for avatar {avatar.reddit_username}, thread {thread_id}: {e}")
        return HTMLResponse(
            f'<div class="p-4 bg-red-900/30 border border-red-700 rounded-lg text-red-300">'
            f'<span class="font-medium">Generation failed:</span> {str(e)[:200]}</div>',
            status_code=200,
        )

    # Get the thread score for display
    thread_score = (
        db.query(ThreadScore)
        .filter(ThreadScore.thread_id == thread.id, ThreadScore.client_id == client.id)
        .first()
    )

    return templates.TemplateResponse(
        name="partials/avatar_pipeline_draft.html",
        context={
            "request": request,
            "draft": draft,
            "thread": thread,
            "thread_score": thread_score,
            "avatar": avatar,
            "selection": selection,
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# Step 5: Inline draft actions (approve, reject, edit, posted, regenerate)
# ---------------------------------------------------------------------------


@router.post("/drafts/{draft_id}/approve", response_class=HTMLResponse)
def pipeline_approve(
    request: Request,
    avatar_id: uuid.UUID,
    draft_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Approve a draft inline from the pipeline tab."""
    from app.services.audit import log_action

    draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
    if not draft:
        return HTMLResponse('<span class="text-red-400 text-xs">Draft not found</span>')

    draft.status = "approved"
    db.commit()

    log_action(
        db=db,
        user_id=current_user.id,
        action="approve",
        entity_type="comment_draft",
        entity_id=draft.id,
        client_id=draft.client_id,
        details={"avatar_username": draft.avatar.reddit_username if draft.avatar else None, "source": "pipeline_tab"},
    )

    # Self-learning loop
    try:
        from app.services.learning import LearningService

        thread = draft.thread
        if thread:
            if draft.edited_draft and draft.edited_draft != draft.ai_draft:
                learning_status = "approved"
            else:
                learning_status = "approved_unchanged"
            LearningService().capture_edit_record(db=db, draft=draft, thread=thread, status=learning_status)
            db.commit()
    except Exception:
        logger.warning("Learning capture failed for draft %s", draft_id, exc_info=True)

    thread_url = draft.thread.url if draft.thread else ""

    return HTMLResponse(f'''
    <div class="space-y-3">
        <div class="flex items-center gap-2">
            <span class="text-green-400 text-sm font-medium">✓ Approved</span>
            <span class="text-gray-500 text-xs">— now post to Reddit, then mark as posted</span>
        </div>
        <div class="p-3 bg-slate-800/50 rounded-lg border border-slate-700/50">
            <form hx-post="/admin/avatars/{avatar_id}/pipeline/drafts/{draft_id}/posted"
                  hx-target="#pipeline-action-panel-{draft_id}"
                  hx-swap="innerHTML"
                  class="flex flex-wrap gap-2 items-center">
                <input type="url" name="reddit_comment_url" placeholder="Paste Reddit comment URL (optional)"
                       class="flex-1 min-w-[200px] px-3 py-1.5 bg-slate-night border border-slate-600 text-gray-200 rounded text-sm focus:outline-none focus:border-indigo-500">
                <button type="submit"
                        class="bg-purple-600 hover:bg-purple-500 text-white px-3 py-1.5 rounded text-xs font-medium">
                    📤 Mark as Posted
                </button>
                {"<a href='" + thread_url + "' target='_blank' rel='noopener' class='text-xs text-indigo-400 hover:text-indigo-300 ml-2'>Reddit ↗</a>" if thread_url else ""}
            </form>
        </div>
    </div>
    ''')


@router.post("/drafts/{draft_id}/reject", response_class=HTMLResponse)
def pipeline_reject(
    request: Request,
    avatar_id: uuid.UUID,
    draft_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Reject a draft inline from the pipeline tab."""
    from app.services.audit import log_action

    draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
    if not draft:
        return HTMLResponse('<span class="text-red-400 text-xs">Draft not found</span>')

    draft.status = "rejected"
    db.commit()

    log_action(
        db=db,
        user_id=current_user.id,
        action="reject",
        entity_type="comment_draft",
        entity_id=draft.id,
        client_id=draft.client_id,
        details={"avatar_username": draft.avatar.reddit_username if draft.avatar else None, "source": "pipeline_tab"},
    )

    # Self-learning loop
    try:
        from app.services.learning import LearningService

        thread = draft.thread
        if thread:
            LearningService().capture_edit_record(db=db, draft=draft, thread=thread, status="rejected")
            db.commit()
    except Exception:
        logger.warning("Learning capture failed for draft %s", draft_id, exc_info=True)

    thread_id = str(draft.thread_id) if draft.thread_id else ""

    return HTMLResponse(f'''
    <div class="space-y-3">
        <div class="flex items-center gap-2">
            <span class="text-red-400 text-sm font-medium">✗ Rejected</span>
            <span class="text-gray-500 text-xs">— draft discarded</span>
        </div>
        <div class="flex items-center gap-2">
            <button hx-post="/admin/avatars/{avatar_id}/pipeline/regenerate/{thread_id}"
                    hx-target="#pipeline-draft-{draft_id}"
                    hx-swap="outerHTML"
                    class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-amber-600 hover:bg-amber-500 text-white transition-colors">
                🔄 Regenerate for same thread
            </button>
            <span class="text-xs text-gray-500">New approach will be used</span>
        </div>
    </div>
    ''')


@router.post("/drafts/{draft_id}/edit", response_class=HTMLResponse)
def pipeline_edit(
    request: Request,
    avatar_id: uuid.UUID,
    draft_id: uuid.UUID,
    edited_text: str = Form(...),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Save edited text for a draft inline from the pipeline tab."""
    from app.services.audit import log_action

    if len(edited_text) > 2000:
        return HTMLResponse(
            '<span class="text-red-400">Text too long (max 2000 chars)</span>',
            status_code=400,
        )

    draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
    if not draft:
        return HTMLResponse('<span class="text-red-400">Draft not found</span>')

    draft.edited_draft = edited_text
    db.commit()

    log_action(
        db=db,
        user_id=current_user.id,
        action="edit",
        entity_type="comment_draft",
        entity_id=draft.id,
        client_id=draft.client_id,
        details={"avatar_username": draft.avatar.reddit_username if draft.avatar else None, "source": "pipeline_tab"},
    )

    # Return the updated text content (replaces the display div innerHTML)
    return HTMLResponse(edited_text)


@router.post("/drafts/{draft_id}/posted", response_class=HTMLResponse)
def pipeline_mark_posted(
    request: Request,
    avatar_id: uuid.UUID,
    draft_id: uuid.UUID,
    reddit_comment_url: str = Form(""),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Mark a draft as posted from the pipeline tab."""
    from app.services.audit import log_action

    draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
    if not draft:
        return HTMLResponse('<span class="text-red-400 text-xs">Draft not found</span>')

    draft.status = "posted"
    draft.posted_at = datetime.now(timezone.utc)
    if reddit_comment_url.strip():
        draft.reddit_comment_url = reddit_comment_url.strip()
    db.commit()

    log_action(
        db=db,
        user_id=current_user.id,
        action="mark_posted",
        entity_type="comment_draft",
        entity_id=draft.id,
        client_id=draft.client_id,
        details={
            "avatar_username": draft.avatar.reddit_username if draft.avatar else None,
            "reddit_url": reddit_comment_url.strip() if reddit_comment_url.strip() else None,
            "source": "pipeline_tab",
        },
    )

    # Piggyback phase evaluation after posting
    try:
        from app.services.phase import PhaseEvaluator, PhaseTransitionManager
        from app.services.phase_lock import PhaseTransitionLock
        from app.config import get_settings
        import redis

        avatar = draft.avatar
        if avatar and PhaseEvaluator().should_piggyback(avatar):
            result = PhaseEvaluator().evaluate(db, avatar)
            if result.action == "promote":
                redis_client = redis.from_url(get_settings().redis_url)
                lock = PhaseTransitionLock(redis_client)
                PhaseTransitionManager(lock).promote(db, avatar, result.criteria_values)
    except Exception:
        logger.warning("Phase evaluation piggyback failed for draft %s", draft_id, exc_info=True)

    url_display = ""
    if reddit_comment_url.strip():
        url_display = f'<a href="{reddit_comment_url.strip()}" target="_blank" rel="noopener" class="text-xs text-indigo-400 hover:text-indigo-300 ml-2">View on Reddit ↗</a>'

    return HTMLResponse(f'''
    <div class="flex items-center gap-2">
        <span class="text-purple-400 text-sm font-medium">📤 Posted</span>
        <span class="text-gray-500 text-xs">— comment is live on Reddit</span>
        {url_display}
    </div>
    <div class="mt-2 text-xs text-gray-500">
        ✓ Done. Select another thread above to continue.
    </div>
    ''')


# ---------------------------------------------------------------------------
# Regenerate: reject current draft + generate new one for same thread
# ---------------------------------------------------------------------------


@router.post("/regenerate/{thread_id}", response_class=HTMLResponse)
def pipeline_regenerate(
    request: Request,
    avatar_id: uuid.UUID,
    thread_id: uuid.UUID,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Reject the existing draft (if any) and generate a fresh comment for the same thread.

    Uses a different temperature/seed to encourage a different approach.
    """
    from app.services.generation import select_persona, generate_comment, edit_comment
    from app.services.safety import check_avatar_can_post, check_subreddit_limit
    from app.services.audit import log_action

    avatar, client = _get_avatar_and_client(db, avatar_id)
    if not avatar:
        return HTMLResponse("Avatar not found", status_code=404)
    if not client:
        return HTMLResponse("Avatar has no assigned client", status_code=400)

    thread = db.query(RedditThread).filter(RedditThread.id == thread_id).first()
    if not thread:
        return HTMLResponse("Thread not found", status_code=404)

    # Reject any existing pending/approved drafts for this avatar+thread
    existing_drafts = (
        db.query(CommentDraft)
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.thread_id == thread.id,
            CommentDraft.status.in_(["pending", "approved"]),
        )
        .all()
    )
    for old_draft in existing_drafts:
        old_draft.status = "rejected"
        log_action(
            db=db,
            user_id=current_user.id,
            action="reject",
            entity_type="comment_draft",
            entity_id=old_draft.id,
            client_id=old_draft.client_id,
            details={"reason": "regenerate", "source": "pipeline_tab"},
        )
    if existing_drafts:
        db.commit()

    # Safety check — pass client + empty comment_text so PhasePolicy enforces
    # subreddit allowlist (see pipeline_generate for rationale).
    safety = check_avatar_can_post(
        db,
        avatar,
        "professional",
        target_subreddit=thread.subreddit,
        comment_text="",
        client=client,
    )
    if not safety:
        return HTMLResponse(
            f'<div class="p-4 bg-yellow-900/30 border border-yellow-700 rounded-lg text-yellow-300">'
            f'<span class="font-medium">Safety blocked:</span> {safety.reason}</div>',
            status_code=200,
        )

    sub_safety = check_subreddit_limit(db, avatar, thread.subreddit)
    if not sub_safety:
        return HTMLResponse(
            f'<div class="p-4 bg-yellow-900/30 border border-yellow-700 rounded-lg text-yellow-300">'
            f'<span class="font-medium">Subreddit limit:</span> {sub_safety.reason}</div>',
            status_code=200,
        )

    # Get previous comments for diversity (exclude the rejected ones for this thread)
    previous = (
        db.query(CommentDraft.ai_draft)
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.ai_draft.isnot(None),
            CommentDraft.thread_id == thread.id,  # include old drafts for this thread as "avoid" signal
        )
        .order_by(CommentDraft.created_at.desc())
        .limit(5)
        .all()
    )
    # Also get general previous comments for diversity
    general_previous = (
        db.query(CommentDraft.ai_draft)
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.ai_draft.isnot(None),
            CommentDraft.thread_id != thread.id,
        )
        .order_by(CommentDraft.created_at.desc())
        .limit(15)
        .all()
    )
    prev_comments = [p[0] for p in previous if p[0]] + [p[0] for p in general_previous if p[0]]

    try:
        # Persona selection (single avatar)
        client_avatars = [avatar]
        selection = select_persona(db, thread, client, client_avatars)
        selection["persona_username"] = avatar.reddit_username

        # Generate with slightly higher temperature for variety
        draft = generate_comment(db, thread, client, avatar, selection, prev_comments)

        # Edit/clean
        edit_comment(db, draft, thread, client)

        # Reload
        db.refresh(draft)

    except Exception as e:
        logger.error(f"Regeneration failed for avatar {avatar.reddit_username}, thread {thread_id}: {e}")
        return HTMLResponse(
            f'<div class="p-4 bg-red-900/30 border border-red-700 rounded-lg text-red-300">'
            f'<span class="font-medium">Regeneration failed:</span> {str(e)[:200]}</div>',
            status_code=200,
        )

    # Get thread score for display
    thread_score = (
        db.query(ThreadScore)
        .filter(ThreadScore.thread_id == thread.id, ThreadScore.client_id == client.id)
        .first()
    )

    return templates.TemplateResponse(
        name="partials/avatar_pipeline_draft.html",
        context={
            "request": request,
            "draft": draft,
            "thread": thread,
            "thread_score": thread_score,
            "avatar": avatar,
            "selection": selection,
        },
        request=request,
    )
