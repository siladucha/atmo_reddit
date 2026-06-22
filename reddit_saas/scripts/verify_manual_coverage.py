#!/usr/bin/env python3
"""Verify UX Manual Overlay coverage — checks all page routes have YAML content."""

import sys
from pathlib import Path

# Manual screens directory
SCREENS_DIR = Path(__file__).parent.parent / "app" / "manual" / "screens"

# Known page routes (extracted from route analysis)
# Format: route_key that _path_to_key() would produce
KNOWN_PAGE_ROUTES = [
    # Admin panel
    "admin_dashboard",
    "admin_activity",
    "admin_users",
    "admin_clients",
    "admin_avatars",
    "admin_avatar_detail",
    "admin_subreddits",
    "admin_keywords",
    "admin_threads",
    "admin_review",
    "admin_settings",
    "admin_health",
    "admin_ai_costs",
    "admin_audit_logs",
    "admin_trials",
    "admin_billing",
    "admin_posting",
    "admin_discovery",
    "admin_geo",
    "admin_scrape_queue",
    "admin_tasks",
    "admin_inspector",
    # Portal
    "portal_home",
    "portal_review",
    "portal_avatars",
    "portal_avatar_detail",
    "portal_epg",
    "portal_strategy",
    "portal_report",
    "portal_subreddits",
    "portal_keywords",
    "portal_settings",
    # Onboarding
    "onboard_step_1",
    "onboard_step_2",
    "onboard_step_3",
    "onboard_step_4",
    "onboard_step_5",
    "onboard_step_6",
    "onboard_trial",
    # Public / Auth
    "login",
    "guide",
    "index",
    "client_hub",
    # Avatar onboarding
    "avatar_onboard_start",
]


def main():
    """Check coverage and report."""
    # Get all YAML files
    yaml_files = {f.stem for f in SCREENS_DIR.glob("*.yaml")} if SCREENS_DIR.exists() else set()
    
    total = len(KNOWN_PAGE_ROUTES)
    covered = []
    missing = []
    
    for route_key in sorted(KNOWN_PAGE_ROUTES):
        if route_key in yaml_files:
            covered.append(route_key)
        else:
            missing.append(route_key)
    
    # Extra YAML files (not in known routes)
    extra = yaml_files - set(KNOWN_PAGE_ROUTES)
    
    # Report
    pct = (len(covered) / total * 100) if total > 0 else 0
    print(f"\n{'='*60}")
    print(f"UX Manual Coverage Report")
    print(f"{'='*60}")
    print(f"Total page routes:  {total}")
    print(f"Covered (YAML):     {len(covered)} ({pct:.0f}%)")
    print(f"Missing:            {len(missing)}")
    print(f"Extra YAML files:   {len(extra)}")
    
    if missing:
        print(f"\n--- Missing YAML files ---")
        for r in missing:
            print(f"  ✗ {r}")
    
    if extra:
        print(f"\n--- Extra YAML files (bonus coverage) ---")
        for r in sorted(extra):
            print(f"  + {r}")
    
    print(f"\n{'='*60}")
    if missing:
        print(f"FAIL: {len(missing)} routes without manual content")
        sys.exit(1)
    else:
        print(f"PASS: 100% coverage ({len(covered)}/{total} routes)")
        sys.exit(0)


if __name__ == "__main__":
    main()
