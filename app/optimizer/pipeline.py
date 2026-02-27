"""app/optimizer/pipeline.py — Shared optimization entry point.

Both the HTTP handler (routes.py) and the Celery re-routing worker call
run_optimization() identically.  All HTTP concerns (status codes, exception
translation) stay in the API layer; this module is pure business logic.
"""
import logging
from datetime import datetime
from typing import List

from app.models.schemas import Location, OptimizeRouteResponse, Stop
from app.optimizer.distance_matrix import build_distance_matrix
from app.optimizer.route_builder import build_final_route
from app.optimizer.vrp_solver import solve_vrp

logger = logging.getLogger(__name__)


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


async def run_optimization(
    driver_id: str,
    driver_location: Location,
    stops: List[Stop],
    departure_time: datetime,
) -> OptimizeRouteResponse:
    """Run the full route optimisation pipeline and return the response.

    Steps:
        1. Build (lat, lng) location list: index 0 = driver, 1..n = stops.
        2. Fetch traffic-aware distance/time matrices (Redis-cached).
        3. Solve VRPTW with OR-Tools to get optimal stop order.
        4. Re-index matrices to match optimised stop order.
        5. Build per-stop ETAs and totals.
        6. Compute optimization_score (naive duration / optimised duration).

    Args:
        driver_id:        Driver identifier included in the response payload.
        driver_location:  Driver's starting (lat, lng).
        stops:            Pickup stops in caller-provided input order.
        departure_time:   Scheduled departure (timezone-aware datetime).

    Returns:
        Fully populated OptimizeRouteResponse with optimization_score set.

    Raises:
        Exception:    If the distance matrix call fails (caller maps to HTTP 503).
        ValueError:   If OR-Tools finds no feasible route (caller maps to HTTP 422).
    """
    # 1. Build coordinate list: index 0 = driver, 1..n = stops (input order)
    locations = [(driver_location.lat, driver_location.lng)]
    locations += [(s.location.lat, s.location.lng) for s in stops]

    # 2. Distance matrix (Google Maps API, Redis-cached)
    matrices = build_distance_matrix(locations, departure_time)
    time_matrix = matrices["time_matrix"]
    distance_matrix = matrices["distance_matrix"]

    # 3. VRP solve
    service_times = [s.service_time_minutes for s in stops]
    departure_minutes = departure_time.hour * 60 + departure_time.minute

    stop_indices = solve_vrp(
        time_matrix,
        stops,
        service_times,
        departure_time_minutes=departure_minutes,
    )

    # 4. Reorder stops and align matrices to optimised visit order
    #    node_order maps new sequential index → original matrix index
    n = len(stops)
    ordered_stops = [stops[i] for i in stop_indices]
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
        driver_id=driver_id,
        driver_location=driver_location,
        ordered_stops=ordered_stops,
        time_matrix=reordered_time,
        distance_matrix=reordered_dist,
        departure_time=departure_time,
    )

    # 6. Compute optimization_score = naive_duration / optimised_duration
    #    Values > 1.0 mean the optimizer improved over the input order.
    naive_duration = _compute_naive_duration(time_matrix, stops)
    if response.total_duration_minutes > 0:
        response.optimization_score = round(
            naive_duration / response.total_duration_minutes, 2
        )

    logger.info(
        "run_optimization done: driver=%s stops=%d %.1f km %.0f min score=%.2f",
        driver_id,
        len(stops),
        response.total_distance_km,
        response.total_duration_minutes,
        response.optimization_score,
    )
    return response
