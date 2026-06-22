"""BYOA (Bring Your Own Avatar) Celery tasks — async Reddit profile fetch + AI analysis.

Tasks:
- fetch_reddit_profile_for_draft: PRAW fetch -> reddit_snapshot
- analyze_reddit_profile_for_draft: AI classification -> ai_analysis
- check_stale_avatar_drafts: periodic cleanup of stuck drafts
- check_avatar_invariant: daily invariant enforcement
- check_onboarding_stall: hourly stall detection for new avatars
"""

import time
import uuid
from datetime import datetime, timezone, timedelta

from app.logging_config import get_logger
from app.tasks.worker import celery_app
from app.database import SessionLocal

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Task 1: Fetch Reddit Profile
# ---------------------------------------------------------------------------


@celery_app.task(name="fetch_reddit_profile_for_draft", bind=True, max_retries=3)
def fetch_reddit_profile_for_draft(self, draft_id: str):
    """Fetch Reddit profile via PRAW and store as reddit_snapshot in AvatarDraft.

    On success: stores snapshot, chains to analyze_reddit_profile_for_draft.
    On permanent error (account not found/suspended): marks draft as fetch_failed.
    On transient error: retries with exponential backoff.
    """
    db = SessionLocal()
    start = time.time()
    try:
        from app.models.avatar_draft import AvatarDraft, DRAFT_STATUS_PENDING_FETCH, DRAFT_STATUS_ANALYZING, DRAFT_STATUS_FETCH_FAILED
        from app.services.external_scheduler import get_external_scheduler
        from app.services.avatar_onboard_analysis import fetch_reddit_profile

        draft = db.query(AvatarDraft).filter(AvatarDraft.id == draft_id).first()
        if not draft:
            logger.error("BYOA_FETCH | draft_id=%s | error=draft_not_found", draft_id)
            return {"status": "error", "reason": "draft_not_found"}

        if draft.status != DRAFT_STATUS_PENDING_FETCH:
            logger.warning(
                "BYOA_FETCH | draft_id=%s | status=%s | error=unexpected_status",
                draft_id, draft.status,
            )
            return {"status": "skipped", "reason": f"unexpected_status:{draft.status}"}

        # Distributed lock: prevent duplicate execution of same draft
        from app.services.distributed_lock import DistributedLock
        _lock = DistributedLock(key=f"byoa:fetch:{draft_id}", ttl=300)
        if not _lock.acquire():
            logger.info("BYOA_FETCH | draft_id=%s | action=already_locked, skipping", draft_id)
            return {"status": "skipped", "reason": "already_running"}

        # Update timestamps
        draft.fetch_started_at = datetime.now(timezone.utc)
        db.commit()

        # Acquire scheduler slot
        scheduler = get_external_scheduler()
        if not scheduler.wait_for_slot("reddit", priority="user_facing_trial", max_wait=30):
            logger.warning("BYOA_FETCH | draft_id=%s | action=scheduler_timeout, retrying", draft_id)
            raise self.retry(countdown=30)

        try:
            # Call existing PRAW fetch function
            profile_data = fetch_reddit_profile(draft.reddit_username)
        finally:
            scheduler.release("reddit")

        duration_ms = int((time.time() - start) * 1000)

        # Check for permanent errors
        if profile_data.get("error"):
            error_msg = profile_data["error"]
            # Permanent: account not found or suspended
            if any(kw in error_msg.lower() for kw in ["not found", "suspended", "404", "banned"]):
                draft.status = DRAFT_STATUS_FETCH_FAILED
                draft.error_message = f"Reddit account issue: {error_msg}"
                draft.fetch_completed_at = datetime.now(timezone.utc)
                db.commit()

                # Notify user
                _notify_draft_failure(db, draft, "fetch_failed")

                scheduler.log_request("reddit", duration_ms, False, priority="user_facing_trial", details=error_msg)
                logger.info("BYOA_FETCH | draft_id=%s | status=fetch_failed | reason=%s", draft_id, error_msg[:100])
                return {"status": "fetch_failed", "error": error_msg}

            # Transient: retry
            scheduler.log_request("reddit", duration_ms, False, priority="user_facing_trial", details=error_msg)
            logger.warning("BYOA_FETCH | draft_id=%s | transient_error=%s | retrying", draft_id, error_msg[:100])
            raise self.retry(countdown=60 * (2 ** self.request.retries))

        # Success: store snapshot
        draft.reddit_snapshot = profile_data
        draft.status = DRAFT_STATUS_ANALYZING
        draft.fetch_completed_at = datetime.now(timezone.utc)
        db.commit()

        scheduler.log_request("reddit", duration_ms, True, priority="user_facing_trial")
        logger.info(
            "BYOA_FETCH | draft_id=%s | status=success | username=%s | comments=%d | posts=%d | duration_ms=%d",
            draft_id, draft.reddit_username,
            len(profile_data.get("comments", [])),
            len(profile_data.get("posts", [])),
            duration_ms,
        )

        # Release lock before chaining (analysis has its own lock)
        _lock.release()

        # Chain to AI analysis
        analyze_reddit_profile_for_draft.delay(draft_id)
        return {"status": "success", "next": "analyze"}

    except self.MaxRetriesExceededError:
        # All retries exhausted
        try:
            draft = db.query(AvatarDraft).filter(AvatarDraft.id == draft_id).first()
            if draft and draft.status != DRAFT_STATUS_FETCH_FAILED:
                draft.status = DRAFT_STATUS_FETCH_FAILED
                draft.error_message = "Reddit profile fetch failed after 3 attempts. Please try again."
                draft.fetch_completed_at = datetime.now(timezone.utc)
                db.commit()
                _notify_draft_failure(db, draft, "fetch_failed")
        except Exception as inner:
            logger.error("BYOA_FETCH | draft_id=%s | failed to mark as failed: %s", draft_id, inner)
            db.rollback()
        return {"status": "fetch_failed", "reason": "max_retries_exceeded"}

    except Exception as e:
        if isinstance(e, self.MaxRetriesExceededError):
            raise
        logger.error("BYOA_FETCH | draft_id=%s | unexpected_error=%s", draft_id, str(e)[:200], exc_info=True)
        # Retry on unexpected errors
        try:
            raise self.retry(countdown=60 * (2 ** self.request.retries), exc=e)
        except self.MaxRetriesExceededError:
            try:
                draft = db.query(AvatarDraft).filter(AvatarDraft.id == draft_id).first()
                if draft:
                    draft.status = DRAFT_STATUS_FETCH_FAILED
                    draft.error_message = f"Unexpected error: {str(e)[:200]}"
                    draft.fetch_completed_at = datetime.now(timezone.utc)
                    db.commit()
                    _notify_draft_failure(db, draft, "fetch_failed")
            except Exception:
                db.rollback()
            return {"status": "fetch_failed", "reason": str(e)[:200]}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Task 2: AI Profile Analysis
