"""
tests/test_api.py — FastAPI endpoint tests using TestClient.

External dependencies (Google Maps, Redis, OR-Tools) are fully mocked so
these tests run fast and offline.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

VALID_REQUEST = {
    "driver_id": "driver-001",
    "driver_location": {"lat": 37.7749, "lng": -122.4194},
    "departure_time": "2030-06-15T09:00:00Z",
    "stops": [
        {
            "stop_id": "s1",
            "location": {"lat": 37.3382, "lng": -121.8863},
            "earliest_pickup": "09:30",
            "latest_pickup": "11:30",
            "service_time_minutes": 10,
        },
        {
            "stop_id": "s2",
            "location": {"lat": 37.6879, "lng": -122.4702},
            "earliest_pickup": "10:00",
            "latest_pickup": "12:00",
            "service_time_minutes": 5,
        },
    ],
}

# Synthetic 3×3 matrices returned by the mocked distance module
# (indices: 0=driver, 1=s1, 2=s2)
MOCK_TIME_MATRIX = [
    [0,    1800,  600],   # driver: 30 min to s1, 10 min to s2
    [1800,    0, 1200],   # s1:     20 min to s2
    [600,  1200,    0],   # s2
]
MOCK_DIST_MATRIX = [
    [0,    20000,  8000],
    [20000,    0, 12000],
    [8000, 12000,     0],
]
MOCK_MATRICES = {
    "time_matrix": MOCK_TIME_MATRIX,
    "distance_matrix": MOCK_DIST_MATRIX,
}


def _patch_optimizer(stop_indices=None):
    """Context manager that mocks build_distance_matrix and solve_vrp."""
    if stop_indices is None:
        stop_indices = [1, 0]   # solver reorders: s2 first, s1 second

    dm_patch = patch(
        "app.api.routes.build_distance_matrix",
        return_value=MOCK_MATRICES,
    )
    vrp_patch = patch(
        "app.api.routes.solve_vrp",
        return_value=stop_indices,
    )
    return dm_patch, vrp_patch


# ---------------------------------------------------------------------------
# POST /api/v1/optimize-route — happy path
# ---------------------------------------------------------------------------

def test_valid_request_returns_200():
    dm, vrp = _patch_optimizer()
    with dm, vrp:
        resp = client.post("/api/v1/optimize-route", json=VALID_REQUEST)
    assert resp.status_code == 200


def test_valid_request_response_shape():
    dm, vrp = _patch_optimizer()
    with dm, vrp:
        resp = client.post("/api/v1/optimize-route", json=VALID_REQUEST)
    data = resp.json()
    assert "driver_id" in data
    assert "optimized_stops" in data
    assert "total_distance_km" in data
    assert "total_duration_minutes" in data
    assert "google_maps_url" in data
    assert "optimization_score" in data


def test_valid_request_returns_correct_driver_id():
    dm, vrp = _patch_optimizer()
    with dm, vrp:
        resp = client.post("/api/v1/optimize-route", json=VALID_REQUEST)
    assert resp.json()["driver_id"] == "driver-001"


def test_valid_request_all_stops_returned():
    dm, vrp = _patch_optimizer()
    with dm, vrp:
        resp = client.post("/api/v1/optimize-route", json=VALID_REQUEST)
    assert len(resp.json()["optimized_stops"]) == 2


def test_valid_request_sequence_numbers():
    dm, vrp = _patch_optimizer()
    with dm, vrp:
        resp = client.post("/api/v1/optimize-route", json=VALID_REQUEST)
    sequences = [s["sequence"] for s in resp.json()["optimized_stops"]]
    assert sequences == [1, 2]


def test_valid_request_maps_url_coordinates_only():
    """HIPAA: stop IDs must not appear in the Maps URL."""
    dm, vrp = _patch_optimizer()
    with dm, vrp:
        resp = client.post("/api/v1/optimize-route", json=VALID_REQUEST)
    url = resp.json()["google_maps_url"]
    assert url.startswith("https://www.google.com/maps/dir/")
    assert "s1" not in url
    assert "s2" not in url


def test_valid_request_optimization_score_positive():
    dm, vrp = _patch_optimizer()
    with dm, vrp:
        resp = client.post("/api/v1/optimize-route", json=VALID_REQUEST)
    assert resp.json()["optimization_score"] > 0


# ---------------------------------------------------------------------------
# POST /api/v1/optimize-route — validation errors (422)
# ---------------------------------------------------------------------------

def test_invalid_driver_lat_returns_422():
    bad = {**VALID_REQUEST, "driver_location": {"lat": 999, "lng": 0}}
    resp = client.post("/api/v1/optimize-route", json=bad)
    assert resp.status_code == 422


def test_invalid_stop_lng_returns_422():
    bad_stops = [{**VALID_REQUEST["stops"][0], "location": {"lat": 0, "lng": 999}}]
    bad = {**VALID_REQUEST, "stops": bad_stops + [VALID_REQUEST["stops"][1]]}
    resp = client.post("/api/v1/optimize-route", json=bad)
    assert resp.status_code == 422


def test_too_many_stops_returns_422():
    stop = VALID_REQUEST["stops"][0]
    bad = {**VALID_REQUEST, "stops": [stop] * 26}
    resp = client.post("/api/v1/optimize-route", json=bad)
    assert resp.status_code == 422


def test_too_few_stops_returns_422():
    bad = {**VALID_REQUEST, "stops": [VALID_REQUEST["stops"][0]]}
    resp = client.post("/api/v1/optimize-route", json=bad)
    assert resp.status_code == 422


def test_past_departure_time_returns_422():
    bad = {**VALID_REQUEST, "departure_time": "2000-01-01T08:00:00Z"}
    resp = client.post("/api/v1/optimize-route", json=bad)
    assert resp.status_code == 422


def test_missing_driver_id_returns_422():
    bad = {k: v for k, v in VALID_REQUEST.items() if k != "driver_id"}
    resp = client.post("/api/v1/optimize-route", json=bad)
    assert resp.status_code == 422


def test_missing_stops_returns_422():
    bad = {k: v for k, v in VALID_REQUEST.items() if k != "stops"}
    resp = client.post("/api/v1/optimize-route", json=bad)
    assert resp.status_code == 422


def test_invalid_time_window_returns_422():
    """earliest >= latest should be rejected."""
    bad_stop = {**VALID_REQUEST["stops"][0], "earliest_pickup": "11:00", "latest_pickup": "09:00"}
    bad = {**VALID_REQUEST, "stops": [bad_stop, VALID_REQUEST["stops"][1]]}
    resp = client.post("/api/v1/optimize-route", json=bad)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/optimize-route — upstream errors
# ---------------------------------------------------------------------------

def test_google_api_failure_returns_503():
    with patch("app.api.routes.build_distance_matrix", side_effect=Exception("API down")):
        resp = client.post("/api/v1/optimize-route", json=VALID_REQUEST)
    assert resp.status_code == 503


def test_vrp_no_solution_returns_422():
    with patch("app.api.routes.build_distance_matrix", return_value=MOCK_MATRICES), \
         patch("app.api.routes.solve_vrp", side_effect=ValueError("No feasible route")):
        resp = client.post("/api/v1/optimize-route", json=VALID_REQUEST)
    assert resp.status_code == 422
    assert "No feasible route" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/v1/health
# ---------------------------------------------------------------------------

def test_health_returns_200():
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200


def test_health_response_shape():
    resp = client.get("/api/v1/health")
    data = resp.json()
    assert "status" in data
    assert "redis" in data
    assert "maps_api" in data


def test_health_status_is_healthy():
    resp = client.get("/api/v1/health")
    assert resp.json()["status"] == "healthy"


def test_health_maps_api_configured():
    """GOOGLE_MAPS_API_KEY is set to 'test-key-not-used-in-tests' in conftest."""
    resp = client.get("/api/v1/health")
    assert resp.json()["maps_api"] == "configured"


def test_health_redis_unavailable_does_not_crash():
    """Health check must succeed even when Redis is down."""
    with patch("app.api.routes.redis.Redis") as mock_redis_cls:
        mock_redis_cls.return_value.ping.side_effect = ConnectionError("down")
        resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["redis"] == "unavailable"


def test_health_redis_ok_when_reachable():
    with patch("app.api.routes.redis.Redis") as mock_redis_cls:
        mock_redis_cls.return_value.ping.return_value = True
        resp = client.get("/api/v1/health")
    assert resp.json()["redis"] == "ok"
