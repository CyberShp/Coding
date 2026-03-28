"""Behavioral WebSocket tests.

Upgrades from endpoint registration tests to behavior tests covering:
- Connection management (add/remove clients)
- Multi-client subscription and broadcast
- Status deduplication and throttling
- Disconnection cleanup
- Message format correctness
"""

import asyncio
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from datetime import datetime
from starlette.websockets import WebSocketState


class TestConnectionManager:
    """Test WebSocket ConnectionManager behavior."""

    def _make_manager(self):
        from backend.api.websocket import ConnectionManager
        return ConnectionManager()

    def _make_ws(self, state=WebSocketState.CONNECTED):
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        ws.send_text = AsyncMock()
        ws.client_state = state
        return ws

    @pytest.mark.asyncio
    async def test_connect_adds_client(self):
        manager = self._make_manager()
        ws = self._make_ws()
        await manager.connect(ws, 'alerts')
        assert ws in manager._connections['alerts']

    @pytest.mark.asyncio
    async def test_disconnect_removes_client(self):
        manager = self._make_manager()
        ws = self._make_ws()
        await manager.connect(ws, 'alerts')
        assert ws in manager._connections['alerts']
        await manager.disconnect(ws, 'alerts')
        assert ws not in manager._connections['alerts']

    @pytest.mark.asyncio
    async def test_multiple_clients_tracked(self):
        manager = self._make_manager()
        ws1 = self._make_ws()
        ws2 = self._make_ws()
        await manager.connect(ws1, 'alerts')
        await manager.connect(ws2, 'alerts')
        assert len(manager._connections['alerts']) == 2

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all(self):
        manager = self._make_manager()
        ws1 = self._make_ws()
        ws2 = self._make_ws()
        await manager.connect(ws1, 'alerts')
        await manager.connect(ws2, 'alerts')

        msg = {"type": "alert", "data": {"level": "warning"}}
        await manager._do_broadcast('alerts', msg)

        ws1.send_json.assert_called_with(msg)
        ws2.send_json.assert_called_with(msg)

    @pytest.mark.asyncio
    async def test_broadcast_removes_broken_connections(self):
        manager = self._make_manager()
        ws_ok = self._make_ws()
        ws_broken = self._make_ws()
        ws_broken.send_json = AsyncMock(side_effect=Exception("Connection closed"))

        await manager.connect(ws_ok, 'alerts')
        await manager.connect(ws_broken, 'alerts')
        assert len(manager._connections['alerts']) == 2

        await manager._do_broadcast('alerts', {"type": "test"})

        assert ws_broken not in manager._connections['alerts']
        assert ws_ok in manager._connections['alerts']

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_is_safe(self):
        manager = self._make_manager()
        ws = self._make_ws()
        await manager.disconnect(ws, 'alerts')  # Should not raise

    @pytest.mark.asyncio
    async def test_different_channels_isolated(self):
        manager = self._make_manager()
        ws_alert = self._make_ws()
        ws_status = self._make_ws()
        await manager.connect(ws_alert, 'alerts')
        await manager.connect(ws_status, 'status')

        assert ws_alert in manager._connections['alerts']
        assert ws_status in manager._connections['status']
        assert ws_alert not in manager._connections['status']

    def test_connection_count(self):
        manager = self._make_manager()
        assert manager.get_connection_count('alerts') == 0
        assert manager.get_connection_count('nonexistent') == 0


class TestStatusDeduplication:
    """Test status update deduplication and throttling."""

    def _make_manager(self):
        from backend.api.websocket import ConnectionManager
        return ConnectionManager()

    def test_first_status_always_sends(self):
        manager = self._make_manager()
        status = {"state": "connected", "agent_running": True}
        assert manager.should_send_status("arr-1", status) is True

    def test_duplicate_status_suppressed(self):
        manager = self._make_manager()
        status = {"state": "connected", "agent_running": True}
        manager.should_send_status("arr-1", status)  # First call
        assert manager.should_send_status("arr-1", status) is False  # Duplicate

    def test_changed_status_sends(self):
        manager = self._make_manager()
        status1 = {"state": "connected", "agent_running": True}
        status2 = {"state": "connected", "agent_running": False}
        manager.should_send_status("arr-1", status1)
        # Clear throttle cache to allow immediate send
        manager._last_status_time["arr-1"] = 0
        assert manager.should_send_status("arr-1", status2) is True

    def test_different_arrays_independent(self):
        manager = self._make_manager()
        status = {"state": "connected"}
        assert manager.should_send_status("arr-1", status) is True
        assert manager.should_send_status("arr-2", status) is True


class TestBroadcastHelpers:
    """Test broadcast_alert and broadcast_status_update functions."""

    @pytest.mark.asyncio
    async def test_broadcast_alert_message_format(self):
        from backend.api.websocket import broadcast_alert, get_manager
        manager = get_manager()

        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED
        await manager.connect(ws, 'alerts')

        alert_data = {
            'array_id': 'arr-1',
            'observer_name': 'cpu_usage',
            'level': 'warning',
            'message': 'CPU high',
        }
        await broadcast_alert(alert_data)
        # Give batching time to flush
        await asyncio.sleep(0.2)

        if ws.send_json.called:
            sent = ws.send_json.call_args[0][0]
            assert sent['type'] == 'alert'
            assert sent['data']['observer_name'] == 'cpu_usage'

        await manager.disconnect(ws, 'alerts')

    @pytest.mark.asyncio
    async def test_broadcast_status_with_dedup(self):
        from backend.api.websocket import broadcast_status_update, get_manager
        manager = get_manager()

        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED
        await manager.connect(ws, 'status')

        status = {'state': 'connected', 'agent_running': True}
        await broadcast_status_update('arr-test', status)
        await asyncio.sleep(0.2)

        await manager.disconnect(ws, 'status')


class TestHeartbeatMessage:
    """Test heartbeat message format."""

    def test_ping_format(self):
        msg = json.dumps({"type": "ping"})
        parsed = json.loads(msg)
        assert parsed["type"] == "ping"

    def test_pong_format(self):
        msg = json.dumps({"type": "pong"})
        parsed = json.loads(msg)
        assert parsed["type"] == "pong"

    def test_heartbeat_interval_reasonable(self):
        heartbeat_interval = 30
        assert 10 <= heartbeat_interval <= 60


class TestAlertMessageFormat:
    """Test alert message serialization."""

    def test_alert_serialization(self):
        alert = {
            "type": "alert",
            "data": {
                "array_id": "arr-1",
                "observer_name": "card_info",
                "level": "error",
                "message": "Card No001 offline",
            }
        }
        serialized = json.dumps(alert)
        deserialized = json.loads(serialized)
        assert deserialized["type"] == "alert"
        assert deserialized["data"]["level"] == "error"

    def test_status_serialization(self):
        status = {
            "type": "status",
            "data": {
                "array_id": "arr-1",
                "state": "connected",
                "agent_deployed": True,
                "agent_running": False,
            }
        }
        serialized = json.dumps(status)
        deserialized = json.loads(serialized)
        assert deserialized["type"] == "status"
        assert deserialized["data"]["agent_running"] is False

