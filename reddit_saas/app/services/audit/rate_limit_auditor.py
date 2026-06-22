"""Audit Block 3 — RateLimitAuditor.

Verifies all external API operations route through the unified rate limit engine
by performing static AST analysis of the codebase. Identifies bypass paths and
local rate limiting patterns outside the unified engine.

Requirements: 3.1-3.13
"""

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.services.audit.base import (
    AuditBlock,
    AuditBlockName,
    FindingInput,
    FixEffort,
    Severity,
)

logger = get_logger(__name__)

# Project root (parent of app/)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = PROJECT_ROOT / "app"

# Directories to scan for external API calls
SCAN_DIRS = ["app/services", "app/tasks", "app/routes"]

# The unified rate limiter module (calls here are not bypasses)
RATE_LIMITER_MODULE = "app/services/rate_limiter.py"

# --- External API call patterns ---

# PRAW patterns: attribute calls that indicate Reddit API usage
PRAW_CALL_PATTERNS = {
    "subreddit",
    "hot",
    "new",
    "top",
    "submission",
    "comment",
    "comments",
    "redditor",
    "reply",
}

PRAW_CONSTRUCTOR_NAMES = {"Reddit"}

# httpx patterns
HTTPX_CALL_PATTERNS = {"get", "post", "put", "delete", "patch", "head", "options"}
HTTPX_MODULE_NAMES = {"httpx"}

# LiteLLM patterns
LITELLM_CALL_PATTERNS = {"completion", "acompletion", "text_completion", "embedding"}
LITELLM_MODULE_NAMES = {"litellm"}

# Rate limiter invocation patterns to check for
RATE_LIMITER_INDICATORS = {
    "is_allowed",
    "record_request",
    "rate_limiter",
    "ScrapeRateLimiter",
    "activate_backoff",
    # Wrapper functions that internally invoke the rate limiter
    "_wait_for_rate_limit",
    "_get_global_rate_limiter",
    "get_reddit_client",
    "wait_for_slot",
    "GeoRateLimiter",
}

# Local rate limiting patterns (things that look like custom throttling)
LOCAL_RATE_LIMIT_PATTERNS = {
    "time.sleep",
    "asyncio.sleep",
}


@dataclass
class ExternalCallSite:
    """Represents a detected external API call site in the codebase."""

    file_path: str
    line_number: int
    function_name: str
    call_type: str
    call_description: str
    has_rate_limit: bool
    rate_limit_source: Optional[str] = None


@dataclass
class LocalRateLimitPattern:
    """A local rate limiting pattern found outside the unified engine."""

    file_path: str
    line_number: int
    pattern: str
    context: str


@dataclass
class CoverageRow:
    """One row in the rate limit coverage report table."""

    endpoint: str
    rate_limited: bool
    limit_source: str
    bypass_possible: bool
    owner: str
    call_type: str


@dataclass
class RateLimitAuditResult:
    """Full result of the rate limit audit."""

    call_sites: list[ExternalCallSite] = field(default_factory=list)
    local_patterns: list[LocalRateLimitPattern] = field(default_factory=list)
    coverage_rows: list[CoverageRow] = field(default_factory=list)
    exemptions: dict[str, str] = field(default_factory=dict)


