"""Comment and post generation service.

Handles persona selection, comment writing, and quality editing.
Uses prompts adapted from Ori's PoC.
"""

import json
from app.logging_config import get_logger

from sqlalchemy.orm import Session

from app.config import get_config
from app.models.client import Client
from app.models.thread import RedditThread
from app.models.avatar import Avatar
from app.models.comment_draft import CommentDraft
from app.services.ai import call_llm, call_llm_json, log_ai_usage
from app.schemas.llm_outputs import CommentOutput

logger = get_logger(__name__)


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
        ValueError: If all candidate avatars fail the accessibility check.
    """
    from app.services.isolation import _avatar_accessible_by_client

    # Runtime isolation check: filter out avatars not accessible by this client
    # (supports both ownership via client_ids AND active rentals)
    accessible_avatars: list[Avatar] = []
    for avatar in avatars:
        if _avatar_accessible_by_client(db, avatar, client):
            accessible_avatars.append(avatar)
        else:
            logger.warning(
                "Context isolation: avatar '%s' (id=%s) is not accessible by "
                "client '%s' (id=%s) — excluded from persona candidates",
                avatar.reddit_username,
                avatar.id,
                client.client_name,
                client.id,
            )

    if not accessible_avatars:
        raise ValueError(
            f"All candidate avatars failed accessibility check for client "
            f"'{client.client_name}' (id={client.id}). "
            f"Original candidates: {[a.reddit_username for a in avatars]}"
        )

    avatars = accessible_avatars

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
        log_ai_usage(
            db, str(client.id), "persona_select", result,
            thread_id=str(thread.id),
            subreddit_name=thread.subreddit,
        )
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
1. Be SHORT. 20-60 words. Hard max 80 words. If over 80 — REWRITE with a shorter idea, don't trim.
2. Be SHARP. Clear point of view, no fence-sitting.
3. Be STRATEGIC. Plant one seed that changes how the reader thinks.

## FORBIDDEN PATTERNS (zero tolerance)

### Never use:
- Em-dashes (—). Use commas, parentheses, or split the sentence.
- Buzzwords: landscape, ecosystem, leverage, unlock, delve, shift, holistic, comprehensive, robust, game-changer, cutting-edge, revolutionary, best practice
- Academic transitions: However, Moreover, Furthermore, Additionally, Consequently
- Distancing phrases: "This highlights," "The data suggests," "It's worth noting"
- Empty questions: "The result?" "What happened next?" "Sound familiar?"
- Generic openings: "Here's the thing," "Picture this," "Imagine this," "Look,"
- Binary oppositions: "It's not X, it's Y" / "Stop X. Start Y."
- Passive voice (every verb needs a clear actor)
- LinkedIn spacing (every sentence on its own line)
- Staccato dry-cut sentences without connectors

### Banned sentence starters:
- NEVER start with "The", "This", "That", "There", "They" (rephrase)
- NEVER start with gerunds: "Trying," "Looking," "Getting," "Running," "Building"
- NEVER start with "I'd argue" / "I'd push" / "I'd say" — state directly
- Do NOT start more than 30% of comments with "I [verb]..."

### Banned endings:
- No guru/yoda endings that sound like motivational posters
- No "food for thought" / "just my two cents" / "take it for what it's worth"
- No generic questions you don't actually want answered

## DIVERSITY ENFORCEMENT (check before writing)

Scan the previous_comments below. Your new comment MUST differ from all of them:

1. **Opener scan**: If >30% start with same structure (e.g. "I [verb]..."), use a DIFFERENT opener type
2. **Approach scan**: If one approach dominates (>40%), use a DIFFERENT approach
3. **Vocabulary scan**: Any phrase appearing 3+ times = BANNED for this comment
4. **Structure scan**: If last 3 comments follow same arc, use a DIFFERENT structure

Opener types to rotate between:
- Flat agreement + pivot: "yeah, except..." / "sure, until..."
- Lead with the claim (no "I" setup)
- Dry reaction: "lol good luck with that at scale"
- Direct response to a detail: "the part about X is backwards..."
- Conditional pushback: "works if..." / "depends entirely on..."
- Personal experience (use sparingly, not every time)

## Voice Profile
{voice_profile}

## Company Context (for worldview only, NEVER mention brand)
Worldview: {company_worldview}
Problem: {company_problem}

## Engagement Strategy
Mode: {mode}
Thread angle: {thread_angle}
POV opportunity: {pov_opportunity}

## Previous comments (avoid repetition — run diversity checks above)
{previous_comments}

## Output JSON
{{
  "comment": "the exact comment text",
  "comment_to": "quote of who we reply to, or 'post' if replying to the post",
  "location_depth": 0,
  "location_reasoning": "why this spot",
  "comment_approach": "reframe_drop | cynical_deconstruction | the_scar | contrarian | drive_by",
  "strategic_angle": "reframe | tear_down | karma_play",
  "perspective_push": "hard | medium | low | undetected"
}}"""


