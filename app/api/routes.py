import logging
from typing import List

import redis
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.config import settings
from app.models.schemas import OptimizeRouteRequest, OptimizeRouteResponse, Stop
from app.optimizer.distance_matrix import build_distance_matrix
from app.optimizer.route_builder import build_final_route
from app.optimizer.vrp_solver import solve_vrp

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


def _compute_naive_duration(
    time_matrix: List[List[int]],
    stops: List[Stop],
) -> float:
    """Compute total route duration (minutes) visiting stops in input order."""
    total = 0
    prev = 0
    for i, stop in enumerate(stops):
        node = i + 1
        total += time_matrix[prev][node] // 60
        total += stop.service_time_minutes
        prev = node
    return float(total)


@router.post("/optimize-route", response_model=OptimizeRouteResponse)
async def optimize_route(request: OptimizeRouteRequest) -> OptimizeRouteResponse:
    """Optimise a multi-stop pickup route using VRPTW and real-time traffic data.

    Calls Google Distance Matrix API (cached in Redis), runs OR-Tools VRPTW solver,
    then assembles per-stop ETAs and a summary response.
    Returns HTTP 503 if Google Maps is unavailable, 422 if no feasible route exists.
    """
    logger.info("optimize-route: driver_id=%s stops=%d", request.driver_id, len(request.stops))

    # 1. Build coordinate list: index 0 = driver, 1..n = stops (input order)
    locations = [(request.driver_location.lat, request.driver_location.lng)]
    locations += [(s.location.lat, s.location.lng) for s in request.stops]

    # 2. Distance matrix (Google Maps API, Redis-cached)
    try:
        matrices = build_distance_matrix(locations, request.departure_time)
    except Exception as exc:
        logger.error("Distance matrix failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Failed to fetch travel times from Google Maps API. Try again shortly.",
        )

    time_matrix = matrices["time_matrix"]
    distance_matrix = matrices["distance_matrix"]

    # 3. VRP solve
    service_times = [s.service_time_minutes for s in request.stops]
    departure_minutes = request.departure_time.hour * 60 + request.departure_time.minute

    try:
        stop_indices = solve_vrp(
            time_matrix,
            request.stops,
            service_times,
            departure_time_minutes=departure_minutes,
        )
    except ValueError as exc:
        logger.warning("VRP no feasible solution: %s", exc)
        raise HTTPException(status_code=422, detail=str(exc))

    # 4. Reorder stops and align matrices to optimised visit order
    #    node_order maps new sequential index → original matrix index
    n = len(request.stops)
    ordered_stops = [request.stops[i] for i in stop_indices]
    node_order = [0] + [i + 1 for i in stop_indices]

    reordered_time = [
        [time_matrix[node_order[r]][node_order[c]] for c in range(n + 1)]
        for r in range(n + 1)
    ]
    reordered_dist = [
        [distance_matrix[node_order[r]][node_order[c]] for c in range(n + 1)]
        for r in range(n + 1)
    ]

    # 5. Build final route with per-stop ETAs
    response = build_final_route(
        driver_id=request.driver_id,
        driver_location=request.driver_location,
        ordered_stops=ordered_stops,
        time_matrix=reordered_time,
        distance_matrix=reordered_dist,
        departure_time=request.departure_time,
    )

    # 6. Compute optimization_score = naive_duration / optimised_duration
    #    Values > 1.0 mean the optimizer improved over the input order.
    naive_duration = _compute_naive_duration(time_matrix, request.stops)
    if response.total_duration_minutes > 0:
        response.optimization_score = round(
            naive_duration / response.total_duration_minutes, 2
        )

    logger.info(
        "optimize-route done: %.1f km %.0f min score=%.2f",
        response.total_distance_km,
        response.total_duration_minutes,
        response.optimization_score,
    )
    return response


@router.get("/health")
async def health_check() -> JSONResponse:
    """Return service health: Redis connectivity and Maps API key presence."""
    # Redis connectivity
    redis_status = "unavailable"
    try:
        r = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            socket_connect_timeout=1,
        )
        r.ping()
        redis_status = "ok"
    except Exception:
        pass

    # Google Maps API key presence (do not make a live call on health check)
    maps_status = "configured" if settings.GOOGLE_MAPS_API_KEY else "missing"

    return JSONResponse(
        {"status": "healthy", "redis": redis_status, "maps_api": maps_status}
    )