# ---------------------------------------------------------------------------


@celery_app.task(name="analyze_reddit_profile_for_draft", bind=True, max_retries=3)
def analyze_reddit_profile_for_draft(self, draft_id: str):
    """Run AI classification on stored Reddit snapshot.

    On success: stores ai_analysis, transitions draft to ready_for_review.
    On failure after retries: marks draft as analysis_failed.
    """
    db = SessionLocal()
    start = time.time()
    try:
        from app.models.avatar_draft import AvatarDraft, DRAFT_STATUS_ANALYZING, DRAFT_STATUS_READY_FOR_REVIEW, DRAFT_STATUS_ANALYSIS_FAILED
        from app.models.client import Client
        from app.services.external_scheduler import get_external_scheduler
        from app.services.avatar_onboard_analysis import analyze_avatar_with_ai

        draft = db.query(AvatarDraft).filter(AvatarDraft.id == draft_id).first()
        if not draft:
            logger.error("BYOA_ANALYZE | draft_id=%s | error=draft_not_found", draft_id)
            return {"status": "error", "reason": "draft_not_found"}

        if draft.status != DRAFT_STATUS_ANALYZING:
            logger.warning(
                "BYOA_ANALYZE | draft_id=%s | status=%s | error=unexpected_status",
                draft_id, draft.status,
            )
            return {"status": "skipped", "reason": f"unexpected_status:{draft.status}"}

        # Distributed lock: prevent duplicate AI calls for same draft
        from app.services.distributed_lock import DistributedLock
        _lock = DistributedLock(key=f"byoa:analyze:{draft_id}", ttl=300)
        if not _lock.acquire():
            logger.info("BYOA_ANALYZE | draft_id=%s | action=already_locked, skipping", draft_id)
            return {"status": "skipped", "reason": "already_running"}

        if not draft.reddit_snapshot:
            logger.error("BYOA_ANALYZE | draft_id=%s | error=no_reddit_snapshot", draft_id)
            draft.status = DRAFT_STATUS_ANALYSIS_FAILED
            draft.error_message = "No Reddit data available for analysis"
            db.commit()
            return {"status": "error", "reason": "no_snapshot"}

        # Update timestamps
        draft.analysis_started_at = datetime.now(timezone.utc)
        db.commit()

        # Load client for context
        client = db.query(Client).filter(Client.id == draft.client_id).first()

        # Acquire scheduler slot
        scheduler = get_external_scheduler()
        if not scheduler.wait_for_slot("ai_llm", priority="user_facing_trial", max_wait=30):
            logger.warning("BYOA_ANALYZE | draft_id=%s | action=scheduler_timeout, retrying", draft_id)
            raise self.retry(countdown=30)

        try:
            # Call existing AI analysis function
            analysis_result = analyze_avatar_with_ai(
                profile_data=draft.reddit_snapshot,
                client=client,
                db=db,
            )
        finally:
            scheduler.release("ai_llm")

        duration_ms = int((time.time() - start) * 1000)

        # Check for errors
        if analysis_result.get("error"):
            error_msg = analysis_result["error"]
            scheduler.log_request("ai_llm", duration_ms, False, priority="user_facing_trial", details=error_msg)
            logger.warning("BYOA_ANALYZE | draft_id=%s | ai_error=%s | retrying", draft_id, error_msg[:100])
            raise self.retry(countdown=60 * (2 ** self.request.retries))

        # Success: store analysis and transition
        draft.ai_analysis = analysis_result.get("data") or analysis_result
        draft.status = DRAFT_STATUS_READY_FOR_REVIEW
        draft.analysis_completed_at = datetime.now(timezone.utc)
        db.commit()

        _lock.release()
        scheduler.log_request("ai_llm", duration_ms, True, priority="user_facing_trial")
        logger.info(
            "BYOA_ANALYZE | draft_id=%s | status=ready_for_review | username=%s | duration_ms=%d",
            draft_id, draft.reddit_username, duration_ms,
        )
        return {"status": "success", "draft_status": "ready_for_review"}

    except self.MaxRetriesExceededError:
        try:
            draft = db.query(AvatarDraft).filter(AvatarDraft.id == draft_id).first()
            if draft and draft.status != DRAFT_STATUS_ANALYSIS_FAILED:
                draft.status = DRAFT_STATUS_ANALYSIS_FAILED
                draft.error_message = "AI analysis failed after 3 attempts. Please try again."
                draft.analysis_completed_at = datetime.now(timezone.utc)
                db.commit()
                _notify_draft_failure(db, draft, "analysis_failed")
        except Exception as inner:
            logger.error("BYOA_ANALYZE | draft_id=%s | failed to mark as failed: %s", draft_id, inner)
            db.rollback()
        return {"status": "analysis_failed", "reason": "max_retries_exceeded"}

    except Exception as e:
        if isinstance(e, self.MaxRetriesExceededError):
            raise
        logger.error("BYOA_ANALYZE | draft_id=%s | unexpected_error=%s", draft_id, str(e)[:200], exc_info=True)
        try:
            raise self.retry(countdown=60 * (2 ** self.request.retries), exc=e)
        except self.MaxRetriesExceededError:
            try:
                draft = db.query(AvatarDraft).filter(AvatarDraft.id == draft_id).first()
                if draft:
                    draft.status = DRAFT_STATUS_ANALYSIS_FAILED
                    draft.error_message = f"Unexpected error: {str(e)[:200]}"
                    draft.analysis_completed_at = datetime.now(timezone.utc)
                    db.commit()
                    _notify_draft_failure(db, draft, "analysis_failed")
            except Exception:
                db.rollback()
            return {"status": "analysis_failed", "reason": str(e)[:200]}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Task 3: Stale Draft Cleanup (periodic)
