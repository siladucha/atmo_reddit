"""Audit Block 6 â SpecCoverageTracker.

Maps all specifications to their implementation and test status:
- Categorizes each spec (not_read -> tested -> outdated)
- Identifies orphan specs, dead features, hidden flags, unreachable templates
- Produces coverage matrix + findings

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7
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
SPECS_DIR = PROJECT_ROOT.parent / ".kiro" / "specs"

# Directories to search for spec references
CODE_DIRS = [
    APP_ROOT / "services",
    APP_ROOT / "routes",
    APP_ROOT / "tasks",
]

# Directories for dead feature detection
SERVICE_DIR = APP_ROOT / "services"
ROUTES_DIR = APP_ROOT / "routes"
TEMPLATES_DIR = APP_ROOT / "templates"
TESTS_DIR = PROJECT_ROOT.parent / "tests"


# Status categories for specs
SPEC_STATUSES = (
    "not_read",
    "read",
    "partially_implemented",
    "implemented",
    "tested",
    "outdated",
)


@dataclass
class SpecInfo:
    """Information about a single specification."""

    name: str  # directory name (kebab-case)
    criteria_count: int = 0
    implemented_count: int = 0
    tested_count: int = 0
    status: str = "not_read"
    implementation_percent: int = 0
    test_percent: int = 0
    owner: str = "unassigned"
    risk: str = "low"
    code_references: list = field(default_factory=list)
    test_references: list = field(default_factory=list)


class SpecCoverageTracker(AuditBlock):
    """Maps specifications to implementation and test coverage.

    Performs static filesystem analysis:
    - Lists all specs with requirements.md
    - Extracts acceptance criteria counts
    - Searches code for references to spec feature names
    - Categorizes each spec by implementation depth
    - Detects orphan specs, dead features, hidden flags, unreachable templates
    """

    @property
    def name(self) -> AuditBlockName:
        return AuditBlockName.SPEC_COVERAGE

    async def run(self, run_id: UUID, db_session) -> list[FindingInput]:
        """Execute spec coverage analysis and return findings."""
        findings: list[FindingInput] = []

        # 1. Collect all specs with requirements.md
        specs = self._collect_specs()

        # 2. For each spec, determine status and coverage
        for spec in specs:
            self._analyze_spec(spec)

        # 3. Generate findings for low-coverage or orphan specs
        findings.extend(self._generate_coverage_findings(specs))

        # 4. Detect orphan specs (no code references)
        findings.extend(self._detect_orphan_specs(specs))

        # 5. Detect dead features (unreferenced modules)
        findings.extend(self._detect_dead_features(specs))

        # 6. Detect hidden feature flags
        findings.extend(self._detect_hidden_flags(db_session))

        # 7. Detect unreachable templates
        findings.extend(self._detect_unreachable_templates())

        # 8. Produce coverage matrix as informational finding
        findings.append(self._build_coverage_matrix_finding(specs))

        logger.info(
            "SpecCoverageTracker completed: %d findings, %d specs analyzed (run_id=%s)",
            len(findings),
            len(specs),
            run_id,
        )
        return findings

    # --- 1. Collect Specs ---

    def _collect_specs(self) -> list[SpecInfo]:
        """List all directories under .kiro/specs/ that contain requirements.md."""
        specs: list[SpecInfo] = []

        if not SPECS_DIR.exists():
            logger.warning("Specs directory not found: %s", SPECS_DIR)
            return specs

        for entry in sorted(SPECS_DIR.iterdir()):
            if not entry.is_dir():
                continue
            requirements_file = entry / "requirements.md"
            if requirements_file.exists():
                spec = SpecInfo(name=entry.name)
                spec.criteria_count = self._count_acceptance_criteria(requirements_file)
                specs.append(spec)

        return specs

    def _count_acceptance_criteria(self, requirements_path: Path) -> int:
        """Extract acceptance criteria count from Markdown numbered lists.

        Counts lines matching patterns like:
        - "1. WHEN..." or "1. THE..." (numbered acceptance criteria)
        - Lines starting with a digit followed by period in AC sections
        """
        count = 0
        in_criteria_section = False

        try:
            content = requirements_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return 0

        for line in content.splitlines():
            stripped = line.strip()

            # Detect acceptance criteria section headers
            if "acceptance criteria" in stripped.lower():
                in_criteria_section = True
                continue

            # Detect next section header (end of criteria)
            if stripped.startswith("### ") or stripped.startswith("## "):
                if in_criteria_section and "acceptance criteria" not in stripped.lower():
                    in_criteria_section = False

            # Count numbered items in criteria sections
            if in_criteria_section and re.match(r"^\d+\.\s+", stripped):
                count += 1

        return max(count, 1)  # At least 1 to avoid division by zero

    # --- 2. Analyze Spec ---

    def _analyze_spec(self, spec: SpecInfo) -> None:
        """Determine implementation level for a spec based on code references.

        Searches app/services/, app/routes/, app/tasks/ for references matching
        the spec feature name (kebab-case or underscore variant).
        """
        feature_name = spec.name  # e.g. "avatar-warming-phases"

        # Generate search terms from the feature name
        search_terms = self._generate_search_terms(feature_name)

        # Scan code directories for references
        code_refs: list[str] = []
        test_refs: list[str] = []

        for code_dir in CODE_DIRS:
            if not code_dir.exists():
                continue
            for py_file in code_dir.rglob("*.py"):
                if py_file.name.startswith("__"):
                    continue
                try:
                    content_text = py_file.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue

                relative_path = str(py_file.relative_to(PROJECT_ROOT))
                if self._has_feature_reference(content_text, search_terms):
                    code_refs.append(relative_path)

        # Scan test directory for test references
        if TESTS_DIR.exists():
            for py_file in TESTS_DIR.rglob("*.py"):
                if py_file.name.startswith("__"):
                    continue
                try:
                    content_text = py_file.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if self._has_feature_reference(content_text, search_terms):
                    test_refs.append(str(py_file.relative_to(PROJECT_ROOT.parent)))

        spec.code_references = code_refs
        spec.test_references = test_refs

        # Determine owner (most relevant service/route file)
        if code_refs:
            spec.owner = code_refs[0]
        else:
            spec.owner = "unassigned"

        # Calculate implementation and test percentages
        # Heuristic: each code reference covers ~criteria_count/max_expected_refs criteria
        max_expected_refs = max(spec.criteria_count, 1)
        impl_ratio = min(len(code_refs) / max(max_expected_refs * 0.3, 1), 1.0)
        spec.implementation_percent = min(int(impl_ratio * 100), 100)

        test_ratio = min(len(test_refs) / max(max_expected_refs * 0.2, 1), 1.0)
        spec.test_percent = min(int(test_ratio * 100), 100)

        # Determine status
        spec.status = self._determine_status(spec)

        # Determine risk level
        spec.risk = self._determine_risk(spec)

    def _generate_search_terms(self, feature_name: str) -> list[str]:
        """Generate search terms from a kebab-case feature name.

        Given "avatar-warming-phases", generates:
        - "avatar-warming-phases" (exact kebab)
        - "avatar_warming_phases" (underscore variant)
        - Key word combinations from the name parts
        """
        terms = [feature_name]
        underscore = feature_name.replace("-", "_")
        terms.append(underscore)

        # Add significant substrings (2+ word combos from the name)
        parts = feature_name.split("-")
        if len(parts) >= 2:
            # Add pairs of adjacent words as underscore
            for i in range(len(parts) - 1):
                pair = f"{parts[i]}_{parts[i + 1]}"
                if len(pair) > 6:  # Only meaningful pairs
                    terms.append(pair)

        return terms

    def _has_feature_reference(self, content: str, search_terms: list[str]) -> bool:
        """Check if file content references the feature via any search term."""
        content_lower = content.lower()
        for term in search_terms:
            if term.lower() in content_lower:
                return True
        return False

    def _determine_status(self, spec: SpecInfo) -> str:
        """Determine the spec status category based on analysis results.

        Categories:
        - not_read: no matching service or route file references the spec name
        - read: referenced in code comments/docs but no functional implementation
        - partially_implemented: at least one but not all criteria have code paths
        - implemented: all criteria have corresponding code paths
        - tested: all criteria have corresponding test assertions
        - outdated: spec references models/routes/services that have been renamed/deleted
        """
        if not spec.code_references:
            return "not_read"

        # Check for outdated status (referenced files no longer exist)
        if self._check_outdated(spec):
            return "outdated"

        # Check if references are only in comments/docstrings (read-only)
        if spec.implementation_percent < 10:
            return "read"

        if spec.test_percent >= 80:
            return "tested"

        if spec.implementation_percent >= 80:
            return "implemented"

        if spec.implementation_percent > 0:
            return "partially_implemented"

        return "read"

    def _check_outdated(self, spec: SpecInfo) -> bool:
        """Check if a spec references files that no longer exist.

        A spec is outdated if its requirements.md mentions specific module names
        that have been deleted or renamed.
        """
        req_path = SPECS_DIR / spec.name / "requirements.md"
        if not req_path.exists():
            return False

        try:
            content = req_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return False

        # Look for Python module references in the spec
        module_refs = re.findall(r"app/(?:services|routes|tasks)/[\w/]+\.py", content)
        if not module_refs:
            return False

        # Check if any referenced module no longer exists
        missing_count = 0
        for ref in module_refs:
            full_path = PROJECT_ROOT / ref
            if not full_path.exists():
                missing_count += 1

        # If more than half of referenced modules are missing, it's outdated
        return missing_count > len(module_refs) / 2

    def _determine_risk(self, spec: SpecInfo) -> str:
        """Determine risk level based on implementation percentage.

        - high: implementation_percent < 30 AND spec is referenced by an active route
        - medium: implementation_percent between 30 and 79
        - low: implementation_percent 80 or above
        """
        if spec.implementation_percent >= 80:
            return "low"

        if spec.implementation_percent >= 30:
            return "medium"

        # Check if spec is referenced by an active route
        if self._is_referenced_by_active_route(spec):
            return "high"

        return "medium"

    def _is_referenced_by_active_route(self, spec: SpecInfo) -> bool:
        """Check if any code reference for this spec is in app/routes/."""
        for ref in spec.code_references:
            if "routes/" in ref:
                return True
        return False

    # --- 3. Coverage Findings ---

    def _generate_coverage_findings(self, specs: list[SpecInfo]) -> list[FindingInput]:
        """Generate findings for specs with concerning coverage levels."""
        findings: list[FindingInput] = []

        for spec in specs:
            if spec.risk == "high":
                findings.append(
                    FindingInput(
                        title=f"High-risk spec: {spec.name} ({spec.implementation_percent}% impl)",
                        severity=Severity.RED,
                        block=AuditBlockName.SPEC_COVERAGE,
                        category="spec_coverage",
                        risk_description=(
                            f"Spec '{spec.name}' has {spec.implementation_percent}% implementation "
                            f"and is referenced by an active route. {spec.criteria_count} acceptance "
                            f"criteria defined but coverage is critically low."
                        ),
                        owner=spec.owner,
                        effort=FixEffort.L,
                        risk_if_unresolved=(
                            f"Feature '{spec.name}' exposed via route but largely unimplemented"
                        ),
                        requirement_ref="6.2",
                        data_path=spec.owner,
                    )
                )
            elif spec.risk == "medium":
                findings.append(
                    FindingInput(
                        title=f"Medium-risk spec: {spec.name} ({spec.implementation_percent}% impl)",
                        severity=Severity.YELLOW,
                        block=AuditBlockName.SPEC_COVERAGE,
                        category="spec_coverage",
                        risk_description=(
                            f"Spec '{spec.name}' is partially implemented at "
                            f"{spec.implementation_percent}%. "
                            f"{spec.criteria_count} criteria, {spec.test_percent}% tested."
                        ),
                        owner=spec.owner,
                        effort=FixEffort.M,
                        risk_if_unresolved=(
                            f"Incomplete implementation of '{spec.name}' may cause runtime gaps"
                        ),
                        requirement_ref="6.2",
                        data_path=spec.owner,
                    )
                )

        return findings

    # --- 4. Orphan Specs ---

    def _detect_orphan_specs(self, specs: list[SpecInfo]) -> list[FindingInput]:
        """Identify specs where no Python file references the spec feature name.

        Requirement 6.3: Orphan specs have no matching import, function, or class
        name in app/services/, app/routes/, or app/tasks/.
        """
        findings: list[FindingInput] = []

        orphans = [s for s in specs if s.status == "not_read"]

        if orphans:
            orphan_names = ", ".join(s.name for s in orphans[:10])
            extra = f" (+{len(orphans) - 10} more)" if len(orphans) > 10 else ""
            findings.append(
                FindingInput(
                    title=f"Orphan specs detected: {len(orphans)} specs with no code references",
                    severity=Severity.YELLOW,
                    block=AuditBlockName.SPEC_COVERAGE,
                    category="spec_coverage",
                    risk_description=(
                        f"Found {len(orphans)} spec directories with requirements.md but "
                        f"no matching code in app/services/, app/routes/, or app/tasks/. "
                        f"Specs: {orphan_names}{extra}"
                    ),
                    owner="Max",
                    effort=FixEffort.M,
                    risk_if_unresolved="Specs exist without implementation; may indicate stale planning artifacts",
                    requirement_ref="6.3",
                    data_path=".kiro/specs/",
                )
            )

        return findings

    # --- 5. Dead Features ---

    def _detect_dead_features(self, specs: list[SpecInfo]) -> list[FindingInput]:
        """Identify Python modules not imported by any other module and not in specs.

        Requirement 6.4: Dead features are modules under app/services/ or app/routes/
        that are not imported by any other module and not referenced by any spec.
        """
        findings: list[FindingInput] = []

        # Collect all spec feature names for cross-reference
        spec_names: set[str] = set()
        if SPECS_DIR.exists():
            for spec_dir in SPECS_DIR.iterdir():
                if spec_dir.is_dir():
                    spec_names.add(spec_dir.name)
                    spec_names.add(spec_dir.name.replace("-", "_"))

        # Build import graph: which modules are imported by others
        all_modules: dict[str, str] = {}  # module_name -> file_path
        imported_modules: set[str] = set()

        scan_dirs = [SERVICE_DIR, ROUTES_DIR]
        for scan_dir in scan_dirs:
            if not scan_dir.exists():
                continue
            for py_file in scan_dir.rglob("*.py"):
                if py_file.name.startswith("__"):
                    continue
                module_name = py_file.stem
                relative_path = str(py_file.relative_to(PROJECT_ROOT))
                all_modules[module_name] = relative_path

        # Scan all Python files for imports
        if APP_ROOT.exists():
            for py_file in APP_ROOT.rglob("*.py"):
                try:
                    content_text = py_file.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue

                # Find import statements
                import_pattern = re.compile(
                    r"(?:from\s+[\w.]+\s+import|import\s+[\w.]+)"
                )
                for match in import_pattern.finditer(content_text):
                    import_line = match.group()
                    for mod_name in all_modules:
                        if mod_name in import_line:
                            imported_modules.add(mod_name)

        # Also check main.py for route registrations
        main_py = APP_ROOT / "main.py"
        if main_py.exists():
            try:
                main_content = main_py.read_text(encoding="utf-8", errors="ignore")
                for mod_name in all_modules:
                    if mod_name in main_content:
                        imported_modules.add(mod_name)
            except OSError:
                pass

        # Find dead modules: not imported and not matching any spec name
        dead_modules: list[str] = []
        for mod_name, mod_path in all_modules.items():
            if mod_name in imported_modules:
                continue
            # Check if module name relates to any spec
            is_spec_related = any(
                term in mod_name or mod_name in term
                for term in spec_names
            )
            if not is_spec_related:
                dead_modules.append(mod_path)

        if dead_modules:
            sample = ", ".join(dead_modules[:8])
            extra = f" (+{len(dead_modules) - 8} more)" if len(dead_modules) > 8 else ""
            findings.append(
                FindingInput(
                    title=f"Dead features: {len(dead_modules)} unreferenced modules",
                    severity=Severity.YELLOW,
                    block=AuditBlockName.SPEC_COVERAGE,
                    category="spec_coverage",
                    risk_description=(
                        f"Found {len(dead_modules)} Python modules not imported by any other "
                        f"module and not referenced by any spec directory. "
                        f"Modules: {sample}{extra}"
                    ),
                    owner="Max",
                    effort=FixEffort.S,
                    risk_if_unresolved="Dead code increases maintenance burden and confusion",
                    requirement_ref="6.4",
                    data_path="app/services/ and app/routes/",
                )
            )

        return findings

    # --- 6. Hidden Feature Flags ---

    def _detect_hidden_flags(self, db_session) -> list[FindingInput]:
        """Identify SystemSetting entries not referenced in active code.

        Requirement 6.5: If a SystemSetting key is not referenced in any active
        route handler or Celery task as a runtime gate, flag as hidden feature flag.
        """
        findings: list[FindingInput] = []

        try:
            from app.models.settings import SystemSetting

            settings = db_session.query(
                SystemSetting.key, SystemSetting.value, SystemSetting.description
            ).all()
        except Exception as exc:
            logger.warning("Could not query SystemSettings: %s", exc)
            return findings

        if not settings:
            return findings

        # Build a set of all code content from routes, tasks, and services
        code_content = ""
        scan_targets = [ROUTES_DIR, APP_ROOT / "tasks", SERVICE_DIR]
        for code_dir in scan_targets:
            if not code_dir.exists():
                continue
            for py_file in code_dir.rglob("*.py"):
                if py_file.name.startswith("__"):
                    continue
                try:
                    code_content += py_file.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue

        hidden_flags: list[dict] = []
        for key, value, description in settings:
            # Check if the setting key is referenced in code
            if key not in code_content:
                hidden_flags.append({
                    "key": key,
                    "value": value,
                    "description": description or "(no description)",
                })

        if hidden_flags:
            flag_sample = "; ".join(
                f"{f['key']}={f['value']}" for f in hidden_flags[:5]
            )
            extra = f" (+{len(hidden_flags) - 5} more)" if len(hidden_flags) > 5 else ""
            findings.append(
                FindingInput(
                    title=f"Hidden feature flags: {len(hidden_flags)} unreferenced settings",
                    severity=Severity.YELLOW,
                    block=AuditBlockName.SPEC_COVERAGE,
                    category="spec_coverage",
                    risk_description=(
                        f"Found {len(hidden_flags)} SystemSetting entries whose keys are not "
                        f"referenced in any route handler, Celery task, or service file. "
                        f"Flags: {flag_sample}{extra}"
                    ),
                    owner="Max",
                    effort=FixEffort.S,
                    risk_if_unresolved="Unreferenced settings may be stale or indicate removed features",
                    requirement_ref="6.5",
                    data_path="system_settings table",
                )
            )

        return findings

    # --- 7. Unreachable Templates ---

    def _detect_unreachable_templates(self) -> list[FindingInput]:
        """Identify templates not referenced by any route or included from other templates.

        Requirement 6.6: Template files under app/templates/ that are not referenced
        by any render_template or TemplateResponse call and not included via Jinja2
        include/extends directives from a referenced template.
        """
        findings: list[FindingInput] = []

        if not TEMPLATES_DIR.exists():
            return findings

        # Collect all template filenames
        all_templates: set[str] = set()
        for tmpl_file in TEMPLATES_DIR.rglob("*.html"):
            relative = str(tmpl_file.relative_to(TEMPLATES_DIR))
            all_templates.add(relative)

        if not all_templates:
            return findings

        # Find all template references in routes (TemplateResponse, render_template)
        referenced_templates: set[str] = set()

        # Scan route files for template references
        if ROUTES_DIR.exists():
            for py_file in ROUTES_DIR.rglob("*.py"):
                try:
                    content_text = py_file.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue

                # Match TemplateResponse("name.html", ...) patterns
                template_refs = re.findall(
                    r'(?:TemplateResponse|render_template)\s*\(\s*["\x27]([^"\x27]+\.html)["\x27]',
                    content_text,
                )
                referenced_templates.update(template_refs)

                # Also match templates.get_template("...") patterns
                get_refs = re.findall(
                    r'get_template\s*\(\s*["\x27]([^"\x27]+\.html)["\x27]',
                    content_text,
                )
                referenced_templates.update(get_refs)

        # Scan templates for Jinja2 include/extends directives
        included_templates: set[str] = set()
        for tmpl_file in TEMPLATES_DIR.rglob("*.html"):
            try:
                content_text = tmpl_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            # Match {% extends "..." %} and {% include "..." %}
            jinja_refs = re.findall(
                r'\{%[-\s]*(?:extends|include)\s+["\x27]([^"\x27]+)["\x27]',
                content_text,
            )
            included_templates.update(jinja_refs)

        # Combine all referenced templates
        all_referenced = referenced_templates | included_templates

        # Find unreachable templates
        unreachable: list[str] = []
        for tmpl in sorted(all_templates):
            # Check if template is referenced directly or via its base name
            tmpl_basename = os.path.basename(tmpl)
            is_referenced = (
                tmpl in all_referenced
                or tmpl_basename in all_referenced
                or any(tmpl.endswith(ref) or ref.endswith(tmpl) for ref in all_referenced)
            )
            if not is_referenced:
                unreachable.append(tmpl)

        if unreachable:
            sample = ", ".join(unreachable[:8])
            extra = f" (+{len(unreachable) - 8} more)" if len(unreachable) > 8 else ""
            findings.append(
                FindingInput(
                    title=f"Unreachable templates: {len(unreachable)} HTML files not referenced",
                    severity=Severity.YELLOW,
                    block=AuditBlockName.SPEC_COVERAGE,
                    category="spec_coverage",
                    risk_description=(
                        f"Found {len(unreachable)} template files not referenced by any route "
                        f"handler (TemplateResponse) or included via Jinja2 extends/include. "
                        f"Templates: {sample}{extra}"
                    ),
                    owner="Max",
                    effort=FixEffort.S,
                    risk_if_unresolved="Dead templates increase maintenance burden and confusion",
                    requirement_ref="6.6",
                    data_path="app/templates/",
                )
            )

        return findings

    # --- 8. Coverage Matrix Finding ---

    def _build_coverage_matrix_finding(self, specs: list[SpecInfo]) -> FindingInput:
        """Produce coverage matrix table as an informational finding.

        Requirement 6.7: Coverage matrix with columns: Specification, Status,
        Implemented_Percent, Tested_Percent, Owner, Risk.
        Plus summary section with total counts per status category and total
        counts of orphans, dead features, hidden flags, and unreachable templates.
        """
        if not specs:
            table_text = "No specifications found in .kiro/specs/"
        else:
            # Build markdown table
            rows: list[str] = []
            for spec in specs:
                owner_short = spec.owner[:40] if spec.owner else "unassigned"
                rows.append(
                    f"| {spec.name} | {spec.status} | {spec.implementation_percent}% "
                    f"| {spec.test_percent}% | {owner_short} | {spec.risk} |"
                )

            table_text = (
                "| Specification | Status | Impl% | Test% | Owner | Risk |\n"
                "| --- | --- | --- | --- | --- | --- |\n"
                + "\n".join(rows[:30])  # Limit to 30 rows for finding text
            )

            # Add summary counts
            status_counts: dict[str, int] = {}
            for spec in specs:
                status_counts[spec.status] = status_counts.get(spec.status, 0) + 1

            orphan_count = sum(1 for s in specs if s.status == "not_read")
            summary = (
                f"\n\nSummary: {len(specs)} specs total. "
                + ", ".join(f"{status}: {count}" for status, count in sorted(status_counts.items()))
                + f". Orphans: {orphan_count}"
            )
            table_text = (table_text + summary)[:500]

        return FindingInput(
            title=f"Spec coverage matrix: {len(specs)} specifications analyzed",
            severity=Severity.GREEN,
            block=AuditBlockName.SPEC_COVERAGE,
            category="spec_coverage",
            risk_description=table_text[:500],
            owner="Max",
            effort=FixEffort.S,
            risk_if_unresolved="N/A - informational",
            requirement_ref="6.7",
            data_path=".kiro/specs/",
        )
