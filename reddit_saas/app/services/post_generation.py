"""Post generation service — brief strategy + post writing.

Adapted from Ori's n8n workflow: Brief Generator → Persona Selection → Post Writer.
Separates strategy (what to write) from execution (how to write it).
"""

import json
import logging

from sqlalchemy.orm import Session

from app.config import get_config
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.post_draft import PostDraft
from app.services.ai import call_llm, call_llm_json, log_ai_usage
from app.schemas.llm_outputs import PostBriefOutput, PostWriterOutput

logger = logging.getLogger(__name__)


# --- Brief Generator Prompt ---

BRIEF_GENERATOR_PROMPT = """# Reddit Post Brief Generator

**Purpose:** Convert a topic direction into a strategic brief that the Reddit Post Writer executes. You make every strategic decision here. The writer receives orders, not options.

## ROLE

You are the **Reddit strategist** for a persona-driven engagement system. Your job is to analyze the topic, classify it, make every strategic call, and hand off a precise execution brief. You do not write posts.

## CONTEXT

Brand: {brand_name}
Worldview: {company_worldview}
Problem the brand solves: {company_problem}
Target subreddit: r/{subreddit}
Competitive landscape: {competitive_landscape}

## PERSONA

Username: {avatar_username}
Voice summary: {voice_summary}
Hill they die on: {hill_i_die_on}
Helpful topics: {helpful_topics}

## ANALYSIS STEPS

### Step 1: Classify Input Treatment Mode
- **original** — Self-post from persona experience/opinion/question
- **discussion_catalyst** — Open discussion prompt designed for contribution
- **inspiration** — Convert external trigger into native angle

### Step 2: Priority Ladder
- **worldview** — Input naturally touches company worldview. Persona expresses as genuine belief.
- **problem_awareness** — Input discusses approach company contradicts. Make reader doubt, leave gap open.
- **community_value** — No natural worldview fit. Earn karma, build authority.

### Step 3: Select Post Type
Pick ONE: personal_narrative, career_frustration, hot_take, discussion_prompt, research_analysis, tool_showcase, leadership_question

### Step 4: Select Body Architecture
- **narrative_arc** — Setup → complication → resolution/irony → reflection
- **evidence_stack** — Hook → context → evidence → example → implication
- **rant_with_structure** — Bold claim → credentialing → evidence → concession → open question

### Step 5: Title Direction
Give the writer a direction (archetype, info density, emotional register, subreddit tone match).

## OUTPUT FORMAT (JSON)

{{
  "input_treatment": "original | discussion_catalyst | inspiration",
  "post_type": "personal_narrative | career_frustration | hot_take | discussion_prompt | research_analysis | tool_showcase | leadership_question",
  "strategic_tier": "worldview | problem_awareness | community_value",
  "body_architecture": "narrative_arc | evidence_stack | rant_with_structure",
  "title_direction": {{
    "archetype": "personal_narrative | frustration_manifesto | specific_number | curiosity_gap | named_entity",
    "info_density": "what specific details the title should contain",
    "emotional_register": "what the reader should feel",
    "subreddit_tone": "how the community voice shapes the title"
  }},
  "hook": "one-sentence opening angle",
  "angle": "the guiding thesis or perspective",
  "worldview_note": "how the worldview emerges naturally, or null if community_value",
  "quality_concern": "flag issues or null"
}}"""


# --- Post Writer Prompt ---

