"""LLM Reliability Monitor — Audit Block 4.

Tracks LLM task lifecycle states and detects:
- Stuck tasks in non-terminal states older than 5 minutes
- Lost Response Rate exceeding threshold (0.01% over rolling 7 days)
- Invalid state transitions (violations of the state machine)
- Duplicate completions (same task_id completed more than once)
- Missing ActivityEvent records for state transitions

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.activity_event import ActivityEvent
from app.models.audit_finding import LLMTaskRecord
from app.services.audit.base import (
    AuditBlock,
    AuditBlockName,
    FindingInput,
    FixEffort,
    Severity,
)

logger = get_logger(__name__)

# LLM Task states
TERMINAL_STATES = {"COMPLETED", "FAILED", "LOST"}
NON_TERMINAL_STATES = {"CREATED", "QUEUED", "SENT", "IN_PROGRESS", "PARTIAL", "RECOVERABLE"}

# Valid state transitions from the design state diagram
VALID_TRANSITIONS: dict[str, set[str]] = {
    "CREATED": {"QUEUED"},
    "QUEUED": {"SENT"},
    "SENT": {"IN_PROGRESS", "FAILED", "RECOVERABLE"},
    "IN_PROGRESS": {"COMPLETED", "PARTIAL", "FAILED", "RECOVERABLE"},
    "PARTIAL": {"RECOVERABLE"},
    "FAILED": {"QUEUED", "LOST"},
    "RECOVERABLE": {"QUEUED", "LOST"},
}

# Threshold for lost response rate (0.01%)
LOST_RESPONSE_RATE_THRESHOLD = 0.0001

# Stuck task threshold (5 minutes)
STUCK_TASK_MINUTES = 5


class LLMReliabilityMonitor(AuditBlock):
    """Monitors LLM task reliability, detecting stuck tasks, invalid transitions,
    duplicates, and missing observability events.
    """

    @property
    def name(self) -> AuditBlockName:
        return AuditBlockName.LLM_RELIABILITY

    async def run(self, run_id: UUID, db_session: Session) -> list[FindingInput]:
        """Execute the LLM reliability audit block.

        Checks:
        1. Stuck tasks in non-terminal states older than 5 min
        2. Lost Response Rate over rolling 7 days
        3. State transition integrity
        4. Duplicate completions
        5. Missing ActivityEvent for transitions

        Args:
            run_id: The parent AuditRun ID.
            db_session: SQLAlchemy session.

        Returns:
            List of findings to persist.
        """
        findings: list[FindingInput] = []

        findings.extend(self._check_stuck_tasks(db_session))
        findings.extend(self._check_lost_response_rate(db_session))
        findings.extend(self._check_state_transition_integrity(db_session))
        findings.extend(self._check_duplicate_completions(db_session))
        findings.extend(self._check_missing_activity_events(db_session))

        logger.info(
            "LLMReliabilityMonitor completed with %d findings", len(findings)
        )
        return findings

    def _check_stuck_tasks(self, db: Session) -> list[FindingInput]:
        """Check for tasks stuck in non-terminal states for > 5 minutes.

        Detects orphaned tasks that should have been transitioned to
        RECOVERABLE or LOST (Req 4.4, 4.10).
        """
        findings: list[FindingInput] = []
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=STUCK_TASK_MINUTES)

        # Query tasks in non-terminal states older than the threshold
        stuck_tasks = (
            db.query(LLMTaskRecord)
            .filter(
                LLMTaskRecord.state.in_(list(NON_TERMINAL_STATES)),
                LLMTaskRecord.created_at < cutoff,
            )
            .all()
        )

        if not stuck_tasks:
            return findings

        # Group by state for reporting
        by_state: dict[str, list[LLMTaskRecord]] = {}
        for task in stuck_tasks:
            by_state.setdefault(task.state, []).append(task)

        for state, tasks in by_state.items():
            # SENT or IN_PROGRESS stuck > 5 min without heartbeat is critical
            if state in ("SENT", "IN_PROGRESS"):
                severity = Severity.RED
                risk_desc = (
                    f"{len(tasks)} LLM task(s) stuck in {state} state for >{STUCK_TASK_MINUTES} min "
                    f"without heartbeat. These represent potential lost responses that were "
                    f"never delivered or recovered."
                )
            else:
                severity = Severity.YELLOW
                risk_desc = (
                    f"{len(tasks)} LLM task(s) in {state} state older than {STUCK_TASK_MINUTES} min. "
                    f"These may indicate processing delays or recovery failures."
                )

            # Include sample task IDs in data_path
            sample_ids = [str(t.celery_task_id) for t in tasks[:5]]
            data_path = f"LLMTaskRecord.state={state}, sample_task_ids={sample_ids}"

            findings.append(
                FindingInput(
                    title=f"Stuck LLM tasks in {state} state ({len(tasks)} tasks)",
                    severity=severity,
                    block=AuditBlockName.LLM_RELIABILITY,
                    category="reliability",
                    risk_description=risk_desc[:500],
                    owner="Max",
                    effort=FixEffort.M,
                    risk_if_unresolved=(
                        f"Lost LLM responses: {len(tasks)} tasks may never deliver results, "
                        f"causing silent content generation failures"
                    )[:200],
                    requirement_ref="4.10",
                    data_path=data_path,
                )
            )

        return findings

    def _check_lost_response_rate(self, db: Session) -> list[FindingInput]:
        """Calculate Lost Response Rate over rolling 7 days.

        Lost Response Rate = LOST tasks / total tasks in the window.
        Threshold: < 0.01% (Req 4.7).
        """
        findings: list[FindingInput] = []
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)

        # Count total tasks in the 7-day window
        total_tasks = (
            db.query(func.count(LLMTaskRecord.id))
            .filter(LLMTaskRecord.created_at >= seven_days_ago)
            .scalar()
        ) or 0

        if total_tasks == 0:
            # No tasks in the window — nothing to check
            return findings

        # Count LOST tasks in the 7-day window
        lost_tasks = (
            db.query(func.count(LLMTaskRecord.id))
            .filter(
                LLMTaskRecord.created_at >= seven_days_ago,
                LLMTaskRecord.state == "LOST",
            )
            .scalar()
        ) or 0

        lost_rate = lost_tasks / total_tasks

        if lost_rate > LOST_RESPONSE_RATE_THRESHOLD:
            findings.append(
                FindingInput(
                    title=f"Lost Response Rate exceeds threshold ({lost_rate:.4%})",
                    severity=Severity.RED,
                    block=AuditBlockName.LLM_RELIABILITY,
                    category="reliability",
                    risk_description=(
                        f"Lost Response Rate is {lost_rate:.4%} ({lost_tasks}/{total_tasks} tasks) "
                        f"over the last 7 days, exceeding the 0.01% threshold. "
                        f"This means generated content is being silently lost."
                    )[:500],
                    owner="Max",
                    effort=FixEffort.L,
                    risk_if_unresolved=(
                        f"{lost_tasks} LLM responses lost in 7 days. Content generation "
                        f"silently fails, pipeline appears healthy but misses deliverables"
                    )[:200],
                    requirement_ref="4.7",
                    data_path=f"LLMTaskRecord: {lost_tasks} LOST / {total_tasks} total (7d window)",
                )
            )

        return findings

    def _check_state_transition_integrity(self, db: Session) -> list[FindingInput]:
        """Verify that all state transitions follow the valid state machine.

        Each LLMTaskRecord has a `previous_state` field. If previous_state -> state
        is not in VALID_TRANSITIONS, it's an invalid transition (Req 4.1).
        """
        findings: list[FindingInput] = []

        # Query all tasks that have a previous_state (i.e., have transitioned)
        transitioned_tasks = (
            db.query(LLMTaskRecord)
            .filter(LLMTaskRecord.previous_state.isnot(None))
            .all()
        )

        invalid_transitions: list[tuple[str, str, str]] = []  # (task_id, from, to)
        for task in transitioned_tasks:
            prev = task.previous_state.upper() if task.previous_state else None
            current = task.state.upper() if task.state else None

            if prev and current:
                valid_next = VALID_TRANSITIONS.get(prev, set())
                if current not in valid_next:
                    invalid_transitions.append(
                        (task.celery_task_id, prev, current)
                    )

        if invalid_transitions:
            # Report invalid transitions
            sample = invalid_transitions[:10]
            sample_desc = "; ".join(
                f"{tid}: {frm}->{to}" for tid, frm, to in sample
            )

            findings.append(
                FindingInput(
                    title=f"Invalid LLM state transitions detected ({len(invalid_transitions)} violations)",
                    severity=Severity.RED,
                    block=AuditBlockName.LLM_RELIABILITY,
                    category="reliability",
                    risk_description=(
                        f"{len(invalid_transitions)} LLM tasks have invalid state transitions "
                        f"that violate the state machine. This indicates bugs in the task "
                        f"lifecycle management. Samples: {sample_desc}"
                    )[:500],
                    owner="Max",
                    effort=FixEffort.M,
                    risk_if_unresolved=(
                        "Invalid state transitions corrupt task lifecycle tracking, "
                        "making it impossible to reliably detect lost responses"
                    )[:200],
                    requirement_ref="4.1",
                    data_path=f"LLMTaskRecord invalid transitions: {sample_desc[:200]}",
                )
            )

        return findings

    def _check_duplicate_completions(self, db: Session) -> list[FindingInput]:
        """Check for duplicate completions (same celery_task_id completed multiple times).

        In the current model, celery_task_id is unique, so true duplicates would be
        multiple records with the same logical task completing. We check for any task
        that has state=COMPLETED and the same operation+client+avatar within a very
        short window (indicating duplicate delivery) (Req 4.6).
        """
        findings: list[FindingInput] = []

        # Since celery_task_id is unique in the table, we look for tasks with the same
        # (client_id, avatar_id, operation) completing within 5 seconds of each other
        # which indicates duplicate task delivery
        from sqlalchemy import text

        # Use a self-join approach: find pairs of COMPLETED tasks with same
        # client_id + avatar_id + operation within 5 seconds
        duplicate_query = text("""
            SELECT t1.celery_task_id AS task1, t2.celery_task_id AS task2,
                   t1.client_id, t1.operation, t1.completed_at AS completed1,
                   t2.completed_at AS completed2
            FROM llm_task_records t1
            JOIN llm_task_records t2
                ON t1.client_id = t2.client_id
                AND t1.avatar_id IS NOT DISTINCT FROM t2.avatar_id
                AND t1.operation = t2.operation
                AND t1.id < t2.id
                AND t1.state = 'COMPLETED'
                AND t2.state = 'COMPLETED'
                AND t1.completed_at IS NOT NULL
                AND t2.completed_at IS NOT NULL
                AND ABS(EXTRACT(EPOCH FROM (t1.completed_at - t2.completed_at))) < 5
            LIMIT 50
        """)

        try:
            duplicates = db.execute(duplicate_query).fetchall()
        except Exception as exc:
            logger.warning(
                "Could not check duplicate completions (table may not exist): %s", exc
            )
            return findings

        if duplicates:
            sample_desc = "; ".join(
                f"{row[0]} & {row[1]} ({row[3]})" for row in duplicates[:5]
            )
            findings.append(
                FindingInput(
                    title=f"Duplicate LLM completions detected ({len(duplicates)} pairs)",
                    severity=Severity.YELLOW,
                    block=AuditBlockName.LLM_RELIABILITY,
                    category="reliability",
                    risk_description=(
                        f"{len(duplicates)} pairs of LLM tasks completed within 5s of each "
                        f"other for the same client/avatar/operation, indicating potential "
                        f"duplicate task delivery. Samples: {sample_desc}"
                    )[:500],
                    owner="Max",
                    effort=FixEffort.M,
                    risk_if_unresolved=(
                        "Duplicate completions waste LLM credits and may produce "
                        "duplicate drafts confusing the review queue"
                    )[:200],
                    requirement_ref="4.6",
                    data_path=f"Duplicate completions: {sample_desc[:200]}",
                )
            )

        return findings

    def _check_missing_activity_events(self, db: Session) -> list[FindingInput]:
        """Verify all LLM task state transitions have corresponding ActivityEvent records.

        For each task that has transitioned (has previous_state), we check that an
        ActivityEvent of type 'llm_task_state_transition' or similar exists with
        matching task context (Req 4.9).
        """
        findings: list[FindingInput] = []

        # Count tasks that have transitioned (have previous_state set)
        transitioned_count = (
            db.query(func.count(LLMTaskRecord.id))
            .filter(LLMTaskRecord.previous_state.isnot(None))
            .scalar()
        ) or 0

        if transitioned_count == 0:
            # No transitions to verify
            return findings

        # Count ActivityEvents that correspond to LLM task transitions
        # Look for events with type matching LLM state transition patterns
        transition_event_types = [
            "llm_task_state_transition",
            "llm_task_transition",
            "llm_state_change",
            "task_state_transition",
        ]

        transition_events_count = (
            db.query(func.count(ActivityEvent.id))
            .filter(ActivityEvent.event_type.in_(transition_event_types))
            .scalar()
        ) or 0

        # If significantly fewer events than transitions, flag as an issue
        if transition_events_count < transitioned_count:
            missing_count = transitioned_count - transition_events_count
            coverage_pct = (
                (transition_events_count / transitioned_count * 100)
                if transitioned_count > 0
                else 0
            )

            # Determine severity based on coverage gap
            if coverage_pct < 50:
                severity = Severity.RED
            elif coverage_pct < 90:
                severity = Severity.YELLOW
            else:
                # Over 90% coverage — minor gap
                return findings

            findings.append(
                FindingInput(
                    title=f"Missing ActivityEvents for LLM state transitions ({missing_count} gaps)",
                    severity=severity,
                    block=AuditBlockName.LLM_RELIABILITY,
                    category="reliability",
                    risk_description=(
                        f"Only {transition_events_count}/{transitioned_count} LLM task state "
                        f"transitions have corresponding ActivityEvent records "
                        f"({coverage_pct:.1f}% coverage). Missing events make it impossible "
                        f"to audit task lifecycle and detect anomalies."
                    )[:500],
                    owner="Max",
                    effort=FixEffort.M,
                    risk_if_unresolved=(
                        "Without transition events, lost responses and lifecycle "
                        "anomalies cannot be detected or diagnosed"
                    )[:200],
                    requirement_ref="4.9",
                    data_path=(
                        f"ActivityEvent coverage: {transition_events_count}/{transitioned_count} "
                        f"({coverage_pct:.1f}%)"
                    ),
                )
            )

        return findings
