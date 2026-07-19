"""EPG Executor — generates comments for persisted EPG slots.

This is the bridge between EPG planning and LLM generation.
Each slot is generated independently: hobby via Flash, professional via Sonnet pipeline.

Key principle: generate_epg_slot() takes a slot_id and produces a CommentDraft.
It doesn't decide WHAT to generate — that's EPG's job. It only executes.
"""

from app.logging_config import get_logger
import uuid
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.epg_slot import EPGSlot
from app.models.hobby import HobbySubreddit
from app.models.thread import RedditThread

logger = get_logger(__name__)


def generate_epg_slot(db: Session, slot_id: uuid.UUID) -> CommentDraft | None:
    """Generate a comment for a single EPG slot.

    Handles both hobby and professional slots:
    - Hobby: inline Gemini Flash call (cheap, fast)
    - Professional: select_persona → generate_comment → edit_comment (Sonnet pipeline)

    Returns the created CommentDraft, or None if skipped.
    Updates slot status to 'generated' or 'skipped'.
    """
    slot = db.query(EPGSlot).filter(EPGSlot.id == slot_id).first()
    if not slot:
        logger.error(f"EPG slot {slot_id} not found")
        return None

    if slot.status != "planned":
        logger.info(f"EPG slot {slot_id} is not planned (status={slot.status}), skipping")
        return None

    avatar = db.query(Avatar).filter(Avatar.id == slot.avatar_id).first()
    if not avatar:
        _skip_slot(db, slot, "avatar_not_found")
        return None

    # Health gates
    if avatar.is_frozen:
        _skip_slot(db, slot, f"avatar_frozen: {avatar.freeze_reason or 'no reason'}")
        return None
    if avatar.health_status in ("shadowbanned", "suspended"):
        _skip_slot(db, slot, f"avatar_health: {avatar.health_status}")
        return None

    # Subreddit intelligence freshness gate — warn if stale but don't block
    _check_subreddit_freshness(db, slot)

    if slot.slot_type == "hobby":
        return _generate_hobby_slot(db, slot, avatar)
    elif slot.slot_type == "professional":
        return _generate_professional_slot(db, slot, avatar)
    elif slot.slot_type == "post":
        return _generate_post_slot(db, slot, avatar)
    else:
        _skip_slot(db, slot, f"unknown_slot_type: {slot.slot_type}")
        return None


