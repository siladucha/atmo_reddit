"""Report Generator — produces Visibility Report from confirmed hypotheses.

Uses Claude Sonnet to generate a structured, professional report that serves
as the $4K setup fee deliverable. The report answers: "What can Reddit
potentially give this client in the next 6-12 months?"

Follows async patterns from entity_extractor.py:
- asyncio.wait_for() for 60s timeout
- asyncio.to_thread() to call synchronous LLM function
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.discovery_hypothesis import DiscoveryHypothesis
from app.models.discovery_session import DiscoverySession
from app.models.visibility_report import VisibilityReport
from app.schemas.discovery import VisibilityReportContent
from app.services.ai import call_llm, log_ai_usage

logger = get_logger(__name__)

# Model: high-quality prose for sales artifact
REPORT_MODEL = "anthropic/claude-sonnet-4-20250514"

REPORT_SYSTEM_PROMPT = """You are a senior Reddit ecosystem strategist writing a professional assessment report.

Your task: Generate a comprehensive Visibility Report that answers the question:
"What can Reddit potentially give this client in the next 6-12 months?"

The report must be evidence-based — every claim must reference specific Reddit data (subreddit names, subscriber counts, post volumes, engagement levels).

OUTPUT FORMAT (strict JSON with these exact keys):
{
  "executive_summary": "200-500 word overview of Reddit potential for this client",
  "demand_assessment": "Analysis of how strongly the client's domain is represented on Reddit",
  "communities": [
    {
      "name": "r/subreddit_name",
      "subscribers": 50000,
      "daily_posts": 15,
      "relevance": 85,
      "approach": "Recommended engagement approach for this community"
    }
  ],
  "discussion_activity": "Analysis of discussion patterns, volume trends, peak activity",
  "entry_points": ["Specific thread types or recurring topics where the client can add value"],
  "competitive_landscape": "Who else is active in these communities, what competitors are doing",
  "visibility_outcomes": [
    {
      "type": "clients|partners|feedback|recognition|hiring|market_research",
      "probability": "high|medium|low",
      "reasoning": "1-3 sentences explaining why this outcome is likely"
    }
  ],
  "risks_and_limitations": "Honest assessment of gaps, weak signals, areas with no Reddit presence"
}

RULES:
- Return ONLY valid JSON. No markdown, no code blocks, no extra text.
- "communities" must have at least 1 entry.
- "visibility_outcomes" must have at least 1 entry.
- "entry_points" must have at least 1 string entry.
- All numeric fields (subscribers, daily_posts, relevance) must be integers.
- "relevance" is 0-100.
- "probability" must be exactly one of: "high", "medium", "low".
- "type" must be exactly one of: "clients", "partners", "feedback", "recognition", "hiring", "market_research".

TONE: Professional, data-driven, actionable. This is a sales artifact — it should inspire confidence while being honest about limitations. Write for a CMO or VP Marketing audience."""

REPORT_USER_PROMPT = """CLIENT BRIEF:
{client_brief}

EXTRACTED ENTITIES:
{entities_text}

CONFIRMED HYPOTHESES (validated against Reddit data):
{hypotheses_text}

NO-SIGNAL AREAS (where Reddit has limited/no relevant discussions):
{no_signal_text}

REDDIT DATA SUMMARY:
{signals_summary}

