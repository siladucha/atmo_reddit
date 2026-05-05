"""Auth middleware — protects routes by checking JWT cookie."""

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.services.auth import decode_access_token

logger = logging.getLogger(__name__)

# Routes that don't require authentication
PUBLIC_ROUTES = {
    "/login",
    "/register",
    "/logout",
    "/health",
    "/docs",
    "/docs/oauth2-redirect",
    "/openapi.json",
    "/redoc",
}

# Prefixes that don't require authentication
PUBLIC_PREFIXES = (
    "/auth/",
    "/static/",
)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip auth for public routes
        if path in PUBLIC_ROUTES or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)

        # Check JWT cookie
        token = request.cookies.get("access_token")
        if not token:
            logger.debug("No auth token, redirecting to login: %s", path)
            return RedirectResponse(url="/login", status_code=303)

        payload = decode_access_token(token)
        if not payload:
            logger.debug("Invalid auth token, redirecting to login: %s", path)
            return RedirectResponse(url="/login", status_code=303)

        # Attach user info to request state
        request.state.user_id = payload.get("sub")
        request.state.user_email = payload.get("email")

        logger.debug(
            "AUTH_REQUEST | method=%s | path=%s | user=%s",
            request.method, path, payload.get("email"),
        )

        return await call_next(request)
