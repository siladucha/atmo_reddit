"""Trial Signal Middleware — lightweight page view detection for trial users.

Intercepts GET requests from trial users and records page view signals.
Only fires for plan_type="trial" clients. Skips static assets, API calls,
health checks, and non-GET requests.

Route → Signal mapping:
    /clients/{id}/home       → page_view (engagement)
    /clients/{id}/report     → report_viewed (value_realization)
    /clients/{id}/epg        → epg_viewed (engagement)
    /clients/{id}/avatars    → avatars_viewed (engagement)
    /clients/{id}/strategy   → strategy_viewed (value_realization)
    /clients/{id}/settings   → settings_viewed (engagement)
    /admin/pricing           → pricing_viewed (conversion)
    /onboard/upgrade         → pricing_viewed (conversion)
    /clients/{id}/keywords   → keywords_configured (intent)
    /clients/{id}/subreddits → subreddits_configured (intent)

Fire-and-forget: never blocks the request. All errors silently logged.
"""

import logging
import re
from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger(__name__)

# Route patterns → (signal_type, signal_category)
# Patterns match against the request path after /clients/{uuid}/
_PORTAL_SIGNAL_MAP: dict[str, tuple[str, str]] = {
    "home": ("page_view", "engagement"),
    "report": ("report_viewed", "value_realization"),
    "epg": ("epg_viewed", "engagement"),
    "avatars": ("avatars_viewed", "engagement"),
    "strategy": ("strategy_viewed", "value_realization"),
    "settings": ("settings_viewed", "engagement"),
    "review": ("review_viewed", "engagement"),
    "activity": ("activity_viewed", "engagement"),
}

# Intent signals from settings sub-pages
_INTENT_PATHS: dict[str, tuple[str, str]] = {
    "keywords": ("keywords_configured", "intent"),
    "subreddits": ("subreddits_configured", "intent"),
}

# Conversion signals (path prefix → signal_type, category)
_CONVERSION_PATHS: list[tuple[str, str, str]] = [
    ("/admin/pricing", "pricing_viewed", "conversion"),
    ("/onboard/upgrade", "pricing_viewed", "conversion"),
]

# Regex to extract client_id from /clients/{uuid}/... paths
_CLIENT_PATH_RE = re.compile(r"^/clients/([0-9a-f\-]{36})/(\w+)")

# Paths to skip entirely
_SKIP_PREFIXES = (
    "/static/",
    "/api/",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/auth/",
    "/favicon",
)


class TrialSignalMiddleware(BaseHTTPMiddleware):
    """Intercepts GET requests from trial users and records page view signals.

    Fire-and-forget: all signal recording happens after the response is sent.
    Never blocks the user request.
    """

    async def dispatch(self, request: Request, call_next):
        # Only process GET requests (page views)
        if request.method != "GET":
            return await call_next(request)

        path = request.url.path

        # Skip static/API/health/docs paths
        if path.startswith(_SKIP_PREFIXES):
            return await call_next(request)

        # Let the request proceed first (never block)
        response = await call_next(request)

        # Only record signals for successful page loads (2xx)
        if response.status_code < 200 or response.status_code >= 300:
            return response

        # Fire-and-forget signal recording
        try:
            self._record_page_signal(request, path)
        except Exception:
            # Never let signal recording affect the response
            pass

        return response

    def _record_page_signal(self, request: Request, path: str) -> None:
        """Attempt to record a page view signal. Fire-and-forget."""
        # Check if user is authenticated (has user_id from AuthMiddleware)
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            return

        # Determine signal from path
        signal_info = self._resolve_signal(request, path)
        if not signal_info:
            return

        signal_type, signal_category, client_id_str = signal_info

        # Dispatch background recording (fire-and-forget)
        try:
            client_id = UUID(client_id_str)
        except (ValueError, TypeError):
            return

        from app.services.trial_signal_hooks import record_trial_signal_background

        record_trial_signal_background(
            client_id=client_id,
            signal_type=signal_type,
            signal_category=signal_category,
            signal_value={"path": path, "source": "middleware"},
        )

    def _resolve_signal(self, request: Request, path: str) -> tuple[str, str, str] | None:
        """Map a request path to (signal_type, signal_category, client_id).

        Returns None if the path doesn't match any tracked pattern.
        """
        # Check portal paths: /clients/{uuid}/{page}
        match = _CLIENT_PATH_RE.match(path)
        if match:
            client_id = match.group(1)
            page = match.group(2)

            # Check intent paths (keywords/subreddits)
            if page in _INTENT_PATHS:
                signal_type, category = _INTENT_PATHS[page]
                return (signal_type, category, client_id)

            # Check standard portal signals
            if page in _PORTAL_SIGNAL_MAP:
                signal_type, category = _PORTAL_SIGNAL_MAP[page]
                return (signal_type, category, client_id)

            return None

        # Check conversion paths (pricing/upgrade) — resolve client_id from user
        for prefix, signal_type, category in _CONVERSION_PATHS:
            if path.startswith(prefix):
                client_id_str = self._get_user_client_id(request)
                if client_id_str:
                    return (signal_type, category, client_id_str)
                return None

        return None

    def _get_user_client_id(self, request: Request) -> str | None:
        """Resolve client_id for the current user from DB. Lightweight lookup.

        Used for conversion paths where client_id is not in the URL.
        Returns None if user has no client association.
        """
        try:
            user_id_str = getattr(request.state, "user_id", None)
            if not user_id_str:
                return None

            from app.database import SessionLocal
            from app.models.user import User

            user_uuid = UUID(user_id_str)
            db = SessionLocal()
            try:
                user = db.query(User.client_id).filter(User.id == user_uuid).first()
                if user and user.client_id:
                    return str(user.client_id)
            finally:
                db.close()
        except Exception:
            pass
        return None
