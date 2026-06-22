"""Intelligence Event Logger for trial conversion tracking.

Logs all intelligence-related events (summary generation, outreach, score changes, etc.)
for trial clients to support conversion intelligence analytics.
"""

import logging
from enum import StrEnum
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.trial_intelligence_event import TrialIntelligenceEvent

logger = logging.getLogger(__name__)


class IntelligenceEventType(StrEnum):
    generated_summary = "generated_summary"
    generated_outreach = "generated_outreach"
    changed_score = "changed_score"
    opened_trial = "opened_trial"
    marked_contacted = "marked_contacted"
    scheduled_followup = "scheduled_followup"
    copied_outreach = "copied_outreach"


class IntelligenceEventLogger:
    """Logs intelligence events for trial conversion tracking.

    All methods are designed to never raise — DB errors are caught and logged.
    """

    @staticmethod
    def log_event(
        db: Session,
        client_id: UUID,
        user_id: UUID,
        event_type: IntelligenceEventType,
        metadata: dict | None = None,
    ) -> UUID | None:
        """Create a TrialIntelligenceEvent record.

        Returns the event ID on success, None on failure.
        Never raises — catches DB errors and logs them.
        """
        try:
            event = TrialIntelligenceEvent(
                client_id=client_id,
                user_id=user_id,
                event_type=event_type.value,
                event_metadata=metadata,
            )
            db.add(event)
            db.flush()
            event_id = event.id
            db.commit()
            logger.debug(
                "Logged intelligence event: type=%s client=%s user=%s id=%s",
                event_type.value,
                client_id,
                user_id,
                event_id,
            )
            return event_id
        except Exception:
            logger.exception(
                "Failed to log intelligence event: type=%s client=%s user=%s",
                event_type.value,
                client_id,
                user_id,
            )
            db.rollback()
            return None

    @staticmethod
    def get_events(
        db: Session,
        client_id: UUID,
        limit: int = 20,
    ) -> list[TrialIntelligenceEvent]:
        """Query trial_intelligence_events for a client.

        Returns events ordered by created_at DESC, limited to `limit` records.
        """
        return (
            db.query(TrialIntelligenceEvent)
            .filter(TrialIntelligenceEvent.client_id == client_id)
            .order_by(TrialIntelligenceEvent.created_at.desc())
            .limit(limit)
            .all()
        )

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    @staticmethod
    def log_summary_generated(
        db: Session,
        client_id: UUID,
        user_id: UUID,
        score_id: UUID,
    ) -> UUID | None:
        """Log that an intelligence summary was generated for a score."""
        return IntelligenceEventLogger.log_event(
            db,
            client_id,
            user_id,
            IntelligenceEventType.generated_summary,
            metadata={"score_id": str(score_id)},
        )

    @staticmethod
    def log_outreach_generated(
        db: Session,
        client_id: UUID,
        user_id: UUID,
        outreach_type: str,
    ) -> UUID | None:
        """Log that an outreach draft was generated."""
        return IntelligenceEventLogger.log_event(
            db,
            client_id,
            user_id,
            IntelligenceEventType.generated_outreach,
            metadata={"outreach_type": outreach_type},
        )

    @staticmethod
    def log_score_change(
        db: Session,
        client_id: UUID,
        user_id: UUID,
        old_score: int,
        new_score: int,
    ) -> UUID | None:
        """Log a conversion score change."""
        return IntelligenceEventLogger.log_event(
            db,
            client_id,
            user_id,
            IntelligenceEventType.changed_score,
            metadata={"old_score": old_score, "new_score": new_score},
        )

    @staticmethod
    def log_trial_opened(
        db: Session,
        client_id: UUID,
        user_id: UUID,
    ) -> UUID | None:
        """Log that a trial intelligence panel was opened."""
        return IntelligenceEventLogger.log_event(
            db,
            client_id,
            user_id,
            IntelligenceEventType.opened_trial,
        )

    @staticmethod
    def log_marked_contacted(
        db: Session,
        client_id: UUID,
        user_id: UUID,
    ) -> UUID | None:
        """Log that a trial client was marked as contacted."""
        return IntelligenceEventLogger.log_event(
            db,
            client_id,
            user_id,
            IntelligenceEventType.marked_contacted,
        )

    @staticmethod
    def log_followup_scheduled(
        db: Session,
        client_id: UUID,
        user_id: UUID,
        scheduled_date: str,
    ) -> UUID | None:
        """Log that a follow-up was scheduled."""
        return IntelligenceEventLogger.log_event(
            db,
            client_id,
            user_id,
            IntelligenceEventType.scheduled_followup,
            metadata={"scheduled_date": scheduled_date},
        )

    @staticmethod
    def log_outreach_copied(
        db: Session,
        client_id: UUID,
        user_id: UUID,
        draft_type: str,
    ) -> UUID | None:
        """Log that an outreach draft was copied to clipboard."""
        return IntelligenceEventLogger.log_event(
            db,
            client_id,
            user_id,
            IntelligenceEventType.copied_outreach,
            metadata={"draft_type": draft_type},
        )
