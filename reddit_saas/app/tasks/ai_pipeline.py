"""Celery tasks for AI pipeline: scoring, persona selection, comment generation."""

import logging
import uuid

import redis
from sqlalchemy import func

from app.tasks.worker import celery_app
from app.config import get_settings
from app.database import SessionLocal
from app.models.client import Client
from app.models.thread import RedditThread
from app.models.thread_score import ThreadScore
from app.models.avatar import Avatar
from app.models.comment_draft import CommentDraft
from app.services.scoring import score_unscored_threads_for_client
from app.services.generation import select_persona, generate_comment, edit_comment
from app.services.transparency import record_activity_event
from app.services.ai import ai_trigger_context

logger = logging.getLogger(__name__)


@celery_app.task(name="score_threads", bind=True, max_retries=3)
def score_threads(self, client_id: str, triggered_by: str = "scheduler"):
    """Score all unscored threads for a client.

    Uses the shared subreddit registry: finds threads in the client's assigned
    subreddits that lack a ThreadScore record for this client.
    """
    ai_trigger_context.set(triggered_by)
    db = SessionLocal()
    try:
        from app.services.settings import is_pipeline_enabled
        if not is_pipeline_enabled(db):
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

            result = score_unscored_threads_for_client(db, client)
            # Handle both dict (new) and int (legacy) return
            if isinstance(result, dict):
                count = result.get("scored", 0)
            else:
                count = result

            # Record activity event with tag distribution from ThreadScore
            try:
                tag_rows = (
                    db.query(ThreadScore.tag, func.count(ThreadScore.id))
                    .filter(ThreadScore.client_id == client_id)
                    .group_by(ThreadScore.tag)
                    .all()
                )
                tag_counts = {row[0]: row[1] for row in tag_rows}
                engage = tag_counts.get("engage", 0)
                monitor = tag_counts.get("monitor", 0)
                skip = tag_counts.get("skip", 0)

                message = f"Scored {count} threads: {engage} engage, {monitor} monitor, {skip} skip"
                metadata = {
                    "threads_scored": count,
                    "engage": engage,
                    "monitor": monitor,
                    "skip": skip,
                }
                record_activity_event(db, "score", message, uuid.UUID(client_id), metadata)
            except Exception:
                logger.exception("Failed to record score activity event")

            return count

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
            # Also log to audit table
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
    db = SessionLocal()
    try:
        from app.services.settings import is_pipeline_enabled, is_generation_enabled
        if not is_pipeline_enabled(db):
            logger.info("generate_comments: pipeline_enabled=false, skipping")
            return 0
        if not is_generation_enabled(db):
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
                and a.warming_phase != 0  # Mentor — excluded from pipelines
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

            # Query threads via ThreadScore for this client with tag='engage'
            engage_threads = (
                db.query(RedditThread)
                .join(ThreadScore, ThreadScore.thread_id == RedditThread.id)
                .filter(
                    ThreadScore.client_id == client_id,
                    ThreadScore.tag == "engage",
                    RedditThread.subreddit_id.in_(active_subreddit_ids),
                    RedditThread.is_locked.is_(False),
                    ~RedditThread.id.in_(db.query(threads_with_drafts.c.thread_id)),
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

            # Get previous comments for diversity check
            previous = (
                db.query(CommentDraft.ai_draft)
                .filter(
                    CommentDraft.client_id == client_id,
                    CommentDraft.ai_draft.isnot(None),
                )
                .order_by(CommentDraft.created_at.desc())
                .limit(20)
                .all()
            )
            prev_comments = [p[0] for p in previous if p[0]]

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

                    # Step 3: Safety gate
                    safety = check_avatar_can_post(db, avatar, "professional")
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

                    # Step 4: Generate comment
                    draft = generate_comment(
                        db, thread, client, avatar, selection, prev_comments
                    )

                    # Step 5: Content safety check
                    from app.services.safety import check_comment_content
                    content_check = check_comment_content(draft.ai_draft or "")
                    if not content_check:
                        logger.warning(f"Content blocked: {content_check.reason}")
                        draft.status = "rejected"
                        db.commit()
                        continue

                    # Step 6: Edit/clean comment
                    edit_comment(db, draft, thread, client)

                    # Add to previous comments for next iteration
                    prev_comments.insert(0, draft.ai_draft)
                    if len(prev_comments) > 20:
                        prev_comments = prev_comments[:20]

                    generated += 1

                except Exception as e:
                    logger.error(f"Failed to generate comment for thread {thread.id}: {e}")
                    continue

            logger.info(f"Generated {generated} comments for {client.client_name}")

            # Record activity event for generation completion
            try:
                message = f"Generated {generated} comment drafts"
                metadata = {"drafts_generated": generated}
                record_activity_event(db, "generate", message, uuid.UUID(client_id), metadata)
            except Exception:
                logger.exception("Failed to record generate activity event")

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
    db = SessionLocal()
    try:
        from app.services.settings import is_pipeline_enabled, is_generation_enabled
        if not is_pipeline_enabled(db):
            logger.info("generate_hobby_comments: pipeline_enabled=false, skipping")
            return 0
        if not is_generation_enabled(db):
            logger.info("generate_hobby_comments: generation_enabled=false, skipping")
            return 0

        from app.models.hobby import HobbySubreddit
        from app.services.ai import call_llm, log_ai_usage

        avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        if not avatar:
            return 0
        if avatar.warming_phase == 0:
            logger.info(f"generate_hobby_comments: avatar {avatar.reddit_username} is Mentor (phase 0), skipping")
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
            posts = (
                db.query(HobbySubreddit)
                .filter(
                    HobbySubreddit.avatar_username == avatar.reddit_username,
                    HobbySubreddit.ai_comment.is_(None),
                    HobbySubreddit.status == "new",
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
                    # Build Ori-style hobby comment prompt
                    system_prompt = _build_hobby_system_prompt(avatar, previous_comments)
                    user_prompt = _build_hobby_user_prompt(post)

                    # Hobby comments: use scoring model (Gemini Flash when available, Sonnet as fallback)
                    # Professional comments use generation model (Sonnet — quality)
                    # This mirrors Ori's setup: Opus for pro, Flash for hobby
                    from app.config import get_config
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

                    # Add to previous_comments for diversity in this batch
                    previous_comments.insert(0, comment_text)
                    if len(previous_comments) > 20:
                        previous_comments.pop()

                except Exception as e:
                    logger.error(f"Failed hobby comment for post {post.id}: {e}")
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


@celery_app.task(name="generate_posts", bind=True, max_retries=3)
def generate_posts(self, client_id: str, max_posts: int = 3, triggered_by: str = "scheduler"):
    """Generate post drafts for a client.

    Pipeline: topic generation → brief strategy → post writing.
    Only generates for avatars in Phase 2+ (posts require established karma).
    """
    ai_trigger_context.set(triggered_by)
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

        if not is_pipeline_enabled(db):
            logger.info("generate_posts: pipeline_enabled=false, skipping")
            return 0
        if not is_generation_enabled(db):
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
                and a.warming_phase >= 2  # Phase gate: posts require Phase 2+ (also excludes Mentor=0)
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
    from datetime import timedelta

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
                Avatar.is_shadowbanned.is_(False),
                Avatar.warming_phase != 0,  # Mentor — not subject to phase evaluation
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
