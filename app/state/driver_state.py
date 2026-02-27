"""app/state/driver_state.py — Redis-backed active driver session state.

Each active driver shift is stored as a single JSON document at:

    driver:{driver_id}:state   TTL = DRIVER_STATE_TTL_SECONDS (12 h default)

GPS updates additionally maintain a short-lived key:

    driver:{driver_id}:last_gps   TTL = 300 s (5 min)

No PHI is stored — only stop IDs (caller-managed UUIDs) and (lat, lng)
coordinates.
"""
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import redis as redis_lib

from app.config import settings

logger = logging.getLogger(__name__)

_GPS_TTL_SECONDS = 300  # last_gps expires after 5 minutes of no updates


# ---------------------------------------------------------------------------
# DriverState dataclass
# ---------------------------------------------------------------------------

@dataclass
class DriverState:
    """All mutable state for a single active driver shift.

    Fields that the delay detector reads:
        schedule_delay_minutes        — minutes behind the original schedule
        remaining_duration            — current predicted remaining route time (minutes)
        original_remaining_duration   — baseline remaining route time (minutes)
        last_reroute_timestamp        — Unix time of last re-route (None = never)
        stops_changed                 — True when dispatcher adds/cancels a stop
    """
    driver_id: str
    current_route: List[Dict[str, Any]] = field(default_factory=list)
    last_gps: Optional[Dict[str, Any]] = field(default=None)   # {lat, lng, timestamp}
    completed_stop_ids: List[str] = field(default_factory=list)
    remaining_duration: float = 0.0            # minutes — updated each GPS cycle
    original_remaining_duration: float = 0.0   # minutes — set once at route start
    schedule_delay_minutes: float = 0.0
    last_reroute_timestamp: Optional[float] = field(default=None)  # Unix timestamp
    stops_changed: bool = False
    status: str = "active"   # "active" | "completed" | "idle"


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------

def _get_redis() -> "redis_lib.Redis | None":
    """Return a connected Redis client, or None if unavailable."""
    try:
        r = redis_lib.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            decode_responses=True,
        )
        r.ping()
        return r
    except Exception as exc:
        logger.warning("Redis unavailable for driver state: %s", exc)
        return None


def _state_key(driver_id: str) -> str:
    """Return the Redis key for the driver's state document."""
    return f"driver:{driver_id}:state"


def _gps_key(driver_id: str) -> str:
    """Return the Redis key for the driver's latest GPS fix."""
    return f"driver:{driver_id}:last_gps"


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def save_driver_state(state: DriverState) -> None:
    """Serialise and persist the full DriverState to Redis.

    TTL is reset to DRIVER_STATE_TTL_SECONDS on every save.
    GPS is written to a separate key with a 5-minute TTL.
    """
    r = _get_redis()
    if r is None:
        return

    data = asdict(state)
    gps = data.pop("last_gps", None)

    r.setex(
        _state_key(state.driver_id),
        settings.DRIVER_STATE_TTL_SECONDS,
        json.dumps(data),
    )
    if gps is not None:
        r.setex(_gps_key(state.driver_id), _GPS_TTL_SECONDS, json.dumps(gps))

    logger.debug("Saved driver state: driver_id=%s status=%s", state.driver_id, state.status)


def get_driver_state(driver_id: str) -> Optional[DriverState]:
    """Load and deserialise the DriverState for the given driver.

    Returns None if the state does not exist or has expired.
    """
    r = _get_redis()
    if r is None:
        return None

    raw = r.get(_state_key(driver_id))
    if raw is None:
        return None

    data = json.loads(raw)
    # Re-attach GPS (may have expired independently)
    gps_raw = r.get(_gps_key(driver_id))
    data["last_gps"] = json.loads(gps_raw) if gps_raw else None

    return DriverState(**data)


def update_driver_gps(
    driver_id: str,
    lat: float,
    lng: float,
    timestamp: str,
) -> None:
    """Update only the GPS position for a driver (does not reload full state).

    Writes to the short-TTL GPS key and patches last_gps in the state doc.
    """
    r = _get_redis()
    if r is None:
        return

    gps = {"lat": lat, "lng": lng, "timestamp": timestamp}
    r.setex(_gps_key(driver_id), _GPS_TTL_SECONDS, json.dumps(gps))

    # Patch last_gps inside the state document without a full round-trip
    raw = r.get(_state_key(driver_id))
    if raw is not None:
        data = json.loads(raw)
        data["last_gps"] = gps
        ttl = r.ttl(_state_key(driver_id))
        if ttl > 0:
            r.setex(_state_key(driver_id), ttl, json.dumps(data))

    logger.debug("GPS updated: driver_id=%s lat=%.4f lng=%.4f", driver_id, lat, lng)


def mark_stop_completed(driver_id: str, stop_id: str) -> None:
    """Append stop_id to the driver's completed_stop_ids list."""
    r = _get_redis()
    if r is None:
        return

    raw = r.get(_state_key(driver_id))
    if raw is None:
        logger.warning("mark_stop_completed: no state found for driver_id=%s", driver_id)
        return

    data = json.loads(raw)
    if stop_id not in data["completed_stop_ids"]:
        data["completed_stop_ids"].append(stop_id)

    ttl = r.ttl(_state_key(driver_id))
    if ttl > 0:
        r.setex(_state_key(driver_id), ttl, json.dumps(data))

    logger.debug("Stop completed: driver_id=%s stop_id=%s", driver_id, stop_id)


def clear_driver_state(driver_id: str) -> None:
    """Delete all Redis keys for this driver (called at end of shift)."""
    r = _get_redis()
    if r is None:
        return

    r.delete(_state_key(driver_id), _gps_key(driver_id))
    logger.info("Driver state cleared: driver_id=%s", driver_id)
