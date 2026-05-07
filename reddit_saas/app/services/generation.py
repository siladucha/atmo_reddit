"""Comment and post generation service.

Handles persona selection, comment writing, and quality editing.
Uses prompts adapted from Ori's PoC.
"""

import json
import logging

from sqlalchemy.orm import Session

from app.config import get_config
from app.models.client import Client
from app.models.thread import RedditThread
from app.models.avatar import Avatar
from app.models.comment_draft import CommentDraft
from app.services.ai import call_llm, call_llm_json, log_ai_usage
from app.schemas.llm_outputs import CommentOutput

logger = logging.getLogger(__name__)


# --- Persona Selection ---

PERSONA_SELECT_PROMPT = """# Reddit Persona Selection Agent

Select the best persona to engage with a given Reddit thread based on subreddit fit,
audience match, topic alignment, and strategic value.

## Available Personas

{personas_json}

## Company Context

Brand: {brand_name}
Worldview: {company_worldview}
Problem: {company_problem}

## Output JSON

{{
  "persona_username": "selected username",
  "mode": "bullseye | helpful_peer | karma_only",
  "audience": "who is in this thread",
  "thread_angle": "what the comment should address",
  "pov_opportunity": "where company worldview fits, or null if karma-only",
  "selection_reasoning": "brief explanation"
}}"""


def select_persona(
    db: Session,
    thread: RedditThread,
    client: Client,
    avatars: list[Avatar],
) -> dict:
    """Select the best avatar/persona for a thread.

    Avatars with established karma in the target subreddit are preferred over
    ones with zero karma there (Req 8). The per-subreddit figure is also fed
    into the LLM persona-selection prompt so the model can break ties.

    Returns:
        Dict with persona selection and engagement strategy.

    Raises:
        RuntimeError: If LLM call fails after logging the error.
    """
    # Runtime assertion: all candidate avatars must belong to this client
    for avatar in avatars:
        assert avatar.client_ids and str(client.id) in avatar.client_ids, (
            f"Context isolation violation: avatar {avatar.reddit_username} "
            f"does not belong to client {client.id}"
        )

    from app.services import karma_tracker

    # Build personas summary for the prompt — include karma in this thread's
    # subreddit so the LLM can prefer credible avatars.
    personas_data = []
    target_sub = thread.subreddit
    karma_by_avatar: dict[str, int] = {}
    for avatar in avatars:
        sub_karma_record = (
            karma_tracker.get_karma_in_subreddit(db, avatar.id, target_sub)
            if target_sub
            else None
        )
        sub_total = sub_karma_record.total_karma if sub_karma_record else 0
        karma_by_avatar[avatar.reddit_username] = sub_total
        personas_data.append({
            "username": avatar.reddit_username,
            "voice_summary": (avatar.voice_profile_md or "")[:500],
            "hill_i_die_on": avatar.hill_i_die_on or "",
            "helpful_topics": avatar.helpful_mode_topics or "",
            "hobby_subs": avatar.hobby_subreddits or [],
            "karma": avatar.karma_comment,
            "subreddit_karma": {
                "subreddit": target_sub,
                "comment_karma": sub_karma_record.comment_karma if sub_karma_record else 0,
                "post_karma": sub_karma_record.post_karma if sub_karma_record else 0,
                "total": sub_total,
            },
        })

    # Sort so the prompt presents the most credible avatars first — provides
    # the model an explicit ranking signal in addition to the numeric column.
    personas_data.sort(
        key=lambda p: (-p["subreddit_karma"]["total"], p["username"])
    )

    thread_content = f"""Subreddit: r/{thread.subreddit}
Alert: {thread.alert}

## Post title:
{thread.post_title}

## Post text:
{thread.post_body or '(no body)'}

## Comments:
{thread.comments_json or '(no comments)'}"""

    system_prompt = PERSONA_SELECT_PROMPT.format(
        personas_json=json.dumps(personas_data, indent=2),
        brand_name=client.brand_name,
        company_worldview=client.company_worldview or "",
        company_problem=client.company_problem or "",
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": thread_content},
    ]

    try:
        result = call_llm_json(
            messages=messages,
            model=get_config("llm_generation_model"),
            temperature=0.4,
            max_tokens=512,
        )
    except Exception as e:
        logger.error(
            f"LLM call failed in select_persona for thread '{thread.post_title[:40]}' "
            f"client={client.client_name}: {e}"
        )
        raise RuntimeError(f"Persona selection LLM failed: {e}") from e

    try:
        log_ai_usage(db, str(client.id), "persona_select", result)
    except Exception:
        logger.warning("Failed to log AI usage for persona_select")

    logger.info(
        f"Selected persona '{result['data'].get('persona_username')}' "
        f"({result['data'].get('mode')}) for thread '{thread.post_title[:40]}'"
    )

    return result["data"]


