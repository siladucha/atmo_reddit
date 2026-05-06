"""Centralized cookie management — ensures secure flags on all auth cookies."""

from starlette.responses import Response

from app.config import get_config


def set_auth_cookie(response: Response, token: str) -> None:
    """Set the access_token cookie with proper security flags.

    In production: secure=True, samesite=Strict (HTTPS only, no cross-site).
    In development: secure=False, samesite=Lax (works over HTTP).
    """
    app_env = get_config("app_env")
    is_production = app_env == "production"

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=is_production,
        samesite="strict" if is_production else "lax",
        max_age=86400,  # 24 hours
        path="/",
    )


def delete_auth_cookie(response: Response) -> None:
    """Delete the access_token cookie."""
    response.delete_cookie(
        key="access_token",
        path="/",
    )
