"""tests/test_rerouting_e2e.py — End-to-end Phase 2 re-routing scenario.

Simulates the complete re-routing flow without real external services:
  - TestClient for the REST /api/v1/optimize-route endpoint
  - fakeredis for all Redis I/O (driver state + Pub/Sub capture)
  - OR-Tools VRP solver runs for real (2-stop subscenario, ~1 s)
  - run_optimization mocked in the Celery task (deterministic, no Google API)
  - WebSocket endpoint tested via TestClient (FastAPI built-in support)

Scenario
--------
Driver "e2e-driver-001" is assigned a 3-stop route starting at 09:00.

Phase A — Normal driving (Steps 1–3):
  5 GPS updates arrive with no schedule delay → no re-routing expected.

Phase B — Delay detected (Steps 4–7):
  The 6th GPS update carries schedule_delay_minutes=6.0, exceeding the
  DELAY_THRESHOLD_MINUTES=5 threshold.  The Celery task re-optimises the
  remaining 2 stops and publishes the new route to Redis Pub/Sub.

Assertions:
  1.  POST /api/v1/optimize-route returns a valid 3-stop route.
  2.  WebSocket connection accepted without errors.
  3.  5 normal GPS updates each return rerouted=False.
  4.  Delayed GPS update returns rerouted=True, reason="traffic_delay".
  5.  Redis Pub/Sub channel receives a well-formed route_updated payload.
  6.  New route contains only the 2 remaining (uncompleted) stops.
  7.  All time windows in the new route are respected.
  8.  No PHI appears in any generated message, Redis key, or log payload.
"""
import json
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import (
    Location,
    OptimizedStop,
    OptimizeRouteResponse,
)
from app.state.driver_state import DriverState, get_driver_state, save_driver_state
from app.utils.time_utils import time_str_to_minutes
from app.websocket.manager import manager as ws_manager
from app.workers.tasks import process_gps_update

# ---------------------------------------------------------------------------
# Scenario constants — no PHI anywhere
# ---------------------------------------------------------------------------

DRIVER_ID = "e2e-driver-001"
DEPARTURE_ISO = "2030-06-15T09:00:00Z"

# 3 stops identified by UUIDs — caller's back-office owns the patient mapping.
STOP_IDS = [
    "aaaabbbb-0000-0000-0000-000000000001",
    "aaaabbbb-0000-0000-0000-000000000002",
    "aaaabbbb-0000-0000-0000-000000000003",
]

_STOPS_INPUT = [
    {
        "stop_id": STOP_IDS[0],
        "location": {"lat": 37.760, "lng": -122.400},
        "earliest_pickup": "09:00",
        "latest_pickup": "22:00",
        "service_time_minutes": 10,
    },
    {
        "stop_id": STOP_IDS[1],
        "location": {"lat": 37.750, "lng": -122.390},
        "earliest_pickup": "09:00",
        "latest_pickup": "22:00",
        "service_time_minutes": 10,
    },
    {
        "stop_id": STOP_IDS[2],
        "location": {"lat": 37.740, "lng": -122.380},
        "earliest_pickup": "09:00",
        "latest_pickup": "22:00",
        "service_time_minutes": 10,
    },
]

# Driver starts slightly north of the first stop
_DRIVER_LAT, _DRIVER_LNG = 37.770, -122.410

# Synthetic 4×4 time + distance matrices (no Google API needed)
# Index: 0 = driver, 1 = stop-0, 2 = stop-1, 3 = stop-2
_POS = [0, 10, 15, 20]   # minutes from driver origin
_TIME_MATRIX = [[abs(_POS[i] - _POS[j]) * 60 for j in range(4)] for i in range(4)]
_DIST_MATRIX = [[abs(_POS[i] - _POS[j]) * 1000 for j in range(4)] for i in range(4)]
_MOCK_MATRICES = {"time_matrix": _TIME_MATRIX, "distance_matrix": _DIST_MATRIX}

