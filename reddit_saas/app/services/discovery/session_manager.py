"""Session Manager — CRUD and state management for Discovery sessions.

Handles creation, retrieval, pagination, state transitions, and cost tracking.
Enforces business rules (max 5 iterations, valid state transitions, permissions).

Provides both module-level functions and a SessionManager class for backward
compatibility with existing route handlers.
"""

import logging
import math
import uuid
from datetime import datetime, timezone

from sqlalchemy import desc, func
from sqlalchemy.orm import Session, joinedload

from app.models.client import Client
from app.models.discovery_entity import DiscoveryEntity
from app.models.discovery_hypothesis import DiscoveryHypothesis
from app.models.discovery_session import DiscoverySession
from app.models.visibility_report import VisibilityReport

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5
MIN_BRIEF_LENGTH = 50
MAX_BRIEF_LENGTH = 5000
MAX_PROSPECT_NAME_LENGTH = 200


# ---------------------------------------------------------------------------
# Module-level functions (task 11.1 interface)
# ---------------------------------------------------------------------------


def create_session(
    operator_id: uuid.UUID,
    client_brief: str,
    prospect_name: str | None,
    client_id: uuid.UUID | None,
    db: Session,
) -> DiscoverySession:
    """Create a new Discovery session.

    Args:
        operator_id: User ID of the operator running discovery.
        client_brief: Free-text description (50-5000 chars).
        prospect_name: Optional prospect name (max 200 chars).
        client_id: Optional existing client UUID to link.
        db: Database session.

    Returns:
        Created DiscoverySession record.

    Raises:
        ValueError: If validation fails (brief length, prospect_name length, client not found).
    """
    # Validate client_brief length
    if not client_brief or len(client_brief.strip()) < MIN_BRIEF_LENGTH:
        raise ValueError(
            f"client_brief must be at least {MIN_BRIEF_LENGTH} characters, "
            f"got {len(client_brief.strip()) if client_brief else 0}"
        )
    if len(client_brief) > MAX_BRIEF_LENGTH:
        raise ValueError(
            f"client_brief must be at most {MAX_BRIEF_LENGTH} characters, "
            f"got {len(client_brief)}"
        )

    # Validate prospect_name length
    if prospect_name and len(prospect_name) > MAX_PROSPECT_NAME_LENGTH:
        raise ValueError(
            f"prospect_name must be at most {MAX_PROSPECT_NAME_LENGTH} characters, "
            f"got {len(prospect_name)}"
        )

    # Verify client exists if client_id provided
    if client_id is not None:
        client = db.query(Client).filter(Client.id == client_id).first()
        if client is None:
            raise ValueError(f"Client with id {client_id} not found")

    session = DiscoverySession(
        operator_user_id=operator_id,
        client_brief=client_brief.strip(),
        prospect_name=prospect_name,
        client_id=client_id,
        status="in_progress",
        current_iteration=1,
        session_metadata={},
        total_ai_cost_usd=0,
    )
    db.add(session)
    db.flush()
    logger.info(f"Created Discovery session {session.id} by operator {operator_id}")
    return session


def get_session(session_id: uuid.UUID, db: Session) -> DiscoverySession:
    """Get a session with relationships eager-loaded.

    Args:
        session_id: UUID of the session to retrieve.
        db: Database session.

    Returns:
        DiscoverySession with entities, hypotheses, and reports loaded.

    Raises:
        ValueError: If session not found.
    """
    session = (
        db.query(DiscoverySession)
        .options(
            joinedload(DiscoverySession.entities),
            joinedload(DiscoverySession.hypotheses),
            joinedload(DiscoverySession.reports),
        )
        .filter(DiscoverySession.id == session_id)
        .first()
    )
    if session is None:
        raise ValueError(f"Discovery session {session_id} not found")
    return session


