import hashlib
import json
import logging
from datetime import datetime
from typing import List, Tuple

import googlemaps
import redis

from app.config import settings

logger = logging.getLogger(__name__)

# Type alias for a (lat, lng) coordinate pair
Coordinate = Tuple[float, float]


def _get_redis() -> "redis.Redis | None":
    """Return a connected Redis client, or None if Redis is unavailable."""
    try:
        r = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            decode_responses=True,
        )
        r.ping()
        return r
    except Exception as exc:
        logger.warning("Redis unavailable, proceeding without cache: %s", exc)
        return None


def _build_cache_key(locations: List[Coordinate], departure_time: datetime) -> str:
    """Build a deterministic MD5 cache key from sorted coordinates + departure hour."""
    sorted_locs = sorted(locations)
    departure_hour = departure_time.strftime("%Y%m%d%H")
    payload = json.dumps({"locs": sorted_locs, "hour": departure_hour}, sort_keys=True)
    digest = hashlib.md5(payload.encode()).hexdigest()
    return f"dm:{digest}"


def build_distance_matrix(
    locations: List[Coordinate],
    departure_time: datetime,
) -> dict:
    """Return a traffic-aware distance matrix for the given locations.

    Checks Redis first; on cache miss calls the Google Distance Matrix API
    with departure_time so travel times reflect real traffic conditions.
    Redis errors are non-fatal — the service degrades gracefully to a direct
    API call.

    Args:
        locations: Ordered list of (lat, lng) pairs.
                   Index 0 = driver location, 1..n = stop locations.
        departure_time: Requested departure datetime (timezone-aware).

    Returns:
        {
            "time_matrix":     [[int, ...], ...]  # travel time in seconds
            "distance_matrix": [[int, ...], ...]  # distance in metres
        }
    """
    cache_key = _build_cache_key(locations, departure_time)

    # --- cache read ---
    r = _get_redis()
    if r is not None:
        try:
            cached = r.get(cache_key)
            if cached:
                logger.info("Distance matrix cache hit key=%s", cache_key)
                return json.loads(cached)
        except Exception as exc:
            logger.warning("Redis read error, falling through to API: %s", exc)

    # --- Google Distance Matrix API ---
    logger.info("Distance matrix cache miss, calling Google API (n=%d)", len(locations))
    client = googlemaps.Client(key=settings.GOOGLE_MAPS_API_KEY)
    coord_strings = [f"{lat},{lng}" for lat, lng in locations]

    response = client.distance_matrix(
        origins=coord_strings,
        destinations=coord_strings,
        mode="driving",
        departure_time=departure_time,
        traffic_model="best_guess",
        units="metric",
    )

    n = len(locations)
    time_matrix = [[0] * n for _ in range(n)]
    distance_matrix = [[0] * n for _ in range(n)]

    for i, row in enumerate(response["rows"]):
        for j, element in enumerate(row["elements"]):
            if element.get("status") != "OK":
                # Treat unreachable pairs as very high cost so the solver avoids them
                time_matrix[i][j] = 999_999
                distance_matrix[i][j] = 999_999
            else:
                # Prefer traffic-aware duration; fall back to plain duration.
                # Conditional required — dict.get() always evaluates its default.
                if "duration_in_traffic" in element:
                    duration = element["duration_in_traffic"]
                else:
                    duration = element["duration"]
                time_matrix[i][j] = duration["value"]
                distance_matrix[i][j] = element["distance"]["value"]

    result = {"time_matrix": time_matrix, "distance_matrix": distance_matrix}

    # --- cache write ---
    if r is not None:
        try:
            r.setex(cache_key, settings.REDIS_TTL_SECONDS, json.dumps(result))
            logger.info("Distance matrix cached key=%s ttl=%ds", cache_key, settings.REDIS_TTL_SECONDS)
        except Exception as exc:
            logger.warning("Redis write error, result not cached: %s", exc)

    return result
