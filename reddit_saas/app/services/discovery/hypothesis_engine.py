"""Hypothesis Engine — LLM-based hypothesis formation for Discovery sessions.

Uses Gemini Flash to generate 3-7 testable hypotheses about a client's Reddit
ecosystem relevance. Each hypothesis includes at least one quantifiable Reddit
metric (subscriber count, post volume, engagement level, or comment frequency).

Hypotheses are informed by extracted entities, prior confirmed directions, and
rejection reasons from previous iterations. Deduplication ensures no statement
is repeated across iterations.
"""

import asyncio
import hashlib
import json
import uuid

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.discovery_entity import DiscoveryEntity
from app.models.discovery_hypothesis import DiscoveryHypothesis
from app.models.discovery_session import DiscoverySession
from app.services.ai import call_llm_json, log_ai_usage

logger = get_logger(__name__)

# Model: fast + cheap for hypothesis generation
HYPOTHESIS_MODEL = "gemini/gemini-2.5-flash-lite"

VALID_CATEGORIES = {"clients", "partners", "feedback", "recognition", "hiring", "market_research"}

HYPOTHESIS_SYSTEM_PROMPT = """You are a Reddit ecosystem strategist specializing in B2B market research.

Your task: Generate testable hypotheses about a client's potential Reddit relevance.

RULES:
- Generate between 3 and 7 hypotheses
- Each hypothesis MUST be a testable statement that includes at least ONE quantifiable Reddit metric:
  * subscriber count (e.g., "subreddits with 10K+ subscribers")
  * post volume (e.g., "20+ posts per month discussing...")
  * engagement level (e.g., "average 15+ upvotes on posts about...")
  * comment frequency (e.g., "5+ comments per discussion thread about...")
- Each hypothesis MUST be categorized as EXACTLY one of: clients, partners, feedback, recognition, hiring, market_research
  * "clients" = potential client acquisition opportunities on Reddit
  * "partners" = partnership or collaboration signals
  * "feedback" = product feedback and user sentiment discussions
  * "recognition" = brand recognition, mentions, and awareness
  * "hiring" = talent acquisition and recruitment signals
  * "market_research" = market intelligence and competitive insights
- Each hypothesis statement must be unique and specific (max 1000 characters)
- Each hypothesis must reference at least one of the provided entities
- Include a reasoning chain (max 500 characters) explaining the logical connection

OUTPUT FORMAT (strict JSON):
{
  "hypotheses": [
    {
      "statement": "A testable statement with a quantifiable Reddit metric...",
      "category": "clients|partners|feedback|recognition|hiring|market_research",
      "triggering_entities": ["Entity Name 1", "Entity Name 2"],
      "reasoning": "Why this hypothesis is worth testing..."
    }
  ]
}

Focus on hypotheses that would be valuable for a business considering Reddit as a marketing/engagement channel. Think about what Reddit data could prove or disprove about the client's fit with the platform."""

HYPOTHESIS_USER_PROMPT = """Client entities to base hypotheses on:
{entities_text}

{context_section}

Generate 3-7 testable hypotheses about this client's Reddit relevance. Each MUST include a quantifiable Reddit metric. Return JSON only."""

HYPOTHESIS_RETRY_PROMPT = """Client entities to base hypotheses on:
{entities_text}

{context_section}

IMPORTANT: The previous attempt returned fewer than 3 hypotheses. Please generate MORE hypotheses (aim for 5-7). Consider:
- Different Reddit metric types (subscribers, post volume, engagement, comment frequency)
- Different category angles (clients, partners, feedback, recognition, hiring, market_research)
- Broader interpretations of the entities
- Adjacent topics that relate to the entities

Generate 5-7 testable hypotheses about this client's Reddit relevance. Each MUST include a quantifiable Reddit metric. Return JSON only."""


def _build_entities_text(entities: list[DiscoveryEntity]) -> str:
    """Format entities into a readable text block for the prompt."""
    lines = []
    for entity in entities:
        lines.append(f"- {entity.name} (category: {entity.category})")
    return "\n".join(lines)