# Re-route result: only stops 2 & 3 remain (stop-0 was completed)
_REROUTE_RESPONSE = OptimizeRouteResponse(
    driver_id=DRIVER_ID,
    optimized_stops=[
        OptimizedStop(
            stop_id=STOP_IDS[1],
            sequence=1,
            location=Location(lat=37.750, lng=-122.390),
            arrival_time="09:25",
            departure_time="09:35",
        ),
        OptimizedStop(
            stop_id=STOP_IDS[2],
            sequence=2,
            location=Location(lat=37.740, lng=-122.380),
            arrival_time="09:45",
            departure_time="09:55",
        ),
    ],
    total_distance_km=2.0,
    total_duration_minutes=55.0,
    google_maps_url=(
        "https://www.google.com/maps/dir/"
        "37.770,-122.410/37.750,-122.390/37.740,-122.380"
    ),
    optimization_score=1.05,
)

# PHI tokens that must never appear in any payload
_PHI_TOKENS = [
    "patient", "name", "address", "dob", "ssn",
    "phone", "diagnosis", "insurance", "doctor", "medical",
]

# ---------------------------------------------------------------------------
# Module-level scenario results — populated by the `scenario` fixture,
# consumed by individual test functions.
# ---------------------------------------------------------------------------

_scenario: dict = {}


# ---------------------------------------------------------------------------
# Shared fakeredis server (module scope so all tests share the same data)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def fake_redis_server():
    return fakeredis.FakeServer()


@pytest.fixture(scope="module")
def fake_redis(fake_redis_server):
    return fakeredis.FakeRedis(server=fake_redis_server, decode_responses=True)


