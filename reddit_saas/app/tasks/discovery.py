"""Discovery Engine — Celery tasks for async Reddit research.

The research phase runs as a background task because it makes multiple
Reddit API calls with rate limiting (up to 120 seconds total).
Progress is tracked in session_metadata for HTMX polling.
"""

from app.logging_config import get_logger
import time
import uuid

from sqlalchemy.orm import Session as DBSession

from app.database import SessionLocal
from app.models.discovery_hypothesis import DiscoveryHypothesis
from app.models.discovery_session import DiscoverySession
from app.services.discovery.confidence_scorer import score_hypothesis
from app.services.discovery.reddit_researcher import research_hypothesis
from app.tasks.worker import celery_app

logger = get_logger(__name__)

TOTAL_TIMEOUT = 120  # Max seconds for all hypotheses in one iteration


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def research_hypotheses_task(self, session_id: str, hypothesis_ids: list[str]):
    """Research Reddit for evidence on all hypotheses in the current iteration.

    Updates each hypothesis with reddit_signals and confidence_score.
    Tracks progress in session_metadata.research_progress for HTMX polling.

    Args:
        session_id: UUID of the Discovery session.
        hypothesis_ids: List of hypothesis UUIDs to research.
    """
    start_time = time.time()
    db: DBSession = SessionLocal()

    try:
        session = db.query(DiscoverySession).filter(
            DiscoverySession.id == uuid.UUID(session_id)
        ).first()

        if not session:
            logger.error(f"Discovery session {session_id} not found")
            return

        entities = list(session.entities)

        # Initialize progress tracking
        progress = {hid: "queued" for hid in hypothesis_ids}
        session.session_metadata = {
            **(session.session_metadata or {}),
            "research_progress": progress,
        }
        db.commit()

        # Process each hypothesis
        for hid in hypothesis_ids:
            elapsed = time.time() - start_time
            if elapsed > TOTAL_TIMEOUT:
                # Timeout: mark remaining as failed
                logger.warning(f"Research timeout ({elapsed:.0f}s) for session {session_id}")
                _mark_remaining_failed(db, session, hypothesis_ids, hid, progress)
                break

            # Check if research was stopped by operator
            db.refresh(session)
            meta = session.session_metadata or {}
            if meta.get("research_stopped_by"):
                logger.info(f"Research stopped by operator for session {session_id}")
                break

            hypothesis = db.query(DiscoveryHypothesis).filter(
                DiscoveryHypothesis.id == uuid.UUID(hid)
            ).first()

            if not hypothesis:
                progress[hid] = "complete"
                continue

            # Update progress: researching
            progress[hid] = "researching"
            session.session_metadata = {
                **(session.session_metadata or {}),
                "research_progress": progress,
            }
            db.commit()

            try:
                # Research Reddit
                signals_output = research_hypothesis(hypothesis, entities)

                # Convert to dict for storage and scoring
                signals_dict = signals_output.model_dump()

                # Adapt schema field name to expected signals format
                # RedditSignalOutput uses "avg_engagement", model expects "avg_engagement_overall"
                if "avg_engagement" in signals_dict and "avg_engagement_overall" not in signals_dict:
                    signals_dict["avg_engagement_overall"] = signals_dict.pop("avg_engagement")

                # Store raw signals on hypothesis
                hypothesis.reddit_signals = signals_dict

                # Score the hypothesis (pure Python, returns dict)
                score_result = score_hypothesis(hypothesis, signals_dict)

                # Update hypothesis record from scoring result
                hypothesis.confidence_score = score_result["confidence_score"]
                hypothesis.confidence_delta = score_result["confidence_delta"]

                # Store confidence reasoning in provenance
                provenance = hypothesis.provenance or {}
                provenance["confidence_reasoning"] = score_result["confidence_reasoning"]
                hypothesis.provenance = provenance

                # Handle no-signal assessment
                if score_result["no_signal"]:
                    rs = hypothesis.reddit_signals or {}
                    rs["no_signal"] = score_result["no_signal"]
                    hypothesis.reddit_signals = rs

                progress[hid] = "complete"

            except Exception as e:
                logger.error(f"Research failed for hypothesis {hid}: {e}")
                hypothesis.status = "research_failed"
                progress[hid] = "complete"

            # Update progress in metadata
            session.session_metadata = {
                **(session.session_metadata or {}),
                "research_progress": progress,
            }
            db.commit()

        # Final progress update: all done
        progress = {hid: "complete" for hid in hypothesis_ids}
        session.session_metadata = {
            **(session.session_metadata or {}),
            "research_progress": progress,
            "research_completed_at": time.time(),
        }
        db.commit()

        elapsed = time.time() - start_time
        logger.info(
            f"Research completed for session {session_id}: "
            f"{len(hypothesis_ids)} hypotheses in {elapsed:.1f}s"
        )

    except Exception as e:
        logger.error(f"Research task failed for session {session_id}: {e}")
        db.rollback()
        raise self.retry(exc=e)
    finally:
        db.close()


def _mark_remaining_failed(
    db: DBSession,
    session: DiscoverySession,
    all_ids: list[str],
    current_id: str,
    progress: dict,
):
    """Mark remaining hypotheses as research_failed after timeout."""
    remaining = False
    for hid in all_ids:
        if progress.get(hid) == "queued":
            remaining = True
            hypothesis = db.query(DiscoveryHypothesis).filter(
                DiscoveryHypothesis.id == uuid.UUID(hid)
            ).first()
            if hypothesis:
                hypothesis.status = "research_failed"
            progress[hid] = "complete"

    session.session_metadata = {
        **(session.session_metadata or {}),
        "research_progress": progress,
    }
    db.commit()


@celery_app.task(name="run_continuous_discovery_all")
def run_continuous_discovery_all_task():
    """Weekly task: run continuous discovery for all active clients.

    Checks real outcomes against Discovery hypotheses, updates confidence,
    and flags strategy reviews when environment signals change.

    Schedule: Weekly Sunday 04:00 (low-traffic time).
    """
    from app.services.discovery.continuous import run_continuous_discovery_all_clients

    db = SessionLocal()
    try:
        results = run_continuous_discovery_all_clients(db)
        logger.info("run_continuous_discovery_all: %s", results)
        return results
    except Exception as e:
        logger.error("run_continuous_discovery_all failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        db.close()
