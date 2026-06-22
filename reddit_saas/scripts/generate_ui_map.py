#!/usr/bin/env python3
"""UI_MAP Generator — RAMP Frontend Observability System.

Scans Jinja2 templates and FastAPI routes to auto-generate UI_MAP.md.

Usage:
    python3 scripts/generate_ui_map.py                        # Print to stdout
    python3 scripts/generate_ui_map.py --output ../UI_MAP.md  # Write to file
    python3 scripts/generate_ui_map.py --check                # Drift detection
    python3 scripts/generate_ui_map.py --check --strict       # Exit 1 on drift
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class PageEntry:
    name: str
    url: str
    template: str
    theme: str
    components_used: list[str] = field(default_factory=list)


@dataclass
class ComponentEntry:
    name: str
    owner_file: str
    used_in_pages: list[str] = field(default_factory=list)
    variants: list[str] = field(default_factory=list)


@dataclass
class DriftItem:
    category: str
    item: str
    detail: str = ""


class UIMapGenerator:
    """Scans templates and routes to produce UI_MAP content."""

    EXTENDS_RE = re.compile(r'\{%[-\s]*extends\s+["\']([^"\']+)["\']')
    INCLUDE_RE = re.compile(r'\{%[-\s]*include\s+["\']([^"\']+)["\']')
    DATA_COMPONENT_RE = re.compile(r'data-component\s*=\s*["\']([^"\']+)["\']')
    DATA_OWNER_RE = re.compile(r'data-owner\s*=\s*["\']([^"\']+)["\']')
    DATA_VARIANT_RE = re.compile(r'data-variant\s*=\s*["\']([^"\']+)["\']')
    ROUTE_DECORATOR_RE = re.compile(
        r'@router\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']'
    )
    TEMPLATE_RESPONSE_RE = re.compile(
        r'TemplateResponse\s*\(\s*(?:name\s*=\s*)?["\']([^"\']+\.html)["\']'
    )

    BASE_TEMPLATES = {"admin_base.html", "client_base.html", "base.html"}
    THEME_MAP = {
        "admin_base.html": "admin",
        "client_base.html": "client",
        "base.html": "public",
    }

    def __init__(self, template_dir: Path, routes_dir: Path):
        self.template_dir = template_dir
        self.routes_dir = routes_dir
        self.pages: list[PageEntry] = []
        self.components: list[ComponentEntry] = []

    def scan(self) -> None:
        route_map = self._scan_routes()
        self._scan_templates(route_map)

    def _scan_routes(self) -> dict[str, str]:
        """Scan route files, return template_name -> URL mapping."""
        template_to_url: dict[str, str] = {}

        for route_file in sorted(self.routes_dir.glob("*.py")):
            if route_file.name == "__init__.py":
                continue
            try:
                file_content = route_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            # Find router prefix
            prefix_match = re.search(
                r'APIRouter\s*\(\s*prefix\s*=\s*["\']([^"\']+)["\']', file_content
            )
            prefix = prefix_match.group(1) if prefix_match else ""

            lines = file_content.splitlines()

            # Find all @router decorator positions
            route_starts = []
            for i, line in enumerate(lines):
                m = self.ROUTE_DECORATOR_RE.search(line)
                if m:
                    route_starts.append((i, m.group(1), m.group(2)))

            # For each GET route, scan body until next route for TemplateResponse
            for idx, (line_num, method, path) in enumerate(route_starts):
                if method != "get":
                    continue

                url = prefix + path if path != "/" else prefix + "/"
                url = re.sub(r'/+', '/', url)
                if not url.startswith("/"):
                    url = "/" + url

                end = route_starts[idx + 1][0] if idx + 1 < len(route_starts) else len(lines)
                body = "\n".join(lines[line_num:end])

                templates_found = self.TEMPLATE_RESPONSE_RE.findall(body)
                for tmpl in templates_found:
                    if tmpl not in template_to_url:
                        template_to_url[tmpl] = url

        return template_to_url

    def _scan_templates(self, route_map: dict[str, str]) -> None:
        """Scan templates, build pages and components lists."""
        component_map: dict[str, ComponentEntry] = {}
        all_templates = sorted(self.template_dir.rglob("*.html"))

        for tmpl_file in all_templates:
            rel_path = str(tmpl_file.relative_to(self.template_dir))

            if rel_path in self.BASE_TEMPLATES or rel_path.startswith("_macros/"):
                continue

            try:
                content = tmpl_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            # Detect theme
            extends_match = self.EXTENDS_RE.search(content)
            theme = "unknown"
            if extends_match:
                base = extends_match.group(1)
                theme = self.THEME_MAP.get(base, "unknown")

            # Extract includes
            includes = self.INCLUDE_RE.findall(content)
            components_used = [inc for inc in includes if not inc.startswith("_macros/")]

            # Extract data-component info
            data_components = self.DATA_COMPONENT_RE.findall(content)
            data_owners = self.DATA_OWNER_RE.findall(content)
            data_variants = self.DATA_VARIANT_RE.findall(content)

            # Partials → register as components
            if "partials/" in rel_path:
                comp_name = data_components[0] if data_components else Path(rel_path).stem.lstrip("_")
                owner = data_owners[0] if data_owners else rel_path
                if comp_name not in component_map:
                    component_map[comp_name] = ComponentEntry(
                        name=comp_name,
                        owner_file=owner,
                        variants=sorted(set(data_variants)),
                    )
                continue

            # Pages
            url = route_map.get(rel_path, "")
            page_name = self._template_to_page_name(rel_path)
            self.pages.append(PageEntry(
                name=page_name,
                url=url or f"(unmapped: {rel_path})",
                template=rel_path,
                theme=theme,
                components_used=components_used,
            ))

            # Track component usage
            for comp_path in components_used:
                comp_stem = Path(comp_path).stem.lstrip("_")
                if comp_stem in component_map:
                    component_map[comp_stem].used_in_pages.append(rel_path)

        self.components = sorted(component_map.values(), key=lambda c: c.name)
        self.pages.sort(key=lambda p: (p.theme, p.url or p.template))

    def _template_to_page_name(self, rel_path: str) -> str:
        name = Path(rel_path).stem
        name = re.sub(r'^admin_', '', name)
        name = name.replace("_", " ").title()
        return name

    def render_markdown(self) -> str:
        lines = []
        lines.append("# UI_MAP — RAMP Platform Interface Registry")
        lines.append("")
        lines.append(f"Last Updated: {date.today().isoformat()}")
        lines.append("")
        lines.append("<!-- AUTO-GENERATED SECTION: DO NOT EDIT BELOW THIS LINE -->")
        lines.append("<!-- Run `make generate-ui-map` to regenerate -->")
        lines.append("")

        admin_pages = [p for p in self.pages if p.theme == "admin"]
        client_pages = [p for p in self.pages if p.theme == "client"]
        public_pages = [p for p in self.pages if p.theme == "public"]
        unknown_pages = [p for p in self.pages if p.theme == "unknown"]

        for section_name, page_list in [
            ("Admin Panel Pages", admin_pages),
            ("Client Portal Pages", client_pages),
            ("Public Pages", public_pages),
            ("Uncategorized Pages", unknown_pages),
        ]:
            if not page_list and section_name == "Uncategorized Pages":
                continue
            lines.append(f"## {section_name}")
            lines.append("")
            if page_list:
                lines.append("| Page | URL | Template | Components |")
                lines.append("|------|-----|----------|------------|")
                for p in page_list:
                    comps = len(p.components_used)
                    lines.append(f"| {p.name} | `{p.url}` | `{p.template}` | {comps} |")
            else:
                lines.append(f"_No {section_name.lower()} detected._")
            lines.append("")

        lines.append("## Component Registry")
        lines.append("")
        if self.components:
            lines.append("| Component | Owner File | Used In | Variants |")
            lines.append("|-----------|-----------|---------|----------|")
            for c in self.components:
                used_count = len(c.used_in_pages)
                variants = ", ".join(c.variants) if c.variants else "—"
                lines.append(f"| `{c.name}` | `{c.owner_file}` | {used_count} pages | {variants} |")
        else:
            lines.append("_No components with data-component markers detected yet._")
        lines.append("")
        lines.append("<!-- END AUTO-GENERATED -->")
        lines.append("")
        lines.append("## Navigation Paths")
        lines.append("")
        lines.append("_(Manual section — add navigation paths from login to each page)_")
        lines.append("")
        lines.append("## Component Descriptions")
        lines.append("")
        lines.append("_(Manual section — add one-line descriptions for each component)_")
        lines.append("")
        return "\n".join(lines)

    def diff_against(self, existing_path: Path) -> list[DriftItem]:
        drift: list[DriftItem] = []
        if not existing_path.exists():
            drift.append(DriftItem("missing_file", str(existing_path), "UI_MAP.md does not exist"))
            return drift

        existing_content = existing_path.read_text(encoding="utf-8")

        for page in self.pages:
            if page.template not in existing_content:
                drift.append(DriftItem(
                    "new_page", page.template,
                    f"Page '{page.name}' ({page.url}) not documented in UI_MAP"
                ))

        for comp in self.components:
            if comp.name not in existing_content:
                drift.append(DriftItem(
                    "new_component", comp.name,
                    f"Component '{comp.name}' (owner: {comp.owner_file}) not documented"
                ))

        return drift


def main():
    parser = argparse.ArgumentParser(description="RAMP UI_MAP Generator")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--template-dir", type=Path, default=Path("app/templates"))
    parser.add_argument("--routes-dir", type=Path, default=Path("app/routes"))
    args = parser.parse_args()

    generator = UIMapGenerator(args.template_dir, args.routes_dir)
    generator.scan()

    if args.check:
        ui_map_path = args.output or Path("../UI_MAP.md")
        if not ui_map_path.is_absolute():
            ui_map_path = Path.cwd() / ui_map_path

        drift_items = generator.diff_against(ui_map_path)

        if drift_items:
            print(f"\nUI MAP DRIFT: {len(drift_items)} issue(s) found\n")
            for item in drift_items:
                print(f"  [{item.category}] {item.item}")
                if item.detail:
                    print(f"    -> {item.detail}")
            print()
            drift_mode = os.environ.get("UI_MAP_DRIFT_MODE", "warn")
            if args.strict or drift_mode == "error":
                print("DRIFT CHECK: FAILED (strict mode)")
                sys.exit(1)
            else:
                print("DRIFT CHECK: WARNING (non-blocking)")
                sys.exit(0)
        else:
            print("UI MAP DRIFT: No drift detected")
            sys.exit(0)
    else:
        markdown = generator.render_markdown()
        if args.output:
            args.output.write_text(markdown, encoding="utf-8")
            print(f"UI_MAP written to {args.output}")
            print(f"  Pages: {len(generator.pages)}")
            print(f"  Components: {len(generator.components)}")
        else:
            print(markdown)


if __name__ == "__main__":
    main()