def _build_context_section(
    session: DiscoverySession,
    prior_hypotheses: list[DiscoveryHypothesis] | None,
    rejection_context: list[dict] | None,
) -> str:
    """Build the context section with confirmed directions, rejections, and exclusions."""
    sections = []

    if prior_hypotheses:
        # Build exclusion list
        exclusion_statements = [h.statement for h in prior_hypotheses]
        if exclusion_statements:
            sections.append(
                "EXCLUSION LIST — Do NOT generate hypotheses similar to these (already proposed):\n"
                + "\n".join(f"- {stmt}" for stmt in exclusion_statements)
            )

        # Confirmed directions to build upon
        confirmed = [h for h in prior_hypotheses if h.status == "confirmed"]
        if confirmed:
            sections.append(
                "CONFIRMED DIRECTIONS — Build upon these validated findings:\n"
                + "\n".join(f"- {h.statement} (confidence: {h.confidence_score})" for h in confirmed)
            )

    if rejection_context:
        # Rejection reasons to avoid
        rejection_lines = []
        for ctx in rejection_context:
            stmt = ctx.get("statement", "")
            reason = ctx.get("rejection_reason", "")
            if stmt and reason:
                rejection_lines.append(f"- REJECTED: \"{stmt}\" — Reason: {reason}")
        if rejection_lines:
            sections.append(
                "REJECTION CONTEXT — These hypotheses were rejected. Generate refined alternatives that address the rejection reasons:\n"
                + "\n".join(rejection_lines)
            )

    if not sections:
        return "This is the first iteration. Generate fresh hypotheses based on the entities above."

    return "\n\n".join(sections)


def _compute_prompt_hash(messages: list[dict]) -> str:
    """Compute a hash of the prompt for provenance tracking."""
    prompt_text = json.dumps(messages, sort_keys=True)
    return hashlib.sha256(prompt_text.encode()).hexdigest()[:16]


def _validate_hypothesis_item(item: dict, entity_names: set[str]) -> dict | None:
    """Validate a single hypothesis item from LLM output.

    Returns cleaned item dict or None if invalid.
    """
    if not isinstance(item, dict):
        return None

    statement = item.get("statement", "").strip()
    category = item.get("category", "").strip().lower()
    triggering_entities = item.get("triggering_entities", [])
    reasoning = item.get("reasoning", "").strip()

    # Validate required fields
    if not statement or not category:
        return None

    # Validate category
    if category not in VALID_CATEGORIES:
        return None

    # Enforce max lengths
    statement = statement[:1000]
    reasoning = reasoning[:500]

    # Validate triggering_entities is a list of strings
    if not isinstance(triggering_entities, list):
        triggering_entities = []
    triggering_entities = [
        str(e).strip() for e in triggering_entities
        if isinstance(e, str) and str(e).strip()
    ]

    # If no triggering entities provided, try to match from statement
    if not triggering_entities:
        for name in entity_names:
            if name.lower() in statement.lower():
                triggering_entities.append(name)
                break

    return {
        "statement": statement,
        "category": category,
        "triggering_entities": triggering_entities,
        "reasoning": reasoning,
    }


