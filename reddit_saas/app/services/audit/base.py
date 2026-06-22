"""AuditBlock abstract base class and shared types for the Production Readiness Audit."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from uuid import UUID


class Severity(str, Enum):
    """Traffic-light severity for audit findings."""

    RED = "red"
    YELLOW = "yellow"
    GREEN = "green"


class Decision(str, Enum):
    """Resolution decision for an audit finding."""

    FIX_BEFORE_RELEASE = "fix_before_release"
    DEFER_TO_POST_RELEASE = "defer_to_post_release"
    ACCEPT = "accept"


class FixEffort(str, Enum):
    """Estimated effort to resolve a finding."""

    S = "S"    # 1-4 hours
    M = "M"    # 4-16 hours
    L = "L"    # 16-40 hours
    XL = "XL"  # 40+ hours


class AuditBlockName(str, Enum):
    """Names of all 8 audit blocks."""

    DATA_LEAKAGE = "data_leakage"
    CREDIT_INTEGRITY = "credit_integrity"
    RATE_LIMIT_COVERAGE = "rate_limit_coverage"
    LLM_RELIABILITY = "llm_reliability"
    FLOW_COMPLETENESS = "flow_completeness"
    SPEC_COVERAGE = "spec_coverage"
    TECHNICAL_DEBT = "technical_debt"
    BYPASS_DETECTION = "bypass_detection"


class BlockStatus(str, Enum):
    """Execution status of an audit block."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class FindingInput:
    """Data required to create an audit finding."""

    title: str                         # max 120 chars
    severity: Severity
    block: AuditBlockName
    category: str                      # e.g. "reliability", "security"
    risk_description: str              # max 500 chars
    owner: str                         # assigned person/team
    effort: FixEffort
    risk_if_unresolved: str            # max 200 chars
    requirement_ref: str               # e.g. "1.2", "7.3"
    data_path: Optional[str] = None    # where violation occurred
    eta: Optional[str] = None          # YYYY-MM-DD or None


class AuditBlock(ABC):
    """Interface all audit blocks must implement."""

    @property
    @abstractmethod
    def name(self) -> AuditBlockName:
        """The block's identifier."""
        ...

    @abstractmethod
    async def run(self, run_id: UUID, db_session) -> list[FindingInput]:
        """Execute the audit block and return findings.

        Args:
            run_id: The parent AuditRun ID.
            db_session: SQLAlchemy async session.

        Returns:
            List of findings to persist.
        """
        ...
