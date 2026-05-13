"""Centralized cookie management — ensures secure flags on all auth cookies."""

from starlette.responses import Response


def set_auth_cookie(response: Response, token: str) -> None:
    """Set the access_token cookie with proper security flags.

    No SSL at this stage — always use secure=False, samesite=Lax.
    When HTTPS is added (domain + cert), switch to secure=True, samesite=Strict.
    """
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=86400,  # 24 hours
        path="/",
    )


def delete_auth_cookie(response: Response) -> None:
    """Delete the access_token cookie."""
    response.delete_cookie(
        key="access_token",
        path="/",
    )
