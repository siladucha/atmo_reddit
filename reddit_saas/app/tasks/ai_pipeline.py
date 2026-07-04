"""Celery tasks for AI pipeline: scoring, persona selection, comment generation."""

from app.logging_config import get_logger
import uuid

import redis
import sqlalchemy as sa
from sqlalchemy import func

from app.tasks.worker import celery_app
from app.config import get_settings
from app.database import SessionLocal
from app.models.client import Client
from app.models.thread import RedditThread
from app.models.thread_score import ThreadScore
from app.models.avatar import Avatar
from app.models.comment_draft import CommentDraft
from app.services.generation import select_persona, generate_comment, edit_comment
from app.services.transparency import record_activity_event
from app.services.ai import ai_trigger_context, reset_task_call_counter

logger = get_logger(__name__)


@celery_app.task(name="score_threads", bind=True, max_retries=3)
def score_threads(self, client_id: str, triggered_by: str = "scheduler"):
    """Smart Score — avatar-centric thread scoring for a client.

    Instead of scoring ALL unscored threads (wasteful), iterates over the
    client's active avatars and scores only threads each avatar can engage
    with, limited by their daily budget.

    This reduces scoring calls from 300+/run to 10-30/run total.
    """
    ai_trigger_context.set(triggered_by)
    reset_task_call_counter()  # R-AI-007: reset per-task LLM call counter
    db = SessionLocal()
    try:
        from app.services.settings import is_pipeline_enabled
        if triggered_by != "manual" and not is_pipeline_enabled(db):
            logger.info("score_threads: pipeline_enabled=false, skipping")
            return 0

        try:
            client = db.query(Client).filter(Client.id == client_id).first()
            if not client:
                logger.error(f"Client {client_id} not found")
                return 0
            if not client.is_active:
                logger.info(f"score_threads: client {client.client_name} is deactivated, skipping")
                return 0
            from app.services.trial_guard import is_trial_expired
            if is_trial_expired(client):
                logger.info(f"score_threads: client {client.client_name} trial expired, skipping")
                return 0

            # Smart scoring: iterate over eligible avatars
            from app.services.smart_scoring import smart_score_for_avatar

            avatars = (
                db.query(Avatar)
                .filter(Avatar.active.is_(True))
                .all()
            )
            client_avatars = [
                a for a in avatars
                if a.client_ids and str(client.id) in a.client_ids
                and not a.is_frozen
                and not a.is_shadowbanned
                and a.health_status not in ("shadowbanned", "suspended")
                and getattr(a, "pool", "b2b") in ("b2b", "b2c", "warm")  # Pipeline-eligible pools (excludes mentor)
            ]

            total_scored = 0
            total_engage = 0
            total_monitor = 0
            total_skip = 0

            for avatar in client_avatars:
                result = smart_score_for_avatar(db, avatar, client)
                total_scored += result.threads_scored
                total_engage += result.engage_count
                total_monitor += len(result.monitor_threads)
                total_skip += len(result.skip_threads)

                logger.info(
                    "score_threads: avatar=%s status=%s scored=%d engage=%d",
                    avatar.reddit_username,
                    result.status,
                    result.threads_scored,
                    result.engage_count,
                )

            # Record activity event
            try:
                message = (
                    f"Smart scored {total_scored} threads across "
                    f"{len(client_avatars)} avatars: "
                    f"{total_engage} engage, {total_monitor} monitor, {total_skip} skip"
                )
                metadata = {
                    "threads_scored": total_scored,
                    "engage": total_engage,
                    "monitor": total_monitor,
                    "skip": total_skip,
                    "avatars_processed": len(client_avatars),
                    "mode": "smart_score",
                }
                record_activity_event(db, "score", message, uuid.UUID(client_id), metadata)
            except Exception:
                logger.exception("Failed to record score activity event")

            # Audit log for scoring batch completion
            try:
                from app.services.audit import log_system_action
                log_system_action(
                    db,
                    action="scoring_batch_completed",
                    entity_type="thread",
                    client_id=uuid.UUID(client_id),
                    details={
                        "threads_scored": total_scored,
                        "engage": total_engage,
                        "monitor": total_monitor,
                        "skip": total_skip,
                    },
                )
            except Exception:
                logger.exception("Failed to record scoring_batch_completed audit log")

            return total_scored

        except Exception as exc:
            # Record system error event
            try:
                record_activity_event(
                    db,
                    "system",
                    f"Scoring failed for client {client_id}: {exc}",
                    uuid.UUID(client_id),
                    {"error": str(exc)},
                )
            except Exception:
                logger.exception("Failed to record system error activity event")
            try:
                from app.services.audit import log_system_action
                log_system_action(
                    db=db,
                    action="error",
                    entity_type="task",
                    client_id=uuid.UUID(client_id),
                    details={"task": "score_threads", "error": str(exc)[:500]},
                )
            except Exception:
                pass
            countdown = 60 * (2 ** self.request.retries)
            logger.warning(
                f"score_threads retry {self.request.retries + 1}/3 "
                f"for client {client_id}, countdown={countdown}s: {exc}"
            )
            raise self.retry(exc=exc, countdown=countdown)

    finally:
        db.close()


