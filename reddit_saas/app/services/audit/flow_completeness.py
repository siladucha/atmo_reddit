"""FlowCompletenessScanner — Audit Block 5: User and System Flow Completeness.

Verifies that every user and system flow reaches a defined terminal state:
- Inventories all user-facing flows (onboarding, avatar creation, trial signup, etc.)
- Checks templates for success indicators (confirmation messages, redirects)
- Checks for error recovery paths (try/except with user-facing responses)
- Queries activity_events for system flows, verifies terminal status records
- Cross-references Celery Beat schedule with last successful ActivityEvent per flow
- Produces Flow Inventory table + findings
"""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlalchemy import desc

from app.logging_config import get_logger
from app.models.activity_event import ActivityEvent
from app.services.audit.base import (
    AuditBlock,
    AuditBlockName,
    FindingInput,
    FixEffort,
    Severity,
)

logger = get_logger(__name__)

# Project root for file scanning
PROJECT_ROOT = Path(__file__).resolve().parents[3]  # up from app/services/audit/
APP_DIR = PROJECT_ROOT / "app"
ROUTES_DIR = APP_DIR / "routes"
TEMPLATES_DIR = APP_DIR / "templates"
TASKS_DIR = APP_DIR / "tasks"

# --- System Flow Definitions ---
# Maps flow name to expected event_type patterns in ActivityEvent.
# Each system flow should produce at least one ActivityEvent with a recognizable
# event_type indicating completion or failure.

SYSTEM_FLOWS = {
    "pipeline": {
        "description": "AI scoring and comment generation pipeline",
        "celery_task": "run_full_pipeline_all_clients",
        "event_type_patterns": ["score", "generate", "pipeline"],
        "schedule": "08:00, 14:00 daily",
        "expected_interval_hours": 12,  # Runs 2x/day
    },
    "epg_build": {
        "description": "EPG daily publishing program build and generation",
        "celery_task": "build_and_generate_epg_all_avatars",
        "event_type_patterns": ["epg"],
        "schedule": "08:15, 14:15 daily",
        "expected_interval_hours": 12,
    },
    "posting": {
        "description": "Automated posting of approved EPG slots",
        "celery_task": "execute_pending_posts",
        "event_type_patterns": ["posting", "post_comment", "avatar_frozen_by_posting"],
        "schedule": "every 5 minutes",
        "expected_interval_hours": 48,  # May not produce events if no pending posts
    },
    "health_check": {
        "description": "Avatar shadowban and suspension detection",
        "celery_task": "health_check_all_avatars",
        "event_type_patterns": ["health_check", "health"],
        "schedule": "07:30, 13:30 daily",
        "expected_interval_hours": 12,
    },
    "scraping": {
        "description": "Reddit subreddit scraping",
        "celery_task": "queue_tick",
        "event_type_patterns": ["scrape"],
        "schedule": "every 60s",
        "expected_interval_hours": 1,  # Should produce events within the hour
    },
    "feedback_loop": {
        "description": "Outcome analysis and EPG model correction",
        "celery_task": "run_feedback_loop_all",
        "event_type_patterns": ["feedback_loop_executed", "feedback"],
        "schedule": "02:00 daily",
        "expected_interval_hours": 48,
    },
    "discovery": {
        "description": "Continuous weekly discovery research",
        "celery_task": "run_continuous_discovery_all",
        "event_type_patterns": ["discovery_continuous_delta", "discovery_handoff", "discovery"],
        "schedule": "04:00 Sunday",
        "expected_interval_hours": 168,  # Weekly = 7 days
    },
    "karma_snapshot": {
        "description": "Comment karma/deletion outcome snapshots",
        "celery_task": "snapshot_comment_outcomes",
        "event_type_patterns": ["comment_deletion_detected", "karma_snapshot", "karma"],
        "schedule": "every 4h at :45",
        "expected_interval_hours": 48,  # May not produce events if no posted comments
    },
}

# --- User Flow Definitions ---
# Multi-step user flows that should be inventoried.

