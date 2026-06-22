#!/usr/bin/env python3
"""UI Lint Script — RAMP Frontend Observability System.

Scans Jinja2 templates for style violations:
1. Inline style="" attributes
2. Arbitrary Tailwind bracket notation values
3. Missing component markers on included partials

Usage:
    python scripts/lint_ui.py app/templates/
    python scripts/lint_ui.py app/templates/ --allowlist ui_lint_allowlist.txt
    python scripts/lint_ui.py app/templates/ --fix
"""

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Violation:
    file: str
    line: int
    violation_type: str  # inline-style | arbitrary-tailwind | missing-marker
    snippet: str
    suggested_fix: str = ""

    def __str__(self) -> str:
        s = f"{self.file}:{self.line}:{self.violation_type}: {self.snippet[:120]}"
        if self.suggested_fix:
            s += f"\n  → fix: {self.suggested_fix}"
        return s


@dataclass
class AllowlistEntry:
    pattern: str  # file path glob or exact path
    violation_type: str  # inline-style | arbitrary-tailwind | missing-marker | *
    justification: str = ""


class UILinter:
    """Main UI linter class."""

    # Regex for inline style attributes
    INLINE_STYLE_RE = re.compile(r'\bstyle\s*=\s*["\']', re.IGNORECASE)

    # Regex for arbitrary Tailwind bracket values
    ARBITRARY_TW_RE = re.compile(
        r'(?:^|[\s"\'`])('
        r'(?:text|bg|border|p|px|py|pt|pb|pl|pr|m|mx|my|mt|mb|ml|mr|'
        r'w|h|min-w|min-h|max-w|max-h|gap|rounded|top|left|right|bottom|'
        r'inset|opacity|z|tracking|leading|indent|basis|grow|shrink|'
        r'columns|rows|col|row|auto-cols|auto-rows|grid-cols|grid-rows|'
        r'stroke|fill|ring|outline|shadow|blur|brightness|contrast|'
        r'hue-rotate|saturate|scale|rotate|translate|skew|origin|'
        r'duration|delay|ease|from|via|to|divide|space|aspect)-\['
        r')',
        re.IGNORECASE,
    )

    # Regex for {% include "..." %} directives
    INCLUDE_RE = re.compile(r'\{%[-\s]*include\s+["\']([^"\']+)["\']')

    # Jinja2 dynamic style patterns to ignore (e.g., style="width: {{ pct }}%")
    DYNAMIC_STYLE_RE = re.compile(r'style\s*=\s*["\'][^"\']*\{\{[^}]+\}\}')

    def __init__(self, template_dir: Path, allowlist_path: Path | None = None):
        self.template_dir = template_dir
        self.violations: list[Violation] = []
        self.allowlist: list[AllowlistEntry] = []
        if allowlist_path and allowlist_path.exists():
            self._load_allowlist(allowlist_path)

    def _load_allowlist(self, path: Path) -> None:
        """Load allowlist entries from file."""
        for raw_line in path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            # Format: path/glob:violation-type  # justification
            justification = ""
            if "#" in line:
                line, justification = line.rsplit("#", 1)
                line = line.strip()
                justification = justification.strip()
            if ":" in line:
                pattern, vtype = line.rsplit(":", 1)
                self.allowlist.append(
                    AllowlistEntry(
                        pattern=pattern.strip(),
                        violation_type=vtype.strip(),
                        justification=justification,
                    )
                )

    def _is_allowlisted(self, violation: Violation) -> bool:
        """Check if a violation is covered by the allowlist."""
        from fnmatch import fnmatch

        for entry in self.allowlist:
            if entry.violation_type not in ("*", violation.violation_type):
                continue
            if fnmatch(violation.file, entry.pattern) or fnmatch(
                violation.file, f"*/{entry.pattern}"
            ):
                return True
        return False

    def run_all_checks(self) -> int:
        """Run all lint checks. Returns exit code (0=pass, 1=violations)."""
        html_files = sorted(self.template_dir.rglob("*.html"))

        for html_file in html_files:
            try:
                content = html_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                print(f"WARNING: Cannot read {html_file}: {e}", file=sys.stderr)
                continue

            rel_path = str(html_file.relative_to(self.template_dir.parent))
            lines = content.splitlines()

            self._check_inline_styles(rel_path, lines)
            self._check_arbitrary_tailwind(rel_path, lines)
            self._check_component_markers(rel_path, content, html_file)

        self._check_duplicate_patterns()

        # Filter out allowlisted violations
        unallowlisted = [v for v in self.violations if not self._is_allowlisted(v)]

        if unallowlisted:
            print(f"\n{'='*60}")
            print(f"UI LINT: {len(unallowlisted)} violation(s) found")
            print(f"{'='*60}\n")
            for v in unallowlisted:
                print(v)
                print()
            print(f"Total: {len(unallowlisted)} violations ({len(self.violations) - len(unallowlisted)} allowlisted)")
            return 1
        else:
            allowlisted_count = len(self.violations)
            print(f"UI LINT: PASS ({allowlisted_count} allowlisted violation(s) skipped)")
            return 0

    def _check_inline_styles(self, rel_path: str, lines: list[str]) -> None:
        """Check for inline style="" attributes."""
        for i, line in enumerate(lines, start=1):
            if self.INLINE_STYLE_RE.search(line):
                # Skip if it's a dynamic Jinja2 style (contains {{ }})
                if self.DYNAMIC_STYLE_RE.search(line):
                    continue
                # Skip if inside a Jinja2 comment
                if "{#" in line:
                    continue
                snippet = line.strip()
                self.violations.append(
                    Violation(
                        file=rel_path,
                        line=i,
                        violation_type="inline-style",
                        snippet=snippet,
                        suggested_fix="Use Tailwind utility classes or CSS custom properties from tokens.css",
                    )
                )

    def _check_arbitrary_tailwind(self, rel_path: str, lines: list[str]) -> None:
        """Check for arbitrary Tailwind bracket notation."""
        for i, line in enumerate(lines, start=1):
            # Skip Jinja2 comments
            if "{#" in line:
                continue
            # Skip lines that are pure CSS (inside <style> blocks)
            stripped = line.strip()
            if stripped.startswith("/*") or stripped.startswith("*") or stripped.endswith("*/"):
                continue

            matches = self.ARBITRARY_TW_RE.findall(line)
            for match in matches:
                # Skip if inside a Jinja2 expression (e.g., class="{{ ... }}")
                # These are usually dynamic and acceptable
                snippet = line.strip()
                self.violations.append(
                    Violation(
                        file=rel_path,
                        line=i,
                        violation_type="arbitrary-tailwind",
                        snippet=snippet,
                        suggested_fix=f"Replace '{match}...' with a named design token from tokens.css",
                    )
                )

    def _check_component_markers(
        self, rel_path: str, content: str, file_path: Path
    ) -> None:
        """Check that included partials have data-component markers."""
        includes = self.INCLUDE_RE.findall(content)

        for include_path in includes:
            # Skip macros and non-partial includes
            if include_path.startswith("_macros/"):
                continue
            # Resolve the partial file
            partial_file = self.template_dir / include_path
            if not partial_file.exists():
                # Try relative to templates dir
                partial_file = file_path.parent / include_path
            if not partial_file.exists():
                continue

            try:
                partial_content = partial_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            # Check if the first non-empty, non-comment HTML element has data-component
            # Simple heuristic: look for data-component in first 10 lines
            first_lines = partial_content[:2000]
            if "data-component" not in first_lines and "component_attrs" not in first_lines:
                # Find the line in the original file where the include is
                for i, line in enumerate(content.splitlines(), start=1):
                    if include_path in line and "include" in line:
                        self.violations.append(
                            Violation(
                                file=rel_path,
                                line=i,
                                violation_type="missing-marker",
                                snippet=f'{{% include "{include_path}" %}} — missing data-component',
                                suggested_fix=f"Add component_attrs() macro to root element of {include_path}",
                            )
                        )
                        break


    def _check_duplicate_patterns(self) -> None:
        """Detect duplicate DOM patterns across templates (same structure 3+ times)."""
        from collections import defaultdict
        import hashlib

        # Build fingerprints: extract tag+class patterns from each file
        # A "pattern" is a sequence of 3+ lines with same tag structure
        pattern_locations: dict[str, list[tuple[str, int]]] = defaultdict(list)

        html_files = sorted(self.template_dir.rglob("*.html"))
        for html_file in html_files:
            rel_path = str(html_file.relative_to(self.template_dir.parent))
            # Skip partials (they ARE the extracted components)
            if "partials/" in rel_path or "_macros/" in rel_path:
                continue
            try:
                lines = html_file.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue

            # Sliding window of 4 lines — fingerprint by tag structure
            for i in range(len(lines) - 3):
                window = lines[i:i+4]
                # Extract just the tag names and class attributes
                tags = []
                for line in window:
                    stripped = line.strip()
                    if stripped.startswith("<") and not stripped.startswith("<!") and not stripped.startswith("{"):
                        # Extract tag name
                        tag_match = re.match(r'<(\w+)', stripped)
                        # Extract class attribute
                        class_match = re.search(r'class="([^"]*)"', stripped)
                        if tag_match:
                            tag_str = tag_match.group(1)
                            if class_match:
                                # Normalize: sort classes, remove dynamic jinja
                                classes = class_match.group(1)
                                classes = re.sub(r'\{\{[^}]*\}\}', '', classes)
                                classes = re.sub(r'\{%[^%]*%\}', '', classes)
                                tag_str += "." + " ".join(sorted(classes.split()))
                            tags.append(tag_str)

                if len(tags) >= 3:
                    fingerprint = hashlib.md5("|".join(tags).encode()).hexdigest()[:12]
                    pattern_locations[fingerprint].append((rel_path, i + 1))

        # Report patterns that appear 3+ times in different files
        for fingerprint, locations in pattern_locations.items():
            unique_files = set(loc[0] for loc in locations)
            if len(unique_files) >= 3:
                # Only report once per pattern
                files_str = ", ".join(sorted(unique_files)[:3])
                self.violations.append(
                    Violation(
                        file=locations[0][0],
                        line=locations[0][1],
                        violation_type="duplicate-pattern",
                        snippet=f"Similar DOM structure found in {len(unique_files)} files: {files_str}...",
                        suggested_fix="Consider extracting to a shared partial/component",
                    )
                )


def main():
    parser = argparse.ArgumentParser(description="RAMP UI Lint — Frontend Observability")
    parser.add_argument("template_dir", type=Path, help="Path to templates directory")
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=None,
        help="Path to allowlist file (default: ui_lint_allowlist.txt in parent dir)",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Show suggested fixes for auto-fixable violations",
    )
    args = parser.parse_args()

    # Auto-detect allowlist if not specified
    allowlist_path = args.allowlist
    if allowlist_path is None:
        candidate = args.template_dir.parent / "ui_lint_allowlist.txt"
        if candidate.exists():
            allowlist_path = candidate

    linter = UILinter(args.template_dir, allowlist_path)
    exit_code = linter.run_all_checks()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