@celery_app.task(name="generate_comments", bind=True, max_retries=3)
def generate_comments(self, client_id: str, max_comments: int = 15, triggered_by: str = "scheduler"):
    """Generate comments for top 'engage' threads.

    Full pipeline: select persona → generate comment → edit comment.
    """
    ai_trigger_context.set(triggered_by)
    reset_task_call_counter()  # R-AI-007: reset per-task LLM call counter
    db = SessionLocal()
    try:
        from app.services.settings import is_pipeline_enabled, is_generation_enabled
        if triggered_by != "manual" and not is_pipeline_enabled(db):
            logger.info("generate_comments: pipeline_enabled=false, skipping")
            return 0
        if triggered_by != "manual" and not is_generation_enabled(db):
            logger.info("generate_comments: generation_enabled=false, skipping")
            return 0

        try:
            client = db.query(Client).filter(Client.id == client_id).first()
            if not client:
                logger.error(f"Client {client_id} not found")
                return 0
            if not client.is_active:
                logger.info(f"generate_comments: client {client.client_name} is deactivated, skipping")
                return 0
            from app.services.trial_guard import is_trial_expired
            if is_trial_expired(client):
                logger.info(f"generate_comments: client {client.client_name} trial expired, skipping")
                return 0

            # Get active avatars for this client
            avatars = (
                db.query(Avatar)
                .filter(Avatar.active.is_(True))
                .all()
            )
            # Filter avatars that serve this client (skip frozen + shadowbanned + unhealthy + mentors)
            # Shadowban filter saves ~$0.06/thread in wasted LLM calls
            # CQS gate: professional pipeline excludes CQS lowest regardless of phase.
            # Fresh avatars warm up via hobby pipeline only.
            # Mentor (phase 0) avatars are excluded from all automated pipelines.
            client_avatars = [
                a for a in avatars
                if a.client_ids and str(client.id) in a.client_ids
                and not a.is_frozen
                and not a.is_shadowbanned
                and a.health_status not in ("shadowbanned", "suspended")
                and a.cqs_level != "lowest"  # CQS lowest → hobby only, no brand comments
                and getattr(a, "pool", "b2b") in ("b2b", "b2c", "warm")  # Pipeline-eligible pools (excludes mentor)
            ]

            # Log avatars excluded due to health_status
            for a in avatars:
                if (a.client_ids and str(client.id) in a.client_ids
                        and not a.is_frozen
                        and not a.is_shadowbanned
                        and a.health_status in ("shadowbanned", "suspended")):
                    logger.warning(
                        "generate_comments: avatar %s excluded, health_status=%s",
                        a.reddit_username, a.health_status,
                    )
                elif (a.client_ids and str(client.id) in a.client_ids
                        and not a.is_frozen
                        and a.cqs_level == "lowest"):
                    logger.warning(
                        "generate_comments: avatar %s excluded, cqs_level=lowest",
                        a.reddit_username,
                    )

            if not client_avatars:
                logger.warning(
                    "generate_comments: no eligible avatars for client %s (all excluded by health_status or other filters)",
                    client.client_name,
                )
                return 0

            # A/B Test: filter out avatars forced to hobby-only content type
            from app.services.settings import get_setting
            if get_setting(db, "ab_test_enabled") == "true":
                from app.services.ab_test.control_enforcer import get_forced_content_type
                pre_ab_count = len(client_avatars)
                client_avatars = [
                    a for a in client_avatars
                    if get_forced_content_type(db, a.id) != "hobby"
                ]
                ab_excluded = pre_ab_count - len(client_avatars)
                if ab_excluded > 0:
                    logger.info(
                        "generate_comments: %d avatar(s) excluded by A/B test "
                        "(forced content_type=hobby) for client %s",
                        ab_excluded, client.client_name,
                    )
                if not client_avatars:
                    logger.info(
                        "generate_comments: all avatars for client %s excluded by A/B test (hobby-only)",
                        client.client_name,
                    )
                    return 0

            # Get engage threads that don't have drafts yet
            threads_with_drafts = (
                db.query(CommentDraft.thread_id)
                .filter(CommentDraft.client_id == client_id)
                .subquery()
            )

            # Only consider threads in subreddits still actively assigned to this client
            from app.models.subreddit import ClientSubredditAssignment
            active_subreddit_ids = (
                db.query(ClientSubredditAssignment.subreddit_id)
                .filter(
                    ClientSubredditAssignment.client_id == client_id,
                    ClientSubredditAssignment.is_active.is_(True),
                )
                .subquery()
            )

            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)

            # Query threads via ThreadScore for this client with tag='engage'
            # NOTE: Image-only posts (empty post_body) are excluded — LLM cannot
            # see images and would generate nonsensical comments.
            # Age filter: skip threads older than 7 days — replying to old threads
            # looks suspicious and reduces engagement value.
            from datetime import timedelta as _td
            max_thread_age = now - _td(days=7)

            engage_threads = (
                db.query(RedditThread)
                .join(ThreadScore, ThreadScore.thread_id == RedditThread.id)
                .filter(
                    ThreadScore.client_id == client_id,
                    ThreadScore.tag == "engage",
                    RedditThread.subreddit_id.in_(active_subreddit_ids),
                    RedditThread.is_locked.is_(False),
                    RedditThread.post_body.isnot(None),
                    func.length(RedditThread.post_body) > 20,
                    # Skip link/video/image posts (external URLs)
                    sa.or_(
                        RedditThread.url.is_(None),
                        RedditThread.url == "",
                        RedditThread.url.like("%reddit.com%"),
                    ),
                    ~RedditThread.id.in_(db.query(threads_with_drafts.c.thread_id)),
                    # Thread age filter: prefer reddit_created_at, fallback to created_at
                    sa.or_(
                        sa.and_(
                            RedditThread.reddit_created_at.isnot(None),
                            RedditThread.reddit_created_at >= max_thread_age,
                        ),
                        sa.and_(
                            RedditThread.reddit_created_at.is_(None),
                            RedditThread.created_at >= max_thread_age,
                        ),
                    ),
                )
                .order_by(
                    ThreadScore.alert.desc(),
                    ThreadScore.composite.desc(),
                    RedditThread.created_at.desc(),
                )
                .limit(max_comments)
                .all()
            )

            if not engage_threads:
                logger.info(f"No new engage threads for {client.client_name}")
                return 0

            # --- Fitness Gate: block unsafe avatar-subreddit pairings (Req 8.1-8.6) ---
            from app.services.settings import is_fitness_gate_enabled
            if is_fitness_gate_enabled(db):
                from app.services.fitness_gate import evaluate_fitness
                filtered_threads = []
                fitness_blocked_count = 0
                for thread in engage_threads:
                    # Evaluate each thread against each avatar that might be selected.
                    # Since persona selection happens inside the generation loop, we use
                    # the first available avatar for pre-filtering. If multiple avatars
                    # exist, the per-avatar gate in evaluate_fitness checks the specific
                    # avatar's karma/age. For single-avatar clients this is exact.
                    # For multi-avatar, we use the first avatar as a representative check.
                    gate_avatar = client_avatars[0] if len(client_avatars) == 1 else None
                    if gate_avatar is None:
                        # Multi-avatar: evaluate with each avatar, pass if ANY avatar can engage
                        any_passed = False
                        blocking_result = None
                        for candidate in client_avatars:
                            result = evaluate_fitness(db, candidate, thread.subreddit)
                            if result.passed:
                                any_passed = True
                                break
                            else:
                                blocking_result = result
                        if any_passed:
                            filtered_threads.append(thread)
                        else:
                            fitness_blocked_count += 1
                            # Log fitness_block event (Req 8.3)
                            try:
                                record_activity_event(
                                    db,
                                    "fitness_block",
                                    (
                                        f"Fitness gate blocked thread in r/{thread.subreddit}: "
                                        f"{blocking_result.blocked_by} — {blocking_result.reason}"
                                    ),
                                    uuid.UUID(client_id),
                                    {
                                        "avatar": client_avatars[0].reddit_username,
                                        "thread_id": str(thread.id),
                                        "thread_reddit_id": thread.reddit_native_id,
                                        "subreddit": thread.subreddit,
                                        "rule": blocking_result.blocked_by,
                                        "reason": blocking_result.reason,
                                    },
                                )
                            except Exception:
                                logger.exception("Failed to record fitness_block event")
                    else:
                        # Single avatar: evaluate directly
                        result = evaluate_fitness(db, gate_avatar, thread.subreddit)
                        if result.passed:
                            filtered_threads.append(thread)
                        else:
                            fitness_blocked_count += 1
                            # Log fitness_block event (Req 8.3)
                            try:
                                record_activity_event(
                                    db,
                                    "fitness_block",
                                    (
                                        f"Fitness gate blocked {gate_avatar.reddit_username} "
                                        f"in r/{thread.subreddit}: {result.blocked_by} — {result.reason}"
                                    ),
                                    uuid.UUID(client_id),
                                    {
                                        "avatar": gate_avatar.reddit_username,
                                        "thread_id": str(thread.id),
                                        "thread_reddit_id": thread.reddit_native_id,
                                        "subreddit": thread.subreddit,
                                        "rule": result.blocked_by,
                                        "reason": result.reason,
                                    },
                                )
                            except Exception:
                                logger.exception("Failed to record fitness_block event")

                # Decrement budget: blocked threads count as consumed (Req 8.2)
                # max_comments effectively reduced by blocked count
                max_comments = max(0, max_comments - fitness_blocked_count)

                # Log if all threads were blocked (Req 8.6)
                if fitness_blocked_count > 0 and not filtered_threads:
                    try:
                        record_activity_event(
                            db,
                            "fitness_zero_eligible",
                            (
                                f"Fitness gate blocked ALL {fitness_blocked_count} engage threads "
                                f"for client {client.client_name} — no threads passed fitness check"
                            ),
                            uuid.UUID(client_id),
                            {
                                "blocked_count": fitness_blocked_count,
                                "client": client.client_name,
                                "avatars": [a.reddit_username for a in client_avatars],
                            },
                        )
                    except Exception:
                        logger.exception("Failed to record fitness_zero_eligible event")

                if fitness_blocked_count > 0:
                    logger.info(
                        "FITNESS_GATE | client=%s | blocked=%d | passed=%d",
                        client.client_name,
                        fitness_blocked_count,
                        len(filtered_threads),
                    )

                engage_threads = filtered_threads

                if not engage_threads:
                    logger.info(
                        "generate_comments: all engage threads blocked by fitness gate for %s",
                        client.client_name,
                    )
                    return 0

            # Get previous comments for diversity check — per avatar
            # We'll build per-avatar prev_comments inside the loop below.
            # Initialize a cache so we only query once per avatar.
            _avatar_prev_cache: dict[str, list[str]] = {}

            def _get_prev_comments_for_avatar(avatar_id_str: str) -> list[str]:
                """Fetch last 20 posted/pending comments for an avatar (cached)."""
                if avatar_id_str not in _avatar_prev_cache:
                    recent = (
                        db.query(CommentDraft.ai_draft)
                        .filter(
                            CommentDraft.avatar_id == avatar_id_str,
                            CommentDraft.ai_draft.isnot(None),
                            CommentDraft.status.in_(["posted", "approved", "pending"]),
                        )
                        .order_by(CommentDraft.created_at.desc())
                        .limit(20)
                        .all()
                    )
                    _avatar_prev_cache[avatar_id_str] = [r[0] for r in recent if r[0]]
                return list(_avatar_prev_cache[avatar_id_str])

            prev_comments: list[str] = []  # will be set per-avatar in loop

            generated = 0
            for thread in engage_threads:
                try:
                    # Step 0: Liveness check for stale threads (avoid wasting LLM on locked threads)
                    from app.services.thread_liveness import check_and_filter_thread
                    if not check_and_filter_thread(db, thread):
                        logger.info(f"Thread {thread.reddit_native_id} is locked/removed, skipping generation")
                        continue

                    # Step 1: Safety check
                    from app.services.safety import check_avatar_can_post, check_subreddit_limit

                    # Step 2: Select persona (skip LLM call for single-avatar clients)
                    if len(client_avatars) == 1:
                        avatar = client_avatars[0]
                        selection = {
                            "persona_username": avatar.reddit_username,
                            "mode": "helpful_peer",
                            "thread_angle": "",
                            "pov_opportunity": "",
                            "selection_reasoning": "single avatar — skipped persona selection",
                        }
                    else:
                        selection = select_persona(db, thread, client, client_avatars)

                        # Find the selected avatar
                        selected_username = selection.get("persona_username")
                        avatar = next(
                            (a for a in client_avatars if a.reddit_username == selected_username),
                            client_avatars[0],  # fallback to first avatar
                        )

                    # Step 3: Safety gate.
                    # Pass target_subreddit + client so PhasePolicy enforces
                    # subreddit allowlist BEFORE we pay for LLM generation.
                    # comment_text="" makes brand-mention checks no-op at this
                    # stage (draft doesn't exist yet); brand classification is
                    # repeated post-generation by check_comment_content.
                    safety = check_avatar_can_post(
                        db,
                        avatar,
                        "professional",
                        target_subreddit=thread.subreddit,
                        comment_text="",
                        client=client,
                    )
                    if not safety:
                        logger.info(f"Safety blocked {avatar.reddit_username}: {safety.reason}")
                        # Log to activity feed for visibility
                        try:
                            from app.models.activity_event import ActivityEvent
                            event = ActivityEvent(
                                event_type="safety_block",
                                client_id=client.id,
                                message=f"Generation blocked for {avatar.reddit_username} in r/{thread.subreddit}: {safety.reason}",
                                event_metadata={
                                    "avatar_id": str(avatar.id),
                                    "thread_id": str(thread.id),
                                    "reason": safety.reason,
                                    "source": "auto_pipeline",
                                },
                            )
                            db.add(event)
                            db.commit()
                        except Exception:
                            pass
                        continue

                    sub_safety = check_subreddit_limit(db, avatar, thread.subreddit)
                    if not sub_safety:
                        logger.info(f"Subreddit limit for {avatar.reddit_username}: {sub_safety.reason}")
                        try:
                            from app.models.activity_event import ActivityEvent
                            event = ActivityEvent(
                                event_type="safety_block",
                                client_id=client.id,
                                message=f"Subreddit limit for {avatar.reddit_username} in r/{thread.subreddit}: {sub_safety.reason}",
                                event_metadata={
                                    "avatar_id": str(avatar.id),
                                    "thread_id": str(thread.id),
                                    "reason": sub_safety.reason,
                                    "source": "auto_pipeline",
                                },
                            )
                            db.add(event)
                            db.commit()
                        except Exception:
                            pass
                        continue

                    # Step 4: Generate comment (with per-avatar previous comments)
                    prev_comments = _get_prev_comments_for_avatar(str(avatar.id))
                    draft = generate_comment(
                        db, thread, client, avatar, selection, prev_comments
                    )

                    # Step 5: Embedding diversity check (reject if too similar to previous)
                    try:
                        from app.services.embedding import check_comment_diversity
                        if prev_comments and draft.ai_draft:
                            is_diverse, max_sim = check_comment_diversity(
                                draft.ai_draft, prev_comments, threshold=0.85
                            )
                            if not is_diverse:
                                logger.warning(
                                    f"Diversity check FAILED for avatar {avatar.reddit_username}: "
                                    f"similarity={max_sim:.2f} > 0.85. Rejecting draft."
                                )
                                draft.status = "rejected"
                                db.commit()
                                continue
                    except Exception as e:
                        # Diversity check is non-critical — proceed if it fails
                        logger.warning(f"Diversity check error (non-critical): {e}")

                    # Step 6: Content safety check
                    from app.services.safety import check_comment_content
                    content_check = check_comment_content(draft.ai_draft or "")
                    if not content_check:
                        logger.warning(f"Content blocked: {content_check.reason}")
                        draft.status = "rejected"
                        db.commit()
                        continue

                    # Step 7: Edit/clean comment
                    edit_comment(db, draft, thread, client)

                    # Step 8: Autopilot auto-approve (if client has autopilot_enabled)
                    if client.autopilot_enabled:
                        draft.status = "approved"
                        db.commit()
                        # Sync EPG slot if linked
                        try:
                            from app.services.epg_executor import sync_slot_status
                            sync_slot_status(db, draft.id, "approved")
                            db.commit()
                        except Exception:
                            pass
                        logger.info(
                            "Draft AUTO-APPROVED (autopilot): avatar=%s thread=%s",
                            avatar.reddit_username, thread.post_title[:40],
                        )

                    # Add to previous comments for next iteration (update cache)
                    if str(avatar.id) in _avatar_prev_cache:
                        _avatar_prev_cache[str(avatar.id)].insert(0, draft.ai_draft)
                        _avatar_prev_cache[str(avatar.id)] = _avatar_prev_cache[str(avatar.id)][:20]

                    generated += 1

                except Exception as e:
                    logger.error(f"Failed to generate comment for thread {thread.id}: {e}")
                    # Log to activity events for admin visibility
                    try:
                        from app.models.activity_event import ActivityEvent
                        event = ActivityEvent(
                            event_type="generation_error",
                            client_id=client.id,
                            message=f"Generation failed for {avatar.reddit_username} on r/{thread.subreddit}: {str(e)[:200]}",
                            event_metadata={
                                "avatar_id": str(avatar.id),
                                "avatar_username": avatar.reddit_username,
                                "thread_id": str(thread.id),
                                "thread_title": thread.post_title[:100] if thread.post_title else "",
                                "subreddit": thread.subreddit,
                                "error": str(e)[:500],
                                "source": "auto_pipeline",
                            },
                        )
                        db.add(event)
                        db.commit()
                    except Exception:
                        db.rollback()
                    # Log to audit table
                    try:
                        from app.services.audit import log_system_action
                        log_system_action(
                            db=db,
                            action="generation_error",
                            entity_type="comment_draft",
                            entity_id=thread.id,
                            client_id=client.id,
                            details={
                                "avatar_id": str(avatar.id),
                                "avatar_username": avatar.reddit_username,
                                "thread_id": str(thread.id),
                                "subreddit": thread.subreddit,
                                "error": str(e)[:500],
                            },
                        )
                    except Exception:
                        db.rollback()
                    continue

            logger.info(f"Generated {generated} comments for {client.client_name}")

            # Record activity event for generation completion
            try:
                message = f"Generated {generated} comment drafts"
                metadata = {"drafts_generated": generated}
                record_activity_event(db, "generate", message, uuid.UUID(client_id), metadata)
            except Exception:
                logger.exception("Failed to record generate activity event")

            # Notify client (real-time)
            if generated > 0:
                try:
                    from app.services.task_notifications import notify_pipeline_complete
                    notify_pipeline_complete(client_id, drafts_count=generated)
                except Exception:
                    pass

            return generated

        except Exception as exc:
            # Record system error event
            try:
                record_activity_event(
                    db,
                    "system",
                    f"Comment generation failed for client {client_id}: {exc}",
                    uuid.UUID(client_id),
                    {"error": str(exc)},
                )
            except Exception:
                logger.exception("Failed to record system error activity event")
            # Also log to audit table
            try:
                from app.services.audit import log_system_action
                log_system_action(
                    db=db,
                    action="error",
                    entity_type="task",
                    client_id=uuid.UUID(client_id),
                    details={"task": "generate_comments", "error": str(exc)[:500]},
                )
            except Exception:
                pass
            countdown = 60 * (2 ** self.request.retries)
            logger.warning(
                f"generate_comments retry {self.request.retries + 1}/3 "
                f"for client {client_id}, countdown={countdown}s: {exc}"
            )
            raise self.retry(exc=exc, countdown=countdown)

    finally:
        db.close()


