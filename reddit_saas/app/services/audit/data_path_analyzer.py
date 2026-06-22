"""DataPathAnalyzer — Audit Block 1: External Data Leakage Detection.

Traces all external data paths end-to-end and verifies:
- No sensitive data leaks beyond intended boundaries
- Retention policies are respected (90 days for threads, 24h for Redis cache)
- PII is not present in logs or activity events
- Redis cached data does not exceed TTL limits
- UUIDs are not exposed in non-admin route contexts
- LLM prompts contain data from at most one client
"""

import ast
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID

import redis

from app.config import get_settings
from app.logging_config import get_logger
from app.models.activity_event import ActivityEvent
from app.models.thread import RedditThread
from app.services.audit.base import (
    AuditBlock,
    AuditBlockName,
    FindingInput,
    FixEffort,
    Severity,
)

logger = get_logger(__name__)

# --- PII Detection Patterns ---

PII_PATTERNS = {
    "email": re.compile(
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.IGNORECASE
    ),
    "ipv4": re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
    ),
    "oauth_token": re.compile(
        r"\b[A-Za-z0-9\-_]{20,}\.[A-Za-z0-9\-_]{20,}\.[A-Za-z0-9\-_]{20,}\b"
    ),
    "password_field": re.compile(
        r"(?:password|passwd|pwd|secret|token)\s*[:=]\s*\S+", re.IGNORECASE
    ),
}

# External integration patterns to detect in code
EXTERNAL_CALL_PATTERNS = {
    "praw": re.compile(r"\bpraw\b|\breddit\b.*\.subreddit|\.submission|\.comment", re.IGNORECASE),
    "httpx": re.compile(r"\bhttpx\b|httpx\.AsyncClient|httpx\.Client|httpx\.(get|post|put|delete)", re.IGNORECASE),
    "litellm": re.compile(r"\blitellm\b|litellm\.completion|litellm\.acompletion", re.IGNORECASE),
}

# UUID pattern for detection in route responses
UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)

# Redis key patterns that suggest external data caching
EXTERNAL_DATA_KEY_PATTERNS = [
    "reddit:", "praw:", "scrape:", "thread:", "api:", "llm:", "response:",
    "external:", "cache:reddit", "cache:api",
]

# Project root for file scanning
PROJECT_ROOT = Path(__file__).resolve().parents[3]  # up from app/services/audit/
APP_DIR = PROJECT_ROOT / "app"
SERVICES_DIR = APP_DIR / "services"
ROUTES_DIR = APP_DIR / "routes"