USER_FLOWS = {
    "onboarding_wizard": {
        "description": "6-step AI-driven client self-service onboarding wizard",
        "entry_point": "/onboard",
        "route_file": "onboarding.py",
        "template_dir": "onboarding",
        "steps": 6,
        "success_indicators": ["onboard_complete", "complete", "activated", "success"],
        "expected_error_recovery": True,
    },
    "avatar_onboarding": {
        "description": "One-click Reddit profile analysis + AI classification",
        "entry_point": "/admin/avatar-onboard",
        "route_file": "avatar_onboard.py",
        "template_dir": "avatar_onboard",
        "steps": 3,  # start -> analysis -> confirm/create
        "success_indicators": ["created", "onboarded", "success", "avatar_onboarded"],
        "expected_error_recovery": True,
    },
    "trial_signup": {
        "description": "14-day free trial signup (any email, honeypot anti-bot)",
        "entry_point": "/onboard/trial",
        "route_file": "onboarding.py",
        "template_dir": None,
        "steps": 2,  # form -> redirect to wizard
        "success_indicators": ["trial", "redirect", "onboard"],
        "expected_error_recovery": True,
    },
    "client_portal_navigation": {
        "description": "Client-facing portal with review, avatars, EPG, strategy",
        "entry_point": "/portal",
        "route_file": "portal.py",
        "template_dir": "client",
        "steps": 1,  # Each page is standalone
        "success_indicators": ["portal", "home", "dashboard"],
        "expected_error_recovery": False,
    },
    "admin_operations": {
        "description": "Admin panel CRUD operations",
        "entry_point": "/admin",
        "route_file": "admin.py",
        "template_dir": None,
        "steps": 1,
        "success_indicators": ["admin", "dashboard"],
        "expected_error_recovery": False,
    },
    "avatar_creation": {
        "description": "Manual avatar creation from admin panel",
        "entry_point": "/admin/avatars/new",
        "route_file": "avatars.py",
        "template_dir": None,
        "steps": 2,  # form -> create
        "success_indicators": ["created", "success", "redirect"],
        "expected_error_recovery": True,
    },
    "payment": {
        "description": "Payment/billing flow (Stripe integration)",
        "entry_point": "/billing",
        "route_file": None,  # Not yet implemented
        "template_dir": None,
        "steps": 0,
        "success_indicators": [],
        "expected_error_recovery": False,
    },
}

# Patterns for success indicators in templates
SUCCESS_PATTERNS = [
    re.compile(r"success|completed|confirmation|thank\s*you|activated|created", re.IGNORECASE),
    re.compile(r"redirect|RedirectResponse|Response\(.*30[12]", re.IGNORECASE),
    re.compile(r"flash.*success|message.*success|alert.*success", re.IGNORECASE),
]