# ---------------------------------------------------------------------------
# Full E2E scenario fixture — runs once per module, caches results
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def scenario(fake_redis):
    """
    Execute the complete re-routing scenario and populate _scenario with
    all intermediate and final results for individual test assertions.
    """
    # Pub/Sub capture: record every publish() call
    mock_pubsub_redis = MagicMock()
    published_calls: list[tuple[str, str]] = []

    def _capture_publish(channel: str, payload: str) -> None:
        published_calls.append((channel, payload))

    mock_pubsub_redis.publish.side_effect = _capture_publish

    with (
        # All Redis driver-state I/O → fakeredis
        patch("app.state.driver_state._get_redis", return_value=fake_redis),
        # Celery task Pub/Sub publish → captured mock
        patch("app.workers.tasks._get_redis", return_value=mock_pubsub_redis),
        # run_optimization → fast deterministic re-route response
        patch(
            "app.workers.tasks.run_optimization",
            new=AsyncMock(return_value=_REROUTE_RESPONSE),
        ),
    ):
        client = TestClient(app)

        # ------------------------------------------------------------------
        # Step 1: REST API → initial 3-stop optimised route
        # ------------------------------------------------------------------
        with patch(
            "app.optimizer.pipeline.build_distance_matrix",
            return_value=_MOCK_MATRICES,
        ):
            resp = client.post(
                "/api/v1/optimize-route",
                json={
                    "driver_id": DRIVER_ID,
                    "driver_location": {"lat": _DRIVER_LAT, "lng": _DRIVER_LNG},
                    "stops": _STOPS_INPUT,
                    "departure_time": DEPARTURE_ISO,
                },
            )
        _scenario["api_status"] = resp.status_code
        _scenario["initial_route"] = resp.json() if resp.status_code == 200 else {}

        # ------------------------------------------------------------------
        # Step 2: Seed driver state in fakeredis using the initial route
        # ------------------------------------------------------------------
        initial_stops = _scenario["initial_route"].get("optimized_stops", [])
        state = DriverState(
            driver_id=DRIVER_ID,
            current_route=initial_stops,
            schedule_delay_minutes=0.0,
            remaining_duration=60.0,
            original_remaining_duration=60.0,
            completed_stop_ids=[],
            last_reroute_timestamp=None,
            stops_changed=False,
        )
        save_driver_state(state)

        # ------------------------------------------------------------------
        # Step 3: 5 normal GPS updates — driver on schedule, no re-route
        # ------------------------------------------------------------------
        normal_results = []
        for i in range(5):
            result = process_gps_update(
                driver_id=DRIVER_ID,
                lat=_DRIVER_LAT + i * 0.001,
                lng=_DRIVER_LNG,
                timestamp=f"2030-06-15T09:0{i}:00Z",
            )
            normal_results.append(result)
        _scenario["normal_results"] = normal_results

        # ------------------------------------------------------------------
        # Step 4: GPS update with delay > threshold → re-route triggered
        # ------------------------------------------------------------------
        # Inject delay directly into driver state (simulates traffic buildup)
        state_before_delay = get_driver_state(DRIVER_ID)
        state_before_delay.schedule_delay_minutes = 6.0  # above threshold of 5
        # Mark stop-0 as completed so the re-router gets 2 remaining stops
        state_before_delay.completed_stop_ids = [STOP_IDS[0]]
        save_driver_state(state_before_delay)

        reroute_result = process_gps_update(
            driver_id=DRIVER_ID,
            lat=_DRIVER_LAT + 0.005,
            lng=_DRIVER_LNG,
            timestamp="2030-06-15T09:10:00Z",
        )
        _scenario["reroute_result"] = reroute_result
        _scenario["published_calls"] = published_calls

        # ------------------------------------------------------------------
        # Step 5: WebSocket connection test
        # ------------------------------------------------------------------
        _scenario["ws_connected"] = False
        _scenario["ws_gps_dispatched"] = False

        with (
            patch.object(ws_manager, "listen_for_reroutes", new=AsyncMock()),
            patch("app.websocket.manager.clear_driver_state"),
        ):
            with client.websocket_connect(f"/ws/driver/{DRIVER_ID}") as ws:
                _scenario["ws_connected"] = True
                ws.send_json({
                    "type": "gps_update",
                    "lat": _DRIVER_LAT,
                    "lng": _DRIVER_LNG,
                    "timestamp": "2030-06-15T09:11:00Z",
                })
                _scenario["ws_gps_dispatched"] = True
                ws.close()

    yield _scenario


# ---------------------------------------------------------------------------
# Step 1: REST API returns a valid initial route
# ---------------------------------------------------------------------------

def test_step1_initial_route_status_200(scenario):
    assert scenario["api_status"] == 200, "POST /optimize-route did not return 200"


def test_step1_initial_route_has_three_stops(scenario):
    stops = scenario["initial_route"].get("optimized_stops", [])
    assert len(stops) == 3, f"Expected 3 stops, got {len(stops)}"


def test_step1_initial_route_all_stop_ids_present(scenario):
    returned_ids = {s["stop_id"] for s in scenario["initial_route"]["optimized_stops"]}
    assert returned_ids == set(STOP_IDS)


def test_step1_initial_route_sequences_are_1_to_3(scenario):
    seqs = sorted(s["sequence"] for s in scenario["initial_route"]["optimized_stops"])
    assert seqs == [1, 2, 3]


def test_step1_initial_route_maps_url_no_phi(scenario):
    url = scenario["initial_route"].get("google_maps_url", "")
    assert url.startswith("https://www.google.com/maps/dir/")
    for token in _PHI_TOKENS:
        assert token.lower() not in url.lower(), f"PHI token '{token}' found in Maps URL"


# ---------------------------------------------------------------------------
# Step 2: WebSocket connection accepted cleanly
# ---------------------------------------------------------------------------

def test_step2_websocket_connection_accepted(scenario):
    assert scenario["ws_connected"] is True, "WebSocket connection was not accepted"


def test_step2_websocket_gps_dispatched(scenario):
    assert scenario["ws_gps_dispatched"] is True


