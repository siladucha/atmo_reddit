"""Entity Extractor — LLM-based entity extraction from client brief.

Uses Gemini Flash to identify 3-20 named entities from the client's free-text
description of their business. Entities become the targets for Reddit research.
"""

import asyncio
import uuid

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.discovery_entity import DiscoveryEntity
from app.schemas.discovery import EntityExtractionOutput, ExtractedEntity
from app.services.ai import call_llm_json, log_ai_usage

logger = get_logger(__name__)

# Model: fast + cheap for entity extraction
ENTITY_EXTRACTION_MODEL = "gemini/gemini-2.5-flash-lite"

ENTITY_EXTRACTION_SYSTEM_PROMPT = """You are a business analyst specializing in B2B market research and Reddit ecosystem analysis.

Your task: Extract key business entities from the client description below.

RULES:
- Extract between 3 and 20 entities
- Each entity must be categorized as EXACTLY one of: product, audience, problem, industry, competitor, use_case
- "product" = specific product/service the client offers
- "audience" = target customer segment, persona, or buyer type
- "problem" = pain point or challenge the client solves
- "industry" = vertical, market, or domain the client operates in
- "competitor" = named competitors or alternative solutions
- "use_case" = specific application, scenario, or workflow

OUTPUT FORMAT (strict JSON):
{
  "entities": [
    {"name": "Entity Name", "category": "product|audience|problem|industry|competitor|use_case"},
    ...
  ]
}

Extract entities that would be useful for researching whether Reddit has active discussions about this client's domain. Focus on concrete, specific terms that people would actually search for or discuss on Reddit. Prefer named products, specific audience segments, and well-defined problems over vague concepts."""

ENTITY_EXTRACTION_USER_PROMPT = """Client description:

{client_brief}

Extract all relevant business entities from this description. Return JSON only."""


async def extract_entities(
    client_brief: str,
    db: Session,
    session_id: uuid.UUID,
) -> dict:
    """Extract named entities from client brief using Gemini Flash.

    Uses call_llm_json() with Pydantic schema validation. If the LLM returns
    fewer than 3 entities, the function does NOT fail — it returns what was
    found with a flag indicating insufficient entities.

    Args:
        client_brief: Free-text client description (50-5000 chars).
        db: Database session.
        session_id: Discovery session ID for FK linkage and cost tracking.

    Returns:
        Dict with keys:
            - entities: list[DiscoveryEntity] — stored entity records
            - insufficient: bool — True if fewer than 3 entities were extracted
            - count: int — number of entities extracted

    Raises:
        ValueError: If LLM returns completely invalid output (no entities at all).
        Exception: On LLM timeout or unrecoverable API error.
    """
    messages = [
        {"role": "system", "content": ENTITY_EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": ENTITY_EXTRACTION_USER_PROMPT.format(client_brief=client_brief)},
    ]

    # call_llm_json is synchronous (uses litellm.completion) — run in thread
    # to avoid blocking the async event loop. Timeout is handled by litellm
    # internally (60s default in call_llm), but we wrap with asyncio timeout
    # per spec requirement of 30s.
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                call_llm_json,
                messages=messages,
                model=ENTITY_EXTRACTION_MODEL,
                temperature=0.3,
                max_tokens=2048,
                schema=None,  # We handle validation manually for edge case <3
            ),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        logger.error(
            "Entity extraction timed out (30s) for session %s", session_id
        )
        raise TimeoutError(
            f"Entity extraction timed out after 30 seconds for session {session_id}"
        )

    data = result["data"]

    if not data or "entities" not in data:
        logger.warning(
            "Entity extraction returned no entities for session %s", session_id
        )
        raise ValueError("LLM returned invalid entity extraction output — no entities key")

    raw_entities = data["entities"]
    if not isinstance(raw_entities, list) or len(raw_entities) == 0:
        raise ValueError("LLM returned empty entities list")

    # Validate individual entities — salvage valid ones even if some are malformed
    valid_categories = {"product", "audience", "problem", "industry", "competitor", "use_case"}
    validated_entities: list[ExtractedEntity] = []

    for item in raw_entities:
        if not isinstance(item, dict):
            continue
        name = item.get("name", "").strip()
        category = item.get("category", "").strip().lower()
        if name and category in valid_categories:
            validated_entities.append(
                ExtractedEntity(name=name[:200], category=category)
            )

    # Cap at 20 entities max
    validated_entities = validated_entities[:20]

    if len(validated_entities) == 0:
        raise ValueError(
            f"Entity extraction produced 0 valid entities from {len(raw_entities)} raw items "
            f"for session {session_id}"
        )

    # Determine if we have insufficient entities (<3)
    insufficient = len(validated_entities) < 3

    if insufficient:
        logger.warning(
            "Entity extraction returned only %d entities (< 3 required) for session %s. "
            "Returning what was found with insufficient flag.",
            len(validated_entities),
            session_id,
        )

    # Try full Pydantic validation (min_length=3) — if it passes, great
    # If it fails due to <3, we still proceed with what we have
    try:
        EntityExtractionOutput(entities=validated_entities)
    except ValidationError:
        # Expected when <3 entities — we handle this gracefully
        pass

    # Store entities in DB as DiscoveryEntity records
    stored_entities: list[DiscoveryEntity] = []
    for entity_data in validated_entities:
        entity = DiscoveryEntity(
            session_id=session_id,
            name=entity_data.name,
            category=entity_data.category,
            source="extracted",
        )
        db.add(entity)
        stored_entities.append(entity)

    db.flush()  # Get IDs assigned without committing

    # Log AI usage with operation="discovery", sub-type in triggered_by context
    try:
        log_ai_usage(
            db=db,
            client_id=None,  # Discovery is pre-client (prospect research)
            operation="discovery",
            result=result,
            triggered_by=f"entity_extraction:{session_id}",
        )
    except Exception as e:
        logger.warning("Failed to log AI usage for entity extraction: %s", e)

    # Update session running total
    try:
        from app.services.discovery.session_manager import update_ai_cost
        update_ai_cost(session_id=session_id, cost_delta=float(result["cost_usd"]), db=db)
    except Exception as e:
        logger.warning("Failed to update session AI cost: %s", e)

    db.commit()

    logger.info(
        "Extracted %d entities for session %s (insufficient=%s)",
        len(stored_entities),
        session_id,
        insufficient,
    )

    return {
        "entities": stored_entities,
        "insufficient": insufficient,
        "count": len(stored_entities),
    }