def _generate_hobby_slot(db: Session, slot: EPGSlot, avatar: Avatar) -> CommentDraft | None:
    """Generate a hobby comment for an EPG slot."""
    from app.config import get_config
    from app.services.ai import call_llm, log_ai_usage

    # Find the hobby post
    hobby_post = db.query(HobbySubreddit).filter(HobbySubreddit.id == slot.hobby_post_id).first()
    if not hobby_post:
        _skip_slot(db, slot, "hobby_post_not_found")
        return None

    # Skip image-only posts — LLM cannot see images
    if not hobby_post.post_body or len(hobby_post.post_body.strip()) < 20:
        _skip_slot(db, slot, "image_only_post_no_text")
        return None

    # Skip hot threads — Match Threads, viral posts with thousands of upvotes
    # are dangerous for low-karma accounts (buried, removed, zero value)
    from app.services.draft_quality_gate import is_hot_thread_for_hobby
    if is_hot_thread_for_hobby(hobby_post.post_ups):
        _skip_slot(db, slot, f"hot_thread:{hobby_post.post_ups}_ups")
        return None

    # Already generated?
    if hobby_post.ai_comment:
        _skip_slot(db, slot, "hobby_already_generated")
        return None

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

        # Build previous comments section for anti-repetition
        prev_section = ""
        if prev_comments:
            prev_section = "\n".join(f"- {c[:100]}" for c in prev_comments[:5])

        system_prompt = f"""# Reddit Comment — Hobby Subreddit

You ARE this person. Not an assistant. Not a coach. Not a content creator. A regular person on Reddit with opinions, blind spots, and a phone.

## Who you are
{voice[:500]}

## The single rule
Write what THIS person would actually type. Not what's helpful. Not what's insightful. What they'd type on the toilet, on the bus, between meetings.

## What real Reddit comments look like
- "honestly I tried this for 2 weeks and nothing happened"
- "wait does this actually work or is it placebo"
- "my physio said the exact opposite lol"
- "had the same issue. ended up just doing X instead"
- "this is wild, I've never seen anyone mention Y before"
- "genuinely curious — how long did it take you?"

## What you MUST NOT do (these are bot signatures)
- Start with praise ("Love that", "Such a smart", "Great point", "Interesting")
- Start with agreement ("Totally agree", "This resonates", "So true")
- Use therapeutic language ("I appreciate you sharing", "Valid point")
- Lecture or explain things nobody asked about
- Offer unsolicited advice framed as questions ("Have you considered...")
- Use hedging qualifiers ("Worth looking into", "You might want to")
- Make vague medical/scientific claims without sources
- Sound supportive when nobody asked for support
- Use em-dashes (—)

## What you CAN do
- Disagree casually ("idk man, that hasn't been my experience")
- Ask a genuine question because you're curious
- Share ONE specific detail from your life (date, place, number, brand)
- Make a joke or sarcastic observation
- Say something short and opinionated
- Admit you don't know something
- Ignore part of the post and respond to one detail that caught your eye

## Structure
- 1 paragraph. 5-60 words (HARD max 80).
- No formatting. No bullets. No signatures.
- Vary sentence structure. Don't always start with "I".
- End naturally — no wrap-up, no closing thought, no encouragement.

## Previous comments (NEVER repeat these patterns):
{prev_section if prev_section else "(none yet)"}

## OUTPUT: Just the comment text. Nothing else."""

        user_prompt = f"""Subreddit: r/{hobby_post.subreddit}
Post title: {hobby_post.post_title}
Post body: {(hobby_post.post_body or '')[:500]}
Upvotes: {hobby_post.post_ups or 0}
{('Top comments: ' + hobby_post.comments[:1500]) if hobby_post.comments else ''}"""

        # --- Inject daily vibe context if available ---
        try:
            from app.services.subreddit_vibe import get_vibe_context_for_prompt
            vibe_ctx = get_vibe_context_for_prompt(db, hobby_post.subreddit)
            if vibe_ctx:
                system_prompt = system_prompt + "\n" + vibe_ctx
        except Exception:
            pass  # Non-blocking: generate without vibe if unavailable

        gen_model = get_config("llm_generation_model")

        # Plain text call (no JSON parsing needed — more reliable with Gemini)
        from app.services.ai import call_llm, log_ai_usage
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
            db, None, "hobby_comment_epg", result,
            avatar_id=str(avatar.id),
            subreddit_name=hobby_post.subreddit,
        )

        comment_text = (result.get("content") or "").strip()

        # Strip common LLM wrapper artifacts
        # Remove JSON wrapper if model still returned it
        if comment_text.startswith('{"comment"'):
            import json as _json
            try:
                comment_text = _json.loads(comment_text).get("comment", comment_text)
            except Exception:
                pass
        # Remove quotes wrapping
        if comment_text.startswith('"') and comment_text.endswith('"'):
            comment_text = comment_text[1:-1]
        # Remove "Comment:" prefix
        for prefix in ("Comment:", "comment:", "Reply:", "reply:"):
            if comment_text.startswith(prefix):
                comment_text = comment_text[len(prefix):].strip()

        # Sentence completeness check — retry if truncated (no .?! ending)
        if comment_text and len(comment_text) > 20:
            last_char = comment_text.rstrip()[-1] if comment_text.rstrip() else ""
            if last_char not in ".?!):;\"'":
                # Likely truncated — one retry with same prompt
                retry_result = call_llm(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    model=gen_model,
                    temperature=0.9,
                    max_tokens=300,
                )
                retry_text = (retry_result.get("content") or "").strip()
                if retry_text.startswith('"') and retry_text.endswith('"'):
                    retry_text = retry_text[1:-1]
                for prefix in ("Comment:", "comment:", "Reply:", "reply:"):
                    if retry_text.startswith(prefix):
                        retry_text = retry_text[len(prefix):].strip()
                # Use retry if it's complete, otherwise keep original
                if retry_text and len(retry_text) > len(comment_text) * 0.5:
                    retry_last = retry_text.rstrip()[-1] if retry_text.rstrip() else ""
                    if retry_last in ".?!):;\"'":
                        comment_text = retry_text
                        log_ai_usage(
                            db, None, "hobby_comment_epg", retry_result,
                            avatar_id=str(avatar.id),
                            subreddit_name=hobby_post.subreddit,
                        )

        # --- Quality gate: reject garbage before it reaches review queue ---
        from app.services.draft_quality_gate import validate_draft_text
        qr = validate_draft_text(comment_text, prev_comments)
        if not qr.ok:
            logger.warning(
                "EPG hobby draft REJECTED by quality gate: avatar=%s sub=r/%s reason=%s text=%s",
                avatar.reddit_username, hobby_post.subreddit, qr.reason, repr(comment_text[:80]),
            )
            _skip_slot(db, slot, f"quality_gate:{qr.reason}")
            return None

        # Save to hobby post
        hobby_post.ai_comment = comment_text
        hobby_post.status = "pending"

        # Create CommentDraft
        draft_client_id = None
        if avatar.client_ids:
            draft_client_id = avatar.client_ids[0]

        draft = CommentDraft(
            id=uuid.uuid4(),
            thread_id=None,
            hobby_post_id=hobby_post.id,
            avatar_id=avatar.id,
            client_id=draft_client_id,
            type="hobby",
            ai_draft=comment_text,
            original_ai_draft=comment_text,
            status="pending",
            comment_approach="hobby_engagement",
        )
        db.add(draft)

        # Update slot
        slot.draft_id = draft.id
        slot.generated_at = datetime.now(timezone.utc)

        # Autopilot: auto-approve if client has autopilot_enabled
        if _should_auto_approve(db, slot.client_id, slot.avatar_id):
            # Hard gate: plan enforcement check before auto-approving
            _plan_ok = True
            if slot.client_id:
                from app.services.plan_enforcement import check_approval_allowed_for_client
                _plan_ok, _ = check_approval_allowed_for_client(db, slot.client_id)
            if _plan_ok:
                slot.status = "approved"
                draft.status = "approved"
                logger.info(
                    "EPG hobby slot AUTO-APPROVED (autopilot): avatar=%s sub=r/%s slot=%s",
                    avatar.reddit_username, hobby_post.subreddit, slot.id,
                )
                # Commit draft+slot so create_execution_task can find them via DB query
                db.commit()
                _dispatch_email_task_if_enabled(db, slot)
            else:
                # Plan limit exceeded — leave as generated (needs manual review or next month)
                slot.status = "generated"
                logger.info(
                    "EPG hobby auto-approve BLOCKED by plan limit: avatar=%s client=%s",
                    avatar.reddit_username, slot.client_id,
                )
                db.commit()
        else:
            slot.status = "generated"
            db.commit()
            # Notify via portal bell that drafts are pending review
            _notify_drafts_pending(db, slot.client_id, avatar, hobby_post.subreddit)

        db.refresh(draft)

        # Audit: log successful generation for pipeline transparency
        _log_slot_generated(db, slot, avatar, hobby_post.subreddit)

        logger.info(
            "EPG hobby slot generated: avatar=%s sub=r/%s slot=%s status=%s",
            avatar.reddit_username, hobby_post.subreddit, slot.id, slot.status,
        )
        return draft

    except Exception as e:
        import traceback
        logger.error(f"EPG hobby generation failed: {e}\n{traceback.format_exc()}")
        _skip_slot(db, slot, f"generation_error: {str(e)[:100]}")
        # Notify ops about generation failure
        _notify_generation_failure(avatar, hobby_post.subreddit, str(e))
        return None


