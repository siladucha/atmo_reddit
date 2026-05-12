"""Error handling middleware — catches exceptions and shows friendly pages."""

import logging
import traceback

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse

logger = logging.getLogger(__name__)

ERROR_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Error — Reddit SaaS</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-50 min-h-screen flex items-center justify-center">
    <div class="bg-white p-8 rounded-lg shadow-md max-w-lg text-center">
        <div class="text-4xl mb-3">⚠️</div>
        <h1 class="text-xl font-bold text-gray-800 mb-2">Something went wrong</h1>
        <p class="text-gray-500 mb-4">{message}</p>
        <a href="/" class="text-blue-600 hover:underline">← Back to Dashboard</a>
        {debug}
    </div>
</body>
</html>
"""


def _format_exception_chain(exc: BaseException) -> str:
    """Format exception with full chain, handling ExceptionGroups from Starlette."""
    try:
        # Simple approach: use traceback.format_exception which handles chains internally
        lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
        return "".join(lines)
    except RecursionError:
        return f"{type(exc).__name__}: {exc}"


def _extract_app_frames(exc: BaseException) -> str:
    """Extract only /app/ frames from the traceback for concise audit logging."""
    try:
        lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
        full = "".join(lines)
        app_lines = []
        for line in full.splitlines():
            if "/app/" in line and "site-packages" not in line:
                app_lines.append(line.strip())
        # Add the final error line
        app_lines.append(f"{type(exc).__name__}: {exc}")
        return "\n".join(app_lines[-10:])
    except Exception:
        return f"{type(exc).__name__}: {exc}"


def _log_error_to_audit(request: Request, error: Exception) -> None:
    """Best-effort logging of unhandled errors to the audit_log table."""
    try:
        from app.database import SessionLocal
        from app.services.audit import log_system_action

        user_id_str = getattr(request.state, "user_id", None)
        app_frames = _extract_app_frames(error)

        db = SessionLocal()
        try:
            log_system_action(
                db=db,
                action="error",
                entity_type="system",
                details={
                    "path": str(request.url.path),
                    "method": request.method,
                    "error_type": type(error).__name__,
                    "error_message": str(error)[:500],
                    "user_id": str(user_id_str) if user_id_str else None,
                    "traceback": app_frames[:2000],
                },
            )
        finally:
            db.close()
    except Exception:
        # Never let audit logging break the error response
        pass


class ErrorMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, debug: bool = False):
        super().__init__(app)
        self.debug = debug

    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)

            # Handle 404s with a friendly page
            if response.status_code == 404 and "text/html" in request.headers.get("accept", ""):
                return HTMLResponse(
                    ERROR_HTML.format(message="Page not found.", debug=""),
                    status_code=404,
                )

            return response

        except Exception as e:
            # Format full traceback including ExceptionGroups
            full_tb = _format_exception_chain(e)

            logger.error("Unhandled error on %s: %s", request.url.path, e)
            logger.error(full_tb)

            # Log to audit table (with app-specific frames)
            _log_error_to_audit(request, e)

            debug_info = ""
            if self.debug:
                debug_info = (
                    f'<pre class="mt-4 text-left text-xs bg-gray-100 p-3 rounded '
                    f'overflow-auto max-h-96 whitespace-pre-wrap">{full_tb}</pre>'
                )

            return HTMLResponse(
                ERROR_HTML.format(
                    message=str(e) if self.debug else "An unexpected error occurred. Check the logs.",
                    debug=debug_info,
                ),
                status_code=500,
            )