async def form_hypotheses(
    entities: list[DiscoveryEntity],
    session: DiscoverySession,
    prior_hypotheses: list[DiscoveryHypothesis] | None = None,
    rejection_context: list[dict] | None = None,
    db: Session | None = None,
) -> list[DiscoveryHypothesis]:
    """Generate testable hypotheses about a client's Reddit relevance.

    Uses Gemini Flash to form 3-7 hypotheses per iteration. Each hypothesis
    includes at least one quantifiable Reddit metric. Handles retry if <3
    hypotheses are returned, deduplication against prior iterations, and
    stores provenance JSONB.

    Args:
        entities: List of confirmed DiscoveryEntity records for this session.
        session: The active DiscoverySession.
        prior_hypotheses: Optional list of hypotheses from prior iterations (for dedup/context).
        rejection_context: Optional list of dicts with "statement" and "rejection_reason" keys.
        db: Database session. If None, uses the session object's bound session.

    Returns:
        List of stored DiscoveryHypothesis records.

    Raises:
        TimeoutError: If LLM call exceeds 30 seconds.
        ValueError: If LLM returns completely invalid output.
    """
    from sqlalchemy import inspect

    # Resolve DB session
    if db is None:
        db = inspect(session).session

    entity_names = {e.name for e in entities}
    entities_text = _build_entities_text(entities)
    context_section = _build_context_section(session, prior_hypotheses, rejection_context)

    # Build exclusion set for dedup
    prior_statements = set()
    if prior_hypotheses:
        prior_statements = {h.statement.strip().lower() for h in prior_hypotheses}

    # Build entity lookup for provenance
    entity_lookup = {e.name: {"id": str(e.id), "name": e.name, "category": e.category} for e in entities}

    # First attempt
    validated_items = await _call_and_validate(
        entities_text=entities_text,
        context_section=context_section,
        entity_names=entity_names,
        prior_statements=prior_statements,
        retry=False,
        session_id=session.id,
    )

    # Retry once with expanded prompt if <3 hypotheses
    if len(validated_items) < 3:
        logger.warning(
            "Hypothesis formation returned only %d items (< 3) for session %s. Retrying with expanded prompt.",
            len(validated_items),
            session.id,
        )
        retry_items = await _call_and_validate(
            entities_text=entities_text,
            context_section=context_section,
            entity_names=entity_names,
            prior_statements=prior_statements,
            retry=True,
            session_id=session.id,
        )
        # Merge retry results with first attempt (dedup by statement)
        existing_statements = {item["statement"].strip().lower() for item in validated_items}
        for item in retry_items:
            if item["statement"].strip().lower() not in existing_statements:
                validated_items.append(item)
                existing_statements.add(item["statement"].strip().lower())

    # Cap at 7 hypotheses max
    validated_items = validated_items[:7]

    if len(validated_items) == 0:
        raise ValueError(
            f"Hypothesis formation produced 0 valid hypotheses for session {session.id}"
        )

    # Store hypotheses in DB
    stored_hypotheses: list[DiscoveryHypothesis] = []
    for item in validated_items:
        # Build provenance JSONB
        triggering_entity_data = []
        for ent_name in item["triggering_entities"]:
            if ent_name in entity_lookup:
                triggering_entity_data.append(entity_lookup[ent_name])
            else:
                # Fuzzy match: find entity whose name appears in the triggering entity string
                for key, val in entity_lookup.items():
                    if key.lower() in ent_name.lower() or ent_name.lower() in key.lower():
                        triggering_entity_data.append(val)
                        break

        provenance = {
            "triggering_entities": triggering_entity_data,
            "reasoning": item["reasoning"],
            "llm_prompt_hash": item.get("prompt_hash", ""),
        }

        hypothesis = DiscoveryHypothesis(
            session_id=session.id,
            iteration_number=session.current_iteration,
            statement=item["statement"],
            category=item["category"],
            confidence_score=50,
            confidence_delta=0,
            status="proposed",
            provenance=provenance,
        )
        db.add(hypothesis)
        stored_hypotheses.append(hypothesis)

    db.flush()  # Get IDs assigned without committing

    # Log AI usage
    # We log a single entry for the hypothesis formation operation
    # The result dict is stored from the last successful call
    try:
        log_ai_usage(
            db=db,
            client_id=None,  # Discovery is pre-client (prospect research)
            operation="discovery",
            result=_last_llm_result,
            triggered_by=f"hypothesis_formation:{session.id}",
        )
    except Exception as e:
        logger.warning("Failed to log AI usage for hypothesis formation: %s", e)

    # Persist full prompt/response as artifact
    try:
        from app.services.discovery.artifact_store import store_artifact
        store_artifact(
            db=db,
            session_id=session.id,
            operation="hypothesis_formation",
            inputs={"entities_count": len(entity_names) if 'entity_names' in dir() else 0, "iteration": session.current_iteration},
            prompt=str(_last_llm_result.get("messages", ""))[:5000],
            response=str(_last_llm_result.get("data", ""))[:5000],
            model=str(_last_llm_result.get("model", HYPOTHESIS_MODEL)),
            cost_usd=float(_last_llm_result.get("cost_usd", _last_llm_result.get("cost", 0)) or 0),
            tokens={"input": _last_llm_result.get("input_tokens", 0), "output": _last_llm_result.get("output_tokens", 0)},
            outcome="success",
            result_summary=f"Formed {len(stored_hypotheses)} hypotheses",
        )
    except Exception as e:
        logger.warning("Failed to store hypothesis formation artifact: %s", e)

    # Update session running total
    try:
        from app.services.discovery.session_manager import update_ai_cost
        update_ai_cost(session_id=session.id, cost_delta=float(_last_llm_result.get("cost_usd", 0)), db=db)
    except Exception as e:
        logger.warning("Failed to update session AI cost: %s", e)

    db.commit()

    logger.info(
        "Generated %d hypotheses for session %s (iteration %d)",
        len(stored_hypotheses),
        session.id,
        session.current_iteration,
    )

    return stored_hypotheses