def _generate_professional_slot(db: Session, slot: EPGSlot, avatar: Avatar) -> CommentDraft | None:
    """Generate a professional comment for an EPG slot using full Sonnet pipeline."""
    from app.services.generation import select_persona, generate_comment, edit_comment
    from app.services.safety import check_avatar_can_post, check_subreddit_limit

    thread = db.query(RedditThread).filter(RedditThread.id == slot.thread_id).first()
    if not thread:
        _skip_slot(db, slot, "thread_not_found")
        return None

    # Skip image-only posts — LLM cannot see images
    if not thread.post_body or len(thread.post_body.strip()) < 20:
        _skip_slot(db, slot, "image_only_post_no_text")
        return None

    # Liveness check
    if thread.is_locked:
        _skip_slot(db, slot, "thread_locked")
        return None

    from app.services.thread_liveness import check_and_filter_thread
    if not check_and_filter_thread(db, thread):
        _skip_slot(db, slot, "thread_locked_or_removed")
        return None

    # Client context
    client = db.query(Client).filter(Client.id == slot.client_id).first()
    if not client:
        _skip_slot(db, slot, "client_not_found")
        return None

    # Safety gate
    safety = check_avatar_can_post(
        db, avatar, "professional",
        target_subreddit=thread.subreddit,
        comment_text="",
        client=client,
    )
    if not safety:
        _skip_slot(db, slot, f"safety_blocked: {safety.reason}")
        return None

    sub_safety = check_subreddit_limit(db, avatar, thread.subreddit)
    if not sub_safety:
        _skip_slot(db, slot, f"subreddit_limit: {sub_safety.reason}")
        return None

    try:
        # Get all client avatars for persona selection
        all_avatars = (
            db.query(Avatar)
            .filter(Avatar.active.is_(True))
            .all()
        )
        client_avatars = [
            a for a in all_avatars
            if a.client_ids and str(client.id) in a.client_ids
            and not a.is_frozen
            and not a.is_shadowbanned
            and a.health_status not in ("shadowbanned", "suspended")
        ]

        # Persona selection (skip for single avatar)
        if len(client_avatars) <= 1:
            selection = {
                "persona_username": avatar.reddit_username,
                "mode": "helpful_peer",
                "thread_angle": "",
                "pov_opportunity": "",
                "selection_reasoning": "single avatar — skipped persona selection",
            }
        else:
            selection = select_persona(db, thread, client, client_avatars)
            # Use the selected avatar
            selected_username = selection.get("persona_username")
            selected = next(
                (a for a in client_avatars if a.reddit_username == selected_username),
                avatar,
            )
            avatar = selected

        # Get previous comments for diversity
        previous = (
            db.query(CommentDraft.ai_draft)
            .filter(
                CommentDraft.avatar_id == avatar.id,
                CommentDraft.ai_draft.isnot(None),
                CommentDraft.status.in_(["posted", "approved", "pending"]),
            )
            .order_by(CommentDraft.created_at.desc())
            .limit(20)
            .all()
        )
        prev_comments = [r[0] for r in previous if r[0]]

        # Generate comment (full pipeline: strategy + learning + approach diversity)
        draft = generate_comment(db, thread, client, avatar, selection, prev_comments)

        # Edit/clean
        edit_comment(db, draft, thread, client)

        # Update slot
        slot.draft_id = draft.id
        slot.generated_at = datetime.now(timezone.utc)

        # Autopilot: auto-approve if client has autopilot_enabled
        if _should_auto_approve(db, slot.client_id, slot.avatar_id):
            # Hard gate: plan enforcement check before auto-approving
            _plan_ok = True
            if slot.client_id:
                from app.services.plan_enforcement import check_approval_allowed_for_client
                _plan_ok, _ = check_approval_allowed_for_client(db, slot.client_id)
            if _plan_ok:
                slot.status = "approved"
                draft.status = "approved"
                logger.info(
                    "EPG pro slot AUTO-APPROVED (autopilot): avatar=%s sub=r/%s slot=%s",
                    avatar.reddit_username, thread.subreddit, slot.id,
                )
                # Commit so create_execution_task can find the draft via DB query
                db.commit()
                _dispatch_email_task_if_enabled(db, slot)
            else:
                # Plan limit exceeded — leave as generated
                slot.status = "generated"
                logger.info(
                    "EPG pro auto-approve BLOCKED by plan limit: avatar=%s client=%s",
                    avatar.reddit_username, slot.client_id,
                )
                db.commit()
        else:
            slot.status = "generated"
            db.commit()
            # Notify via portal bell that drafts are pending review
            _notify_drafts_pending(db, slot.client_id, avatar, thread.subreddit)

        # Audit: log successful generation for pipeline transparency
        _log_slot_generated(db, slot, avatar, thread.subreddit)

        logger.info(
            "EPG pro slot generated: avatar=%s sub=r/%s thread='%s' slot=%s status=%s",
            avatar.reddit_username, thread.subreddit, thread.post_title[:40], slot.id, slot.status,
        )
        return draft

    except Exception as e:
        logger.error(f"EPG professional generation failed for slot {slot.id}: {e}")
        _skip_slot(db, slot, f"generation_error: {str(e)[:100]}")
        return None


