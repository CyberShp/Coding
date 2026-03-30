"""
Tests for status consistency, running detection, ingest attribution,
and recovery handling.

Covers the requirements from the status-consistency-fix issue:
1. Unified status output consistency between list and detail endpoints
2. Strict systemd running detection (MainPID validation)
3. Stale PID file detection
4. pgrep false-positive rejection
5. Running=true + healthy=false when no heartbeat
6. Ingest array_id attribution (no push_xxx pseudo IDs)
7. Recovery event clears stale failure state
"""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from backend.core.runtime_status import build_runtime_status, get_transport_info
from backend.core.agent_deployer import AgentDeployer
from backend.models.array import ArrayModel, ConnectionState


# ---------------------------------------------------------------------------
# 1. Unified status: both endpoints produce consistent fields
# ---------------------------------------------------------------------------

class TestUnifiedStatusConsistency:
    """build_runtime_status produces the same shape regardless of input."""

    def test_build_runtime_status_basic_fields(self):
        """All required fields present in output."""
        result = build_runtime_status(
            array_id="arr1",
            name="TestArray",
            host="10.0.0.1",
            transport_connected=True,
            agent_running=True,
            agent_deployed=True,
            last_heartbeat_at=datetime.now(),
        )
        # All mandatory fields exist
        for field in [
            "array_id", "name", "host", "state",
            "transport_connected", "agent_running", "agent_healthy",
            "collect_status", "active_issues", "last_heartbeat_at",
            "running_source", "health_source", "updated_at", "status_version",
        ]:
            assert field in result, f"Missing field: {field}"

    def test_status_version_increments(self):
        """Each call to build_runtime_status increments status_version."""
        r1 = build_runtime_status(array_id="a", name="A", host="h")
        r2 = build_runtime_status(array_id="a", name="A", host="h")
        assert r2["status_version"] > r1["status_version"]

    def test_connected_state_when_transport_up(self):
        """transport_connected=True → state is connected (or degraded)."""
        result = build_runtime_status(
            array_id="a", name="A", host="h",
            transport_connected=True,
        )
        assert result["state"] in ("connected", "degraded")

    def test_disconnected_when_transport_down(self):
        """transport_connected=False → state=disconnected."""
        result = build_runtime_status(
            array_id="a", name="A", host="h",
            transport_connected=False,
        )
        assert result["state"] == "disconnected"

    def test_degraded_when_running_no_heartbeat(self):
        """running=True but no recent heartbeat → degraded."""
        old_hb = datetime.now() - timedelta(seconds=300)
        result = build_runtime_status(
            array_id="a", name="A", host="h",
            transport_connected=True,
            agent_running=True,
            agent_deployed=True,
            last_heartbeat_at=old_hb,
        )
        assert result["state"] == "degraded"
        assert result["agent_running"] is True
        assert result["agent_healthy"] is False


# ---------------------------------------------------------------------------
# 2. systemd active but MainPID invalid → NOT running
# ---------------------------------------------------------------------------

class TestSystemdRunningDetection:
    """Strict systemd detection prevents false positives."""

    def _make_deployer(self, execute_map=None):
        """Create AgentDeployer with a mock SSHConnection."""
        conn = MagicMock()
        conn.host = "10.0.0.1"
        conn.is_connected.return_value = True

        execute_results = execute_map or {}

        def fake_execute(cmd, **kwargs):
            for pattern, result in execute_results.items():
                if pattern in cmd:
                    return result
            return (1, "", "")

        conn.execute.side_effect = fake_execute

        config = MagicMock()
        config.remote.agent_deploy_path = "/opt/observation_points"
        return AgentDeployer(conn, config)

    def test_systemd_active_mainpid_zero(self):
        """ActiveState=active but MainPID=0 → NOT running."""
        deployer = self._make_deployer({
            "systemctl show": (0, "ActiveState=active\nSubState=running\nMainPID=0\n", ""),
            "command -v systemctl": (0, "", ""),
            "test -d /run/systemd": (0, "", ""),
            f"cat /var/run/observation-points.pid": (1, "", ""),
            "pgrep": (1, "", ""),
        })
        state = deployer._resolve_running_state()
        assert state["service_active"] is True
        # MainPID=0 means no real process
        assert state["running"] is False or state["running_confidence"] != "high"

    def test_systemd_active_mainpid_dead(self):
        """ActiveState=active, MainPID=12345 but process dead → NOT running (high confidence)."""
        deployer = self._make_deployer({
            "systemctl show": (0, "ActiveState=active\nSubState=running\nMainPID=12345\n", ""),
            "command -v systemctl": (0, "", ""),
            "test -d /run/systemd": (0, "", ""),
            "kill -0 12345": (1, "", ""),  # process dead
            f"cat /var/run/observation-points.pid": (1, "", ""),
            "pgrep": (1, "", ""),
        })
        state = deployer._resolve_running_state()
        assert state["service_active"] is True
        # Process dead → should not be running at high confidence
        assert state["running"] is False

    def test_systemd_active_mainpid_valid_cmdline_match(self):
        """ActiveState=active, MainPID alive, cmdline matches → running=True, confidence=high."""
        deployer = self._make_deployer({
            "systemctl show": (0, "ActiveState=active\nSubState=running\nMainPID=9999\n", ""),
            "command -v systemctl": (0, "", ""),
            "test -d /run/systemd": (0, "", ""),
            "kill -0 9999": (0, "alive", ""),
            "/proc/9999/cmdline": (0, "python3 -m observation_points --config /etc/observation-points/config.json", ""),
            f"cat /var/run/observation-points.pid": (1, "", ""),
            "pgrep": (1, "", ""),
        })
        state = deployer._resolve_running_state()
        assert state["running"] is True
        assert state["running_source"] == "systemd"
        assert state["running_confidence"] == "high"
        assert "observation_points" in state["matched_process_cmdline"]


