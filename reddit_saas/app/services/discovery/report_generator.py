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

# Model: Gemini Flash for speed + cost (structured JSON output)
# Fallback to Claude Sonnet via MODEL_FALLBACK_CHAIN if Flash fails
REPORT_MODEL = "gemini/gemini-2.5-flash"

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

    # Safety cap: use top-7 by confidence_score for report focus + cost control.
    # Remaining confirmed hypotheses are mentioned briefly as "also validated".
    MAX_REPORT_HYPOTHESES = 7
    if len(confirmed) > MAX_REPORT_HYPOTHESES:
        confirmed_sorted = sorted(confirmed, key=lambda h: h.confidence_score or 0, reverse=True)
        primary_hypotheses = confirmed_sorted[:MAX_REPORT_HYPOTHESES]
        secondary_hypotheses = confirmed_sorted[MAX_REPORT_HYPOTHESES:]
        logger.info(
            "Session %s has %d confirmed hypotheses, using top-%d for report (by confidence)",
            session.id, len(confirmed), MAX_REPORT_HYPOTHESES,
        )
    else:
        primary_hypotheses = confirmed
        secondary_hypotheses = []

    # Aggregate hypotheses by category for concise prompt
    hypotheses_text = _aggregate_hypotheses_by_category(primary_hypotheses)
    signals_summary = _format_signals_summary(primary_hypotheses)
    no_signal_text = ""  # Aggregated view doesn't need separate no-signal section
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
            ) + (_format_secondary_brief(secondary_hypotheses) if secondary_hypotheses else ""),
        },
    ]

    # call_llm is synchronous (uses litellm.completion) — run in thread
    # to avoid blocking the async event loop. 180s timeout — reports with many hypotheses need more time.
    # max_tokens=8192: Gemini Flash reports typically need 5000-7000 tokens for full JSON.
    # 4096 was causing truncation → invalid JSON → parse failure.
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                call_llm,
                messages=messages,
                model=REPORT_MODEL,
                temperature=0.4,
                max_tokens=8192,
                timeout=90,
            ),
            timeout=120.0,
        )
    except asyncio.TimeoutError:
        logger.error(
            "Report generation timed out (120s) for session %s", session.id
        )
        raise TimeoutError(
            f"Report generation timed out after 120 seconds for session {session.id}"
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

    # Persist full prompt/response as artifact
    try:
        from app.services.discovery.artifact_store import store_artifact
        store_artifact(
            db=db,
            session_id=session.id,
            operation="report_generation",
            inputs={"hypotheses_confirmed": len([h for h in session.hypotheses if h.status == 'confirmed'])},
            prompt=str(messages)[:8000] if 'messages' in dir() else "",
            response=str(result.get("data", result.get("content", "")))[:8000],
            model=str(result.get("model", REPORT_MODEL)),
            cost_usd=float(result.get("cost_usd", result.get("cost", 0)) or 0),
            tokens={"input": result.get("input_tokens", 0), "output": result.get("output_tokens", 0)},
            outcome="success",
            result_summary=f"Generated Visibility Report v{version}",
        )
    except Exception as e:
        logger.warning("Failed to store report generation artifact: %s", e)

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
    4. Truncated JSON (attempts to close open braces/brackets)
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
            # Try to repair truncated JSON from code block
            repaired = _try_repair_truncated_json(block)
            if repaired is not None:
                return repaired

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
                repaired = _try_repair_truncated_json(block.strip())
                if repaired is not None:
                    return repaired

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

        # 4. If we reached end without closing all braces — JSON is truncated
        # Try to repair by closing open structures
        candidate = text[brace_start:]
        repaired = _try_repair_truncated_json(candidate)
        if repaired is not None:
            return repaired

    return None


def _try_repair_truncated_json(text: str) -> dict | None:
    """Attempt to repair truncated JSON by closing open structures.

    This handles the common case where max_tokens cuts off mid-JSON.
    Strategy: find the last complete key-value pair, close all open structures.
    """
    if not text or "{" not in text:
        return None

    # Strip trailing incomplete value (after last complete comma or colon)
    # Find last complete line ending with a comma or value
    lines = text.rstrip().split("\n")

    # Try progressively removing lines from the end until we can close valid JSON
    for trim_count in range(min(len(lines), 20)):
        candidate_lines = lines[:len(lines) - trim_count] if trim_count > 0 else lines
        candidate = "\n".join(candidate_lines).rstrip().rstrip(",")

        # Count open braces/brackets
        open_braces = candidate.count("{") - candidate.count("}")
        open_brackets = candidate.count("[") - candidate.count("]")

        if open_braces < 0 or open_brackets < 0:
            continue

        # Close all open structures
        suffix = "]" * open_brackets + "}" * open_braces
        attempt = candidate + suffix

        try:
            parsed = json.loads(attempt)
            if isinstance(parsed, dict):
                logger.warning(
                    "Repaired truncated JSON by closing %d braces, %d brackets (trimmed %d lines)",
                    open_braces, open_brackets, trim_count,
                )
                return parsed
        except json.JSONDecodeError:
            continue

    return None


def _aggregate_hypotheses_by_category(hypotheses) -> str:
    """Aggregate confirmed hypotheses into category clusters for concise prompting.

    Instead of listing 5-7 individual hypotheses verbatim, groups them by category
    and summarizes key signals per group. Reduces prompt size by ~60%.
    """
    from collections import defaultdict

    by_category: dict[str, list] = defaultdict(list)
    for h in hypotheses:
        by_category[h.category].append(h)

    lines = []
    for category, hyps in sorted(by_category.items()):
        # Collect all subreddits across hypotheses in this category
        all_subs = []
        total_posts = 0
        avg_confidence = sum(h.confidence_score or 0 for h in hyps) / len(hyps)

        for h in hyps:
            signals = h.reddit_signals or {}
            total_posts += signals.get("total_posts_found", 0)
            for sub in signals.get("subreddits", []):
                if sub.get("name") and sub["name"] not in [s.get("name") for s in all_subs]:
                    all_subs.append(sub)

        # Sort subs by relevance
        top_subs = sorted(all_subs, key=lambda s: s.get("relevance_score", 0), reverse=True)[:5]
        sub_text = ", ".join(
            f"{s.get('name', '?')} ({s.get('subscribers', 0):,} members, rel:{s.get('relevance_score', 0)})"
            for s in top_subs
        ) if top_subs else "no specific communities identified"

        lines.append(
            f"[{category.upper()}] {len(hyps)} validated hypotheses (avg confidence: {avg_confidence:.0f}/100)\n"
            f"  Key findings: {'; '.join(h.statement[:100] for h in hyps[:3])}\n"
            f"  Communities: {sub_text}\n"
            f"  Total posts found: {total_posts}"
        )

    return "\n\n".join(lines)


def _format_secondary_brief(hypotheses) -> str:
    """Format secondary (overflow) hypotheses as a brief addendum to the prompt."""
    if not hypotheses:
        return ""
    lines = ["\n\nADDITIONAL VALIDATED HYPOTHESES (mention briefly, do not detail):"]
    for h in hypotheses:
        lines.append(f"- [{h.category}] {h.statement} (confidence: {h.confidence_score}/100)")
    return "\n".join(lines)


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
