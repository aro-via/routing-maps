from datetime import datetime, timezone

import pytest

from app.models.schemas import Location, Stop
from app.optimizer.route_builder import _build_maps_url, build_final_route

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

DRIVER_ID = "driver-001"
DRIVER_LOC = Location(lat=10.0, lng=20.0)

# Departure: 09:00 UTC on a future date
DEPARTURE = datetime(2030, 6, 15, 9, 0, tzinfo=timezone.utc)  # 540 min


def make_stop(stop_id: str, lat: float, lng: float, service_time: int = 10) -> Stop:
    return Stop(
        stop_id=stop_id,
        location=Location(lat=lat, lng=lng),
        earliest_pickup="00:00",
        latest_pickup="23:59",
        service_time_minutes=service_time,
    )


STOP_A = make_stop("stop-A", lat=11.0, lng=21.0, service_time=10)
STOP_B = make_stop("stop-B", lat=12.0, lng=22.0, service_time=5)

# Ordered stops: driver → stop_A → stop_B
ORDERED_STOPS = [STOP_A, STOP_B]

# time_matrix (seconds): [driver, stop_A, stop_B]
# driver→stop_A = 1800 s (30 min)
# stop_A→stop_B = 1200 s (20 min)
TIME_MATRIX = [
    [0,    1800, 5400],  # driver
    [1800,    0, 1200],  # stop_A
    [5400, 1200,    0],  # stop_B
]

# distance_matrix (metres)
DISTANCE_MATRIX = [
    [0,     15000, 45000],
    [15000,     0, 10000],
    [45000, 10000,     0],
]


# ---------------------------------------------------------------------------
# Arrival & departure time calculations
# ---------------------------------------------------------------------------

def test_arrival_times_calculated_correctly():
    """stop_A arrives at 09:30, stop_B arrives at 10:00."""
    result = build_final_route(
        DRIVER_ID, DRIVER_LOC, ORDERED_STOPS,
        TIME_MATRIX, DISTANCE_MATRIX, DEPARTURE,
    )
    stops = result.optimized_stops
    # driver departs 09:00, travels 30 min → arrives stop_A 09:30
    assert stops[0].arrival_time == "09:30"
    # departs stop_A 09:40 (30 min travel + 10 min service),
    # travels 20 min → arrives stop_B 10:00
    assert stops[1].arrival_time == "10:00"


def test_departure_times_include_service_time():
    """departure = arrival + service_time_minutes."""
    result = build_final_route(
        DRIVER_ID, DRIVER_LOC, ORDERED_STOPS,
        TIME_MATRIX, DISTANCE_MATRIX, DEPARTURE,
    )
    stops = result.optimized_stops
    # stop_A: arrive 09:30, service 10 min → depart 09:40
    assert stops[0].departure_time == "09:40"
    # stop_B: arrive 10:00, service 5 min → depart 10:05
    assert stops[1].departure_time == "10:05"


def test_sequence_numbers_start_at_one():
    result = build_final_route(
        DRIVER_ID, DRIVER_LOC, ORDERED_STOPS,
        TIME_MATRIX, DISTANCE_MATRIX, DEPARTURE,
    )
    sequences = [s.sequence for s in result.optimized_stops]
    assert sequences == [1, 2]


def test_sequence_numbers_are_contiguous():
    result = build_final_route(
        DRIVER_ID, DRIVER_LOC, ORDERED_STOPS,
        TIME_MATRIX, DISTANCE_MATRIX, DEPARTURE,
    )
    sequences = [s.sequence for s in result.optimized_stops]
    assert sequences == list(range(1, len(ORDERED_STOPS) + 1))


# ---------------------------------------------------------------------------
# Distance and duration totals
# ---------------------------------------------------------------------------

def test_total_distance_km():
    """driver→stop_A (15 km) + stop_A→stop_B (10 km) = 25 km."""
    result = build_final_route(
        DRIVER_ID, DRIVER_LOC, ORDERED_STOPS,
        TIME_MATRIX, DISTANCE_MATRIX, DEPARTURE,
    )
    assert result.total_distance_km == 25.0


def test_total_duration_minutes():
    """30 min travel + 10 min service + 20 min travel + 5 min service = 65 min."""
    result = build_final_route(
        DRIVER_ID, DRIVER_LOC, ORDERED_STOPS,
        TIME_MATRIX, DISTANCE_MATRIX, DEPARTURE,
    )
    assert result.total_duration_minutes == 65.0


# ---------------------------------------------------------------------------
# Google Maps URL
# ---------------------------------------------------------------------------

def test_maps_url_format():
    result = build_final_route(
        DRIVER_ID, DRIVER_LOC, ORDERED_STOPS,
        TIME_MATRIX, DISTANCE_MATRIX, DEPARTURE,
    )
    assert result.google_maps_url.startswith("https://www.google.com/maps/dir/")


def test_maps_url_contains_driver_coordinates():
    result = build_final_route(
        DRIVER_ID, DRIVER_LOC, ORDERED_STOPS,
        TIME_MATRIX, DISTANCE_MATRIX, DEPARTURE,
    )
    assert "10.0,20.0" in result.google_maps_url


def test_maps_url_contains_stop_coordinates():
    result = build_final_route(
        DRIVER_ID, DRIVER_LOC, ORDERED_STOPS,
        TIME_MATRIX, DISTANCE_MATRIX, DEPARTURE,
    )
    assert "11.0,21.0" in result.google_maps_url
    assert "12.0,22.0" in result.google_maps_url


def test_maps_url_contains_only_coordinates_no_ids():
    """HIPAA: stop_id must never appear in the Maps URL."""
    result = build_final_route(
        DRIVER_ID, DRIVER_LOC, ORDERED_STOPS,
        TIME_MATRIX, DISTANCE_MATRIX, DEPARTURE,
    )
    assert "stop-A" not in result.google_maps_url
    assert "stop-B" not in result.google_maps_url


def test_maps_url_stops_in_order():
    """Coordinates in URL must follow the optimised visit order."""
    result = build_final_route(
        DRIVER_ID, DRIVER_LOC, ORDERED_STOPS,
        TIME_MATRIX, DISTANCE_MATRIX, DEPARTURE,
    )
    url = result.google_maps_url
    pos_driver = url.index("10.0,20.0")
    pos_a = url.index("11.0,21.0")
    pos_b = url.index("12.0,22.0")
    assert pos_driver < pos_a < pos_b


# ---------------------------------------------------------------------------
# _build_maps_url unit tests
# ---------------------------------------------------------------------------

def test_build_maps_url_structure():
    url = _build_maps_url(DRIVER_LOC, ORDERED_STOPS)
    assert url == "https://www.google.com/maps/dir/10.0,20.0/11.0,21.0/12.0,22.0"


def test_build_maps_url_no_stop_ids():
    url = _build_maps_url(DRIVER_LOC, ORDERED_STOPS)
    assert "stop-A" not in url
    assert "stop-B" not in url


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------

def test_response_contains_driver_id():
    result = build_final_route(
        DRIVER_ID, DRIVER_LOC, ORDERED_STOPS,
        TIME_MATRIX, DISTANCE_MATRIX, DEPARTURE,
    )
    assert result.driver_id == DRIVER_ID


def test_response_stop_ids_preserved():
    result = build_final_route(
        DRIVER_ID, DRIVER_LOC, ORDERED_STOPS,
        TIME_MATRIX, DISTANCE_MATRIX, DEPARTURE,
    )
    ids = [s.stop_id for s in result.optimized_stops]
    assert ids == ["stop-A", "stop-B"]
