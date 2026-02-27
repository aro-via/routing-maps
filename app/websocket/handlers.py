"""app/websocket/handlers.py — WebSocket endpoint for real-time GPS tracking.

Endpoint: WS /ws/driver/{driver_id}

Driver → Server message (every 15 s, or per adaptive interval):
  {
    "type": "gps_update",
    "lat": 40.7128,
    "lng": -74.0060,
    "timestamp": "2024-01-15T08:14:30Z",
    "completed_stop_id": "stop_002"      // optional
  }

Server → Driver messages are pushed by the ConnectionManager when the
Celery re-routing task publishes to the driver's Redis Pub/Sub channel.

No PHI appears in any log message or WebSocket frame beyond stop_id UUIDs.
"""
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.websocket.manager import manager
from app.workers.tasks import process_gps_update

logger = logging.getLogger(__name__)

ws_router = APIRouter()


@ws_router.websocket("/ws/driver/{driver_id}")
async def driver_route_stream(websocket: WebSocket, driver_id: str) -> None:
    """Handle a driver WebSocket session.

    Flow:
      1. Accept connection and register with ConnectionManager.
      2. Start a background asyncio task that subscribes to the driver's
         Redis Pub/Sub channel and pushes route_updated messages.
      3. Receive GPS JSON frames in a loop; validate and dispatch the
         process_gps_update Celery task for each valid gps_update message.
      4. On disconnect (clean or error): cancel the Pub/Sub listener and
         unregister the connection (which also clears driver state in Redis).
    """
    await manager.connect(driver_id, websocket)
    listener_task = asyncio.create_task(
        manager.listen_for_reroutes(driver_id),
        name=f"pubsub-{driver_id}",
    )

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "gps_update":
                lat = data.get("lat")
                lng = data.get("lng")
                if lat is None or lng is None:
                    logger.warning(
                        "gps_update missing lat/lng: driver=%s", driver_id
                    )
                    continue

                timestamp = data.get(
                    "timestamp",
                    datetime.now(timezone.utc).isoformat(),
                )
                completed_stop_id = data.get("completed_stop_id")

                process_gps_update.delay(
                    driver_id=driver_id,
                    lat=float(lat),
                    lng=float(lng),
                    timestamp=timestamp,
                    completed_stop_id=completed_stop_id,
                )
                logger.debug(
                    "GPS task dispatched: driver=%s lat=%.4f lng=%.4f",
                    driver_id,
                    lat,
                    lng,
                )
            else:
                logger.debug(
                    "Unhandled message type=%s driver=%s", msg_type, driver_id
                )

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected cleanly: driver=%s", driver_id)
    except Exception as exc:
        logger.warning("WebSocket error: driver=%s error=%s", driver_id, exc)
    finally:
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass
        manager.disconnect(driver_id)
