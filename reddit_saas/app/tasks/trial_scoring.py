"""Celery tasks for Trial Conversion Intelligence scoring.

Tasks:
- recompute_trial_score(client_id): Debounced scoring recomputation triggered by signals.
  Acquires distributed lock (5s TTL), loads signals, computes scores, evaluates lifecycle,
  stores TrialScore, detects score changes, emits events.

- classify_expired_trials: Daily failure analysis for expired trial clients.
  Queries clients where plan_type="trial" AND created_at < now()-14days AND no existing
  TrialFailure record. For each: classify -> generate reactivation intel -> store.

Schedule:
- recompute_trial_score: On-demand (dispatched by signal hooks via DebounceManager)
- classify_expired_trials: Daily at 02:30 (after feedback loop)
"""

from celery import shared_task
from datetime import datetime, timedelta
from uuid import UUID

from app.database import SessionLocal
from app.logging_config import get_logger

logger = get_logger(__name__)

# Score change threshold for emitting events (Requirement 2.9)
SCORE_CHANGE_THRESHOLD = 10


@shared_task(name="recompute_trial_score", bind=True, max_retries=1)
def recompute_trial_score(self, client_id: str):
    """Recompute trial scores for a client after signal collection.

    This task is dispatched by signal hooks via DebounceManager (60s window).
    It acquires a distributed lock (5s TTL) to prevent concurrent recomputes.

    Steps:
    1. Acquire Redis distributed lock per client_id (5s TTL)
    2. Load all signals for the client
    3. Compute scores via ScoringEngine
    4. Evaluate lifecycle via LifecycleFSM
    5. Store result as new TrialScore record
    6. Compare with previous score -- if change > 10 points, emit events
    7. Clear debounce key

    Fallback: if Redis unavailable for lock, proceed with recompute anyway.
    """
    import redis as redis_lib
    from zoneinfo import ZoneInfo

    from app.config import get_settings
    from app.models.activity_event import ActivityEvent
    from app.models.client import Client
    from app.models.trial_intelligence_event import TrialIntelligenceEvent
    from app.models.trial_score import TrialScore
    from app.models.trial_signal import TrialSignal
    from app.services.trial_debounce import DebounceManager
    from app.services.trial_lifecycle import LifecycleFSM
    from app.services.trial_scoring import ScoringEngine

    TZ = ZoneInfo("Asia/Jerusalem")
    client_uuid = UUID(client_id)
    settings = get_settings()

    # Get Redis client
    try:
        redis_client = redis_lib.from_url(settings.redis_url, decode_responses=True)
        debounce = DebounceManager(redis_client)
    except (redis_lib.ConnectionError, redis_lib.TimeoutError) as e:
        logger.warning("Redis unavailable, proceeding without lock/debounce: %s", e)
        redis_client = None
        debounce = None

    # Step 1: Acquire distributed lock (5s TTL) to prevent concurrent recomputes
    lock_acquired = True
    if debounce:
        lock_acquired = debounce.acquire_recompute_lock(client_uuid)
        if not lock_acquired:
            logger.info(
                "recompute_trial_score: lock held for client %s, skipping",
                client_id,
            )
            return {"status": "skipped", "reason": "lock_held", "client_id": client_id}

    db = SessionLocal()
    try:
        # Verify client is still a trial client
        client = (
            db.query(Client)
            .filter(Client.id == client_uuid, Client.plan_type == "trial")
            .first()
        )
        if not client:
            logger.info(
                "recompute_trial_score: client %s not a trial client, skipping",
                client_id,
            )
            return {"status": "skipped", "reason": "not_trial", "client_id": client_id}

        # Step 2: Load all signals for the client
        signals = (
            db.query(TrialSignal)
            .filter(TrialSignal.client_id == client_uuid)
            .order_by(TrialSignal.created_at.asc())
            .all()
        )

        if not signals:
            logger.info(
                "recompute_trial_score: no signals for client %s, skipping",
                client_id,
            )
            return {"status": "skipped", "reason": "no_signals", "client_id": client_id}

        # Step 3: Get previous score for change detection
        previous_score = (
            db.query(TrialScore)
            .filter(TrialScore.client_id == client_uuid)
            .order_by(TrialScore.scored_at.desc())
            .first()
        )
        previous_conversion_score = (
            previous_score.conversion_score if previous_score else None
        )
        previous_lifecycle_state = (
            previous_score.lifecycle_state if previous_score else "trial_started"
        )

        # Step 4: Compute scores via ScoringEngine
        scoring_engine = ScoringEngine()

        # Get configurable weights
        weights = scoring_engine.get_scoring_weights(db)

        # Compute conversion score
        conversion_score = scoring_engine.compute_conversion_score(signals, weights)

        # Compute opportunity value
        opportunity_value_cents = scoring_engine.compute_opportunity_value(client)

        # Compute days remaining
        now = datetime.now(tz=TZ)
        created = client.created_at
        if created and created.tzinfo is None:
            created = created.replace(tzinfo=TZ)
        days_elapsed = (now - created).days if created else 0
        days_remaining = max(0, 14 - days_elapsed)

        # Compute priority score
        priority_score = scoring_engine.compute_priority_score(
            conversion_score, opportunity_value_cents, days_remaining
        )

        # Step 5: Evaluate lifecycle via LifecycleFSM
        lifecycle_fsm = LifecycleFSM(db)
        lifecycle_state = lifecycle_fsm.evaluate_state(
            client_uuid, signals, previous_lifecycle_state
        )

        # Build explanation and snapshot
        score_explanation = scoring_engine.build_score_explanation(signals)
        signal_snapshot = scoring_engine.build_signal_snapshot(signals)

        # Determine recommended action
        last_signal_at = signals[-1].created_at if signals else None
        recommended_action = scoring_engine.determine_recommended_action(
            conversion_score, days_remaining, lifecycle_state, last_signal_at
        )

        # Step 6: Store result as new TrialScore record
        new_score = TrialScore(
            client_id=client_uuid,
            conversion_score=conversion_score,
            priority_score=priority_score,
            opportunity_value_cents=opportunity_value_cents,
            recommended_action=recommended_action,
            score_explanation=score_explanation,
            signal_snapshot=signal_snapshot,
            lifecycle_state=lifecycle_state,
        )
        db.add(new_score)
        db.flush()

        # Step 7: Score change detection (>10 points -> emit events)
        if previous_conversion_score is not None:
            score_change = abs(conversion_score - previous_conversion_score)
            if score_change > SCORE_CHANGE_THRESHOLD:
                # Emit ActivityEvent (visible in activity feed)
                activity_event = ActivityEvent(
                    client_id=client_uuid,
                    event_type="trial_score_changed",
                    message=(
                        f"Trial conversion score changed: "
                        f"{previous_conversion_score} -> {conversion_score} "
                        f"(delta {conversion_score - previous_conversion_score:+d})"
                    ),
                    event_metadata={
                        "old_score": previous_conversion_score,
                        "new_score": conversion_score,
                        "change": conversion_score - previous_conversion_score,
                        "lifecycle_state": lifecycle_state,
                    },
                )
                db.add(activity_event)

                # Emit IntelligenceEvent (audit trail for trial intelligence)
                # Use a system user_id placeholder (UUID zero) for automated events
                system_user_id = UUID("00000000-0000-0000-0000-000000000000")
                intel_event = TrialIntelligenceEvent(
                    client_id=client_uuid,
                    user_id=system_user_id,
                    event_type="changed_score",
                    event_metadata={
                        "old_score": previous_conversion_score,
                        "new_score": conversion_score,
                        "change": conversion_score - previous_conversion_score,
                        "score_id": str(new_score.id),
                    },
                )
                db.add(intel_event)

                logger.info(
                    "Trial score change detected for client %s: %d -> %d (delta %+d)",
                    client_id,
                    previous_conversion_score,
                    conversion_score,
                    conversion_score - previous_conversion_score,
                )

        db.commit()

        logger.info(
            "recompute_trial_score complete for client %s: "
            "conversion=%d, priority=%d, lifecycle=%s",
            client_id,
            conversion_score,
            priority_score,
            lifecycle_state,
        )

        return {
            "status": "ok",
            "client_id": client_id,
            "conversion_score": conversion_score,
            "priority_score": priority_score,
            "lifecycle_state": lifecycle_state,
        }

    except Exception as e:
        db.rollback()
        logger.error(
            "recompute_trial_score failed for client %s: %s",
            client_id,
            e,
            exc_info=True,
        )
        return {"status": "error", "client_id": client_id, "error": str(e)}

    finally:
        db.close()
        # Step 8: Clear debounce key + release lock
        if debounce:
            debounce.clear(client_uuid)
            debounce.release_recompute_lock(client_uuid)


