"""Audit Block 8 — BypassDetector.

Identifies bypass paths in the system where operations may circumvent safety
gates, rate limits, or access controls through non-standard channels.

Checks:
1. Celery Beat tasks that modify CommentDraft/PostDraft/PostingEvent — verify
   they invoke all 9 posting safety gates from posting_safety.py
2. Routes missing require_superuser/require_platform_admin dependencies
3. _*.py scripts in project root for direct DB writes without Pydantic validation
4. Admin CRUD routes produce AuditLog entries
5. Feature flags have valid description + boolean value
6. Alembic scripts with UPDATE/DELETE have downgrade functions

Requirements: 8.1-8.10
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
# Project root scripts are at ../_*.py relative to reddit_saas/
SCRIPTS_ROOT = PROJECT_ROOT.parent

# The 9 posting safety gates from posting_safety.py
POSTING_SAFETY_GATES = [
    "kill_switch",
    "posting_mode",
    "frozen",
    "health_status",
    "phase_exclusion",
    "daily_cap",
    "proxy_configured",
    "user_agent_configured",
    "subnet_consistency",
]

# Indicators that check_posting_safety is invoked
SAFETY_GATE_INDICATORS = {
    "check_posting_safety",
    "posting_safety",
    "SafetyResult",
}

# Models that indicate posting-related modifications
POSTING_MODELS = {"CommentDraft", "PostDraft", "PostingEvent"}

# Admin auth dependency names
ADMIN_AUTH_DEPS = {
    "require_superuser",
    "require_platform_admin",
    "require_owner",
}

# Pydantic validation indicators
PYDANTIC_INDICATORS = {
    "BaseModel",
    "model_validate",
    "parse_obj",
    ".model_dump",
    "Field(",
    "validator",
}

# DB write indicators
DB_WRITE_INDICATORS = {
    "db.add",
    "db.execute",
    "session.add",
    "session.execute",
    ".add(",
    ".commit()",
    ".bulk_save_objects",
    ".merge(",
    "INSERT",
    "UPDATE",
}


@dataclass
class CeleryTaskBypass:
    """A Celery task that modifies posting-related models."""
    file_path: str
    task_name: str
    models_modified: list[str]
    has_safety_gates: bool
    missing_gates: list[str] = field(default_factory=list)


@dataclass
class RouteBypass:
    """A route missing admin auth dependencies."""
    file_path: str
    line_number: int
    route_path: str
    function_name: str
    has_auth: bool
    auth_type: Optional[str] = None


@dataclass
class ScriptBypass:
    """A root script with direct DB writes without Pydantic validation."""
    file_path: str
    has_db_writes: bool
    has_pydantic: bool
    db_write_lines: list[int] = field(default_factory=list)


@dataclass
class AdminCrudBypass:
    """An admin CRUD route missing AuditLog entry."""
    file_path: str
    line_number: int
    function_name: str
    operation: str  # create/update/delete
    has_audit_log: bool


@dataclass
class FeatureFlagIssue:
    """A feature flag with invalid description or value."""
    key: str
    value: Optional[str]
    description: Optional[str]
    issue: str  # "missing_description" | "invalid_value"


@dataclass
class AlembicBypass:
    """An Alembic migration with UPDATE/DELETE but no downgrade."""
    file_path: str
    has_data_modification: bool
    has_downgrade: bool
    modification_type: str  # "UPDATE" | "DELETE"


class BypassDetector(AuditBlock):
    """Audit Block 8: Bypass Path Detection.

    Identifies operations that circumvent safety gates, access controls,
    or validation through non-standard channels.

    Requirements: 8.1-8.10
    """

    def __init__(self, project_root: Optional[Path] = None) -> None:
        """Initialize with optional project root override (for testing)."""
        self._project_root = project_root or PROJECT_ROOT
        self._app_root = self._project_root / "app"
        self._scripts_root = self._project_root.parent

    @property
    def name(self) -> AuditBlockName:
        return AuditBlockName.BYPASS_DETECTION

    async def run(self, run_id: UUID, db_session: Session) -> list[FindingInput]:
        """Execute bypass detection audit.

        1. Identify Celery Beat tasks modifying posting models
        2. Verify safety gate invocations
        3. Scan routes for missing auth dependencies
        4. Check root scripts for direct DB writes
        5. Verify admin CRUD audit logging
        6. Check feature flags validity
        7. Scan Alembic migrations for UPDATE/DELETE without downgrade

        Args:
            run_id: Parent AuditRun ID.
            db_session: SQLAlchemy session.

        Returns:
            List of findings for bypass paths detected.
        """
        logger.info("BypassDetector: starting analysis (run_id=%s)", run_id)

        findings: list[FindingInput] = []

        # 1. Check Celery tasks that modify posting models (Req 8.1, 8.7)
        task_findings = self._check_celery_task_safety_gates()
        findings.extend(task_findings)

        # 2. Scan routes for missing auth (Req 8.2)
        route_findings = self._check_route_auth_dependencies()
        findings.extend(route_findings)

        # 3. Check root scripts for direct DB writes (Req 8.3)
        script_findings = self._check_root_scripts()
        findings.extend(script_findings)

        # 4. Verify admin CRUD audit logging (Req 8.4)
        crud_findings = self._check_admin_crud_audit_logs()
        findings.extend(crud_findings)

        # 5. Check feature flags (Req 8.5)
        flag_findings = self._check_feature_flags(db_session)
        findings.extend(flag_findings)

        # 6. Scan Alembic migrations (Req 8.6)
        alembic_findings = self._check_alembic_migrations()
        findings.extend(alembic_findings)

        logger.info(
            "BypassDetector: completed with %d findings (run_id=%s)",
            len(findings), run_id,
        )
        return findings

    # ------------------------------------------------------------------
    # Check 1: Celery tasks with posting model modifications (Req 8.1, 8.7)
    # ------------------------------------------------------------------

    def _check_celery_task_safety_gates(self) -> list[FindingInput]:
        """Check that Celery tasks modifying posting models invoke safety gates.

        Scans app/tasks/ for tasks that import/reference CommentDraft, PostDraft,
        or PostingEvent and verifies they call check_posting_safety or delegate
        to a service that does.

        Returns:
            Findings for tasks missing safety gate invocations.
        """
        findings: list[FindingInput] = []
        tasks_dir = self._app_root / "tasks"

        if not tasks_dir.exists():
            return findings

        for py_file in sorted(tasks_dir.glob("*.py")):
            if py_file.name.startswith("__"):
                continue

            try:
                source = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            # Check if this file references posting-related models
            models_referenced = []
            for model in POSTING_MODELS:
                if model in source:
                    models_referenced.append(model)

            if not models_referenced:
                continue

            # Check if the file modifies these models (writes, not just reads)
            has_modification = self._file_modifies_posting_models(source)
            if not has_modification:
                continue

            # Check if safety gates are invoked
            has_safety = any(
                indicator in source for indicator in SAFETY_GATE_INDICATORS
            )

            # Also check if it delegates to posting service (which has gates)
            delegates_to_posting_service = (
                "execute_post" in source
                or "from app.services.posting" in source
            )

            if not has_safety and not delegates_to_posting_service:
                rel_path = str(py_file.relative_to(self._project_root))
                findings.append(
                    FindingInput(
                        title=f"Celery task modifies posting models without safety gates: {py_file.name}"[:120],
                        severity=Severity.RED,
                        block=AuditBlockName.BYPASS_DETECTION,
                        category="security",
                        risk_description=(
                            f"Task file {rel_path} references {models_referenced} "
                            f"and performs modifications but does not invoke "
                            f"check_posting_safety() or delegate to posting service. "
                            f"Posting operations may bypass safety gates."
                        )[:500],
                        owner=rel_path,
                        effort=FixEffort.M,
                        risk_if_unresolved=(
                            "Automated posting tasks could bypass safety gates, "
                            "leading to posts from frozen/banned avatars or exceeding daily caps."
                        )[:200],
                        requirement_ref="8.1",
                        data_path=rel_path,
                    )
                )

        return findings

    def _file_modifies_posting_models(self, source: str) -> bool:
        """Check if source code modifies posting-related models (not just reads)."""
        modification_patterns = [
            r"\.status\s*=",      # draft.status = "posted"
            r"db\.add\(",         # db.add(posting_event)
            r"db\.commit\(",      # commits after model changes
            r"\.outcome\s*=",     # event.outcome = "success"
            r"\.posted_at\s*=",   # draft.posted_at = now
            r"PostingEvent\(",    # Creating new PostingEvent
        ]
        for pattern in modification_patterns:
            if re.search(pattern, source):
                return True
        return False

    # ------------------------------------------------------------------
    # Check 2: Routes missing auth dependencies (Req 8.2)
    # ------------------------------------------------------------------

    def _check_route_auth_dependencies(self) -> list[FindingInput]:
        """Scan admin routes for missing require_superuser/require_platform_admin.

        Parses route files to find route decorators and checks if the handler
        function has admin auth dependencies.

        Returns:
            Findings for unprotected routes.
        """
        findings: list[FindingInput] = []
        routes_dir = self._app_root / "routes"

        if not routes_dir.exists():
            return findings

        for py_file in sorted(routes_dir.glob("*.py")):
            if py_file.name.startswith("__"):
                continue

            # Only check admin-related route files
            if not self._is_admin_route_file(py_file):
                continue

            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except (OSError, UnicodeDecodeError, SyntaxError):
                continue

            unprotected = self._find_unprotected_routes(tree, source, py_file)
            for route_info in unprotected:
                rel_path = str(py_file.relative_to(self._project_root))
                findings.append(
                    FindingInput(
                        title=f"Admin route without auth guard: {route_info[1]} in {py_file.name}"[:120],
                        severity=Severity.RED,
                        block=AuditBlockName.BYPASS_DETECTION,
                        category="security",
                        risk_description=(
                            f"Route handler '{route_info[1]}' at line {route_info[0]} "
                            f"in {rel_path} does not have require_superuser or "
                            f"require_platform_admin dependency. Admin endpoints must "
                            f"be protected by authorization guards."
                        )[:500],
                        owner=rel_path,
                        effort=FixEffort.S,
                        risk_if_unresolved=(
                            "Unprotected admin routes allow unauthorized users to "
                            "perform privileged operations."
                        )[:200],
                        requirement_ref="8.2",
                        data_path=f"{rel_path}:{route_info[0]}",
                    )
                )

        return findings

    def _is_admin_route_file(self, py_file: Path) -> bool:
        """Check if a route file contains admin routes."""
        name = py_file.name
        # Files that contain admin routes
        admin_files = {
            "admin.py", "admin_audit.py", "admin_geo.py",
            "dashboard.py", "posting_dashboard.py",
            "decision_center.py",
        }
        if name in admin_files:
            return True
        if "admin" in name:
            return True
        return False

    def _find_unprotected_routes(
        self, tree: ast.Module, source: str, py_file: Path
    ) -> list[tuple[int, str]]:
        """Find route handler functions without admin auth dependencies.

        Returns list of (line_number, function_name) for unprotected routes.
        """
        unprotected: list[tuple[int, str]] = []

        # Check if file-level router uses dependencies (prefix-level auth)
        has_router_level_auth = self._has_router_level_auth(source)
        if has_router_level_auth:
            return unprotected  # All routes under this router are protected

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            # Check if this function has route decorators
            if not self._has_route_decorator(node):
                continue

            # Check if function parameters include auth dependencies
            if not self._has_auth_dependency(node, source):
                unprotected.append((node.lineno, node.name))

        return unprotected

    def _has_router_level_auth(self, source: str) -> bool:
        """Check if the router is configured with dependencies at the prefix level."""
        # Pattern: APIRouter(..., dependencies=[Depends(require_superuser)])
        router_pattern = r"APIRouter\([^)]*dependencies\s*=\s*\[.*?require_(superuser|platform_admin)"
        return bool(re.search(router_pattern, source, re.DOTALL))

    def _has_route_decorator(self, node: ast.FunctionDef) -> bool:
        """Check if a function has @router.get/post/put/delete decorators."""
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                if decorator.func.attr in ("get", "post", "put", "delete", "patch"):
                    return True
            elif isinstance(decorator, ast.Attribute):
                if decorator.attr in ("get", "post", "put", "delete", "patch"):
                    return True
        return False

    def _has_auth_dependency(self, node: ast.FunctionDef, source: str) -> bool:
        """Check if function parameters include admin auth dependency via Depends()."""
        # Get function source lines for checking parameter annotations
        lines = source.split("\n")
        func_start = node.lineno - 1
        func_end = min(node.end_lineno or func_start + 20, len(lines))
        func_lines = lines[func_start:func_end]
        func_text = "\n".join(func_lines)

        # Check for Depends(require_superuser) or Depends(require_platform_admin)
        # in function parameters
        for dep_name in ADMIN_AUTH_DEPS:
            if dep_name in func_text:
                return True

        # Also check for current_user parameter patterns (indicates some auth)
        if "current_user" in func_text and "Depends" in func_text:
            return True

        return False

    # ------------------------------------------------------------------
    # Check 3: Root scripts with DB writes (Req 8.3)
    # ------------------------------------------------------------------

    def _check_root_scripts(self) -> list[FindingInput]:
        """Check _*.py scripts in project root for direct DB writes without Pydantic.

        Scripts at the project root (../_*.py relative to reddit_saas/) that
        write to the database should use Pydantic validation like API routes.

        Returns:
            Findings for scripts with unvalidated DB writes.
        """
        findings: list[FindingInput] = []

        if not self._scripts_root.exists():
            return findings

        # Find _*.py files in the parent directory (project root)
        script_files = sorted(self._scripts_root.glob("_*.py"))

        for script_file in script_files:
            if script_file.name.startswith("__"):
                continue

            try:
                source = script_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            # Check for DB write indicators
            has_db_writes = any(
                indicator in source for indicator in DB_WRITE_INDICATORS
            )

            if not has_db_writes:
                continue

            # Check for Pydantic validation
            has_pydantic = any(
                indicator in source for indicator in PYDANTIC_INDICATORS
            )

            if not has_pydantic:
                rel_path = str(script_file.relative_to(self._scripts_root))
                findings.append(
                    FindingInput(
                        title=f"Root script with DB writes lacks Pydantic validation: {script_file.name}"[:120],
                        severity=Severity.YELLOW,
                        block=AuditBlockName.BYPASS_DETECTION,
                        category="security",
                        risk_description=(
                            f"Script {rel_path} performs direct database writes "
                            f"without Pydantic schema validation. Data written by "
                            f"this script may bypass validation rules enforced by "
                            f"the API routes."
                        )[:500],
                        owner=rel_path,
                        effort=FixEffort.S,
                        risk_if_unresolved=(
                            "Scripts that bypass validation may insert invalid data "
                            "causing downstream failures in the pipeline."
                        )[:200],
                        requirement_ref="8.3",
                        data_path=rel_path,
                    )
                )

        return findings

    # ------------------------------------------------------------------
    # Check 4: Admin CRUD audit logging (Req 8.4)
    # ------------------------------------------------------------------

    def _check_admin_crud_audit_logs(self) -> list[FindingInput]:
        """Verify admin CRUD routes produce AuditLog entries.

        Scans admin route handlers for create/update/delete operations and
        checks if they call audit_service.log_action or equivalent.

        Returns:
            Findings for CRUD operations missing audit logging.
        """
        findings: list[FindingInput] = []
        admin_route_file = self._app_root / "routes" / "admin.py"

        if not admin_route_file.exists():
            return findings

        try:
            source = admin_route_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(admin_route_file))
        except (OSError, UnicodeDecodeError, SyntaxError):
            return findings

        # Find functions that perform CRUD operations
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            # Check if this is a route handler with CRUD intent
            crud_type = self._identify_crud_operation(node)
            if not crud_type:
                continue

            # Get function source to check for audit_service.log_action
            lines = source.split("\n")
            func_start = node.lineno - 1
            func_end = min(node.end_lineno or func_start + 50, len(lines))
            func_lines = lines[func_start:func_end]
            func_text = "\n".join(func_lines)

            has_audit_log = (
                "log_action" in func_text
                or "audit_service" in func_text
                or "log_system_action" in func_text
            )

            if not has_audit_log:
                rel_path = str(admin_route_file.relative_to(self._project_root))
                findings.append(
                    FindingInput(
                        title=f"Admin CRUD without audit log: {node.name} ({crud_type})"[:120],
                        severity=Severity.YELLOW,
                        block=AuditBlockName.BYPASS_DETECTION,
                        category="security",
                        risk_description=(
                            f"Admin route handler '{node.name}' at line {node.lineno} "
                            f"performs a {crud_type} operation but does not produce an "
                            f"AuditLog entry. All admin CUD operations must be logged "
                            f"for traceability."
                        )[:500],
                        owner=rel_path,
                        effort=FixEffort.S,
                        risk_if_unresolved=(
                            "Unlogged admin operations cannot be traced for security "
                            "audit or incident investigation."
                        )[:200],
                        requirement_ref="8.4",
                        data_path=f"{rel_path}:{node.lineno}",
                    )
                )

        return findings

    def _identify_crud_operation(self, node: ast.FunctionDef) -> Optional[str]:
        """Identify if a function performs a CRUD operation based on decorators and name."""
        # Check decorator for POST/PUT/DELETE (create/update/delete)
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                method = decorator.func.attr
                if method == "post":
                    return "create"
                elif method == "put":
                    return "update"
                elif method == "delete":
                    return "delete"

        # Check function name patterns
        name = node.name.lower()
        if any(prefix in name for prefix in ("create_", "add_", "new_")):
            return "create"
        if any(prefix in name for prefix in ("update_", "edit_", "modify_")):
            return "update"
        if any(prefix in name for prefix in ("delete_", "remove_", "deactivate_")):
            return "delete"

        return None

    # ------------------------------------------------------------------
    # Check 5: Feature flags validity (Req 8.5)
    # ------------------------------------------------------------------

    def _check_feature_flags(self, db_session: Session) -> list[FindingInput]:
        """Check feature flags for valid description and boolean value.

        Queries SystemSetting where group='app' and key contains 'enabled'
        or 'disabled'. Verifies each has a non-empty description and value
        is 'true' or 'false'.

        Returns:
            Findings for invalid feature flags.
        """
        findings: list[FindingInput] = []

        try:
            from app.models.settings import SystemSetting

            flags = (
                db_session.query(SystemSetting)
                .filter(
                    SystemSetting.group == "app",
                )
                .all()
            )

            # Filter to keys containing 'enabled' or 'disabled'
            feature_flags = [
                f for f in flags
                if "enabled" in (f.key or "").lower()
                or "disabled" in (f.key or "").lower()
            ]

            for flag in feature_flags:
                issues = []

                # Check description
                if not flag.description or not flag.description.strip():
                    issues.append("missing_description")

                # Check value is boolean string
                value_lower = (flag.value or "").strip().lower()
                if value_lower not in ("true", "false"):
                    issues.append(f"invalid_value: '{flag.value}'")

                for issue in issues:
                    severity = Severity.YELLOW
                    if "invalid_value" in issue:
                        severity = Severity.RED

                    findings.append(
                        FindingInput(
                            title=f"Feature flag issue: {flag.key} - {issue}"[:120],
                            severity=severity,
                            block=AuditBlockName.BYPASS_DETECTION,
                            category="security",
                            risk_description=(
                                f"Feature flag '{flag.key}' (group='app') has issue: "
                                f"{issue}. Feature flags must have a non-empty "
                                f"description identifying the owning team and a "
                                f"value of 'true' or 'false'."
                            )[:500],
                            owner="platform",
                            effort=FixEffort.S,
                            risk_if_unresolved=(
                                "Invalid feature flags may cause unpredictable "
                                "behavior or hide ownership information."
                            )[:200],
                            requirement_ref="8.5",
                            data_path=f"system_settings:{flag.key}",
                        )
                    )

        except Exception as exc:
            logger.warning("BypassDetector: failed to check feature flags: %s", exc)

        return findings

    # ------------------------------------------------------------------
    # Check 6: Alembic migrations with data modifications (Req 8.6)
    # ------------------------------------------------------------------

    def _check_alembic_migrations(self) -> list[FindingInput]:
        """Scan Alembic migration scripts for UPDATE/DELETE without downgrade.

        Checks each migration file in alembic/versions/ for SQL statements
        that modify existing data (UPDATE, DELETE) and verifies the script
        includes a corresponding downgrade function that reverses the change.

        Returns:
            Findings for migrations with data modifications but no downgrade.
        """
        findings: list[FindingInput] = []
        alembic_dir = self._project_root / "alembic" / "versions"

        if not alembic_dir.exists():
            return findings

        for py_file in sorted(alembic_dir.glob("*.py")):
            if py_file.name.startswith("__") or py_file.name == ".gitkeep":
                continue

            try:
                source = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            # Check for data modification SQL in upgrade function
            has_update = bool(re.search(
                r"(UPDATE|update)\s+", source
            ))
            has_delete = bool(re.search(
                r"(DELETE|delete)\s+(FROM|from)", source
            ))

            if not has_update and not has_delete:
                continue

            modification_type = "UPDATE" if has_update else "DELETE"
            if has_update and has_delete:
                modification_type = "UPDATE+DELETE"

            # Check for downgrade function with actual content
            has_downgrade = self._has_meaningful_downgrade(source)

            if not has_downgrade:
                rel_path = str(py_file.relative_to(self._project_root))
                findings.append(
                    FindingInput(
                        title=f"Alembic migration with {modification_type} lacks downgrade: {py_file.name}"[:120],
                        severity=Severity.YELLOW,
                        block=AuditBlockName.BYPASS_DETECTION,
                        category="reliability",
                        risk_description=(
                            f"Migration {rel_path} contains {modification_type} SQL "
                            f"statements that modify existing data but does not have "
                            f"a meaningful downgrade function to reverse the change. "
                            f"Data modifications must be reversible."
                        )[:500],
                        owner=rel_path,
                        effort=FixEffort.M,
                        risk_if_unresolved=(
                            "Irreversible data migrations prevent safe rollback "
                            "if deployment issues are detected."
                        )[:200],
                        requirement_ref="8.6",
                        data_path=rel_path,
                    )
                )

        return findings

    def _has_meaningful_downgrade(self, source: str) -> bool:
        """Check if a migration has a meaningful downgrade function.

        A meaningful downgrade is one that contains actual operations,
        not just 'pass' or an empty body.
        """
        # Parse to find the downgrade function
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return False

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "downgrade":
                # Check if body is just 'pass' or empty
                if len(node.body) == 1:
                    stmt = node.body[0]
                    if isinstance(stmt, ast.Pass):
                        return False
                    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                        # Just a docstring
                        return False
                # Has real content
                return True

        # No downgrade function found at all
        return False