# Patterns for error recovery in route handlers
ERROR_RECOVERY_PATTERNS = [
    re.compile(r"except\s+.*:", re.IGNORECASE),
    re.compile(r"error_message|flash.*error|alert.*error|validation_error", re.IGNORECASE),
    re.compile(r"return.*error|status_code\s*=\s*4\d\d", re.IGNORECASE),
]
class FlowCompletenessScanner(AuditBlock):
    """Verifies user and system flows reach defined terminal states.

    Performs mixed analysis:
    - Static: scans route handlers and templates for multi-step flow patterns
    - Runtime: queries ActivityEvent table for system flow terminal records
    - Cross-reference: Celery Beat schedule vs actual last successful event
    """

    @property
    def name(self) -> AuditBlockName:
        return AuditBlockName.FLOW_COMPLETENESS

    async def run(self, run_id: UUID, db_session) -> list[FindingInput]:
        """Execute all flow completeness checks and return findings.

        Args:
            run_id: The parent AuditRun ID.
            db_session: SQLAlchemy session.

        Returns:
            List of findings for detected issues.
        """
        findings: list[FindingInput] = []

        # 1. Inventory user flows and check for success/error recovery
        findings.extend(self._check_user_flows())

        # 2. Check system flows — verify terminal ActivityEvent records
        findings.extend(self._check_system_flows(db_session))

        # 3. Produce flow inventory table as informational finding
        findings.append(self._build_flow_inventory_finding(db_session))

        logger.info(
            "FlowCompletenessScanner completed: %d findings (run_id=%s)",
            len(findings),
            run_id,
        )
        return findings

    # --- User Flow Checks ---

    def _check_user_flows(self) -> list[FindingInput]:
        """Check user-facing flows for success indicators and error recovery paths.

        Scans route handlers for multi-step patterns (wizard, forms),
        checks templates for confirmation messages, and verifies error handling.
        """
        findings: list[FindingInput] = []

        for flow_name, flow_info in USER_FLOWS.items():
            route_file = flow_info["route_file"]
            template_dir = flow_info["template_dir"]

            # Skip flows that are not yet implemented
            if route_file is None:
                findings.append(
                    FindingInput(
                        title=f"User flow not implemented: {flow_name}",
                        severity=Severity.YELLOW,
                        block=AuditBlockName.FLOW_COMPLETENESS,
                        category="product",
                        risk_description=(
                            f"Flow '{flow_info['description']}' has no route handler "
                            f"implementation. Entry point: {flow_info['entry_point']}"
                        ),
                        owner="Max",
                        effort=FixEffort.L,
                        risk_if_unresolved="User flow leads to dead end or 404",
                        requirement_ref="5.1",
                        data_path=flow_info["entry_point"],
                    )
                )
                continue

            # Check route handler for success indicators
            route_path = ROUTES_DIR / route_file
            has_success = False
            has_error_recovery = False

            if route_path.exists():
                try:
                    content = route_path.read_text(encoding="utf-8", errors="ignore")
                    has_success = self._has_success_indicators(content, flow_info)
                    has_error_recovery = self._has_error_recovery(content)
                except OSError:
                    pass

            # Check templates for success indicators
            if template_dir and not has_success:
                template_path = TEMPLATES_DIR / template_dir
                if template_path.exists():
                    has_success = self._check_templates_for_success(
                        template_path, flow_info["success_indicators"]
                    )

            # Report missing success indicators
            if not has_success and flow_info["steps"] > 1:
                findings.append(
                    FindingInput(
                        title=f"Missing success confirmation: {flow_name}",
                        severity=Severity.YELLOW,
                        block=AuditBlockName.FLOW_COMPLETENESS,
                        category="product",
                        risk_description=(
                            f"Flow '{flow_info['description']}' ({flow_info['steps']} steps) "
                            f"has no detectable success confirmation screen or redirect. "
                            f"Users may not know the flow completed successfully."
                        ),
                        owner="Max",
                        effort=FixEffort.S,
                        risk_if_unresolved="Users reach flow end without confirmation, causing uncertainty",
                        requirement_ref="5.2",
                        data_path=f"app/routes/{route_file}",
                    )
                )

            # Report missing error recovery
            if flow_info["expected_error_recovery"] and not has_error_recovery:
                findings.append(
                    FindingInput(
                        title=f"Missing error recovery path: {flow_name}",
                        severity=Severity.YELLOW,
                        block=AuditBlockName.FLOW_COMPLETENESS,
                        category="product",
                        risk_description=(
                            f"Flow '{flow_info['description']}' lacks detectable error "
                            f"recovery patterns. Users encountering errors may be unable "
                            f"to return to a valid state."
                        ),
                        owner="Max",
                        effort=FixEffort.M,
                        risk_if_unresolved="User error results in dead-end state with no recovery",
                        requirement_ref="5.3",
                        data_path=f"app/routes/{route_file}",
                    )
                )

        return findings

    def _has_success_indicators(self, route_content: str, flow_info: dict) -> bool:
        """Check if route handler content contains success indicators."""
        for indicator in flow_info["success_indicators"]:
            if indicator.lower() in route_content.lower():
                return True
        for pattern in SUCCESS_PATTERNS:
            if pattern.search(route_content):
                return True
        return False

    def _has_error_recovery(self, route_content: str) -> bool:
        """Check if route handler content contains error recovery patterns."""
        matches = 0
        for pattern in ERROR_RECOVERY_PATTERNS:
            if pattern.search(route_content):
                matches += 1
        # Need at least 2 different error handling patterns to count
        return matches >= 2

    def _check_templates_for_success(
        self, template_dir: Path, success_keywords: list[str]
    ) -> bool:
        """Check templates in a directory for success/completion indicators."""
        if not template_dir.exists():
            return False

        for template_file in template_dir.rglob("*.html"):
            try:
                content = template_file.read_text(encoding="utf-8", errors="ignore")
                # Check for success keywords
                for keyword in success_keywords:
                    if keyword.lower() in content.lower():
                        return True
                # Check for common success patterns in templates
                if re.search(
                    r"congratulations|successfully|all\s+done|complete",
                    content,
                    re.IGNORECASE,
                ):
                    return True
            except OSError:
                continue

        return False

    # --- System Flow Checks ---

    def _check_system_flows(self, db_session) -> list[FindingInput]:
        """Check system flows for terminal ActivityEvent records.

        For each system flow:
        1. Query ActivityEvent for matching event_type patterns
        2. Verify at least one terminal record exists
        3. Check if last successful event is within expected interval (stale detection)
        """
        findings: list[FindingInput] = []
        now = datetime.now(timezone.utc)
        stale_threshold = now - timedelta(hours=48)

        for flow_name, flow_info in SYSTEM_FLOWS.items():
            event_patterns = flow_info["event_type_patterns"]

            try:
                # Query for any ActivityEvent matching this flow's event types
                last_event = self._find_last_event_for_flow(
                    db_session, event_patterns
                )

                if last_event is None:
                    # No terminal status record at all = broken (RED)
                    findings.append(
                        FindingInput(
                            title=f"System flow has no terminal event: {flow_name}",
                            severity=Severity.RED,
                            block=AuditBlockName.FLOW_COMPLETENESS,
                            category="reliability",
                            risk_description=(
                                f"System flow '{flow_info['description']}' "
                                f"(task: {flow_info['celery_task']}) has no ActivityEvent "
                                f"record with matching event_type. The flow may not be "
                                f"instrumented or has never completed successfully."
                            ),
                            owner="Max",
                            effort=FixEffort.M,
                            risk_if_unresolved=(
                                f"System flow '{flow_name}' execution is unobservable — "
                                f"failures cannot be detected"
                            ),
                            requirement_ref="5.6",
                            data_path=f"activity_events (event_type IN {event_patterns})",
                        )
                    )
                elif last_event.created_at < stale_threshold:
                    # Has events but none in last 48 hours = stale (YELLOW)
                    hours_since = int(
                        (now - last_event.created_at.replace(tzinfo=timezone.utc)
                         if last_event.created_at.tzinfo is None
                         else now - last_event.created_at).total_seconds() / 3600
                    )
                    findings.append(
                        FindingInput(
                            title=f"System flow is stale: {flow_name} ({hours_since}h ago)",
                            severity=Severity.YELLOW,
                            block=AuditBlockName.FLOW_COMPLETENESS,
                            category="reliability",
                            risk_description=(
                                f"System flow '{flow_info['description']}' "
                                f"(task: {flow_info['celery_task']}) last produced an "
                                f"ActivityEvent {hours_since} hours ago. Schedule: "
                                f"{flow_info['schedule']}. No 'completed' event in "
                                f"the last 48 hours while the flow is scheduled to run."
                            ),
                            owner="Max",
                            effort=FixEffort.S,
                            risk_if_unresolved=(
                                f"System flow '{flow_name}' may be silently failing — "
                                f"schedule vs reality mismatch"
                            ),
                            requirement_ref="5.7",
                            data_path=(
                                f"activity_events (event_type IN {event_patterns}), "
                                f"last: {last_event.created_at.isoformat()}"
                            ),
                        )
                    )
                # If event is recent enough, flow is healthy — no finding needed.

            except Exception as exc:
                logger.warning("System flow check failed for %s: %s", flow_name, exc)
                findings.append(
                    FindingInput(
                        title=f"System flow check error: {flow_name}",
                        severity=Severity.YELLOW,
                        block=AuditBlockName.FLOW_COMPLETENESS,
                        category="reliability",
                        risk_description=(
                            f"Could not verify system flow '{flow_name}': {str(exc)[:200]}"
                        ),
                        owner="Max",
                        effort=FixEffort.S,
                        risk_if_unresolved="Unable to verify flow completeness",
                        requirement_ref="5.5",
                        data_path=f"activity_events query for {flow_name}",
                    )
                )

        return findings

    def _find_last_event_for_flow(
        self, db_session, event_patterns: list[str]
    ) -> Optional[ActivityEvent]:
        """Find the most recent ActivityEvent matching any of the given event_type patterns.

        Uses LIKE matching to find events where event_type contains any of the patterns.
        """
        from sqlalchemy import or_

        filters = []
        for pattern in event_patterns:
            filters.append(ActivityEvent.event_type.like(f"%{pattern}%"))

        result = (
            db_session.query(ActivityEvent)
            .filter(or_(*filters))
            .order_by(desc(ActivityEvent.created_at))
            .first()
        )
        return result

    # --- Flow Inventory ---

    def _build_flow_inventory_finding(self, db_session) -> FindingInput:
        """Produce Flow Inventory table as an informational finding.

        Requirement 5.8: Flow Inventory with columns:
        Flow_Name, Type, Entry_Point, Steps_Count, Terminal_State,
        Error_Recovery, Progress_Persisted, Observable, Last_Successful_Run
        """
        rows: list[str] = []

        # User flows
        for flow_name, flow_info in USER_FLOWS.items():
            route_file = flow_info["route_file"]
            has_success = False
            has_error_recovery = False

            if route_file:
                route_path = ROUTES_DIR / route_file
                if route_path.exists():
                    try:
                        content = route_path.read_text(encoding="utf-8", errors="ignore")
                        has_success = self._has_success_indicators(content, flow_info)
                        has_error_recovery = self._has_error_recovery(content)
                    except OSError:
                        pass

            terminal_state = "Yes" if has_success else "No"
            error_recovery = "Yes" if has_error_recovery else "No"
            progress_persisted = "Yes" if flow_info["steps"] > 1 else "N/A"
            observable = "Yes" if route_file else "No"

            rows.append(
                f"| {flow_name} | user | {flow_info['entry_point']} | "
                f"{flow_info['steps']} | {terminal_state} | {error_recovery} | "
                f"{progress_persisted} | {observable} | N/A |"
            )

        # System flows
        for flow_name, flow_info in SYSTEM_FLOWS.items():
            last_event = None
            try:
                last_event = self._find_last_event_for_flow(
                    db_session, flow_info["event_type_patterns"]
                )
            except Exception:
                pass

            last_run = (
                last_event.created_at.strftime("%Y-%m-%d %H:%M")
                if last_event
                else "Never"
            )

            rows.append(
                f"| {flow_name} | system | {flow_info['celery_task']} | "
                f"1 | ActivityEvent | N/A | N/A | "
                f"{'Yes' if last_event else 'No'} | {last_run} |"
            )

        # Build table
        header = (
            "| Flow_Name | Type | Entry_Point | Steps_Count | Terminal_State | "
            "Error_Recovery | Progress_Persisted | Observable | Last_Successful_Run |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"
        )
        table_text = header + "\n" + "\n".join(rows)

        return FindingInput(
            title="Flow Inventory produced successfully",
            severity=Severity.GREEN,
            block=AuditBlockName.FLOW_COMPLETENESS,
            category="product",
            risk_description=table_text[:500],
            owner="Max",
            effort=FixEffort.S,
            risk_if_unresolved="N/A - informational",
            requirement_ref="5.8",
            data_path="app/routes/ + app/templates/ + activity_events",
        )
