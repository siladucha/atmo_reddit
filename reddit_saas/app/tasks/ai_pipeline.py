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
from app.models.avatar import Avatar
from app.models.comment_draft import CommentDraft
from app.services.scoring import score_unscored_threads
from app.services.generation import select_persona, generate_comment, edit_comment
from app.services.transparency import record_activity_event

logger = logging.getLogger(__name__)


@celery_app.task(name="score_threads")
def score_threads(client_id: str):
    """Score all unscored threads for a client."""
    db = SessionLocal()
    try:
        try:
            client = db.query(Client).filter(Client.id == client_id).first()
            if not client:
                logger.error(f"Client {client_id} not found")
                return 0

            count = score_unscored_threads(db, client)

            # Record activity event with tag distribution
            try:
                tag_rows = (
                    db.query(RedditThread.tag, func.count(RedditThread.id))
                    .filter(RedditThread.client_id == client_id)
                    .group_by(RedditThread.tag)
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

        except Exception as e:
            # Record system error event
            try:
                record_activity_event(
                    db,
                    "system",
                    f"Scoring failed for client {client_id}: {e}",
                    uuid.UUID(client_id),
                    {"error": str(e)},
                )
            except Exception:
                logger.exception("Failed to record system error activity event")
            raise

    finally:
        db.close()


@celery_app.task(name="generate_comments")
def generate_comments(client_id: str, max_comments: int = 15):
    """Generate comments for top 'engage' threads.

    Full pipeline: select persona → generate comment → edit comment.
    """
    db = SessionLocal()
    try:
        try:
            client = db.query(Client).filter(Client.id == client_id).first()
            if not client:
                logger.error(f"Client {client_id} not found")
                return 0

            # Get active avatars for this client
            avatars = (
                db.query(Avatar)
                .filter(Avatar.active.is_(True))
                .all()
            )
            # Filter avatars that serve this client
            client_avatars = [
                a for a in avatars
                if a.client_ids and str(client.id) in a.client_ids
            ]

            if not client_avatars:
                logger.warning(f"No active avatars for client {client.client_name}")
                return 0

            # Get engage threads that don't have drafts yet
            threads_with_drafts = (
                db.query(CommentDraft.thread_id)
                .filter(CommentDraft.client_id == client_id)
                .subquery()
            )

            engage_threads = (
                db.query(RedditThread)
                .filter(
                    RedditThread.client_id == client_id,
                    RedditThread.tag == "engage",
                    ~RedditThread.id.in_(db.query(threads_with_drafts.c.thread_id)),
                )
                .order_by(
                    RedditThread.alert.desc(),
                    RedditThread.composite.desc(),
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
                    # Step 1: Safety check
                    from app.services.safety import check_avatar_can_post, check_subreddit_limit

                    # Step 2: Select persona
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
                        continue

                    sub_safety = check_subreddit_limit(db, avatar, thread.subreddit)
                    if not sub_safety:
                        logger.info(f"Subreddit limit for {avatar.reddit_username}: {sub_safety.reason}")
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

        except Exception as e:
            # Record system error event
            try:
                record_activity_event(
                    db,
                    "system",
                    f"Comment generation failed for client {client_id}: {e}",
                    uuid.UUID(client_id),
                    {"error": str(e)},
                )
            except Exception:
                logger.exception("Failed to record system error activity event")
            raise

    finally:
        db.close()


@celery_app.task(name="generate_hobby_comments")
def generate_hobby_comments(avatar_id: str, max_comments: int = 10):
    """Generate hobby comments for karma building using Ori-style prompt with voice profile."""
    db = SessionLocal()
    try:
        from app.models.hobby import HobbySubreddit
        from app.services.ai import call_llm, log_ai_usage

        avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
        if not avatar:
            return 0

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

                log_ai_usage(db, None, "hobby_comment", result)

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


@celery_app.task(name="generate_posts")
def generate_posts(client_id: str):
    """Generate post drafts. Placeholder for now."""
    # TODO: implement post generation pipeline
    logger.info(f"Post generation for client {client_id} — not yet implemented")
    return 0


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
        # Query all active, non-shadowbanned avatars
        avatars = (
            db.query(Avatar)
            .filter(
                Avatar.active.is_(True),
                Avatar.is_shadowbanned.is_(False),
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
