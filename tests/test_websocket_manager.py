"""tests/test_websocket_manager.py — Unit tests for ConnectionManager.

All external I/O is mocked:
  - WebSocket (FastAPI) — replaced with AsyncMock
  - clear_driver_state — patched so no real Redis call occurs
  - Redis Pub/Sub — patched in listener tests
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.websocket.manager import ConnectionManager


# ---------------------------------------------------------------------------
# Fixture: fresh manager per test (no shared state)
# ---------------------------------------------------------------------------


@pytest.fixture()
def mgr() -> ConnectionManager:
    return ConnectionManager()


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_adds_to_registry(mgr):
    mock_ws = AsyncMock()
    await mgr.connect("driver-001", mock_ws)
    assert "driver-001" in mgr.active_connections
    mock_ws.accept.assert_awaited_once()


@pytest.mark.asyncio
async def test_connect_stores_websocket_reference(mgr):
    mock_ws = AsyncMock()
    await mgr.connect("driver-001", mock_ws)
    assert mgr.active_connections["driver-001"] is mock_ws


@pytest.mark.asyncio
async def test_connect_multiple_drivers(mgr):
    ws1, ws2 = AsyncMock(), AsyncMock()
    await mgr.connect("driver-001", ws1)
    await mgr.connect("driver-002", ws2)
    assert len(mgr.active_connections) == 2


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------


def test_disconnect_removes_from_registry(mgr):
    mgr.active_connections["driver-001"] = MagicMock()
    with patch("app.websocket.manager.clear_driver_state") as mock_clear:
        mgr.disconnect("driver-001")
    assert "driver-001" not in mgr.active_connections
    mock_clear.assert_called_once_with("driver-001")


def test_disconnect_unknown_driver_is_safe(mgr):
    """Disconnecting a driver not in the registry should not raise."""
    with patch("app.websocket.manager.clear_driver_state"):
        mgr.disconnect("ghost")  # must not raise


def test_disconnect_calls_clear_driver_state(mgr):
    mgr.active_connections["driver-001"] = MagicMock()
    with patch("app.websocket.manager.clear_driver_state") as mock_clear:
        mgr.disconnect("driver-001")
    mock_clear.assert_called_once_with("driver-001")


def test_disconnect_only_removes_target_driver(mgr):
    mgr.active_connections["driver-001"] = MagicMock()
    mgr.active_connections["driver-002"] = MagicMock()
    with patch("app.websocket.manager.clear_driver_state"):
        mgr.disconnect("driver-001")
    assert "driver-002" in mgr.active_connections


# ---------------------------------------------------------------------------
# send_route_update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_route_update_calls_send_json(mgr):
    mock_ws = AsyncMock()
    mgr.active_connections["driver-001"] = mock_ws
    payload = {"type": "route_updated", "reason": "traffic_delay"}
    await mgr.send_route_update("driver-001", payload)
    mock_ws.send_json.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_send_route_update_no_connection_is_safe(mgr):
    """Should not raise when driver has no active connection."""
    await mgr.send_route_update("ghost", {"type": "route_updated"})


@pytest.mark.asyncio
async def test_send_route_update_handles_send_error(mgr):
    """Should not propagate exceptions raised by websocket.send_json."""
    mock_ws = AsyncMock()
    mock_ws.send_json.side_effect = Exception("connection reset")
    mgr.active_connections["driver-001"] = mock_ws
    await mgr.send_route_update("driver-001", {"type": "route_updated"})


# ---------------------------------------------------------------------------
# listen_for_reroutes (Pub/Sub listener)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_listen_forwards_route_update_message(mgr):
    """A valid route_updated Pub/Sub message is forwarded via send_route_update."""
    payload = {"type": "route_updated", "reason": "traffic_delay"}
    messages = [
        {"type": "subscribe", "data": 1},   # subscription confirmation
        {"type": "message", "data": json.dumps(payload)},
    ]

    mock_pubsub = AsyncMock()
    # pubsub() is synchronous in redis.asyncio — use MagicMock so it returns
    # mock_pubsub directly (not a coroutine)
    mock_pubsub.listen = MagicMock(return_value=_async_iter(messages))

    mock_redis = MagicMock()
    mock_redis.pubsub.return_value = mock_pubsub
    mock_redis.aclose = AsyncMock()

    with (
        patch("app.websocket.manager.aioredis.Redis", return_value=mock_redis),
        patch.object(mgr, "send_route_update", new=AsyncMock()) as mock_send,
    ):
        await mgr.listen_for_reroutes("driver-001")

    mock_send.assert_awaited_once_with("driver-001", payload)


@pytest.mark.asyncio
async def test_listen_skips_non_message_events(mgr):
    """subscribe/unsubscribe events should be ignored."""
    messages = [
        {"type": "subscribe", "data": 1},
        {"type": "psubscribe", "data": 1},
    ]

    mock_pubsub = AsyncMock()
    mock_pubsub.listen = MagicMock(return_value=_async_iter(messages))
    mock_redis = MagicMock()
    mock_redis.pubsub.return_value = mock_pubsub
    mock_redis.aclose = AsyncMock()

    with (
        patch("app.websocket.manager.aioredis.Redis", return_value=mock_redis),
        patch.object(mgr, "send_route_update", new=AsyncMock()) as mock_send,
    ):
        await mgr.listen_for_reroutes("driver-001")

    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_listen_skips_invalid_json(mgr):
    """Malformed Pub/Sub data should be logged and skipped without raising."""
    messages = [
        {"type": "message", "data": "not-json{{{}"},
    ]

    mock_pubsub = AsyncMock()
    mock_pubsub.listen = MagicMock(return_value=_async_iter(messages))
    mock_redis = MagicMock()
    mock_redis.pubsub.return_value = mock_pubsub
    mock_redis.aclose = AsyncMock()

    with (
        patch("app.websocket.manager.aioredis.Redis", return_value=mock_redis),
        patch.object(mgr, "send_route_update", new=AsyncMock()) as mock_send,
    ):
        await mgr.listen_for_reroutes("driver-001")  # must not raise

    mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_listen_exits_cleanly_on_cancel(mgr):
    """CancelledError from asyncio task cancellation propagates correctly."""

    async def _slow_listen():
        """Simulates a long-running Pub/Sub subscription."""
        await asyncio.sleep(10)
        # Unreachable; the yield makes Python treat this as an async generator
        yield  # noqa: unreachable

    mock_pubsub = AsyncMock()
    mock_pubsub.listen = MagicMock(return_value=_slow_listen())
    mock_redis = MagicMock()
    mock_redis.pubsub.return_value = mock_pubsub
    mock_redis.aclose = AsyncMock()

    with patch("app.websocket.manager.aioredis.Redis", return_value=mock_redis):
        task = asyncio.create_task(mgr.listen_for_reroutes("driver-001"))
        await asyncio.sleep(0)  # yield control so the task can start
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _async_iter(items):
    """Yield items as an async iterator — used to mock pubsub.listen()."""
    for item in items:
        yield item
