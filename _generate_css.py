#!/usr/bin/env python3
"""
CSS Generator — Canonical State Snapshot
Generates .kiro/state/current.yaml from live system state.

Usage:
  Local (reads local DB + env):
    cd reddit_saas && python ../_generate_css.py

  Remote (reads production via SSH):
    python _generate_css.py --remote

Requires: pyyaml (pip install pyyaml)
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml required. Install: pip install pyyaml")
    sys.exit(1)


IST = timezone(timedelta(hours=3))
PROJECT_ROOT = Path(__file__).resolve().parent
REDDIT_SAAS = PROJECT_ROOT / "reddit_saas"
STATE_FILE = PROJECT_ROOT / ".kiro" / "state" / "current.yaml"


def get_version() -> str:
    """Read VERSION file."""
    version_file = REDDIT_SAAS / "VERSION"
    if version_file.exists():
        return version_file.read_text().strip()
    return "unknown"


def run_local_sql(query: str) -> str:
    """Run SQL query against local PostgreSQL."""
    try:
        result = subprocess.run(
            ["psql", "-U", "reddit_saas_user", "-d", "reddit_saas",
             "-t", "-A", "-c", query],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def run_remote_sql(query: str) -> str:
    """Run SQL query on production via SSH."""
    docker_cmd = (
        f"docker compose exec -T db psql -U reddit_saas_user -d reddit_saas "
        f"-t -A -c \"{query}\""
    )
    try:
        result = subprocess.run(
            ["ssh", "ramp", f"cd /app && {docker_cmd}"],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def query_avatar_stats(run_sql) -> dict:
    """Get avatar fleet statistics."""
    total = run_sql("SELECT COUNT(*) FROM avatars WHERE is_active = true")
    frozen = run_sql("SELECT COUNT(*) FROM avatars WHERE is_frozen = true AND is_active = true")
    shadowbanned = run_sql(
        "SELECT COUNT(*) FROM avatars WHERE is_shadowbanned = true AND is_active = true"
    )
    with_email = run_sql(
        "SELECT COUNT(*) FROM avatars WHERE executor_email IS NOT NULL "
        "AND executor_email_verified = true AND is_active = true"
    )

    frozen_list = run_sql(
        "SELECT username, freeze_reason, frozen_at::date "
        "FROM avatars WHERE is_frozen = true AND is_active = true "
        "ORDER BY frozen_at DESC"
    )

    frozen_avatars = []
    for line in frozen_list.split("\n"):
        if "|" in line:
            parts = line.split("|")
            frozen_avatars.append({
                "name": parts[0].strip(),
                "reason": parts[1].strip() if len(parts) > 1 else "unknown",
                "since": parts[2].strip() if len(parts) > 2 else "unknown",
            })

    return {
        "total_active": int(total) if total.isdigit() else 0,
        "frozen": int(frozen) if frozen.isdigit() else 0,
        "shadowbanned": int(shadowbanned) if shadowbanned.isdigit() else 0,
        "with_executor_email": int(with_email) if with_email.isdigit() else 0,
        "frozen_list": frozen_avatars,
    }


def query_client_stats(run_sql) -> dict:
    """Get client statistics."""
    total = run_sql("SELECT COUNT(*) FROM clients WHERE is_active = true")
    by_plan = run_sql(
        "SELECT plan_type, COUNT(*) FROM clients WHERE is_active = true "
        "GROUP BY plan_type ORDER BY plan_type"
    )

    plan_distribution = {}
    for line in by_plan.split("\n"):
        if "|" in line:
            parts = line.split("|")
            plan_distribution[parts[0].strip()] = int(parts[1].strip())

    return {
        "total_active": int(total) if total.isdigit() else 0,
        "plan_distribution": plan_distribution,
    }


def query_kill_switches(run_sql) -> dict:
    """Read system settings (kill switches)."""
    switches = run_sql(
        "SELECT key, value FROM system_settings "
        "WHERE key IN ("
        "'pipeline_enabled', 'generation_enabled', 'scrape_enabled', "
        "'auto_posting_enabled', 'email_tasks_enabled', "
        "'fitness_gate_enabled', 'cqs_check_tasks_enabled', 'epg2_enabled'"
        ") ORDER BY key"
    )

    result = {}
    for line in switches.split("\n"):
        if "|" in line:
            parts = line.split("|")
            key = parts[0].strip()
            val = parts[1].strip().lower()
            result[key] = val in ("true", "1", "yes")

    return result


def query_open_incidents(run_sql) -> list:
    """Detect open incidents from DB state."""
    incidents = []

    # Frozen avatars with reasons
    frozen = run_sql(
        "SELECT username, freeze_reason, health_status "
        "FROM avatars WHERE is_frozen = true AND is_active = true"
    )
    for line in frozen.split("\n"):
        if "|" in line:
            parts = line.split("|")
            incidents.append({
                "avatar": parts[0].strip(),
                "type": parts[2].strip() if len(parts) > 2 else "frozen",
                "reason": parts[1].strip() if len(parts) > 1 else "unknown",
            })

    return incidents


def build_css(run_sql, method: str) -> dict:
    """Build the full CSS document."""
    now = datetime.now(IST).isoformat()

    avatar_stats = query_avatar_stats(run_sql)
    client_stats = query_client_stats(run_sql)
    kill_switches = query_kill_switches(run_sql)
    incidents = query_open_incidents(run_sql)

    css = {
        "meta": {
            "version": get_version(),
            "last_reconciled": now,
            "reconciled_by": method,
            "staleness_threshold_hours": 48,
            "generator": "_generate_css.py",
        },
        "infrastructure": {
            "environment": "production" if method == "remote" else "development",
            "domain": "gorampit.com",
            "server": "161.35.27.165",
            "timezone": "Asia/Jerusalem",
        },
        "application": {
            "posting_disabled": True,  # env-level, not in DB
            "kill_switches": kill_switches,
        },
        "avatars": {
            "total_active": avatar_stats["total_active"],
            "frozen": avatar_stats["frozen"],
            "shadowbanned": avatar_stats["shadowbanned"],
            "with_executor_email": avatar_stats["with_executor_email"],
            "frozen_list": avatar_stats["frozen_list"],
        },
        "clients": client_stats,
        "open_incidents": incidents,
    }

    return css


def write_css(css: dict):
    """Write CSS to .kiro/state/current.yaml."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    header = (
        "# Canonical State Snapshot (CSS)\n"
        f"# Generated: {css['meta']['last_reconciled']}\n"
        f"# Method: {css['meta']['reconciled_by']}\n"
        "#\n"
        "# This file is DERIVED. It is NOT a source of truth.\n"
        "# Priority: ops > system > steering > CSS\n"
        "# Staleness rule: treat as inaccurate if >48h old.\n\n"
    )

    with open(STATE_FILE, "w") as f:
        f.write(header)
        yaml.dump(css, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print(f"✓ CSS written to {STATE_FILE}")
    print(f"  Version: {css['meta']['version']}")
    print(f"  Reconciled: {css['meta']['last_reconciled']}")
    print(f"  Avatars: {css['avatars']['total_active']} active, {css['avatars']['frozen']} frozen")
    print(f"  Clients: {css['clients']['total_active']} active")


def main():
    parser = argparse.ArgumentParser(description="Generate CSS from live system state")
    parser.add_argument("--remote", action="store_true", help="Query production via SSH")
    args = parser.parse_args()

    if args.remote:
        print("Generating CSS from PRODUCTION (ssh ramp)...")
        run_sql = run_remote_sql
        method = "remote"
    else:
        print("Generating CSS from LOCAL database...")
        run_sql = run_local_sql
        method = "local"

    css = build_css(run_sql, method)
    write_css(css)


if __name__ == "__main__":
    main()
