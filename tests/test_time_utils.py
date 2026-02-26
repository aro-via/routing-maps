import pytest

from app.utils.time_utils import (
    add_minutes_to_time,
    minutes_to_time_str,
    time_str_to_minutes,
)


# ---------------------------------------------------------------------------
# time_str_to_minutes
# ---------------------------------------------------------------------------

def test_time_str_to_minutes_basic():
    assert time_str_to_minutes("08:30") == 510


def test_time_str_to_minutes_midnight():
    assert time_str_to_minutes("00:00") == 0


def test_time_str_to_minutes_end_of_day():
    assert time_str_to_minutes("23:59") == 1439


def test_time_str_to_minutes_noon():
    assert time_str_to_minutes("12:00") == 720


# ---------------------------------------------------------------------------
# minutes_to_time_str
# ---------------------------------------------------------------------------

def test_minutes_to_time_str_basic():
    assert minutes_to_time_str(510) == "08:30"


def test_minutes_to_time_str_midnight():
    assert minutes_to_time_str(0) == "00:00"


def test_minutes_to_time_str_end_of_day():
    assert minutes_to_time_str(1439) == "23:59"


def test_minutes_to_time_str_overflow_wraps():
    # 1440 minutes = exactly one full day, wraps to 00:00
    assert minutes_to_time_str(1440) == "00:00"
    assert minutes_to_time_str(1441) == "00:01"


def test_minutes_to_time_str_large_overflow():
    # 1500 = 1440 + 60 → 01:00
    assert minutes_to_time_str(1500) == "01:00"


def test_minutes_to_time_str_zero_padding():
    assert minutes_to_time_str(5) == "00:05"
    assert minutes_to_time_str(65) == "01:05"


# ---------------------------------------------------------------------------
# add_minutes_to_time
# ---------------------------------------------------------------------------

def test_add_minutes_to_time_basic():
    assert add_minutes_to_time("08:30", 45) == "09:15"


def test_add_minutes_to_time_no_change():
    assert add_minutes_to_time("08:30", 0) == "08:30"


def test_add_minutes_to_time_crosses_hour():
    assert add_minutes_to_time("08:45", 30) == "09:15"


def test_add_minutes_to_time_overnight_overflow():
    assert add_minutes_to_time("23:30", 45) == "00:15"


def test_add_minutes_to_time_exactly_midnight():
    assert add_minutes_to_time("23:59", 1) == "00:00"


def test_add_minutes_to_time_large_addition():
    # Adding 120 min (2 hours) to 22:00 → 00:00
    assert add_minutes_to_time("22:00", 120) == "00:00"


# ---------------------------------------------------------------------------
# Round-trip consistency
# ---------------------------------------------------------------------------

def test_round_trip():
    for minutes in [0, 1, 59, 60, 510, 720, 1439]:
        assert time_str_to_minutes(minutes_to_time_str(minutes)) == minutes
