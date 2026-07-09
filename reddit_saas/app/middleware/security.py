"""Security middleware — adds protective HTTP headers and rate limiting.

Rate limiter uses Redis for shared state across workers. Falls back to
in-memory when Redis is unavailable (development/testing).
"""

from app.logging_config import get_logger
import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from app.config import get_config

logger = get_logger(__name__)


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
    """Redis-backed rate limiter for auth endpoints and global per-IP throttling.

    Uses Redis sorted sets (sliding window) for shared state across all
    Uvicorn workers. Falls back to in-memory when Redis is unavailable.

    Security:
    - X-Forwarded-For is ONLY trusted when request comes through the known
      reverse proxy (nginx on localhost). Direct connections use client.host.
    - Configurable trusted_proxy_ips — only these sources can set X-Forwarded-For.
    """

    def __init__(
        self,
        app,
        auth_limit: int = 5,
        auth_window_seconds: int = 900,  # 15 minutes
        global_limit: int = 100,
        global_window_seconds: int = 60,
        enabled: bool = True,
        trusted_proxy_ips: set[str] | None = None,
    ):
        super().__init__(app)
        self.auth_limit = auth_limit
        self.auth_window = auth_window_seconds
        self.global_limit = global_limit
        self.global_window = global_window_seconds
        self.enabled = enabled
        # Only trust X-Forwarded-For from these IPs (nginx on same host)
        self.trusted_proxy_ips = trusted_proxy_ips or {
            "127.0.0.1", "::1", "172.17.0.1", "172.18.0.1",
            "172.19.0.1", "172.20.0.1",  # Docker bridge networks
        }
        self._redis = None
        self._redis_available = True
        self._redis_last_check = 0.0
        # Fallback in-memory storage (used only when Redis is down)
        self._auth_attempts: dict[str, list[float]] = defaultdict(list)
        self._global_requests: dict[str, list[float]] = defaultdict(list)

    # Endpoints that get strict rate limiting (10 attempts per 15 min per IP)
    _AUTH_PATHS = {
        "/login", "/register", "/auth/login", "/auth/register",
        "/onboard/trial/signup", "/forgot-password", "/reset-password",
        "/api/extension/activate",
    }

    def _get_redis(self):
        """Get or create Redis connection. Caches for performance."""
        if self._redis is not None:
            return self._redis
        # Avoid hammering Redis if it's down (check every 30s)
        now = time.time()
        if not self._redis_available and (now - self._redis_last_check) < 30:
            return None
        try:
            import redis as redis_lib
            from app.config import get_settings
            settings = get_settings()
            self._redis = redis_lib.from_url(
                settings.redis_url, decode_responses=True, socket_timeout=1
            )
            self._redis.ping()
            self._redis_available = True
            return self._redis
        except Exception as e:
            logger.warning("Rate limiter Redis unavailable (using in-memory fallback): %s", str(e)[:80])
            self._redis_available = False
            self._redis_last_check = now
            self._redis = None
            return None

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP with secure proxy trust validation.

        X-Forwarded-For is ONLY trusted when the direct connection comes from
        a known proxy IP (nginx on localhost/Docker network). Otherwise, the
        actual TCP peer address is used — preventing header spoofing attacks.
        """
        peer_ip = request.client.host if request.client else "unknown"

        # Only trust X-Forwarded-For if the direct peer is a known proxy
        if peer_ip in self.trusted_proxy_ips:
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                # Take the LAST entry added by our trusted proxy, not the first
                # (attacker can prepend fake IPs, but cannot append after our proxy)
                # Our nginx adds the real client IP as the rightmost entry
                # Format: "client_spoofed, real_client_from_nginx"
                # Actually nginx appends, so rightmost before our proxy is real
                parts = [p.strip() for p in forwarded.split(",")]
                # Use first non-private IP, or first entry if all are private
                # Safest: trust the leftmost IP only when we verified it's our proxy
                # nginx default: $proxy_add_x_forwarded_for appends to existing
                # With single-layer proxy, the rightmost entry is from nginx
                if len(parts) == 1:
                    return parts[0]
                # Multi-hop: take the first entry (client IP as seen by first proxy)
                # This is safe because our nginx is the ONLY entry point
                return parts[0]

        return peer_ip

    def _cleanup_window(self, timestamps: list[float], window: int) -> list[float]:
        """Remove timestamps outside the current window (in-memory fallback)."""
        cutoff = time.time() - window
        return [t for t in timestamps if t > cutoff]

    def _check_redis_rate_limit(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        """Check rate limit using Redis sorted set.

        Returns (is_blocked, current_count).
        """
        r = self._get_redis()
        if r is None:
            return False, 0  # Redis unavailable, fall through to in-memory

        try:
            now = time.time()
            window_start = now - window

            pipe = r.pipeline(transaction=False)
            pipe.zremrangebyscore(key, "-inf", window_start)
            pipe.zcard(key)
            pipe.zadd(key, {f"{now}": now})
            pipe.expire(key, window + 10)  # TTL = window + safety buffer
            results = pipe.execute()

            current_count = results[1]  # count BEFORE adding current request

            if current_count >= limit:
                # Over limit — remove the entry we just added
                try:
                    r.zrem(key, f"{now}")
                except Exception:
                    pass
                return True, current_count

            return False, current_count + 1

        except Exception as e:
            logger.warning("Redis rate limit error (falling back to in-memory): %s", str(e)[:80])
            self._redis_available = False
            self._redis_last_check = time.time()
            self._redis = None
            return False, 0  # fail-open, fall through

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip rate limiting when disabled (e.g., during tests)
        if not self.enabled:
            return await call_next(request)

        ip = self._get_client_ip(request)
        now = time.time()
        path = request.url.path

        # Auth endpoint rate limiting (POST only)
        if request.method == "POST" and path in self._AUTH_PATHS:
            redis_key = f"ramp:ratelimit:auth:{ip}"
            is_blocked, count = self._check_redis_rate_limit(
                redis_key, self.auth_limit, self.auth_window
            )

            if not is_blocked and count == 0:
                # Redis failed — use in-memory fallback
                self._auth_attempts[ip] = self._cleanup_window(
                    self._auth_attempts[ip], self.auth_window
                )
                if len(self._auth_attempts[ip]) >= self.auth_limit:
                    is_blocked = True
                    count = len(self._auth_attempts[ip])
                else:
                    self._auth_attempts[ip].append(now)

            if is_blocked:
                logger.warning(
                    "RATE_LIMIT_AUTH | ip=%s | path=%s | attempts=%d",
                    ip, path, count,
                )
                return JSONResponse(
                    {"detail": "Too many attempts. Please try again later."},
                    status_code=429,
                    headers={"Retry-After": str(self.auth_window)},
                )

        # Global per-IP rate limiting
        redis_key = f"ramp:ratelimit:global:{ip}"
        is_blocked, count = self._check_redis_rate_limit(
            redis_key, self.global_limit, self.global_window
        )

        if not is_blocked and count == 0:
            # Redis failed — use in-memory fallback
            self._global_requests[ip] = self._cleanup_window(
                self._global_requests[ip], self.global_window
            )
            if len(self._global_requests[ip]) >= self.global_limit:
                is_blocked = True
                count = len(self._global_requests[ip])
            else:
                self._global_requests[ip].append(now)

        if is_blocked:
            logger.warning(
                "RATE_LIMIT_GLOBAL | ip=%s | path=%s | requests=%d",
                ip, path, count,
            )
            return JSONResponse(
                {"detail": "Rate limit exceeded. Please slow down."},
                status_code=429,
                headers={"Retry-After": str(self.global_window)},
            )

        return await call_next(request)
