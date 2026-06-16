"""Quality Gate — checks if client profile is complete enough for activation.

Simple MVP version: required fields must be non-empty.
Phase 2: scoring (0-100) with weighted sections.
"""

from app.logging_config import get_logger
from app.models.client import Client

logger = get_logger(__name__)


def check_quality(client: Client) -> dict:
    """Check if a client's onboarding data is sufficient for activation.

    Returns:
        {
            "can_activate": bool,
            "missing": ["field_name", ...],  # required fields that are empty
            "warnings": ["field_name", ...],  # optional fields that are empty (non-blocking)
        }
    """
    missing = []
    warnings = []

    # Required fields (block activation if empty)
    if not client.client_name or not client.client_name.strip():
        missing.append("client_name")
    if not client.brand_name or not client.brand_name.strip():
        missing.append("brand_name")
    if not client.company_profile or len(client.company_profile.strip()) < 20:
        missing.append("company_profile")
    if not client.company_problem or len(client.company_problem.strip()) < 20:
        missing.append("company_problem")
    if not client.icp_profiles or len(client.icp_profiles.strip()) < 20:
        missing.append("icp_profiles")

    # Keywords: at least 3 total
    keywords = client.keywords or {}
    total_keywords = sum(len(v) for v in keywords.values() if isinstance(v, list))
    if total_keywords < 3:
        missing.append("keywords (minimum 3)")

    # Subreddits: check via relationship or count
    # For MVP, we trust that step 5 adds at least 1 subreddit
    # This will be validated at activation time with a DB query

    # Optional fields (warnings, non-blocking)
    if not client.brand_voice or len(client.brand_voice.strip()) < 10:
        warnings.append("brand_voice")
    if not client.competitive_landscape or len(client.competitive_landscape.strip()) < 10:
        warnings.append("competitive_landscape")
    if not client.brand_domain:
        warnings.append("brand_domain")

    can_activate = len(missing) == 0

    if not can_activate:
        logger.info(
            "Quality gate BLOCKED for client %s: missing=%s",
            client.client_name, missing,
        )

    return {
        "can_activate": can_activate,
        "missing": missing,
        "warnings": warnings,
    }
