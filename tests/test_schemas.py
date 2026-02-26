from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.models.schemas import (
    Location,
    OptimizeRouteRequest,
    OptimizedStop,
    OptimizeRouteResponse,
    Stop,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def future_time(hours: int = 1) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def make_stop(
    stop_id: str = "stop-001",
    lat: float = 40.71,
    lng: float = -74.00,
    earliest: str = "08:00",
    latest: str = "09:00",
    service: int = 5,
) -> dict:
    return {
        "stop_id": stop_id,
        "location": {"lat": lat, "lng": lng},
        "earliest_pickup": earliest,
        "latest_pickup": latest,
        "service_time_minutes": service,
    }


def make_request(num_stops: int = 2, departure_hours: int = 1) -> dict:
    stops = [
        make_stop(stop_id=f"stop-{i:03}", lat=40.71 + i * 0.01)
        for i in range(num_stops)
    ]
    return {
        "driver_id": "driver-001",
        "driver_location": {"lat": 40.70, "lng": -74.01},
        "departure_time": (datetime.now(timezone.utc) + timedelta(hours=departure_hours)).isoformat(),
        "stops": stops,
    }


# ── Location ─────────────────────────────────────────────────────────────────

def test_valid_location():
    loc = Location(lat=40.71, lng=-74.00)
    assert loc.lat == 40.71
    assert loc.lng == -74.00


def test_invalid_lat_too_high():
    with pytest.raises(ValidationError, match="lat must be between"):
        Location(lat=91.0, lng=0.0)


def test_invalid_lat_too_low():
    with pytest.raises(ValidationError, match="lat must be between"):
        Location(lat=-91.0, lng=0.0)


def test_invalid_lng_too_high():
    with pytest.raises(ValidationError, match="lng must be between"):
        Location(lat=0.0, lng=181.0)


def test_invalid_lng_too_low():
    with pytest.raises(ValidationError, match="lng must be between"):
        Location(lat=0.0, lng=-181.0)


def test_boundary_coordinates_valid():
    loc = Location(lat=90.0, lng=180.0)
    assert loc.lat == 90.0
    assert loc.lng == 180.0


# ── Stop ─────────────────────────────────────────────────────────────────────

def test_valid_stop():
    stop = Stop(**make_stop())
    assert stop.stop_id == "stop-001"
    assert stop.service_time_minutes == 5


def test_invalid_time_format():
    with pytest.raises(ValidationError, match="HH:MM"):
        Stop(**make_stop(earliest="8:00"))


def test_invalid_time_format_letters():
    with pytest.raises(ValidationError, match="HH:MM"):
        Stop(**make_stop(latest="ab:cd"))


def test_invalid_time_window_earliest_equals_latest():
    with pytest.raises(ValidationError, match="earliest_pickup.*before"):
        Stop(**make_stop(earliest="09:00", latest="09:00"))


def test_invalid_time_window_earliest_after_latest():
    with pytest.raises(ValidationError, match="earliest_pickup.*before"):
        Stop(**make_stop(earliest="10:00", latest="09:00"))


def test_service_time_too_low():
    with pytest.raises(ValidationError, match="service_time_minutes must be between"):
        Stop(**make_stop(service=0))


def test_service_time_too_high():
    with pytest.raises(ValidationError, match="service_time_minutes must be between"):
        Stop(**make_stop(service=61))


def test_service_time_boundary_valid():
    s1 = Stop(**make_stop(service=1))
    s2 = Stop(**make_stop(service=60))
    assert s1.service_time_minutes == 1
    assert s2.service_time_minutes == 60


# ── OptimizeRouteRequest ──────────────────────────────────────────────────────

def test_valid_request():
    req = OptimizeRouteRequest(**make_request(num_stops=2))
    assert req.driver_id == "driver-001"
    assert len(req.stops) == 2


def test_too_few_stops():
    with pytest.raises(ValidationError, match="between 2 and 25"):
        OptimizeRouteRequest(**make_request(num_stops=1))


def test_too_many_stops():
    with pytest.raises(ValidationError, match="between 2 and 25"):
        OptimizeRouteRequest(**make_request(num_stops=26))


def test_max_stops_valid():
    req = OptimizeRouteRequest(**make_request(num_stops=25))
    assert len(req.stops) == 25


def test_past_departure_time():
    data = make_request()
    data["departure_time"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with pytest.raises(ValidationError, match="must not be in the past"):
        OptimizeRouteRequest(**data)


def test_future_departure_time_valid():
    req = OptimizeRouteRequest(**make_request(departure_hours=2))
    assert req.departure_time > datetime.now(timezone.utc)


def test_invalid_coordinates_in_request():
    data = make_request()
    data["driver_location"] = {"lat": 999.0, "lng": 0.0}
    with pytest.raises(ValidationError, match="lat must be between"):
        OptimizeRouteRequest(**data)


# ── OptimizedStop & OptimizeRouteResponse ─────────────────────────────────────

def test_optimized_stop_valid():
    stop = OptimizedStop(
        stop_id="stop-001",
        sequence=1,
        location={"lat": 40.71, "lng": -74.00},
        arrival_time="08:30",
        departure_time="08:35",
    )
    assert stop.sequence == 1
    assert stop.arrival_time == "08:30"


def test_optimize_route_response_valid():
    response = OptimizeRouteResponse(
        driver_id="driver-001",
        optimized_stops=[
            OptimizedStop(
                stop_id="stop-001",
                sequence=1,
                location={"lat": 40.71, "lng": -74.00},
                arrival_time="08:30",
                departure_time="08:35",
            )
        ],
        total_distance_km=12.5,
        total_duration_minutes=45.0,
        google_maps_url="https://www.google.com/maps/dir/40.70,-74.01/40.71,-74.00",
        optimization_score=0.92,
    )
    assert response.total_distance_km == 12.5
    assert len(response.optimized_stops) == 1
