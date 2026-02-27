"""app/websocket/manager.py — WebSocket connection registry and Redis Pub/Sub listener.

ConnectionManager holds the in-memory map of driver_id → WebSocket.  Each
connected driver gets an async background task that subscribes to their
personal Redis Pub/Sub channel (reroute:{driver_id}) and forwards any
route_updated payloads published by the Celery task.

No PHI is stored here — only driver_id (internal UUID) and WebSocket handles.
"""
import asyncio
import json
import logging

import redis.asyncio as aioredis
from fastapi import WebSocket

from app.config import settings
from app.state.driver_state import clear_driver_state

logger = logging.getLogger(__name__)

# Redis Pub/Sub channel template (mirrors app/workers/tasks.py)
_REROUTE_CHANNEL = "reroute:{driver_id}"


class ConnectionManager:
    """In-memory registry of active driver WebSocket connections.

    A single shared instance (``manager``) is imported by the WebSocket
    handler.  The class is intentionally simple — connection state is held
    per-process so a single Uvicorn worker is assumed for Phase 2.
    """

    def __init__(self) -> None:
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, driver_id: str, websocket: WebSocket) -> None:
        """Accept and register a new driver WebSocket connection."""
        await websocket.accept()
        self.active_connections[driver_id] = websocket
        logger.info(
            "WebSocket connected: driver=%s active=%d",
            driver_id,
            len(self.active_connections),
        )

    def disconnect(self, driver_id: str) -> None:
        """Remove the driver's connection and clear their Redis driver state."""
        self.active_connections.pop(driver_id, None)
        clear_driver_state(driver_id)
        logger.info(
            "WebSocket disconnected: driver=%s active=%d",
            driver_id,
            len(self.active_connections),
        )

    async def send_route_update(self, driver_id: str, route_data: dict) -> None:
        """Push a route_updated payload to the driver over WebSocket.

        Silently skips if the driver is no longer connected.
        """
        websocket = self.active_connections.get(driver_id)
        if websocket is None:
            logger.warning(
                "send_route_update: no active connection for driver=%s", driver_id
            )
            return
        try:
            await websocket.send_json(route_data)
            logger.debug("Route update sent: driver=%s", driver_id)
        except Exception as exc:
            logger.warning(
                "Failed to send route update to driver=%s: %s", driver_id, exc
            )

    async def listen_for_reroutes(self, driver_id: str) -> None:
        """Subscribe to the driver's Redis Pub/Sub channel and forward messages.

        Runs as an ``asyncio`` background task created by the WebSocket
        handler.  Exits cleanly when cancelled (on driver disconnect).
        """
        channel = _REROUTE_CHANNEL.format(driver_id=driver_id)
        r: aioredis.Redis | None = None
        pubsub = None
        try:
            r = aioredis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                decode_responses=True,
            )
            pubsub = r.pubsub()
            await pubsub.subscribe(channel)
            logger.info(
                "Pub/Sub listening: channel=%s driver=%s", channel, driver_id
            )

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    payload = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.warning(
                        "Invalid Pub/Sub message on %s: %s", channel, exc
                    )
                    continue
                await self.send_route_update(driver_id, payload)

        except asyncio.CancelledError:
            logger.info("Pub/Sub listener cancelled: driver=%s", driver_id)
            raise
        except Exception as exc:
            logger.error(
                "Pub/Sub listener error: driver=%s error=%s", driver_id, exc
            )
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(channel)
                except Exception:
                    pass
            if r is not None:
                try:
                    await r.aclose()
                except Exception:
                    pass


# Shared singleton used by the WebSocket handler and tests.
manager = ConnectionManager()
