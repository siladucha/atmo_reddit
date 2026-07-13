"""Application version — single source of truth.

Reads from the VERSION file at project root. Falls back to "unknown" if
the file is missing (shouldn't happen in normal builds).

DEPLOYED_AT is written by the deploy pipeline at build time.
"""

from pathlib import Path

_VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"
_DEPLOYED_AT_FILE = Path(__file__).resolve().parent.parent / "DEPLOYED_AT"


def get_version() -> str:
    """Return the current application version string."""
    try:
        return _VERSION_FILE.read_text().strip()
    except FileNotFoundError:
        return "unknown"


def get_deployed_at() -> str:
    """Return the deploy timestamp (ISO format) or empty string."""
    try:
        return _DEPLOYED_AT_FILE.read_text().strip()
    except FileNotFoundError:
        return ""


__version__ = get_version()
__deployed_at__ = get_deployed_at()
