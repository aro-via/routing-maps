"""
tests/test_e2e.py — End-to-end integration tests for the optimizer pipeline.

Tests call the three optimizer components in sequence with a realistic
5-stop scenario.  The only mock is build_distance_matrix (no real Google API
key is needed); the VRP solver and route builder run for real.

Scenario
--------
Stops are placed along a 1-D corridor.  Distances are proportional to the
difference in position, so the optimal route visits them in ascending position
order — which is *different* from the input order:

  Position (min from driver):  driver=0, s0=100, s1=30, s2=5, s3=110, s4=10

  Input order  : s0→s1→s2→s3→s4  (total travel ≈ 400 min → 450 min with service)
  Optimal order: s2→s4→s1→s0→s3  (total travel ≈ 110 min → 160 min with service)
"""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.models.schemas import Location, Stop
from app.optimizer.route_builder import build_final_route
from app.optimizer.vrp_solver import solve_vrp
from app.utils.time_utils import time_str_to_minutes

# ---------------------------------------------------------------------------
# 5-stop scenario constants
# ---------------------------------------------------------------------------

DEPARTURE = datetime(2030, 6, 15, 9, 0, tzinfo=timezone.utc)  # 09:00 → 540 min
DEPARTURE_MINUTES = 540
DRIVER_LOCATION = Location(lat=37.7749, lng=-122.4194)

STOPS = [
    Stop(stop_id="s0", location=Location(lat=37.3000, lng=-121.8000),
         earliest_pickup="09:00", latest_pickup="22:00", service_time_minutes=10),
    Stop(stop_id="s1", location=Location(lat=37.5500, lng=-122.1000),
         earliest_pickup="09:00", latest_pickup="22:00", service_time_minutes=10),
    Stop(stop_id="s2", location=Location(lat=37.7600, lng=-122.4000),
         earliest_pickup="09:00", latest_pickup="22:00", service_time_minutes=10),
    Stop(stop_id="s3", location=Location(lat=37.2500, lng=-121.7000),
         earliest_pickup="09:00", latest_pickup="22:00", service_time_minutes=10),
    Stop(stop_id="s4", location=Location(lat=37.7400, lng=-122.3800),
         earliest_pickup="09:00", latest_pickup="22:00", service_time_minutes=10),
]

# Positions along a 1-D corridor (minutes from driver):
#   driver=0, s0=100, s1=30, s2=5, s3=110, s4=10
_POS = [0, 100, 30, 5, 110, 10]

# 6×6 time matrix (seconds): index 0=driver, 1=s0, 2=s1, 3=s2, 4=s3, 5=s4
TIME_MATRIX = [
    [abs(_POS[i] - _POS[j]) * 60 for j in range(6)]
    for i in range(6)
]

# 6×6 distance matrix (metres): same proportions for convenience
DISTANCE_MATRIX = [
    [abs(_POS[i] - _POS[j]) * 1000 for j in range(6)]
    for i in range(6)
]

MOCK_MATRICES = {
    "time_matrix": TIME_MATRIX,
    "distance_matrix": DISTANCE_MATRIX,
}


def _naive_duration(time_matrix, stops):
    """Total route time (min) visiting stops in input order."""
    total, prev = 0, 0
    for i, stop in enumerate(stops):
        node = i + 1
        total += time_matrix[prev][node] // 60
        total += stop.service_time_minutes
        prev = node
    return total


# ---------------------------------------------------------------------------
# Helpers to run the full pipeline with a mocked distance matrix
# ---------------------------------------------------------------------------

def _run_pipeline():
    """Run distance_matrix → vrp_solver → route_builder, return the response."""
    service_times = [s.service_time_minutes for s in STOPS]

    stop_indices = solve_vrp(
        TIME_MATRIX,
        STOPS,
        service_times,
        departure_time_minutes=DEPARTURE_MINUTES,
    )

    n = len(STOPS)
    ordered_stops = [STOPS[i] for i in stop_indices]
    node_order = [0] + [i + 1 for i in stop_indices]

    reordered_time = [
        [TIME_MATRIX[node_order[r]][node_order[c]] for c in range(n + 1)]
        for r in range(n + 1)
    ]
    reordered_dist = [
        [DISTANCE_MATRIX[node_order[r]][node_order[c]] for c in range(n + 1)]
        for r in range(n + 1)
    ]

    response = build_final_route(
        driver_id="driver-e2e",
        driver_location=DRIVER_LOCATION,
        ordered_stops=ordered_stops,
        time_matrix=reordered_time,
        distance_matrix=reordered_dist,
        departure_time=DEPARTURE,
    )
    return response, stop_indices