# --- Comment Generation ---

COMMENT_WRITER_PROMPT = """# Reddit Comment Writer

You are writing a Reddit comment as the avatar described below.
You are a cynical, experienced practitioner. You type fast, don't explain yourself,
and never write essays.

## Rules (in order of priority)
1. Be SHORT. 20-60 words. Hard max 80 words.
2. Be SHARP. Clear point of view, no fence-sitting.
3. Be STRATEGIC. Plant one seed that changes how the reader thinks.

## Never:
- Mention the client's brand or product by name. ZERO TOLERANCE.
- Use em-dashes (—). Ever.
- Use buzzwords: landscape, ecosystem, leverage, unlock, delve, shift, hit
- Start with "I [verb]" more than 30% of the time
- Write more than one paragraph

## Voice Profile
{voice_profile}

## Company Context (for worldview only, NEVER mention brand)
Worldview: {company_worldview}
Problem: {company_problem}

## Engagement Strategy
Mode: {mode}
Thread angle: {thread_angle}
POV opportunity: {pov_opportunity}

## Previous comments (avoid repetition)
{previous_comments}

## Output JSON
{{
  "comment": "the exact comment text",
  "comment_to": "quote of who we reply to, or 'post' if replying to the post",
  "location_depth": 0,
  "location_reasoning": "why this spot",
  "comment_approach": "reframe_drop | cynical_deconstruction | the_scar | contrarian | drive_by",
  "strategic_angle": "reframe | tear_down | karma_play"
}}"""


def generate_comment(
    db: Session,
    thread: RedditThread,
    client: Client,
    avatar: Avatar,
    persona_selection: dict,
    previous_comments: list[str] | None = None,
) -> CommentDraft:
    """Generate a comment for a thread using the selected avatar.

    Returns:
        Created CommentDraft instance.

    Raises:
        RuntimeError: If LLM call fails.
    """
    # Runtime assertion: avatar must belong to this client
    assert avatar.client_ids and str(client.id) in avatar.client_ids, (
        f"Context isolation violation: avatar {avatar.reddit_username} "
        f"does not belong to client {client.id}"
    )

    prev_comments_text = "\n---\n".join(previous_comments or [])
    if not prev_comments_text:
        prev_comments_text = "(no previous comments)"

    thread_content = f"""## Thread

### Post title
{thread.post_title}

### Post text
{thread.post_body or '(no body)'}

### Comments
{thread.comments_json or '(no comments)'}"""

    system_prompt = COMMENT_WRITER_PROMPT.format(
        voice_profile=avatar.voice_profile_md or "",
        company_worldview=client.company_worldview or "",
        company_problem=client.company_problem or "",
        mode=persona_selection.get("mode", "helpful_peer"),
        thread_angle=persona_selection.get("thread_angle", ""),
        pov_opportunity=persona_selection.get("pov_opportunity", ""),
        previous_comments=prev_comments_text,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": thread_content},
    ]

    try:
        result = call_llm_json(
            messages=messages,
            model=get_config("llm_generation_model"),
            temperature=0.7,
            max_tokens=512,
            schema=CommentOutput,
        )
    except Exception as e:
        logger.error(
            f"LLM call failed in generate_comment for thread '{thread.post_title[:40]}' "
            f"avatar={avatar.reddit_username}: {e}"
        )
        raise RuntimeError(f"Comment generation LLM failed: {e}") from e

    try:
        log_ai_usage(db, str(client.id), "generation", result)
    except Exception:
        logger.warning("Failed to log AI usage for generation")

    data = result["data"]

    # Create draft
    draft = CommentDraft(
        thread_id=thread.id,
        client_id=client.id,
        avatar_id=avatar.id,
        type=thread.type or "professional",
        ai_draft=data.get("comment", ""),
        comment_to=data.get("comment_to", "post"),
        location_depth=data.get("location_depth", 0),
        location_reasoning=data.get("location_reasoning", ""),
        comment_approach=data.get("comment_approach", ""),
        strategic_angle=data.get("strategic_angle", ""),
        engagement_mode=persona_selection.get("mode", "helpful_peer"),
        status="pending",
    )

    try:
        db.add(draft)
        db.commit()
        db.refresh(draft)
    except Exception as e:
        logger.error(f"DB error saving comment draft for thread {thread.id}: {e}")
        db.rollback()
        raise RuntimeError(f"Failed to save comment draft: {e}") from e

    # Audit log for AI-generated draft
    try:
        from app.services.audit import log_system_action
        log_system_action(
            db=db,
            action="generate",
            entity_type="comment_draft",
            entity_id=draft.id,
            client_id=client.id,
            details={
                "avatar_username": avatar.reddit_username,
                "thread_title": thread.post_title[:100],
                "engagement_mode": persona_selection.get("mode", ""),
            },
        )
    except Exception:
        logger.warning("Failed to audit log generated draft")

    logger.info(
        f"Generated comment for thread '{thread.post_title[:40]}' "
        f"by avatar '{avatar.reddit_username}'"
    )

    return draft


