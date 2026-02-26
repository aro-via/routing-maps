import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.optimizer.distance_matrix import _build_cache_key, build_distance_matrix

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

LOCATIONS = [(37.7749, -122.4194), (37.3382, -121.8863), (37.6879, -122.4702)]
DEPARTURE = datetime(2030, 6, 15, 9, 0, tzinfo=timezone.utc)

GOOGLE_RESPONSE = {
    "rows": [
        {
            "elements": [
                {"status": "OK", "duration_in_traffic": {"value": 0}, "distance": {"value": 0}},
                {"status": "OK", "duration_in_traffic": {"value": 1200}, "distance": {"value": 15000}},
                {"status": "OK", "duration_in_traffic": {"value": 600}, "distance": {"value": 8000}},
            ]
        },
        {
            "elements": [
                {"status": "OK", "duration_in_traffic": {"value": 1200}, "distance": {"value": 15000}},
                {"status": "OK", "duration_in_traffic": {"value": 0}, "distance": {"value": 0}},
                {"status": "OK", "duration_in_traffic": {"value": 900}, "distance": {"value": 11000}},
            ]
        },
        {
            "elements": [
                {"status": "OK", "duration_in_traffic": {"value": 600}, "distance": {"value": 8000}},
                {"status": "OK", "duration_in_traffic": {"value": 900}, "distance": {"value": 11000}},
                {"status": "OK", "duration_in_traffic": {"value": 0}, "distance": {"value": 0}},
            ]
        },
    ]
}

CACHED_RESULT = {
    "time_matrix": [[0, 1200, 600], [1200, 0, 900], [600, 900, 0]],
    "distance_matrix": [[0, 15000, 8000], [15000, 0, 11000], [8000, 11000, 0]],
}


def _mock_redis(cached_value=None, ping_raises=False):
    """Build a Redis mock that optionally returns a cached JSON string."""
    mock_r = MagicMock()
    if ping_raises:
        mock_r.ping.side_effect = ConnectionError("Redis down")
    else:
        mock_r.ping.return_value = True
        mock_r.get.return_value = json.dumps(cached_value) if cached_value else None
    return mock_r


# ---------------------------------------------------------------------------
# _build_cache_key
# ---------------------------------------------------------------------------

def test_cache_key_is_deterministic():
    key1 = _build_cache_key(LOCATIONS, DEPARTURE)
    key2 = _build_cache_key(LOCATIONS, DEPARTURE)
    assert key1 == key2


def test_cache_key_differs_for_different_locations():
    other = [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)]
    assert _build_cache_key(LOCATIONS, DEPARTURE) != _build_cache_key(other, DEPARTURE)


def test_cache_key_differs_for_different_hour():
    dep2 = datetime(2030, 6, 15, 10, 0, tzinfo=timezone.utc)
    assert _build_cache_key(LOCATIONS, DEPARTURE) != _build_cache_key(LOCATIONS, dep2)


def test_cache_key_same_for_different_minute_same_hour():
    dep_at_09_30 = datetime(2030, 6, 15, 9, 30, tzinfo=timezone.utc)
    assert _build_cache_key(LOCATIONS, DEPARTURE) == _build_cache_key(LOCATIONS, dep_at_09_30)


def test_cache_key_sorted_by_coordinates():
    reversed_locs = list(reversed(LOCATIONS))
    assert _build_cache_key(LOCATIONS, DEPARTURE) == _build_cache_key(reversed_locs, DEPARTURE)


# ---------------------------------------------------------------------------
# Cache hit — Google API must NOT be called
# ---------------------------------------------------------------------------

def test_cache_hit_returns_cached_value():
    mock_r = _mock_redis(cached_value=CACHED_RESULT)

    with patch("app.optimizer.distance_matrix.redis.Redis", return_value=mock_r), \
         patch("app.optimizer.distance_matrix.googlemaps.Client") as mock_gmaps:

        result = build_distance_matrix(LOCATIONS, DEPARTURE)

    assert result == CACHED_RESULT
    mock_gmaps.assert_not_called()


def test_cache_hit_does_not_write_again():
    mock_r = _mock_redis(cached_value=CACHED_RESULT)

    with patch("app.optimizer.distance_matrix.redis.Redis", return_value=mock_r):
        build_distance_matrix(LOCATIONS, DEPARTURE)

    mock_r.setex.assert_not_called()


# ---------------------------------------------------------------------------
# Cache miss — Google API IS called and result is cached
# ---------------------------------------------------------------------------

def test_cache_miss_calls_google_api():
    mock_r = _mock_redis()  # get() returns None

    with patch("app.optimizer.distance_matrix.redis.Redis", return_value=mock_r), \
         patch("app.optimizer.distance_matrix.googlemaps.Client") as mock_client_cls:

        mock_client = mock_client_cls.return_value
        mock_client.distance_matrix.return_value = GOOGLE_RESPONSE

        result = build_distance_matrix(LOCATIONS, DEPARTURE)

    mock_client.distance_matrix.assert_called_once()
    assert result["time_matrix"][0][1] == 1200
    assert result["distance_matrix"][0][1] == 15000


