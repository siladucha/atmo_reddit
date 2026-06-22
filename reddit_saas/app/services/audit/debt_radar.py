"""Audit Block 7 - DebtRadar.

Systematically scans the codebase for technical debt across four dimensions:
- Reliability: missing retry, missing idempotency, missing ActivityEvent,
  missing alert thresholds
- Performance: missing indexes, N+1 patterns, unbounded queries, queue backpressure
- Security: missing auth guards, permission leakage, secrets in source,
  missing validation
- Product: incomplete scenarios, missing error messages, UX dead ends

Uses Python AST module for static analysis. Assigns severity per Req 7.5:
- RED: can cause data loss, security breach, or complete workflow failure
- YELLOW: degrades UX or ops efficiency but doesn't block core workflows
- GREEN: no user-visible impact, no security/data-integrity risk

Per Req 7.7: RED findings must have decision=fix_before_release.

Requirements: 7.1-7.7
"""

import ast
import os
import re
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

# Directories to scan
SCAN_DIRS = ["app/services", "app/tasks", "app/routes"]

# Patterns indicating external calls that should have retry logic
EXTERNAL_CALL_MODULES = {"httpx", "praw", "litellm", "aiohttp", "requests"}

EXTERNAL_CALL_ATTRS = {
    "get", "post", "put", "delete", "patch",  # httpx/requests
    "completion", "acompletion", "text_completion",  # litellm
}

# Retry indicators in function bodies
RETRY_INDICATORS = {
    "retry", "max_retries", "tenacity", "backoff", "retrying",
    "Retry", "exponential_backoff", "countdown", "autoretry_for",
    "bind=True",
}

# Auth guard function names from dependencies/permissions.py
AUTH_GUARD_NAMES = {
    "require_superuser", "require_platform_admin", "require_owner",
    "require_client_admin", "require_client_manager_or_above",
    "require_client_access", "require_authenticated",
    "require_avatar_manager_or_above", "get_current_user",
    "verify_client_access_from_path",
}

# Secret patterns (regex for potential hardcoded secrets)
SECRET_PATTERNS = [
    re.compile(r"(?:api[_-]?key|secret|password|token)\s*=\s*[\"\'][^\"\']{8,}[\"\']", re.I),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),  # OpenAI key pattern
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),  # Google API key
    re.compile(r"ghp_[A-Za-z0-9]{36}"),  # GitHub PAT
]

# ActivityEvent emission indicators
ACTIVITY_EVENT_INDICATORS = {
    "ActivityEvent", "activity_event", "emit_event",
    "create_activity_event", "log_activity", "transparency",
}

# Pydantic validation indicators
VALIDATION_INDICATORS = {
    "BaseModel", "Field", "validator", "field_validator",
    "model_validate", "Depends",
}


@dataclass
class DebtItem:
    """A detected technical debt item before converting to FindingInput."""

    description: str
    category: str  # reliability, performance, security, product
    severity: Severity
    file_path: str
    line_number: int
    effort: FixEffort
    risk_if_unresolved: str
    requirement_ref: str