def _generate_post_slot(db: Session, slot: EPGSlot, avatar: Avatar):
    """Generate a Reddit post for an EPG slot using the post_generation pipeline.

    Flow: topic → brief → write → PostDraft created.
    Returns the PostDraft (for slot tracking) or None on failure.
    """
    from app.services.post_generation import generate_post_topic, generate_post_brief, generate_post

    # Get client
    client = db.query(Client).filter(Client.id == slot.client_id).first()
    if not client:
        _skip_slot(db, slot, "client_not_found")
        return None

    # Phase gate: posts only for Phase 2+
    if avatar.warming_phase < 2:
        _skip_slot(db, slot, f"post_phase_gate: phase={avatar.warming_phase}")
        return None

    subreddit = slot.subreddit
    if not subreddit:
        _skip_slot(db, slot, "no_subreddit_for_post")
        return None

    try:
        # Get previous posts for diversity
        from app.models.post_draft import PostDraft as PostDraftModel
        previous = (
            db.query(PostDraftModel.ai_title)
            .filter(
                PostDraftModel.avatar_id == avatar.id,
                PostDraftModel.ai_title.isnot(None),
            )
            .order_by(PostDraftModel.created_at.desc())
            .limit(5)
            .all()
        )
        prev_posts = [p[0] for p in previous if p[0]]

        # Stage 1: Generate topic direction
        topic = generate_post_topic(db, client, avatar, subreddit, prev_posts)
        if not topic:
            _skip_slot(db, slot, "post_topic_empty")
            return None

        # Stage 2: Generate strategic brief
        brief = generate_post_brief(db, client, avatar, subreddit, topic)
        if not brief:
            _skip_slot(db, slot, "post_brief_empty")
            return None

        # Stage 3: Generate the post
        post_draft = generate_post(db, client, avatar, subreddit, brief, prev_posts)
        if not post_draft:
            _skip_slot(db, slot, "post_generation_failed")
            return None

        # Update slot — link to post_draft (we store PostDraft.id in skip_reason for tracking since
        # draft_id FK points to CommentDraft, not PostDraft)
        slot.generated_at = datetime.now(timezone.utc)
        slot.skip_reason = None  # Clear any previous skip
        # Store post_draft reference in selection_reasoning JSONB
        slot.selection_reasoning = slot.selection_reasoning or {}
        slot.selection_reasoning["post_draft_id"] = str(post_draft.id)
        slot.selection_reasoning["post_title"] = post_draft.ai_title[:100] if post_draft.ai_title else ""

        # Auto-approve if configured
        if _should_auto_approve(db, slot.client_id, slot.avatar_id):
            _plan_ok = True
            if slot.client_id:
                from app.services.plan_enforcement import check_approval_allowed_for_client
                _plan_ok, _ = check_approval_allowed_for_client(db, slot.client_id)
            if _plan_ok:
                slot.status = "approved"
                post_draft.status = "approved"
                logger.info(
                    "EPG post slot AUTO-APPROVED: avatar=%s sub=r/%s slot=%s",
                    avatar.reddit_username, subreddit, slot.id,
                )
            else:
                slot.status = "generated"
        else:
            slot.status = "generated"
            _notify_drafts_pending(db, slot.client_id, avatar, subreddit)

        db.commit()

        _log_slot_generated(db, slot, avatar, subreddit)

        logger.info(
            "EPG post slot generated: avatar=%s sub=r/%s title='%s' slot=%s",
            avatar.reddit_username, subreddit,
            (post_draft.ai_title or "")[:50], slot.id,
        )
        return post_draft

    except Exception as e:
        import traceback
        logger.error(f"EPG post generation failed: {e}\n{traceback.format_exc()}")
        _skip_slot(db, slot, f"post_error: {str(e)[:100]}")
        _notify_generation_failure(avatar, subreddit, str(e))
        return None