def test_cache_miss_stores_result_in_redis():
    mock_r = _mock_redis()

    with patch("app.optimizer.distance_matrix.redis.Redis", return_value=mock_r), \
         patch("app.optimizer.distance_matrix.googlemaps.Client") as mock_client_cls:

        mock_client = mock_client_cls.return_value
        mock_client.distance_matrix.return_value = GOOGLE_RESPONSE

        build_distance_matrix(LOCATIONS, DEPARTURE)

    mock_r.setex.assert_called_once()


def test_duration_in_traffic_preferred_over_duration():
    """duration_in_traffic (1200s) should be used instead of duration (999s)."""
    response_with_both = {
        "rows": [
            {
                "elements": [
                    {"status": "OK", "duration_in_traffic": {"value": 1200}, "duration": {"value": 999}, "distance": {"value": 5000}},
                    {"status": "OK", "duration_in_traffic": {"value": 500}, "duration": {"value": 400}, "distance": {"value": 3000}},
                ]
            },
            {
                "elements": [
                    {"status": "OK", "duration_in_traffic": {"value": 500}, "duration": {"value": 400}, "distance": {"value": 3000}},
                    {"status": "OK", "duration_in_traffic": {"value": 0}, "duration": {"value": 0}, "distance": {"value": 0}},
                ]
            },
        ]
    }

    with patch("app.optimizer.distance_matrix.redis.Redis") as mock_redis_cls, \
         patch("app.optimizer.distance_matrix.googlemaps.Client") as mock_client_cls:

        mock_redis_cls.return_value.ping.side_effect = ConnectionError()
        mock_client = mock_client_cls.return_value
        mock_client.distance_matrix.return_value = response_with_both

        result = build_distance_matrix([(0.0, 0.0), (1.0, 1.0)], DEPARTURE)

    assert result["time_matrix"][0][0] == 1200
    assert result["time_matrix"][0][1] == 500


def test_fallback_to_duration_when_no_traffic_data():
    """When duration_in_traffic is absent, use duration."""
    response_no_traffic = {
        "rows": [
            {
                "elements": [
                    {"status": "OK", "duration": {"value": 800}, "distance": {"value": 5000}},
                    {"status": "OK", "duration": {"value": 300}, "distance": {"value": 2000}},
                ]
            },
            {
                "elements": [
                    {"status": "OK", "duration": {"value": 300}, "distance": {"value": 2000}},
                    {"status": "OK", "duration": {"value": 0}, "distance": {"value": 0}},
                ]
            },
        ]
    }

    with patch("app.optimizer.distance_matrix.redis.Redis") as mock_redis_cls, \
         patch("app.optimizer.distance_matrix.googlemaps.Client") as mock_client_cls:

        mock_redis_cls.return_value.ping.side_effect = ConnectionError()
        mock_client = mock_client_cls.return_value
        mock_client.distance_matrix.return_value = response_no_traffic

        result = build_distance_matrix([(0.0, 0.0), (1.0, 1.0)], DEPARTURE)

    assert result["time_matrix"][0][0] == 800
    assert result["time_matrix"][0][1] == 300


# ---------------------------------------------------------------------------
# Google API error handling
# ---------------------------------------------------------------------------

def test_google_api_not_ok_element_uses_sentinel_value():
    """Elements with status != OK are treated as unreachable (999999)."""
    response_with_error = {
        "rows": [
            {
                "elements": [
                    {"status": "OK", "duration_in_traffic": {"value": 0}, "distance": {"value": 0}},
                    {"status": "NOT_FOUND"},
                ]
            },
            {
                "elements": [
                    {"status": "NOT_FOUND"},
                    {"status": "OK", "duration_in_traffic": {"value": 0}, "distance": {"value": 0}},
                ]
            },
        ]
    }

    with patch("app.optimizer.distance_matrix.redis.Redis") as mock_redis_cls, \
         patch("app.optimizer.distance_matrix.googlemaps.Client") as mock_client_cls:

        mock_redis_cls.return_value.ping.side_effect = ConnectionError()
        mock_client = mock_client_cls.return_value
        mock_client.distance_matrix.return_value = response_with_error

        result = build_distance_matrix([(0.0, 0.0), (1.0, 1.0)], DEPARTURE)

    assert result["time_matrix"][0][1] == 999_999
    assert result["distance_matrix"][0][1] == 999_999


# ---------------------------------------------------------------------------
# Redis unavailable — service degrades gracefully, no exception raised
# ---------------------------------------------------------------------------

def test_redis_unavailable_falls_through_to_google():
    with patch("app.optimizer.distance_matrix.redis.Redis") as mock_redis_cls, \
         patch("app.optimizer.distance_matrix.googlemaps.Client") as mock_client_cls:

        mock_redis_cls.return_value.ping.side_effect = ConnectionError("Redis down")
        mock_client = mock_client_cls.return_value
        mock_client.distance_matrix.return_value = GOOGLE_RESPONSE

        # Must not raise despite Redis being down
        result = build_distance_matrix(LOCATIONS, DEPARTURE)

    assert "time_matrix" in result
    assert "distance_matrix" in result
    mock_client.distance_matrix.assert_called_once()
