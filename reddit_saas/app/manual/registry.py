"""Content registry for the UX Manual Overlay."""

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

MANUAL_DIR = Path(__file__).parent / "screens"

# UUID pattern for path normalization
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)

# Route aliases: map computed keys to canonical YAML filenames
_ROUTE_ALIASES: dict[str, str] = {
    "clients_home": "portal_home",
    "clients_review": "portal_review",
    "clients_avatars": "portal_avatars",
    "clients_avatar_detail": "portal_avatar_detail",
    "clients_epg": "portal_epg",
    "clients_strategy": "portal_strategy",
    "clients_report": "portal_report",
    "clients_subreddits": "portal_subreddits",
    "clients_keywords": "portal_keywords",
    "clients_settings": "portal_settings",
    "clients_notifications": "portal_notifications",
}


def _path_to_key(path: str) -> str:
    """Convert URL path to YAML filename key.

    Examples:
        /admin/clients -> admin_clients
        /admin/ -> admin_dashboard
        /clients/550e8400-.../home -> portal_home
        / -> index
    """
    clean = path.strip("/")
    if not clean:
        return "index"

    # Remove UUID segments
    parts = clean.split("/")
    parts = [p for p in parts if not _UUID_RE.fullmatch(p)]

    # Join remaining parts and normalize hyphens to underscores
    key = "_".join(parts).replace("-", "_")

    # Special case: /admin/ with no sub-path
    if key == "admin":
        key = "admin_dashboard"

    # Apply route aliases (portal paths)
    key = _ROUTE_ALIASES.get(key, key)

    return key or "index"


@lru_cache(maxsize=128)
def _load_yaml(route_key: str) -> dict[str, Any] | None:
    """Load YAML file for a given route key. Cached per process."""
    file_path = MANUAL_DIR / f"{route_key}.yaml"
    if not file_path.exists():
        return None
    try:
        return yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Failed to load manual YAML %s: %s", file_path, e)
        return None


def get_manual_content(path: str, role: str) -> dict[str, Any]:
    """Get manual content for a route path and user role.

    Returns a dict ready to be passed to the manual_content.html template.
    """
    route_key = _path_to_key(path)
    data = _load_yaml(route_key)

    if not data:
        logger.debug("No manual content for route_key=%s (path=%s)", route_key, path)
        return {
            "found": False,
            "title": "Help",
            "route_key": route_key,
        }

    # Filter actions by role: use role-specific list, or fall back to "all"
    actions_map = data.get("available_actions", {})
    if role in actions_map:
        role_actions = actions_map[role]
    else:
        role_actions = actions_map.get("all", [])

    return {
        "found": True,
        "title": data.get("title", ""),
        "lifecycle_stage": data.get("lifecycle_stage", ""),
        "flow_position": data.get("flow_position", {}),
        "screen_context": data.get("screen_context", {}),
        "screen_purpose": data.get("screen_purpose", ""),
        "available_actions": role_actions,
        "role_behavior": data.get("role_behavior", {}),
    }