# ---------------------------------------------------------------------------


@celery_app.task(name="check_stale_avatar_drafts")
def check_stale_avatar_drafts():
    """Fail drafts stuck in non-terminal state for more than 60 minutes.

    Runs every 10 minutes via Celery Beat.
    """
    db = SessionLocal()
    try:
        from app.models.avatar_draft import (
            AvatarDraft,
            DRAFT_STATUS_PENDING_FETCH,
            DRAFT_STATUS_ANALYZING,
            DRAFT_STATUS_FETCH_FAILED,
            DRAFT_STATUS_ANALYSIS_FAILED,
        )

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=60)

        # Find stuck drafts
        stuck_drafts = (
            db.query(AvatarDraft)
            .filter(
                AvatarDraft.status.in_([DRAFT_STATUS_PENDING_FETCH, DRAFT_STATUS_ANALYZING]),
                AvatarDraft.updated_at < cutoff,
            )
            .all()
        )

        if not stuck_drafts:
            return {"status": "ok", "stale_count": 0}

        failed_count = 0
        for draft in stuck_drafts:
            try:
                if draft.status == DRAFT_STATUS_PENDING_FETCH:
                    draft.status = DRAFT_STATUS_FETCH_FAILED
                    draft.error_message = "Timed out: Reddit profile fetch did not complete within 60 minutes"
                else:
                    draft.status = DRAFT_STATUS_ANALYSIS_FAILED
                    draft.error_message = "Timed out: AI analysis did not complete within 60 minutes"

                db.commit()  # Commit per-draft to isolate failures
                _notify_draft_failure(db, draft, draft.status)
                failed_count += 1
                logger.warning(
                    "BYOA_STALE | draft_id=%s | username=%s | old_status=%s | new_status=%s",
                    str(draft.id), draft.reddit_username, "stuck", draft.status,
                )
            except Exception as per_draft_err:
                logger.error("BYOA_STALE | draft_id=%s | commit_failed: %s", str(draft.id), per_draft_err)
                db.rollback()
        logger.info("check_stale_avatar_drafts: failed %d stuck drafts", failed_count)
        return {"status": "ok", "stale_count": failed_count}

    except Exception as e:
        logger.error("check_stale_avatar_drafts failed: %s", e, exc_info=True)
        db.rollback()
        return {"status": "error", "reason": str(e)[:200]}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Task 4: Avatar Invariant Check (daily)
