"""Trial Failure Analyzer.

Classifies why a trial expired without conversion and generates
reactivation intelligence using LLM analysis.

Classification priority (first match wins):
1. no_engagement — fewer than 2 distinct days with signals
2. product_confusion — onboarding started but not completed, OR completed but <2 value_realization signals
3. wrong_icp — free email domain OR industry is null
4. no_value_discovered — zero landscape_report AND zero opportunity_report signals
5. no_urgency — signals in first 7 days but zero in last 7 days
6. budget_issue — pricing/upgrade signals exist but no conversion
7. unknown — none matched
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

import litellm
from sqlalchemy import func
from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo

from app.models.client import Client
from app.models.trial_failure import TrialFailure
from app.models.trial_signal import TrialSignal
from app.models.user import User

logger = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Jerusalem")

FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "protonmail.com",
    "icloud.com",
    "mail.com",
    "aol.com",
    "yandex.ru",
    "mail.ru",
}


class FailureCategory(StrEnum):
    no_engagement = "no_engagement"
    product_confusion = "product_confusion"
    wrong_icp = "wrong_icp"
    no_value_discovered = "no_value_discovered"
    no_urgency = "no_urgency"
    budget_issue = "budget_issue"
    unknown = "unknown"


@dataclass
class FailureClassification:
    category: FailureCategory
    confidence: float  # 0.0 - 1.0
    evidence: list[str]  # signal types that led to classification


@dataclass
class ReactivationIntel:
    win_back_window_days: int
    next_best_action: str
    confidence: float  # 0.0 - 1.0
    reasoning: str  # AI explanation


# Default win-back heuristics per failure category
WIN_BACK_DEFAULTS: dict[FailureCategory, int] = {
    FailureCategory.no_engagement: 30,
    FailureCategory.wrong_icp: 0,  # never — confidence 0.0
    FailureCategory.budget_issue: 60,
    FailureCategory.no_urgency: 14,
    FailureCategory.no_value_discovered: 7,
    FailureCategory.product_confusion: 3,
    FailureCategory.unknown: 21,
}


class FailureAnalyzer:
    """Analyzes why a trial client did not convert and generates reactivation intel."""

    def classify_failure(self, db: Session, client_id: UUID) -> FailureClassification:
        """Classify why a trial failed based on signal analysis.

        Applies classification rules in priority order (first match wins).
        """
        signals = (
            db.query(TrialSignal)
            .filter(TrialSignal.client_id == client_id)
            .order_by(TrialSignal.created_at.asc())
            .all()
        )

        client = db.query(Client).filter(Client.id == client_id).first()

        # Rule 1: no_engagement — fewer than 2 distinct days with signals
        distinct_days = self._count_distinct_signal_days(signals)
        if distinct_days < 2:
            signal_types = list({s.signal_type for s in signals}) if signals else []
            confidence = 0.9 if distinct_days == 0 else 0.7
            return FailureClassification(
                category=FailureCategory.no_engagement,
                confidence=confidence,
                evidence=signal_types or ["no_signals"],
            )

        # Rule 2: product_confusion — onboarding started but not completed,
        # OR completed but <2 value_realization signals after
        confusion_result = self._check_product_confusion(signals, client)
        if confusion_result is not None:
            return confusion_result

        # Rule 3: wrong_icp — free email domain OR industry is null
        icp_result = self._check_wrong_icp(db, client_id, client)
        if icp_result is not None:
            return icp_result

        # Rule 4: no_value_discovered — zero landscape_report AND zero opportunity_report
        value_types = {s.signal_type for s in signals}
        if "landscape_report" not in value_types and "opportunity_report" not in value_types:
            evidence = [s.signal_type for s in signals if s.signal_category == "engagement"][:5]
            return FailureClassification(
                category=FailureCategory.no_value_discovered,
                confidence=0.7,
                evidence=evidence or ["no_reports_generated"],
            )

        # Rule 5: no_urgency — signals in first 7 days but zero in last 7 days
        urgency_result = self._check_no_urgency(signals, client)
        if urgency_result is not None:
            return urgency_result

        # Rule 6: budget_issue — pricing/upgrade signals exist but no conversion
        budget_result = self._check_budget_issue(signals)
        if budget_result is not None:
            return budget_result

        # Rule 7: unknown — none matched
        return FailureClassification(
            category=FailureCategory.unknown,
            confidence=0.5,
            evidence=list({s.signal_type for s in signals})[:5],
        )

    def generate_reactivation_intel(
        self,
        db: Session,
        client_id: UUID,
        failure: FailureClassification,
    ) -> ReactivationIntel:
        """Generate reactivation intelligence using LLM analysis.

        Calls Claude Sonnet via LiteLLM with failure classification + signal summary.
        Falls back to heuristic defaults on timeout or error.
        """
        # Start with heuristic defaults
        default_window = WIN_BACK_DEFAULTS.get(failure.category, 21)

        # wrong_icp is not worth reactivating
        if failure.category == FailureCategory.wrong_icp:
            return ReactivationIntel(
                win_back_window_days=0,
                next_best_action="Do not reactivate — wrong ICP profile",
                confidence=0.0,
                reasoning="Client does not match ideal customer profile (free email domain or unknown industry).",
            )

        # Build signal summary for LLM
        signals = (
            db.query(TrialSignal)
            .filter(TrialSignal.client_id == client_id)
            .order_by(TrialSignal.created_at.desc())
            .limit(50)
            .all()
        )

        client = db.query(Client).filter(Client.id == client_id).first()
        client_name = client.client_name if client else "Unknown"
        industry = client.industry if client else "Unknown"

        signal_summary = self._build_signal_summary(signals)

        prompt = (
            f"You are a SaaS trial conversion expert. A trial client did not convert.\n\n"
            f"Client: {client_name}\n"
            f"Industry: {industry}\n"
            f"Failure category: {failure.category.value}\n"
            f"Confidence: {failure.confidence}\n"
            f"Evidence signals: {', '.join(failure.evidence)}\n\n"
            f"Signal summary (last 50 signals):\n{signal_summary}\n\n"
            f"Default win-back window: {default_window} days\n\n"
            f"Based on this analysis, provide:\n"
            f"1. Refined win_back_window_days (integer, when to reach out)\n"
            f"2. next_best_action (one sentence: what specific action to take)\n"
            f"3. confidence (0.0-1.0: how confident you are this will work)\n"
            f"4. reasoning (2-3 sentences explaining your recommendation)\n\n"
            f"Respond in JSON format:\n"
            f'{{"win_back_window_days": <int>, "next_best_action": "<str>", '
            f'"confidence": <float>, "reasoning": "<str>"}}'
        )

        try:
            response = litellm.completion(
                model="claude-sonnet-4-20250514",
                messages=[{"role": "user", "content": prompt}],
                timeout=30,
                max_tokens=500,
                temperature=0.3,
            )

            content = response.choices[0].message.content.strip()
            # Parse JSON from response (handle markdown code blocks)
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            parsed = json.loads(content)

            return ReactivationIntel(
                win_back_window_days=int(parsed.get("win_back_window_days", default_window)),
                next_best_action=str(parsed.get("next_best_action", "Send personalized follow-up email")),
                confidence=max(0.0, min(1.0, float(parsed.get("confidence", 0.5)))),
                reasoning=str(parsed.get("reasoning", "AI analysis completed.")),
            )

        except Exception as e:
            logger.warning("LLM reactivation intel failed (timeout or error): %s", e)
            # Return heuristic defaults
            return ReactivationIntel(
                win_back_window_days=default_window,
                next_best_action=self._default_action_for_category(failure.category),
                confidence=0.5,
                reasoning=f"Heuristic default — LLM analysis failed: {str(e)[:100]}",
            )

    def store_failure(
        self,
        db: Session,
        client_id: UUID,
        classification: FailureClassification,
        intel: ReactivationIntel | None,
        ai_status: str = "completed",
    ) -> TrialFailure:
        """Persist failure classification and reactivation intel to database."""
        reactivation_recommended = (
            intel is not None
            and intel.confidence > 0.0
            and classification.category != FailureCategory.wrong_icp
        )

        record = TrialFailure(
            client_id=client_id,
            failure_category=classification.category.value,
            ai_analysis=json.dumps({
                "evidence": classification.evidence,
                "classification_confidence": classification.confidence,
                "reasoning": intel.reasoning if intel else None,
            }),
            ai_analysis_status=ai_status,
            reactivation_recommended=reactivation_recommended,
            win_back_window_days=intel.win_back_window_days if intel else None,
            next_best_action=intel.next_best_action if intel else None,
            reactivation_confidence=intel.confidence if intel else None,
        )

        db.add(record)
        db.commit()
        db.refresh(record)

        logger.info(
            "Stored trial failure for client %s: category=%s, reactivation=%s",
            client_id,
            classification.category.value,
            reactivation_recommended,
        )

        return record

    # --- Private helpers ---

    def _count_distinct_signal_days(self, signals: list[TrialSignal]) -> int:
        """Count distinct calendar days with at least one signal."""
        days = set()
        for signal in signals:
            if signal.created_at:
                dt = signal.created_at
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=TZ)
                days.add(dt.astimezone(TZ).date())
        return len(days)

    def _check_product_confusion(
        self, signals: list[TrialSignal], client: Client | None
    ) -> FailureClassification | None:
        """Check for product confusion pattern.

        Triggers if:
        - Onboarding started but not completed, OR
        - Onboarding completed but <2 value_realization signals after completion
        """
        # Check if onboarding was started (any onboarding-related signal)
        onboarding_started = any(
            s.signal_type in ("onboarding_started", "onboarding_step_completed")
            for s in signals
        )

        onboarding_completed = (
            client is not None and client.onboarding_completed_at is not None
        )

        if onboarding_started and not onboarding_completed:
            evidence = [s.signal_type for s in signals if "onboarding" in s.signal_type]
            return FailureClassification(
                category=FailureCategory.product_confusion,
                confidence=0.8,
                evidence=evidence or ["onboarding_incomplete"],
            )

        if onboarding_completed:
            # Count value_realization signals after onboarding completion
            value_signals_after = [
                s for s in signals
                if s.signal_category == "value_realization"
                and s.created_at
                and client.onboarding_completed_at
                and s.created_at > client.onboarding_completed_at
            ]
            if len(value_signals_after) < 2:
                evidence = [s.signal_type for s in value_signals_after] or ["low_value_realization"]
                return FailureClassification(
                    category=FailureCategory.product_confusion,
                    confidence=0.65,
                    evidence=evidence,
                )

        return None

    def _check_wrong_icp(
        self, db: Session, client_id: UUID, client: Client | None
    ) -> FailureClassification | None:
        """Check for wrong ICP pattern.

        Triggers if:
        - Client's user email is a free domain (gmail/yahoo/etc), OR
        - Client industry is null
        """
        evidence: list[str] = []

        # Check user email domain
        user = (
            db.query(User)
            .filter(User.client_id == client_id)
            .first()
        )

        if user and user.email:
            domain = user.email.rsplit("@", 1)[-1].lower() if "@" in user.email else ""
            if domain in FREE_EMAIL_DOMAINS:
                evidence.append(f"free_email_domain:{domain}")

        # Check industry
        if client and client.industry is None:
            evidence.append("industry_null")

        if evidence:
            confidence = 0.8 if len(evidence) >= 2 else 0.6
            return FailureClassification(
                category=FailureCategory.wrong_icp,
                confidence=confidence,
                evidence=evidence,
            )

        return None

    def _check_no_urgency(
        self, signals: list[TrialSignal], client: Client | None
    ) -> FailureClassification | None:
        """Check for no urgency pattern.

        Triggers if signals exist in first 7 days but zero in last 7 days of trial.
        """
        if not signals or not client or not client.created_at:
            return None

        trial_start = client.created_at
        if trial_start.tzinfo is None:
            trial_start = trial_start.replace(tzinfo=TZ)

        first_7_days_end = trial_start + timedelta(days=7)
        last_7_days_start = trial_start + timedelta(days=7)  # days 8-14

        first_7_signals = [
            s for s in signals
            if s.created_at and s.created_at <= first_7_days_end
        ]

        last_7_signals = [
            s for s in signals
            if s.created_at and s.created_at > last_7_days_start
        ]

        if first_7_signals and not last_7_signals:
            evidence = list({s.signal_type for s in first_7_signals})[:5]
            return FailureClassification(
                category=FailureCategory.no_urgency,
                confidence=0.7,
                evidence=evidence,
            )

        return None

    def _check_budget_issue(
        self, signals: list[TrialSignal]
    ) -> FailureClassification | None:
        """Check for budget issue pattern.

        Triggers if pricing_page_viewed or upgrade_screen_opened signals exist
        but no conversion signal (upgrade_cta).
        """
        signal_types = {s.signal_type for s in signals}

        pricing_signals = signal_types & {
            "pricing_page_viewed", "pricing_viewed",
            "upgrade_screen_opened", "upgrade_screen",
        }
        conversion_signals = signal_types & {"upgrade_cta", "converted", "subscription_started"}

        if pricing_signals and not conversion_signals:
            evidence = list(pricing_signals)
            # Higher confidence with more pricing views
            pricing_count = sum(
                1 for s in signals
                if s.signal_type in pricing_signals
            )
            confidence = min(0.9, 0.6 + pricing_count * 0.1)
            return FailureClassification(
                category=FailureCategory.budget_issue,
                confidence=confidence,
                evidence=evidence,
            )

        return None

    def _build_signal_summary(self, signals: list[TrialSignal]) -> str:
        """Build a concise signal summary string for LLM context."""
        if not signals:
            return "No signals recorded."

        lines = []
        for s in signals[:30]:  # Limit to 30 for token efficiency
            ts = s.created_at.strftime("%Y-%m-%d %H:%M") if s.created_at else "unknown"
            lines.append(f"  [{ts}] {s.signal_category}/{s.signal_type}")

        return "\n".join(lines)

    def _default_action_for_category(self, category: FailureCategory) -> str:
        """Return a sensible default action when LLM is unavailable."""
        actions = {
            FailureCategory.no_engagement: "Send personalized re-engagement email with value proposition",
            FailureCategory.product_confusion: "Offer guided onboarding walkthrough session",
            FailureCategory.wrong_icp: "Do not reactivate",
            FailureCategory.no_value_discovered: "Send landscape report preview with key findings",
            FailureCategory.no_urgency: "Share competitor activity alert to create urgency",
            FailureCategory.budget_issue: "Offer limited-time discount or extended trial",
            FailureCategory.unknown: "Send follow-up survey to understand needs",
        }
        return actions.get(category, "Send follow-up email")
