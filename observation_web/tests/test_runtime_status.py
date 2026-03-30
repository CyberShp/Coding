"""Tests for unified runtime status, strict running detection, ingest array_id,
and recovery-driven failure state cleanup.

Covers:
1. /arrays/statuses and /arrays/{id}/status return consistent fields
2. systemd active but MainPID invalid → running=false
3. PID file present but PID dead → stale_pidfile detected
4. pgrep fuzzy mismatch → running=false
5. Process exists but no heartbeat → running=true, healthy=false
6. Ingest without real array_id → rejected (no push_xxx)
7. Recovery event clears stale failure state
"""

import time
import pytest
import pytest_asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, AsyncMock

from backend.core.agent_deployer import (
    AgentDeployer,
    AGENT_PID_FILE,
    SYSTEMD_SERVICE_NAME,
)
from backend.core.runtime_status import (
    build_runtime_status,
    record_heartbeat,
    is_agent_healthy,
    get_last_heartbeat,
    register_ip_array_mapping,
    resolve_array_id_by_ip,
    on_recovery_event,
    _heartbeat_store,
    _health_source_store,
    _ip_to_array_id,
    _status_versions,
    HEALTHY_WINDOW_SECONDS,
)
from backend.models.array import ArrayStatus, ConnectionState
from backend.config import AppConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_deployer(connected=True):
    mock_conn = MagicMock()
    mock_conn.is_connected.return_value = connected
    mock_conn.host = "10.0.0.1"
    mock_conn.execute.return_value = (0, "", "")
    config = AppConfig()
    config.server.host = "backend.local"
    return AgentDeployer(mock_conn, config), mock_conn


def _cmd_router(responses: dict, default=(1, "", "")):
    def _route(cmd, *args, **kwargs):
        for pattern, result in responses.items():
            if pattern in cmd:
                return result
        return default
    return _route


def _fresh_status(array_id="arr-001"):
    return ArrayStatus(array_id=array_id, name="Test", host="10.0.0.1")


# ---------------------------------------------------------------------------
# 1. Status consistency: build_runtime_status outputs correct fields
# ---------------------------------------------------------------------------

