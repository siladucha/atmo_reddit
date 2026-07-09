#!/usr/bin/env python3
"""Agent Pre-Flight Check — runs locally before any production deploy.

This is the automated version of Phase 1 from deploy_protocol.md.
Designed to be run by the AI agent (no Docker, no Redis, no external deps needed).

Usage:
    python scripts/agent_preflight.py
    python scripts/agent_preflight.py --files app/services/smart_scoring.py app/routes/portal.py
    python scripts/agent_preflight.py --all

Exit codes:
    0 = all checks pass, safe to deploy
    1 = one or more checks failed, DO NOT deploy
"""

import argparse
import importlib
import os
import py_compile
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

# ANSI colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"


def ok(msg: str):
    print(f"  {GREEN}✓{RESET} {msg}")


def fail(msg: str):
    print(f"  {RED}✗{RESET} {msg}")


def warn(msg: str):
    print(f"  {YELLOW}⚠{RESET} {msg}")


def header(msg: str):
    print(f"\n{BOLD}── {msg} ──{RESET}")


# ---------------------------------------------------------------------------
# Check 1: Python files compile
# ---------------------------------------------------------------------------

def check_compile(files: list[str]) -> bool:
    header("Syntax Check (py_compile)")
    passed = True
    for f in files:
        path = PROJECT_ROOT / f
        if not path.exists():
            fail(f"{f} — FILE NOT FOUND")
            passed = False
            continue
        if not f.endswith(".py"):
            continue
        try:
            py_compile.compile(str(path), doraise=True)
            ok(f"{f}")
        except py_compile.PyCompileError as e:
            fail(f"{f} — {e}")
            passed = False
    return passed


# ---------------------------------------------------------------------------
# Check 2: Key modules import
# ---------------------------------------------------------------------------

SCIPY_DEPENDENT = {
    "app.services.ab_test.statistical_reporter",
    "app.routes.admin_ab_test",
}


def check_imports(files: list[str]) -> bool:
    header("Import Check")
    passed = True

    # Extract module paths from file paths
    modules = set()
    for f in files:
        if not f.endswith(".py"):
            continue
        if f.startswith("_") or f.startswith("scripts/"):
            continue
        # Convert path to module: app/services/smart_scoring.py → app.services.smart_scoring
        module_path = f.replace("/", ".").replace(".py", "")
        if module_path.startswith("app."):
            modules.add(module_path)

    sys.path.insert(0, str(PROJECT_ROOT))
    os.chdir(PROJECT_ROOT)

    for module in sorted(modules):
        try:
            importlib.import_module(module)
            ok(f"{module}")
        except ImportError as e:
            # scipy is Docker-only, acceptable
            if "scipy" in str(e) or module in SCIPY_DEPENDENT:
                warn(f"{module} — scipy missing (Docker-only, OK)")
            else:
                fail(f"{module} — {e}")
                passed = False
        except Exception as e:
            # Other errors (DB connection, etc.) are acceptable in local-only mode
            error_type = type(e).__name__
            if "OperationalError" in error_type or "Connection" in error_type:
                warn(f"{module} — {error_type} (DB/Redis offline, OK for preflight)")
            else:
                fail(f"{module} — {error_type}: {e}")
                passed = False

    return passed


# ---------------------------------------------------------------------------
# Check 3: Templates exist
# ---------------------------------------------------------------------------

def check_templates(files: list[str]) -> bool:
    header("Template Existence")
    passed = True
    templates = [f for f in files if f.startswith("app/templates/") or f.endswith(".html")]
    if not templates:
        ok("No templates in changeset")
        return True

    for t in templates:
        path = PROJECT_ROOT / t
        if path.exists():
            ok(f"{t}")
        else:
            fail(f"{t} — NOT FOUND")
            passed = False
    return passed


# ---------------------------------------------------------------------------
# Check 4 & 5: Alembic status
# ---------------------------------------------------------------------------

