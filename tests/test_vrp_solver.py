import pytest

from app.models.schemas import Location, Stop
from app.optimizer.vrp_solver import solve_vrp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_stop(
    stop_id: str,
    earliest: str = "00:00",
    latest: str = "23:59",
    service_time: int = 5,
) -> Stop:
    return Stop(
        stop_id=stop_id,
        location=Location(lat=0.0, lng=0.0),
        earliest_pickup=earliest,
        latest_pickup=latest,
        service_time_minutes=service_time,
    )


# ---------------------------------------------------------------------------
# 3-stop problem with a known optimal order
#
# time_matrix (seconds) — index 0 = driver, 1 = stop0, 2 = stop1, 3 = stop2
#
# Key distances (minutes):
#   driver → stop2 = 5 min   ← go here first (closest)
#   stop2  → stop1 = 10 min
#   stop1  → stop0 = 10 min
#   stop0  → driver= 5 min   ← return here (closest to depot)
#
# Route [2,1,0] total cost (including 5-min service per stop and return):
#   5 + (10+5) + (10+5) + (5+5) = 45 min  ← OPTIMAL
#
# All other permutations involve ≥ 60-min detours (≥ 100 min total).
# Input order [0,1,2] → solver must reorder to [2, 1, 0].
# ---------------------------------------------------------------------------

TIME_MATRIX_3 = [
    [0,    3600, 1800,  300],  # driver:  60→s0, 30→s1,  5→s2
    [300,     0,  600, 3600],  # stop0:    5→depot, 10→s1, 60→s2
    [1800,  600,    0,  600],  # stop1:   30→depot, 10→s0, 10→s2
    [300,  3600,  600,    0],  # stop2:    5→depot, 60→s0, 10→s1
]


def test_three_stop_known_optimal_order():
    stops = [make_stop("s0"), make_stop("s1"), make_stop("s2")]
    service_times = [5, 5, 5]
    result = solve_vrp(TIME_MATRIX_3, stops, service_times, departure_time_minutes=0)
    assert result == [2, 1, 0]


def test_result_is_permutation_of_all_stops():
    stops = [make_stop("s0"), make_stop("s1"), make_stop("s2")]
    service_times = [5, 5, 5]
    result = solve_vrp(TIME_MATRIX_3, stops, service_times, departure_time_minutes=0)
    assert sorted(result) == [0, 1, 2]


def test_returns_different_order_than_input():
    """Verifies the solver reorders stops, not just returns input order."""
    stops = [make_stop("s0"), make_stop("s1"), make_stop("s2")]
    service_times = [5, 5, 5]
    result = solve_vrp(TIME_MATRIX_3, stops, service_times, departure_time_minutes=0)
    assert result != [0, 1, 2], "Solver should return a different order than input"


# ---------------------------------------------------------------------------
# Time windows are respected
#
# Departure: 09:00 (540 min)
# stop0 window: 09:30–10:30 (570–630) — must be visited first
# stop1 window: 10:00–11:00 (600–660) — only reachable after stop0
#
# Route stop0 → stop1 is the ONLY feasible order:
#   arrive stop0 = 540+20=560 (wait 10 min → 570 ✓), depart 580
#   arrive stop1 = 580+30=610 ∈ [600,660] ✓
#
# Route stop1 → stop0 is infeasible:
#   arrive stop0 too late (670 > 630).
# ---------------------------------------------------------------------------

TIME_MATRIX_TW = [
    [0, 1200, 5400],   # driver: 20 min to stop0, 90 min to stop1
    [1200,  0, 1800],  # stop0: 30 min to stop1
    [5400, 1800,  0],  # stop1
]


def test_time_windows_force_correct_order():
    stops = [
        make_stop("s0", earliest="09:30", latest="10:30", service_time=10),
        make_stop("s1", earliest="10:00", latest="11:00", service_time=10),
    ]
    service_times = [10, 10]
    result = solve_vrp(TIME_MATRIX_TW, stops, service_times, departure_time_minutes=540)
    assert result == [0, 1]


def test_result_length_matches_number_of_stops():
    stops = [
        make_stop("s0", earliest="09:30", latest="10:30", service_time=10),
        make_stop("s1", earliest="10:00", latest="11:00", service_time=10),
    ]
    service_times = [10, 10]
    result = solve_vrp(TIME_MATRIX_TW, stops, service_times, departure_time_minutes=540)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Infeasible time windows raise ValueError
#
# Departure at 09:00 (540 min); stop0 window closes at 08:30 (510 min).
# Fastest travel = 5 min → arrives at 545, too late.
# ---------------------------------------------------------------------------

def test_impossible_windows_raise_value_error():
    time_matrix = [
        [0,  300, 3600],   # driver: 5 min to stop0
        [300,  0, 3300],   # stop0
        [3600, 3300, 0],   # stop1
    ]
    stops = [
        make_stop("s0", earliest="08:00", latest="08:30"),
        make_stop("s1", earliest="10:00", latest="11:00"),
    ]
    with pytest.raises(ValueError, match="No feasible route"):
        solve_vrp(time_matrix, stops, [5, 5], departure_time_minutes=540)


# ---------------------------------------------------------------------------
# Single stop — edge case
# ---------------------------------------------------------------------------

def test_single_stop_returns_single_index():
    time_matrix = [
        [0,  600],
        [600,  0],
    ]
    stops = [make_stop("s0")]
    result = solve_vrp(time_matrix, stops, [5], departure_time_minutes=0)
    assert result == [0]


# ---------------------------------------------------------------------------
# Return type is always a list of ints
# ---------------------------------------------------------------------------

def test_return_type_is_list_of_ints():
    stops = [make_stop("s0"), make_stop("s1")]
    time_matrix = [
        [0,  600, 1200],
        [600,  0,  600],
        [1200, 600,  0],
    ]
    result = solve_vrp(time_matrix, stops, [5, 5], departure_time_minutes=0)
    assert isinstance(result, list)
    assert all(isinstance(i, int) for i in result)