class TestBuildRuntimeStatus:
    """Validate build_runtime_status produces the unified shape."""

    def test_disconnected_array(self):
        """No SSH connection → disconnected, running=false."""
        status = _fresh_status()
        result = build_runtime_status(status, ssh_conn=None, probe_mode="cached")
        assert result.state == ConnectionState.DISCONNECTED
        assert result.transport_connected is False
        assert result.agent_running is False
        assert result.agent_healthy is False
        assert result.collect_status == "unknown"
        assert result.status_version >= 1
        assert result.updated_at is not None

    def test_connected_with_deployer(self):
        """Connected + deployer info → correct running/confidence."""
        status = _fresh_status()
        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = True
        mock_conn.state = ConnectionState.CONNECTED
        mock_conn.last_error = ""

        deployer_info = {
            "deployed": True,
            "running": True,
            "running_confidence": "high",
            "running_source": "systemd",
        }
        result = build_runtime_status(
            status, ssh_conn=mock_conn, deployer_info=deployer_info, probe_mode="strict"
        )
        assert result.state == ConnectionState.CONNECTED
        assert result.transport_connected is True
        assert result.agent_running is True
        assert result.running_confidence == "high"
        assert result.running_source == "systemd"

    def test_running_but_no_heartbeat(self):
        """running=true but no heartbeat → healthy=false, collect_status=error."""
        status = _fresh_status()
        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = True
        mock_conn.state = ConnectionState.CONNECTED
        mock_conn.last_error = ""

        deployer_info = {"deployed": True, "running": True, "running_confidence": "high", "running_source": "systemd"}
        # Ensure no heartbeat for this array
        _heartbeat_store.pop("arr-001", None)

        result = build_runtime_status(
            status, ssh_conn=mock_conn, deployer_info=deployer_info, probe_mode="strict"
        )
        assert result.agent_running is True
        assert result.agent_healthy is False
        assert result.collect_status == "error"

    def test_running_with_fresh_heartbeat(self):
        """running=true + fresh heartbeat → healthy=true, collect_status=ok."""
        status = _fresh_status()
        record_heartbeat("arr-001", source="ingest")

        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = True
        mock_conn.state = ConnectionState.CONNECTED
        mock_conn.last_error = ""

        deployer_info = {"deployed": True, "running": True, "running_confidence": "high", "running_source": "systemd"}
        result = build_runtime_status(
            status, ssh_conn=mock_conn, deployer_info=deployer_info, probe_mode="strict"
        )
        assert result.agent_running is True
        assert result.agent_healthy is True
        assert result.collect_status == "ok"
        assert result.health_source == "ingest"

    def test_statuses_and_detail_use_same_fields(self):
        """Both /statuses and /{id}/status should produce the same field set."""
        status = _fresh_status()
        build_runtime_status(status, ssh_conn=None, probe_mode="cached")
        data = status.model_dump()
        required_fields = [
            "state", "transport_connected", "agent_running", "agent_healthy",
            "collect_status", "running_confidence", "running_source",
            "health_source", "last_heartbeat_at", "status_version", "updated_at",
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# 2. systemd active but MainPID invalid → not running
# ---------------------------------------------------------------------------

class TestSystemdMainPidInvalid:
    """systemd reports active but MainPID=0 or process dead → running=false."""

    def test_mainpid_zero(self):
        deployer, conn = _make_deployer()
        conn.execute.side_effect = _cmd_router({
            "/run/systemd/system": (0, "", ""),
            "systemctl show": (0, "ActiveState=active\nSubState=running\nMainPID=0\n", ""),
            f"cat {AGENT_PID_FILE}": (1, "", ""),
            "pgrep": (1, "", ""),
        })
        assert deployer.check_running() is False

    def test_mainpid_dead_process(self):
        deployer, conn = _make_deployer()
        conn.execute.side_effect = _cmd_router({
            "/run/systemd/system": (0, "", ""),
            "systemctl show": (0, "ActiveState=active\nSubState=running\nMainPID=9999\n", ""),
            "kill -0": (0, "", ""),  # not alive (no "alive" in output)
            f"cat {AGENT_PID_FILE}": (1, "", ""),
            "pgrep": (1, "", ""),
        })
        assert deployer.check_running() is False

    def test_mainpid_alive_but_wrong_cmdline(self):
        deployer, conn = _make_deployer()
        conn.execute.side_effect = _cmd_router({
            "/run/systemd/system": (0, "", ""),
            "systemctl show": (0, "ActiveState=active\nSubState=running\nMainPID=5555\n", ""),
            "kill -0 5555": (0, "alive", ""),
            "/proc/5555/cmdline": (0, "java -jar some-other-service.jar", ""),
            f"cat {AGENT_PID_FILE}": (1, "", ""),
            "pgrep": (1, "", ""),
        })
        assert deployer.check_running() is False


# ---------------------------------------------------------------------------
# 3. PID file present but PID dead → stale_pidfile
# ---------------------------------------------------------------------------

class TestStalePidFile:
    """PID file exists but process is dead → detect stale."""

    def test_stale_pidfile_detected(self):
        deployer, conn = _make_deployer()
        conn.execute.side_effect = _cmd_router({
            "systemctl": (1, "", ""),
            f"cat {AGENT_PID_FILE}": (0, "8888\n", ""),
            "kill -0": (0, "", ""),  # not alive
            "/proc/": (1, "", ""),
            "pgrep": (1, "", ""),
        })
        diag = deployer._resolve_running_state()
        assert diag["running"] is False
        assert diag["pidfile_present"] is True
        assert diag["pidfile_stale"] is True
        assert diag["pidfile_pid"] == "8888"

    def test_pidfile_alive_wrong_cmdline(self):
        deployer, conn = _make_deployer()
        conn.execute.side_effect = _cmd_router({
            "systemctl": (1, "", ""),
            f"cat {AGENT_PID_FILE}": (0, "7777\n", ""),
            "kill -0 7777": (0, "alive", ""),
            "/proc/7777/cmdline": (0, "/usr/bin/nginx -g daemon off", ""),
            "pgrep": (1, "", ""),
        })
        diag = deployer._resolve_running_state()
        assert diag["running"] is False


# ---------------------------------------------------------------------------
# 4. pgrep fuzzy mismatch → not running
# ---------------------------------------------------------------------------

class TestPgrepFuzzyMismatch:
    """pgrep returns a hit but cmdline doesn't match agent."""

    def test_pgrep_wrong_process(self):
        deployer, conn = _make_deployer()
        conn.execute.side_effect = _cmd_router({
            "systemctl": (1, "", ""),
            f"cat {AGENT_PID_FILE}": (1, "", ""),
            "pgrep": (0, "4444 python some_other_script.py\n", ""),
        })
        assert deployer.check_running() is False

    def test_pgrep_empty_output(self):
        deployer, conn = _make_deployer()
        conn.execute.side_effect = _cmd_router({
            "systemctl": (1, "", ""),
            f"cat {AGENT_PID_FILE}": (1, "", ""),
            "pgrep": (0, "\n", ""),
        })
        assert deployer.check_running() is False


# ---------------------------------------------------------------------------
# 5. Process exists but no heartbeat → running=true, healthy=false
# ---------------------------------------------------------------------------

class TestRunningButUnhealthy:
    """Agent process exists but no recent heartbeat → unhealthy."""

    def test_running_no_heartbeat(self):
        status = _fresh_status("arr-unhealthy")
        _heartbeat_store.pop("arr-unhealthy", None)  # ensure no heartbeat

        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = True
        mock_conn.state = ConnectionState.CONNECTED
        mock_conn.last_error = ""

        deployer_info = {"deployed": True, "running": True, "running_confidence": "high", "running_source": "systemd"}
        result = build_runtime_status(
            status, ssh_conn=mock_conn, deployer_info=deployer_info, probe_mode="strict"
        )
        assert result.agent_running is True
        assert result.agent_healthy is False
        assert result.collect_status == "error"

    def test_running_stale_heartbeat(self):
        """Heartbeat older than HEALTHY_WINDOW → unhealthy."""
        _heartbeat_store["arr-stale"] = time.time() - HEALTHY_WINDOW_SECONDS - 10
        status = _fresh_status("arr-stale")

        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = True
        mock_conn.state = ConnectionState.CONNECTED
        mock_conn.last_error = ""

        deployer_info = {"deployed": True, "running": True, "running_confidence": "high", "running_source": "systemd"}
        result = build_runtime_status(
            status, ssh_conn=mock_conn, deployer_info=deployer_info, probe_mode="strict"
        )
        assert result.agent_running is True
        assert result.agent_healthy is False


# ---------------------------------------------------------------------------
# 6. Ingest without real array_id → rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestIngestArrayIdRequired:
    """Ingest must require real array_id; push_xxx IDs are rejected."""

    async def test_alert_without_array_id_rejected(self, app_client):
        """Alert with no array_id and no IP mapping → 400."""
        payload = {
            "type": "alert",
            "observer_name": "cpu_usage",
            "level": "warning",
            "message": "CPU high",
        }
        resp = await app_client.post("/api/ingest", json=payload)
        assert resp.status_code == 400
        assert "array_id" in resp.json()["detail"].lower() or "mapping" in resp.json()["detail"].lower()

    async def test_alert_with_push_xxx_rejected(self, app_client):
        """Alert with push_xxx pseudo ID → 400."""
        payload = {
            "type": "alert",
            "array_id": "push_10.0.0.1",
            "observer_name": "cpu_usage",
            "level": "warning",
            "message": "CPU high",
        }
        resp = await app_client.post("/api/ingest", json=payload)
        assert resp.status_code == 400
        assert "pseudo" in resp.json()["detail"].lower() or "push_" in resp.json()["detail"].lower()

    async def test_alert_with_real_array_id_accepted(self, app_client):
        """Alert with real array_id → 200."""
        mock_store = AsyncMock()
        mock_store.create_alert = AsyncMock()
        with patch("backend.api.websocket.broadcast_alert", new=AsyncMock()), \
             patch("backend.core.alert_store.get_alert_store", return_value=mock_store):
            payload = {
                "type": "alert",
                "array_id": "arr-real-001",
                "observer_name": "cpu_usage",
                "level": "warning",
                "message": "CPU high",
            }
            resp = await app_client.post("/api/ingest", json=payload)
        assert resp.status_code == 200
        assert resp.json()["array_id"] == "arr-real-001"

    async def test_alert_with_ip_mapping_accepted(self, app_client):
        """Alert without array_id but with IP mapping → resolved and accepted."""
        register_ip_array_mapping("127.0.0.1", "arr-mapped-001")
        mock_store = AsyncMock()
        mock_store.create_alert = AsyncMock()
        with patch("backend.api.websocket.broadcast_alert", new=AsyncMock()), \
             patch("backend.core.alert_store.get_alert_store", return_value=mock_store):
            payload = {
                "type": "alert",
                "observer_name": "disk",
                "level": "info",
                "message": "ok",
            }
            resp = await app_client.post("/api/ingest", json=payload)
        assert resp.status_code == 200
        assert resp.json()["array_id"] == "arr-mapped-001"


# ---------------------------------------------------------------------------
# 7. Recovery event clears stale failure state
# ---------------------------------------------------------------------------

class TestRecoveryEvent:
    """Recovery events should update heartbeat and refresh status cache."""

    def test_record_heartbeat_updates_health(self):
        _heartbeat_store.pop("arr-recover", None)
        assert is_agent_healthy("arr-recover") is False

        record_heartbeat("arr-recover", source="ingest")
        assert is_agent_healthy("arr-recover") is True
        assert get_last_heartbeat("arr-recover") is not None

    @pytest.mark.asyncio
    async def test_recovery_event_clears_failure(self):
        """on_recovery_event should recompute collect_status."""
        status = _fresh_status("arr-recovery-test")
        status.agent_running = True
        status.collect_status = "error"
        status.active_issues = []

        cache = {"arr-recovery-test": status}

        with patch("backend.api.websocket.broadcast_status_update", new=AsyncMock()):
            await on_recovery_event("arr-recovery-test", "heartbeat", status_cache=cache)

        # After recovery, heartbeat recorded → healthy
        assert is_agent_healthy("arr-recovery-test") is True
        # collect_status recomputed: running=true + healthy=true + no issues = ok
        assert status.collect_status == "ok"
        assert status.status_version >= 1

    def test_ip_array_mapping(self):
        register_ip_array_mapping("192.168.1.100", "arr-map-001")
        assert resolve_array_id_by_ip("192.168.1.100") == "arr-map-001"
        assert resolve_array_id_by_ip("192.168.1.999") is None

    def test_collect_status_degraded_with_error_issues(self):
        """running + healthy + error issues = degraded."""
        status = _fresh_status("arr-degraded")
        status.agent_running = True
        status.active_issues = [{"level": "error", "key": "test"}]
        record_heartbeat("arr-degraded", source="probe")

        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = True
        mock_conn.state = ConnectionState.CONNECTED
        mock_conn.last_error = ""

        deployer_info = {"deployed": True, "running": True, "running_confidence": "high", "running_source": "systemd"}
        build_runtime_status(status, ssh_conn=mock_conn, deployer_info=deployer_info)
        assert status.collect_status == "degraded"