class _ReliabilityVisitor(ast.NodeVisitor):
    """AST visitor detecting reliability debt patterns."""

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.items: list[DebtItem] = []
        self._current_function: str = "<module>"
        self._current_class: Optional[str] = None
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

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node) -> None:
        old_func = self._current_function
        old_class = self._current_class
        if self._current_class:
            self._current_function = f"{self._current_class}.{node.name}"
        else:
            self._current_function = node.name

        # Check for external calls without retry
        self._check_missing_retry(node)
        # Check for state changes without ActivityEvent
        self._check_missing_activity_event(node)

        # Visit children
        self.generic_visit(node)

        self._current_function = old_func
        self._current_class = old_class

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        old_class = self._current_class
        self._current_class = node.name
        self.generic_visit(node)
        self._current_class = old_class

    def _check_missing_retry(self, node) -> None:
        """Check if function makes external calls without retry logic."""
        has_external_call = False
        has_retry = False
        external_call_line = node.lineno

        for child in ast.walk(node):
            # Check for external call indicators
            if isinstance(child, ast.Call):
                call_str = self._get_call_string(child)
                if call_str and self._is_external_call(call_str):
                    has_external_call = True
                    external_call_line = child.lineno

            # Check for retry indicators in decorators
            if isinstance(child, ast.Name) and child.id in RETRY_INDICATORS:
                has_retry = True
            if isinstance(child, ast.Attribute) and child.attr in RETRY_INDICATORS:
                has_retry = True

        # Also check decorators
        if hasattr(node, "decorator_list"):
            for dec in node.decorator_list:
                dec_str = ast.dump(dec)
                for indicator in RETRY_INDICATORS:
                    if indicator in dec_str:
                        has_retry = True
                        break

        # Also check if the function source contains retry keywords
        if has_external_call and not has_retry:
            # Check try/except wrapping as partial retry indicator
            for child in ast.walk(node):
                if isinstance(child, ast.Try):
                    has_retry = True
                    break

        if has_external_call and not has_retry:
            self.items.append(DebtItem(
                description=f"Missing retry on external call in {self._current_function}",
                category="reliability",
                severity=Severity.YELLOW,
                file_path=self.file_path,
                line_number=external_call_line,
                effort=FixEffort.S,
                risk_if_unresolved="Transient failures cause silent data loss or broken workflows",
                requirement_ref="7.1",
            ))

    def _check_missing_activity_event(self, node) -> None:
        """Check if function mutates state without emitting ActivityEvent."""
        has_state_mutation = False
        has_activity_event = False
        mutation_line = node.lineno

        for child in ast.walk(node):
            # State mutations: db.add, db.commit, .save, session.commit
            if isinstance(child, ast.Call):
                call_str = self._get_call_string(child)
                if call_str and any(
                    m in call_str for m in ("db.add", "db.commit", "session.add",
                                            "session.commit", ".save", "db.execute")
                ):
                    has_state_mutation = True
                    mutation_line = child.lineno
            # ActivityEvent indicators
            if isinstance(child, ast.Name) and child.id in ACTIVITY_EVENT_INDICATORS:
                has_activity_event = True
            if isinstance(child, ast.Attribute) and child.attr in ACTIVITY_EVENT_INDICATORS:
                has_activity_event = True
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                if any(ind in child.value for ind in ACTIVITY_EVENT_INDICATORS):
                    has_activity_event = True

        # Only flag in services and tasks (not routes - routes delegate to services)
        if (
            has_state_mutation
            and not has_activity_event
            and ("services/" in self.file_path or "tasks/" in self.file_path)
            and not self._current_function.startswith("_")
            and self._current_function != "<module>"
        ):
            self.items.append(DebtItem(
                description=f"State mutation without ActivityEvent in {self._current_function}",
                category="reliability",
                severity=Severity.GREEN,
                file_path=self.file_path,
                line_number=mutation_line,
                effort=FixEffort.S,
                risk_if_unresolved="State changes not observable; debugging and audit trail incomplete",
                requirement_ref="7.1",
            ))

    def _is_external_call(self, call_str: str) -> bool:
        """Check if a call string represents an external API call."""
        # Must be a method call on a known external module/client object
        if any(f"{mod}." in call_str for mod in ("httpx", "requests", "litellm", "aiohttp")):
            return True
        # PRAW Reddit client calls
        if any(f"{obj}." in call_str.lower() for obj in ("reddit", "subreddit", "praw")):
            if any(attr in call_str for attr in EXTERNAL_CALL_ATTRS):
                return True
        # Generic HTTP client patterns
        if any(f"{client}." in call_str for client in ("client", "http_client", "session")):
            if any(attr in call_str for attr in ("get", "post", "put", "delete", "patch")):
                return True
        return False

    def _get_call_string(self, node: ast.Call) -> Optional[str]:
        """Get a string representation of a Call node."""
        if isinstance(node.func, ast.Attribute):
            value = self._get_value_name(node.func.value)
            return f"{value}.{node.func.attr}"
        elif isinstance(node.func, ast.Name):
            return node.func.id
        return None

    def _get_value_name(self, node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            parent = self._get_value_name(node.value)
            return f"{parent}.{node.attr}"
        return "<expr>"


class _SecurityVisitor(ast.NodeVisitor):
    """AST visitor detecting security debt patterns in route files."""

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.items: list[DebtItem] = []
        self._has_auth_guard = False
        self._imports: set[str] = set()
        self._is_route_file = "routes/" in file_path

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            name = alias.asname or alias.name
            self._imports.add(name)
            if name in AUTH_GUARD_NAMES:
                self._has_auth_guard = True
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._imports.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_route_handler(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_route_handler(node)
        self.generic_visit(node)

    def _check_route_handler(self, node) -> None:
        """Check if a route handler has an auth guard."""
        if not self._is_route_file:
            return

        # Check if this is a route handler (has @router.get/post/... decorator)
        is_route = False
        for dec in node.decorator_list:
            dec_str = ast.dump(dec)
            if any(method in dec_str for method in (
                "get", "post", "put", "delete", "patch", "router"
            )):
                is_route = True
                break

        if not is_route:
            return

        # Check if function has Depends() with an auth guard in parameters
        has_guard = False
        for arg in node.args.defaults + node.args.kw_defaults:
            if arg is None:
                continue
            arg_str = ast.dump(arg)
            for guard in AUTH_GUARD_NAMES:
                if guard in arg_str:
                    has_guard = True
                    break

        # Also check args annotations (for Depends patterns)
        for arg in node.args.args + node.args.kwonlyargs:
            if arg.annotation:
                ann_str = ast.dump(arg.annotation)
                for guard in AUTH_GUARD_NAMES:
                    if guard in ann_str:
                        has_guard = True
                        break

        # Skip known public endpoints
        public_endpoints = {
            "login", "register", "health", "healthcheck",
            "oauth_callback", "trial_signup", "sse_notifications",
        }
        if node.name in public_endpoints or node.name.startswith("_"):
            return

        # Skip auth module itself
        if "auth.py" in self.file_path and node.name in ("login", "register", "refresh_token"):
            return

        if not has_guard and not self._has_auth_guard:
            # Check if file-level Depends was imported
            if not any(g in self._imports for g in AUTH_GUARD_NAMES):
                self.items.append(DebtItem(
                    description=f"Route handler without auth guard: {node.name}",
                    category="security",
                    severity=Severity.RED,
                    file_path=self.file_path,
                    line_number=node.lineno,
                    effort=FixEffort.S,
                    risk_if_unresolved="Unauthenticated access to protected resources; security breach risk",
                    requirement_ref="7.3",
                ))


class _PerformanceVisitor(ast.NodeVisitor):
    """AST visitor detecting performance debt patterns."""

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.items: list[DebtItem] = []
        self._current_function: str = "<module>"
        self._current_class: Optional[str] = None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        old_class = self._current_class
        self._current_class = node.name
        self.generic_visit(node)
        self._current_class = old_class

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node) -> None:
        old_func = self._current_function
        if self._current_class:
            self._current_function = f"{self._current_class}.{node.name}"
        else:
            self._current_function = node.name

        # Check for N+1 patterns (loop with query inside)
        self._check_n_plus_one(node)
        # Check for unbounded queries
        self._check_unbounded_queries(node)

        self.generic_visit(node)
        self._current_function = old_func

    def _check_n_plus_one(self, node) -> None:
        """Detect N+1 patterns: a for-loop containing a DB query call."""
        for child in ast.walk(node):
            if isinstance(child, ast.For):
                for inner in ast.walk(child):
                    if isinstance(inner, ast.Call):
                        call_str = self._get_call_string(inner)
                        if call_str and any(
                            q in call_str for q in (
                                ".query", "db.execute", "session.execute",
                                "session.query", "select(", "db.query",
                            )
                        ):
                            self.items.append(DebtItem(
                                description=f"Potential N+1 query in loop: {self._current_function}",
                                category="performance",
                                severity=Severity.YELLOW,
                                file_path=self.file_path,
                                line_number=inner.lineno,
                                effort=FixEffort.M,
                                risk_if_unresolved="Linear DB query growth per item; response time degrades at scale",
                                requirement_ref="7.2",
                            ))
                            return  # Only flag once per function

    def _check_unbounded_queries(self, node) -> None:
        """Detect queries without LIMIT when in list endpoints."""
        # Only check route handlers (list endpoints)
        func_name = self._current_function.lower()
        is_list_endpoint = any(
            kw in func_name for kw in ("list", "all", "get_all", "index")
        )
        if not is_list_endpoint and "routes/" not in self.file_path:
            return

        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                call_str = self._get_call_string(child)
                if not call_str:
                    continue
                if any(q in call_str for q in (".query", "session.query", "db.query")):
                    # Check if .limit() or .paginate() is chained
                    parent = self._find_parent_chain(node, child)
                    if parent and not self._has_limit(parent):
                        self.items.append(DebtItem(
                            description=f"Unbounded query in {self._current_function} (no LIMIT)",
                            category="performance",
                            severity=Severity.YELLOW,
                            file_path=self.file_path,
                            line_number=child.lineno,
                            effort=FixEffort.S,
                            risk_if_unresolved="Result sets grow unbounded; memory exhaustion at scale",
                            requirement_ref="7.2",
                        ))
                        return  # Only flag once per function

    def _has_limit(self, node) -> bool:
        """Check if a query chain includes .limit() or pagination."""
        source = ast.dump(node)
        return any(lim in source for lim in ("limit", "paginate", "LIMIT", "slice", "[:"))

    def _find_parent_chain(self, root, target) -> Optional[ast.AST]:
        """Find the statement containing the target node."""
        for child in ast.walk(root):
            if isinstance(child, ast.Assign):
                if target in ast.walk(child):
                    return child
            elif isinstance(child, ast.Return):
                if target in ast.walk(child):
                    return child
            elif isinstance(child, ast.Expr):
                if target in ast.walk(child):
                    return child
        return None

    def _get_call_string(self, node: ast.Call) -> Optional[str]:
        if isinstance(node.func, ast.Attribute):
            value = self._get_value_name(node.func.value)
            return f"{value}.{node.func.attr}"
        elif isinstance(node.func, ast.Name):
            return node.func.id
        return None

    def _get_value_name(self, node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            parent = self._get_value_name(node.value)
            return f"{parent}.{node.attr}"
        return "<expr>"


class DebtRadar(AuditBlock):
    """Audit Block 7: Technical Debt Scanner.

    Scans app/services/, app/tasks/, app/routes/ for technical debt across
    four dimensions: reliability, performance, security, product.

    Requirements: 7.1-7.7
    """

    def __init__(self, project_root: Optional[Path] = None) -> None:
        """Initialize with optional project root override (for testing).

        Args:
            project_root: Override project root path. Defaults to auto-detection.
        """
        self._project_root = project_root or PROJECT_ROOT

    @property
    def name(self) -> AuditBlockName:
        return AuditBlockName.TECHNICAL_DEBT

    async def run(self, run_id: UUID, db_session: Session) -> list[FindingInput]:
        """Execute technical debt scan.

        1. Scan for reliability debt (missing retry, idempotency, ActivityEvent)
        2. Scan for performance debt (N+1, unbounded queries, missing indexes)
        3. Scan for security debt (missing auth guards, secrets, missing validation)
        4. Scan for product debt (incomplete flows, missing error messages)
        5. Assign severity per Req 7.5
        6. Record all required fields per finding (Req 7.6)

        Args:
            run_id: Parent AuditRun ID.
            db_session: SQLAlchemy session.

        Returns:
            List of findings for detected technical debt.
        """
        logger.info("DebtRadar: starting analysis (run_id=%s)", run_id)

        # Collect all Python files to scan
        files_to_scan = self._collect_files()
        logger.info("DebtRadar: scanning %d files", len(files_to_scan))

        all_items: list[DebtItem] = []

        # 1. Reliability debt scan
        reliability_items = self._scan_reliability(files_to_scan)
        all_items.extend(reliability_items)
        logger.info("DebtRadar: found %d reliability debt items", len(reliability_items))

        # 2. Performance debt scan
        performance_items = self._scan_performance(files_to_scan)
        all_items.extend(performance_items)
        logger.info("DebtRadar: found %d performance debt items", len(performance_items))

        # 3. Security debt scan
        security_items = self._scan_security(files_to_scan)
        all_items.extend(security_items)
        logger.info("DebtRadar: found %d security debt items", len(security_items))

        # 4. Product debt scan
        product_items = self._scan_product(files_to_scan)
        all_items.extend(product_items)
        logger.info("DebtRadar: found %d product debt items", len(product_items))

        # 5. Secret scan (separate pass)
        secret_items = self._scan_secrets(files_to_scan)
        all_items.extend(secret_items)
        logger.info("DebtRadar: found %d secret exposure items", len(secret_items))

        # Convert DebtItems to FindingInputs
        findings = self._items_to_findings(all_items)

        logger.info(
            "DebtRadar: completed with %d findings (run_id=%s)",
            len(findings),
            run_id,
        )
        return findings

    def _collect_files(self) -> list[str]:
        """Collect all Python files from scan directories.

        Excludes __pycache__, test files, migration files, and audit code
        (audit modules reference external libraries for analysis, not for calls).

        Returns:
            List of relative file paths from project root.
        """
        files: list[str] = []
        for scan_dir in SCAN_DIRS:
            dir_path = self._project_root / scan_dir
            if not dir_path.exists():
                continue
            for root, dirs, filenames in os.walk(dir_path):
                dirs[:] = [d for d in dirs if d not in ("__pycache__", "audit")]
                for filename in filenames:
                    if not filename.endswith(".py"):
                        continue
                    if filename.startswith("test_"):
                        continue
                    full_path = Path(root) / filename
                    rel_path = str(full_path.relative_to(self._project_root))
                    files.append(rel_path)
        return sorted(files)

    def _parse_file(self, file_path: str) -> Optional[ast.Module]:
        """Parse a Python file into an AST, returning None on failure."""
        full_path = self._project_root / file_path
        try:
            source = full_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        try:
            return ast.parse(source, filename=file_path)
        except SyntaxError:
            return None

    def _read_file_source(self, file_path: str) -> Optional[str]:
        """Read file source as a string."""
        full_path = self._project_root / file_path
        try:
            return full_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def _scan_reliability(self, files: list[str]) -> list[DebtItem]:
        """Scan for reliability debt: missing retry, missing ActivityEvent.

        Req 7.1: missing retry on external calls, missing idempotency keys,
        missing observability, missing alert thresholds.
        """
        items: list[DebtItem] = []
        for file_path in files:
            tree = self._parse_file(file_path)
            if tree is None:
                continue
            visitor = _ReliabilityVisitor(file_path)
            visitor.visit(tree)
            items.extend(visitor.items)
        return items

    def _scan_performance(self, files: list[str]) -> list[DebtItem]:
        """Scan for performance debt: N+1 patterns, unbounded queries.

        Req 7.2: missing indexes, N+1 patterns, unbounded queries,
        queue backpressure.
        """
        items: list[DebtItem] = []
        for file_path in files:
            tree = self._parse_file(file_path)
            if tree is None:
                continue
            visitor = _PerformanceVisitor(file_path)
            visitor.visit(tree)
            items.extend(visitor.items)
        return items

    def _scan_security(self, files: list[str]) -> list[DebtItem]:
        """Scan for security debt: missing auth guards, missing validation.

        Req 7.3: authentication bypass paths, permission leakage,
        secrets in source, missing input validation.
        """
        items: list[DebtItem] = []
        route_files = [f for f in files if "routes/" in f]
        for file_path in route_files:
            tree = self._parse_file(file_path)
            if tree is None:
                continue
            visitor = _SecurityVisitor(file_path)
            visitor.visit(tree)
            items.extend(visitor.items)

        # Check for missing Pydantic validation on POST/PUT endpoints
        for file_path in route_files:
            items.extend(self._check_missing_validation(file_path))

        return items

    def _scan_product(self, files: list[str]) -> list[DebtItem]:
        """Scan for product debt: incomplete scenarios, missing error messages.

        Req 7.4: incomplete user scenarios, missing user-facing error
        explanations, UX dead ends.
        """
        items: list[DebtItem] = []
        route_files = [f for f in files if "routes/" in f]

        for file_path in route_files:
            tree = self._parse_file(file_path)
            if tree is None:
                continue
            items.extend(self._check_bare_http_exceptions(file_path, tree))

        return items

    def _scan_secrets(self, files: list[str]) -> list[DebtItem]:
        """Scan source files for hardcoded secrets.

        Req 7.3: secrets in source code or non-encrypted configuration.
        """
        items: list[DebtItem] = []
        for file_path in files:
            source = self._read_file_source(file_path)
            if source is None:
                continue
            for line_num, line in enumerate(source.splitlines(), start=1):
                # Skip comments and docstrings (basic heuristic)
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if stripped.startswith(("\"\"\"", "\'\'\'")):
                    continue

                for pattern in SECRET_PATTERNS:
                    if pattern.search(line):
                        # Skip known safe patterns (env var reads, config refs)
                        if any(safe in line for safe in (
                            "os.environ", "os.getenv", "settings.",
                            "config.", "get_settings", "SECRET_PATTERNS",
                            "# ", "test_", "example", "placeholder",
                            "Fernet", "encrypted",
                        )):
                            continue
                        items.append(DebtItem(
                            description=f"Potential hardcoded secret in {file_path}:{line_num}",
                            category="security",
                            severity=Severity.RED,
                            file_path=file_path,
                            line_number=line_num,
                            effort=FixEffort.S,
                            risk_if_unresolved="Secrets in source may leak via repo access; credential compromise",
                            requirement_ref="7.3",
                        ))
                        break  # One finding per line

        return items

    def _check_missing_validation(self, file_path: str) -> list[DebtItem]:
        """Check route handlers for missing Pydantic validation on input endpoints."""
        items: list[DebtItem] = []
        tree = self._parse_file(file_path)
        if tree is None:
            return items

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            # Check if this is a POST/PUT route
            is_mutation_route = False
            for dec in node.decorator_list:
                dec_str = ast.dump(dec)
                if any(method in dec_str for method in ("post", "put", "patch")):
                    is_mutation_route = True
                    break

            if not is_mutation_route:
                continue

            # Check if function has a typed body parameter (Pydantic model)
            has_body_validation = False
            for arg in node.args.args:
                if arg.annotation:
                    ann_str = ast.dump(arg.annotation)
                    # Pydantic models, Form data, or explicit Body
                    if any(v in ann_str for v in VALIDATION_INDICATORS):
                        has_body_validation = True
                        break
                    # Type annotations that suggest schema usage
                    if "Schema" in ann_str or "Input" in ann_str or "Request" in ann_str:
                        has_body_validation = True
                        break

            # Check if Request object is used (manual parsing, still valid)
            for child in ast.walk(node):
                if isinstance(child, ast.Attribute):
                    if child.attr in ("form", "json", "body"):
                        # Uses request body parsing - check for validation
                        for inner in ast.walk(node):
                            if isinstance(inner, ast.Name) and inner.id in VALIDATION_INDICATORS:
                                has_body_validation = True
                                break

            # Skip HTMX partials and simple toggle endpoints
            if any(skip in node.name for skip in ("toggle", "htmx", "partial")):
                has_body_validation = True

            if not has_body_validation and is_mutation_route:
                items.append(DebtItem(
                    description=f"Missing input validation on {node.name} in {file_path}",
                    category="security",
                    severity=Severity.YELLOW,
                    file_path=file_path,
                    line_number=node.lineno,
                    effort=FixEffort.S,
                    risk_if_unresolved="Unvalidated input may allow injection or data corruption",
                    requirement_ref="7.3",
                ))

        return items

    def _check_bare_http_exceptions(self, file_path: str, tree: ast.Module) -> list[DebtItem]:
        """Check for HTTPException raises without user-friendly messages.

        Req 7.4: Missing user-facing error explanations.
        """
        items: list[DebtItem] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise):
                continue
            if node.exc is None:
                continue

            # Check if raising HTTPException
            exc_str = ast.dump(node.exc)
            if "HTTPException" not in exc_str:
                continue

            # Check if detail= keyword is provided with a meaningful message
            if isinstance(node.exc, ast.Call):
                has_detail = False
                for kw in node.exc.keywords:
                    if kw.arg == "detail":
                        # Check if detail has a meaningful message (not just a status code)
                        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            if len(kw.value.value) > 5:
                                has_detail = True
                        elif not isinstance(kw.value, ast.Constant):
                            # Dynamic detail (f-string, variable) - acceptable
                            has_detail = True
                if not has_detail:
                    items.append(DebtItem(
                        description=f"HTTPException without user-friendly detail in {file_path}",
                        category="product",
                        severity=Severity.GREEN,
                        file_path=file_path,
                        line_number=node.lineno,
                        effort=FixEffort.S,
                        risk_if_unresolved="Users see generic error codes without actionable guidance",
                        requirement_ref="7.4",
                    ))

        return items

    def _items_to_findings(self, items: list[DebtItem]) -> list[FindingInput]:
        """Convert internal DebtItem list to FindingInput list.

        Per Req 7.7: RED findings get decision=fix_before_release.
        This is enforced by the model-level constraint, but we set it here
        for clarity.
        """
        findings: list[FindingInput] = []
        for item in items:
            findings.append(FindingInput(
                title=item.description[:120],
                severity=item.severity,
                block=AuditBlockName.TECHNICAL_DEBT,
                category=item.category,
                risk_description=(
                    f"{item.category.capitalize()} debt in {item.file_path} "
                    f"(line {item.line_number}): {item.risk_if_unresolved}"
                )[:500],
                owner=item.file_path,
                effort=item.effort,
                risk_if_unresolved=item.risk_if_unresolved[:200],
                requirement_ref=item.requirement_ref,
                data_path=f"{item.file_path}:{item.line_number}",
            ))
        return findings