def _assert_context_isolation(
    client: Client,
    avatar: Avatar,
    strategy,
    examples: list,
    patterns: list,
) -> None:
    """Verify every context item belongs to the target client_id.

    Checks:
    - Strategy document's avatar belongs to the client
    - All learning examples (EditRecords) belong to the client
    - All correction patterns belong to the client

    Raises:
        RuntimeError: If any context item violates client isolation.
    """
    client_id_str = str(client.id)

    # Check strategy document — it's loaded via avatar, verify avatar ownership
    if strategy is not None:
        # Strategy is loaded for the avatar; verify the avatar belongs to client
        if not (avatar.client_ids and client_id_str in avatar.client_ids):
            logger.error(
                "Context isolation ABORT: strategy document (id=%s) loaded for avatar %s "
                "which does not belong to client %s",
                getattr(strategy, "id", "unknown"),
                avatar.reddit_username,
                client.id,
            )
            raise RuntimeError(
                f"Context isolation violation: strategy for avatar {avatar.reddit_username} "
                f"does not belong to client {client.id}"
            )

    # Check learning examples (EditRecords have client_id)
    for ex in examples:
        ex_client_id = str(getattr(ex, "client_id", None) or "")
        if ex_client_id != client_id_str:
            logger.error(
                "Context isolation ABORT: EditRecord (id=%s) has client_id=%s, "
                "expected client_id=%s",
                getattr(ex, "id", "unknown"),
                ex_client_id,
                client.id,
            )
            raise RuntimeError(
                f"Context isolation violation: EditRecord {getattr(ex, 'id', 'unknown')} "
                f"belongs to client {ex_client_id}, not target client {client.id}"
            )

    # Check correction patterns (CorrectionPatterns have client_id)
    for pat in patterns:
        pat_client_id = str(getattr(pat, "client_id", None) or "")
        if pat_client_id != client_id_str:
            logger.error(
                "Context isolation ABORT: CorrectionPattern (id=%s) has client_id=%s, "
                "expected client_id=%s",
                getattr(pat, "id", "unknown"),
                pat_client_id,
                client.id,
            )
            raise RuntimeError(
                f"Context isolation violation: CorrectionPattern {getattr(pat, 'id', 'unknown')} "
                f"belongs to client {pat_client_id}, not target client {client.id}"
            )


