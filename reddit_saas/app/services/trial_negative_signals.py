"""Trial Negative Signal Detector — identifies churn risk patterns for trial clients.

Detects behavioral signals that indicate a trial client is unlikely to convert:
- Inactivity (72h without signals)
- Multiple short sessions (<30s)
- Viewed pricing without upgrading
- Abandoned onboarding
- Removed keywords
- Exported data without returning
- Opened report without scrolling

Time-based detections run via Celery every 4h.
Event-driven detections are recorded by hooks in real-time.
"""

import logging
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo

from app.models.client import Client
from app.models.trial_signal import TrialSignal
from app.services.trial_signals import SignalCategory, SignalCollector

logger = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Jerusalem")

INACTIVITY_THRESHOLD_HOURS = 72
SHORT_SESSION_THRESHOLD_SEC = 30
SHORT_SESSION_COUNT_THRESHOLD = 3
SHORT_SESSION_WINDOW_HOURS = 24
PRICING_RETURN_WINDOW_HOURS = 24
ONBOARDING_COMPLETE_WINDOW_HOURS = 48
EXPORT_RETURN_WINDOW_HOURS = 48
REPORT_SCROLL_PCT_THRESHOLD = 10


class NegativeSignalDetector:
    """Detects negative behavioral patterns that indicate churn risk.

    Each detect_* method:
    - Queries trial_signals for a specific pattern
    - If pattern detected, records a negative signal via SignalCollector
    - Returns bool (True if negative detected)

    Time-based detections (run via Celery every 4h):
    - detect_inactivity_72h
    - detect_pricing_without_upgrade
    - detect_onboarding_abandoned
    - detect_export_without_return

    Event-driven detections (called by route hooks):
    - detect_multiple_short_sessions
    - detect_removed_keywords
    - detect_report_no_scroll
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._collector = SignalCollector(db)

    def detect_inactivity_72h(self, client_id: UUID) -> bool:
        """Detect if client has been inactive for more than 72 hours.

        Checks the most recent signal for this client. If last signal is older
        than 72 hours, or if no signals exist and client was created > 72h ago,
        records a "no_activity_72h" negative signal.

        Returns:
            True if negative signal was recorded, False otherwise.
        """
        now = datetime.now(TZ)
        cutoff = now - timedelta(hours=INACTIVITY_THRESHOLD_HOURS)

        # Get the most recent signal for this client (exclude negative signals to avoid loops)
        last_signal = (
            self.db.query(TrialSignal)
            .filter(
                TrialSignal.client_id == client_id,
                TrialSignal.signal_category != SignalCategory.negative,
            )
            .order_by(TrialSignal.created_at.desc())
            .first()
        )

        if last_signal is not None:
            if last_signal.created_at < cutoff:
                # Check if we already recorded this signal recently (avoid duplicates)
                if self._already_recorded_recently(client_id, "no_activity_72h"):
                    return False
                self._collector.record_negative_signal(
                    client_id=client_id,
                    signal_type="no_activity_72h",
                    metadata={
                        "last_signal_at": last_signal.created_at.isoformat(),
                        "hours_inactive": int((now - last_signal.created_at).total_seconds() / 3600),
                    },
                )
                return True
            return False

        # No non-negative signals at all - check client creation date
        client = self.db.query(Client).filter(Client.id == client_id).first()
        if client and client.created_at < cutoff:
            if self._already_recorded_recently(client_id, "no_activity_72h"):
                return False
            self._collector.record_negative_signal(
                client_id=client_id,
                signal_type="no_activity_72h",
                metadata={
                    "reason": "no_signals_ever",
                    "client_created_at": client.created_at.isoformat(),
                },
            )
            return True

        return False

    def detect_multiple_short_sessions(self, client_id: UUID) -> bool:
        """Detect 3+ sessions under 30 seconds within a 24-hour window.

        Counts "login" signals where signal_value contains duration_sec < 30.
        If count >= 3, records "multiple_short_sessions" negative signal.

        Returns:
            True if negative signal was recorded, False otherwise.
        """
        now = datetime.now(TZ)
        window_start = now - timedelta(hours=SHORT_SESSION_WINDOW_HOURS)

        # Count login signals with short duration in the last 24h
        # Using JSONB extraction for duration_sec field
        short_session_count: int = (
            self.db.query(func.count(TrialSignal.id))
            .filter(
                TrialSignal.client_id == client_id,
                TrialSignal.signal_type == "login",
                TrialSignal.created_at >= window_start,
                TrialSignal.signal_value["duration_sec"].as_integer() < SHORT_SESSION_THRESHOLD_SEC,
            )
            .scalar()
        ) or 0

        if short_session_count >= SHORT_SESSION_COUNT_THRESHOLD:
            if self._already_recorded_recently(client_id, "multiple_short_sessions"):
                return False
            self._collector.record_negative_signal(
                client_id=client_id,
                signal_type="multiple_short_sessions",
                metadata={
                    "short_sessions_24h": short_session_count,
                    "threshold_sec": SHORT_SESSION_THRESHOLD_SEC,
                },
            )
            return True

        return False

    def detect_pricing_without_upgrade(self, client_id: UUID) -> bool:
        """Detect if client viewed pricing page but didn't return within 24h.

        Checks for "pricing_page_viewed" signal and whether any subsequent
        signal exists within 24 hours after it. If pricing was viewed but
        no follow-up activity occurred, records "viewed_pricing_without_upgrade".

        Returns:
            True if negative signal was recorded, False otherwise.
        """
        # Find most recent pricing_page_viewed signal
        pricing_signal = (
            self.db.query(TrialSignal)
            .filter(
                TrialSignal.client_id == client_id,
                TrialSignal.signal_type == "pricing_page_viewed",
            )
            .order_by(TrialSignal.created_at.desc())
            .first()
        )

        if pricing_signal is None:
            return False

        now = datetime.now(TZ)
        return_window_end = pricing_signal.created_at + timedelta(hours=PRICING_RETURN_WINDOW_HOURS)

        # If the return window hasn't elapsed yet, skip
        if now < return_window_end:
            return False

        # Check if any non-negative signal exists after the pricing view within the window
        return_signal = (
            self.db.query(TrialSignal.id)
            .filter(
                TrialSignal.client_id == client_id,
                TrialSignal.created_at > pricing_signal.created_at,
                TrialSignal.created_at <= return_window_end,
                TrialSignal.signal_type != "pricing_page_viewed",
                TrialSignal.signal_category != SignalCategory.negative,
            )
            .first()
        )

        if return_signal is None:
            # Check if already recorded for this pricing view
            already_recorded = (
                self.db.query(TrialSignal.id)
                .filter(
                    TrialSignal.client_id == client_id,
                    TrialSignal.signal_type == "viewed_pricing_without_upgrade",
                    TrialSignal.created_at > pricing_signal.created_at,
                )
                .first()
            )
            if already_recorded:
                return False

            self._collector.record_negative_signal(
                client_id=client_id,
                signal_type="viewed_pricing_without_upgrade",
                metadata={
                    "pricing_viewed_at": pricing_signal.created_at.isoformat(),
                },
            )
            return True

        return False

    def detect_onboarding_abandoned(self, client_id: UUID) -> bool:
        """Detect if onboarding was started but not completed within 48h.

        Checks for "onboarding_started" signal without a corresponding
        "onboarding_completed" signal within 48 hours.

        Returns:
            True if negative signal was recorded, False otherwise.
        """
        # Find onboarding_started signal
        started_signal = (
            self.db.query(TrialSignal)
            .filter(
                TrialSignal.client_id == client_id,
                TrialSignal.signal_type == "onboarding_started",
            )
            .order_by(TrialSignal.created_at.desc())
            .first()
        )

        if started_signal is None:
            return False

        now = datetime.now(TZ)
        complete_window_end = started_signal.created_at + timedelta(
            hours=ONBOARDING_COMPLETE_WINDOW_HOURS
        )

        # If the window hasn't elapsed yet, skip
        if now < complete_window_end:
            return False

        # Check if onboarding_completed exists after started
        completed_signal = (
            self.db.query(TrialSignal.id)
            .filter(
                TrialSignal.client_id == client_id,
                TrialSignal.signal_type == "onboarding_completed",
                TrialSignal.created_at > started_signal.created_at,
            )
            .first()
        )

        if completed_signal is not None:
            return False

        # Check if already recorded for this started event
        already_recorded = (
            self.db.query(TrialSignal.id)
            .filter(
                TrialSignal.client_id == client_id,
                TrialSignal.signal_type == "onboarding_abandoned",
                TrialSignal.created_at > started_signal.created_at,
            )
            .first()
        )
        if already_recorded:
            return False

        self._collector.record_negative_signal(
            client_id=client_id,
            signal_type="onboarding_abandoned",
            metadata={
                "onboarding_started_at": started_signal.created_at.isoformat(),
                "hours_elapsed": int((now - started_signal.created_at).total_seconds() / 3600),
            },
        )
        return True

    def detect_removed_keywords(self, client_id: UUID) -> bool:
        """Record a negative signal for keyword removal event.

        This is event-driven — called directly by keyword removal hooks.
        Records a "removed_keywords" negative signal.

        Returns:
            True if signal was recorded, False otherwise.
        """
        result = self._collector.record_negative_signal(
            client_id=client_id,
            signal_type="removed_keywords",
            metadata={"source": "event_hook"},
        )
        return result is not None

    def detect_export_without_return(self, client_id: UUID) -> bool:
        """Detect if client exported data without subsequent activity within 48h.

        Checks for "export_data" signal without any follow-up signal within
        48 hours. This pattern suggests the client is extracting data before
        churning.

        Returns:
            True if negative signal was recorded, False otherwise.
        """
        # Find most recent export_data signal
        export_signal = (
            self.db.query(TrialSignal)
            .filter(
                TrialSignal.client_id == client_id,
                TrialSignal.signal_type == "export_data",
            )
            .order_by(TrialSignal.created_at.desc())
            .first()
        )

        if export_signal is None:
            return False

        now = datetime.now(TZ)
        return_window_end = export_signal.created_at + timedelta(hours=EXPORT_RETURN_WINDOW_HOURS)

        # If the window hasn't elapsed yet, skip
        if now < return_window_end:
            return False

        # Check if any non-negative signal exists after the export within the window
        return_signal = (
            self.db.query(TrialSignal.id)
            .filter(
                TrialSignal.client_id == client_id,
                TrialSignal.created_at > export_signal.created_at,
                TrialSignal.created_at <= return_window_end,
                TrialSignal.signal_type != "export_data",
                TrialSignal.signal_category != SignalCategory.negative,
            )
            .first()
        )

        if return_signal is None:
            # Already recorded for this export?
            already_recorded = (
                self.db.query(TrialSignal.id)
                .filter(
                    TrialSignal.client_id == client_id,
                    TrialSignal.signal_type == "export_without_return",
                    TrialSignal.created_at > export_signal.created_at,
                )
                .first()
            )
            if already_recorded:
                return False

            self._collector.record_negative_signal(
                client_id=client_id,
                signal_type="export_without_return",
                metadata={
                    "export_at": export_signal.created_at.isoformat(),
                    "hours_without_return": int(
                        (now - export_signal.created_at).total_seconds() / 3600
                    ),
                },
            )
            return True

        return False

    def detect_report_no_scroll(self, client_id: UUID) -> bool:
        """Detect report opened with scroll_pct < 10%.

        Checks for recent "report_opened" signals that have scroll_pct < 10%
        in their signal_value. This is primarily event-driven but can also be
        called to check historical data.

        Returns:
            True if negative signal was recorded, False otherwise.
        """
        now = datetime.now(TZ)
        # Look at reports opened in the last 24h that have low scroll
        window_start = now - timedelta(hours=24)

        low_scroll_report = (
            self.db.query(TrialSignal)
            .filter(
                TrialSignal.client_id == client_id,
                TrialSignal.signal_type == "report_opened",
                TrialSignal.created_at >= window_start,
                TrialSignal.signal_value["scroll_pct"].as_float() < REPORT_SCROLL_PCT_THRESHOLD,
            )
            .order_by(TrialSignal.created_at.desc())
            .first()
        )

        if low_scroll_report is None:
            return False

        # Check if already recorded for this report view
        already_recorded = (
            self.db.query(TrialSignal.id)
            .filter(
                TrialSignal.client_id == client_id,
                TrialSignal.signal_type == "report_open_no_scroll",
                TrialSignal.created_at > low_scroll_report.created_at,
            )
            .first()
        )
        if already_recorded:
            return False

        self._collector.record_negative_signal(
            client_id=client_id,
            signal_type="report_open_no_scroll",
            metadata={
                "report_opened_at": low_scroll_report.created_at.isoformat(),
                "scroll_pct": low_scroll_report.signal_value.get("scroll_pct", 0),
                "threshold": REPORT_SCROLL_PCT_THRESHOLD,
            },
        )
        return True

    def run_all_time_based_detections(self) -> dict:
        """Run all time-based negative signal detections for active trial clients.

        Queries all active trial clients and runs detectors:
        - detect_inactivity_72h
        - detect_pricing_without_upgrade
        - detect_onboarding_abandoned
        - detect_export_without_return

        Returns:
            Summary dict: {"checked": N, "signals_recorded": M}
        """
        # Get all active trial clients
        trial_clients = (
            self.db.query(Client)
            .filter(
                Client.plan_type == "trial",
                Client.is_active.is_(True),
            )
            .all()
        )

        checked = 0
        signals_recorded = 0

        for client in trial_clients:
            checked += 1
            client_id = client.id

            try:
                if self.detect_inactivity_72h(client_id):
                    signals_recorded += 1
                if self.detect_pricing_without_upgrade(client_id):
                    signals_recorded += 1
                if self.detect_onboarding_abandoned(client_id):
                    signals_recorded += 1
                if self.detect_export_without_return(client_id):
                    signals_recorded += 1
            except Exception:
                logger.exception(
                    "Error running negative signal detections for client %s",
                    client_id,
                )
                continue

        logger.info(
            "Negative signal detection complete: checked=%d, signals_recorded=%d",
            checked,
            signals_recorded,
        )

        return {"checked": checked, "signals_recorded": signals_recorded}

    def _already_recorded_recently(
        self, client_id: UUID, signal_type: str, hours: int = 24
    ) -> bool:
        """Check if a negative signal was already recorded within the last N hours.

        Prevents duplicate negative signals for the same pattern.
        """
        cutoff = datetime.now(TZ) - timedelta(hours=hours)
        exists = (
            self.db.query(TrialSignal.id)
            .filter(
                TrialSignal.client_id == client_id,
                TrialSignal.signal_type == signal_type,
                TrialSignal.signal_category == SignalCategory.negative,
                TrialSignal.created_at >= cutoff,
            )
            .first()
        )
        return exists is not None