# Module-level variable to track the last LLM result for AI usage logging
_last_llm_result: dict = {}


async def _call_and_validate(
    entities_text: str,
    context_section: str,
    entity_names: set[str],
    prior_statements: set[str],
    retry: bool,
    session_id: uuid.UUID,
) -> list[dict]:
    """Call LLM and validate hypothesis output.

    Args:
        entities_text: Formatted entity text for the prompt.
        context_section: Context section with confirmed/rejected/exclusion info.
        entity_names: Set of entity names for validation.
        prior_statements: Set of lowercased prior statements for dedup.
        retry: Whether this is the retry attempt (uses expanded prompt).
        session_id: Session ID for logging.

    Returns:
        List of validated hypothesis item dicts.
    """
    global _last_llm_result

    # Choose prompt template based on retry flag
    user_prompt_template = HYPOTHESIS_RETRY_PROMPT if retry else HYPOTHESIS_USER_PROMPT
    user_content = user_prompt_template.format(
        entities_text=entities_text,
        context_section=context_section,
    )

    messages = [
        {"role": "system", "content": HYPOTHESIS_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    prompt_hash = _compute_prompt_hash(messages)

    # call_llm_json is synchronous (uses litellm.completion) — run in thread
    # to avoid blocking the async event loop. 30s timeout per spec.
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                call_llm_json,
                messages=messages,
                model=HYPOTHESIS_MODEL,
                temperature=0.5,
                max_tokens=4096,
                schema=None,  # We handle validation manually for flexibility
            ),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        logger.error(
            "Hypothesis formation timed out (30s) for session %s (retry=%s)",
            session_id,
            retry,
        )
        raise TimeoutError(
            f"Hypothesis formation timed out after 30 seconds for session {session_id}"
        )

    _last_llm_result = result
    data = result["data"]

    if not data or "hypotheses" not in data:
        logger.warning(
            "Hypothesis formation returned no hypotheses key for session %s",
            session_id,
        )
        return []

    raw_hypotheses = data["hypotheses"]
    if not isinstance(raw_hypotheses, list):
        logger.warning(
            "Hypothesis formation returned non-list hypotheses for session %s",
            session_id,
        )
        return []

    # Validate and dedup
    validated_items: list[dict] = []
    seen_statements: set[str] = set()

    for item in raw_hypotheses:
        validated = _validate_hypothesis_item(item, entity_names)
        if validated is None:
            continue

        # Dedup against prior iterations
        stmt_lower = validated["statement"].strip().lower()
        if stmt_lower in prior_statements:
            logger.debug(
                "Skipping duplicate hypothesis (matches prior iteration): %s",
                validated["statement"][:80],
            )
            continue

        # Dedup within current batch
        if stmt_lower in seen_statements:
            continue

        seen_statements.add(stmt_lower)
        validated["prompt_hash"] = prompt_hash
        validated_items.append(validated)

    return validated_items
