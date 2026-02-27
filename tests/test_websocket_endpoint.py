"""tests/test_websocket_endpoint.py — Integration tests for WS /ws/driver/{driver_id}.

Uses FastAPI's TestClient WebSocket support (synchronous).

Strategy: use the real ConnectionManager singleton but mock only the
external I/O it reaches out to:
  - manager.listen_for_reroutes  → AsyncMock (no real Redis)
  - clear_driver_state           → patched (no real Redis)
  - process_gps_update           → patched (no real Celery)

This ensures websocket.accept() is called for real (required by TestClient)
while keeping tests fast and isolated.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.websocket.manager import manager as ws_manager


@pytest.fixture()
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Context manager: standard patches for all WebSocket tests
# ---------------------------------------------------------------------------

def _ws_patches(mock_task=None):
    """Return a list of context managers that suppress all external I/O."""
    patches = [
        patch.object(ws_manager, "listen_for_reroutes", new=AsyncMock()),
        patch("app.websocket.manager.clear_driver_state"),
    ]
    if mock_task is not None:
        patches.append(
            patch("app.websocket.handlers.process_gps_update", mock_task)
        )
    return patches


# ---------------------------------------------------------------------------
# Task 22 — Test: connection accepted
# ---------------------------------------------------------------------------


def test_websocket_connection_accepted(client):
    """WebSocket handshake succeeds without errors."""
    with (
        patch.object(ws_manager, "listen_for_reroutes", new=AsyncMock()),
        patch("app.websocket.manager.clear_driver_state"),
    ):
        with client.websocket_connect("/ws/driver/driver-001") as ws:
            ws.close()
    # Reaching here means the endpoint accepted the connection cleanly


def test_websocket_disconnect_cleans_up(client):
    """Closing the WebSocket removes the driver from active_connections."""
    with (
        patch.object(ws_manager, "listen_for_reroutes", new=AsyncMock()),
        patch("app.websocket.manager.clear_driver_state"),
    ):
        with client.websocket_connect("/ws/driver/driver-001") as ws:
            ws.close()

    assert "driver-001" not in ws_manager.active_connections


# ---------------------------------------------------------------------------
# Task 22 — Test: GPS message dispatches Celery task
# ---------------------------------------------------------------------------


def test_gps_message_dispatches_celery_task(client):
    """A valid gps_update message causes process_gps_update.delay to be called."""
    mock_task = MagicMock()

    with (
        patch.object(ws_manager, "listen_for_reroutes", new=AsyncMock()),
        patch("app.websocket.manager.clear_driver_state"),
        patch("app.websocket.handlers.process_gps_update", mock_task),
    ):
        with client.websocket_connect("/ws/driver/driver-001") as ws:
            ws.send_json({
                "type": "gps_update",
                "lat": 37.77,
                "lng": -122.41,
                "timestamp": "2030-06-15T09:10:00Z",
            })
            ws.close()

    mock_task.delay.assert_called_once_with(
        driver_id="driver-001",
        lat=37.77,
        lng=-122.41,
        timestamp="2030-06-15T09:10:00Z",
        completed_stop_id=None,
    )


def test_gps_message_with_completed_stop_id(client):
    """completed_stop_id is forwarded to the Celery task when present."""
    mock_task = MagicMock()

    with (
        patch.object(ws_manager, "listen_for_reroutes", new=AsyncMock()),
        patch("app.websocket.manager.clear_driver_state"),
        patch("app.websocket.handlers.process_gps_update", mock_task),
    ):
        with client.websocket_connect("/ws/driver/driver-001") as ws:
            ws.send_json({
                "type": "gps_update",
                "lat": 37.77,
                "lng": -122.41,
                "timestamp": "2030-06-15T09:10:00Z",
                "completed_stop_id": "stop-42",
            })
            ws.close()

    call_kwargs = mock_task.delay.call_args.kwargs
    assert call_kwargs["completed_stop_id"] == "stop-42"


def test_gps_update_missing_lat_lng_not_dispatched(client):
    """A gps_update message without lat/lng must NOT dispatch a Celery task."""
    mock_task = MagicMock()

    with (
        patch.object(ws_manager, "listen_for_reroutes", new=AsyncMock()),
        patch("app.websocket.manager.clear_driver_state"),
        patch("app.websocket.handlers.process_gps_update", mock_task),
    ):
        with client.websocket_connect("/ws/driver/driver-001") as ws:
            ws.send_json({"type": "gps_update"})  # missing lat and lng
            ws.close()

    mock_task.delay.assert_not_called()


def test_unknown_message_type_ignored(client):
    """An unknown message type does not raise and does not dispatch a task."""
    mock_task = MagicMock()

    with (
        patch.object(ws_manager, "listen_for_reroutes", new=AsyncMock()),
        patch("app.websocket.manager.clear_driver_state"),
        patch("app.websocket.handlers.process_gps_update", mock_task),
    ):
        with client.websocket_connect("/ws/driver/driver-001") as ws:
            ws.send_json({"type": "ping", "client_time": "2030-06-15T09:00:00Z"})
            ws.close()

    mock_task.delay.assert_not_called()


# ---------------------------------------------------------------------------
# Task 22 — Test: multiple GPS messages
# ---------------------------------------------------------------------------


def test_multiple_gps_updates_each_dispatch_task(client):
    """Each gps_update in the session dispatches its own Celery task."""
    mock_task = MagicMock()

    with (
        patch.object(ws_manager, "listen_for_reroutes", new=AsyncMock()),
        patch("app.websocket.manager.clear_driver_state"),
        patch("app.websocket.handlers.process_gps_update", mock_task),
    ):
        with client.websocket_connect("/ws/driver/driver-001") as ws:
            for i in range(3):
                ws.send_json({
                    "type": "gps_update",
                    "lat": 37.77 + i * 0.01,
                    "lng": -122.41,
                    "timestamp": f"2030-06-15T09:{10 + i:02d}:00Z",
                })
            ws.close()

    assert mock_task.delay.call_count == 3


# ---------------------------------------------------------------------------
# Task 22 — Test: Pub/Sub listener started per connection
# ---------------------------------------------------------------------------


def test_pubsub_listener_started_on_connect(client):
    """listen_for_reroutes is invoked once per connection with the correct driver_id."""
    mock_listener = AsyncMock()

    with (
        patch.object(ws_manager, "listen_for_reroutes", new=mock_listener),
        patch("app.websocket.manager.clear_driver_state"),
    ):
        with client.websocket_connect("/ws/driver/driver-001") as ws:
            ws.close()

    mock_listener.assert_awaited_once_with("driver-001")