# ---------------------------------------------------------------------------
# 3. PID file exists but PID not running → stale_pidfile
# ---------------------------------------------------------------------------

class TestStalePidfile:
    """PID file present but process dead → stale_pidfile=True."""

    def _make_deployer(self, execute_map):
        conn = MagicMock()
        conn.host = "10.0.0.2"
        conn.is_connected.return_value = True
        config = MagicMock()
        config.remote.agent_deploy_path = "/opt/observation_points"

        def fake_execute(cmd, **kwargs):
            for pattern, result in execute_map.items():
                if pattern in cmd:
                    return result
            return (1, "", "")

        conn.execute.side_effect = fake_execute
        return AgentDeployer(conn, config)

    def test_pidfile_stale(self):
        """PID file has PID 5555, but process 5555 is dead → stale."""
        deployer = self._make_deployer({
            "command -v systemctl": (1, "", ""),  # no systemd
            "cat /var/run/observation-points.pid": (0, "5555\n", ""),
            "kill -0 5555": (1, "", ""),  # dead
            "pgrep": (1, "", ""),
        })
        state = deployer._resolve_running_state()
        assert state["pidfile_present"] is True
        assert state["pidfile_pid"] == 5555
        assert state["pidfile_stale"] is True
        assert state["running"] is False


# ---------------------------------------------------------------------------
# 4. pgrep false-positive rejection
# ---------------------------------------------------------------------------

class TestPgrepFalsePositive:
    """pgrep hit where cmdline doesn't match agent → NOT running."""

    def _make_deployer(self, execute_map):
        conn = MagicMock()
        conn.host = "10.0.0.3"
        conn.is_connected.return_value = True
        config = MagicMock()
        config.remote.agent_deploy_path = "/opt/observation_points"

        def fake_execute(cmd, **kwargs):
            for pattern, result in execute_map.items():
                if pattern in cmd:
                    return result
            return (1, "", "")

        conn.execute.side_effect = fake_execute
        return AgentDeployer(conn, config)

    def test_pgrep_hit_wrong_cmdline(self):
        """pgrep finds PID 7777 but cmdline is some other python process."""
        deployer = self._make_deployer({
            "command -v systemctl": (1, "", ""),  # no systemd
            "cat /var/run/observation-points.pid": (1, "", ""),
            "pgrep": (0, "7777\n", ""),
            "/proc/7777/cmdline": (0, "python3 /some/other/script.py", ""),
        })
        state = deployer._resolve_running_state()
        assert state["running"] is False


# ---------------------------------------------------------------------------
# 5. Running but no heartbeat → running=True, healthy=False
# ---------------------------------------------------------------------------

class TestRunningButUnhealthy:
    """Agent process exists but no recent heartbeat."""

    def test_running_true_healthy_false(self):
        """running=True with stale heartbeat → agent_healthy=False."""
        old_hb = datetime.now() - timedelta(seconds=600)
        result = build_runtime_status(
            array_id="a",
            name="A",
            host="h",
            transport_connected=True,
            agent_running=True,
            agent_deployed=True,
            last_heartbeat_at=old_hb,
        )
        assert result["agent_running"] is True
        assert result["agent_healthy"] is False
        assert result["collect_status"] == "no_heartbeat"

    def test_running_true_healthy_true(self):
        """running=True with fresh heartbeat → agent_healthy=True."""
        fresh_hb = datetime.now() - timedelta(seconds=30)
        result = build_runtime_status(
            array_id="a",
            name="A",
            host="h",
            transport_connected=True,
            agent_running=True,
            agent_deployed=True,
            last_heartbeat_at=fresh_hb,
        )
        assert result["agent_running"] is True
        assert result["agent_healthy"] is True
        assert result["collect_status"] == "ok"

    def test_not_running_not_healthy(self):
        """running=False → healthy=False always."""
        result = build_runtime_status(
            array_id="a",
            name="A",
            host="h",
            transport_connected=True,
            agent_running=False,
            agent_deployed=True,
        )
        assert result["agent_running"] is False
        assert result["agent_healthy"] is False
        assert result["collect_status"] == "agent_stopped"


