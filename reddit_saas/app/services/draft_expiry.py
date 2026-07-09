"""DraftExpiryService — automatically expires stale CommentDraft records.

Approved drafts older than 48h and pending drafts older than 72h are expired.
Cascades to EPGSlot (→expired) and ExecutionTask (→cancelled).
Emits activity events per client for transparency.

Protects drafts whose EPGSlot is scheduled within the next 2 hours
(execution window protection).
"""

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.comment_draft import CommentDraft
from app.models.epg_slot import EPGSlot
from app.models.execution_task import ExecutionTask
from app.services.settings import get_setting_int
from app.services.transparency import record_activity_event

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------


@dataclass
class DraftExpiry:
    """Record of a single expired draft."""

    draft_id: uuid.UUID
    avatar_id: uuid.UUID
    client_id: uuid.UUID
    original_status: str  # 'approved' | 'pending'
    age_hours: int
    slot_expired: bool = False
    tasks_cancelled: int = 0


@dataclass
class BatchResult:
    """Result of processing a single batch of up to 50 drafts."""

    expired: list[DraftExpiry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class DraftExpiryResult:
    """Summary result of an entire expiry run."""

    total_expired: int = 0
    approved_expired: int = 0
    pending_expired: int = 0
    tasks_cancelled: int = 0
    per_client: dict[uuid.UUID, list[DraftExpiry]] = field(default_factory=dict)
    batch_errors: list[str] = field(default_factory=list)
    duration_ms: int = 0


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class DraftExpiryService:
    """Identifies and expires stale CommentDraft records with full cascade."""

    def run(self, db: Session) -> DraftExpiryResult:
        """Main entry point. Returns summary of actions taken.

        Steps:
        1. Record start time
        2. Read threshold settings
        3. Query stale approved and pending drafts
        4. Combine candidates, chunk into batches of 50
        5. Process each batch
        6. Emit activity events per client
        7. Log summary
        8. Return DraftExpiryResult
        """
        start = time.time()

        # Read threshold settings
        approved_hours = get_setting_int(db, "draft_expiry_approved_hours", default=48)
        pending_hours = get_setting_int(db, "draft_expiry_pending_hours", default=72)

        # Query stale drafts
        approved_candidates = self._query_stale_approved(db, approved_hours)
        pending_candidates = self._query_stale_pending(db, pending_hours)

        # Combine all candidates
        all_candidates = approved_candidates + pending_candidates

        result = DraftExpiryResult()

        if not all_candidates:
            result.duration_ms = int((time.time() - start) * 1000)
            logger.info(
                "DRAFT_EXPIRY | 0 stale drafts found, nothing to expire | duration=%dms",
                result.duration_ms,
            )
            return result

        # Process in batches of 50
        batch_error_count = 0
        now = datetime.now(timezone.utc)

        for i in range(0, len(all_candidates), 50):
            batch = all_candidates[i : i + 50]
            batch_result = self._process_batch(db, batch, now)

            # Accumulate results
            for expiry in batch_result.expired:
                # Track per-client
                if expiry.client_id:
                    result.per_client.setdefault(expiry.client_id, []).append(expiry)

            result.batch_errors.extend(batch_result.errors)

            if batch_result.errors:
                batch_error_count += len(batch_result.errors)
                if batch_error_count > 3:
                    logger.critical(
                        "DRAFT_EXPIRY | >3 batch failures in single run, systemic issue detected"
                    )

        # Compute totals from per_client
        all_expiries: list[DraftExpiry] = []
        for client_expiries in result.per_client.values():
            all_expiries.extend(client_expiries)

        result.total_expired = len(all_expiries)
        result.approved_expired = sum(
            1 for e in all_expiries if e.original_status == "approved"
        )
        result.pending_expired = sum(
            1 for e in all_expiries if e.original_status == "pending"
        )
        result.tasks_cancelled = sum(e.tasks_cancelled for e in all_expiries)

        # Emit activity events per client
        self._emit_activity_events(db, result)

        # Compute duration
        result.duration_ms = int((time.time() - start) * 1000)

        # Log summary (Req 9.1: always log INFO with full summary)
        logger.info(
            "DRAFT_EXPIRY | completed: total=%d approved=%d pending=%d "
            "tasks_cancelled=%d clients=%d duration=%dms errors=%d",
            result.total_expired,
            result.approved_expired,
            result.pending_expired,
            result.tasks_cancelled,
            len(result.per_client),
            result.duration_ms,
            len(result.batch_errors),
        )

        # Req 9.2: additional WARNING if high volume
        if result.total_expired > 50:
            logger.warning(
                "DRAFT_EXPIRY | HIGH VOLUME: %d drafts expired exceeds threshold of 50",
                result.total_expired,
            )

        return result

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def _query_stale_approved(
        self, db: Session, threshold_hours: int
    ) -> list[CommentDraft]:
        """Query approved drafts older than threshold, excluding execution-window-protected.

        LEFT JOINs EPGSlot to exclude drafts whose slot is scheduled within the
        next 2 hours (execution window protection).  Skips orphaned drafts
        (client_id IS NULL) with a WARNING log.
        """
        from sqlalchemy import or_, and_, not_

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=threshold_hours)
        protection_window = now + timedelta(hours=2)

        # Protection logic: a draft is protected ONLY if it has an EPGSlot
        # with scheduled_at in the near future [now, now+2h].
        # Old slots (scheduled_at in the past) and far-future slots do NOT protect.
        # No slot or no scheduled_at → not protected.
        results: list[CommentDraft] = (
            db.query(CommentDraft)
            .outerjoin(EPGSlot, EPGSlot.draft_id == CommentDraft.id)
            .filter(
                CommentDraft.status == "approved",
                CommentDraft.updated_at < cutoff,
                # Exclude only drafts whose slot is scheduled within [now, now+2h]
                or_(
                    EPGSlot.id.is_(None),
                    EPGSlot.scheduled_at.is_(None),
                    not_(and_(
                        EPGSlot.scheduled_at >= now,
                        EPGSlot.scheduled_at <= protection_window,
                    )),
                ),
            )
            .order_by(CommentDraft.updated_at.asc())
            .limit(500)
            .all()
        )

        # Filter out orphaned drafts (client_id IS NULL) and log warning
        valid_drafts: list[CommentDraft] = []
        for draft in results:
            if draft.client_id is None:
                logger.warning(
                    "DRAFT_EXPIRY | orphaned draft skipped (client_id=NULL) | "
                    "draft_id=%s avatar_id=%s",
                    draft.id,
                    draft.avatar_id,
                )
                continue
            valid_drafts.append(draft)

        return valid_drafts

    def _query_stale_pending(
        self, db: Session, threshold_hours: int
    ) -> list[CommentDraft]:
        """Query pending drafts older than threshold.

        Returns drafts with status='pending' whose created_at is older than
        now() - threshold_hours. Ordered by created_at ASC, limited to 500.
        Skips drafts with client_id IS NULL (logs WARNING for orphaned drafts).
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=threshold_hours)

        results: list[CommentDraft] = (
            db.query(CommentDraft)
            .filter(
                CommentDraft.status == "pending",
                CommentDraft.created_at < cutoff,
            )
            .order_by(CommentDraft.created_at.asc())
            .limit(500)
            .all()
        )

        # Filter out orphaned drafts (client_id IS NULL) with WARNING log
        valid_drafts: list[CommentDraft] = []
        for draft in results:
            if draft.client_id is None:
                logger.warning(
                    "DRAFT_EXPIRY | orphaned pending draft skipped (client_id=NULL) | "
                    "draft_id=%s avatar_id=%s",
                    draft.id,
                    draft.avatar_id,
                )
                continue
            valid_drafts.append(draft)

        return valid_drafts

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    def _process_batch(
        self, db: Session, drafts: list[CommentDraft], now: datetime
    ) -> BatchResult:
        """Process a batch of up to 50 drafts atomically.

        Uses a savepoint (nested transaction) so that failure of this batch
        does not affect previously committed batches or subsequent ones.
        """
        from sqlalchemy.exc import SQLAlchemyError

        result = BatchResult()

        try:
            with db.begin_nested():
                for draft in drafts:
                    expiry = self._expire_draft(db, draft, now)
                    if expiry is not None:
                        result.expired.append(expiry)
        except SQLAlchemyError as exc:
            error_msg = (
                f"Database error processing batch of {len(drafts)} drafts: {exc}"
            )
            logger.error("DRAFT_EXPIRY | %s", error_msg)
            result.errors.append(error_msg)
        except Exception as exc:
            error_msg = (
                f"Unexpected error processing batch of {len(drafts)} drafts: {exc}"
            )
            logger.error("DRAFT_EXPIRY | %s", error_msg)
            result.errors.append(error_msg)

        return result

    # ------------------------------------------------------------------
    # Single Draft Expiry
    # ------------------------------------------------------------------

    def _expire_draft(
        self, db: Session, draft: CommentDraft, now: datetime
    ) -> DraftExpiry:
        """Expire single draft + cascade to slot + tasks. No commit.

        Sets draft.status to 'expired', updates learning_metadata with expiry
        info, cascades to EPGSlot and ExecutionTask, logs at DEBUG level,
        and returns a DraftExpiry dataclass.
        """
        from sqlalchemy.orm.attributes import flag_modified

        # Capture original status before mutation
        original_status: str = draft.status

        # Compute stale age in whole hours
        if original_status == "approved":
            age_hours = int((now - draft.updated_at).total_seconds() / 3600)
        else:  # pending
            age_hours = int((now - draft.created_at).total_seconds() / 3600)

        # Transition draft status
        draft.status = "expired"

        # Determine expiry reason
        expiry_reason = (
            "stale_approved" if original_status == "approved" else "stale_pending"
        )

        # Build expiry metadata
        expiry_metadata = {
            "expiry_reason": expiry_reason,
            "stale_age_hours": age_hours,
            "expired_at": now.isoformat(),
        }

        # Merge with existing learning_metadata (preserve prior keys)
        if draft.learning_metadata is None:
            draft.learning_metadata = {}
        draft.learning_metadata.update(expiry_metadata)
        flag_modified(draft, "learning_metadata")

        # Cascade to EPGSlot and cancel ExecutionTasks
        slot = self._cascade_epg_slot(db, draft.id)
        tasks_cancelled = self._cancel_execution_tasks(db, slot)

        # Log each expiry at DEBUG level
        logger.debug(
            "DRAFT_EXPIRY | expired draft_id=%s avatar_id=%s client_id=%s "
            "original_status=%s age_hours=%d",
            draft.id,
            draft.avatar_id,
            draft.client_id,
            original_status,
            age_hours,
        )

        # Build and return result
        return DraftExpiry(
            draft_id=draft.id,
            avatar_id=draft.avatar_id,
            client_id=draft.client_id,
            original_status=original_status,
            age_hours=age_hours,
            slot_expired=slot is not None,
            tasks_cancelled=tasks_cancelled,
        )

    # ------------------------------------------------------------------
    # Cascade Methods
    # ------------------------------------------------------------------

    def _cascade_epg_slot(self, db: Session, draft_id: uuid.UUID) -> "EPGSlot | None":
        """Transition associated EPGSlot to expired if non-terminal.

        Queries for an EPGSlot linked to the given draft_id.
        - If found with non-terminal status ('generated', 'approved'):
          sets status='expired', skip_reason='draft_stale_expired'
        - If found with terminal status ('posted', 'skipped', 'expired'):
          leaves unchanged, returns None
        - If not found: returns None without error
        """
        slot = (
            db.query(EPGSlot)
            .filter(EPGSlot.draft_id == draft_id)
            .first()
        )

        if slot is None:
            return None

        # Terminal statuses — leave unchanged
        terminal_statuses = ("posted", "skipped", "expired")
        if slot.status in terminal_statuses:
            return None

        # Non-terminal statuses — expire
        non_terminal_statuses = ("generated", "approved")
        if slot.status in non_terminal_statuses:
            slot.status = "expired"
            slot.skip_reason = "draft_stale_expired"
            return slot

        # Any other unexpected status — leave unchanged
        return None

    def _cancel_execution_tasks(self, db: Session, slot: "EPGSlot | None") -> int:
        """Cancel associated ExecutionTasks if non-terminal. Returns count.

        If slot is None (no associated EPGSlot or slot was terminal), nothing
        to cancel — returns 0.

        For each ExecutionTask linked to the slot with a non-terminal status
        ('generated', 'emailed', 'accepted'), sets:
          - status = 'cancelled'
          - cancel_reason = 'draft_stale_expired'
          - cancelled_at = now (UTC)
          - task_lifecycle_status = 'CANCELLED' (only if currently 'ASSIGNED')

        Terminal statuses ('submitted', 'verified', 'expired', 'cancelled') are
        left unchanged.
        """
        if slot is None:
            return 0

        now = datetime.now(timezone.utc)
        non_terminal_statuses = ("generated", "emailed", "accepted")

        tasks = (
            db.query(ExecutionTask)
            .filter(ExecutionTask.epg_slot_id == slot.id)
            .all()
        )

        cancelled_count = 0
        for task in tasks:
            if task.status in non_terminal_statuses:
                task.status = "cancelled"
                task.cancel_reason = "draft_stale_expired"
                task.cancelled_at = now
                if task.task_lifecycle_status == "ASSIGNED":
                    task.task_lifecycle_status = "CANCELLED"
                cancelled_count += 1

        return cancelled_count

    # ------------------------------------------------------------------
    # Activity Events
    # ------------------------------------------------------------------

    def _emit_activity_events(self, db: Session, result: DraftExpiryResult) -> None:
        """Emit one ActivityEvent per affected client.

        Groups expired drafts by client_id and emits a 'system' activity event
        for each client with counts and metadata. Wraps each client emission in
        try/except so that a failure for one client does not prevent other
        clients' events or revert already-committed batches.
        """
        for client_id, expiries in result.per_client.items():
            try:
                n = len(expiries)
                distinct_avatar_ids = list(
                    {str(e.avatar_id) for e in expiries}
                )
                m = len(distinct_avatar_ids)
                a = sum(1 for e in expiries if e.original_status == "approved")
                p = sum(1 for e in expiries if e.original_status == "pending")
                t = sum(e.tasks_cancelled for e in expiries)

                message = f"Expired {n} stale draft(s) for {m} avatar(s)"

                metadata = {
                    "action": "stale_draft_expiry",
                    "drafts_expired_count": n,
                    "approved_expired_count": a,
                    "pending_expired_count": p,
                    "tasks_cancelled_count": t,
                    "avatar_ids": distinct_avatar_ids,
                }

                record_activity_event(
                    db,
                    event_type="system",
                    message=message,
                    client_id=client_id,
                    metadata=metadata,
                )
            except Exception as exc:
                logger.error(
                    "DRAFT_EXPIRY | failed to emit activity event for client_id=%s: %s",
                    client_id,
                    exc,
                )