def generate_all_planned_slots(
    db: Session,
    avatar_id: uuid.UUID,
    plan_date: date | None = None,
) -> int:
    """Generate comments for all planned slots of an avatar for a given day.

    SAFETY: Enforces absolute daily budget cap. If the avatar already has
    generated/approved/posted slots >= budget, refuses to generate more.
    This prevents over-generation from multiple EPG paths (morning build,
    ensure_minimum, topup, manual triggers) accumulating beyond the limit.

    Returns count of successfully generated slots.
    """
    if plan_date is None:
        plan_date = date.today()

    # --- BUDGET SAFETY GATE ---
    # Hard cap: never generate more than budget allows in a single day,
    # regardless of how many "planned" slots exist.
    from app.services.portfolio_manager import AttentionBudget
    from app.models.avatar import Avatar

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        logger.warning("generate_all_planned_slots: avatar %s not found", avatar_id)
        return 0

    budget = AttentionBudget.from_avatar(avatar)
    already_used = get_budget_used_today(db, avatar_id, plan_date)

    if already_used >= budget.max_total_actions:
        logger.info(
            "generate_all_planned_slots BLOCKED by budget cap: avatar=%s "
            "used=%d >= budget=%d. Skipping generation.",
            avatar.reddit_username, already_used, budget.max_total_actions,
        )
        return 0

    remaining_budget = budget.max_total_actions - already_used

    # --- Pre-compute daily vibe for all subreddits in today's EPG ---
    try:
        from app.services.subreddit_vibe import compute_vibe_for_epg_subreddits
        vibes = compute_vibe_for_epg_subreddits(db, avatar_id, plan_date)
        if vibes:
            logger.info(
                "EPG vibe pre-computed for %d subreddits (avatar=%s)",
                len(vibes), avatar_id,
            )
    except Exception as e:
        logger.warning("EPG vibe pre-compute failed (non-blocking): %s", str(e)[:100])

    slots = (
        db.query(EPGSlot)
        .filter(
            EPGSlot.avatar_id == avatar_id,
            EPGSlot.plan_date == plan_date,
            EPGSlot.status == "planned",
        )
        .order_by(EPGSlot.scheduled_at.asc().nullslast())
        .limit(remaining_budget)  # Never process more than remaining budget
        .all()
    )

    generated = 0
    for slot in slots:
        # Re-check budget before each generation (another path may have
        # generated in parallel between iterations)
        current_used = get_budget_used_today(db, avatar_id, plan_date)
        if current_used >= budget.max_total_actions:
            logger.info(
                "generate_all_planned_slots: budget exhausted mid-loop "
                "avatar=%s used=%d/%d after %d generated",
                avatar.reddit_username, current_used,
                budget.max_total_actions, generated,
            )
            break

        result = generate_epg_slot(db, slot.id)
        if result:
            generated += 1

    logger.info(
        "generate_all_planned_slots: avatar=%s date=%s generated=%d/%d (budget=%d, used=%d)",
        avatar.reddit_username, plan_date, generated, len(slots),
        budget.max_total_actions, already_used + generated,
    )
    return generated