# ---------------------------------------------------------------------------


@celery_app.task(name="check_avatar_invariant")
def check_avatar_invariant():
    """Verify all active clients have at least one active avatar.

    Runs daily at 02:30 via Celery Beat.
    Deactivates violating clients and notifies admin.
    """
    db = SessionLocal()
    try:
        from app.models.client import Client
        from app.models.avatar import Avatar
        from app.services.notifications import notify_client

        # Find active clients with onboarding complete
        active_clients = (
            db.query(Client)
            .filter(
                Client.is_active.is_(True),
                Client.onboarding_completed_at.isnot(None),
            )
            .all()
        )

        violations = 0
        for client in active_clients:
            avatar_count = (
                db.query(Avatar)
                .filter(
                    Avatar.client_ids.any(str(client.id)),
                    Avatar.active.is_(True),
                )
                .count()
            )

            if avatar_count == 0:
                client.is_active = False
                violations += 1
                logger.warning(
                    "AVATAR_INVARIANT_VIOLATION | client=%s | name=%s | action=deactivated",
                    str(client.id), client.client_name,
                )

                # Record activity event for admin visibility
                try:
                    from app.services.transparency import record_activity_event
                    record_activity_event(
                        db=db,
                        client_id=str(client.id),
                        event_type="invariant_violation",
                        description=f"Client '{client.client_name}' deactivated: no active avatars",
                        details={"reason": "zero_active_avatars", "action": "client_deactivated"},
                    )
                except Exception:
                    pass

        if violations > 0:
            db.commit()

        logger.info(
            "check_avatar_invariant: checked %d clients, %d violations found",
            len(active_clients), violations,
        )
        return {"status": "ok", "checked": len(active_clients), "violations": violations}

    except Exception as e:
        logger.error("check_avatar_invariant failed: %s", e, exc_info=True)
        db.rollback()
        return {"status": "error", "reason": str(e)[:200]}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Task 5: Onboarding Stall Detection (hourly)
