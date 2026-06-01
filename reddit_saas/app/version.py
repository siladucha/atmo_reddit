"""Application version — single source of truth.

Reads from the VERSION file at project root. Falls back to "unknown" if
the file is missing (shouldn't happen in normal builds).
"""

from pathlib import Path

_VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"


def get_version() -> str:
    """Return the current application version string."""
    try:
        return _VERSION_FILE.read_text().strip()
    except FileNotFoundError:
        return "unknown"


__version__ = get_version()