def list_sessions(
    db: Session,
    page: int = 1,
    per_page: int = 25,
    status_filter: str | None = None,
) -> dict:
    """List sessions with pagination, sorted by created_at DESC.

    Args:
        db: Database session.
        page: Page number (1-indexed).
        per_page: Items per page (default 25).
        status_filter: Optional filter by status.

    Returns:
        Dict with keys: items, page, per_page, total, pages.
    """
    query = db.query(DiscoverySession)

    if status_filter:
        query = query.filter(DiscoverySession.status == status_filter)

    total = query.count()
    pages = math.ceil(total / per_page) if per_page > 0 else 0

    items = (
        query.order_by(desc(DiscoverySession.created_at))
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return {
        "items": items,
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": pages,
    }


def abandon_session(
    session_id: uuid.UUID,
    reason: str | None,
    db: Session,
) -> DiscoverySession:
    """Mark a session as abandoned.

    Args:
        session_id: UUID of the session to abandon.
        reason: Optional abandonment reason.
        db: Database session.

    Returns:
        Updated DiscoverySession.

    Raises:
        ValueError: If session not found or not in 'in_progress' status.
    """
    session = (
        db.query(DiscoverySession)
        .options(joinedload(DiscoverySession.hypotheses))
        .filter(DiscoverySession.id == session_id)
        .first()
    )
    if session is None:
        raise ValueError(f"Discovery session {session_id} not found")

    if session.status != "in_progress":
        raise ValueError(
            f"Only 'in_progress' sessions can be abandoned, "
            f"current status is '{session.status}'"
        )

    session.status = "abandoned"
    session.abandon_reason = reason[:500] if reason else None

    # Mark any "proposed" hypotheses in current iteration as "abandoned"
    for h in session.hypotheses:
        if h.status == "proposed" and h.iteration_number == session.current_iteration:
            h.status = "abandoned"

    db.flush()
    logger.info(f"Session {session.id} abandoned. Reason: {reason or 'none'}")
    return session


def advance_iteration(session_id: uuid.UUID, db: Session) -> DiscoverySession:
    """Advance session to next iteration.

    Args:
        session_id: UUID of the session to advance.
        db: Database session.

    Returns:
        Updated DiscoverySession with incremented iteration.

    Raises:
        ValueError: If session not found, already at max iterations,
                    or hypotheses in current iteration still undecided.
    """
    session = (
        db.query(DiscoverySession)
        .options(joinedload(DiscoverySession.hypotheses))
        .filter(DiscoverySession.id == session_id)
        .first()
    )
    if session is None:
        raise ValueError(f"Discovery session {session_id} not found")

    if session.current_iteration >= MAX_ITERATIONS:
        raise ValueError(
            f"Cannot advance beyond {MAX_ITERATIONS} iterations "
            f"(current: {session.current_iteration})"
        )

    # All hypotheses in current iteration must have a decision (not "proposed")
    current_hypotheses = [
        h for h in session.hypotheses
        if h.iteration_number == session.current_iteration
    ]
    undecided = [h for h in current_hypotheses if h.status == "proposed"]
    if undecided:
        raise ValueError(
            f"Cannot advance: {len(undecided)} hypothesis(es) in iteration "
            f"{session.current_iteration} still have status 'proposed'"
        )

    session.current_iteration += 1
    db.flush()
    logger.info(
        f"Session {session.id} advanced to iteration {session.current_iteration}"
    )
    return session


def update_ai_cost(session_id: uuid.UUID, cost_delta: float, db: Session) -> None:
    """Atomically increment session AI cost.

    Uses SQL expression for atomic increment (no read-modify-write race).

    Args:
        session_id: UUID of the session.
        cost_delta: Cost to add (USD). Must be positive.
        db: Database session.

    Raises:
        ValueError: If cost_delta is not positive.
    """
    if cost_delta <= 0:
        raise ValueError(f"cost_delta must be positive, got {cost_delta}")

    rows_updated = (
        db.query(DiscoverySession)
        .filter(DiscoverySession.id == session_id)
        .update(
            {DiscoverySession.total_ai_cost_usd: DiscoverySession.total_ai_cost_usd + cost_delta},
            synchronize_session="fetch",
        )
    )
    if rows_updated == 0:
        raise ValueError(f"Discovery session {session_id} not found")

    db.flush()
    logger.debug(f"Session {session_id} AI cost incremented by ${cost_delta:.4f}")


# ---------------------------------------------------------------------------
# SessionManager class (backward compatibility with existing routes)
# ---------------------------------------------------------------------------


class SessionManager:
    """Manages Discovery session lifecycle.

    Provides static methods that delegate to module-level functions for
    backward compatibility with existing route handlers.
    """

    @staticmethod
    def create_session(
        db: Session,
        operator_id: uuid.UUID,
        client_brief: str,
        prospect_name: str | None = None,
        client_id: uuid.UUID | None = None,
    ) -> DiscoverySession:
        """Create a new Discovery session.

        Args:
            db: Database session.
            operator_id: User ID of the operator running discovery.
            client_brief: Free-text description (50-5000 chars).
            prospect_name: Optional prospect name if no client linked.
            client_id: Optional existing client UUID to link.

        Returns:
            Created DiscoverySession record.
        """
        return create_session(
            operator_id=operator_id,
            client_brief=client_brief,
            prospect_name=prospect_name,
            client_id=client_id,
            db=db,
        )

    @staticmethod
    def get_session(db: Session, session_id: uuid.UUID) -> DiscoverySession | None:
        """Get a session with all relationships eager-loaded.

        Returns None instead of raising ValueError for backward compatibility.
        """
        try:
            return get_session(session_id=session_id, db=db)
        except ValueError:
            return None

    @staticmethod
    def list_sessions(
        db: Session,
        page: int = 1,
        per_page: int = 25,
        status_filter: str | None = None,
    ) -> tuple[list[DiscoverySession], int]:
        """List sessions with pagination.

        Returns tuple of (session_list, total_count) for backward compatibility.
        """
        result = list_sessions(db=db, page=page, per_page=per_page, status_filter=status_filter)
        return result["items"], result["total"]

    @staticmethod
    def advance_iteration(db: Session, session: DiscoverySession) -> bool:
        """Advance session to next iteration.

        Returns True if advanced, False if already at max iterations.
        Backward-compatible wrapper.
        """
        try:
            advance_iteration(session_id=session.id, db=db)
            return True
        except ValueError:
            return False

    @staticmethod
    def abandon_session(db: Session, session: DiscoverySession, reason: str | None = None) -> None:
        """Mark session as abandoned. Raises ValueError on invalid state."""
        abandon_session(session_id=session.id, reason=reason, db=db)

    @staticmethod
    def complete_session(db: Session, session: DiscoverySession) -> None:
        """Mark session as completed (called after report generation)."""
        session.status = "completed"
        session.completed_at = datetime.now(timezone.utc)
        db.flush()

    @staticmethod
    def update_ai_cost(db: Session, session: DiscoverySession, cost_delta: float) -> None:
        """Atomically increment session AI cost."""
        update_ai_cost(session_id=session.id, cost_delta=cost_delta, db=db)

    @staticmethod
    def get_current_step(session: DiscoverySession) -> str:
        """Determine which UI step the session is currently on.

        Returns one of: brief, entities, hypotheses, research, results, report
        """
        current_hypos = [
            h for h in session.hypotheses
            if h.iteration_number == session.current_iteration
        ]

        # If hypotheses already exist, skip earlier steps regardless of entities state
        if not current_hypos:
            if not session.entities:
                return "brief"
            return "entities"

        metadata = session.session_metadata or {}

        # Check if research was completed/stopped (explicit signals)
        research_done = (
            "research_completed_at" in metadata
            or "research_stopped_by" in metadata
        )

        if not research_done:
            # Check if research is still in progress
            researched = [h for h in current_hypos if h.status != "proposed" or h.reddit_signals]
            if len(researched) < len(current_hypos):
                progress = metadata.get("research_progress", {})
                if progress:
                    return "research"
                return "hypotheses"

        # Research is done (completed or stopped). Check if all decided.
        decided = [h for h in current_hypos if h.status in ("confirmed", "rejected", "abandoned", "research_failed")]
        undecided = [h for h in current_hypos if h.status == "proposed"]

        # If there are undecided but research is done, show results
        # (operator needs to confirm/reject the remaining ones)
        if undecided and not research_done:
            return "results"

        # All decided OR research done with some undecided — show results/report
        if session.reports:
            return "report"

        return "results"

    @staticmethod
    def can_generate_report(session: DiscoverySession) -> bool:
        """Check if session has enough data for report generation."""
        confirmed = [h for h in session.hypotheses if h.status == "confirmed"]
        if len(confirmed) < 1:
            return False

        # Research must be done (either completed iteration or explicit stop)
        metadata = session.session_metadata or {}
        research_done = (
            "research_completed_at" in metadata
            or "research_stopped_by" in metadata
        )

        if research_done:
            return True

        # Fallback: check if at least one iteration has all hypotheses decided
        has_completed_iteration = any(
            all(
                h.status in ("confirmed", "rejected", "abandoned", "research_failed")
                for h in session.hypotheses
                if h.iteration_number == i
            )
            for i in range(1, session.current_iteration + 1)
            if any(h.iteration_number == i for h in session.hypotheses)
        )
        return has_completed_iteration

    @staticmethod
    def is_at_max_iterations(session: DiscoverySession) -> bool:
        """Check if session has reached the maximum iteration count."""
        return session.current_iteration >= MAX_ITERATIONS
