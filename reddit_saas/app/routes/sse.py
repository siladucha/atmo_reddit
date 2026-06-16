"""SSE (Server-Sent Events) endpoint for real-time notifications.

Clients connect to GET /api/sse/notifications and receive events as they happen.
Uses Redis PubSub to listen for notification events published by Celery workers.
"""

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.permissions import get_current_user
from app.logging_config import get_logger
from app.models.user import User

logger = get_logger(__name__)

router = APIRouter(prefix="/api/sse", tags=["sse"])


@router.get("/notifications")
async def sse_notifications(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """SSE stream for real-time notifications.
    
    The client connects and receives events whenever a new notification
    is published for their client_id via Redis PubSub.
    """
    client_id = user.client_id
    
    # For platform-level users (owner/partner), no client-scoped stream
    if not client_id:
        async def empty_stream():
            yield "data: {\"type\": \"connected\", \"message\": \"No client scope\"}\n\n"
            while True:
                await asyncio.sleep(30)
                yield ": keepalive\n\n"
        return StreamingResponse(empty_stream(), media_type="text/event-stream")

    async def event_stream():
        import redis.asyncio as aioredis
        from app.config import get_settings

        # Send initial connected event
        yield f"data: {json.dumps({'type': 'connected', 'client_id': str(client_id)})}\n\n"

        try:
            r = aioredis.from_url(get_settings().redis_url)
            pubsub = r.pubsub()
            channel = f"notifications:client:{client_id}"
            await pubsub.subscribe(channel)

            # Listen for messages
            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message and message["type"] == "message":
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    yield f"data: {data}\n\n"
                else:
                    # Send keepalive every 15s to prevent timeout
                    yield ": keepalive\n\n"
                    await asyncio.sleep(15)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("SSE stream error: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'message': 'Stream interrupted'})}\n\n"
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
                await r.close()
            except Exception:
                pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
