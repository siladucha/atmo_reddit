from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Bootstrap-only settings — values needed before the database is available.

    All other configuration lives in the ``system_settings`` DB table and is
    accessed via ``get_config()`` or ``settings_service.get_setting()``.
    """
    database_url: str = "postgresql://postgres:postgres@localhost:5432/reddit_saas"
    redis_url: str = "redis://localhost:6379/0"
    app_env: str = "production"
    posting_disabled: bool = False  # env-level kill switch (cannot be toggled from admin UI)
    extension_hmac_secret: str | None = None  # HMAC secret for browser extension task signing
    secret_key: str = "change-me"  # JWT signing key (MUST override in .env)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # NOTE: Stripe keys (stripe_secret_key, stripe_webhook_secret, stripe_publishable_key)
    # are stored in the system_settings DB table, NOT in this bootstrap class.
    # Access them via get_setting(db, "stripe_secret_key") etc.


@lru_cache
def get_settings() -> Settings:
    """Return the bootstrap Settings (database_url, redis_url only)."""
    return Settings()


# Bootstrap keys that are resolved from env, never from DB
_BOOTSTRAP_KEYS = frozenset({
    "database_url", "redis_url", "app_env", "extension_hmac_secret", "secret_key",
})


def get_config(key: str, db=None) -> str:
    """Get a config value.  Bootstrap keys come from env; everything else from DB.

    Args:
        key: The setting key (e.g. ``"secret_key"``, ``"reddit_client_id"``).
        db: An optional SQLAlchemy ``Session``.  If *None* and the key is not
            a bootstrap key, a throwaway session is created and closed
            automatically.

    Returns:
        The setting value as a string.
    """
    if key in _BOOTSTRAP_KEYS:
        return getattr(get_settings(), key)

    from app.services import settings as settings_service

    if db is not None:
        return settings_service.get_setting(db, key)

    # No session provided — create one for the lookup
    from app.database import SessionLocal
    session = SessionLocal()
    try:
        return settings_service.get_setting(session, key)
    finally:
        session.close()
