"""tests/test_delay_detector.py — Unit tests for should_reroute()."""
import time
from unittest.mock import patch

from app.state.driver_state import DriverState
from app.workers.delay_detector import should_reroute


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(**overrides) -> DriverState:
    """Return an on-schedule DriverState (should NOT trigger reroute)."""
    defaults = dict(
        driver_id="driver-001",
        schedule_delay_minutes=0.0,
        remaining_duration=60.0,
        original_remaining_duration=60.0,
        last_reroute_timestamp=None,
        stops_changed=False,
        status="active",
    )
    defaults.update(overrides)
    return DriverState(**defaults)


# ---------------------------------------------------------------------------
# Baseline: on-time driver produces no reroute
# ---------------------------------------------------------------------------

def test_no_reroute_on_schedule():
    state = _make_state()
    triggered, reason = should_reroute(state)
    assert triggered is False
    assert reason == ""


# ---------------------------------------------------------------------------
# Rule 1: schedule delay
# ---------------------------------------------------------------------------

def test_rule1_triggers_when_delay_exceeds_threshold():
    """schedule_delay_minutes just above DELAY_THRESHOLD_MINUTES → reroute."""
    state = _make_state(schedule_delay_minutes=6.0)   # threshold is 5
    triggered, reason = should_reroute(state)
    assert triggered is True
    assert reason == "traffic_delay"


def test_rule1_does_not_trigger_at_threshold():
    """Delay exactly equal to the threshold should NOT trigger."""
    state = _make_state(schedule_delay_minutes=5.0)
    triggered, _ = should_reroute(state)
    assert triggered is False


def test_rule1_does_not_trigger_below_threshold():
    state = _make_state(schedule_delay_minutes=2.0)
    triggered, _ = should_reroute(state)
    assert triggered is False


# ---------------------------------------------------------------------------
# Rule 2: traffic increase ratio
# ---------------------------------------------------------------------------

def test_rule2_triggers_when_remaining_exceeds_ratio():
    """remaining_duration > original × 1.20 → reroute."""
    # original=60, ratio=1.20 → threshold=72; 73 should trigger
    state = _make_state(remaining_duration=73.0, original_remaining_duration=60.0)
    triggered, reason = should_reroute(state)
    assert triggered is True
    assert reason == "traffic_delay"


def test_rule2_does_not_trigger_at_ratio():
    """Exactly at ratio (72.0) should NOT trigger."""
    state = _make_state(remaining_duration=72.0, original_remaining_duration=60.0)
    triggered, _ = should_reroute(state)
    assert triggered is False


def test_rule2_does_not_trigger_below_ratio():
    state = _make_state(remaining_duration=65.0, original_remaining_duration=60.0)
    triggered, _ = should_reroute(state)
    assert triggered is False


def test_rule2_skipped_when_original_duration_is_zero():
    """Zero original duration should not cause division / false trigger."""
    state = _make_state(remaining_duration=100.0, original_remaining_duration=0.0)
    triggered, _ = should_reroute(state)
    assert triggered is False


# ---------------------------------------------------------------------------
# Rule 3: stops changed
# ---------------------------------------------------------------------------

def test_rule3_triggers_when_stops_changed():
    state = _make_state(stops_changed=True)
    triggered, reason = should_reroute(state)
    assert triggered is True
    assert reason == "stop_modified"


def test_rule3_does_not_trigger_when_stops_unchanged():
    state = _make_state(stops_changed=False)
    triggered, _ = should_reroute(state)
    assert triggered is False


# ---------------------------------------------------------------------------
# Rule 0 (cooldown): prevents back-to-back re-routing
# ---------------------------------------------------------------------------

def test_cooldown_suppresses_reroute_when_recent():
    """A reroute that just happened should be suppressed by cooldown."""
    # last_reroute_timestamp = now → 0 seconds ago → within cooldown (300s)
    state = _make_state(
        schedule_delay_minutes=10.0,   # would trigger Rule 1
        last_reroute_timestamp=time.time(),
    )
    triggered, reason = should_reroute(state)
    assert triggered is False
    assert reason == ""


def test_cooldown_allows_reroute_after_interval():
    """After MIN_REROUTE_INTERVAL_SECONDS the cooldown expires."""
    past = time.time() - 301   # 301 s ago > 300 s threshold
    state = _make_state(
        schedule_delay_minutes=10.0,
        last_reroute_timestamp=past,
    )
    triggered, reason = should_reroute(state)
    assert triggered is True
    assert reason == "traffic_delay"


def test_cooldown_does_not_apply_if_never_rerouted():
    """last_reroute_timestamp=None means no cooldown."""
    state = _make_state(
        schedule_delay_minutes=10.0,
        last_reroute_timestamp=None,
    )
    triggered, reason = should_reroute(state)
    assert triggered is True


def test_cooldown_suppresses_stop_modified_too():
    """Cooldown applies to all rules, including stops_changed."""
    state = _make_state(
        stops_changed=True,
        last_reroute_timestamp=time.time(),
    )
    triggered, _ = should_reroute(state)
    assert triggered is False


# ---------------------------------------------------------------------------
# Rule independence: each rule fires on its own
# ---------------------------------------------------------------------------

def test_rules_are_independent_rule1_only():
    state = _make_state(schedule_delay_minutes=6.0, stops_changed=False)
    triggered, reason = should_reroute(state)
    assert triggered is True
    assert reason == "traffic_delay"


def test_rules_are_independent_rule2_only():
    state = _make_state(remaining_duration=80.0, original_remaining_duration=60.0)
    triggered, reason = should_reroute(state)
    assert triggered is True
    assert reason == "traffic_delay"


def test_rules_are_independent_rule3_only():
    state = _make_state(stops_changed=True)
    triggered, reason = should_reroute(state)
    assert triggered is True
    assert reason == "stop_modified"