# ---------------------------------------------------------------------------


@celery_app.task(name="check_onboarding_stall")
def check_onboarding_stall():
    """Detect avatars confirmed more than 24 hours ago with no comment drafts generated.

    Creates admin alert (ActivityEvent) for manual investigation.
    Runs hourly via Celery Beat.
    """
    db = SessionLocal()
    try:
        from app.models.avatar_draft import AvatarDraft, DRAFT_STATUS_CONFIRMED
        from app.models.comment_draft import CommentDraft
        from app.models.avatar import Avatar

        # Find drafts confirmed 24-48 hours ago
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(hours=48)
        window_end = now - timedelta(hours=24)

        confirmed_drafts = (
            db.query(AvatarDraft)
            .filter(
                AvatarDraft.status == DRAFT_STATUS_CONFIRMED,
                AvatarDraft.confirmed_at.between(window_start, window_end),
                AvatarDraft.avatar_id.isnot(None),
            )
            .all()
        )

        stalls = 0
        for draft in confirmed_drafts:
            # Check if any comment drafts exist for this client
            draft_count = (
                db.query(CommentDraft)
                .filter(CommentDraft.client_id == str(draft.client_id))
                .count()
            )

            if draft_count == 0:
                stalls += 1
                logger.warning(
                    "ONBOARDING_STALL | client_id=%s | avatar_id=%s | username=%s | hours_since_confirm=%d",
                    str(draft.client_id), str(draft.avatar_id), draft.reddit_username,
                    int((now - draft.confirmed_at).total_seconds() / 3600),
                )

                # Create admin alert
                try:
                    from app.services.transparency import record_activity_event
                    record_activity_event(
                        db=db,
                        client_id=str(draft.client_id),
                        event_type="onboarding_stall_detected",
                        description=f"Avatar u/{draft.reddit_username} confirmed {int((now - draft.confirmed_at).total_seconds() / 3600)}h ago but no drafts generated",
                        details={
                            "avatar_id": str(draft.avatar_id),
                            "avatar_username": draft.reddit_username,
                            "confirmed_at": draft.confirmed_at.isoformat(),
                            "hours_elapsed": int((now - draft.confirmed_at).total_seconds() / 3600),
                        },
                    )
                except Exception as e:
                    logger.warning("Failed to record onboarding_stall event: %s", e)

        if stalls > 0:
            db.commit()

        logger.info("check_onboarding_stall: checked %d recent confirmations, %d stalls detected", len(confirmed_drafts), stalls)
        return {"status": "ok", "checked": len(confirmed_drafts), "stalls": stalls}

    except Exception as e:
        logger.error("check_onboarding_stall failed: %s", e, exc_info=True)
        db.rollback()
        return {"status": "error", "reason": str(e)[:200]}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Helper: notify user of draft failure
# ---------------------------------------------------------------------------


def _notify_draft_failure(db, draft, failure_type: str) -> None:
    """Create in-app notification for the user who initiated the draft."""
    try:
        from app.services.notifications import notify_client

        if failure_type == "fetch_failed":
            title = "Avatar analysis failed"
            body = f"We could not fetch the Reddit profile for u/{draft.reddit_username}. {draft.error_message or 'Please try again.'}"
        else:
            title = "Avatar analysis failed"
            body = f"AI analysis for u/{draft.reddit_username} could not be completed. {draft.error_message or 'Please try again.'}"

        notify_client(
            db=db,
            client_id=draft.client_id,
            notification_type="warning",
            title=title,
            body=body,
            link=f"/onboard/step/5",
        )
    except Exception as e:
        logger.warning("Failed to notify user about draft failure: %s", e)
