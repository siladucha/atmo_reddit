#!/usr/bin/env python3
"""Screen Spec Validator — RAMP Frontend Observability System.

Validates YAML screen specification files against the required schema.
Reports missing fields, invalid values, and coverage gaps.

Usage:
    python3 scripts/validate_screen_specs.py docs/screen_specs/
    python3 scripts/validate_screen_specs.py docs/screen_specs/ --routes-dir app/routes/
"""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import yaml
except ImportError:
    # Fallback: try to parse YAML minimally without pyyaml
    yaml = None


@dataclass
class ValidationError:
    file: str
    field: str
    message: str

    def __str__(self) -> str:
        return f"{self.file}: [{self.field}] {self.message}"


VALID_THEMES = {"admin", "client", "public"}
VALID_VERIFIABLE_BY = {"visual_only", "visual_with_test_data", "requires_backend_state"}
REQUIRED_STATES = {"loading", "empty", "error", "filled"}
REQUIRED_FIELDS = {"page", "theme", "entry", "states", "sections", "verifiable_by"}


class ScreenSpecValidator:
    """Validates screen spec YAML files."""

    def __init__(self, specs_dir: Path, routes_dir: Path | None = None):
        self.specs_dir = specs_dir
        self.routes_dir = routes_dir
        self.errors: list[ValidationError] = []
        self.warnings: list[str] = []

    def validate_all(self) -> int:
        """Validate all YAML files. Returns exit code (0=pass, 1=errors)."""
        if not self.specs_dir.exists():
            print(f"WARNING: Screen specs directory does not exist: {self.specs_dir}")
            print("Run `make validate-specs` after creating initial specs.")
            return 0

        yaml_files = sorted(self.specs_dir.glob("*.yaml")) + sorted(self.specs_dir.glob("*.yml"))

        if not yaml_files:
            print("WARNING: No screen spec files found. This is expected during initial setup.")
            return 0

        for spec_file in yaml_files:
            self._validate_file(spec_file)

        # Check coverage if routes_dir provided
        if self.routes_dir:
            self._check_coverage(yaml_files)

        # Report results
        if self.errors:
            print(f"\nSCREEN SPEC VALIDATION: {len(self.errors)} error(s)\n")
            for err in self.errors:
                print(f"  ERROR: {err}")
            print()

        if self.warnings:
            print(f"\nSCREEN SPEC COVERAGE: {len(self.warnings)} warning(s)\n", file=sys.stderr)
            for w in self.warnings:
                print(f"  WARN: {w}", file=sys.stderr)
            print(file=sys.stderr)

        if self.errors:
            print(f"VALIDATION: FAILED ({len(self.errors)} errors, {len(self.warnings)} warnings)")
            return 1

        print(f"SCREEN SPECS: PASS ({len(yaml_files)} specs validated, {len(self.warnings)} coverage warnings)")
        return 0

    def _validate_file(self, spec_file: Path) -> None:
        """Validate a single YAML spec file."""
        rel_path = str(spec_file.name)

        try:
            content = spec_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            self.errors.append(ValidationError(rel_path, "file", f"Cannot read: {e}"))
            return

        # Parse YAML
        if yaml:
            try:
                data = yaml.safe_load(content)
            except yaml.YAMLError as e:
                self.errors.append(ValidationError(rel_path, "yaml", f"Parse error: {e}"))
                return
        else:
            # Minimal YAML parsing without library
            data = self._minimal_yaml_parse(content)
            if data is None:
                self.errors.append(ValidationError(rel_path, "yaml", "Cannot parse (install PyYAML for full validation)"))
                return

        if not isinstance(data, dict):
            self.errors.append(ValidationError(rel_path, "root", "Spec must be a YAML mapping (object)"))
            return

        # Check required fields
        for field in REQUIRED_FIELDS:
            if field not in data:
                self.errors.append(ValidationError(rel_path, field, f"Missing required field '{field}'"))

        # Validate theme
        if "theme" in data and data["theme"] not in VALID_THEMES:
            self.errors.append(ValidationError(
                rel_path, "theme",
                f"Invalid value '{data['theme']}' — must be one of: {', '.join(sorted(VALID_THEMES))}"
            ))

        # Validate verifiable_by
        if "verifiable_by" in data and data["verifiable_by"] not in VALID_VERIFIABLE_BY:
            self.errors.append(ValidationError(
                rel_path, "verifiable_by",
                f"Invalid value '{data['verifiable_by']}' — must be one of: {', '.join(sorted(VALID_VERIFIABLE_BY))}"
            ))

        # Validate states
        if "states" in data:
            if not isinstance(data["states"], dict):
                self.errors.append(ValidationError(rel_path, "states", "Must be a mapping"))
            else:
                missing_states = REQUIRED_STATES - set(data["states"].keys())
                if missing_states:
                    self.errors.append(ValidationError(
                        rel_path, "states",
                        f"Missing required state(s): {', '.join(sorted(missing_states))}"
                    ))

        # Validate sections
        if "sections" in data:
            if not isinstance(data["sections"], dict) or len(data["sections"]) == 0:
                self.errors.append(ValidationError(rel_path, "sections", "Must be a non-empty mapping"))

        # Validate page starts with /
        if "page" in data:
            page = str(data["page"])
            if not page.startswith("/"):
                self.errors.append(ValidationError(rel_path, "page", f"Must start with '/' — got '{page}'"))

        # If requires_backend_state, test_data should be present
        if data.get("verifiable_by") == "requires_backend_state":
            if "test_data" not in data or not data["test_data"]:
                self.errors.append(ValidationError(
                    rel_path, "test_data",
                    "Required when verifiable_by is 'requires_backend_state'"
                ))

    def _check_coverage(self, existing_specs: list[Path]) -> None:
        """Check which routed templates lack a screen spec."""
        # Extract template names from route files
        TMPL_RE = re.compile(r'TemplateResponse\s*\(\s*(?:name\s*=\s*)?["\']([^"\']+\.html)["\']')
        routed_templates = set()

        for route_file in sorted(self.routes_dir.glob("*.py")):
            if route_file.name == "__init__.py":
                continue
            try:
                content = route_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            routed_templates.update(TMPL_RE.findall(content))

        # Filter to page templates (exclude base, partials, macros)
        page_templates = {
            t for t in routed_templates
            if not t.endswith("_base.html")
            and "partials/" not in t
            and "_macros/" not in t
        }

        # Check which have specs
        spec_names = {f.stem for f in existing_specs}
        for tmpl in sorted(page_templates):
            # Generate expected spec name: admin_dashboard.html → admin_dashboard
            expected_name = Path(tmpl).stem
            # Also check with directory prefix: client/home.html → client_home
            alt_name = tmpl.replace("/", "_").replace(".html", "")
            if expected_name not in spec_names and alt_name not in spec_names:
                self.warnings.append(f"Template '{tmpl}' has route but no screen spec ({expected_name}.yaml)")

    def _minimal_yaml_parse(self, content: str) -> dict | None:
        """Minimal YAML parser for simple key-value specs (fallback when PyYAML unavailable)."""
        result = {}
        current_key = None
        for line in content.splitlines():
            if line.strip().startswith("#") or not line.strip():
                continue
            # Top-level key
            match = re.match(r'^(\w+)\s*:\s*(.*)', line)
            if match:
                key = match.group(1)
                value = match.group(2).strip()
                if value:
                    result[key] = value
                else:
                    result[key] = {}
                current_key = key
            elif current_key and line.startswith("  "):
                # Nested content — mark as dict exists
                if not isinstance(result.get(current_key), dict):
                    result[current_key] = {}
                sub_match = re.match(r'^\s+(\w+)\s*:\s*(.*)', line)
                if sub_match:
                    result[current_key][sub_match.group(1)] = sub_match.group(2).strip() or {}
        return result if result else None


def main():
    parser = argparse.ArgumentParser(description="RAMP Screen Spec Validator")
    parser.add_argument("specs_dir", type=Path, help="Path to screen_specs/ directory")
    parser.add_argument("--routes-dir", type=Path, default=None, help="Path to routes/ for coverage check")
    args = parser.parse_args()

    validator = ScreenSpecValidator(args.specs_dir, args.routes_dir)
    exit_code = validator.validate_all()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