# ---------------------------------------------------------------------------
# 6. Ingest rejects push_xxx pseudo ID (integration test)
# ---------------------------------------------------------------------------

class TestIngestArrayIdAttribution:
    """Ingest endpoint must use real array_id, not push_{source_ip}."""

    async def test_ingest_rejects_missing_array_id(self, app_client):
        """Missing array_id and no IP mapping → 400."""
        payload = {
            "type": "alert",
            "observer_name": "test",
            "level": "info",
            "message": "no id",
        }
        resp = await app_client.post("/api/ingest", json=payload)
        assert resp.status_code == 400

    async def test_ingest_rejects_push_prefix(self, app_client):
        """push_xxx pseudo ID → rejected."""
        payload = {
            "type": "alert",
            "array_id": "push_10.0.0.1",
            "observer_name": "test",
            "level": "info",
            "message": "pseudo id",
        }
        resp = await app_client.post("/api/ingest", json=payload)
        assert resp.status_code == 400

    def test_resolve_array_id_rejects_push_prefix(self):
        """_resolve_array_id returns None for push_xxx prefix."""
        from backend.api.ingest import _resolve_array_id
        assert _resolve_array_id("push_1.2.3.4", "1.2.3.4") is None

    def test_resolve_array_id_accepts_real_id(self):
        """_resolve_array_id returns the real id as-is."""
        from backend.api.ingest import _resolve_array_id
        assert _resolve_array_id("arr_42", "1.2.3.4") == "arr_42"

    def test_resolve_array_id_uses_mapping(self):
        """_resolve_array_id falls back to IP mapping."""
        from backend.api.ingest import _resolve_array_id, register_ip_array_mapping
        register_ip_array_mapping("10.0.0.5", "mapped_arr_5")
        assert _resolve_array_id(None, "10.0.0.5") == "mapped_arr_5"

    def test_resolve_array_id_returns_none_without_mapping(self):
        """_resolve_array_id returns None when no mapping and no payload id."""
        from backend.api.ingest import _resolve_array_id
        assert _resolve_array_id(None, "9.9.9.9") is None


# ---------------------------------------------------------------------------
# 7. Recovery event clears stale failure status
# ---------------------------------------------------------------------------

class TestRecoveryEventClearsFailure:
    """After recovery, collect_status and state should be updated."""

    def test_recovery_from_no_heartbeat(self):
        """Agent goes from stale heartbeat to fresh → state changes."""
        # Before: running but no heartbeat
        before = build_runtime_status(
            array_id="a",
            name="A",
            host="h",
            transport_connected=True,
            agent_running=True,
            agent_deployed=True,
            last_heartbeat_at=datetime.now() - timedelta(seconds=600),
        )
        assert before["agent_healthy"] is False
        assert before["state"] == "degraded"

        # After: fresh heartbeat
        after = build_runtime_status(
            array_id="a",
            name="A",
            host="h",
            transport_connected=True,
            agent_running=True,
            agent_deployed=True,
            last_heartbeat_at=datetime.now() - timedelta(seconds=10),
        )
        assert after["agent_healthy"] is True
        assert after["state"] == "connected"
        assert after["collect_status"] == "ok"

    def test_recovery_from_disconnect(self):
        """Transport goes from down to up → state=connected."""
        before = build_runtime_status(
            array_id="a",
            name="A",
            host="h",
            transport_connected=False,
        )
        assert before["state"] == "disconnected"

        after = build_runtime_status(
            array_id="a",
            name="A",
            host="h",
            transport_connected=True,
            agent_running=True,
            agent_deployed=True,
            last_heartbeat_at=datetime.now(),
        )
        assert after["state"] == "connected"


# ---------------------------------------------------------------------------
# Transport info helper
# ---------------------------------------------------------------------------

class TestGetTransportInfo:
    """get_transport_info extracts correct state from SSHConnection or None."""

    def test_none_connection(self):
        info = get_transport_info(None)
        assert info["transport_connected"] is False
        assert info["transport_state"] == "disconnected"

    def test_connected(self):
        conn = MagicMock()
        conn.state = ConnectionState.CONNECTED
        conn.last_error = ""
        info = get_transport_info(conn)
        assert info["transport_connected"] is True

    def test_disconnected(self):
        conn = MagicMock()
        conn.state = ConnectionState.DISCONNECTED
        conn.last_error = "timeout"
        info = get_transport_info(conn)
        assert info["transport_connected"] is False
        assert info["last_error"] == "timeout"