def generate_comment(
    db: Session,
    thread: RedditThread,
    client: Client,
    avatar: Avatar,
    persona_selection: dict,
    previous_comments: list[str] | None = None,
) -> CommentDraft:
    """Generate a comment for a thread using the selected avatar.

    Integrates:
    - Strategy injection: if an approved strategy exists for this avatar,
      injects tone guidelines and cadence rules into the system prompt.
    - Self-learning loop: retrieves few-shot examples and correction
      patterns from past human edits, injects them into the system prompt.

    Both injections are non-critical — if any call fails, generation
    proceeds normally without degradation.

    Returns:
        Created CommentDraft instance.

    Raises:
        ValueError: If client_id is null.
        RuntimeError: If LLM call fails or context isolation assertion fails.
    """
    # 1. Validate client_id is not null
    if not client or not client.id:
        raise ValueError("LLM context assembly requires a valid client_id")

    # 2. Assert avatar is accessible by client (owned OR rented)
    from app.services.isolation import _avatar_accessible_by_client

    if not _avatar_accessible_by_client(db, avatar, client):
        logger.error(
            "Context isolation violation: avatar %s (id=%s) not accessible by client %s",
            avatar.reddit_username,
            avatar.id,
            client.id,
        )
        raise RuntimeError(
            f"Context isolation violation: avatar {avatar.reddit_username} "
            f"not accessible by client {client.id}"
        )

    # --- Strategy Injection: retrieve approved strategy ---
    strategy_context = ""
    approved_strategy = None
    try:
        from app.services.strategy_engine import StrategyEngine

        strategy_engine = StrategyEngine()
        approved_strategy = strategy_engine.get_approved_strategy(db, avatar.id, client_id=client.id)

        if approved_strategy:
            # Build strategy context from structured fields
            parts = []
            if approved_strategy.tone_guidelines:
                tone = approved_strategy.tone_guidelines
                avoid_list = tone.get("avoid", [])
                parts.append(f"Tone: {tone.get('formality', 'casual')}, humor={tone.get('humor', 'subtle')}, expertise={tone.get('expertise', 'peer')}")
                if avoid_list:
                    parts.append(f"Avoid: {', '.join(avoid_list[:5])}")

            if approved_strategy.cadence_rules:
                cadence = approved_strategy.cadence_rules
                if isinstance(cadence, list):
                    # Weekly cadence — find current week's rules
                    # For now just note the overall approach
                    current = cadence[0] if cadence else {}
                    hobby_pct = current.get("hobby_percent", 100)
                    pro_pct = current.get("professional_percent", 0)
                    if pro_pct == 0:
                        parts.append("Focus: hobby/community engagement only (no professional topics yet)")
                elif isinstance(cadence, dict):
                    pro_ratio = cadence.get("pro_ratio", 0)
                    if pro_ratio == 0:
                        parts.append("Focus: hobby/community engagement only (no professional topics yet)")

            if approved_strategy.goals:
                goals = approved_strategy.goals
                if isinstance(goals, list) and goals:
                    goal_summaries = [g.get("description", g.get("objective", "")) for g in goals[:2]]
                    goal_summaries = [g for g in goal_summaries if g]
                    if goal_summaries:
                        parts.append(f"Goals: {'; '.join(goal_summaries)}")

            if parts:
                strategy_context = "## Avatar Strategy (approved)\n" + "\n".join(f"- {p}" for p in parts)
                logger.info(
                    "Strategy context injected for avatar %s (v%d)",
                    avatar.reddit_username,
                    approved_strategy.version,
                )
    except Exception:
        logger.warning(
            "Failed to retrieve strategy for avatar %s — proceeding without",
            avatar.id,
        )
        strategy_context = ""

    # --- Self-Learning Loop: retrieve learning context ---
    learning_context = ""
    learning_metadata: dict | None = None
    examples = []
    patterns = []

    try:
        from app.services.learning import LearningService

        learning_service = LearningService()

        # Select few-shot examples from past edits
        examples = learning_service.select_few_shot_examples(
            db,
            avatar_id=avatar.id,
            client_id=client.id,
            subreddit=thread.subreddit,
            engagement_mode=persona_selection.get("mode", "helpful_peer"),
        )

        # Get correction patterns (returns empty if <5 qualifying records)
        patterns = learning_service.get_correction_patterns(
            db, avatar_id=avatar.id, client_id=client.id
        )

        # Format learning context for prompt injection
        if examples or patterns:
            learning_context = learning_service.format_learning_context(
                examples, patterns
            )

            # Build provenance metadata
            edit_record_ids = [str(ex.id) for ex in examples]
            correction_pattern_texts = [p.rule_text for p in patterns]
            learning_token_count = len(learning_context) // 4  # rough approximation

            learning_metadata = {
                "edit_record_ids": edit_record_ids,
                "correction_patterns": correction_pattern_texts,
                "learning_token_count": learning_token_count,
            }

            logger.info(
                "Learning context prepared for avatar %s: %d examples, %d patterns, ~%d tokens",
                avatar.reddit_username,
                len(examples),
                len(patterns),
                learning_token_count,
            )

    except Exception:
        # Learning is non-critical — generation must never fail due to learning
        logger.warning(
            "Failed to retrieve learning context for avatar %s, client %s — proceeding without",
            avatar.id,
            client.id,
        )
        learning_context = ""
        learning_metadata = None

    # --- Final context isolation assertion ---
    # Verify every loaded context item belongs to the target client_id
    _assert_context_isolation(
        client=client,
        avatar=avatar,
        strategy=approved_strategy if strategy_context else None,
        examples=examples if learning_context else [],
        patterns=patterns if learning_context else [],
    )

    # --- Build prompt ---
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

    # --- Approach Diversity: select and inject approach constraint ---
    approach_constraint = ""
    try:
        from app.services.approach_diversity import select_approach_for_avatar, format_approach_constraint
        from app.services import karma_tracker

        # Get avatar's karma in this specific subreddit
        sub_karma_record = karma_tracker.get_karma_in_subreddit(db, avatar.id, thread.subreddit)
        sub_karma = sub_karma_record.total_karma if sub_karma_record else 0

        selected_approach = select_approach_for_avatar(
            db,
            avatar=avatar,
            subreddit=thread.subreddit,
            subreddit_karma=sub_karma,
        )
        if selected_approach:
            approach_constraint = format_approach_constraint(selected_approach)
            logger.info(
                "Approach diversity: avatar=%s subreddit=r/%s karma=%d → forced approach=%s",
                avatar.reddit_username, thread.subreddit, sub_karma, selected_approach,
            )
    except Exception:
        # Approach diversity is non-critical — generation proceeds without constraint
        logger.warning(
            "Failed to compute approach diversity for avatar %s — proceeding without constraint",
            avatar.reddit_username,
        )
        approach_constraint = ""

    # Inject learning context between voice profile and thread content
    if learning_context:
        # Insert learning context after the Voice Profile section in the system prompt
        # The COMMENT_WRITER_PROMPT has "## Voice Profile\n{voice_profile}" followed by
        # "## Company Context" — we inject learning context between them
        voice_profile_content = avatar.voice_profile_md or ""
        injection_marker = f"## Voice Profile\n{voice_profile_content}"
        if injection_marker in system_prompt:
            system_prompt = system_prompt.replace(
                injection_marker,
                f"{injection_marker}\n\n{learning_context}\n",
            )
        else:
            # Fallback: append learning context before thread content in messages
            system_prompt = system_prompt + "\n\n" + learning_context

    # Inject strategy context after Engagement Strategy section
    if strategy_context:
        engagement_marker = "## Engagement Strategy"
        if engagement_marker in system_prompt:
            # Find the end of the Engagement Strategy section and inject after it
            idx = system_prompt.index(engagement_marker)
            # Find the next ## section after Engagement Strategy
            next_section = system_prompt.find("\n## ", idx + len(engagement_marker))
            if next_section != -1:
                system_prompt = (
                    system_prompt[:next_section]
                    + "\n\n" + strategy_context + "\n"
                    + system_prompt[next_section:]
                )
            else:
                system_prompt = system_prompt + "\n\n" + strategy_context
        else:
            system_prompt = system_prompt + "\n\n" + strategy_context


    # --- Subreddit Tone Context: inject emotional profile warnings ---
    tone_context = ""
    try:
        from app.services.emotional_profile import get_subreddit_tone_context
        tone_context = get_subreddit_tone_context(db, thread.subreddit) or ""
        if tone_context:
            logger.info(
                "Tone context injected for subreddit r/%s (avatar=%s)",
                thread.subreddit, avatar.reddit_username,
            )
    except Exception:
        logger.warning(
            "Failed to retrieve tone context for r/%s — proceeding without",
            thread.subreddit,
        )
        tone_context = ""

    if tone_context:
        system_prompt = system_prompt + "\n\n" + tone_context

    # Inject approach diversity constraint (after all other context)
    if approach_constraint:
        system_prompt = system_prompt + "\n" + approach_constraint

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
        log_ai_usage(
            db, str(client.id), "generation", result,
            avatar_id=str(avatar.id),
            thread_id=str(thread.id),
            subreddit_name=thread.subreddit,
        )
    except Exception:
        logger.warning("Failed to log AI usage for generation")

    data = result["data"]

    # Sanitize LLM output for Reddit-safe plain text
    from app.services.text_sanitizer import sanitize_for_reddit
    raw_comment = data.get("comment", "")
    sanitized_comment = sanitize_for_reddit(raw_comment)

    # Create draft with learning provenance metadata
    draft = CommentDraft(
        thread_id=thread.id,
        client_id=client.id,
        avatar_id=avatar.id,
        type=thread.type or "professional",
        ai_draft=sanitized_comment,
        comment_to=data.get("comment_to", "post"),
        location_depth=data.get("location_depth", 0),
        location_reasoning=data.get("location_reasoning", ""),
        comment_approach=data.get("comment_approach", ""),
        strategic_angle=data.get("strategic_angle", ""),
        perspective_push=data.get("perspective_push", "undetected"),
        engagement_mode=persona_selection.get("mode", "helpful_peer"),
        status="pending",
        learning_metadata=learning_metadata,
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
                "learning_examples_used": len(learning_metadata["edit_record_ids"]) if learning_metadata else 0,
                "learning_patterns_used": len(learning_metadata["correction_patterns"]) if learning_metadata else 0,
            },
        )
    except Exception:
        logger.warning("Failed to audit log generated draft")

    logger.info(
        f"Generated comment for thread '{thread.post_title[:40]}' "
        f"by avatar '{avatar.reddit_username}'"
        f"{' (with learning context)' if learning_metadata else ''}"
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
        log_ai_usage(
            db, str(client.id), "editing", result,
            avatar_id=str(draft.avatar_id),
            thread_id=str(thread.id),
            subreddit_name=thread.subreddit,
        )
    except Exception:
        logger.warning("Failed to log AI usage for editing")

    edited = result["content"].strip()

    # Sanitize editor output for Reddit-safe plain text
    from app.services.text_sanitizer import sanitize_for_reddit
    edited = sanitize_for_reddit(edited)

    # Update draft with edited version (overwrite ai_draft, preserve original)
    try:
        if not draft.original_ai_draft:
            draft.original_ai_draft = draft.ai_draft
        draft.ai_draft = edited
        db.commit()
    except Exception as e:
        logger.error(f"DB error saving edited draft {draft.id}: {e}")
        db.rollback()
        return edited  # Return edited text even if DB save fails

    logger.info(f"Edited comment {draft.id}")

    return edited