@celery_app.task(name="generate_hobby_comments", bind=True, max_retries=3)
def generate_hobby_comments(self, avatar_id: str, max_comments: int = 10, triggered_by: str = "scheduler"):
    """Generate hobby comments for karma building using Ori-style prompt with voice profile."""
    ai_trigger_context.set(triggered_by)
    reset_task_call_counter()  # R-AI-007: reset per-task LLM call counter
    db = SessionLocal()
    try:
        from app.services.settings import is_pipeline_enabled, is_generation_enabled
        if triggered_by != "manual" and not is_pipeline_enabled(db):
            logger.info("generate_hobby_comments: pipeline_enabled=false, skipping")
            return 0
        if triggered_by != "manual" and not is_generation_enabled(db):
            logger.info("generate_hobby_comments: generation_enabled=false, skipping")
            return 0

        from app.models.hobby import HobbySubreddit
        from app.services.ai import call_llm, log_ai_usage

        avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        if not avatar:
            return 0
        if avatar.pool == "mentor":
            logger.info(f"generate_hobby_comments: avatar {avatar.reddit_username} is Mentor (pool), skipping")
            return 0
        if not getattr(avatar, "pool", "b2b") in ("b2b", "b2c", "warm"):
            logger.info(f"generate_hobby_comments: avatar {avatar.reddit_username} pool={avatar.pool}, skipping")
            return 0
        if avatar.is_frozen:
            logger.info(f"generate_hobby_comments: avatar {avatar.reddit_username} is frozen, skipping")
            return 0
        if avatar.is_shadowbanned:
            logger.info(f"generate_hobby_comments: avatar {avatar.reddit_username} is shadowbanned, skipping")
            return 0
        if avatar.health_status in ("shadowbanned", "suspended"):
            logger.warning(
                "generate_hobby_comments: avatar %s health_status=%s, skipping",
                avatar.reddit_username, avatar.health_status,
            )
            return 0

        try:
            # Get hobby posts without comments
            # NOTE: Image-only posts (empty post_body) are excluded — LLM cannot
            # see images and would generate nonsensical comments. Revisit when
            # multimodal LLM support is added.
            from sqlalchemy import func as sa_func, or_ as sa_or

            # Round-robin across subreddits for diversity (don't let one sub dominate)
            hobby_sub_names = []
            raw_subs = avatar.hobby_subreddits or []
            if isinstance(raw_subs, str):
                raw_subs = [s.strip() for s in raw_subs.split(",")]
            for item in raw_subs:
                if isinstance(item, dict):
                    name = item.get("subreddit") or item.get("name") or ""
                else:
                    name = str(item)
                name = name.strip().replace("r/", "")
                if name:
                    hobby_sub_names.append(name)


            # Filter out banned subreddits
            try:
                from app.services.subreddit_ban import get_banned_subreddits
                banned_subs = get_banned_subreddits(db, avatar.id)
                if banned_subs:
                    pre_count = len(hobby_sub_names)
                    hobby_sub_names = [s for s in hobby_sub_names if s.lower() not in banned_subs]
                    if pre_count != len(hobby_sub_names):
                        logger.info(
                            "generate_hobby_comments: avatar=%s filtered %d banned subs",
                            avatar.reddit_username, pre_count - len(hobby_sub_names),
                        )
            except Exception as e:
                logger.warning("Failed to check subreddit bans in hobby: %s", str(e)[:100])
            if not hobby_sub_names and avatar.warming_phase == 1:
                from app.services.sanitize import DEFAULT_PHASE1_HOBBY_SUBREDDITS
                hobby_sub_names = list(DEFAULT_PHASE1_HOBBY_SUBREDDITS)

            # Distribute max_comments evenly across subreddits
            # Freshness filter: skip posts older than 7 days — replying to
            # stale threads looks suspicious and provides zero engagement value.
            from datetime import datetime as _dt, timezone as _tz, timedelta as _hobby_td
            hobby_freshness_cutoff = _dt.now(_tz.utc) - _hobby_td(days=7)

            posts = []
            if hobby_sub_names:
                per_sub_limit = max(2, max_comments // len(hobby_sub_names))
                for sub_name in hobby_sub_names:
                    sub_posts = (
                        db.query(HobbySubreddit)
                        .filter(
                            HobbySubreddit.avatar_username == avatar.reddit_username,
                            HobbySubreddit.subreddit == sub_name,
                            HobbySubreddit.ai_comment.is_(None),
                            HobbySubreddit.status == "new",
                            HobbySubreddit.post_body.isnot(None),
                            sa_func.length(HobbySubreddit.post_body) > 20,
                            # Freshness: only posts scraped within last 7 days
                            HobbySubreddit.created_at >= hobby_freshness_cutoff,
                            # Skip image/video/link posts - text-only replies
                            # to photo posts look out of place and often get locked
                            sa_or(
                                HobbySubreddit.url.is_(None),
                                HobbySubreddit.url == "",
                                HobbySubreddit.url.like("%reddit.com%"),
                            ),
                        )
                        .order_by(HobbySubreddit.scraped_at.desc())
                        .limit(per_sub_limit)
                        .all()
                    )
                    posts.extend(sub_posts)
                # Trim to max_comments total
                posts = posts[:max_comments]
            else:
                # Fallback: no subreddit list, use old behavior
                posts = (
                    db.query(HobbySubreddit)
                    .filter(
                        HobbySubreddit.avatar_username == avatar.reddit_username,
                        HobbySubreddit.ai_comment.is_(None),
                        HobbySubreddit.status == "new",
                        HobbySubreddit.post_body.isnot(None),
                        sa_func.length(HobbySubreddit.post_body) > 20,
                        # Freshness: only posts scraped within last 7 days
                        HobbySubreddit.created_at >= hobby_freshness_cutoff,
                        # Skip image/video/link posts
                        sa_or(
                            HobbySubreddit.url.is_(None),
                            HobbySubreddit.url == "",
                            HobbySubreddit.url.like("%reddit.com%"),
                        ),
                    )
                    .limit(max_comments)
                    .all()
                )

            # Get last 20 comments for diversity enforcement
            recent_comments = (
                db.query(HobbySubreddit.ai_comment)
                .filter(
                    HobbySubreddit.avatar_username == avatar.reddit_username,
                    HobbySubreddit.ai_comment.isnot(None),
                )
                .order_by(HobbySubreddit.created_at.desc())
                .limit(20)
                .all()
            )
            previous_comments = [r[0] for r in recent_comments if r[0]]

            generated = 0
            for post in posts:
                try:
                    # Phase 0 (Incubation) uses ultra-simple newcomer prompt
                    from app.services.settings import get_setting
                    incubation_enabled = get_setting(db, "incubation_phase_enabled") == "true"
                    if avatar.warming_phase == 0 and incubation_enabled:
                        system_prompt = _build_incubation_system_prompt(avatar, previous_comments)
                    else:
                        system_prompt = _build_hobby_system_prompt(avatar, previous_comments)
                    user_prompt = _build_hobby_user_prompt(post)

                    # Hobby comments: use scoring model (Gemini Flash when available, Sonnet as fallback)
                    # Professional comments use generation model (Sonnet — quality)
                    # This mirrors Ori's setup: Opus for pro, Flash for hobby
                    from app.config import get_config
                    gen_model = get_config("llm_scoring_model") or get_config("llm_generation_model")

                    # A/B Test: force generation model if avatar in experiment
                    if get_setting(db, "ab_test_enabled") == "true":
                        from app.services.ab_test.control_enforcer import get_forced_generation_model
                        forced_model = get_forced_generation_model(db, avatar.id)
                        if forced_model:
                            logger.info(
                                "A/B test: overriding model to '%s' for avatar %s",
                                forced_model, avatar.reddit_username,
                            )
                            gen_model = forced_model

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
                        db, None, "hobby_comment", result,
                        avatar_id=str(avatar.id),
                        subreddit_name=post.subreddit if hasattr(post, 'subreddit') else None,
                    )

                    # Parse JSON response or use raw text
                    import json as json_mod
                    content = result["content"].strip()
                    try:
                        parsed = json_mod.loads(content)
                        comment_text = parsed.get("comment", content)
                    except (json_mod.JSONDecodeError, TypeError):
                        comment_text = content

                    post.ai_comment = comment_text
                    post.status = "pending"
                    db.commit()
                    generated += 1

                    # Also create a CommentDraft so it appears in client Review Queue
                    try:
                        # Determine client_id from avatar
                        draft_client_id = None
                        if avatar.client_ids:
                            draft_client_id = avatar.client_ids[0]

                        from app.models.comment_draft import CommentDraft as CD
                        import uuid as uuid_mod
                        draft = CD(
                            id=uuid_mod.uuid4(),
                            thread_id=None,
                            hobby_post_id=post.id,
                            avatar_id=avatar.id,
                            client_id=draft_client_id,
                            type="hobby",
                            ai_draft=comment_text,
                            status="pending",
                            comment_approach="hobby_engagement",
                        )
                        db.add(draft)
                        db.commit()

                        # Autopilot: auto-approve hobby draft if client has autopilot_enabled
                        if draft_client_id:
                            try:
                                from app.models.client import Client as ClientModel
                                _client = db.query(ClientModel).filter(ClientModel.id == draft_client_id).first()
                                if _client and _client.autopilot_enabled:
                                    draft.status = "approved"
                                    post.status = "approved"
                                    db.commit()
                                    logger.info(
                                        "Hobby draft AUTO-APPROVED (autopilot): avatar=%s sub=r/%s",
                                        avatar.reddit_username, post.subreddit,
                                    )
                            except Exception:
                                pass

                    except Exception as draft_err:
                        logger.warning(f"Failed to create CommentDraft for hobby post {post.id}: {draft_err}")
                        db.rollback()

                    # Add to previous_comments for diversity in this batch
                    previous_comments.insert(0, comment_text)
                    if len(previous_comments) > 20:
                        previous_comments.pop()

                except Exception as e:
                    logger.error(f"Failed hobby comment for post {post.id}: {e}")
                    # Log to audit for admin visibility
                    try:
                        from app.services.audit import log_system_action
                        log_system_action(
                            db=db,
                            action="generation_error",
                            entity_type="hobby_comment",
                            entity_id=post.id if hasattr(post, 'id') else None,
                            details={
                                "avatar_id": str(avatar.id),
                                "avatar_username": avatar.reddit_username,
                                "post_id": str(post.id) if hasattr(post, 'id') else None,
                                "subreddit": post.subreddit if hasattr(post, 'subreddit') else None,
                                "error": str(e)[:500],
                            },
                        )
                    except Exception:
                        db.rollback()
                    continue

            logger.info(f"Generated {generated} hobby comments for {avatar.reddit_username}")
            return generated

        except Exception as exc:
            countdown = 60 * (2 ** self.request.retries)
            logger.warning(
                f"generate_hobby_comments retry {self.request.retries + 1}/3 "
                f"for avatar {avatar_id}, countdown={countdown}s: {exc}"
            )
            raise self.retry(exc=exc, countdown=countdown)

    finally:
        db.close()


