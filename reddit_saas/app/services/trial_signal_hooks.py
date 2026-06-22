"""Trial Signal Hooks — fire-and-forget utility for recording signals from routes.

This module provides `record_trial_signal_background()`, a helper that:
1. Calls SignalCollector.record_signal() to persist the signal
2. On success, checks DebounceManager.should_recompute()
3. If True, dispatches recompute_trial_score.delay(str(client_id))
4. All wrapped in try/except — never raises, never blocks the caller

Usage in routes:
    from app.services.trial_signal_hooks import record_trial_signal_background

    # At the end of a route handler (fire-and-forget):
    record_trial_signal_background(
        client_id=client_id,
        signal_type="onboarding_completed",
        signal_category="engagement",
        signal_value={"step": 6},
    )
"""

import logging
from uuid import UUID

logger = logging.getLogger(__name__)


def record_trial_signal_background(
    client_id: UUID,
    signal_type: str,
    signal_category: str,
    signal_value: dict | None = None,
) -> None:
    """Record a trial signal and dispatch debounced recompute if needed.

    Fire-and-forget: this function NEVER raises exceptions.
    It opens its own DB session and closes it when done.
    Safe to call from any route handler without affecting the response.

    Args:
        client_id: Trial client UUID
        signal_type: e.g. "page_view", "onboarding_completed", "pricing_viewed"
        signal_category: One of engagement/intent/value_realization/conversion/negative
        signal_value: Optional JSON payload with context
    """
    try:
        _do_record_and_dispatch(client_id, signal_type, signal_category, signal_value)
    except Exception as exc:
        # Fire-and-forget: log and swallow
        logger.debug(
            "Trial signal hook failed (non-blocking): client=%s signal=%s error=%s",
            client_id,
            signal_type,
            exc,
        )


def _do_record_and_dispatch(
    client_id: UUID,
    signal_type: str,
    signal_category: str,
    signal_value: dict | None,
) -> None:
    """Internal: record signal + check debounce + dispatch recompute.

    Uses its own DB session to avoid interfering with route transactions.
    """
    from app.database import SessionLocal
    from app.services.trial_signals import SignalCollector

    db = SessionLocal()
    try:
        collector = SignalCollector(db)

        # Step 1: Record signal (returns None if skipped/failed)
        signal_id = collector.record_signal(
            client_id=client_id,
            signal_type=signal_type,
            signal_category=signal_category,
            signal_value=signal_value,
        )

        if signal_id is None:
            # Signal was skipped (not a trial client, daily cap, dedup, or DB error)
            return

        # Step 2: Check debounce — should we trigger a score recompute?
        _check_debounce_and_dispatch(client_id)

    finally:
        db.close()


def _check_debounce_and_dispatch(client_id: UUID) -> None:
    """Check debounce manager and dispatch recompute task if needed.

    Fire-and-forget: if Redis or Celery is unavailable, silently skip.
    """
    try:
        import redis as redis_lib

        from app.config import get_settings
        from app.services.trial_debounce import DebounceManager

        settings = get_settings()
        redis_client = redis_lib.from_url(settings.redis_url, decode_responses=True)
        debounce = DebounceManager(redis_client)

        if debounce.should_recompute(client_id):
            # Dispatch Celery task for score recomputation
            from app.tasks.trial_scoring import recompute_trial_score

            recompute_trial_score.delay(str(client_id))
            logger.debug(
                "Trial recompute dispatched for client %s", client_id
            )

    except Exception as exc:
        # Redis or Celery unavailable — silently skip
        logger.debug(
            "Debounce/dispatch failed (non-blocking): client=%s error=%s",
            client_id,
            exc,
        )