# --- Comment Editor (quality check) ---

EDITOR_PROMPT = """# Comment Editor

Fix this AI-generated Reddit comment to sound like an actual human typed it.
Output ONLY the corrected comment text. No JSON, no explanation.

## Rules
- Must sound like someone typing on their phone between meetings
- No em-dashes (—) ever. Use parentheses or commas instead.
- No blank lines between paragraphs
- Lowercase by default (only capitalize proper names, acronyms, first word)
- All contractions: "you are" → "you're", "it is" → "it's"
- Delete "just" (filler word)
- No buzzwords: landscape, ecosystem, leverage, game-changer
- No "I'd push" / "I'd argue" — state directly
- No guru/yoda endings that sound like motivational posters
- Must connect to specific details from the post

## Draft comment:
{draft}

## Original post title:
{post_title}

## Original post:
{post_body}

Output ONLY the fixed comment text, nothing else."""


def edit_comment(
    db: Session,
    draft: CommentDraft,
    thread: RedditThread,
    client: Client,
) -> str:
    """Run the editor prompt on a draft comment to clean up AI artifacts.

    Returns:
        The edited comment text (original text returned if editing fails).
    """
    messages = [
        {
            "role": "system",
            "content": EDITOR_PROMPT.format(
                draft=draft.ai_draft,
                post_title=thread.post_title,
                post_body=(thread.post_body or "")[:1000],
            ),
        },
        {
            "role": "user",
            "content": f"Edit this comment:\n\n{draft.ai_draft}",
        },
    ]

    try:
        result = call_llm(
            messages=messages,
            model=get_config("llm_generation_model"),
            temperature=0.3,
            max_tokens=256,
        )
    except Exception as e:
        logger.error(f"LLM call failed in edit_comment for draft {draft.id}: {e}")
        # Return original text — editing is non-critical
        return draft.ai_draft or ""

    try:
        log_ai_usage(db, str(client.id), "editing", result)
    except Exception:
        logger.warning("Failed to log AI usage for editing")

    edited = result["content"].strip()

    # Update draft with edited version
    try:
        draft.ai_draft = edited
        db.commit()
    except Exception as e:
        logger.error(f"DB error saving edited draft {draft.id}: {e}")
        db.rollback()
        return edited  # Return edited text even if DB save fails

    logger.info(f"Edited comment {draft.id}")

    return edited