def _build_hobby_system_prompt(avatar, previous_comments: list[str]) -> str:
    """Build the Ori-style hobby comment system prompt with voice profile."""
    voice_section = ""
    if avatar.voice_profile_md:
        voice_section = f"\n## Voice Profile\n\n{avatar.voice_profile_md}\n"

    prev_section = ""
    if previous_comments:
        import json as json_mod
        prev_section = f"\n## Previous Comments (last {len(previous_comments)} — avoid repetition)\n\n{json_mod.dumps(previous_comments, ensure_ascii=False)}\n"

    return f"""# Hobby & Karma Comment Writer

**Purpose:** Generate a short, engaging Reddit comment in a hobby subreddit. The single goal is karma: be the comment people upvote, reply to, and remember. You're a regular person participating in a community you enjoy.

## Rules (NON-NEGOTIABLE)

1. **5-60 words** (hard max 80). If over 80, rewrite with a shorter idea.
2. **Sound like a person typing on their phone.** Not a content creator, not AI.
3. **One paragraph only.** No formatting, no bullets, no bold, no signatures.
4. **Connect to specific details** in the post. Generic comments that work on any thread = fail.
5. **No em-dashes (—).** Use commas, parentheses, or split the sentence.
6. **No brand/product mentions.** Zero tolerance.
7. **No "Th" sentence starters** (The, This, That, There, They). Rephrase.
8. **No gerund openers** (Trying, Looking, Getting). Anchor to a subject.
9. **Vary openers.** Don't start with "I [verb]..." every time.

## Engagement Angles (pick ONE)

- **sharp_take** — opinionated observation nobody mentioned
- **yeah_and** — relatable agreement with a twist
- **useful_drop** — helpful tip delivered casually
- **micro_story** — ultra-short personal anecdote (specific moment, not narrative)
- **reality_check** — casual pushback on something off
- **question** — genuine question that sparks discussion

## Tone

Match the thread energy. Be casual, specific, concise, genuine. Never be a guru, teacher, or marketer. You're a casual participant, not an authority.
{voice_section}{prev_section}
## Output

Output ONLY the comment text. No JSON, no explanation, no metadata. Just the comment itself."""


