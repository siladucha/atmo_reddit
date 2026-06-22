"""CreditIntegrityChecker — Audit Block 2: Credit and Usage Accounting Integrity.

Verifies that credit/usage accounting is consistent across all state transitions:
- Each AI operation has a matching AIUsageLog entry
- No duplicates within 60-second execution windows
- Failed calls (output_tokens=0) produce zero cost
- No orphaned executions (tasks without usage entry)
- Retry sequences record only the successful attempt

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.ai_usage import AIUsageLog
from app.models.audit_finding import LLMTaskRecord
from app.services.audit.base import (
    AuditBlock,
    AuditBlockName,
    FindingInput,
    FixEffort,
    Severity,
)

logger = get_logger(__name__)

# Configuration constants
TASK_USAGE_MATCH_WINDOW_SECONDS = 5  # Req 2.3: AIUsageLog within 5s of task completion
DUPLICATE_WINDOW_SECONDS = 60  # Req 2.2: same operation within 60s = duplicate
# How far back to look for recent data (audit window)
AUDIT_LOOKBACK_DAYS = 7


class CreditIntegrityChecker(AuditBlock):
    """Verifies credit/usage accounting integrity across AI operations.

    Queries LLMTaskRecord (task lifecycle) and AIUsageLog (usage entries)
    to detect inconsistencies: missing entries, duplicates, incorrect costs,
    orphaned executions, and retry accounting violations.
    """

    @property
    def name(self) -> AuditBlockName:
        return AuditBlockName.CREDIT_INTEGRITY

    async def run(self, run_id: UUID, db_session: Session) -> list[FindingInput]:
        """Execute credit integrity checks and return findings.

        Args:
            run_id: The parent AuditRun ID.
            db_session: SQLAlchemy session.

        Returns:
            List of FindingInput objects representing detected issues.
        """
        findings: list[FindingInput] = []
        now = datetime.now(timezone.utc)
        lookback_start = now - timedelta(days=AUDIT_LOOKBACK_DAYS)

        logger.info("CreditIntegrityChecker: starting audit (lookback=%d days)", AUDIT_LOOKBACK_DAYS)

        # Check 1: Detect duplicate AIUsageLog entries (Req 2.2)
        duplicate_findings = self._check_duplicates(db_session, lookback_start)
        findings.extend(duplicate_findings)

        # Check 2: Verify task-to-usage reconciliation (Req 2.3, 2.5, 2.7)
        reconciliation_findings = self._check_task_usage_reconciliation(
            db_session, lookback_start
        )
        findings.extend(reconciliation_findings)

        # Check 3: Verify failed calls have zero cost (Req 2.4)
        failed_cost_findings = self._check_failed_call_costs(db_session, lookback_start)
        findings.extend(failed_cost_findings)

        # Check 4: Verify retry deduplication (Req 2.6, 2.8)
        retry_findings = self._check_retry_deduplication(db_session, lookback_start)
        findings.extend(retry_findings)

        # Check 5: Produce reconciliation report summary (Req 2.9)
        summary_finding = self._produce_reconciliation_summary(
            db_session, lookback_start, findings
        )
        if summary_finding:
            findings.append(summary_finding)

        logger.info(
            "CreditIntegrityChecker: completed with %d findings", len(findings)
        )
        return findings

    def _check_duplicates(
        self, db: Session, lookback_start: datetime
    ) -> list[FindingInput]:
        """Detect duplicate AIUsageLog entries within 60-second windows.

        Requirement 2.2: No single operation (client_id, avatar_id, thread_id, operation)
        should be recorded more than once within 60 seconds.
        """
        findings: list[FindingInput] = []

        # Query all usage entries in the audit window
        usage_entries = (
            db.query(AIUsageLog)
            .filter(AIUsageLog.created_at >= lookback_start)
            .order_by(
                AIUsageLog.client_id,
                AIUsageLog.avatar_id,
                AIUsageLog.operation,
                AIUsageLog.created_at,
            )
            .all()
        )

        # Group by (client_id, avatar_id, thread_id, operation) and check for entries
        # within 60s of each other
        duplicates_found = 0
        seen: dict[tuple, list[datetime]] = {}

        for entry in usage_entries:
            key = (
                str(entry.client_id) if entry.client_id else None,
                str(entry.avatar_id) if entry.avatar_id else None,
                str(entry.thread_id) if entry.thread_id else None,
                entry.operation,
            )

            if key not in seen:
                seen[key] = [entry.created_at]
                continue

            # Check if this entry is within 60s of any previous entry with same key
            for prev_time in seen[key]:
                if entry.created_at and prev_time:
                    delta = abs((entry.created_at - prev_time).total_seconds())
                    if delta <= DUPLICATE_WINDOW_SECONDS:
                        duplicates_found += 1
                        break

            seen[key].append(entry.created_at)

        if duplicates_found > 0:
            findings.append(
                FindingInput(
                    title=f"Duplicate usage entries: {duplicates_found} duplicates within 60s window",
                    severity=Severity.YELLOW if duplicates_found < 10 else Severity.RED,
                    block=AuditBlockName.CREDIT_INTEGRITY,
                    category="reliability",
                    risk_description=(
                        f"Found {duplicates_found} duplicate AIUsageLog entries with same "
                        f"(client_id, avatar_id, thread_id, operation) within 60 seconds. "
                        f"This may cause over-billing or inaccurate cost reporting."
                    ),
                    owner="Max",
                    effort=FixEffort.M,
                    risk_if_unresolved="Clients may be charged multiple times for single operations",
                    requirement_ref="2.2",
                    data_path="ai_usage_log table — duplicate entries",
                )
            )

        return findings

    def _check_task_usage_reconciliation(
        self, db: Session, lookback_start: datetime
    ) -> list[FindingInput]:
        """Verify each completed LLM task has a matching AIUsageLog entry.

        Requirement 2.3: Every completed Celery task that invokes an LLM call
        must have a corresponding AIUsageLog entry within 5 seconds.
        Requirement 2.5: Orphaned executions (task completed but no usage log).
        Requirement 2.7: Worker restart leaving unreconciled gaps.
        """
        findings: list[FindingInput] = []

        # Get all completed LLMTaskRecords in the audit window
        completed_tasks = (
            db.query(LLMTaskRecord)
            .filter(
                LLMTaskRecord.state == "COMPLETED",
                LLMTaskRecord.completed_at >= lookback_start,
                LLMTaskRecord.completed_at.isnot(None),
            )
            .all()
        )

        if not completed_tasks:
            logger.info("No completed LLM tasks found in audit window")
            return findings

        missing_usage_count = 0
        missing_tasks: list[str] = []

        for task in completed_tasks:
            # Look for a matching AIUsageLog entry:
            # - same client_id, avatar_id, operation
            # - created_at within 5 seconds of task.completed_at
            window_start = task.completed_at - timedelta(seconds=TASK_USAGE_MATCH_WINDOW_SECONDS)
            window_end = task.completed_at + timedelta(seconds=TASK_USAGE_MATCH_WINDOW_SECONDS)

            matching_usage = (
                db.query(AIUsageLog)
                .filter(
                    AIUsageLog.client_id == task.client_id,
                    AIUsageLog.operation == task.operation,
                    AIUsageLog.created_at >= window_start,
                    AIUsageLog.created_at <= window_end,
                )
            )

            # Also match avatar_id if available
            if task.avatar_id:
                matching_usage = matching_usage.filter(
                    AIUsageLog.avatar_id == task.avatar_id
                )

            match = matching_usage.first()
            if not match:
                missing_usage_count += 1
                missing_tasks.append(task.celery_task_id)

        if missing_usage_count > 0:
            severity = Severity.RED if missing_usage_count > 5 else Severity.YELLOW
            findings.append(
                FindingInput(
                    title=f"Orphaned executions: {missing_usage_count} tasks without usage entry",
                    severity=severity,
                    block=AuditBlockName.CREDIT_INTEGRITY,
                    category="reliability",
                    risk_description=(
                        f"Found {missing_usage_count} completed LLM tasks with no matching "
                        f"AIUsageLog entry within {TASK_USAGE_MATCH_WINDOW_SECONDS}s window. "
                        f"These represent unreconciled usage gaps."
                    ),
                    owner="Max",
                    effort=FixEffort.M,
                    risk_if_unresolved="LLM costs incurred but not tracked, usage reports inaccurate",
                    requirement_ref="2.3",
                    data_path=(
                        f"Orphaned task IDs: "
                        f"{', '.join(missing_tasks[:5])}"
                        f"{'...' if len(missing_tasks) > 5 else ''}"
                    ),
                )
            )

        # Check for tasks stuck in non-terminal states (Req 2.7)
        now = datetime.now(timezone.utc)
        stuck_threshold = now - timedelta(minutes=5)

        stuck_tasks = (
            db.query(LLMTaskRecord)
            .filter(
                LLMTaskRecord.state.in_(["SENT", "IN_PROGRESS", "QUEUED"]),
                LLMTaskRecord.created_at >= lookback_start,
                LLMTaskRecord.last_heartbeat_at < stuck_threshold,
            )
            .count()
        )

        if stuck_tasks > 0:
            findings.append(
                FindingInput(
                    title=f"Unreconciled gaps: {stuck_tasks} tasks stuck in non-terminal state",
                    severity=Severity.RED,
                    block=AuditBlockName.CREDIT_INTEGRITY,
                    category="reliability",
                    risk_description=(
                        f"Found {stuck_tasks} LLM tasks in SENT/IN_PROGRESS/QUEUED state "
                        f"with no heartbeat in 5+ minutes. These may represent worker crashes "
                        f"leaving operations partially executed without usage recording."
                    ),
                    owner="Max",
                    effort=FixEffort.M,
                    risk_if_unresolved="Operations may have consumed LLM tokens without accounting",
                    requirement_ref="2.7",
                    data_path="llm_task_records — stuck in non-terminal state",
                )
            )

        return findings

    def _check_failed_call_costs(
        self, db: Session, lookback_start: datetime
    ) -> list[FindingInput]:
        """Verify failed calls (output_tokens=0) have cost_usd=0.

        Requirement 2.4: If an LLM call returns error or produces zero output_tokens,
        no AIUsageLog entry should have cost_usd > 0.
        """
        findings: list[FindingInput] = []

        # Find usage entries where output_tokens=0 but cost_usd > 0
        invalid_cost_entries = (
            db.query(AIUsageLog)
            .filter(
                AIUsageLog.created_at >= lookback_start,
                AIUsageLog.output_tokens == 0,
                AIUsageLog.cost_usd > Decimal("0"),
            )
            .count()
        )

        if invalid_cost_entries > 0:
            findings.append(
                FindingInput(
                    title=f"Failed calls with non-zero cost: {invalid_cost_entries} entries",
                    severity=Severity.RED,
                    block=AuditBlockName.CREDIT_INTEGRITY,
                    category="reliability",
                    risk_description=(
                        f"Found {invalid_cost_entries} AIUsageLog entries where output_tokens=0 "
                        f"but cost_usd > 0. Failed LLM calls should never incur cost charges "
                        f"since no useful output was produced."
                    ),
                    owner="Max",
                    effort=FixEffort.S,
                    risk_if_unresolved="Clients charged for failed operations with no output",
                    requirement_ref="2.4",
                    data_path="ai_usage_log — output_tokens=0 with cost_usd > 0",
                )
            )

        return findings

    def _check_retry_deduplication(
        self, db: Session, lookback_start: datetime
    ) -> list[FindingInput]:
        """Verify retry sequences record only the successful attempt.

        Requirement 2.6: Only the successful attempt in a retry sequence should be
        recorded in AIUsageLog. Failed retry attempts with zero tokens should not
        count toward client cost.
        Requirement 2.8: At most one AIUsageLog entry per unique Celery task_id.
        """
        findings: list[FindingInput] = []

        # Get tasks with retry attempts (attempt_count > 1)
        retried_tasks = (
            db.query(LLMTaskRecord)
            .filter(
                LLMTaskRecord.created_at >= lookback_start,
                LLMTaskRecord.attempt_count > 1,
                LLMTaskRecord.state == "COMPLETED",
                LLMTaskRecord.completed_at.isnot(None),
            )
            .all()
        )

        multi_usage_count = 0

        for task in retried_tasks:
            # For each retried task, check how many AIUsageLog entries exist
            # within a broader window covering all retry attempts
            retry_window_start = task.created_at
            retry_window_end = task.completed_at + timedelta(
                seconds=TASK_USAGE_MATCH_WINDOW_SECONDS
            )

            usage_count_query = (
                db.query(func.count(AIUsageLog.id))
                .filter(
                    AIUsageLog.client_id == task.client_id,
                    AIUsageLog.operation == task.operation,
                    AIUsageLog.created_at >= retry_window_start,
                    AIUsageLog.created_at <= retry_window_end,
                )
            )

            if task.avatar_id:
                usage_count_query = usage_count_query.filter(
                    AIUsageLog.avatar_id == task.avatar_id
                )

            count = usage_count_query.scalar() or 0

            if count > 1:
                multi_usage_count += 1

        if multi_usage_count > 0:
            findings.append(
                FindingInput(
                    title=f"Retry dedup violation: {multi_usage_count} tasks with multiple usage entries",
                    severity=Severity.YELLOW if multi_usage_count < 5 else Severity.RED,
                    block=AuditBlockName.CREDIT_INTEGRITY,
                    category="reliability",
                    risk_description=(
                        f"Found {multi_usage_count} retried LLM tasks that have more than one "
                        f"AIUsageLog entry. Only the successful attempt should be recorded — "
                        f"failed retry attempts should not count toward client cost."
                    ),
                    owner="Max",
                    effort=FixEffort.M,
                    risk_if_unresolved="Client costs inflated by counting failed retries as billable",
                    requirement_ref="2.6",
                    data_path="ai_usage_log — multiple entries for retried operations",
                )
            )

        # Check for duplicate task_id usage (Req 2.8)
        # Since AIUsageLog doesn't have celery_task_id, we check via LLMTaskRecord.
        # Look for multiple completed LLMTaskRecords with same celery_task_id
        # (duplicate message delivery).
        duplicate_task_ids = (
            db.query(LLMTaskRecord.celery_task_id, func.count(LLMTaskRecord.id))
            .filter(
                LLMTaskRecord.created_at >= lookback_start,
                LLMTaskRecord.state == "COMPLETED",
            )
            .group_by(LLMTaskRecord.celery_task_id)
            .having(func.count(LLMTaskRecord.id) > 1)
            .all()
        )

        if duplicate_task_ids:
            dup_count = len(duplicate_task_ids)
            findings.append(
                FindingInput(
                    title=f"Task ID dedup violation: {dup_count} task IDs with multiple records",
                    severity=Severity.RED,
                    block=AuditBlockName.CREDIT_INTEGRITY,
                    category="reliability",
                    risk_description=(
                        f"Found {dup_count} Celery task IDs with multiple completed "
                        f"LLMTaskRecord entries. Each unique task_id should produce at "
                        f"most one record, regardless of message delivery count."
                    ),
                    owner="Max",
                    effort=FixEffort.M,
                    risk_if_unresolved="Duplicate task execution causing double-counting of usage",
                    requirement_ref="2.8",
                    data_path="llm_task_records — duplicate celery_task_id completions",
                )
            )

        return findings

    def _produce_reconciliation_summary(
        self, db: Session, lookback_start: datetime, current_findings: list[FindingInput]
    ) -> FindingInput | None:
        """Produce reconciliation report summary (Req 2.9).

        Lists: total operations executed, total AIUsageLog entries,
        count of duplicates, missing entries, orphaned executions,
        and per-client cost variance.

        Only produces a finding if there are discrepancies or data exists.
        """
        # Total completed LLM tasks
        total_tasks = (
            db.query(func.count(LLMTaskRecord.id))
            .filter(
                LLMTaskRecord.created_at >= lookback_start,
                LLMTaskRecord.state == "COMPLETED",
            )
            .scalar()
            or 0
        )

        # Total AIUsageLog entries
        total_usage_entries = (
            db.query(func.count(AIUsageLog.id))
            .filter(AIUsageLog.created_at >= lookback_start)
            .scalar()
            or 0
        )

        # Count findings by type
        duplicates = sum(
            1 for f in current_findings if "Duplicate" in f.title and "usage" in f.title
        )
        orphans = sum(1 for f in current_findings if "Orphaned" in f.title)
        stuck = sum(1 for f in current_findings if "Unreconciled" in f.title)
        failed_cost_issues = sum(1 for f in current_findings if "Failed calls" in f.title)
        retry_issues = sum(1 for f in current_findings if "Retry dedup" in f.title)

        # Per-client cost summary
        client_costs = (
            db.query(
                AIUsageLog.client_id,
                func.sum(AIUsageLog.cost_usd).label("total_cost"),
                func.count(AIUsageLog.id).label("entry_count"),
            )
            .filter(AIUsageLog.created_at >= lookback_start)
            .group_by(AIUsageLog.client_id)
            .all()
        )

        # Determine if there are any discrepancies
        has_issues = any([duplicates, orphans, stuck, failed_cost_issues, retry_issues])

        if not has_issues and total_tasks == 0 and total_usage_entries == 0:
            # No data to audit — skip summary
            return None

        # Build summary description
        cost_summary_parts = []
        for row in client_costs[:5]:  # Show top 5 clients
            client_label = str(row.client_id)[:8] if row.client_id else "system"
            cost_summary_parts.append(
                f"{client_label}: ${row.total_cost:.4f} ({row.entry_count} ops)"
            )

        cost_text = "; ".join(cost_summary_parts) if cost_summary_parts else "No usage data"

        severity = Severity.GREEN
        if has_issues:
            severity = Severity.YELLOW

        return FindingInput(
            title=f"Reconciliation: {total_tasks} tasks, {total_usage_entries} usage entries",
            severity=severity,
            block=AuditBlockName.CREDIT_INTEGRITY,
            category="reliability",
            risk_description=(
                f"Audit window: last {AUDIT_LOOKBACK_DAYS} days. "
                f"Tasks completed: {total_tasks}. Usage entries: {total_usage_entries}. "
                f"Duplicates: {duplicates}. Orphaned: {orphans}. "
                f"Stuck: {stuck}. Failed-cost issues: {failed_cost_issues}. "
                f"Retry issues: {retry_issues}. Client costs: {cost_text}"
            ),
            owner="Max",
            effort=FixEffort.S,
            risk_if_unresolved="Reconciliation discrepancies may indicate billing inaccuracies",
            requirement_ref="2.9",
            data_path="credit_integrity — reconciliation report summary",
        )