class _RateLimitVisitor(ast.NodeVisitor):
    """AST visitor that detects external API calls and rate limiter usage."""

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.call_sites: list[ExternalCallSite] = []
        self.local_rate_patterns: list[LocalRateLimitPattern] = []

        self._current_function: str = "<module>"
        self._current_class: Optional[str] = None
        self._function_has_rate_limiter: dict[str, bool] = {}
        self._imports: dict[str, str] = {}

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.asname or alias.name
            self._imports[name] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            name = alias.asname or alias.name
            self._imports[name] = f"{module}.{alias.name}"
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        old_class = self._current_class
        self._current_class = node.name
        self.generic_visit(node)
        self._current_class = old_class

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        old_function = self._current_function
        if self._current_class:
            func_key = f"{self._current_class}.{node.name}"
        else:
            func_key = node.name
        self._current_function = func_key

        # Track inline imports within function body
        self._collect_inline_imports(node)

        # First pass: check if this function body contains rate limiter calls
        has_rate_limiter = self._scan_for_rate_limiter(node)
        self._function_has_rate_limiter[func_key] = has_rate_limiter

        # Second pass: find external API calls
        self._scan_for_external_calls(node)

        # Also check for local rate limiting patterns
        self._scan_for_local_rate_patterns(node)

        self._current_function = old_function

    def _collect_inline_imports(self, node: ast.AST) -> None:
        """Collect import statements within function bodies (inline/lazy imports)."""
        for child in ast.walk(node):
            if isinstance(child, ast.Import):
                for alias in child.names:
                    name = alias.asname or alias.name
                    self._imports[name] = alias.name
            elif isinstance(child, ast.ImportFrom):
                module = child.module or ""
                for alias in child.names:
                    name = alias.asname or alias.name
                    self._imports[name] = f"{module}.{alias.name}"

    def _scan_for_rate_limiter(self, node: ast.AST) -> bool:
        """Check if any node in the subtree references the rate limiter."""
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                call_name = self._get_call_name(child)
                if call_name and any(
                    indicator in call_name for indicator in RATE_LIMITER_INDICATORS
                ):
                    return True
            elif isinstance(child, ast.Attribute):
                if child.attr in RATE_LIMITER_INDICATORS:
                    return True
            elif isinstance(child, ast.Name):
                if child.id in RATE_LIMITER_INDICATORS:
                    return True
        return False

    def _scan_for_external_calls(self, node: ast.AST) -> None:
        """Find external API call sites in the function body."""
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                self._check_call(child)

    def _check_call(self, node: ast.Call) -> None:
        """Check if a Call node is an external API call."""
        call_info = self._classify_call(node)
        if call_info:
            call_type, description = call_info
            func_key = self._current_function
            has_rl = self._function_has_rate_limiter.get(func_key, False)

            self.call_sites.append(
                ExternalCallSite(
                    file_path=self.file_path,
                    line_number=node.lineno,
                    function_name=func_key,
                    call_type=call_type,
                    call_description=description,
                    has_rate_limit=has_rl,
                )
            )

    def _classify_call(self, node: ast.Call) -> Optional[tuple[str, str]]:
        """Classify a call node as praw/httpx/litellm or None."""
        # Case 1: attribute call like obj.method()
        if isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr

            # Check for PRAW patterns
            if attr_name in PRAW_CALL_PATTERNS:
                value_name = self._get_value_name(node.func.value)
                # Only flag if the value looks like a reddit/praw related object
                if self._is_praw_context(value_name):
                    return ("praw", f"{value_name}.{attr_name}()")

            # Check for PRAW constructor: praw.Reddit()
            if attr_name in PRAW_CONSTRUCTOR_NAMES:
                value_name = self._get_value_name(node.func.value)
                if value_name == "praw" or self._imports.get(value_name, "") == "praw":
                    return ("praw", f"{value_name}.{attr_name}()")

            # Check for httpx patterns
            if attr_name in HTTPX_CALL_PATTERNS:
                value_name = self._get_value_name(node.func.value)
                if value_name in HTTPX_MODULE_NAMES or self._imports.get(
                    value_name, ""
                ).startswith("httpx"):
                    return ("httpx", f"{value_name}.{attr_name}()")
                # Also catch generic client.get/post calls in httpx-importing modules
                if "httpx" in self._imports or any(
                    "httpx" in v for v in self._imports.values()
                ):
                    if value_name in (
                        "client",
                        "http_client",
                        "async_client",
                        "session",
                    ):
                        return ("httpx", f"{value_name}.{attr_name}()")

            # Check for litellm patterns
            if attr_name in LITELLM_CALL_PATTERNS:
                value_name = self._get_value_name(node.func.value)
                if value_name in LITELLM_MODULE_NAMES or self._imports.get(
                    value_name, ""
                ).startswith("litellm"):
                    return ("litellm", f"{value_name}.{attr_name}()")

        # Case 2: Name call like completion() (if imported directly)
        elif isinstance(node.func, ast.Name):
            func_name = node.func.id
            import_src = self._imports.get(func_name, "")
            if "litellm" in import_src and func_name in LITELLM_CALL_PATTERNS:
                return ("litellm", f"{func_name}()")

        return None

    def _is_praw_context(self, value_name: str) -> bool:
        """Determine if a value name is likely a PRAW-related object."""
        praw_indicators = {
            "reddit",
            "subreddit",
            "submission",
            "comment",
            "redditor",
            "praw",
        }
        lower_name = value_name.lower()
        for indicator in praw_indicators:
            if indicator in lower_name:
                return True
        # Check if the module imports praw
        if "praw" in self._imports or any(
            "praw" in v for v in self._imports.values()
        ):
            # In praw-importing modules, common variable patterns
            if value_name in ("reddit", "subreddit", "sub", "r"):
                return True
        return False

    def _scan_for_local_rate_patterns(self, node: ast.AST) -> None:
        """Detect local rate limiting patterns (time.sleep, asyncio.sleep)."""
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                call_name = self._get_call_name(child)
                if call_name and any(
                    pattern in call_name for pattern in LOCAL_RATE_LIMIT_PATTERNS
                ):
                    self.local_rate_patterns.append(
                        LocalRateLimitPattern(
                            file_path=self.file_path,
                            line_number=child.lineno,
                            pattern=call_name,
                            context=f"in {self._current_function}",
                        )
                    )

    def _get_call_name(self, node: ast.Call) -> Optional[str]:
        """Get a string representation of a Call node's function."""
        if isinstance(node.func, ast.Attribute):
            value_name = self._get_value_name(node.func.value)
            return f"{value_name}.{node.func.attr}"
        elif isinstance(node.func, ast.Name):
            return node.func.id
        return None

    def _get_value_name(self, node: ast.expr) -> str:
        """Get the name of a value expression (for obj.method patterns)."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            parent = self._get_value_name(node.value)
            return f"{parent}.{node.attr}"
        elif isinstance(node, ast.Call):
            return self._get_call_name(node) or "<call>"
        return "<expr>"


class RateLimitAuditor(AuditBlock):
    """Audit Block 3: Unified Rate Limit Coverage.

    Performs static AST analysis to verify all external API call sites
    route through the unified rate limit engine. Identifies bypasses and
    local rate limiting patterns.

    Requirements: 3.1-3.13
    """

    def __init__(self, project_root: Optional[Path] = None) -> None:
        """Initialize with optional project root override (for testing).

        Args:
            project_root: Override project root path. Defaults to auto-detection.
        """
        self._project_root = project_root or PROJECT_ROOT

    @property
    def name(self) -> AuditBlockName:
        return AuditBlockName.RATE_LIMIT_COVERAGE

    async def run(self, run_id: UUID, db_session: Session) -> list[FindingInput]:
        """Execute rate limit coverage audit.

        1. Parse all files in app/services/, app/tasks/, app/routes/ using AST
        2. Identify external API call sites (PRAW, httpx, LiteLLM)
        3. Check if is_allowed() or rate limiter invocation precedes each call
        4. Scan for local rate limiting patterns outside rate_limiter.py
        5. Cross-reference with exemption registry (SystemSetting keys)
        6. Produce coverage report and findings

        Args:
            run_id: Parent AuditRun ID.
            db_session: SQLAlchemy session for querying exemptions.

        Returns:
            List of findings for bypasses and local rate limiting patterns.
        """
        logger.info("RateLimitAuditor: starting analysis (run_id=%s)", run_id)

        # 1. Load exemption registry from DB
        exemptions = self._load_exemptions(db_session)
        logger.info(
            "RateLimitAuditor: loaded %d exemptions from SystemSetting",
            len(exemptions),
        )

        # 2. Collect all Python files to scan
        files_to_scan = self._collect_files()
        logger.info("RateLimitAuditor: scanning %d files", len(files_to_scan))

        # 3. Parse each file and collect call sites + local patterns
        result = RateLimitAuditResult(exemptions=exemptions)

        for file_path in files_to_scan:
            self._analyze_file(file_path, result)

        logger.info(
            "RateLimitAuditor: found %d external call sites, %d local rate patterns",
            len(result.call_sites),
            len(result.local_patterns),
        )

        # 4. Apply exemption registry to call sites
        self._apply_exemptions(result)

        # 5. Build coverage table
        self._build_coverage_table(result)

        # 6. Generate findings for bypasses and local patterns
        findings = self._generate_findings(result)

        logger.info(
            "RateLimitAuditor: completed with %d findings (run_id=%s)",
            len(findings),
            run_id,
        )
        return findings

    def _load_exemptions(self, db_session: Session) -> dict[str, str]:
        """Load rate limit exemptions from SystemSetting table.

        Looks for keys with prefix 'rate_limit_exemption:'.

        Returns:
            Dict mapping exemption key suffix to value (justification).
        """
        from app.models.settings import SystemSetting

        try:
            settings = (
                db_session.query(SystemSetting)
                .filter(SystemSetting.key.like("rate_limit_exemption:%"))
                .all()
            )
            return {
                s.key.replace("rate_limit_exemption:", ""): s.value
                for s in settings
            }
        except Exception as exc:
            logger.warning(
                "RateLimitAuditor: failed to load exemptions: %s", str(exc)
            )
            return {}

    def _collect_files(self) -> list[str]:
        """Collect all Python files from scan directories.

        Excludes:
        - The rate_limiter.py module itself (it IS the unified engine)
        - __pycache__ directories
        - Test files

        Returns:
            List of relative file paths from project root.
        """
        files: list[str] = []
        for scan_dir in SCAN_DIRS:
            dir_path = self._project_root / scan_dir
            if not dir_path.exists():
                continue
            for root, dirs, filenames in os.walk(dir_path):
                # Skip __pycache__
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for filename in filenames:
                    if not filename.endswith(".py"):
                        continue
                    full_path = Path(root) / filename
                    rel_path = str(full_path.relative_to(self._project_root))

                    # Skip the rate limiter module itself
                    if rel_path == RATE_LIMITER_MODULE:
                        continue

                    files.append(rel_path)
        return sorted(files)

    def _analyze_file(self, file_path: str, result: RateLimitAuditResult) -> None:
        """Parse a single file and extract call sites and local patterns.

        Args:
            file_path: Relative path from project root.
            result: Accumulator for findings.
        """
        full_path = self._project_root / file_path
        try:
            source = full_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug("RateLimitAuditor: could not read %s: %s", file_path, exc)
            return

        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError as exc:
            logger.debug("RateLimitAuditor: syntax error in %s: %s", file_path, exc)
            return

        visitor = _RateLimitVisitor(file_path)
        visitor.visit(tree)

        result.call_sites.extend(visitor.call_sites)

        # Only collect local rate patterns from files outside the unified engine
        if file_path != RATE_LIMITER_MODULE:
            result.local_patterns.extend(visitor.local_rate_patterns)

    def _apply_exemptions(self, result: RateLimitAuditResult) -> None:
        """Apply exemption registry to call sites.

        If a call site's function or file path matches an exemption key,
        mark it as exempt.
        """
        for site in result.call_sites:
            if site.has_rate_limit:
                site.rate_limit_source = "unified_engine"
                continue

            # Check if file or function matches an exemption
            for exemption_key, exemption_value in result.exemptions.items():
                if (
                    exemption_key in site.file_path
                    or exemption_key in site.function_name
                    or exemption_key == f"{site.file_path}:{site.function_name}"
                ):
                    site.has_rate_limit = True
                    site.rate_limit_source = f"exemption:{exemption_key}"
                    break

    def _build_coverage_table(self, result: RateLimitAuditResult) -> None:
        """Build the coverage report table with one row per auditable path."""
        for site in result.call_sites:
            endpoint = f"{site.file_path}:{site.function_name}"
            rate_limited = site.has_rate_limit
            if site.rate_limit_source:
                limit_source = site.rate_limit_source
            else:
                limit_source = "NONE"

            bypass_possible = not rate_limited

            result.coverage_rows.append(
                CoverageRow(
                    endpoint=endpoint,
                    rate_limited=rate_limited,
                    limit_source=limit_source,
                    bypass_possible=bypass_possible,
                    owner=site.file_path,
                    call_type=site.call_type,
                )
            )

    def _generate_findings(self, result: RateLimitAuditResult) -> list[FindingInput]:
        """Generate audit findings from analysis results.

        Produces:
        - RED findings for bypass paths (external calls without rate limiting
          and no exemption)
        - YELLOW findings for local rate limiting patterns outside unified engine
        - GREEN summary finding with coverage stats
        """
        findings: list[FindingInput] = []

        # Group bypass sites by file for cleaner reporting
        bypass_sites = [s for s in result.call_sites if not s.has_rate_limit]

        # Generate findings for bypass paths (Req 3.12)
        for site in bypass_sites:
            findings.append(
                FindingInput(
                    title=f"Rate limit bypass: {site.call_description} in {site.function_name}"[:120],
                    severity=Severity.RED,
                    block=AuditBlockName.RATE_LIMIT_COVERAGE,
                    category="security",
                    risk_description=(
                        f"External API call {site.call_description} in "
                        f"{site.file_path}:{site.function_name} (line {site.line_number}) "
                        f"does not invoke the unified rate limit engine and has no "
                        f"exemption in the registry."
                    )[:500],
                    owner=site.file_path,
                    effort=FixEffort.S,
                    risk_if_unresolved=(
                        f"Uncontrolled {site.call_type} API calls may exhaust rate "
                        f"limits or incur unexpected costs."
                    )[:200],
                    requirement_ref="3.12",
                    data_path=f"{site.file_path}:{site.line_number}",
                )
            )

        # Generate findings for local rate limiting patterns (Req 3.11)
        for pattern in result.local_patterns:
            findings.append(
                FindingInput(
                    title=f"Local rate limiting: {pattern.pattern} in {pattern.context}"[:120],
                    severity=Severity.YELLOW,
                    block=AuditBlockName.RATE_LIMIT_COVERAGE,
                    category="reliability",
                    risk_description=(
                        f"Local rate limiting pattern '{pattern.pattern}' found in "
                        f"{pattern.file_path} line {pattern.line_number} "
                        f"({pattern.context}). Should use the unified rate limit "
                        f"engine instead."
                    )[:500],
                    owner=pattern.file_path,
                    effort=FixEffort.S,
                    risk_if_unresolved=(
                        "Inconsistent rate limiting across the platform; "
                        "bypass or race conditions possible."
                    )[:200],
                    requirement_ref="3.11",
                    data_path=f"{pattern.file_path}:{pattern.line_number}",
                )
            )

        # Generate summary coverage finding (Req 3.13)
        total_sites = len(result.call_sites)
        covered_sites = sum(1 for s in result.call_sites if s.has_rate_limit)
        bypass_count = total_sites - covered_sites
        coverage_pct = (covered_sites / total_sites * 100) if total_sites > 0 else 100

        if bypass_count == 0:
            severity = Severity.GREEN
        elif bypass_count <= 3:
            severity = Severity.YELLOW
        else:
            severity = Severity.RED

        findings.append(
            FindingInput(
                title=f"Rate limit coverage: {coverage_pct:.0f}% ({covered_sites}/{total_sites} paths)"[:120],
                severity=severity,
                block=AuditBlockName.RATE_LIMIT_COVERAGE,
                category="security",
                risk_description=(
                    f"Rate limit coverage report: {total_sites} external API call "
                    f"sites detected, {covered_sites} are rate-limited, "
                    f"{bypass_count} bypass paths found, "
                    f"{len(result.local_patterns)} local rate patterns detected, "
                    f"{len(result.exemptions)} exemptions registered."
                )[:500],
                owner="platform",
                effort=FixEffort.M if bypass_count > 0 else FixEffort.S,
                risk_if_unresolved=(
                    "Incomplete rate limit coverage allows uncontrolled API usage "
                    "that may cause service disruptions."
                    if bypass_count > 0
                    else "All external API calls are rate-limited."
                )[:200],
                requirement_ref="3.13",
                data_path="rate_limit_coverage_table",
            )
        )

        return findings