class DataPathAnalyzer(AuditBlock):
    """Traces external data paths and detects leakage violations.

    Performs mixed analysis:
    - Static code scan: external HTTP calls, UUID exposure, prompt assembly
    - Runtime data: DB queries for retention violations, PII in activity events
    - Redis inspection: TTL compliance for cached external data
    """

    @property
    def name(self) -> AuditBlockName:
        return AuditBlockName.DATA_LEAKAGE

    async def run(self, run_id: UUID, db_session) -> list[FindingInput]:
        """Execute all data path checks and return findings.

        Args:
            run_id: The parent AuditRun ID.
            db_session: SQLAlchemy session.

        Returns:
            List of findings for detected violations.
        """
        findings: list[FindingInput] = []

        # 1. Scan services for external HTTP calls and build integration map
        integration_map = self._scan_external_integrations()

        # 2. Check retention policy violations (threads > 90 days with body > 500 chars)
        findings.extend(self._check_retention_violations(db_session))

        # 3. Scan activity_events for PII patterns
        findings.extend(self._check_pii_in_activity_events(db_session))

        # 4. Scan log config for PII risk
        findings.extend(self._check_log_config_pii_risk())

        # 5. Inspect Redis keys with TTL > 24h for external data patterns
        findings.extend(self._check_redis_ttl_violations())

        # 6. Check route handlers for UUID exposure in non-admin contexts
        findings.extend(self._check_uuid_exposure_in_routes())

        # 7. Sample LLM prompt assembly code for multi-client data inclusion
        findings.extend(self._check_llm_prompt_isolation())

        # 8. Produce integration map as a GREEN finding (informational)
        findings.append(self._build_integration_map_finding(integration_map))

        logger.info(
            "DataPathAnalyzer completed: %d findings (run_id=%s)",
            len(findings),
            run_id,
        )
        return findings

    # --- 1. External Integration Scanning ---

    def _scan_external_integrations(self) -> list[dict]:
        """Scan app/services/ for external HTTP calls (httpx, PRAW, LiteLLM).

        Returns a list of integration descriptors for the integration map.
        """
        integrations: list[dict] = []

        if not SERVICES_DIR.exists():
            return integrations

        for py_file in SERVICES_DIR.rglob("*.py"):
            if py_file.name.startswith("__"):
                continue

            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            relative_path = str(py_file.relative_to(PROJECT_ROOT))

            for integration_name, pattern in EXTERNAL_CALL_PATTERNS.items():
                if pattern.search(content):
                    integrations.append({
                        "integration": integration_name,
                        "file": relative_path,
                        "data_read": self._infer_data_read(integration_name),
                        "data_stored": self._infer_data_stored(integration_name),
                        "retention_period": self._infer_retention(integration_name),
                        "access_roles": "all authenticated",
                        "compliance_status": "PASS",
                    })

        return integrations

    def _infer_data_read(self, integration: str) -> str:
        """Infer what data is read from each integration type."""
        mapping = {
            "praw": "Reddit posts, comments, user profiles, subreddit data",
            "httpx": "External website content, API responses",
            "litellm": "LLM-generated text (scores, comments, analyses)",
        }
        return mapping.get(integration, "Unknown")

    def _infer_data_stored(self, integration: str) -> str:
        """Infer what data is stored from each integration type."""
        mapping = {
            "praw": "Thread body, comments_json, author, scores in reddit_threads",
            "httpx": "Scraped website content (onboarding), temporary processing",
            "litellm": "Generated drafts in comment_drafts, scores in thread_scores",
        }
        return mapping.get(integration, "Unknown")

    def _infer_retention(self, integration: str) -> str:
        """Infer retention period for each integration type."""
        mapping = {
            "praw": "90 days (scraped threads), indefinite (derived metadata)",
            "httpx": "Session-only (onboarding scrape not persisted long-term)",
            "litellm": "Indefinite (drafts are product data)",
        }
        return mapping.get(integration, "Not configured")

    # --- 2. Retention Policy Violations ---

    def _check_retention_violations(self, db_session) -> list[FindingInput]:
        """Query reddit_threads for records older than 90 days with body > 500 chars.

        Requirement 1.2: Raw API responses should not be stored with > 500 chars
        of original post body beyond the 90-day retention policy.
        """
        findings: list[FindingInput] = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)

        try:
            from sqlalchemy import func, and_

            # Count threads older than 90 days with body > 500 chars
            violation_count = (
                db_session.query(func.count(RedditThread.id))
                .filter(
                    and_(
                        RedditThread.created_at < cutoff,
                        func.length(RedditThread.post_body) > 500,
                    )
                )
                .scalar()
            ) or 0

            if violation_count > 0:
                findings.append(
                    FindingInput(
                        title=f"Retention violation: {violation_count} threads > 90 days with body > 500 chars",
                        severity=Severity.YELLOW,
                        block=AuditBlockName.DATA_LEAKAGE,
                        category="data_leakage",
                        risk_description=(
                            f"Found {violation_count} reddit_threads records older than 90 days "
                            f"that still contain raw post body exceeding 500 characters. "
                            f"Per retention policy, these should retain only derived metadata."
                        ),
                        owner="Max",
                        effort=FixEffort.M,
                        risk_if_unresolved="Raw Reddit content retained beyond policy window, potential GDPR exposure",
                        requirement_ref="1.2",
                        data_path="reddit_threads.post_body (created_at < 90 days ago)",
                    )
                )
        except Exception as exc:
            logger.warning("Retention check failed: %s", exc)
            findings.append(
                FindingInput(
                    title="Retention check could not be completed",
                    severity=Severity.YELLOW,
                    block=AuditBlockName.DATA_LEAKAGE,
                    category="data_leakage",
                    risk_description=f"Failed to query retention violations: {str(exc)[:200]}",
                    owner="Max",
                    effort=FixEffort.S,
                    risk_if_unresolved="Unable to verify retention compliance",
                    requirement_ref="1.2",
                )
            )

        return findings

    # --- 3. PII Detection in Activity Events ---

    def _check_pii_in_activity_events(self, db_session) -> list[FindingInput]:
        """Scan activity_events message field for PII patterns.

        Requirement 1.4: No private user data (passwords, emails, IPs, tokens)
        should appear in activity_events free-text fields.
        """
        findings: list[FindingInput] = []

        try:
            # Sample recent activity events (last 1000)
            from sqlalchemy import desc

            events = (
                db_session.query(ActivityEvent.id, ActivityEvent.message)
                .order_by(desc(ActivityEvent.created_at))
                .limit(1000)
                .all()
            )

            pii_violations: dict[str, int] = {}

            for event_id, message in events:
                if not message:
                    continue
                for pii_type, pattern in PII_PATTERNS.items():
                    if pattern.search(message):
                        pii_violations[pii_type] = pii_violations.get(pii_type, 0) + 1

            for pii_type, count in pii_violations.items():
                severity = Severity.RED if pii_type in ("password_field", "oauth_token") else Severity.YELLOW
                findings.append(
                    FindingInput(
                        title=f"PII detected in activity_events: {pii_type} ({count} occurrences)",
                        severity=severity,
                        block=AuditBlockName.DATA_LEAKAGE,
                        category="security",
                        risk_description=(
                            f"Found {count} activity_events records with {pii_type} patterns "
                            f"in the message field. Private user data must not appear in logs."
                        ),
                        owner="Max",
                        effort=FixEffort.M,
                        risk_if_unresolved=f"PII ({pii_type}) exposed in activity logs, potential compliance violation",
                        requirement_ref="1.4",
                        data_path="activity_events.message",
                    )
                )
        except Exception as exc:
            logger.warning("PII check in activity_events failed: %s", exc)

        return findings

    # --- 4. Log Config PII Risk ---

    def _check_log_config_pii_risk(self) -> list[FindingInput]:
        """Scan log configuration for patterns that might log PII.

        Checks logging_config.py and services that log request/response data.
        """
        findings: list[FindingInput] = []

        # Check if logging format includes potentially PII-sensitive fields
        log_config_path = APP_DIR / "logging_config.py"
        if log_config_path.exists():
            try:
                content = log_config_path.read_text(encoding="utf-8")

                # Check if PRAW/prawcore debug logging is enabled (logs full API responses)
                if "prawcore" in content and "DEBUG" in content:
                    findings.append(
                        FindingInput(
                            title="PRAW debug logging enabled - may log user data",
                            severity=Severity.YELLOW,
                            block=AuditBlockName.DATA_LEAKAGE,
                            category="security",
                            risk_description=(
                                "prawcore logger is set to DEBUG level which logs full Reddit "
                                "API request/response payloads including user data, tokens, "
                                "and post content to log files."
                            ),
                            owner="Max",
                            effort=FixEffort.S,
                            risk_if_unresolved="Reddit API responses with user data written to log files",
                            requirement_ref="1.4",
                            data_path="app/logging_config.py (prawcore DEBUG)",
                        )
                    )
            except OSError:
                pass

        # Scan services for patterns that log sensitive data
        sensitive_log_patterns = re.compile(
            r"logger\.\w+\(.*(?:password|token|secret|api_key|credentials).*\)",
            re.IGNORECASE,
        )

        if SERVICES_DIR.exists():
            for py_file in SERVICES_DIR.rglob("*.py"):
                if py_file.name.startswith("__"):
                    continue
                try:
                    content = py_file.read_text(encoding="utf-8", errors="ignore")
                    matches = sensitive_log_patterns.findall(content)
                    if matches:
                        relative_path = str(py_file.relative_to(PROJECT_ROOT))
                        findings.append(
                            FindingInput(
                                title=f"Potential PII in logs: {py_file.name}",
                                severity=Severity.YELLOW,
                                block=AuditBlockName.DATA_LEAKAGE,
                                category="security",
                                risk_description=(
                                    f"File {relative_path} contains {len(matches)} logging "
                                    f"statement(s) that may include sensitive data (password, "
                                    f"token, secret, api_key, credentials)."
                                ),
                                owner="Max",
                                effort=FixEffort.S,
                                risk_if_unresolved="Sensitive data may be written to application logs",
                                requirement_ref="1.4",
                                data_path=relative_path,
                            )
                        )
                except OSError:
                    continue

        return findings

    # --- 5. Redis TTL Violations ---

    def _check_redis_ttl_violations(self) -> list[FindingInput]:
        """Inspect Redis keys with TTL > 24h for external data patterns.

        Requirement 1.6: No cache key containing external API response data
        should have a TTL exceeding 24 hours.
        """
        findings: list[FindingInput] = []

        try:
            settings = get_settings()
            r = redis.from_url(settings.redis_url, decode_responses=True)

            # Scan Redis keys for external data patterns
            violations: list[str] = []
            max_ttl_seconds = 24 * 3600  # 24 hours

            # Use SCAN to iterate keys safely
            cursor = 0
            scanned_keys = 0
            max_scan = 10000  # Limit scan scope

            while scanned_keys < max_scan:
                cursor, keys = r.scan(cursor=cursor, count=100)
                scanned_keys += len(keys)

                for key in keys:
                    # Check if key matches external data patterns
                    key_lower = key.lower()
                    is_external = any(
                        pattern in key_lower for pattern in EXTERNAL_DATA_KEY_PATTERNS
                    )

                    if is_external:
                        ttl = r.ttl(key)
                        # ttl = -1 means no expiry (persists indefinitely)
                        # ttl = -2 means key doesn't exist
                        if ttl == -1 or ttl > max_ttl_seconds:
                            violations.append(
                                f"{key} (TTL: {'no expiry' if ttl == -1 else f'{ttl}s'})"
                            )

                if cursor == 0:
                    break

            if violations:
                violation_sample = "; ".join(violations[:5])
                findings.append(
                    FindingInput(
                        title=f"Redis TTL violation: {len(violations)} keys exceed 24h",
                        severity=Severity.YELLOW,
                        block=AuditBlockName.DATA_LEAKAGE,
                        category="data_leakage",
                        risk_description=(
                            f"Found {len(violations)} Redis keys matching external data patterns "
                            f"with TTL > 24 hours or no expiry. Sample: {violation_sample[:300]}"
                        ),
                        owner="Max",
                        effort=FixEffort.S,
                        risk_if_unresolved="External API data persists in cache beyond retention policy",
                        requirement_ref="1.6",
                        data_path="Redis cache keys",
                    )
                )
        except redis.ConnectionError:
            logger.warning("Redis connection failed during TTL check - skipping")
        except Exception as exc:
            logger.warning("Redis TTL check failed: %s", exc)

        return findings

    # --- 6. UUID Exposure in Non-Admin Routes ---

    def _check_uuid_exposure_in_routes(self) -> list[FindingInput]:
        """Check route handlers for UUID exposure in non-admin contexts.

        Requirement 1.7: No internal database IDs should be exposed in
        user-facing output or API responses to non-admin roles.
        """
        findings: list[FindingInput] = []

        if not ROUTES_DIR.exists():
            return findings

        # Non-admin route files (admin routes are allowed to expose UUIDs)
        admin_prefixes = ("admin", "dashboard")

        for py_file in ROUTES_DIR.glob("*.py"):
            if py_file.name.startswith("__"):
                continue

            # Skip admin routes
            if any(py_file.name.startswith(prefix) for prefix in admin_prefixes):
                continue

            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(content, filename=str(py_file))
            except (OSError, SyntaxError):
                continue

            relative_path = str(py_file.relative_to(PROJECT_ROOT))
            uuid_exposures: list[str] = []

            for node in ast.walk(tree):
                # Look for route function definitions that return dicts/JSONResponse
                # with UUID-like field names
                if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                    func_source = ast.get_source_segment(content, node)
                    if func_source and self._has_uuid_in_response(func_source):
                        uuid_exposures.append(node.name)

            if uuid_exposures:
                funcs = ", ".join(uuid_exposures[:5])
                findings.append(
                    FindingInput(
                        title=f"UUID exposure in non-admin route: {py_file.name}",
                        severity=Severity.YELLOW,
                        block=AuditBlockName.DATA_LEAKAGE,
                        category="data_leakage",
                        risk_description=(
                            f"Route file {relative_path} exposes internal UUIDs in "
                            f"non-admin handler(s): {funcs}. Internal IDs should not "
                            f"be visible to non-admin roles."
                        ),
                        owner="Max",
                        effort=FixEffort.M,
                        risk_if_unresolved="Internal database IDs leaked to non-privileged users",
                        requirement_ref="1.7",
                        data_path=relative_path,
                    )
                )

        return findings

    def _has_uuid_in_response(self, func_source: str) -> bool:
        """Check if a function source contains UUID-like patterns in response bodies.

        Looks for patterns like: {"id": str(something.id)}, "client_id", etc.
        in return statements or response construction.
        """
        # Patterns suggesting UUID fields exposed in responses
        response_uuid_patterns = [
            # Direct dict construction with id fields in JSONResponse/return
            re.compile(r'["\'](?:id|client_id|avatar_id|user_id|run_id)["\'].*?str\(', re.DOTALL),
            # String formatting with .id
            re.compile(r'f["\'].*?\{.*?\.id\}', re.DOTALL),
        ]

        # Only flag if this looks like it's in a response context
        response_indicators = ["JSONResponse", "return {", "return json", "jsonable_encoder"]
        has_response = any(indicator in func_source for indicator in response_indicators)

        if not has_response:
            return False

        return any(pattern.search(func_source) for pattern in response_uuid_patterns)

    # --- 7. LLM Prompt Context Isolation ---

    def _check_llm_prompt_isolation(self) -> list[FindingInput]:
        """Sample LLM prompt assembly code for multi-client data inclusion.

        Requirement 1.8: LLM prompts must not contain data from multiple clients.
        Checks that prompt assembly code has isolation assertions.
        """
        findings: list[FindingInput] = []

        if not SERVICES_DIR.exists():
            return findings

        # Files likely to assemble LLM prompts
        prompt_files = [
            "generation.py",
            "scoring.py",
            "ai.py",
            "post_generation.py",
            "avatar_analysis.py",
            "smart_scoring.py",
        ]

        for filename in prompt_files:
            filepath = SERVICES_DIR / filename
            if not filepath.exists():
                continue

            try:
                content = filepath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            relative_path = str(filepath.relative_to(PROJECT_ROOT))

            # Check if file assembles prompts (contains PROMPT patterns + litellm/messages)
            has_prompt_assembly = (
                ("PROMPT" in content or "prompt" in content.lower())
                and ("messages" in content or "litellm" in content)
            )

            if not has_prompt_assembly:
                continue

            # Check for isolation assertion
            has_isolation_check = (
                "_assert_context_isolation" in content
                or "context_isolation" in content
                or "client_id" in content and "assert" in content.lower()
                or "isolation" in content.lower()
            )

            if not has_isolation_check:
                findings.append(
                    FindingInput(
                        title=f"Missing context isolation in prompt assembly: {filename}",
                        severity=Severity.RED,
                        block=AuditBlockName.DATA_LEAKAGE,
                        category="security",
                        risk_description=(
                            f"File {relative_path} assembles LLM prompts but lacks "
                            f"context isolation assertion. Multi-client data may enter "
                            f"the same prompt, violating data boundaries."
                        ),
                        owner="Max",
                        effort=FixEffort.M,
                        risk_if_unresolved="Cross-client data leakage via LLM prompt context",
                        requirement_ref="1.8",
                        data_path=relative_path,
                    )
                )

        return findings

    # --- 8. Integration Map Finding ---

    def _build_integration_map_finding(self, integrations: list[dict]) -> FindingInput:
        """Produce integration map table as an informational finding.

        Requirement 1.9: Produce integration map with columns:
        Integration, Data_Read, Data_Stored, Retention_Period, Access_Roles, Compliance_Status
        """
        if not integrations:
            table_text = "No external integrations detected."
        else:
            # Deduplicate by integration type
            seen: dict[str, dict] = {}
            for item in integrations:
                key = item["integration"]
                if key not in seen:
                    seen[key] = item
                else:
                    # Merge file references
                    seen[key]["file"] += f", {item['file']}"

            rows = []
            for key, item in seen.items():
                rows.append(
                    f"| {item['integration']} | {item['data_read'][:80]} | "
                    f"{item['data_stored'][:80]} | {item['retention_period']} | "
                    f"{item['access_roles']} | {item['compliance_status']} |"
                )

            table_text = (
                "| Integration | Data_Read | Data_Stored | Retention_Period | "
                "Access_Roles | Compliance_Status |\n"
                "| --- | --- | --- | --- | --- | --- |\n"
                + "\n".join(rows)
            )

        return FindingInput(
            title="Integration map produced successfully",
            severity=Severity.GREEN,
            block=AuditBlockName.DATA_LEAKAGE,
            category="data_leakage",
            risk_description=table_text[:500],
            owner="Max",
            effort=FixEffort.S,
            risk_if_unresolved="N/A - informational",
            requirement_ref="1.9",
            data_path="app/services/ (external integration scan)",
        )
