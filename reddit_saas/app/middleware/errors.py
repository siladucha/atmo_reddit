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


def _log_error_to_audit(request: Request, error: Exception) -> None:
    """Best-effort logging of unhandled errors to the audit_log table."""
    try:
        from app.database import SessionLocal
        from app.services.audit import log_system_action

        user_id_str = getattr(request.state, "user_id", None)
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
            logger.error("Unhandled error on %s: %s", request.url.path, e)
            logger.error(traceback.format_exc())

            # Log to audit table
            _log_error_to_audit(request, e)

            debug_info = ""
            if self.debug:
                debug_info = f'<pre class="mt-4 text-left text-xs bg-gray-100 p-3 rounded overflow-auto max-h-64">{traceback.format_exc()}</pre>'

            return HTMLResponse(
                ERROR_HTML.format(
                    message=str(e) if self.debug else "An unexpected error occurred. Check the logs.",
                    debug=debug_info,
                ),
                status_code=500,
            )