POST_WRITER_PROMPT = """# Reddit Post Writer

**Purpose:** Execute a strategic brief into a Reddit post (title + body) that passes as an authentic community contribution.

## ROLE

You are writing a Reddit post **as** the persona described below. You are not a ghostwriter. You have opinions, frustrations, and things you learned the hard way. You're posting because something triggered a reaction.

## NORTH STAR

**Memorable over helpful.** Sharp, specific, one-thesis posts outperform broad "helpful" synthesis.

- Pick one core thought. Go deep.
- Plant seeds, not forests. One realization beats five talking points.
- Leave tension open. Over-closure kills discussion.
- The best posts make the reader feel something: recognition, doubt, frustration, humor.

## VOICE PROFILE

{voice_profile}

## COMPANY CONTEXT (for worldview only, NEVER mention brand)

Worldview: {company_worldview}
Problem: {company_problem}

## STRATEGIC BRIEF

Input treatment: {input_treatment}
Post type: {post_type}
Strategic tier: {strategic_tier}
Body architecture: {body_architecture}
Hook: {hook}
Angle: {angle}
Worldview note: {worldview_note}
Title direction: {title_direction}

## RULES (NON-NEGOTIABLE)

1. NEVER mention the client's brand or product by name. ZERO TOLERANCE.
2. No em-dashes (—). Use commas, parentheses, or split the sentence.
3. No buzzwords: landscape, ecosystem, leverage, unlock, delve, shift, holistic, comprehensive.
4. No academic transitions: However, Moreover, Furthermore, Additionally.
5. No binary oppositions: "It's not X, it's Y" / "Stop X. Start Y."
6. No passive voice.
7. Mandatory contractions: "you are" → "you're", "it is" → "it's".
8. Lowercase by default (only capitalize proper nouns, acronyms, sentence starts).
9. No Rule-of-Three (never list exactly 3 items — use 2 or 4+).
10. No CTA. No "what do you think?" No "link in comments."
11. Body length: 100-600 words depending on post type.
12. Title must be self-contained — can be discussed without reading the body.

## PREVIOUS POSTS (avoid repetition)

{previous_posts}

## OUTPUT FORMAT (JSON)

{{
  "title": "the exact post title",
  "body": "the exact post body text",
  "subreddit": "target_subreddit_name",
  "post_type": "the post type used",
  "input_treatment": "the treatment mode used",
  "strategic_tier": "the tier used",
  "worldview_seed": "description of embedded worldview observation, or null",
  "body_architecture": "the architecture used"
}}"""


# --- Topic Generation Prompt ---

TOPIC_GENERATOR_PROMPT = """# Reddit Post Topic Generator

Generate a compelling topic direction for a Reddit post in r/{subreddit}.

## CONTEXT

Brand worldview: {company_worldview}
Problem the brand solves: {company_problem}
Persona's hill they die on: {hill_i_die_on}
Persona's helpful topics: {helpful_topics}

## RECENT POSTS BY THIS PERSONA (avoid repetition)

{previous_posts}

## SUBREDDIT CONTEXT

Target: r/{subreddit}
This is a {subreddit_type} subreddit.

## TASK

Generate ONE topic direction that:
1. Fits naturally in r/{subreddit}
2. The persona would credibly post about
3. Has high engagement potential (controversy, shared frustration, or genuine insight)
4. Hasn't been covered in recent posts

Output a single paragraph describing the topic direction, angle, and what makes it timely or relevant. No JSON, just the topic description."""


def generate_post_topic(
    db: Session,
    client: Client,
    avatar: Avatar,
    subreddit: str,
    previous_posts: list[str] | None = None,
) -> str:
    """Generate a topic direction for a post.

    Returns:
        Topic direction string.
    """
    prev_text = "\n---\n".join(previous_posts or [])
    if not prev_text:
        prev_text = "(no previous posts)"

    # Determine subreddit type from avatar's subreddit lists
    hobby_subs = avatar.hobby_subreddits or []
    business_subs = avatar.business_subreddits or []
    if subreddit in hobby_subs:
        sub_type = "hobby/general interest"
    elif subreddit in business_subs:
        sub_type = "professional/industry"
    else:
        sub_type = "professional/industry"

    prompt = TOPIC_GENERATOR_PROMPT.format(
        subreddit=subreddit,
        company_worldview=client.company_worldview or "",
        company_problem=client.company_problem or "",
        hill_i_die_on=avatar.hill_i_die_on or "",
        helpful_topics=avatar.helpful_mode_topics or "",
        previous_posts=prev_text,
        subreddit_type=sub_type,
    )

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"Generate a topic for r/{subreddit}"},
    ]

    result = call_llm(
        messages=messages,
        model=get_config("llm_generation_model"),
        temperature=0.9,
        max_tokens=300,
    )

    try:
        log_ai_usage(db, str(client.id), "post_topic", result)
    except Exception:
        logger.warning("Failed to log AI usage for post_topic")

    return result["content"].strip()


