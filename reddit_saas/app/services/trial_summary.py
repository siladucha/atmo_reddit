"""Sales Summary Generator — LLM-powered trial account briefings for sales team.

Generates structured sales intelligence summaries from trial score data.
Uses Claude Sonnet via LiteLLM with caching and invalidation logic.
"""

import json
import logging
import re
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import litellm
from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.trial_sales_summary import TrialSalesSummary
from app.models.trial_score import TrialScore

logger = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Jerusalem")

LLM_MODEL = "anthropic/claude-sonnet-4-20250514"
LLM_TIMEOUT = 15
CACHE_DURATION_HOURS = 24
MIN_SIGNALS_REQUIRED = 3

SYSTEM_PROMPT = (
    "You are a B2B sales intelligence analyst. Generate a structured sales "
    "briefing for an internal sales team preparing to contact a trial user. "
    "Be specific — cite exact actions and data points. Avoid generic statements."
)

SECTION_KEYS = [
    "client_identity",
    "activity_summary",
    "value_discovered",
    "problems_being_solved",
    "likely_objections",
]


class SalesSummaryGenerator:
    """Generates and caches LLM-powered sales briefings from trial score data."""

    def generate_summary(self, db: Session, client_id: UUID, score_id: UUID) -> dict:
        """Generate a sales summary from a TrialScore record.

        Loads the score, builds an LLM prompt from the signal snapshot,
        calls Claude Sonnet, and parses the response into 5 sections.

        Args:
            db: Database session.
            client_id: Client UUID.
            score_id: TrialScore UUID to generate summary from.

        Returns:
            Structured dict with 5 sections, or insufficient_data status.
        """
        score = db.query(TrialScore).filter(TrialScore.id == score_id).first()
        if not score:
            logger.warning("TrialScore %s not found", score_id)
            return {"status": "error", "message": "Score not found"}

        client = db.query(Client).filter(Client.id == client_id).first()
        if not client:
            logger.warning("Client %s not found", client_id)
            return {"status": "error", "message": "Client not found"}

        # Check minimum signals requirement
        snapshot = score.signal_snapshot or {}
        signals = snapshot.get("signals", [])

        if len(signals) < MIN_SIGNALS_REQUIRED:
            logger.info(
                "Insufficient data for client %s: %d signals (need %d)",
                client_id, len(signals), MIN_SIGNALS_REQUIRED,
            )
            return {
                "status": "insufficient_data",
                "available_signals": [
                    {"type": s.get("type"), "timestamp": s.get("created_at")}
                    for s in signals
                ],
            }

        # Build and send LLM prompt
        user_prompt = self._build_user_prompt(client, score, signals)
        response_text = self._call_llm(user_prompt)

        if response_text is None:
            return {"status": "error", "message": "LLM call failed or timed out"}

        # Parse response into sections
        sections = self._parse_sections(response_text, signals)

        return {
            "status": "success",
            "client_identity": sections.get("client_identity", ""),
            "activity_summary": sections.get("activity_summary", ""),
            "value_discovered": sections.get("value_discovered", ""),
            "problems_being_solved": sections.get("problems_being_solved", ""),
            "likely_objections": sections.get("likely_objections", ""),
        }

    def get_or_generate_summary(self, db: Session, client_id: UUID) -> dict:
        """Get cached summary or generate a new one.

        Checks if a TrialSalesSummary exists with the latest score_id.
        If match and not expired, returns cached content.
        If no match or expired, generates a new summary and stores it.

        Args:
            db: Database session.
            client_id: Client UUID.

        Returns:
            Structured dict with 5 sections, or status indicator.
        """
        # Get latest score for client
        latest_score = (
            db.query(TrialScore)
            .filter(TrialScore.client_id == client_id)
            .order_by(TrialScore.scored_at.desc())
            .first()
        )

        if not latest_score:
            logger.info("No TrialScore found for client %s", client_id)
            return {"status": "no_score", "message": "No trial score available"}

        # Check for existing cached summary
        cached = (
            db.query(TrialSalesSummary)
            .filter(TrialSalesSummary.client_id == client_id)
            .order_by(TrialSalesSummary.generated_at.desc())
            .first()
        )

        now = datetime.now(TZ)

        # If cache exists and score_id matches (not invalidated)
        if cached and cached.score_id == latest_score.id:
            # Cache hit — return stored content
            logger.info(
                "Cache hit for client %s, score %s (version %d)",
                client_id, latest_score.id, cached.sales_summary_version,
            )
            return self._deserialize_content(cached.content)

        # Cache miss or invalidation (score_id differs) — regenerate
        summary = self.generate_summary(db, client_id, latest_score.id)

        if summary.get("status") != "success":
            return summary

        # Store in TrialSalesSummary
        self._store_summary(db, client_id, latest_score.id, summary, cached)

        return summary

    def _build_user_prompt(self, client: Client, score: TrialScore, signals: list[dict]) -> str:
        """Build the user prompt from client data and score snapshot."""
        now = datetime.now(TZ)

        # Calculate days remaining
        if client.created_at:
            created = client.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=TZ)
            days_elapsed = (now - created).days
            days_remaining = max(0, 14 - days_elapsed)
        else:
            days_remaining = 14

        # Format signals by category
        formatted_signals = self._format_signals_by_category(signals)

        # Format score explanation
        score_explanation = score.score_explanation or {}
        score_explanation_formatted = self._format_score_explanation(score_explanation)

        prompt = (
            "## Trial Account Profile\n"
            f"- Company: {client.client_name}\n"
            f"- Domain: {client.brand_domain or 'Unknown'}\n"
            f"- Industry: {client.industry or 'Unknown'}\n"
            f"- Signed up: {client.created_at.strftime('%Y-%m-%d') if client.created_at else 'Unknown'}\n"
            f"- Days remaining: {days_remaining}\n"
            f"- Lifecycle state: {score.lifecycle_state}\n"
            f"- Conversion score: {score.conversion_score}/100\n"
            "\n"
            "## Activity During Trial (from signal_snapshot)\n"
            f"{formatted_signals}\n"
            "\n"
            "## Score Breakdown\n"
            f"{score_explanation_formatted}\n"
            "\n"
            "## Generate 5 sections:\n"
            "1. CLIENT IDENTITY — Who they are (1-2 sentences)\n"
            "2. ACTIVITY SUMMARY — What they did (bullet points with specific data)\n"
            "3. VALUE DISCOVERED — What value they found in the platform (specific reports, insights)\n"
            "4. PROBLEMS BEING SOLVED — Why they signed up, what pain they have (inferred)\n"
            "5. LIKELY OBJECTIONS — What might stop them from converting (inferred from gaps)"
        )

        return prompt

    def _format_signals_by_category(self, signals: list[dict]) -> str:
        """Group and format signals by category for the LLM prompt."""
        categories: dict[str, list[dict]] = {}
        for signal in signals:
            category = signal.get("category", "other")
            if category not in categories:
                categories[category] = []
            categories[category].append(signal)

        lines: list[str] = []
        for category, category_signals in sorted(categories.items()):
            lines.append(f"\n### {category.replace('_', ' ').title()}")
            for s in category_signals:
                signal_type = s.get("type", "unknown")
                value = s.get("value")
                created_at = s.get("created_at", "")
                value_str = f" (value: {value})" if value else ""
                lines.append(f"- {signal_type}{value_str} — {created_at}")

        return "\n".join(lines) if lines else "No activity signals recorded."

    def _format_score_explanation(self, explanation: dict) -> str:
        """Format score explanation dict into readable text."""
        lines: list[str] = []

        positive = explanation.get("positive", [])
        negative = explanation.get("negative", [])

        if positive:
            lines.append("### Positive Contributors")
            for item in positive:
                signal_type = item.get("signal_type", "unknown")
                contribution = item.get("contribution", 0)
                category = item.get("category", "")
                lines.append(f"- {signal_type} ({category}): +{contribution} points")

        if negative:
            lines.append("\n### Negative Factors")
            for item in negative:
                signal_type = item.get("signal_type", "unknown")
                contribution = item.get("contribution", 0)
                category = item.get("category", "")
                lines.append(f"- {signal_type} ({category}): {contribution} points")

        return "\n".join(lines) if lines else "No score breakdown available."

    def _call_llm(self, user_prompt: str) -> str | None:
        """Call Claude Sonnet via LiteLLM with 15s timeout.

        Returns:
            Response text or None on failure.
        """
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = litellm.completion(
                model=LLM_MODEL,
                messages=messages,
                temperature=0.7,
                max_tokens=2048,
                timeout=LLM_TIMEOUT,
            )
            content = response.choices[0].message.content
            logger.info(
                "LLM sales summary generated | model=%s | tokens_in=%d | tokens_out=%d",
                LLM_MODEL,
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
            )
            return content

        except litellm.exceptions.Timeout:
            logger.error("LLM timeout (%ds) generating sales summary", LLM_TIMEOUT)
            return None
        except Exception as e:
            logger.error("LLM call failed for sales summary: %s", str(e))
            return None

    def _parse_sections(self, response_text: str, signals: list[dict]) -> dict:
        """Parse LLM response into 5 named sections.

        Looks for section headers like "CLIENT IDENTITY", "ACTIVITY SUMMARY", etc.
        Falls back to numbered sections (1., 2., etc.) if headers not found.
        """
        sections: dict[str, str] = {}

        # Define header patterns to match
        header_patterns = [
            (r"(?:1\.?\s*)?CLIENT\s*IDENTITY", "client_identity"),
            (r"(?:2\.?\s*)?ACTIVITY\s*SUMMARY", "activity_summary"),
            (r"(?:3\.?\s*)?VALUE\s*DISCOVERED", "value_discovered"),
            (r"(?:4\.?\s*)?PROBLEMS?\s*BEING\s*SOLVED", "problems_being_solved"),
            (r"(?:5\.?\s*)?LIKELY\s*OBJECTIONS?", "likely_objections"),
        ]

        # Find all section positions in the response
        section_positions: list[tuple[int, int, str]] = []

        for pattern, key in header_patterns:
            match = re.search(pattern, response_text, re.IGNORECASE)
            if match:
                section_positions.append((match.start(), match.end(), key))

        # Sort by position
        section_positions.sort(key=lambda x: x[0])

        # Extract content between headers
        for i, (start, end, key) in enumerate(section_positions):
            # Content starts after the header (skip delimiters)
            content_start = end
            while content_start < len(response_text) and response_text[content_start] in " \u2014:\n":
                content_start += 1

            # Content ends at next section or end of text
            if i + 1 < len(section_positions):
                content_end = section_positions[i + 1][0]
            else:
                content_end = len(response_text)

            sections[key] = response_text[content_start:content_end].strip()

        # Handle missing onboarding data
        has_onboarding_signals = any(
            s.get("type", "").startswith("onboarding_") for s in signals
        )
        if not has_onboarding_signals:
            problems = sections.get("problems_being_solved", "")
            note = "Onboarding data not collected — problems inferred from usage signals only"
            if note not in problems:
                sections["problems_being_solved"] = f"{problems}\n\nNote: {note}".strip()

        return sections

    def _store_summary(
        self,
        db: Session,
        client_id: UUID,
        score_id: UUID,
        summary: dict,
        existing_cached: TrialSalesSummary | None,
    ) -> None:
        """Store or update the TrialSalesSummary record.

        If existing cache exists with different score_id:
            - Increment version
            - Update score_id, content, cached_until

        If no cache exists:
            - Create new record with version 1
        """
        now = datetime.now(TZ)
        cached_until = now + timedelta(hours=CACHE_DURATION_HOURS)
        content = json.dumps(summary)

        if existing_cached:
            # Cache invalidation: score_id differs — regenerate
            existing_cached.score_id = score_id
            existing_cached.content = content
            existing_cached.cached_until = cached_until
            existing_cached.sales_summary_version += 1
            existing_cached.generated_at = now
            logger.info(
                "Updated sales summary for client %s (version %d)",
                client_id, existing_cached.sales_summary_version,
            )
        else:
            # Create new record
            new_summary = TrialSalesSummary(
                client_id=client_id,
                score_id=score_id,
                sales_summary_version=1,
                content=content,
                cached_until=cached_until,
            )
            db.add(new_summary)
            logger.info("Created new sales summary for client %s", client_id)

        db.commit()

    def _deserialize_content(self, content: str) -> dict:
        """Deserialize stored JSON content back to dict."""
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            logger.error("Failed to deserialize cached sales summary content")
            return {"status": "error", "message": "Cached content corrupted"}