@shared_task(name="classify_expired_trials")
def classify_expired_trials():
    """Classify all expired trial clients that have not been analyzed yet.

    Finds clients where:
    - plan_type = "trial"
    - created_at < now() - 14 days (trial expired)
    - No existing TrialFailure record

    For each: classify failure -> generate reactivation intel -> store result.
    """
    from zoneinfo import ZoneInfo

    from sqlalchemy import and_, exists

    from app.models.client import Client
    from app.models.trial_failure import TrialFailure
    from app.services.trial_failure import FailureAnalyzer

    TZ = ZoneInfo("Asia/Jerusalem")

    db = SessionLocal()
    try:
        now = datetime.now(tz=TZ)
        cutoff = now - timedelta(days=14)

        # Find expired trial clients without a TrialFailure record
        expired_trials = (
            db.query(Client)
            .filter(
                and_(
                    Client.plan_type == "trial",
                    Client.created_at < cutoff,
                    ~exists().where(TrialFailure.client_id == Client.id),
                )
            )
            .all()
        )

        if not expired_trials:
            logger.info("classify_expired_trials: no unclassified expired trials found")
            return {"status": "ok", "processed": 0}

        logger.info(
            "classify_expired_trials: found %d expired trials to classify",
            len(expired_trials),
        )

        analyzer = FailureAnalyzer()
        results = {"processed": 0, "succeeded": 0, "failed": 0}

        for client in expired_trials:
            results["processed"] += 1
            try:
                # Step 1: Classify failure
                classification = analyzer.classify_failure(db, client.id)
                logger.info(
                    "Client %s classified as %s (confidence=%.2f)",
                    client.id,
                    classification.category.value,
                    classification.confidence,
                )

                # Step 2: Generate reactivation intel (with LLM, 30s timeout)
                try:
                    intel = analyzer.generate_reactivation_intel(db, client.id, classification)
                    ai_status = "completed"
                except Exception as llm_err:
                    logger.warning(
                        "LLM analysis failed for client %s: %s", client.id, llm_err
                    )
                    intel = None
                    ai_status = "failed"

                # Step 3: Store result
                analyzer.store_failure(
                    db,
                    client.id,
                    classification,
                    intel,
                    ai_status=ai_status,
                )
                results["succeeded"] += 1

            except Exception as e:
                logger.error(
                    "classify_expired_trials failed for client %s: %s",
                    client.id,
                    e,
                    exc_info=True,
                )
                results["failed"] += 1
                # Continue with next client
                db.rollback()

        logger.info("classify_expired_trials complete: %s", results)
        return {"status": "ok", **results}

    except Exception as e:
        logger.error("classify_expired_trials failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        db.close()
