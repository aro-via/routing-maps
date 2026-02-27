"""tests/test_driver_state.py — Unit tests for app/state/driver_state.py.

Redis is replaced with fakeredis so no real server is needed.
"""
from unittest.mock import patch

import fakeredis
import pytest

from app.state.driver_state import (
    DriverState,
    clear_driver_state,
    get_driver_state,
    mark_stop_completed,
    save_driver_state,
    update_driver_gps,
)

# ---------------------------------------------------------------------------
# Fixture: patch _get_redis to return a fresh fakeredis instance per test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    """Replace every call to _get_redis with a fresh in-process fake."""
    server = fakeredis.FakeServer()
    client = fakeredis.FakeRedis(server=server, decode_responses=True)
    monkeypatch.setattr("app.state.driver_state._get_redis", lambda: client)
    return client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(**overrides) -> DriverState:
    defaults = dict(
        driver_id="driver-001",
        current_route=[{"stop_id": "s1", "sequence": 1}],
        last_gps={"lat": 37.77, "lng": -122.41, "timestamp": "2030-06-15T09:00:00Z"},
        completed_stop_ids=[],
        original_remaining_duration=60.0,
        schedule_delay_minutes=0.0,
        last_reroute_timestamp=None,
        stops_changed=False,
        status="active",
    )
    defaults.update(overrides)
    return DriverState(**defaults)


# ---------------------------------------------------------------------------
# save / get round-trip
# ---------------------------------------------------------------------------

def test_save_and_get_round_trip():
    state = _make_state()
    save_driver_state(state)
    loaded = get_driver_state("driver-001")
    assert loaded is not None
    assert loaded.driver_id == "driver-001"
    assert loaded.status == "active"
    assert loaded.original_remaining_duration == 60.0


def test_get_returns_none_for_unknown_driver():
    assert get_driver_state("ghost-driver") is None


def test_save_preserves_current_route():
    route = [{"stop_id": "s1", "sequence": 1}, {"stop_id": "s2", "sequence": 2}]
    state = _make_state(current_route=route)
    save_driver_state(state)
    loaded = get_driver_state("driver-001")
    assert loaded.current_route == route


def test_save_preserves_last_gps():
    gps = {"lat": 37.77, "lng": -122.41, "timestamp": "2030-06-15T09:05:00Z"}
    state = _make_state(last_gps=gps)
    save_driver_state(state)
    loaded = get_driver_state("driver-001")
    assert loaded.last_gps == gps


def test_save_with_no_gps():
    state = _make_state(last_gps=None)
    save_driver_state(state)
    loaded = get_driver_state("driver-001")
    assert loaded.last_gps is None


def test_save_preserves_completed_stop_ids():
    state = _make_state(completed_stop_ids=["s1", "s2"])
    save_driver_state(state)
    loaded = get_driver_state("driver-001")
    assert loaded.completed_stop_ids == ["s1", "s2"]


# ---------------------------------------------------------------------------
# update_driver_gps
# ---------------------------------------------------------------------------

def test_update_gps_modifies_only_last_gps():
    state = _make_state()
    save_driver_state(state)

    update_driver_gps("driver-001", lat=37.80, lng=-122.40, timestamp="2030-06-15T09:10:00Z")

    loaded = get_driver_state("driver-001")
    assert loaded.last_gps == {"lat": 37.80, "lng": -122.40, "timestamp": "2030-06-15T09:10:00Z"}
    # Other fields must be unchanged
    assert loaded.status == "active"
    assert loaded.original_remaining_duration == 60.0
    assert loaded.completed_stop_ids == []


def test_update_gps_without_existing_state_does_not_crash():
    """GPS update for a driver with no state should not raise."""
    update_driver_gps("unknown-driver", lat=37.80, lng=-122.40, timestamp="2030-06-15T09:00:00Z")


# ---------------------------------------------------------------------------
# mark_stop_completed
# ---------------------------------------------------------------------------

def test_completed_stops_accumulate():
    state = _make_state()
    save_driver_state(state)

    mark_stop_completed("driver-001", "s1")
    mark_stop_completed("driver-001", "s2")

    loaded = get_driver_state("driver-001")
    assert "s1" in loaded.completed_stop_ids
    assert "s2" in loaded.completed_stop_ids
    assert len(loaded.completed_stop_ids) == 2


def test_duplicate_stop_not_added_twice():
    state = _make_state(completed_stop_ids=["s1"])
    save_driver_state(state)

    mark_stop_completed("driver-001", "s1")

    loaded = get_driver_state("driver-001")
    assert loaded.completed_stop_ids.count("s1") == 1


def test_mark_stop_completed_without_state_does_not_crash():
    mark_stop_completed("ghost-driver", "s99")


# ---------------------------------------------------------------------------
# clear_driver_state
# ---------------------------------------------------------------------------

def test_clear_removes_state():
    state = _make_state()
    save_driver_state(state)
    clear_driver_state("driver-001")
    assert get_driver_state("driver-001") is None


def test_clear_nonexistent_driver_does_not_crash():
    clear_driver_state("ghost-driver")


# ---------------------------------------------------------------------------
# Expired state returns None
# ---------------------------------------------------------------------------

def test_expired_state_returns_none(fake_redis):
    """Simulate TTL expiry by deleting the key directly."""
    state = _make_state()
    save_driver_state(state)
    # Force-expire the key
    fake_redis.delete("driver:driver-001:state")
    assert get_driver_state("driver-001") is None


# ---------------------------------------------------------------------------
# No PHI in stored keys / values
# ---------------------------------------------------------------------------

def test_no_phi_in_redis_keys(fake_redis):
    """Confirm Redis keys contain only driver IDs (UUIDs), not patient data."""
    state = _make_state(driver_id="d-uuid-001")
    save_driver_state(state)
    keys = fake_redis.keys("*")
    for key in keys:
        assert "patient" not in key.lower()
        assert "name" not in key.lower()
        assert "dob" not in key.lower()