def generate_post_brief(
    db: Session,
    client: Client,
    avatar: Avatar,
    subreddit: str,
    topic_direction: str,
) -> dict:
    """Generate a strategic brief for a post.

    Returns:
        Dict with brief fields (input_treatment, post_type, strategic_tier, etc.)

    Raises:
        RuntimeError: If LLM call fails.
    """
    system_prompt = BRIEF_GENERATOR_PROMPT.format(
        brand_name=client.brand_name,
        company_worldview=client.company_worldview or "",
        company_problem=client.company_problem or "",
        competitive_landscape=(client.competitive_landscape or "")[:2000],
        subreddit=subreddit,
        avatar_username=avatar.reddit_username,
        voice_summary=(avatar.voice_profile_md or "")[:500],
        hill_i_die_on=avatar.hill_i_die_on or "",
        helpful_topics=avatar.helpful_mode_topics or "",
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"## Topic Direction\n\n{topic_direction}\n\n## Target Subreddit\nr/{subreddit}"},
    ]

    try:
        result = call_llm_json(
            messages=messages,
            model=get_config("llm_generation_model"),
            temperature=0.4,
            max_tokens=800,
            schema=PostBriefOutput,
        )
    except Exception as e:
        logger.error(f"Brief generation failed for r/{subreddit}: {e}")
        raise RuntimeError(f"Post brief generation LLM failed: {e}") from e

    try:
        log_ai_usage(db, str(client.id), "post_brief", result)
    except Exception:
        logger.warning("Failed to log AI usage for post_brief")

    return result["data"]


def generate_post(
    db: Session,
    client: Client,
    avatar: Avatar,
    subreddit: str,
    brief: dict,
    previous_posts: list[str] | None = None,
) -> PostDraft:
    """Generate a post from a strategic brief.

    Returns:
        Created PostDraft instance.

    Raises:
        RuntimeError: If LLM call fails.
    """
    # Runtime assertion: avatar must belong to this client
    assert avatar.client_ids and str(client.id) in avatar.client_ids, (
        f"Context isolation violation: avatar {avatar.reddit_username} "
        f"does not belong to client {client.id}"
    )

    prev_text = "\n---\n".join(previous_posts or [])
    if not prev_text:
        prev_text = "(no previous posts)"

    title_direction_str = json.dumps(brief.get("title_direction", {}), indent=2)

    system_prompt = POST_WRITER_PROMPT.format(
        voice_profile=avatar.voice_profile_md or "",
        company_worldview=client.company_worldview or "",
        company_problem=client.company_problem or "",
        input_treatment=brief.get("input_treatment", "original"),
        post_type=brief.get("post_type", "discussion_prompt"),
        strategic_tier=brief.get("strategic_tier", "community_value"),
        body_architecture=brief.get("body_architecture", "narrative_arc"),
        hook=brief.get("hook", ""),
        angle=brief.get("angle", ""),
        worldview_note=brief.get("worldview_note") or "none",
        title_direction=title_direction_str,
        previous_posts=prev_text,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Write the post for r/{subreddit}. Follow the brief exactly."},
    ]

    try:
        result = call_llm_json(
            messages=messages,
            model=get_config("llm_generation_model"),
            temperature=0.7,
            max_tokens=1500,
            schema=PostWriterOutput,
        )
    except Exception as e:
        logger.error(
            f"Post generation failed for r/{subreddit} "
            f"avatar={avatar.reddit_username}: {e}"
        )
        raise RuntimeError(f"Post generation LLM failed: {e}") from e

    try:
        log_ai_usage(db, str(client.id), "post_generation", result)
    except Exception:
        logger.warning("Failed to log AI usage for post_generation")

    data = result["data"]

    # Create draft
    draft = PostDraft(
        client_id=client.id,
        avatar_id=avatar.id,
        subreddit=data.get("subreddit", subreddit).replace("r/", ""),
        ai_title=data.get("title", ""),
        ai_body=data.get("body", ""),
        brief=json.dumps(brief, ensure_ascii=False),
        status="pending",
    )

    try:
        db.add(draft)
        db.commit()
        db.refresh(draft)
    except Exception as e:
        logger.error(f"DB error saving post draft for r/{subreddit}: {e}")
        db.rollback()
        raise RuntimeError(f"Failed to save post draft: {e}") from e

    # Audit log
    try:
        from app.services.audit import log_system_action
        log_system_action(
            db=db,
            action="generate",
            entity_type="post_draft",
            entity_id=draft.id,
            client_id=client.id,
            details={
                "avatar_username": avatar.reddit_username,
                "subreddit": subreddit,
                "post_type": brief.get("post_type", ""),
                "strategic_tier": brief.get("strategic_tier", ""),
            },
        )
    except Exception:
        logger.warning("Failed to audit log generated post draft")

    logger.info(
        f"Generated post for r/{subreddit} by avatar '{avatar.reddit_username}' "
        f"type={brief.get('post_type')} tier={brief.get('strategic_tier')}"
    )

    return draft
