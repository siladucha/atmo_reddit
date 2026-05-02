"""Celery tasks for AI pipeline: scoring, persona selection, comment generation."""

import logging

from app.tasks.worker import celery_app
from app.database import SessionLocal
from app.models.client import Client
from app.models.thread import RedditThread
from app.models.avatar import Avatar
from app.models.comment_draft import CommentDraft
from app.services.scoring import score_unscored_threads
from app.services.generation import select_persona, generate_comment, edit_comment

logger = logging.getLogger(__name__)


@celery_app.task(name="score_threads")
def score_threads(client_id: str):
    """Score all unscored threads for a client."""
    db = SessionLocal()
    try:
        client = db.query(Client).filter(Client.id == client_id).first()
        if not client:
            logger.error(f"Client {client_id} not found")
            return 0

        count = score_unscored_threads(db, client)
        return count

    finally:
        db.close()


@celery_app.task(name="generate_comments")
def generate_comments(client_id: str, max_comments: int = 15):
    """Generate comments for top 'engage' threads.

    Full pipeline: select persona → generate comment → edit comment.
    """
    db = SessionLocal()
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
        return generated

    finally:
        db.close()


@celery_app.task(name="generate_hobby_comments")
def generate_hobby_comments(avatar_id: str, max_comments: int = 10):
    """Generate hobby comments for karma building. Simpler pipeline."""
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

        generated = 0
        for post in posts:
            try:
                prompt = f"""Write a short, casual Reddit comment (20-50 words) on this post.
You are {avatar.reddit_username}. Be helpful, funny, or add a personal take.
No marketing, no brand mentions. Just be a normal Redditor.

Subreddit: r/{post.subreddit}
Title: {post.post_title}
Post: {(post.post_body or '')[:500]}

Output ONLY the comment text."""

                result = call_llm(
                    messages=[{"role": "user", "content": prompt}],
                    model="gemini/gemini-2.0-flash",
                    temperature=0.8,
                    max_tokens=128,
                )

                log_ai_usage(db, None, "hobby_comment", result)

                post.ai_comment = result["content"].strip()
                post.status = "pending"
                db.commit()
                generated += 1

            except Exception as e:
                logger.error(f"Failed hobby comment for post {post.id}: {e}")
                continue

        logger.info(f"Generated {generated} hobby comments for {avatar.reddit_username}")
        return generated

    finally:
        db.close()


@celery_app.task(name="generate_posts")
def generate_posts(client_id: str):
    """Generate post drafts. Placeholder for now."""
    # TODO: implement post generation pipeline
    logger.info(f"Post generation for client {client_id} — not yet implemented")
    return 0
