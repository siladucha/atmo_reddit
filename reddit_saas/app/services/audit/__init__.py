"""Production Readiness Audit engine — orchestrator for modular audit blocks.

The AuditEngine coordinates execution of all 8 audit blocks, persists findings,
calculates GO/NO-GO status, and emits activity events on completion.

This package also re-exports the original audit logging functions so that all
existing imports from `app.services.audit` continue to work.
"""

# Re-export original audit logging service functions for backwards compatibility
from app.services.audit.audit_logging import (  # noqa: F401
    delete_all_audit_logs,
    delete_filtered_audit_logs,
    get_distinct_actions,
    get_distinct_entity_types,
    log_action,
    log_system_action,
    query_audit_logs,
)

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.logging_config import get_logger
from app.models.activity_event import ActivityEvent
from app.models.audit_finding import AuditFinding, AuditRun
from app.services.audit.base import (
    AuditBlock,
    AuditBlockName,
    BlockStatus,
    FindingInput,
    Severity,
)
from app.services.distributed_lock import DistributedLock

logger = get_logger(__name__)

# Redis lock key for concurrent audit prevention
AUDIT_LOCK_KEY = "audit_engine:run_lock"
AUDIT_LOCK_TTL = 1800  # 30 minutes


class AuditConflictError(Exception):
    """Raised when an audit is already in progress (409 conflict)."""

    pass