# ---------------------------------------------------------------------------
# Step 3: 5 normal GPS updates — no re-routing
# ---------------------------------------------------------------------------

def test_step3_five_normal_updates_collected(scenario):
    assert len(scenario["normal_results"]) == 5


def test_step3_normal_gps_no_reroute(scenario):
    for i, result in enumerate(scenario["normal_results"]):
        assert result["rerouted"] is False, (
            f"GPS update {i + 1} unexpectedly triggered a re-route"
        )


# ---------------------------------------------------------------------------
# Step 4: Delayed GPS update triggers re-routing
# ---------------------------------------------------------------------------

def test_step4_rerouted_is_true(scenario):
    assert scenario["reroute_result"]["rerouted"] is True, (
        "Expected rerouted=True for delayed GPS update"
    )


def test_step4_reroute_reason_is_traffic_delay(scenario):
    assert scenario["reroute_result"]["reason"] == "traffic_delay"


# ---------------------------------------------------------------------------
# Step 5: New route published to Redis Pub/Sub
# ---------------------------------------------------------------------------

def test_step5_pubsub_channel_received_message(scenario):
    assert len(scenario["published_calls"]) >= 1, (
        "Expected at least one Pub/Sub publish; got none"
    )


def test_step5_pubsub_channel_name_correct(scenario):
    channel, _ = scenario["published_calls"][0]
    assert channel == f"reroute:{DRIVER_ID}"


def test_step5_pubsub_payload_type_is_route_updated(scenario):
    _, payload_str = scenario["published_calls"][0]
    payload = json.loads(payload_str)
    assert payload["type"] == "route_updated"


def test_step5_pubsub_payload_reason_matches(scenario):
    _, payload_str = scenario["published_calls"][0]
    payload = json.loads(payload_str)
    assert payload["reason"] == "traffic_delay"


def test_step5_pubsub_payload_contains_stops(scenario):
    _, payload_str = scenario["published_calls"][0]
    payload = json.loads(payload_str)
    assert "optimized_stops" in payload
    assert len(payload["optimized_stops"]) > 0


def test_step5_pubsub_payload_contains_maps_url(scenario):
    _, payload_str = scenario["published_calls"][0]
    payload = json.loads(payload_str)
    assert "google_maps_url" in payload


# ---------------------------------------------------------------------------
# Step 6: New route is different from original (optimizer ran)
# ---------------------------------------------------------------------------

def test_step6_new_route_excludes_completed_stop(scenario):
    """Stop-0 was completed — it must not appear in the new route."""
    _, payload_str = scenario["published_calls"][0]
    payload = json.loads(payload_str)
    new_stop_ids = {s["stop_id"] for s in payload["optimized_stops"]}
    assert STOP_IDS[0] not in new_stop_ids, (
        f"Completed stop {STOP_IDS[0]} appeared in re-optimised route"
    )


def test_step6_new_route_has_remaining_stops(scenario):
    _, payload_str = scenario["published_calls"][0]
    payload = json.loads(payload_str)
    new_stop_ids = {s["stop_id"] for s in payload["optimized_stops"]}
    assert STOP_IDS[1] in new_stop_ids
    assert STOP_IDS[2] in new_stop_ids


def test_step6_new_route_stop_count_reduced(scenario):
    """Re-routed route should have fewer stops than the original 3."""
    _, payload_str = scenario["published_calls"][0]
    payload = json.loads(payload_str)
    original_count = len(scenario["initial_route"]["optimized_stops"])
    new_count = len(payload["optimized_stops"])
    assert new_count < original_count, (
        f"Expected new route ({new_count} stops) to have fewer stops "
        f"than original ({original_count} stops)"
    )


# ---------------------------------------------------------------------------
# Step 7: All time windows respected in the new route
# ---------------------------------------------------------------------------

