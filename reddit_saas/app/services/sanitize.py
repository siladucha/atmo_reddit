"""Reddit name sanitization — prevents double-prefix bugs and invalid API calls.

All functions that interact with the Reddit API (PRAW) or store subreddit/username
data should pass values through these sanitizers first.

Rules:
- Subreddit names: bare name only (no r/ prefix, no spaces, lowercase-safe)
- Usernames: bare name only (no u/ prefix, no spaces)
- Both: strip whitespace, reject empty strings
"""

import re
import logging

logger = logging.getLogger(__name__)

# Valid Reddit subreddit: 3-21 chars, alphanumeric + underscores
_SUBREDDIT_PATTERN = re.compile(r"^[A-Za-z0-9_]{2,21}$")

# Valid Reddit username: 3-20 chars, alphanumeric + underscores + hyphens
_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,20}$")


def clean_subreddit(name: str | None) -> str | None:
    """Strip r/ prefix, whitespace, and validate subreddit name.

    Returns cleaned name or None if invalid.

    Examples:
        clean_subreddit("r/cybersecurity") -> "cybersecurity"
        clean_subreddit("r/r/docker") -> "docker"
        clean_subreddit("  softwaretesting  ") -> "softwaretesting"
        clean_subreddit("") -> None
        clean_subreddit(None) -> None
    """
    if not name:
        return None

    cleaned = str(name).strip()

    # Remove any number of r/ prefixes (handles r/r/r/name)
    while cleaned.lower().startswith("r/"):
        cleaned = cleaned[2:]

    # Remove leading/trailing slashes and whitespace
    cleaned = cleaned.strip().strip("/").strip()

    if not cleaned:
        return None

    # Validate format
    if not _SUBREDDIT_PATTERN.match(cleaned):
        logger.warning("Invalid subreddit name after cleaning: %r (original: %r)", cleaned, name)
        return None

    return cleaned


def clean_username(name: str | None) -> str | None:
    """Strip u/ prefix, whitespace, and validate Reddit username.

    Returns cleaned name or None if invalid.

    Examples:
        clean_username("u/Hot-Thought2408") -> "Hot-Thought2408"
        clean_username("u/u/Flaky_Finder_13") -> "Flaky_Finder_13"
        clean_username("  d-wreck-w12  ") -> "d-wreck-w12"
        clean_username("") -> None
    """
    if not name:
        return None

    cleaned = str(name).strip()

    # Remove any number of u/ prefixes
    while cleaned.lower().startswith("u/"):
        cleaned = cleaned[2:]

    # Remove leading/trailing whitespace
    cleaned = cleaned.strip()

    if not cleaned:
        return None

    # Validate format
    if not _USERNAME_PATTERN.match(cleaned):
        logger.warning("Invalid username after cleaning: %r (original: %r)", cleaned, name)
        return None

    return cleaned


def ensure_subreddit_bare(name: str) -> str:
    """Like clean_subreddit but raises ValueError if invalid.

    Use at API boundaries where we must not proceed with bad data.
    """
    result = clean_subreddit(name)
    if result is None:
        raise ValueError(f"Invalid subreddit name: {name!r}")
    return result


def ensure_username_bare(name: str) -> str:
    """Like clean_username but raises ValueError if invalid.

    Use at API boundaries where we must not proceed with bad data.
    """
    result = clean_username(name)
    if result is None:
        raise ValueError(f"Invalid Reddit username: {name!r}")
    return result


def clean_subreddit_list(items: list | None) -> list[str]:
    """Clean a list of subreddit names/dicts, removing invalid entries.

    Handles both plain strings and dicts with 'subreddit' or 'name' keys.
    Returns list of bare subreddit names.
    """
    if not items:
        return []

    result = []
    for item in items:
        if isinstance(item, str):
            cleaned = clean_subreddit(item)
            if cleaned:
                result.append(cleaned)
        elif isinstance(item, dict):
            raw = item.get("subreddit") or item.get("name") or item.get("sub") or ""
            cleaned = clean_subreddit(raw)
            if cleaned:
                result.append(cleaned)

    return result