def _build_hobby_user_prompt(post) -> str:
    """Build the user prompt with thread content."""
    comments_section = ""
    if post.comments:
        # Truncate comments to avoid token overflow
        comments_text = post.comments[:3000] if len(post.comments or "") > 3000 else post.comments
        comments_section = f"\n\n## Comments\n\n{comments_text}"

    return f"""## Subreddit: r/{post.subreddit}

## Post Title: {post.post_title}

## Post Text:
{(post.post_body or '(no text, title-only post)')[:2000]}
{comments_section}"""


def _build_incubation_system_prompt(avatar, previous_comments: list[str]) -> str:
    """Build Phase 0 (Incubation) prompt: ultra-short, newcomer-style comments.

    Goal: survive first week without AutoMod kills. Comments must be
    indistinguishable from a genuine new Reddit user exploring communities.
    """
    prev_section = ""
    if previous_comments:
        import json as json_mod
        prev_section = f"\n\nPrevious comments (do NOT repeat patterns):\n{json_mod.dumps(previous_comments[-3:], ensure_ascii=False)}"

    return f"""You are a new Reddit user casually browsing and exploring communities.

Write ONE very short comment (10-30 words maximum). You are curious, friendly, and brief.

ALLOWED styles (pick one):
- Ask a genuine question about the topic
- Share a brief personal reaction ("oh wow, this happened to me too")
- Agree with someone and add one small detail from your life
- Express surprise or interest in a specific detail

ABSOLUTELY FORBIDDEN:
- Opinions longer than one sentence
- Technical advice or expertise
- Links of any kind
- Any formatting (no bold, no lists, no headers, no bullets)
- Multi-sentence or multi-paragraph responses
- Starting with "I think" or "In my opinion"
- Brand, product, or company mentions
- Em-dashes (—)
- Sounding like an authority or expert

Your comment MUST be under 30 words. If it's longer, make it shorter.
{prev_section}

Output ONLY the comment text. Nothing else."""