def sync_slot_status(db: Session, draft_id: uuid.UUID, new_status: str) -> None:
    """Sync EPG slot status when a CommentDraft status changes.

    Called from review routes when approve/reject/posted happens.
    Maps draft status → slot status:
      approved → approved
      rejected → skipped (skip_reason = "rejected_by_reviewer")
      posted   → posted (posted_at = now)
    """
    slot = db.query(EPGSlot).filter(EPGSlot.draft_id == draft_id).first()
    if not slot:
        return  # Draft not linked to an EPG slot (legacy draft)

    if new_status == "approved":
        slot.status = "approved"
        # --- Email Task Delivery hook ---
        _dispatch_email_task_if_enabled(db, slot)
    elif new_status == "rejected":
        slot.status = "skipped"
        slot.skip_reason = "rejected_by_reviewer"
    elif new_status == "posted":
        slot.status = "posted"
        slot.posted_at = datetime.now(timezone.utc)

    # No commit here — caller is responsible for committing


def get_budget_used_today(db: Session, avatar_id: uuid.UUID, plan_date: date | None = None) -> int:
    """Count slots that consumed budget today (comments + posts combined).

    Budget is consumed by:
    - EPG slots: generated, approved, posted — successful generation
    - EPG slots: skipped WITH draft_id — generation succeeded but posting failed
    - PostDrafts: created today (pending/approved/posted) — post generation counts toward daily total

    Only 'planned' EPG slots are free (not yet attempted).
    """
    from sqlalchemy import func as sa_func

    if plan_date is None:
        plan_date = date.today()

    # Count EPG slots that consumed budget
    from sqlalchemy import or_, and_

    comment_count = (
        db.query(sa_func.count(EPGSlot.id))
        .filter(
            EPGSlot.avatar_id == avatar_id,
            EPGSlot.plan_date == plan_date,
            or_(
                EPGSlot.status.in_(["generated", "approved", "posted"]),
                and_(EPGSlot.status == "skipped", EPGSlot.draft_id.isnot(None)),
            ),
        )
        .scalar()
    ) or 0

    # Count PostDrafts created today (non-rejected) as consumed post budget
    from app.models.post_draft import PostDraft
    from datetime import datetime, timezone as tz

    today_start = datetime.combine(plan_date, datetime.min.time()).replace(tzinfo=tz.utc)
    today_end = datetime.combine(plan_date, datetime.max.time()).replace(tzinfo=tz.utc)

    post_count = (
        db.query(sa_func.count(PostDraft.id))
        .filter(
            PostDraft.avatar_id == avatar_id,
            PostDraft.created_at >= today_start,
            PostDraft.created_at <= today_end,
            PostDraft.status.notin_(["rejected"]),
        )
        .scalar()
    ) or 0

    return comment_count + post_count


def _notify_drafts_pending(db: Session, client_id, avatar: Avatar, subreddit: str) -> None:
    """Emit notifications that a draft is pending review.

    Non-blocking, non-critical. Fires SSE notification to client portal + Telegram.
    """
    # Portal bell (SSE)
    try:
        from app.services.notifications import notify_client
        if client_id:
            notify_client(
                db,
                client_id=client_id,
                type="info",
                title="New draft ready for review",
                body=f"u/{avatar.reddit_username} has a new comment for r/{subreddit} waiting for approval.",
                link=f"/clients/{client_id}/review",
            )
    except Exception:
        pass  # Non-critical — don't break generation pipeline

    # Telegram draft review notifications
    try:
        from app.services.settings import get_setting
        if get_setting(db, "telegram_draft_review_enabled") == "true":
            from app.services.telegram.draft_review import TelegramDraftReview
            from app.models.comment_draft import CommentDraft
            # Get recently generated pending drafts for this avatar + client
            pending_drafts = (
                db.query(CommentDraft)
                .filter(
                    CommentDraft.avatar_id == avatar.id,
                    CommentDraft.client_id == client_id,
                    CommentDraft.status == "pending",
                )
                .order_by(CommentDraft.created_at.desc())
                .limit(10)
                .all()
            )
            if pending_drafts:
                TelegramDraftReview().notify_pending_drafts(db, str(client_id), pending_drafts)
    except Exception:
        pass  # Non-critical — don't break generation pipeline


