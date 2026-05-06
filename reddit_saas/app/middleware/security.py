"""Security middleware — adds protective HTTP headers and rate limiting."""

import logging
import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from app.config import get_config

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        # Prevent MIME-type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # XSS protection (legacy browsers)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # Referrer policy — don't leak full URL to external sites
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Permissions policy — disable unnecessary browser features
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        # HSTS — only in production (requires HTTPS)
        app_env = get_config("app_env")
        if app_env == "production":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiter for auth endpoints.

    Limits login/register attempts per IP to prevent brute-force attacks.
    Uses a sliding window approach with configurable limits.

    NOTE: For multi-process deployments, replace with Redis-backed rate limiting.
    """

    def __init__(
        self,
        app,
        auth_limit: int = 5,
        auth_window_seconds: int = 900,  # 15 minutes
        global_limit: int = 100,
        global_window_seconds: int = 60,
        enabled: bool = True,
    ):
        super().__init__(app)
        self.auth_limit = auth_limit
        self.auth_window = auth_window_seconds
        self.global_limit = global_limit
        self.global_window = global_window_seconds
        self.enabled = enabled
        # {ip: [timestamp, ...]}
        self._auth_attempts: dict[str, list[float]] = defaultdict(list)
        self._global_requests: dict[str, list[float]] = defaultdict(list)

    # Endpoints that get strict rate limiting
    _AUTH_PATHS = {"/login", "/register", "/auth/login", "/auth/register"}

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP, respecting X-Forwarded-For behind reverse proxy."""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _cleanup_window(self, timestamps: list[float], window: int) -> list[float]:
        """Remove timestamps outside the current window."""
        cutoff = time.time() - window
        return [t for t in timestamps if t > cutoff]

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip rate limiting when disabled (e.g., during tests)
        if not self.enabled:
            return await call_next(request)

        ip = self._get_client_ip(request)
        now = time.time()
        path = request.url.path

        # Auth endpoint rate limiting (POST only)
        if request.method == "POST" and path in self._AUTH_PATHS:
            self._auth_attempts[ip] = self._cleanup_window(
                self._auth_attempts[ip], self.auth_window
            )
            if len(self._auth_attempts[ip]) >= self.auth_limit:
                logger.warning(
                    "RATE_LIMIT_AUTH | ip=%s | path=%s | attempts=%d",
                    ip, path, len(self._auth_attempts[ip]),
                )
                return JSONResponse(
                    {"detail": "Too many attempts. Please try again later."},
                    status_code=429,
                    headers={"Retry-After": str(self.auth_window)},
                )
            self._auth_attempts[ip].append(now)

        # Global per-IP rate limiting
        self._global_requests[ip] = self._cleanup_window(
            self._global_requests[ip], self.global_window
        )
        if len(self._global_requests[ip]) >= self.global_limit:
            logger.warning(
                "RATE_LIMIT_GLOBAL | ip=%s | path=%s | requests=%d",
                ip, path, len(self._global_requests[ip]),
            )
            return JSONResponse(
                {"detail": "Rate limit exceeded. Please slow down."},
                status_code=429,
                headers={"Retry-After": str(self.global_window)},
            )
        self._global_requests[ip].append(now)

        return await call_next(request)