# Run once and cache — VRP solve takes ~10 s (OR-Tools time limit)
_RESPONSE = None
_STOP_INDICES = None


def _get_result():
    global _RESPONSE, _STOP_INDICES
    if _RESPONSE is None:
        _RESPONSE, _STOP_INDICES = _run_pipeline()
    return _RESPONSE, _STOP_INDICES


# ---------------------------------------------------------------------------
# E2E assertions
# ---------------------------------------------------------------------------

def test_e2e_optimised_route_differs_from_input_order():
    """Solver must reorder the stops, not return the input sequence."""
    _, stop_indices = _get_result()
    assert stop_indices != [0, 1, 2, 3, 4], (
        "Solver returned input order — optimisation did not fire"
    )


def test_e2e_all_stops_visited():
    """Every stop must appear exactly once in the optimised route."""
    response, _ = _get_result()
    returned_ids = {s.stop_id for s in response.optimized_stops}
    expected_ids = {s.stop_id for s in STOPS}
    assert returned_ids == expected_ids


def test_e2e_sequence_numbers_correct():
    response, _ = _get_result()
    sequences = [s.sequence for s in response.optimized_stops]
    assert sequences == list(range(1, len(STOPS) + 1))


def test_e2e_optimised_duration_less_than_naive():
    """Core correctness: solver must beat the naive (input) order."""
    response, _ = _get_result()
    naive = _naive_duration(TIME_MATRIX, STOPS)
    assert response.total_duration_minutes < naive, (
        f"Optimised {response.total_duration_minutes} min ≥ naive {naive} min"
    )


def test_e2e_time_windows_respected():
    """Every stop must be visited within its earliest/latest_pickup window."""
    response, _ = _get_result()
    for opt_stop in response.optimized_stops:
        # Find the original stop to get its time windows
        original = next(s for s in STOPS if s.stop_id == opt_stop.stop_id)
        earliest_min = time_str_to_minutes(original.earliest_pickup)
        latest_min = time_str_to_minutes(original.latest_pickup)

        arrival_min = time_str_to_minutes(opt_stop.arrival_time)
        assert arrival_min >= earliest_min, (
            f"{opt_stop.stop_id}: arrived {opt_stop.arrival_time} "
            f"before window opens {original.earliest_pickup}"
        )
        assert arrival_min <= latest_min, (
            f"{opt_stop.stop_id}: arrived {opt_stop.arrival_time} "
            f"after window closes {original.latest_pickup}"
        )


def test_e2e_maps_url_valid_format():
    response, _ = _get_result()
    assert response.google_maps_url.startswith("https://www.google.com/maps/dir/")


def test_e2e_maps_url_no_stop_ids():
    """HIPAA: no stop identifier may appear in the Maps URL."""
    response, _ = _get_result()
    url = response.google_maps_url
    for stop in STOPS:
        assert stop.stop_id not in url, (
            f"PHI violation: stop_id '{stop.stop_id}' found in Maps URL"
        )


def test_e2e_maps_url_contains_driver_coordinates():
    response, _ = _get_result()
    assert f"{DRIVER_LOCATION.lat},{DRIVER_LOCATION.lng}" in response.google_maps_url


def test_e2e_total_distance_positive():
    response, _ = _get_result()
    assert response.total_distance_km > 0


def test_e2e_total_duration_positive():
    response, _ = _get_result()
    assert response.total_duration_minutes > 0


def test_e2e_departure_times_after_arrivals():
    """Departure from each stop must be strictly after arrival."""
    response, _ = _get_result()
    for opt_stop in response.optimized_stops:
        arrival = time_str_to_minutes(opt_stop.arrival_time)
        departure = time_str_to_minutes(opt_stop.departure_time)
        assert departure > arrival, (
            f"{opt_stop.stop_id}: departure {opt_stop.departure_time} "
            f"not after arrival {opt_stop.arrival_time}"
        )