def _notify_generation_failure(avatar: Avatar, subreddit: str, error_msg: str) -> None:
    """Notify ops (Telegram + admin bell) about EPG generation failure.

    Non-blocking, non-critical. Debounced via Redis key to avoid spam.
    """
    try:
        import redis
        from app.config import get_settings

        # Debounce: max 1 notification per avatar per hour for same error category
        r = redis.from_url(get_settings().redis_url)
        error_category = "credits" if "credit balance" in error_msg.lower() else "generation"
        dedup_key = f"ramp:ops_notify_dedup:{avatar.id}:{error_category}"
        if r.exists(dedup_key):
            r.close()
            return
        r.setex(dedup_key, 3600, "1")  # 1 hour cooldown

        # Set client degradation flag (visible in portal as banner)
        if avatar.client_ids:
            for cid in avatar.client_ids:
                r.setex(f"ramp:generation_degraded:{cid}", 14400, error_category)  # 4h TTL

        r.close()

        from app.services.ops_notifications import notify_ops

        # Detect specific failure types
        if "credit balance" in error_msg.lower():
            notify_ops(
                level="critical",
                title="🔴 LLM Credits Exhausted",
                body=f"Anthropic API: credits too low. Fallback generation blocked.\n"
                     f"Avatar: u/{avatar.reddit_username}, sub: r/{subreddit}.\n"
                     f"Action: top up credits at console.anthropic.com",
                category="llm_credits",
                link="/admin/settings",
            )
        elif "empty response" in error_msg.lower():
            notify_ops(
                level="warning",
                title="⚠️ LLM Empty Response",
                body=f"Generation returned empty for u/{avatar.reddit_username} in r/{subreddit}.\n"
                     f"Primary model failed, fallback also failed.",
                category="llm_failure",
            )
        else:
            notify_ops(
                level="warning",
                title="⚠️ EPG Generation Failed",
                body=f"u/{avatar.reddit_username} in r/{subreddit}: {error_msg[:200]}",
                category="llm_failure",
            )
    except Exception:
        pass  # Non-critical — never break pipeline


def _check_subreddit_freshness(db: Session, slot: EPGSlot) -> None:
    """Check if subreddit has fresh emotional profile + risk profile.

    Emits activity event if stale. Does NOT block generation (fail-open).
    This is observability — the daily intelligence task handles actual refresh.
    """
    from datetime import timedelta
    from app.models.subreddit import Subreddit
    from app.models.subreddit_risk_profile import SubredditRiskProfile

    subreddit_name = slot.subreddit
    if not subreddit_name:
        return

    now = datetime.now(timezone.utc)
    stale_threshold = now - timedelta(days=7)

    try:
        sub = (
            db.query(Subreddit)
            .filter(Subreddit.subreddit_name.ilike(subreddit_name))
            .first()
        )
        if not sub:
            return

        issues = []

        # Check emotional profile freshness
        if sub.emotional_profile_analyzed_at is None:
            issues.append("emotional_never_analyzed")
        elif sub.emotional_profile_analyzed_at < stale_threshold:
            days_stale = (now - sub.emotional_profile_analyzed_at).days
            issues.append(f"emotional_stale_{days_stale}d")

        # Check risk profile freshness
        risk_profile = (
            db.query(SubredditRiskProfile)
            .filter(SubredditRiskProfile.subreddit_id == sub.id)
            .first()
        )
        if risk_profile is None:
            issues.append("risk_profile_missing")
        elif risk_profile.next_check_at and risk_profile.next_check_at < now:
            days_overdue = (now - risk_profile.next_check_at).days
            issues.append(f"risk_overdue_{days_overdue}d")

        if issues:
            from app.services.transparency import record_activity_event
            record_activity_event(
                db=db,
                event_type="subreddit_intelligence_stale",
                message=f"Generating for r/{subreddit_name} with stale intelligence: {', '.join(issues)}",
                metadata={
                    "subreddit": subreddit_name,
                    "slot_id": str(slot.id),
                    "issues": issues,
                },
                avatar_id=slot.avatar_id,
            )

    except Exception as e:
        # Never block generation on freshness check failure
        logger.debug("Freshness check failed for r/%s: %s", subreddit_name, str(e)[:100])