@celery_app.task(name="generate_posts", bind=True, max_retries=3)
def generate_posts(self, client_id: str, max_posts: int = 3, triggered_by: str = "scheduler"):
    """Generate post drafts for a client.

    Pipeline: topic generation → brief strategy → post writing.
    Only generates for avatars in Phase 2+ (posts require established karma).
    """
    ai_trigger_context.set(triggered_by)
    reset_task_call_counter()  # R-AI-007: reset per-task LLM call counter
    db = SessionLocal()
    try:
        from app.services.settings import is_pipeline_enabled, is_generation_enabled
        from app.services.post_generation import (
            generate_post_topic,
            generate_post_brief,
            generate_post,
        )
        from app.models.post_draft import PostDraft
        from app.models.subreddit import ClientSubreddit

        if triggered_by != "manual" and not is_pipeline_enabled(db):
            logger.info("generate_posts: pipeline_enabled=false, skipping")
            return 0
        if triggered_by != "manual" and not is_generation_enabled(db):
            logger.info("generate_posts: generation_enabled=false, skipping")
            return 0

        try:
            client = db.query(Client).filter(Client.id == client_id).first()
            if not client:
                logger.error(f"Client {client_id} not found")
                return 0
            if not client.is_active:
                logger.info(f"generate_posts: client {client.client_name} is deactivated, skipping")
                return 0
            from app.services.trial_guard import is_trial_expired
            if is_trial_expired(client):
                logger.info(f"generate_posts: client {client.client_name} trial expired, skipping")
                return 0

            # Get active avatars for this client — Phase 2+ only (posts need karma)
            avatars = (
                db.query(Avatar)
                .filter(Avatar.active.is_(True))
                .all()
            )
            client_avatars = [
                a for a in avatars
                if a.client_ids and str(client.id) in a.client_ids
                and not a.is_frozen
                and a.warming_phase >= 2  # Phase gate: posts require Phase 2+
                and a.health_status not in ("shadowbanned", "suspended")
            ]

            if not client_avatars:
                logger.info(f"No Phase 2+ avatars for client {client.client_name} — skipping post generation")
                return 0

            # Get client's subreddits (business subs preferred for posts)
            from app.models.subreddit import ClientSubredditAssignment, Subreddit
            assignments = (
                db.query(ClientSubredditAssignment)
                .filter(ClientSubredditAssignment.client_id == client.id)
                .all()
            )
            subreddit_names = []
            for a in assignments:
                sub = db.query(Subreddit).filter(Subreddit.id == a.subreddit_id).first()
                if sub:
                    subreddit_names.append(sub.subreddit_name)

            if not subreddit_names:
                # Fallback: use avatar business subreddits
                for av in client_avatars:
                    if av.business_subreddits:
                        subreddit_names.extend(av.business_subreddits)
                subreddit_names = list(set(subreddit_names))

            if not subreddit_names:
                logger.warning(f"No subreddits configured for client {client.client_name}")
                return 0

            # Get previous post titles for diversity check
            previous_posts = (
                db.query(PostDraft.ai_title)
                .filter(
                    PostDraft.client_id == client_id,
                    PostDraft.ai_title.isnot(None),
                )
                .order_by(PostDraft.created_at.desc())
                .limit(10)
                .all()
            )
            prev_titles = [p[0] for p in previous_posts if p[0]]

            # Check how many pending posts already exist (don't flood the queue)
            pending_count = (
                db.query(func.count(PostDraft.id))
                .filter(
                    PostDraft.client_id == client_id,
                    PostDraft.status == "pending",
                )
                .scalar()
            ) or 0

            if pending_count >= 5:
                logger.info(
                    f"Client {client.client_name} already has {pending_count} pending posts — skipping"
                )
                return 0

            # Limit generation to not exceed queue cap
            posts_to_generate = min(max_posts, 5 - pending_count)

            generated = 0
            for i in range(posts_to_generate):
                try:
                    # Round-robin avatar selection
                    avatar = client_avatars[i % len(client_avatars)]

                    # Pick subreddit (prefer business subs the avatar has karma in)
                    target_sub = _select_post_subreddit(
                        db, avatar, subreddit_names, client_id
                    )
                    if not target_sub:
                        continue

                    # Step 1: Generate topic
                    topic = generate_post_topic(
                        db, client, avatar, target_sub, prev_titles
                    )

                    # Step 2: Generate strategic brief
                    brief = generate_post_brief(
                        db, client, avatar, target_sub, topic
                    )

                    # Step 3: Generate post
                    draft = generate_post(
                        db, client, avatar, target_sub, brief, prev_titles
                    )

                    prev_titles.insert(0, draft.ai_title or "")
                    generated += 1

                except Exception as e:
                    logger.error(f"Failed to generate post {i+1} for {client.client_name}: {e}")
                    continue

            logger.info(f"Generated {generated} post drafts for {client.client_name}")

            # Record activity event
            try:
                message = f"Generated {generated} post drafts"
                metadata = {"drafts_generated": generated, "type": "post"}
                record_activity_event(db, "generate", message, uuid.UUID(client_id), metadata)
            except Exception:
                logger.exception("Failed to record post generation activity event")

            return generated

        except Exception as exc:
            try:
                record_activity_event(
                    db,
                    "system",
                    f"Post generation failed for client {client_id}: {exc}",
                    uuid.UUID(client_id),
                    {"error": str(exc)},
                )
            except Exception:
                logger.exception("Failed to record system error activity event")
            countdown = 60 * (2 ** self.request.retries)
            logger.warning(
                f"generate_posts retry {self.request.retries + 1}/3 "
                f"for client {client_id}, countdown={countdown}s: {exc}"
            )
            raise self.retry(exc=exc, countdown=countdown)
    finally:
        db.close()


