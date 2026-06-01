"""PRAW client factory — builds authenticated Reddit clients per avatar.

Supports two auth modes:
- Password auth (MVP): username + password via script app
- OAuth auth (upgrade): refresh_token via web app

Each client is configured with:
- Per-avatar proxy routing (SOCKS5 or HTTP)
- Custom User-Agent header
- Connection timeouts

Usage:
    from app.services.praw_factory import create_avatar_reddit_client, resolve_proxy_ip

    reddit = create_avatar_reddit_client(avatar, reddit_app, encryptor)
    reddit.submission(id="abc123").reply("Hello!")
"""

import logging
from typing import TYPE_CHECKING

import praw
import requests

if TYPE_CHECKING:
    from app.models.avatar import Avatar
    from app.models.reddit_app import RedditApp
    from app.services.encryption import FieldEncryptor

logger = logging.getLogger(__name__)

# Timeouts for Reddit API calls through proxy
CONNECT_TIMEOUT = 30  # seconds
READ_TIMEOUT = 60     # seconds

# IP echo service for proxy verification
IP_ECHO_URL = "https://api.ipify.org"
IP_ECHO_TIMEOUT = 10  # seconds


class PostingConfigError(Exception):
    """Raised when avatar posting configuration is incomplete."""
    pass


def create_avatar_reddit_client(
    avatar: "Avatar",
    reddit_app: "RedditApp",
    encryptor: "FieldEncryptor",
) -> praw.Reddit:
    """Create an authenticated PRAW client routed through the avatar's proxy.

    Auth mode selection:
    - If refresh_token_encrypted is set → OAuth mode
    - Elif reddit_password_encrypted is set → Password auth mode
    - Else → raise PostingConfigError

    Args:
        avatar: Avatar with proxy and credential fields
        reddit_app: The Reddit app to authenticate through
        encryptor: FieldEncryptor for decrypting secrets

    Returns:
        Authenticated praw.Reddit instance

    Raises:
        PostingConfigError: If required credentials are missing
    """
    # Validate required fields
    if not avatar.proxy_url_encrypted:
        raise PostingConfigError(f"Avatar {avatar.reddit_username}: proxy_url not configured")
    if not avatar.user_agent_string:
        raise PostingConfigError(f"Avatar {avatar.reddit_username}: user_agent_string not configured")

    # Decrypt proxy URL
    proxy_url = encryptor.decrypt(avatar.proxy_url_encrypted)

    # Decrypt app secret
    client_secret = encryptor.decrypt(reddit_app.client_secret_encrypted)

    # Build proxied session
    session = requests.Session()
    session.proxies = {"https": proxy_url, "http": proxy_url}
    session.headers["User-Agent"] = avatar.user_agent_string
    # Note: PRAW manages its own timeouts via requestor, but we set session-level defaults
    session.timeout = (CONNECT_TIMEOUT, READ_TIMEOUT)

    # Select auth mode
    if avatar.refresh_token_encrypted:
        # OAuth mode — per-avatar refresh token
        refresh_token = encryptor.decrypt(avatar.refresh_token_encrypted)
        reddit = praw.Reddit(
            client_id=reddit_app.client_id_reddit,
            client_secret=client_secret,
            refresh_token=refresh_token,
            user_agent=avatar.user_agent_string,
            requestor_kwargs={"session": session},
        )
        logger.debug("Created OAuth PRAW client for %s", avatar.reddit_username)

    elif avatar.reddit_password_encrypted:
        # Password auth mode — username + password (MVP)
        password = encryptor.decrypt(avatar.reddit_password_encrypted)
        reddit = praw.Reddit(
            client_id=reddit_app.client_id_reddit,
            client_secret=client_secret,
            username=avatar.reddit_username,
            password=password,
            user_agent=avatar.user_agent_string,
            requestor_kwargs={"session": session},
        )
        logger.debug("Created password-auth PRAW client for %s", avatar.reddit_username)

    else:
        raise PostingConfigError(
            f"Avatar {avatar.reddit_username}: no auth credentials "
            "(neither refresh_token nor reddit_password configured)"
        )

    return reddit


def resolve_proxy_ip(proxy_url: str, timeout: int = IP_ECHO_TIMEOUT) -> str | None:
    """Resolve the exit IP of a proxy by making a request to an IP echo service.

    Args:
        proxy_url: Full proxy URL (e.g., socks5://user:pass@1.2.3.4:1080)
        timeout: Request timeout in seconds

    Returns:
        IP address string or None on failure
    """
    try:
        session = requests.Session()
        session.proxies = {"https": proxy_url, "http": proxy_url}
        response = session.get(IP_ECHO_URL, timeout=timeout)
        response.raise_for_status()
        ip = response.text.strip()
        logger.debug("Proxy %s resolves to IP: %s", proxy_url[:30] + "...", ip)
        return ip
    except requests.RequestException as e:
        logger.warning("Failed to resolve proxy IP: %s", str(e))
        return None