def _skip_slot(db: Session, slot: EPGSlot, reason: str) -> None:
    """Mark a slot as skipped with a reason."""
    slot.status = "skipped"
    slot.skip_reason = reason
    db.commit()
    logger.info(f"EPG slot {slot.id} skipped: {reason}")

    # Log generation errors to audit for admin visibility
    if "generation_error" in reason or "error" in reason.lower():
        try:
            from app.services.audit import log_system_action

            # Resolve avatar username for searchability in audit logs
            avatar_username = None
            try:
                avatar = db.query(Avatar).filter(Avatar.id == slot.avatar_id).first()
                avatar_username = avatar.reddit_username if avatar else None
            except Exception:
                pass

            log_system_action(
                db=db,
                action="generation_error",
                entity_type="epg_slot",
                entity_id=slot.id,
                client_id=slot.client_id,
                details={
                    "slot_id": str(slot.id),
                    "avatar_id": str(slot.avatar_id),
                    "avatar_username": avatar_username,
                    "thread_id": str(slot.thread_id) if slot.thread_id else None,
                    "reason": reason,
                },
            )
        except Exception:
            db.rollback()


def _should_auto_approve(db: Session, client_id: uuid.UUID | None, avatar_id: uuid.UUID | None = None) -> bool:
    """Check if client or avatar has auto-approve enabled.

    Auto-approve triggers if:
    - Client has autopilot_enabled=True (all avatars for that client), OR
    - Avatar has auto_approve_drafts=True (per-avatar override)
    """
    # Avatar-level override
    if avatar_id:
        try:
            from app.models.avatar import Avatar
            avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
            if avatar and avatar.auto_approve_drafts:
                return True
        except Exception:
            pass

    # Client-level autopilot
    if not client_id:
        return False
    try:
        from app.models.client import Client
        client = db.query(Client).filter(Client.id == client_id).first()
        return bool(client and client.autopilot_enabled)
    except Exception:
        return False


def _log_slot_generated(db: Session, slot: EPGSlot, avatar: Avatar, subreddit: str) -> None:
    """Log successful slot generation to audit for pipeline transparency."""
    try:
        from app.services.audit import log_system_action
        log_system_action(
            db=db,
            action="epg_slot_generated",
            entity_type="epg_slot",
            entity_id=slot.id,
            client_id=slot.client_id,
            details={
                "slot_id": str(slot.id),
                "avatar_id": str(slot.avatar_id),
                "avatar_username": avatar.reddit_username,
                "subreddit": subreddit,
                "slot_type": slot.slot_type,
                "status": slot.status,  # "generated" or "approved" (autopilot)
                "plan_date": str(slot.plan_date),
            },
        )
    except Exception:
        pass  # Non-critical — don't fail generation on audit error

def _dispatch_email_task_if_enabled(db, slot) -> None:
    """Create an execution task for approved slot.

    For email delivery: gated by email_tasks_enabled setting.
    For extension delivery: always creates task (extension polls independently).

    The task is created with status='generated' but NOT delivered immediately.
    A separate Beat task (dispatch_due_email_tasks, every 5 min) handles actual
    email delivery ~30 min before slot.scheduled_at.

    This prevents email spam — executor gets ONE email at a time, close to when
    they need to act, not a batch dump at EPG generation time.

    Fire-and-forget: errors here never break the approval flow.
    """
    try:
        from app.services.settings import get_setting

        # Determine avatar's delivery channel
        delivery_channel = "email"
        if slot.avatar:
            delivery_channel = getattr(slot.avatar, "delivery_channel", "email") or "email"
        else:
            from app.models.avatar import Avatar
            avatar_obj = db.query(Avatar).filter(Avatar.id == slot.avatar_id).first()
            if avatar_obj:
                delivery_channel = getattr(avatar_obj, "delivery_channel", "email") or "email"

        # Extension channel: always create task (extension polls for it)
        # Email channel: gated by email_tasks_enabled setting
        if delivery_channel == "email":
            if get_setting(db, "email_tasks_enabled") != "true":
                return
        # "both" channel: create task regardless (extension can pick it up;
        # email delivery is separately gated in dispatch_due_email_tasks)

        from app.services.execution_tasks import create_execution_task
        task = create_execution_task(db, slot.id)
        if task:
            db.commit()  # Ensure task is persisted
            # NOTE: No immediate deliver_execution_task.delay() here.
            # dispatch_due_email_tasks Beat task will send the email
            # ~30 min before slot.scheduled_at.
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "Email task creation failed for slot %s (non-critical): %s", slot.id, e
        )
