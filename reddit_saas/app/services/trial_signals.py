"""Trial Signal Collector — records engagement signals for trial clients.

Lightweight service: no scoring logic, just storage with deduplication
and daily cap enforcement.
"""

import logging
import time
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo

from app.models.client import Client
from app.models.trial_signal import TrialSignal

logger = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Jerusalem")

DAILY_SIGNAL_CAP = 500
DEDUP_WINDOW_SECONDS = 60


class SignalCategory(StrEnum):
    """Signal categories for trial engagement tracking."""

    engagement = "engagement"
    intent = "intent"
    value_realization = "value_realization"
    conversion = "conversion"
    negative = "negative"


class SignalCollector:
    """Records trial signals to the database. No scoring logic."""

    def __init__(self, db: Session):
        self.db = db

    def record_signal(
        self,
        client_id: UUID,
        signal_type: str,
        signal_category: SignalCategory | str,
        signal_value: dict | None = None,
    ) -> UUID | None:
        """Record a trial engagement signal.

        Args:
            client_id: Trial client UUID
            signal_type: e.g. "page_view", "report_generated", "pricing_viewed"
            signal_category: One of engagement/intent/value_realization/conversion/negative
            signal_value: Optional JSON payload

        Returns:
            UUID of created TrialSignal record, or None if skipped/failed

        Behavior:
            1. Short-circuits if client is not an active trial client
            2. Enforces daily cap (500 signals per client per Asia/Jerusalem day)
            3. Deduplicates same (client_id, signal_type) within 60s window
            4. Stores with Asia/Jerusalem timezone context
            5. On DB error: retries once after 2s, then discards (never blocks caller)
        """
        # Only record signals for active trial clients
        if not self.is_trial_client(client_id):
            return None

        # Daily cap check (Asia/Jerusalem day boundary)
        now_jerusalem = datetime.now(TZ)
        day_start = now_jerusalem.replace(hour=0, minute=0, second=0, microsecond=0)

        today_count: int = (
            self.db.query(func.count(TrialSignal.id))
            .filter(
                TrialSignal.client_id == client_id,
                TrialSignal.created_at >= day_start,
            )
            .scalar()
        ) or 0

        if today_count >= DAILY_SIGNAL_CAP:
            logger.info(
                "Daily signal cap reached for client %s (%d/%d)",
                client_id,
                today_count,
                DAILY_SIGNAL_CAP,
            )
            return None

        # Deduplication: skip if same (client_id, signal_type) within last 60s
        dedup_cutoff = now_jerusalem - timedelta(seconds=DEDUP_WINDOW_SECONDS)
        duplicate_exists: bool = (
            self.db.query(TrialSignal.id)
            .filter(
                TrialSignal.client_id == client_id,
                TrialSignal.signal_type == signal_type,
                TrialSignal.created_at >= dedup_cutoff,
            )
            .first()
            is not None
        )

        if duplicate_exists:
            logger.debug(
                "Dedup: skipping signal %s for client %s (within %ds window)",
                signal_type,
                client_id,
                DEDUP_WINDOW_SECONDS,
            )
            return None

        # Build the signal record with timezone-aware created_at
        signal = TrialSignal(
            client_id=client_id,
            signal_type=signal_type,
            signal_category=str(signal_category),
            signal_value=signal_value,
            created_at=now_jerusalem,
        )

        # Store with retry-once-on-db-error
        return self._persist_signal(signal)

    def record_negative_signal(
        self,
        client_id: UUID,
        signal_type: str,
        metadata: dict | None = None,
    ) -> UUID | None:
        """Record a negative signal (detected by async Celery tasks).

        Convenience wrapper around record_signal with category=negative.

        Negative signal types:
            - no_activity_72h
            - bounced_email
            - multiple_short_sessions
            - viewed_pricing_without_upgrade
            - onboarding_abandoned
            - removed_keywords
            - export_without_return
            - report_open_no_scroll

        Args:
            client_id: Trial client UUID
            signal_type: One of the negative signal types above
            metadata: Optional JSON payload with detection context

        Returns:
            UUID of created TrialSignal record, or None if skipped/failed
        """
        return self.record_signal(
            client_id=client_id,
            signal_type=signal_type,
            signal_category=SignalCategory.negative,
            signal_value=metadata,
        )

    def get_signals(
        self,
        client_id: UUID,
        since: datetime | None = None,
    ) -> list[TrialSignal]:
        """Get all signals for a client, optionally since a timestamp.

        Args:
            client_id: Trial client UUID
            since: Optional cutoff — only return signals after this time

        Returns:
            List of TrialSignal records ordered by created_at ascending
        """
        query = self.db.query(TrialSignal).filter(TrialSignal.client_id == client_id)
        if since is not None:
            query = query.filter(TrialSignal.created_at >= since)
        return query.order_by(TrialSignal.created_at.asc()).all()

    def is_trial_client(self, client_id: UUID) -> bool:
        """Check if a client is an active trial client.

        Returns False for non-trial clients, allowing callers to
        short-circuit signal recording early.

        Args:
            client_id: Client UUID to check

        Returns:
            True if client exists with plan_type="trial" and is_active=True
        """
        client = (
            self.db.query(Client)
            .filter(
                Client.id == client_id,
                Client.plan_type == "trial",
                Client.is_active.is_(True),
            )
            .first()
        )
        return client is not None

    def _persist_signal(self, signal: TrialSignal) -> UUID | None:
        """Persist signal with retry-once-on-db-error.

        On IntegrityError or OperationalError: log warning, wait 2s, retry once.
        On second failure: log error, return None (never block the caller).
        """
        for attempt in range(2):
            try:
                self.db.add(signal)
                self.db.flush()
                signal_id = signal.id
                self.db.commit()
                return signal_id
            except (IntegrityError, OperationalError) as exc:
                self.db.rollback()
                if attempt == 0:
                    logger.warning(
                        "DB error recording signal (attempt 1), retrying in 2s: %s",
                        exc,
                    )
                    time.sleep(2)
                else:
                    logger.error(
                        "DB error recording signal (attempt 2), discarding: %s",
                        exc,
                    )
                    return None

        return None
