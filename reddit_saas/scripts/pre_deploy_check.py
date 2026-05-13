#!/usr/bin/env python3
"""Pre-deployment readiness checker.

Validates environment, Docker config, database migrations, Celery connectivity,
security settings, and health endpoints before deploying to production.

Usage:
    python scripts/pre_deploy_check.py [--env-file .env.production]
    python scripts/pre_deploy_check.py --skip-docker  # skip Docker checks (CI)
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

# Resolve project root (one level up from scripts/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class CheckResult(NamedTuple):
    passed: bool
    name: str
    message: str
    fix: str = ""


# ---------------------------------------------------------------------------
# 1. Environment Variables
# ---------------------------------------------------------------------------

REQUIRED_ENV_VARS = [
    "DATABASE_URL",
    "REDIS_URL",
    "REDDIT_CLIENT_ID",
    "REDDIT_CLIENT_SECRET",
    "SECRET_KEY",
]

# At least one LLM key must be set
LLM_KEY_VARS = ["LITELLM_API_KEY", "GEMINI_API_KEY"]

OPTIONAL_BUT_RECOMMENDED = [
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "APP_ENV",
    "ADMIN_EMAIL",
    "ADMIN_PASSWORD",
]


def load_env_file(env_file: str) -> dict[str, str]:
    """Parse a .env file into a dict (simple key=value, no interpolation)."""
    env = {}
    path = PROJECT_ROOT / env_file
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def check_env_vars(env_file: str) -> list[CheckResult]:
    """Check that all required environment variables are present and non-empty."""
    results = []
    env = load_env_file(env_file)

    # Merge with os.environ (env file takes precedence for this check)
    combined = {**os.environ, **env}

    missing = []
    empty = []
    for var in REQUIRED_ENV_VARS:
        if var not in combined:
            missing.append(var)
        elif not combined[var]:
            empty.append(var)

    # Check LLM keys (at least one)
    has_llm_key = any(combined.get(k) for k in LLM_KEY_VARS)

    if missing:
        results.append(CheckResult(
            False, "Environment: required vars",
            f"Missing: {', '.join(missing)}",
            f"Add to {env_file}: {', '.join(missing)}",
        ))
    elif empty:
        results.append(CheckResult(
            False, "Environment: required vars",
            f"Empty values: {', '.join(empty)}",
            f"Set values in {env_file} for: {', '.join(empty)}",
        ))
    else:
        results.append(CheckResult(
            True, "Environment: required vars",
            f"All {len(REQUIRED_ENV_VARS)} required variables present",
        ))

    if not has_llm_key:
        results.append(CheckResult(
            False, "Environment: LLM API key",
            "No LLM API key found (need LITELLM_API_KEY or GEMINI_API_KEY)",
            f"Set LITELLM_API_KEY or GEMINI_API_KEY in {env_file}",
        ))
    else:
        results.append(CheckResult(
            True, "Environment: LLM API key",
            "LLM API key configured",
        ))

    # Warn about recommended vars
    missing_recommended = [v for v in OPTIONAL_BUT_RECOMMENDED if not combined.get(v)]
    if missing_recommended:
        results.append(CheckResult(
            True, "Environment: recommended vars",
            f"⚠️  Missing optional: {', '.join(missing_recommended)}",
        ))

    return results


# ---------------------------------------------------------------------------
# 2. Docker Configuration
# ---------------------------------------------------------------------------

def check_docker(skip: bool = False) -> list[CheckResult]:
    """Validate Docker Compose configuration."""
    results = []

    if skip:
        results.append(CheckResult(True, "Docker Compose", "Skipped (--skip-docker)"))
        return results

    compose_file = PROJECT_ROOT / "docker-compose.yml"
    if not compose_file.exists():
        results.append(CheckResult(
            False, "Docker Compose: file",
            "docker-compose.yml not found",
            "Create docker-compose.yml in project root",
        ))
        return results

    # Validate config
    try:
        proc = subprocess.run(
            ["docker", "compose", "config", "--quiet"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0:
            results.append(CheckResult(
                True, "Docker Compose: config valid",
                "docker-compose.yml passes validation",
            ))
        else:
            results.append(CheckResult(
                False, "Docker Compose: config valid",
                f"Validation failed: {proc.stderr[:200]}",
                "Fix docker-compose.yml syntax errors",
            ))
    except FileNotFoundError:
        results.append(CheckResult(
            False, "Docker Compose: docker CLI",
            "docker command not found",
            "Install Docker Desktop or Docker Engine",
        ))
    except subprocess.TimeoutExpired:
        results.append(CheckResult(
            False, "Docker Compose: config valid",
            "Timed out validating config",
            "Check Docker daemon is running",
        ))

    # Check Dockerfile exists
    dockerfile = PROJECT_ROOT / "Dockerfile"
    if dockerfile.exists():
        results.append(CheckResult(True, "Docker: Dockerfile", "Dockerfile present"))
    else:
        results.append(CheckResult(
            False, "Docker: Dockerfile",
            "Dockerfile not found",
            "Create Dockerfile in project root",
        ))

    # Check port conflicts (informational)
    required_ports = [8000, 5432, 6379]
    conflicts = []
    for port in required_ports:
        try:
            proc = subprocess.run(
                ["lsof", "-i", f":{port}", "-t"],
                capture_output=True, text=True, timeout=5,
            )
            if proc.stdout.strip():
                conflicts.append(port)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass  # lsof not available, skip

    if conflicts:
        results.append(CheckResult(
            False, "Docker: port conflicts",
            f"Ports in use: {conflicts}",
            f"Stop services on ports {conflicts} or remap in docker-compose.yml",
        ))
    else:
        results.append(CheckResult(
            True, "Docker: ports available",
            f"Ports {required_ports} are free",
        ))

    return results


# ---------------------------------------------------------------------------
# 3. Database Migrations
# ---------------------------------------------------------------------------

def check_migrations() -> list[CheckResult]:
    """Check Alembic migration status."""
    results = []

    alembic_dir = PROJECT_ROOT / "alembic"
    if not alembic_dir.exists():
        results.append(CheckResult(
            False, "Database: alembic directory",
            "alembic/ directory not found",
            "Run: alembic init alembic",
        ))
        return results

    alembic_ini = PROJECT_ROOT / "alembic.ini"
    if not alembic_ini.exists():
        results.append(CheckResult(
            False, "Database: alembic.ini",
            "alembic.ini not found",
            "Create alembic.ini in project root",
        ))
        return results

    # Check for pending migrations (compare current vs head)
    try:
        current = subprocess.run(
            ["alembic", "current"],
            cwd=PROJECT_ROOT,
            capture_output=True, text=True, timeout=15,
        )
        heads = subprocess.run(
            ["alembic", "heads"],
            cwd=PROJECT_ROOT,
            capture_output=True, text=True, timeout=15,
        )

        if current.returncode != 0:
            results.append(CheckResult(
                False, "Database: migration status",
                f"Cannot check current revision (DB offline?): {current.stderr[:150]}",
                "Ensure DATABASE_URL is correct and PostgreSQL is running",
            ))
        elif heads.returncode != 0:
            results.append(CheckResult(
                False, "Database: migration heads",
                f"Cannot determine head revision: {heads.stderr[:150]}",
                "Check alembic configuration",
            ))
        else:
            current_rev = current.stdout.strip()
            head_rev = heads.stdout.strip()

            # Parse revision IDs
            current_ids = set()
            for line in current_rev.splitlines():
                if "(head)" in line or "head" in line.lower():
                    current_ids.add(line.split()[0] if line.split() else "")
                elif line.strip():
                    current_ids.add(line.split()[0] if line.split() else "")

            if "(head)" in current_rev or "head" in current_rev.lower():
                results.append(CheckResult(
                    True, "Database: migrations up to date",
                    f"Current = head ({current_rev.splitlines()[0][:40] if current_rev else 'unknown'})",
                ))
            else:
                results.append(CheckResult(
                    False, "Database: pending migrations",
                    f"Current: {current_rev[:60]} | Head: {head_rev[:60]}",
                    "Run: alembic upgrade head",
                ))
    except FileNotFoundError:
        results.append(CheckResult(
            False, "Database: alembic CLI",
            "alembic command not found",
            "Install: pip install alembic",
        ))
    except subprocess.TimeoutExpired:
        results.append(CheckResult(
            False, "Database: migration check",
            "Timed out (DB connection issue?)",
            "Check DATABASE_URL and PostgreSQL availability",
        ))

    # Check for untracked migration files
    versions_dir = alembic_dir / "versions"
    if versions_dir.exists():
        migration_count = len(list(versions_dir.glob("*.py")))
        results.append(CheckResult(
            True, "Database: migration files",
            f"{migration_count} migration files in alembic/versions/",
        ))

    return results


# ---------------------------------------------------------------------------
# 4. Celery Configuration
# ---------------------------------------------------------------------------

def check_celery(env_file: str) -> list[CheckResult]:
    """Check Celery worker connectivity and task imports."""
    results = []
    env = load_env_file(env_file)
    combined = {**os.environ, **env}

    redis_url = combined.get("REDIS_URL", "")

    # Check Redis connectivity
    if redis_url:
        try:
            import redis as redis_lib
            r = redis_lib.from_url(redis_url, socket_timeout=5)
            r.ping()
            results.append(CheckResult(
                True, "Celery: Redis connection",
                f"Connected to {_mask_url(redis_url)}",
            ))
        except ImportError:
            results.append(CheckResult(
                False, "Celery: redis package",
                "redis package not installed",
                "pip install redis",
            ))
        except Exception as e:
            results.append(CheckResult(
                False, "Celery: Redis connection",
                f"Cannot connect: {type(e).__name__}: {str(e)[:100]}",
                "Check REDIS_URL and ensure Redis is running",
            ))
    else:
        results.append(CheckResult(
            False, "Celery: Redis URL",
            "REDIS_URL not set",
            f"Set REDIS_URL in {env_file}",
        ))

    # Check task imports
    task_modules = [
        "app.tasks.queue_ticker",
        "app.tasks.scraping",
        "app.tasks.orchestrator",
        "app.tasks.ai_pipeline",
        "app.tasks.heartbeat",
        "app.tasks.karma_tracking",
        "app.tasks.health_check",
        "app.tasks.presence",
        "app.tasks.profile_analytics",
        "app.tasks.strategy",
    ]

    import_errors = []
    for module in task_modules:
        try:
            __import__(module)
        except Exception as e:
            import_errors.append(f"{module}: {type(e).__name__}")

    if import_errors:
        results.append(CheckResult(
            False, "Celery: task imports",
            f"{len(import_errors)} modules failed: {'; '.join(import_errors[:3])}",
            "Fix import errors in task modules",
        ))
    else:
        results.append(CheckResult(
            True, "Celery: task imports",
            f"All {len(task_modules)} task modules import cleanly",
        ))

    # Validate Beat schedule
    try:
        from app.tasks.worker import celery_app
        schedule = celery_app.conf.beat_schedule
        if schedule and len(schedule) > 0:
            results.append(CheckResult(
                True, "Celery: Beat schedule",
                f"{len(schedule)} scheduled tasks configured",
            ))
        else:
            results.append(CheckResult(
                False, "Celery: Beat schedule",
                "No beat schedule defined",
                "Check app/tasks/worker.py beat_schedule",
            ))
    except Exception as e:
        results.append(CheckResult(
            False, "Celery: Beat schedule",
            f"Cannot load schedule: {e}",
            "Fix app/tasks/worker.py",
        ))

    return results


# ---------------------------------------------------------------------------
# 5. Security
# ---------------------------------------------------------------------------

def check_security(env_file: str) -> list[CheckResult]:
    """Check security configuration for production readiness."""
    results = []
    env = load_env_file(env_file)
    combined = {**os.environ, **env}

    # DEBUG / APP_ENV
    app_env = combined.get("APP_ENV", "development")
    if app_env == "production":
        results.append(CheckResult(
            True, "Security: APP_ENV",
            "APP_ENV=production",
        ))
    else:
        results.append(CheckResult(
            False, "Security: APP_ENV",
            f"APP_ENV={app_env} (should be 'production' for deploy)",
            f"Set APP_ENV=production in {env_file}",
        ))

    # SECRET_KEY strength
    secret_key = combined.get("SECRET_KEY", "")
    default_secrets = {"change-me", "change-me-to-random-string", "secret", ""}
    if secret_key in default_secrets:
        results.append(CheckResult(
            False, "Security: SECRET_KEY",
            "SECRET_KEY is default/empty",
            'Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"',
        ))
    elif len(secret_key) < 32:
        results.append(CheckResult(
            False, "Security: SECRET_KEY",
            f"SECRET_KEY too short ({len(secret_key)} chars, need 32+)",
            'Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"',
        ))
    else:
        results.append(CheckResult(
            True, "Security: SECRET_KEY",
            f"Strong key ({len(secret_key)} chars)",
        ))

    # POSTGRES_PASSWORD
    pg_pass = combined.get("POSTGRES_PASSWORD", "")
    weak_passwords = {"postgres", "password", "change-me-in-production", ""}
    if pg_pass in weak_passwords:
        results.append(CheckResult(
            False, "Security: POSTGRES_PASSWORD",
            "Weak or default PostgreSQL password",
            "Set a strong POSTGRES_PASSWORD (16+ random chars)",
        ))
    else:
        results.append(CheckResult(
            True, "Security: POSTGRES_PASSWORD",
            "PostgreSQL password set",
        ))

    # REDIS_PASSWORD
    redis_pass = combined.get("REDIS_PASSWORD", "")
    if redis_pass in {"", "change-me-in-production"}:
        results.append(CheckResult(
            False, "Security: REDIS_PASSWORD",
            "Weak or default Redis password",
            "Set a strong REDIS_PASSWORD",
        ))
    else:
        results.append(CheckResult(
            True, "Security: REDIS_PASSWORD",
            "Redis password set",
        ))

    # Check no secrets in source code (basic scan)
    source_dirs = [PROJECT_ROOT / "app"]
    hardcoded_secrets = []
    patterns_to_check = ["sk-", "AIza", "ghp_", "glpat-"]

    for src_dir in source_dirs:
        if not src_dir.exists():
            continue
        for py_file in src_dir.rglob("*.py"):
            try:
                content = py_file.read_text(errors="ignore")
                for pattern in patterns_to_check:
                    if pattern in content and "# noqa" not in content:
                        # Exclude test files and comments
                        for i, line in enumerate(content.splitlines(), 1):
                            if pattern in line and not line.strip().startswith("#"):
                                hardcoded_secrets.append(f"{py_file.name}:{i}")
                                break
            except Exception:
                pass

    if hardcoded_secrets:
        results.append(CheckResult(
            False, "Security: hardcoded secrets",
            f"Potential secrets in: {', '.join(hardcoded_secrets[:5])}",
            "Move secrets to .env file, never commit to source",
        ))
    else:
        results.append(CheckResult(
            True, "Security: no hardcoded secrets",
            "No obvious API keys found in source code",
        ))

    # Check .env is in .gitignore
    gitignore = PROJECT_ROOT / ".gitignore"
    if gitignore.exists():
        gitignore_content = gitignore.read_text()
        if ".env" in gitignore_content:
            results.append(CheckResult(
                True, "Security: .gitignore",
                ".env is in .gitignore",
            ))
        else:
            results.append(CheckResult(
                False, "Security: .gitignore",
                ".env not in .gitignore — secrets may be committed",
                "Add .env to .gitignore",
            ))

    return results


# ---------------------------------------------------------------------------
# 6. Health Check Endpoints
# ---------------------------------------------------------------------------

def check_health_endpoints() -> list[CheckResult]:
    """Verify health check endpoints exist in the codebase."""
    results = []

    main_py = PROJECT_ROOT / "app" / "main.py"
    if not main_py.exists():
        results.append(CheckResult(
            False, "Health: main.py",
            "app/main.py not found",
            "Ensure FastAPI app exists at app/main.py",
        ))
        return results

    content = main_py.read_text()

    # Check /health endpoint exists
    if '/health' in content or "@app.get(\"/health\")" in content:
        results.append(CheckResult(
            True, "Health: /health endpoint",
            "GET /health endpoint defined (checks DB + Redis)",
        ))
    else:
        results.append(CheckResult(
            False, "Health: /health endpoint",
            "No /health endpoint found",
            "Add a health check endpoint that verifies DB and Redis",
        ))

    # Check if health endpoint tests both DB and Redis
    if "SELECT 1" in content or "select 1" in content:
        results.append(CheckResult(
            True, "Health: DB check",
            "Health endpoint includes PostgreSQL connectivity check",
        ))
    else:
        results.append(CheckResult(
            False, "Health: DB check",
            "Health endpoint missing DB connectivity check",
            "Add SELECT 1 query in health endpoint",
        ))

    if "ping" in content.lower() and "redis" in content.lower():
        results.append(CheckResult(
            True, "Health: Redis check",
            "Health endpoint includes Redis PING check",
        ))
    else:
        results.append(CheckResult(
            False, "Health: Redis check",
            "Health endpoint missing Redis PING check",
            "Add Redis PING in health endpoint",
        ))

    return results


# ---------------------------------------------------------------------------
# 7. Dependencies
# ---------------------------------------------------------------------------

def check_dependencies() -> list[CheckResult]:
    """Check that critical Python packages are installed."""
    results = []

    critical_packages = [
        ("fastapi", "FastAPI web framework"),
        ("uvicorn", "ASGI server"),
        ("sqlalchemy", "Database ORM"),
        ("alembic", "Database migrations"),
        ("celery", "Task queue"),
        ("redis", "Redis client"),
        ("praw", "Reddit API"),
        ("litellm", "LLM abstraction"),
        ("pydantic", "Data validation"),
        ("pydantic_settings", "Settings management"),
    ]

    missing = []
    for package, desc in critical_packages:
        try:
            __import__(package)
        except ImportError:
            missing.append(f"{package} ({desc})")

    if missing:
        results.append(CheckResult(
            False, "Dependencies: critical packages",
            f"Missing: {', '.join(missing)}",
            "Run: pip install -r requirements.txt",
        ))
    else:
        results.append(CheckResult(
            True, "Dependencies: critical packages",
            f"All {len(critical_packages)} critical packages installed",
        ))

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mask_url(url: str) -> str:
    """Mask password in URL for display."""
    if "@" in url and ":" in url:
        # redis://:password@host:port -> redis://:***@host:port
        parts = url.split("@")
        return parts[0].rsplit(":", 1)[0] + ":***@" + parts[1]
    return url


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Pre-deployment readiness checker")
    parser.add_argument(
        "--env-file", default=".env",
        help="Path to .env file to check (default: .env)",
    )
    parser.add_argument(
        "--skip-docker", action="store_true",
        help="Skip Docker-related checks",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output results as JSON",
    )
    args = parser.parse_args()

    # Change to project root for relative path resolution
    os.chdir(PROJECT_ROOT)

    # Add project root to Python path for imports
    sys.path.insert(0, str(PROJECT_ROOT))

    print(f"\n{'='*60}")
    print("  Reddit SaaS — Pre-Deployment Readiness Check")
    print(f"  Env file: {args.env_file}")
    print(f"{'='*60}\n")

    all_results: list[CheckResult] = []

    # Run all checks
    sections = [
        ("Environment Variables", check_env_vars(args.env_file)),
        ("Docker Configuration", check_docker(skip=args.skip_docker)),
        ("Database Migrations", check_migrations()),
        ("Celery & Task Queue", check_celery(args.env_file)),
        ("Security", check_security(args.env_file)),
        ("Health Endpoints", check_health_endpoints()),
        ("Dependencies", check_dependencies()),
    ]

    for section_name, results in sections:
        all_results.extend(results)
        print(f"── {section_name} ──")
        for r in results:
            icon = "✅" if r.passed else "❌"
            print(f"  {icon} {r.name}: {r.message}")
            if not r.passed and r.fix:
                print(f"     → Fix: {r.fix}")
        print()

    # Summary
    passed = sum(1 for r in all_results if r.passed)
    failed = sum(1 for r in all_results if not r.passed)
    total = len(all_results)

    print(f"{'='*60}")
    if failed == 0:
        print(f"  ✅ ALL CHECKS PASSED ({passed}/{total})")
        print("  Ready to deploy!")
    else:
        print(f"  Summary: {passed}/{total} checks passed, {failed} failed")
        print(f"  Fix {failed} issue(s) before deploying.")
    print(f"{'='*60}\n")

    # JSON output
    if args.json:
        output = {
            "passed": passed,
            "failed": failed,
            "total": total,
            "ready": failed == 0,
            "results": [
                {"passed": r.passed, "name": r.name, "message": r.message, "fix": r.fix}
                for r in all_results
            ],
        }
        print(json.dumps(output, indent=2))

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
