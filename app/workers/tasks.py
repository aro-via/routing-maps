"""app/workers/tasks.py — Celery tasks for real-time GPS processing.

process_gps_update is enqueued by the WebSocket handler every time the
driver app sends a position fix.  It:
  1. Updates GPS in Redis driver state.
  2. Marks a stop complete (if provided).
  3. Runs delay detection — exits early if no re-route is needed.
  4. Re-optimises the route with the remaining stops.
  5. Persists the new route and publishes it via Redis Pub/Sub so the
     WebSocket handler can push it to the driver app.

No PHI appears in task arguments, log messages, or Redis channels.
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import redis as redis_lib

from app.config import settings
from app.models.schemas import Location, Stop
from app.optimizer.pipeline import run_optimization
from app.state.driver_state import (
    DriverState,
    get_driver_state,
    mark_stop_completed,
    save_driver_state,
    update_driver_gps,
)
from app.workers.celery_app import celery_app
from app.workers.delay_detector import should_reroute

logger = logging.getLogger(__name__)

# Redis Pub/Sub channel template — no PHI, only driver ID (internal UUID)
_REROUTE_CHANNEL = "reroute:{driver_id}"


def _get_redis() -> "redis_lib.Redis | None":
    """Return a connected Redis client for Pub/Sub publishing."""
    try:
        r = redis_lib.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            decode_responses=True,
        )
        r.ping()
        return r
    except Exception as exc:
        logger.warning("Redis unavailable in tasks: %s", exc)
        return None


def _remaining_stops(state: DriverState) -> list[Stop]:
    """Return Stop objects for all stops not yet completed."""
    completed = set(state.completed_stop_ids)
    stops = []
    for entry in state.current_route:
        if entry["stop_id"] not in completed:
            stops.append(
                Stop(
                    stop_id=entry["stop_id"],
                    location=Location(
                        lat=entry["location"]["lat"],
                        lng=entry["location"]["lng"],
                    ),
                    earliest_pickup=entry.get("earliest_pickup", "00:00"),
                    latest_pickup=entry.get("latest_pickup", "23:59"),
                    service_time_minutes=entry.get("service_time_minutes", 10),
                )
            )
    return stops


@celery_app.task(name="app.workers.tasks.process_gps_update")
def process_gps_update(
    driver_id: str,
    lat: float,
    lng: float,
    timestamp: str,
    completed_stop_id: Optional[str] = None,
) -> dict:
    """Process a single GPS position fix from the driver app.

    Args:
        driver_id:          Driver identifier (internal UUID, no PHI).
        lat:                Current latitude.
        lng:                Current longitude.
        timestamp:          ISO-8601 UTC timestamp of the GPS fix.
        completed_stop_id:  Optional stop that the driver just completed.

    Returns:
        Dict with keys: rerouted (bool), reason (str).
    """
    logger.info("GPS update: driver=%s lat=%.4f lng=%.4f", driver_id, lat, lng)

    # 1. Persist GPS fix immediately (short TTL key)
    update_driver_gps(driver_id, lat, lng, timestamp)

    # 2. Load full driver state
    state = get_driver_state(driver_id)
    if state is None:
        logger.warning("process_gps_update: no active state for driver=%s", driver_id)
        return {"rerouted": False, "reason": "no_state"}

    # 3. Mark stop completed if provided
    if completed_stop_id:
        mark_stop_completed(driver_id, completed_stop_id)
        state = get_driver_state(driver_id)  # reload after mutation
        state.stops_changed = True           # flag for delay detector

    # 4. Run delay detection
    triggered, reason = should_reroute(state)
    if not triggered:
        save_driver_state(state)
        return {"rerouted": False, "reason": reason}

    # 5. Re-optimise with remaining stops and current driver position
    remaining = _remaining_stops(state)
    if not remaining:
        logger.info("No remaining stops for driver=%s — skipping reroute", driver_id)
        save_driver_state(state)
        return {"rerouted": False, "reason": "no_remaining_stops"}

    driver_location = Location(lat=lat, lng=lng)
    departure_time = datetime.now(timezone.utc)

    try:
        new_route = asyncio.run(
            run_optimization(
                driver_id=driver_id,
                driver_location=driver_location,
                stops=remaining,
                departure_time=departure_time,
            )
        )
    except Exception as exc:
        logger.error("Re-optimisation failed for driver=%s: %s", driver_id, exc)
        save_driver_state(state)
        return {"rerouted": False, "reason": "optimization_failed"}

    # 6. Update driver state with new route
    state.current_route = [s.model_dump() for s in new_route.optimized_stops]
    state.remaining_duration = new_route.total_duration_minutes
    state.last_reroute_timestamp = time.time()
    state.stops_changed = False
    save_driver_state(state)

    # 7. Publish new route to Redis Pub/Sub → WebSocket handler pushes to driver
    channel = _REROUTE_CHANNEL.format(driver_id=driver_id)
    payload = json.dumps({
        "type": "route_updated",
        "reason": reason,
        "optimized_stops": [s.model_dump() for s in new_route.optimized_stops],
        "total_duration_minutes": new_route.total_duration_minutes,
        "google_maps_url": new_route.google_maps_url,
    })
    r = _get_redis()
    if r:
        r.publish(channel, payload)
        logger.info(
            "Reroute published: driver=%s reason=%s stops=%d channel=%s",
            driver_id,
            reason,
            len(new_route.optimized_stops),
            channel,
        )

    return {"rerouted": True, "reason": reason}