def check_alembic() -> bool:
    header("Alembic Migration Status")
    passed = True

    # Check heads (should be exactly 1)
    try:
        result = subprocess.run(
            [PYTHON, "-m", "alembic", "heads"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            fail(f"alembic heads failed: {result.stderr[:200]}")
            return False

        heads = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
        if len(heads) == 1:
            ok(f"Single head: {heads[0]}")
        elif len(heads) == 0:
            fail("No alembic heads found")
            passed = False
        else:
            fail(f"Multiple heads detected ({len(heads)}): {heads}")
            fail("Run: alembic merge heads -m 'merge'")
            passed = False
    except subprocess.TimeoutExpired:
        fail("alembic heads timed out (DB unreachable?)")
        passed = False
    except FileNotFoundError:
        fail("alembic not found in PATH")
        passed = False

    # Check current = head
    try:
        result = subprocess.run(
            [PYTHON, "-m", "alembic", "current"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            fail(f"alembic current failed: {result.stderr[:200]}")
            return False

        output = result.stdout.strip()
        if "(head)" in output:
            ok(f"Current at head: {output.splitlines()[-1] if output else 'unknown'}")
        else:
            fail(f"NOT at head! Current: {output}")
            fail("Run: alembic upgrade head")
            passed = False
    except subprocess.TimeoutExpired:
        fail("alembic current timed out")
        passed = False

    return passed


# ---------------------------------------------------------------------------
# Check 6: One-off scripts
# ---------------------------------------------------------------------------

def check_oneoff_scripts(files: list[str]) -> bool:
    header("One-Off Scripts Safety")
    scripts = [f for f in files if f.startswith("_") and f.endswith(".py")]
    if not scripts:
        ok("No one-off scripts in changeset")
        return True

    passed = True
    for script in scripts:
        path = PROJECT_ROOT / script
        if not path.exists():
            fail(f"{script} — NOT FOUND")
            passed = False
            continue

        # Compile check
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as e:
            fail(f"{script} — compile error: {e}")
            passed = False
            continue

        # Check for destructive SQL
        content = path.read_text()
        destructive = []
        for i, line in enumerate(content.splitlines(), 1):
            line_upper = line.upper().strip()
            if line_upper.startswith("#") or line_upper.startswith("'") or line_upper.startswith('"'):
                continue
            for keyword in ["DROP TABLE", "DROP COLUMN", "TRUNCATE", "DELETE FROM"]:
                if keyword in line_upper:
                    destructive.append(f"  Line {i}: {line.strip()[:80]}")

        if destructive:
            warn(f"{script} — contains potentially destructive operations:")
            for d in destructive:
                print(f"    {YELLOW}{d}{RESET}")
            warn("Review manually before running on production!")
        else:
            ok(f"{script} — safe (no destructive SQL)")

    return passed


# ---------------------------------------------------------------------------
# Check 7: .env not in changeset
# ---------------------------------------------------------------------------

def check_no_env(files: list[str]) -> bool:
    header("Environment File Safety")
    env_files = [f for f in files if ".env" in f and not f.endswith(".example")]
    if env_files:
        fail(f"Environment files in changeset: {env_files}")
        fail("NEVER deploy .env files! Remove from file list.")
        return False
    ok("No .env files in changeset")
    return True


# ---------------------------------------------------------------------------
# Bonus: Check for common issues
# ---------------------------------------------------------------------------

def check_common_issues(files: list[str]) -> bool:
    header("Common Issue Detection")
    passed = True
    py_files = [f for f in files if f.endswith(".py") and (PROJECT_ROOT / f).exists()]

    for f in py_files:
        content = (PROJECT_ROOT / f).read_text()

        # Check for debug prints/breakpoints
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "breakpoint()" in stripped:
                fail(f"{f}:{i} — breakpoint() left in code!")
                passed = False
            if "import pdb" in stripped:
                fail(f"{f}:{i} — pdb import left in code!")
                passed = False

    if passed:
        ok("No breakpoints or debug imports found")
    return passed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def discover_changed_files() -> list[str]:
    """Try to discover recently changed files via git."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return [f for f in result.stdout.strip().splitlines() if f]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Fallback: git status (uncommitted changes)
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            files = []
            for line in result.stdout.strip().splitlines():
                # Format: XY filename or XY old -> new
                parts = line[3:].split(" -> ")
                files.append(parts[-1])
            return files
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return []


def main():
    parser = argparse.ArgumentParser(description="Agent Pre-Flight Deployment Check")
    parser.add_argument(
        "--files", nargs="*",
        help="Specific files to check (relative to project root)",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Check all Python files in app/",
    )
    parser.add_argument(
        "--skip-alembic", action="store_true",
        help="Skip alembic checks (when DB is offline)",
    )
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  RAMP Agent Pre-Flight Check")
    print(f"  Project: {PROJECT_ROOT}")
    print(f"{'='*60}")

    # Determine files to check
    if args.files:
        files = args.files
    elif args.all:
        files = [
            str(p.relative_to(PROJECT_ROOT))
            for p in PROJECT_ROOT.rglob("app/**/*.py")
        ]
    else:
        files = discover_changed_files()
        if not files:
            print(f"\n  {YELLOW}No changed files detected. Use --files or --all.{RESET}")
            sys.exit(0)

    print(f"\n  Files to check: {len(files)}")
    for f in files[:10]:
        print(f"    • {f}")
    if len(files) > 10:
        print(f"    ... and {len(files) - 10} more")

    # Run checks
    results = []
    results.append(("Syntax", check_compile(files)))
    results.append(("Imports", check_imports(files)))
    results.append(("Templates", check_templates(files)))

    if not args.skip_alembic:
        results.append(("Alembic", check_alembic()))
    else:
        header("Alembic Migration Status")
        warn("Skipped (--skip-alembic)")

    results.append(("Scripts", check_oneoff_scripts(files)))
    results.append(("Env Safety", check_no_env(files)))
    results.append(("Common Issues", check_common_issues(files)))

    # Summary
    print(f"\n{'='*60}")
    passed = sum(1 for _, r in results if r)
    failed = sum(1 for _, r in results if not r)
    total = len(results)

    if failed == 0:
        print(f"  {GREEN}{BOLD}✓ ALL CHECKS PASSED ({passed}/{total}){RESET}")
        print(f"  {GREEN}Ready for deploy (with user permission).{RESET}")
    else:
        print(f"  {RED}{BOLD}✗ {failed} CHECK(S) FAILED{RESET}")
        for name, result in results:
            icon = f"{GREEN}✓{RESET}" if result else f"{RED}✗{RESET}"
            print(f"    {icon} {name}")
        print(f"\n  {RED}DO NOT DEPLOY. Fix issues above first.{RESET}")

    print(f"{'='*60}\n")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