Generate the Visibility Report as a single JSON object. Every recommendation must cite specific Reddit evidence from the confirmed hypotheses above. Be specific about subreddit names, subscriber counts, and engagement levels."""


async def generate_visibility_report(
    session: DiscoverySession,
    db: Session,
) -> VisibilityReport:
    """Generate Visibility Report from confirmed hypotheses using Claude Sonnet.

    Uses call_llm() (prose-capable) with JSON output instruction in the prompt.
    Validates the parsed output with Pydantic VisibilityReportContent schema.

    Args:
        session: Discovery session with confirmed hypotheses loaded.
        db: Database session.

    Returns:
        Stored VisibilityReport record.

    Raises:
        ValueError: If no confirmed hypotheses or LLM output fails validation.
        TimeoutError: If LLM call exceeds 60 seconds.
    """
    # Gather confirmed hypotheses
    confirmed = [h for h in session.hypotheses if h.status == "confirmed"]
    if not confirmed:
        raise ValueError(
            f"Cannot generate report for session {session.id}: no confirmed hypotheses"
        )

    # Build prompt context
    hypotheses_text = _format_hypotheses(confirmed)
    no_signal_text = _format_no_signal(session.hypotheses)
    signals_summary = _format_signals_summary(confirmed)
    entities_text = _format_entities(session.entities)

    messages = [
        {"role": "system", "content": REPORT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": REPORT_USER_PROMPT.format(
                client_brief=session.client_brief[:3000],
                entities_text=entities_text,
                hypotheses_text=hypotheses_text,
                no_signal_text=no_signal_text or "None — all hypotheses had signal.",
                signals_summary=signals_summary,
            ),
        },
    ]

    # call_llm is synchronous (uses litellm.completion) — run in thread
    # to avoid blocking the async event loop. 60s timeout per spec.
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                call_llm,
                messages=messages,
                model=REPORT_MODEL,
                temperature=0.4,
                max_tokens=4096,
            ),
            timeout=60.0,
        )
    except asyncio.TimeoutError:
        logger.error(
            "Report generation timed out (60s) for session %s", session.id
        )
        raise TimeoutError(
            f"Report generation timed out after 60 seconds for session {session.id}"
        )

    raw_content = result["content"]

    if not raw_content or not raw_content.strip():
        raise ValueError(
            f"Report generation returned empty response for session {session.id}"
        )

    # Parse the LLM output into structured dict
    parsed = _extract_report_json(raw_content)
    if parsed is None:
        raise ValueError(
            f"Failed to parse report JSON from LLM response for session {session.id}. "
            f"Response preview: {raw_content[:300]!r}"
        )

    # Validate with Pydantic schema
    try:
        validated = VisibilityReportContent.model_validate(parsed)
        content_dict = validated.model_dump()
    except ValidationError as e:
        raise ValueError(
            f"Report content failed schema validation for session {session.id}: {e}"
        ) from e

    # Determine version number (increment if session already has reports)
    existing_count = len(session.reports) if session.reports else 0
    version = existing_count + 1

    # Create and store report record
    report = VisibilityReport(
        session_id=session.id,
        content=content_dict,
        report_version=version,
        model_used=REPORT_MODEL,
        generation_cost_usd=result["cost_usd"],
    )
    db.add(report)

    # Update session status to completed
    session.status = "completed"
    session.completed_at = datetime.now(timezone.utc)

    db.flush()

    # Log AI usage with operation="discovery", sub-type "report_generation"
    try:
        log_ai_usage(
            db=db,
            client_id=str(session.client_id) if session.client_id else None,
            operation="discovery",
            result=result,
            triggered_by=f"report_generation:{session.id}",
        )
    except Exception as e:
        logger.warning("Failed to log AI usage for report generation: %s", e)

    # Update session running total
    try:
        from app.services.discovery.session_manager import update_ai_cost
        update_ai_cost(session_id=session.id, cost_delta=float(result["cost_usd"]), db=db)
    except Exception as e:
        logger.warning("Failed to update session AI cost: %s", e)

    db.commit()

    logger.info(
        "Generated Visibility Report v%d for session %s (cost=$%.4f, model=%s)",
        version,
        session.id,
        result["cost_usd"],
        result["model"],
    )

    return report


def _extract_report_json(content: str) -> dict | None:
    """Extract JSON object from LLM response content.

    Handles multiple formats:
    1. Pure JSON string
    2. Markdown code blocks (```json ... ```)
    3. Prose-wrapped JSON (text before/after JSON block)
    """
    if not content or not content.strip():
        return None

    text = content.strip()

    # 1. Try direct JSON parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Extract from markdown code blocks
    if "```json" in text:
        block = text.split("```json", 1)[1]
        if "```" in block:
            block = block.split("```", 1)[0]
        block = block.strip()
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            pass

    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            block = parts[1].strip()
            # Remove optional language hint on first line
            if block and block.split("\n")[0].isalpha():
                block = "\n".join(block.split("\n")[1:])
            try:
                return json.loads(block.strip())
            except json.JSONDecodeError:
                pass

    # 3. Find the outermost { ... } block (handles nested objects)
    brace_start = text.find("{")
    if brace_start != -1:
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[brace_start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        pass
                    break

    return None


def _format_hypotheses(hypotheses: list[DiscoveryHypothesis]) -> str:
    """Format confirmed hypotheses for the report prompt."""
    lines = []
    for i, h in enumerate(hypotheses, 1):
        signals = h.reddit_signals or {}
        subs = signals.get("subreddits", [])
        sub_text = ", ".join(
            s.get("name", "") for s in subs[:5]
        ) if subs else "no specific subreddits identified"

        lines.append(
            f"{i}. [{h.category.upper()}] {h.statement}\n"
            f"   Confidence: {h.confidence_score}/100 | Communities: {sub_text}\n"
            f"   Posts found: {signals.get('total_posts_found', 0)} | "
            f"Avg engagement: {signals.get('avg_engagement_overall', 0)}"
        )
    return "\n\n".join(lines)


def _format_no_signal(hypotheses: list[DiscoveryHypothesis]) -> str:
    """Format no-signal hypotheses for the report prompt."""
    no_signal_hypos = [
        h for h in hypotheses
        if h.reddit_signals and h.reddit_signals.get("no_signal")
    ]
    if not no_signal_hypos:
        return ""
    lines = []
    for h in no_signal_hypos:
        ns = h.reddit_signals.get("no_signal", {})
        cause = ns.get("cause", "unknown")
        explanation = ns.get("explanation", "")
        lines.append(f"- {h.statement} ({cause}: {explanation})")
    return "\n".join(lines)


def _format_signals_summary(hypotheses: list[DiscoveryHypothesis]) -> str:
    """Summarize all Reddit signals across confirmed hypotheses."""
    all_subs: dict[str, dict] = {}
    total_posts = 0

    for h in hypotheses:
        signals = h.reddit_signals or {}
        total_posts += signals.get("total_posts_found", 0)
        for sub in signals.get("subreddits", []):
            name = sub.get("name", "")
            if name and name not in all_subs:
                all_subs[name] = sub

    # Sort by relevance score
    sorted_subs = sorted(
        all_subs.values(),
        key=lambda s: s.get("relevance_score", 0),
        reverse=True,
    )

    lines = [f"Total posts found across all hypotheses: {total_posts}"]
    lines.append(f"Unique subreddits identified: {len(sorted_subs)}")
    lines.append("\nTop communities by relevance:")
    for sub in sorted_subs[:10]:
        lines.append(
            f"  - {sub.get('name')}: {sub.get('subscribers', 0):,} members, "
            f"~{sub.get('posts_30d', 0)} posts/month, "
            f"avg engagement {sub.get('avg_engagement', 0)}, "
            f"relevance {sub.get('relevance_score', 0)}/100"
        )

    return "\n".join(lines)


def _format_entities(entities) -> str:
    """Format extracted entities for the report prompt."""
    if not entities:
        return "No entities extracted."

    by_category: dict[str, list[str]] = {}
    for entity in entities:
        cat = entity.category
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(entity.name)

    lines = []
    for category, names in sorted(by_category.items()):
        lines.append(f"  {category}: {', '.join(names)}")

    return "\n".join(lines)
