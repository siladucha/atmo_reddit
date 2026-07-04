"""Outreach Generator — produces personalized draft messages for trial conversion.

Generates 4 outreach drafts (email, LinkedIn, follow-up, discovery call notes)
using Claude Sonnet via LiteLLM, calibrated to the client's conversion score.

# ANTI-AUTOMATION: Drafts are text-only. No email/LinkedIn API integration. Never.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo

from app.models.client import Client
from app.models.trial_score import TrialScore
from app.models.trial_signal import TrialSignal
from app.services.ai import call_llm, log_ai_usage
from app.services.trial_events import IntelligenceEventLogger

logger = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Jerusalem")

# --- Character limits ---
CHAR_LIMIT_EMAIL = 2000
CHAR_LIMIT_LINKEDIN = 300
CHAR_LIMIT_FOLLOWUP = 1000
CHAR_LIMIT_CALL_NOTES = 1500

# --- LLM configuration ---
LLM_MODEL = "anthropic/claude-sonnet-4-20250514"
LLM_TIMEOUT = 20  # seconds

# --- Minimum signals threshold ---
MIN_SIGNALS_FOR_PERSONALIZATION = 3


@dataclass
class OutreachDraft:
    draft_type: str       # email, linkedin, followup, call_notes
    subject: str | None   # email subject (None for non-email)
    body: str
    tone: str             # urgency, curiosity, soft_reengagement


@dataclass
class OutreachDrafts:
    email: OutreachDraft
    linkedin: OutreachDraft
    followup: OutreachDraft
    call_notes: OutreachDraft
    score_id: UUID


class OutreachGenerator:
    """Generates personalized outreach drafts for trial conversion.

    # ANTI-AUTOMATION: Drafts are text-only. No email/LinkedIn API integration. Never.
    """

    def generate_outreach(
        self,
        db: Session,
        client_id: UUID,
        score_id: UUID,
    ) -> OutreachDrafts:
        """Generate 4 outreach drafts personalized to the trial client's activity.

        Args:
            db: SQLAlchemy session
            client_id: Trial client UUID
            score_id: TrialScore UUID for context

        Returns:
            OutreachDrafts with email, linkedin, followup, call_notes

        Raises:
            ValueError: If score_id not found
            Exception: If LLM call fails after fallback chain
        """
        # Load TrialScore
        score = db.query(TrialScore).filter(TrialScore.id == score_id).first()
        if not score:
            raise ValueError(f"TrialScore not found: {score_id}")

        # Load Client for personalization
        client = db.query(Client).filter(Client.id == client_id).first()
        if not client:
            raise ValueError(f"Client not found: {client_id}")

        # Determine tone based on conversion score
        tone = self._select_tone(score.conversion_score)

        # Load signals for personalization
        signals = self._load_recent_signals(db, client_id)

        # Check if we have enough data for personalization
        if len(signals) < MIN_SIGNALS_FOR_PERSONALIZATION:
            logger.info(
                "Insufficient signals (%d < %d) for client %s, using generic drafts",
                len(signals),
                MIN_SIGNALS_FOR_PERSONALIZATION,
                client_id,
            )
            return self._build_generic_drafts(client, score, tone)

        # Build prompt and call LLM
        signals_summary = self._summarize_signals(signals)
        days_remaining = self._calculate_days_remaining(client)

        system_prompt = self._build_system_prompt(tone)
        user_prompt = self._build_user_prompt(
            client_name=client.client_name,
            industry=client.industry or "Unknown",
            signals_summary=signals_summary,
            conversion_score=score.conversion_score,
            days_remaining=days_remaining,
        )

        # Call Claude Sonnet via centralized LLM wrapper with cost logging
        response_text = self._call_llm(db, client_id, system_prompt, user_prompt)

        # Parse LLM response into drafts
        drafts = self._parse_response(response_text, tone, score_id)

        return drafts

    def _select_tone(self, conversion_score: int) -> str:
        """Select outreach tone based on conversion score.

        - score > 70: "urgency" — value confirmation, deadline, clear next step
        - score 40-70: "curiosity" — additional value, questions, explore
        - score < 40: "soft_reengagement" — gentle check-in, offer help
        """
        if conversion_score > 70:
            return "urgency"
        elif conversion_score >= 40:
            return "curiosity"
        else:
            return "soft_reengagement"

    def _load_recent_signals(self, db: Session, client_id: UUID) -> list[TrialSignal]:
        """Load recent signals for the client (last 14 days, max 50)."""
        cutoff = datetime.now(TZ) - timedelta(days=14)
        return (
            db.query(TrialSignal)
            .filter(
                TrialSignal.client_id == client_id,
                TrialSignal.created_at >= cutoff,
            )
            .order_by(TrialSignal.created_at.desc())
            .limit(50)
            .all()
        )

    def _summarize_signals(self, signals: list[TrialSignal]) -> str:
        """Create a concise summary of trial activity from signals."""
        signal_counts: dict[str, int] = {}
        categories: set[str] = set()

        for sig in signals:
            signal_counts[sig.signal_type] = signal_counts.get(sig.signal_type, 0) + 1
            categories.add(sig.signal_category)

        # Build readable summary
        parts: list[str] = []
        for signal_type, count in sorted(signal_counts.items(), key=lambda x: -x[1])[:10]:
            readable = signal_type.replace("_", " ")
            if count > 1:
                parts.append(f"{readable} ({count}x)")
            else:
                parts.append(readable)

        summary = ", ".join(parts)
        category_str = ", ".join(sorted(categories))
        return f"Activities: {summary}. Categories engaged: {category_str}."

    def _calculate_days_remaining(self, client: Client) -> int:
        """Calculate days remaining in 14-day trial."""
        if not client.created_at:
            return 7  # default assumption
        now = datetime.now(TZ)
        trial_end = client.created_at + timedelta(days=14)
        if trial_end.tzinfo is None:
            trial_end = trial_end.replace(tzinfo=TZ)
        remaining = (trial_end - now).days
        return max(0, remaining)

    def _build_system_prompt(self, tone: str) -> str:
        """Build the system prompt for the LLM."""
        tone_instructions = {
            "urgency": (
                "Tone: urgency. Emphasize confirmed value, time-sensitive deadline, "
                "and a clear next step. Create FOMO without being pushy."
            ),
            "curiosity": (
                "Tone: curiosity. Highlight additional value they haven't explored yet. "
                "Ask thoughtful questions. Invite exploration of untapped features."
            ),
            "soft_reengagement": (
                "Tone: soft_reengagement. Gentle check-in approach. Offer help without pressure. "
                "Focus on understanding their needs rather than selling."
            ),
        }

        return (
            "You are a B2B sales communication specialist. "
            "Generate personalized outreach drafts for a trial user who has not yet converted. "
            f"{tone_instructions[tone]} "
            "Be specific — reference their actual trial activity. "
            "Output EXACTLY in this format with clear section headers:\n\n"
            "EMAIL_SUBJECT: <subject line>\n"
            "EMAIL_BODY:\n<body text>\n\n"
            "LINKEDIN:\n<message text>\n\n"
            "FOLLOWUP:\n<follow-up message>\n\n"
            "CALL_NOTES:\n<talking points and questions>"
        )

    def _build_user_prompt(
        self,
        client_name: str,
        industry: str,
        signals_summary: str,
        conversion_score: int,
        days_remaining: int,
    ) -> str:
        """Build the user prompt with client context."""
        return (
            f"Company: {client_name} ({industry})\n"
            f"Trial activity: {signals_summary}\n"
            f"Conversion score: {conversion_score}/100\n"
            f"Days remaining: {days_remaining}\n\n"
            "Generate 4 drafts:\n"
            f"1. EMAIL (subject + body, max {CHAR_LIMIT_EMAIL} chars body)\n"
            f"2. LINKEDIN CONNECTION MESSAGE (max {CHAR_LIMIT_LINKEDIN} chars)\n"
            f"3. FOLLOW-UP (if no response to initial, max {CHAR_LIMIT_FOLLOWUP} chars)\n"
            f"4. DISCOVERY CALL NOTES (talking points + questions, max {CHAR_LIMIT_CALL_NOTES} chars)"
        )

    def _call_llm(self, db: Session, client_id: UUID, system_prompt: str, user_prompt: str) -> str:
        """Call Claude Sonnet via centralized call_llm with cost logging.

        Raises:
            Exception: On LLM errors (after fallback chain exhausted)
        """
        try:
            result = call_llm(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=LLM_MODEL,
                max_tokens=4000,
                timeout=LLM_TIMEOUT,
            )

            # Log AI usage for cost tracking
            log_ai_usage(
                db=db,
                client_id=str(client_id),
                operation="trial_outreach",
                result=result,
                triggered_by="manual",
            )

            return result["content"]
        except Exception:
            logger.exception("LLM call failed for outreach generation")
            raise

    def _parse_response(self, response_text: str, tone: str, score_id: UUID) -> OutreachDrafts:
        """Parse LLM response into OutreachDrafts, enforcing character limits."""
        # Extract sections from response
        email_subject = self._extract_section(response_text, "EMAIL_SUBJECT:", "EMAIL_BODY:")
        email_body = self._extract_section(response_text, "EMAIL_BODY:", "LINKEDIN:")
        linkedin = self._extract_section(response_text, "LINKEDIN:", "FOLLOWUP:")
        followup = self._extract_section(response_text, "FOLLOWUP:", "CALL_NOTES:")
        call_notes = self._extract_after(response_text, "CALL_NOTES:")

        # Enforce character limits with truncation
        email_body = self._truncate(email_body, CHAR_LIMIT_EMAIL)
        linkedin = self._truncate(linkedin, CHAR_LIMIT_LINKEDIN)
        followup = self._truncate(followup, CHAR_LIMIT_FOLLOWUP)
        call_notes = self._truncate(call_notes, CHAR_LIMIT_CALL_NOTES)

        return OutreachDrafts(
            email=OutreachDraft(
                draft_type="email",
                subject=email_subject.strip() if email_subject else None,
                body=email_body.strip(),
                tone=tone,
            ),
            linkedin=OutreachDraft(
                draft_type="linkedin",
                subject=None,
                body=linkedin.strip(),
                tone=tone,
            ),
            followup=OutreachDraft(
                draft_type="followup",
                subject=None,
                body=followup.strip(),
                tone=tone,
            ),
            call_notes=OutreachDraft(
                draft_type="call_notes",
                subject=None,
                body=call_notes.strip(),
                tone=tone,
            ),
            score_id=score_id,
        )

    def _extract_section(self, text: str, start_marker: str, end_marker: str) -> str:
        """Extract text between two markers."""
        start_idx = text.find(start_marker)
        end_idx = text.find(end_marker)

        if start_idx == -1:
            return ""

        content_start = start_idx + len(start_marker)
        if end_idx == -1:
            return text[content_start:].strip()

        return text[content_start:end_idx].strip()

    def _extract_after(self, text: str, marker: str) -> str:
        """Extract all text after a marker."""
        idx = text.find(marker)
        if idx == -1:
            return ""
        return text[idx + len(marker):].strip()

    def _truncate(self, text: str, max_chars: int) -> str:
        """Truncate text to max_chars, appending '...' if exceeds limit."""
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3] + "..."

    def _build_generic_drafts(
        self, client: Client, score: TrialScore, tone: str
    ) -> OutreachDrafts:
        """Build generic drafts when insufficient data (<3 signals).

        Uses only company name + industry for personalization.
        """
        company = client.client_name
        industry = client.industry or "your industry"

        if tone == "urgency":
            email_body = (
                f"Hi there,\n\n"
                f"I noticed {company} started a trial with us. Companies in {industry} "
                f"typically see results within the first week of active use.\n\n"
                f"Your trial period is running — I'd love to help you get the most value "
                f"before it ends. Would a quick 15-minute walkthrough help?\n\n"
                f"Best regards"
            )
            linkedin_msg = (
                f"Hi! I saw {company} is exploring our platform. "
                f"Happy to share how other {industry} teams are getting value. Quick chat?"
            )
            followup_msg = (
                f"Hi again,\n\n"
                f"Just following up on my earlier note. I know things get busy, "
                f"but wanted to make sure you don't miss out on the trial period.\n\n"
                f"Would it help if I shared a quick {industry}-specific use case?"
            )
            call_notes_text = (
                f"Talking points:\n"
                f"- Confirm {company}'s goals for the trial\n"
                f"- Ask about current {industry} challenges\n"
                f"- Show relevant success metrics\n"
                f"- Discuss timeline and next steps\n\n"
                f"Questions to ask:\n"
                f"- What prompted the trial signup?\n"
                f"- Who else on the team should be involved?\n"
                f"- What does success look like for {company}?"
            )
        elif tone == "curiosity":
            email_body = (
                f"Hi there,\n\n"
                f"I noticed {company} signed up for a trial. I'm curious — "
                f"what sparked your interest in our platform?\n\n"
                f"We work with several {industry} companies and I'd love to understand "
                f"what you're hoping to achieve. There might be features you haven't "
                f"discovered yet that could be a perfect fit.\n\n"
                f"Open to a quick chat?"
            )
            linkedin_msg = (
                f"Hi! Noticed {company} is trying our platform. "
                f"Curious what caught your eye — happy to point you to hidden gems."
            )
            followup_msg = (
                f"Hi,\n\n"
                f"Circling back — I've been thinking about how {industry} teams "
                f"use our platform and had some ideas for {company}.\n\n"
                f"No pressure, but I'd love to hear what you're working on."
            )
            call_notes_text = (
                f"Talking points:\n"
                f"- Explore what {company} is trying to solve\n"
                f"- Ask open-ended questions about their workflow\n"
                f"- Introduce features they may not have found\n"
                f"- Listen more than pitch\n\n"
                f"Questions to ask:\n"
                f"- What does your current process look like?\n"
                f"- What would make this a no-brainer for {company}?\n"
                f"- Any features you wish existed?"
            )
        else:  # soft_reengagement
            email_body = (
                f"Hi there,\n\n"
                f"Just checking in — I noticed {company} has a trial with us "
                f"and wanted to see if there's anything I can help with.\n\n"
                f"No pressure at all. Sometimes the timing isn't right, and that's "
                f"perfectly fine. But if you have questions or need a hand getting "
                f"started, I'm here.\n\n"
                f"Best regards"
            )
            linkedin_msg = (
                f"Hi! Just checking in from our team. "
                f"If there's anything I can help {company} with, happy to chat."
            )
            followup_msg = (
                f"Hi,\n\n"
                f"Hope all is well at {company}. No agenda here — just wanted to "
                f"let you know we're available if you'd like any guidance.\n\n"
                f"Sometimes a quick walkthrough makes all the difference."
            )
            call_notes_text = (
                f"Talking points:\n"
                f"- Be warm and low-pressure\n"
                f"- Ask if timing/priorities changed\n"
                f"- Offer specific help for {industry} use case\n"
                f"- Leave door open without pushing\n\n"
                f"Questions to ask:\n"
                f"- Is now a good time, or should we reconnect later?\n"
                f"- What would be most helpful for {company} right now?\n"
                f"- Is there a specific challenge I can address?"
            )

        return OutreachDrafts(
            email=OutreachDraft(
                draft_type="email",
                subject=f"Quick question about {company}'s trial",
                body=self._truncate(email_body, CHAR_LIMIT_EMAIL),
                tone=tone,
            ),
            linkedin=OutreachDraft(
                draft_type="linkedin",
                subject=None,
                body=self._truncate(linkedin_msg, CHAR_LIMIT_LINKEDIN),
                tone=tone,
            ),
            followup=OutreachDraft(
                draft_type="followup",
                subject=None,
                body=self._truncate(followup_msg, CHAR_LIMIT_FOLLOWUP),
                tone=tone,
            ),
            call_notes=OutreachDraft(
                draft_type="call_notes",
                subject=None,
                body=self._truncate(call_notes_text, CHAR_LIMIT_CALL_NOTES),
                tone=tone,
            ),
            score_id=score.id,
        )


def log_copy_event(db: Session, client_id: UUID, user_id: UUID, draft_type: str) -> None:
    """Log that an outreach draft was copied to clipboard.

    Uses IntelligenceEventLogger.log_outreach_copied() for event tracking.

    Args:
        db: SQLAlchemy session
        client_id: Trial client UUID
        user_id: User who copied the draft
        draft_type: One of email, linkedin, followup, call_notes
    """
    IntelligenceEventLogger.log_outreach_copied(
        db=db,
        client_id=client_id,
        user_id=user_id,
        draft_type=draft_type,
    )