class AuditEngine:
    """Orchestrates audit block execution and finding persistence.

    Creates AuditRun records, dispatches blocks, persists findings,
    calculates GO/NO-GO, and emits activity events.
    """

    def __init__(self, db: Session, blocks: list[AuditBlock] | None = None) -> None:
        self.db = db
        self.blocks = blocks or []

    async def run_full_audit(self, triggered_by: str = "manual") -> uuid.UUID:
        """Create AuditRun, execute all blocks, persist findings, generate report.

        Args:
            triggered_by: Who triggered the audit (e.g. "manual:{user_id}", "scheduled").

        Returns:
            The AuditRun ID.

        Raises:
            AuditConflictError: If another audit is already running (409).
        """
        # 1. Acquire distributed lock to prevent concurrent audits
        lock = DistributedLock(key=AUDIT_LOCK_KEY, ttl=AUDIT_LOCK_TTL)
        if not lock.acquire():
            raise AuditConflictError(
                "Another audit is already in progress. Please wait for it to complete."
            )

        try:
            # 2. Create AuditRun record
            run = AuditRun(
                id=uuid.uuid4(),
                status="running",
                triggered_by=triggered_by,
                started_at=datetime.now(timezone.utc),
                block_statuses={
                    block.name.value: BlockStatus.PENDING.value for block in self.blocks
                },
            )
            self.db.add(run)
            self.db.commit()
            self.db.refresh(run)

            logger.info("Audit run started: %s (triggered_by=%s)", run.id, triggered_by)

            # 3. Run each block, catch exceptions per block
            all_findings: list[FindingInput] = []
            for block in self.blocks:
                all_findings.extend(
                    await self._execute_block(block, run)
                )

            # 4. Persist all findings as AuditFinding records
            self._persist_findings(run.id, all_findings)

            # 5. Calculate go_no_go and incident_probability
            findings_for_calc = (
                self.db.query(AuditFinding).filter(AuditFinding.run_id == run.id).all()
            )
            run.go_no_go = self.calculate_go_no_go(findings_for_calc)
            run.incident_probability = self.calculate_incident_probability(findings_for_calc)

            # 6. Update AuditRun with results
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
            self.db.commit()

            # 7. Emit ActivityEvent on audit completion
            self._emit_completion_event(run)

            logger.info(
                "Audit run completed: %s (go_no_go=%s, incident_prob=%d%%)",
                run.id,
                run.go_no_go,
                run.incident_probability or 0,
            )

            return run.id

        finally:
            # 8. Release lock
            lock.release()

    async def run_single_block(
        self, block_name: AuditBlockName, triggered_by: str = "manual"
    ) -> uuid.UUID:
        """Run a single audit block for re-checks after fixes.

        Args:
            block_name: The block to run.
            triggered_by: Who triggered the re-check.

        Returns:
            The AuditRun ID.

        Raises:
            AuditConflictError: If another audit is already running (409).
            ValueError: If block_name is not found in registered blocks.
        """
        # Find the requested block
        target_block: AuditBlock | None = None
        for block in self.blocks:
            if block.name == block_name:
                target_block = block
                break

        if target_block is None:
            raise ValueError(f"Block '{block_name.value}' not found in registered blocks.")

        # Acquire distributed lock
        lock = DistributedLock(key=AUDIT_LOCK_KEY, ttl=AUDIT_LOCK_TTL)
        if not lock.acquire():
            raise AuditConflictError(
                "Another audit is already in progress. Please wait for it to complete."
            )

        try:
            # Create AuditRun for single block
            run = AuditRun(
                id=uuid.uuid4(),
                status="running",
                triggered_by=triggered_by,
                started_at=datetime.now(timezone.utc),
                block_statuses={block_name.value: BlockStatus.PENDING.value},
            )
            self.db.add(run)
            self.db.commit()
            self.db.refresh(run)

            logger.info(
                "Single block audit started: %s (block=%s, triggered_by=%s)",
                run.id,
                block_name.value,
                triggered_by,
            )

            # Execute the single block
            findings = await self._execute_block(target_block, run)

            # Persist findings
            self._persist_findings(run.id, findings)

            # Calculate results
            findings_for_calc = (
                self.db.query(AuditFinding).filter(AuditFinding.run_id == run.id).all()
            )
            run.go_no_go = self.calculate_go_no_go(findings_for_calc)
            run.incident_probability = self.calculate_incident_probability(findings_for_calc)

            # Update run status
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
            self.db.commit()

            # Emit completion event
            self._emit_completion_event(run)

            logger.info(
                "Single block audit completed: %s (block=%s, go_no_go=%s)",
                run.id,
                block_name.value,
                run.go_no_go,
            )

            return run.id

        finally:
            lock.release()

    def calculate_go_no_go(self, findings: list) -> bool:
        """Calculate GO/NO-GO decision.

        Returns True (GO) if there are no unexempted RED findings.
        A RED finding is considered exempted if it has decision='accept'
        AND an exemption_reason is provided.

        Args:
            findings: List of AuditFinding records.

        Returns:
            True if GO, False if NO-GO.
        """
        for finding in findings:
            if finding.severity == Severity.RED.value:
                # RED finding is a blocker unless explicitly accepted with exemption
                if finding.decision != "accept" or not finding.exemption_reason:
                    return False
        return True

    def calculate_incident_probability(self, findings: list) -> int:
        """Calculate first-week incident probability percentage.

        Formula: min(100, red_count * 15 + yellow_count * 5)

        Args:
            findings: List of AuditFinding records.

        Returns:
            Integer 0-100 representing probability percentage.
        """
        red_count = sum(1 for f in findings if f.severity == Severity.RED.value)
        yellow_count = sum(1 for f in findings if f.severity == Severity.YELLOW.value)
        return min(100, red_count * 15 + yellow_count * 5)

    async def _execute_block(
        self, block: AuditBlock, run: AuditRun
    ) -> list[FindingInput]:
        """Execute a single audit block with exception handling.

        On success: sets block status to completed.
        On failure: sets block status to failed, continues (does not re-raise).

        Args:
            block: The audit block to execute.
            run: The parent AuditRun record.

        Returns:
            List of findings from the block (empty if block failed).
        """
        block_name = block.name.value

        # Update status to running
        run.block_statuses[block_name] = BlockStatus.RUNNING.value
        flag_modified(run, "block_statuses")
        self.db.commit()

        try:
            findings = await block.run(run.id, self.db)

            # Mark block as completed
            run.block_statuses[block_name] = BlockStatus.COMPLETED.value
            flag_modified(run, "block_statuses")
            self.db.commit()

            logger.info(
                "Block '%s' completed with %d findings", block_name, len(findings)
            )
            return findings

        except Exception as exc:
            # Set block status to failed, continue with other blocks
            logger.error(
                "Block '%s' failed with exception: %s", block_name, str(exc),
                exc_info=True,
            )
            run.block_statuses[block_name] = BlockStatus.FAILED.value
            flag_modified(run, "block_statuses")
            self.db.commit()
            return []

    def _persist_findings(
        self, run_id: uuid.UUID, findings: list[FindingInput]
    ) -> None:
        """Persist FindingInput objects as AuditFinding records in the database.

        Args:
            run_id: The parent AuditRun ID.
            findings: List of finding inputs to persist.
        """
        for finding_input in findings:
            # RED and YELLOW default to fix_before_release; GREEN defaults to accept
            if finding_input.severity in (Severity.RED, Severity.YELLOW):
                default_decision = "fix_before_release"
            else:
                default_decision = "accept"

            finding = AuditFinding(
                id=uuid.uuid4(),
                run_id=run_id,
                block=finding_input.block.value,
                title=finding_input.title[:120],
                severity=finding_input.severity.value,
                category=finding_input.category,
                risk_description=finding_input.risk_description[:500],
                owner=finding_input.owner,
                effort=finding_input.effort.value,
                risk_if_unresolved=finding_input.risk_if_unresolved[:200],
                decision=default_decision,
                requirement_ref=finding_input.requirement_ref,
                data_path=finding_input.data_path,
                eta=finding_input.eta,
            )
            self.db.add(finding)

        self.db.commit()
        logger.info("Persisted %d findings for run %s", len(findings), run_id)

    def _emit_completion_event(self, run: AuditRun) -> None:
        """Emit an ActivityEvent on audit completion.

        Args:
            run: The completed AuditRun record.
        """
        # Count findings by severity
        red_count = (
            self.db.query(AuditFinding)
            .filter(AuditFinding.run_id == run.id, AuditFinding.severity == "red")
            .count()
        )
        yellow_count = (
            self.db.query(AuditFinding)
            .filter(AuditFinding.run_id == run.id, AuditFinding.severity == "yellow")
            .count()
        )
        green_count = (
            self.db.query(AuditFinding)
            .filter(AuditFinding.run_id == run.id, AuditFinding.severity == "green")
            .count()
        )

        go_status = "GO" if run.go_no_go else "NO-GO"
        message = (
            f"Production readiness audit completed: {go_status}. "
            f"RED: {red_count}, YELLOW: {yellow_count}, GREEN: {green_count}. "
            f"Incident probability: {run.incident_probability or 0}%"
        )

        event = ActivityEvent(
            event_type="audit_completed",
            message=message,
            event_metadata={
                "run_id": str(run.id),
                "go_no_go": run.go_no_go,
                "incident_probability": run.incident_probability,
                "red_count": red_count,
                "yellow_count": yellow_count,
                "green_count": green_count,
                "triggered_by": run.triggered_by,
                "block_statuses": run.block_statuses,
            },
        )
        self.db.add(event)
        self.db.commit()
