"""tests/test_tasks.py — Unit tests for app/workers/tasks.py.

All external dependencies are mocked:
  - app.state.driver_state functions (fakeredis via monkeypatch)
  - run_optimization (no real Google API / OR-Tools call)
  - Redis Pub/Sub publish
"""
import json
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
import pytest

from app.models.schemas import Location, OptimizedStop, OptimizeRouteResponse
from app.state.driver_state import DriverState
from app.workers.tasks import process_gps_update

# ---------------------------------------------------------------------------
# Shared fake route response
# ---------------------------------------------------------------------------

_FAKE_RESPONSE = OptimizeRouteResponse(
    driver_id="driver-001",
    optimized_stops=[
        OptimizedStop(
            stop_id="s2",
            sequence=1,
            location=Location(lat=37.76, lng=-122.40),
            arrival_time="09:15",
            departure_time="09:25",
        ),
        OptimizedStop(
            stop_id="s3",
            sequence=2,
            location=Location(lat=37.75, lng=-122.39),
            arrival_time="09:35",
            departure_time="09:45",
        ),
    ],
    total_distance_km=5.0,
    total_duration_minutes=45.0,
    google_maps_url="https://www.google.com/maps/dir/37.77,-122.41/37.76,-122.40/37.75,-122.39",
    optimization_score=1.2,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_redis_client():
    """In-process fakeredis client."""
    server = fakeredis.FakeServer()
    return fakeredis.FakeRedis(server=server, decode_responses=True)


def _base_state(driver_id="driver-001", **overrides) -> DriverState:
    defaults = dict(
        driver_id=driver_id,
        current_route=[
            {
                "stop_id": "s2",
                "sequence": 1,
                "location": {"lat": 37.76, "lng": -122.40},
                "earliest_pickup": "09:00",
                "latest_pickup": "22:00",
                "service_time_minutes": 10,
                "arrival_time": "09:15",
                "departure_time": "09:25",
            },
            {
                "stop_id": "s3",
                "sequence": 2,
                "location": {"lat": 37.75, "lng": -122.39},
                "earliest_pickup": "09:00",
                "latest_pickup": "22:00",
                "service_time_minutes": 10,
                "arrival_time": "09:35",
                "departure_time": "09:45",
            },
        ],
        last_gps=None,
        completed_stop_ids=[],
        remaining_duration=60.0,
        original_remaining_duration=60.0,
        schedule_delay_minutes=0.0,
        last_reroute_timestamp=None,
        stops_changed=False,
        status="active",
    )
    defaults.update(overrides)
    return DriverState(**defaults)


# ---------------------------------------------------------------------------
# Helper: run task with mocked state layer and optimizer
# ---------------------------------------------------------------------------

def _run_task(state, *, trigger_reroute=False, completed_stop_id=None):
    """Call process_gps_update with fully mocked deps."""

    # State sequence: initial get → (optional second get after mark_stop_completed)
    get_returns = [state, state]

    with (
        patch("app.workers.tasks.update_driver_gps"),
        patch("app.workers.tasks.get_driver_state", side_effect=get_returns),
        patch("app.workers.tasks.mark_stop_completed"),
        patch("app.workers.tasks.save_driver_state"),
        patch(
            "app.workers.tasks.should_reroute",
            return_value=(trigger_reroute, "traffic_delay" if trigger_reroute else ""),
        ),
        patch(
            "app.workers.tasks.run_optimization",
            new=AsyncMock(return_value=_FAKE_RESPONSE),
        ),
        patch("app.workers.tasks._get_redis", return_value=MagicMock()),
    ):
        return process_gps_update(
            driver_id=state.driver_id,
            lat=37.77,
            lng=-122.41,
            timestamp="2030-06-15T09:10:00Z",
            completed_stop_id=completed_stop_id,
        )


# ---------------------------------------------------------------------------
# Task: GPS update stored
# ---------------------------------------------------------------------------

def test_gps_update_called_with_correct_args():
    state = _base_state()
    with (
        patch("app.workers.tasks.update_driver_gps") as mock_gps,
        patch("app.workers.tasks.get_driver_state", return_value=state),
        patch("app.workers.tasks.save_driver_state"),
        patch("app.workers.tasks.should_reroute", return_value=(False, "")),
        patch("app.workers.tasks._get_redis", return_value=MagicMock()),
    ):
        process_gps_update("driver-001", 37.77, -122.41, "2030-06-15T09:10:00Z")
        mock_gps.assert_called_once_with("driver-001", 37.77, -122.41, "2030-06-15T09:10:00Z")


def test_returns_no_reroute_when_on_schedule():
    result = _run_task(_base_state(), trigger_reroute=False)
    assert result["rerouted"] is False


# ---------------------------------------------------------------------------
# Task: no active state
# ---------------------------------------------------------------------------

def test_returns_no_state_when_driver_not_found():
    with (
        patch("app.workers.tasks.update_driver_gps"),
        patch("app.workers.tasks.get_driver_state", return_value=None),
    ):
        result = process_gps_update("ghost", 0.0, 0.0, "2030-06-15T09:00:00Z")
    assert result == {"rerouted": False, "reason": "no_state"}


# ---------------------------------------------------------------------------
# Task: rerouting triggered when delay detected
# ---------------------------------------------------------------------------

def test_rerouting_triggered_when_delay_detected():
    state = _base_state(schedule_delay_minutes=10.0)
    result = _run_task(state, trigger_reroute=True)
    assert result["rerouted"] is True
    assert result["reason"] == "traffic_delay"


def test_run_optimization_called_with_remaining_stops():
    state = _base_state(schedule_delay_minutes=10.0)
    with (
        patch("app.workers.tasks.update_driver_gps"),
        patch("app.workers.tasks.get_driver_state", side_effect=[state, state]),
        patch("app.workers.tasks.mark_stop_completed"),
        patch("app.workers.tasks.save_driver_state"),
        patch("app.workers.tasks.should_reroute", return_value=(True, "traffic_delay")),
        patch(
            "app.workers.tasks.run_optimization",
            new=AsyncMock(return_value=_FAKE_RESPONSE),
        ) as mock_opt,
        patch("app.workers.tasks._get_redis", return_value=MagicMock()),
    ):
        process_gps_update("driver-001", 37.77, -122.41, "2030-06-15T09:10:00Z")
        mock_opt.assert_called_once()
        call_kwargs = mock_opt.call_args.kwargs
        # Remaining stops should match the current_route (none completed)
        assert len(call_kwargs["stops"]) == 2


# ---------------------------------------------------------------------------
# Task: completed stop removed from remaining stops
# ---------------------------------------------------------------------------

def test_completed_stop_excluded_from_reroute():
    state = _base_state(completed_stop_ids=["s2"])   # s2 already done
    with (
        patch("app.workers.tasks.update_driver_gps"),
        patch("app.workers.tasks.get_driver_state", side_effect=[state, state]),
        patch("app.workers.tasks.mark_stop_completed"),
        patch("app.workers.tasks.save_driver_state"),
        patch("app.workers.tasks.should_reroute", return_value=(True, "traffic_delay")),
        patch(
            "app.workers.tasks.run_optimization",
            new=AsyncMock(return_value=_FAKE_RESPONSE),
        ) as mock_opt,
        patch("app.workers.tasks._get_redis", return_value=MagicMock()),
    ):
        process_gps_update("driver-001", 37.77, -122.41, "2030-06-15T09:10:00Z")
        call_kwargs = mock_opt.call_args.kwargs
        stop_ids = [s.stop_id for s in call_kwargs["stops"]]
        assert "s2" not in stop_ids
        assert "s3" in stop_ids


# ---------------------------------------------------------------------------
# Task: rerouting NOT triggered when on schedule
# ---------------------------------------------------------------------------

def test_rerouting_not_triggered_when_on_schedule():
    state = _base_state()
    result = _run_task(state, trigger_reroute=False)
    assert result["rerouted"] is False


# ---------------------------------------------------------------------------
# Task: Pub/Sub publish called on reroute
# ---------------------------------------------------------------------------

def test_pubsub_published_on_reroute():
    state = _base_state(schedule_delay_minutes=10.0)
    mock_redis = MagicMock()
    with (
        patch("app.workers.tasks.update_driver_gps"),
        patch("app.workers.tasks.get_driver_state", side_effect=[state, state]),
        patch("app.workers.tasks.mark_stop_completed"),
        patch("app.workers.tasks.save_driver_state"),
        patch("app.workers.tasks.should_reroute", return_value=(True, "traffic_delay")),
        patch(
            "app.workers.tasks.run_optimization",
            new=AsyncMock(return_value=_FAKE_RESPONSE),
        ),
        patch("app.workers.tasks._get_redis", return_value=mock_redis),
    ):
        process_gps_update("driver-001", 37.77, -122.41, "2030-06-15T09:10:00Z")

    mock_redis.publish.assert_called_once()
    channel, payload_str = mock_redis.publish.call_args.args
    assert channel == "reroute:driver-001"
    payload = json.loads(payload_str)
    assert payload["type"] == "route_updated"
    assert payload["reason"] == "traffic_delay"
    assert len(payload["optimized_stops"]) == 2


def test_pubsub_not_published_when_no_reroute():
    state = _base_state()
    mock_redis = MagicMock()
    with (
        patch("app.workers.tasks.update_driver_gps"),
        patch("app.workers.tasks.get_driver_state", return_value=state),
        patch("app.workers.tasks.save_driver_state"),
        patch("app.workers.tasks.should_reroute", return_value=(False, "")),
        patch("app.workers.tasks._get_redis", return_value=mock_redis),
    ):
        process_gps_update("driver-001", 37.77, -122.41, "2030-06-15T09:10:00Z")

    mock_redis.publish.assert_not_called()
