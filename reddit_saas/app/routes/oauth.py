"""Reddit OAuth callback endpoint for avatar token authorization.

Flow:
1. Admin clicks "Connect OAuth" on avatar page → redirected to Reddit authorize URL
2. Avatar owner logs in on Reddit, clicks "Allow"
3. Reddit redirects to this callback with ?code=AUTH_CODE&state=STATE
4. This endpoint exchanges code for refresh_token and stores it (encrypted) on the avatar

For now: placeholder that confirms the endpoint is reachable.
Full implementation comes with the automated-proxy-posting feature.
"""

from app.logging_config import get_logger

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

logger = get_logger(__name__)

router = APIRouter(prefix="/api/oauth", tags=["oauth"])


@router.get("/reddit/callback")
async def reddit_oauth_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    """Reddit OAuth2 callback endpoint.

    Reddit redirects here after the user authorizes (or denies) the app.
    Query params:
      - code: authorization code (on success)
      - state: anti-CSRF token (contains avatar_id)
      - error: error string (if user denied)
    """
    if error:
        logger.warning("Reddit OAuth denied: error=%s, state=%s", error, state)
        return HTMLResponse(
            content=f"""
            <html><body style="font-family: sans-serif; padding: 40px; background: #1a1a2e; color: #eee;">
                <h2>❌ OAuth Denied</h2>
                <p>The Reddit authorization was denied.</p>
                <p>Error: <code>{error}</code></p>
                <p><a href="/admin" style="color: #4fc3f7;">← Back to Admin</a></p>
            </body></html>
            """,
            status_code=200,
        )

    if not code:
        logger.warning("Reddit OAuth callback called without code or error. state=%s", state)
        return HTMLResponse(
            content="""
            <html><body style="font-family: sans-serif; padding: 40px; background: #1a1a2e; color: #eee;">
                <h2>⚠️ OAuth Callback</h2>
                <p>This endpoint receives Reddit OAuth callbacks.</p>
                <p>No authorization code received. Start the OAuth flow from the avatar admin page.</p>
                <p><a href="/admin" style="color: #4fc3f7;">← Back to Admin</a></p>
            </body></html>
            """,
            status_code=200,
        )

    # TODO: Implement full OAuth code exchange when automated-proxy-posting is built
    # 1. Validate state (extract avatar_id, verify CSRF token)
    # 2. Exchange code for access_token + refresh_token via Reddit API
    # 3. Encrypt and store refresh_token on avatar record
    # 4. Redirect to avatar detail page with success message

    logger.info("Reddit OAuth callback received: code=%s..., state=%s", code[:10] if code else "?", state)

    return HTMLResponse(
        content=f"""
        <html><body style="font-family: sans-serif; padding: 40px; background: #1a1a2e; color: #eee;">
            <h2>✅ OAuth Callback Received</h2>
            <p>Authorization code received successfully.</p>
            <p>State: <code>{state or 'none'}</code></p>
            <p><strong>Note:</strong> Token exchange not yet implemented. This confirms the endpoint is reachable.</p>
            <p><a href="/admin" style="color: #4fc3f7;">← Back to Admin</a></p>
        </body></html>
        """,
        status_code=200,
    )
