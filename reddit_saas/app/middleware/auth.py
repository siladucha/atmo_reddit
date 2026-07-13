"""Auth middleware — protects routes by checking JWT cookie.

Two independent auth mechanisms:
1. JWT cookie auth (form login at /login) — checks user in DB via authenticate_user().
   User MUST exist in `users` table with correct role (owner/partner for admin access).
2. HTTP Basic Auth — ONLY for /docs, /openapi.json, /redoc (Swagger UI protection).
   Uses hardcoded _DOCS_CREDENTIALS dict below. NOT related to /login form at all.

If /login says "Invalid credentials" — the user is missing from `users` table or
password hash doesn't match. Check: SELECT email, role FROM users;

If login succeeds but redirects back to /login?error=no_access — the user's `role`
field is wrong (needs 'owner' or 'partner' for admin panel access). The /home route
checks role.is_admin_level which only matches owner/partner.
"""

from app.logging_config import get_logger
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.services.auth import decode_access_token

logger = get_logger(__name__)

# Routes that don't require authentication
PUBLIC_ROUTES = {
    "/onboard/trial",
    "/onboard/trial/signup",
    "/login",
    "/register",
    "/logout",
    "/health",
    "/verify-email",
    "/verify-executor-email",
    "/resend-verification",
    "/forgot-password",
    "/reset-password",
}

# Routes protected by HTTP Basic Auth (API docs)
BASIC_AUTH_ROUTES = {
    "/docs",
    "/docs/oauth2-redirect",
    "/openapi.json",
    "/redoc",
}

# Allowed credentials for docs access (username: password)
# NOTE: This is ONLY for HTTP Basic Auth on /docs and /openapi.json (Swagger UI).
# This has NOTHING to do with the /login form — that uses users table in DB.
# If /login fails, check: SELECT email, role, is_superuser FROM users;
_DOCS_CREDENTIALS = {
    "max.breger@gmail.com": "MethodB2024!",
    "Jekorn12@gmail.com": "JennyRamp2026!",
}

# Prefixes that don't require authentication
PUBLIC_PREFIXES = (
    "/auth/",
    "/static/",
    "/api/oauth/",
    "/api/extension/",
    "/tasks/",
    "/demo/",
)


def _check_basic_auth(request: Request) -> bool:
    """Validate HTTP Basic Auth credentials for docs access."""
    import base64

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Basic "):
        return False

    try:
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        username, password = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError):
        return False

    expected_password = _DOCS_CREDENTIALS.get(username)
    if expected_password is None:
        return False

    return secrets.compare_digest(password, expected_password)


def _basic_auth_response() -> Response:
    """Return 401 with WWW-Authenticate header to trigger browser login dialog."""
    return Response(
        content="Unauthorized",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="API Docs"'},
    )


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Docs routes — HTTP Basic Auth (independent of JWT session)
        if path in BASIC_AUTH_ROUTES:
            if not _check_basic_auth(request):
                return _basic_auth_response()
            return await call_next(request)

        # Skip auth for public routes
        if path in PUBLIC_ROUTES or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)

        # Check JWT cookie
        token = request.cookies.get("access_token")
        if not token:
            # Onboarding routes → redirect to trial signup (not login)
            if path.startswith("/onboard/"):
                return RedirectResponse(url="/onboard/trial?next=onboarding", status_code=303)
            logger.debug("No auth token, redirecting to login: %s", path)
            return RedirectResponse(url="/login", status_code=303)

        payload = decode_access_token(token)
        if not payload:
            # Onboarding routes → redirect to trial signup (not login)
            if path.startswith("/onboard/"):
                return RedirectResponse(url="/onboard/trial?next=onboarding", status_code=303)
            logger.debug("Invalid auth token, redirecting to login: %s", path)
            return RedirectResponse(url="/login", status_code=303)

        # Attach user info to request state
        request.state.user_id = payload.get("sub")
        request.state.user_email = payload.get("email")
        request.state.user_full_name = payload.get("full_name", "")
        request.state.user_role = payload.get("role", "")
        request.state.is_superuser = payload.get("is_superuser", False)

        logger.debug(
            "AUTH_REQUEST | method=%s | path=%s | user=%s | role=%s",
            request.method, path, payload.get("email"), payload.get("role"),
        )

        return await call_next(request)