def _select_post_subreddit(
    db, avatar: Avatar, subreddit_names: list[str], client_id: str
) -> str | None:
    """Select the best subreddit for a post, preferring subs with established karma."""
    from app.services import karma_tracker
    from app.models.post_draft import PostDraft
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)

    # Get subreddits where avatar has karma (credibility)
    scored_subs = []
    for sub_name in subreddit_names:
        record = karma_tracker.get_karma_in_subreddit(db, avatar.id, sub_name)
        karma = record.total_karma if record else 0
        scored_subs.append((sub_name, karma))

    # Sort by karma (prefer subs where avatar is established)
    scored_subs.sort(key=lambda x: -x[1])

    # Avoid subreddits where we posted recently (7-day cooldown per sub per avatar)
    for sub_name, karma in scored_subs:
        recent_post = (
            db.query(PostDraft)
            .filter(
                PostDraft.client_id == client_id,
                PostDraft.avatar_id == avatar.id,
                PostDraft.subreddit == sub_name,
                PostDraft.created_at >= now - timedelta(days=7),
            )
            .first()
        )
        if not recent_post:
            return sub_name

    # If all subs have recent posts, pick the one with highest karma anyway
    if scored_subs:
        return scored_subs[0][0]

    return None


@celery_app.task(name="evaluate_all_avatar_phases")
def evaluate_all_avatar_phases():
    """Evaluate phase eligibility for all active, non-shadowbanned avatars.

    For each avatar:
    - Runs PhaseEvaluator.evaluate() to check promotion/demotion eligibility
    - If promote → PhaseTransitionManager.promote()
    - If demote → PhaseTransitionManager.demote()
    - Per-avatar failures are logged and do not stop processing of other avatars

    Logs a summary at the end with counts of evaluated, promoted, demoted, and errors.
    """
    from app.services.phase import PhaseEvaluator, PhaseTransitionManager
    from app.services.phase_lock import PhaseTransitionLock

    settings = get_settings()
    db = SessionLocal()
    redis_client = redis.from_url(settings.redis_url)

    try:
        # Query all active, non-shadowbanned avatars (skip Mentors — phase 0)
        avatars = (
            db.query(Avatar)
            .filter(
                Avatar.active.is_(True),
                Avatar.pool.in_(["b2b", "b2c", "warm"]),  # Pipeline-eligible pools (excludes mentor)
            )
            .all()
        )

        evaluator = PhaseEvaluator()
        lock = PhaseTransitionLock(redis_client)
        manager = PhaseTransitionManager(lock)

        evaluated = 0
        promoted = 0
        demoted = 0
        errors = 0

        for avatar in avatars:
            try:
                result = evaluator.evaluate(db, avatar)
                evaluated += 1

                if result.action == "promote":
                    success = manager.promote(db, avatar, result.criteria_values)
                    if success:
                        promoted += 1

                elif result.action == "demote":
                    success = manager.demote(
                        db, avatar, result.target_phase, result.trigger_reason
                    )
                    if success:
                        demoted += 1

            except Exception as e:
                errors += 1
                logger.error(
                    "Phase evaluation failed for avatar %s: %s",
                    avatar.reddit_username,
                    e,
                )
                continue

        logger.info(
            "Phase evaluation complete: %d evaluated, %d promoted, %d demoted, %d errors",
            evaluated,
            promoted,
            demoted,
            errors,
        )

        # --- Zone Evaluation (Risk-Aware Activation) ---
        # Run zone graduation/demotion for Phase 0-1 avatars with activation routes
        zone_graduated = 0
        zone_demoted = 0
        zone_errors = 0
        try:
            from app.services.settings import get_setting
            activation_enabled = get_setting(db, "activation_routing_enabled")
            if activation_enabled in ("true", "True", "1"):
                from app.services.zone_evaluator import run_zone_evaluation_for_avatar

                phase01_avatars = [
                    a for a in avatars
                    if a.warming_phase <= 1 and a.activation_route
                ]
                for avatar in phase01_avatars:
                    try:
                        result = run_zone_evaluation_for_avatar(db, avatar)
                        if result["action"] == "graduated":
                            zone_graduated += 1
                        elif result["action"] == "demoted":
                            zone_demoted += 1
                    except Exception as e:
                        zone_errors += 1
                        logger.error(
                            "Zone evaluation failed for avatar %s: %s",
                            avatar.reddit_username, e,
                        )

                if zone_graduated or zone_demoted:
                    logger.info(
                        "Zone evaluation: %d graduated, %d demoted, %d errors",
                        zone_graduated, zone_demoted, zone_errors,
                    )
        except Exception as e:
            logger.error("Zone evaluation batch failed: %s", e)

        try:
            from app.services.audit import log_system_action
            log_system_action(
                db,
                action="phase_evaluation_completed",
                entity_type="avatar",
                details={
                    "evaluated": evaluated,
                    "promoted": promoted,
                    "demoted": demoted,
                    "errors": errors,
                    "zone_graduated": zone_graduated,
                    "zone_demoted": zone_demoted,
                    "zone_errors": zone_errors,
                },
            )
        except Exception as e:
            logger.error(f"Failed to log phase_evaluation_completed audit entry: {e}")

        return {
            "evaluated": evaluated,
            "promoted": promoted,
            "demoted": demoted,
            "errors": errors,
        }

    finally:
        db.close()
        redis_client.close()


@celery_app.task(name="refresh_thread_liveness")
def refresh_thread_liveness(max_threads: int = 50):
    """Periodic task: check locked status for stale threads with pending drafts.

    Prevents operators from reviewing comments for threads that are no longer
    commentable. Also auto-rejects pending drafts for locked threads.

    Should be scheduled every 2-4 hours via Celery Beat.
    """
    db = SessionLocal()
    try:
        from app.services.thread_liveness import bulk_refresh_locked_status
        result = bulk_refresh_locked_status(db, max_threads=max_threads)
        logger.info("refresh_thread_liveness: %s", result)
        return result
    except Exception as e:
        logger.error("refresh_thread_liveness failed: %s", e)
        return {"error": str(e)}
    finally:
        db.close()