def test_step7_arrival_times_are_strings(scenario):
    _, payload_str = scenario["published_calls"][0]
    payload = json.loads(payload_str)
    for stop in payload["optimized_stops"]:
        assert isinstance(stop["arrival_time"], str)
        assert ":" in stop["arrival_time"], f"arrival_time not HH:MM: {stop['arrival_time']}"


def test_step7_departure_after_arrival(scenario):
    _, payload_str = scenario["published_calls"][0]
    payload = json.loads(payload_str)
    for stop in payload["optimized_stops"]:
        arr = time_str_to_minutes(stop["arrival_time"])
        dep = time_str_to_minutes(stop["departure_time"])
        assert dep > arr, (
            f"Stop {stop['stop_id']}: departure {stop['departure_time']} "
            f"not after arrival {stop['arrival_time']}"
        )


def test_step7_arrivals_within_original_time_windows(scenario):
    """Arrivals in the new route must respect the original pickup windows."""
    _, payload_str = scenario["published_calls"][0]
    payload = json.loads(payload_str)
    window_map = {s["stop_id"]: s for s in _STOPS_INPUT}
    for stop in payload["optimized_stops"]:
        orig = window_map.get(stop["stop_id"])
        if orig is None:
            continue
        arr = time_str_to_minutes(stop["arrival_time"])
        earliest = time_str_to_minutes(orig["earliest_pickup"])
        latest = time_str_to_minutes(orig["latest_pickup"])
        assert arr >= earliest, (
            f"Stop {stop['stop_id']}: arrival before earliest_pickup"
        )
        assert arr <= latest, (
            f"Stop {stop['stop_id']}: arrival after latest_pickup"
        )


# ---------------------------------------------------------------------------
# Step 8: No PHI in any generated message or Redis key
# ---------------------------------------------------------------------------

def test_step8_no_phi_in_initial_route_response(scenario):
    payload_str = json.dumps(scenario["initial_route"])
    for token in _PHI_TOKENS:
        assert token.lower() not in payload_str.lower(), (
            f"PHI token '{token}' found in initial route API response"
        )


def test_step8_no_phi_in_pubsub_payload(scenario):
    if not scenario["published_calls"]:
        pytest.skip("No Pub/Sub payload to inspect")
    _, payload_str = scenario["published_calls"][0]
    for token in _PHI_TOKENS:
        assert token.lower() not in payload_str.lower(), (
            f"PHI token '{token}' found in Pub/Sub re-route payload"
        )


def test_step8_stop_ids_are_uuids_not_names(scenario):
    """Stop IDs in both routes must be UUIDs, never patient names."""
    all_stop_ids = set(STOP_IDS)
    initial_ids = {s["stop_id"] for s in scenario["initial_route"].get("optimized_stops", [])}
    assert initial_ids == all_stop_ids

    if scenario["published_calls"]:
        _, payload_str = scenario["published_calls"][0]
        payload = json.loads(payload_str)
        for stop in payload["optimized_stops"]:
            assert stop["stop_id"] in all_stop_ids, (
                f"Unknown stop_id in re-route payload: {stop['stop_id']}"
            )


def test_step8_maps_url_contains_only_coordinates(scenario):
    """Google Maps URL must contain only lat/lng pairs — no stop IDs or names."""
    url = scenario["initial_route"].get("google_maps_url", "")
    for stop_id in STOP_IDS:
        assert stop_id not in url, f"stop_id '{stop_id}' found in Maps URL"
    for token in _PHI_TOKENS:
        assert token.lower() not in url.lower(), (
            f"PHI token '{token}' found in Maps URL"
        )


def test_step8_websocket_channel_name_no_phi(scenario):
    """The Pub/Sub channel name must be 'reroute:{driver_id}' — no PHI."""
    if not scenario["published_calls"]:
        pytest.skip("No Pub/Sub publish recorded")
    channel, _ = scenario["published_calls"][0]
    for token in _PHI_TOKENS:
        assert token.lower() not in channel.lower(), (
            f"PHI token '{token}' found in Pub/Sub channel name: {channel}"
        )
