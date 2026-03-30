"""State matrix tests for backend/core/agent_deployer.py.

These tests verify:
- Branch coverage for all detection layers (systemd, PID file, pgrep)
- State matrix: all combinations of systemd/pid/pgrep states
- Consistency: check_running() and get_agent_status()["running"] always agree
- Deploy semantics: partial success (warnings) vs total failure
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from backend.core.agent_deployer import (
    AgentDeployer,
    AGENT_PID_FILE,
    SYSTEMD_SERVICE_NAME,
)
from backend.config import AppConfig


# ---------------------------------------------------------------------------
# Helper: create a deployer with configurable mock SSH
# ---------------------------------------------------------------------------

def _make_deployer(connected=True):
    mock_conn = MagicMock()
    mock_conn.is_connected.return_value = connected
    mock_conn.host = "10.0.0.1"
    mock_conn.execute.return_value = (0, "", "")
    mock_conn.upload_content.return_value = True
    config = AppConfig()
    config.server.host = "backend.local"
    return AgentDeployer(mock_conn, config), mock_conn


def _cmd_router(responses: dict, default=(1, "", "")):
    """Return a side_effect callable that routes based on command substrings."""

    def _route(cmd, *args, **kwargs):
        for pattern, result in responses.items():
            if pattern in cmd:
                return result
        return default

    return _route


# ===================================================================
# A. Branch coverage tests
# ===================================================================


class TestSystemdAvailability:
    """Branch: systemd available / unavailable."""

    def test_systemd_available(self):
        deployer, conn = _make_deployer()
        conn.execute.return_value = (0, "", "")
        assert deployer._is_systemd_available() is True

    def test_systemd_unavailable(self):
        deployer, conn = _make_deployer()
        conn.execute.return_value = (1, "", "command not found")
        assert deployer._is_systemd_available() is False


class TestDaemonReload:
    """Branch: daemon-reload success / failure."""

    @patch.object(AgentDeployer, "_build_package", return_value="/tmp/test.tar.gz")
    @patch.object(AgentDeployer, "_upload_package", return_value=True)
    @patch("pathlib.Path.exists", return_value=False)
    def test_daemon_reload_success(self, _exists, _upload, _build):
        deployer, conn = _make_deployer()
        conn.execute.return_value = (0, "", "")
        result = deployer.deploy()
        assert result["ok"] is True
        cmds = [c.args[0] for c in conn.execute.call_args_list]
        assert "systemctl daemon-reload" in cmds

    @patch.object(AgentDeployer, "_build_package", return_value="/tmp/test.tar.gz")
    @patch.object(AgentDeployer, "_upload_package", return_value=True)
    @patch("pathlib.Path.exists", return_value=False)
    def test_daemon_reload_failure_produces_warning(self, _exists, _upload, _build):
        """daemon-reload failure is now a deploy warning, not failure."""
        deployer, conn = _make_deployer()
        conn.execute.side_effect = _cmd_router({
            "daemon-reload": (1, "", "daemon-reload failed"),
        }, default=(0, "", ""))
        result = deployer.deploy()
        # Deploy still succeeds, but with warnings
        assert result["ok"] is True
        assert "warnings" in result


class TestSystemdEnable:
    """Branch: systemctl enable success / failure."""

    @patch.object(AgentDeployer, "_build_package", return_value="/tmp/test.tar.gz")
    @patch.object(AgentDeployer, "_upload_package", return_value=True)
    @patch("pathlib.Path.exists", return_value=False)
    def test_enable_failure_produces_warning(self, _exists, _upload, _build):
        deployer, conn = _make_deployer()
        conn.execute.side_effect = _cmd_router({
            "systemctl enable": (1, "", "enable failed"),
        }, default=(0, "", ""))
        result = deployer.deploy()
        assert result["ok"] is True
        assert "warnings" in result


class TestPidFilePresence:
    """Branch: PID file exists / missing."""

    def test_pid_file_present_and_alive(self):
        deployer, conn = _make_deployer()
        conn.execute.side_effect = _cmd_router({
            "systemctl": (1, "", ""),              # systemd not running
            f"cat {AGENT_PID_FILE}": (0, "9999\n", ""),
            "kill -0": (0, "alive", ""),
        })
        assert deployer.check_running() is True

    def test_pid_file_missing(self):
        deployer, conn = _make_deployer()
        conn.execute.side_effect = _cmd_router({
            "systemctl": (1, "", ""),
            f"cat {AGENT_PID_FILE}": (1, "", "No such file"),
            "pgrep": (1, "", ""),
        })
        assert deployer.check_running() is False


class TestPidStale:
    """Branch: PID exists but process dead (stale PID)."""

    def test_stale_pid_falls_through_to_pgrep(self):
        deployer, conn = _make_deployer()
        conn.execute.side_effect = _cmd_router({
            "systemctl": (1, "", ""),
            f"cat {AGENT_PID_FILE}": (0, "9999\n", ""),
            "kill -0": (0, "", ""),                 # process not alive
            "pgrep": (0, "12345\n", ""),
        })
        assert deployer.check_running() is True

    def test_stale_pid_no_pgrep(self):
        deployer, conn = _make_deployer()
        conn.execute.side_effect = _cmd_router({
            "systemctl": (1, "", ""),
            f"cat {AGENT_PID_FILE}": (0, "9999\n", ""),
            "kill -0": (0, "", ""),                 # not alive
            "pgrep": (1, "", ""),
        })
        assert deployer.check_running() is False


class TestPgrepFallback:
    """Branch: pgrep hit / miss."""

    def test_pgrep_hit(self):
        deployer, conn = _make_deployer()
        conn.execute.side_effect = _cmd_router({
            "systemctl": (1, "", ""),
            f"cat {AGENT_PID_FILE}": (1, "", ""),
            "pgrep": (0, "7777\n", ""),
        })
        assert deployer.check_running() is True

    def test_pgrep_miss(self):
        deployer, conn = _make_deployer()
        conn.execute.side_effect = _cmd_router({
            "systemctl": (1, "", ""),
            f"cat {AGENT_PID_FILE}": (1, "", ""),
            "pgrep": (1, "", ""),
        })
        assert deployer.check_running() is False


# ===================================================================
# B. State matrix tests — all combos of (systemd, pid, pgrep)
# ===================================================================


class TestRunningStateMatrix:
    """Cross-product state matrix for running detection.

    Dimensions:
    - systemd: active / inactive
    - pid_file: present+alive / present+stale / missing
    - pgrep: hit / miss
    """

    @staticmethod
    def _setup(deployer, conn, systemd_active, pid_state, pgrep_hit):
        """Configure mock for a specific state combination."""

        def execute_side_effect(cmd, *args, **kwargs):
            # systemd is-active
            if "is-active" in cmd:
                if systemd_active:
                    return (0, "active\n", "")
                return (1, "inactive\n", "")
            # systemd availability
            if "systemctl" in cmd and "/run/systemd/system" in cmd:
                return (0, "", "")  # systemd is available
            # systemd show MainPID
            if "MainPID" in cmd:
                return (0, "5555\n", "") if systemd_active else (0, "0\n", "")
            # PID file read
            if f"cat {AGENT_PID_FILE}" in cmd:
                if pid_state == "alive":
                    return (0, "9999\n", "")
                elif pid_state == "stale":
                    return (0, "9999\n", "")
                return (1, "", "No such file")
            # Process alive check
            if "kill -0" in cmd:
                if pid_state == "alive":
                    return (0, "alive", "")
                return (0, "", "")  # not alive
            # pgrep
            if "pgrep" in cmd:
                if pgrep_hit:
                    return (0, "12345\n", "")
                return (1, "", "")
            # deploy check
            if "test -d" in cmd:
                return (0, "deployed", "")
            return (0, "", "")

        conn.execute.side_effect = execute_side_effect

    # ---- Scenario 1: systemd active + pid missing + pgrep miss ----
    def test_systemd_active_pid_missing_pgrep_miss(self):
        deployer, conn = _make_deployer()
        self._setup(deployer, conn, systemd_active=True, pid_state="missing", pgrep_hit=False)
        assert deployer.check_running() is True, "systemd active should be enough"

    # ---- Scenario 2: systemd inactive + pid alive + pgrep miss ----
    def test_systemd_inactive_pid_alive_pgrep_miss(self):
        deployer, conn = _make_deployer()
        self._setup(deployer, conn, systemd_active=False, pid_state="alive", pgrep_hit=False)
        assert deployer.check_running() is True, "live PID should be enough"

    # ---- Scenario 3: systemd inactive + pid stale + pgrep hit ----
    def test_systemd_inactive_pid_stale_pgrep_hit(self):
        deployer, conn = _make_deployer()
        self._setup(deployer, conn, systemd_active=False, pid_state="stale", pgrep_hit=True)
        assert deployer.check_running() is True, "pgrep should catch what stale PID misses"

    # ---- Scenario 4: systemd inactive + pid missing + pgrep miss ----
    def test_systemd_inactive_pid_missing_pgrep_miss(self):
        deployer, conn = _make_deployer()
        self._setup(deployer, conn, systemd_active=False, pid_state="missing", pgrep_hit=False)
        assert deployer.check_running() is False, "nothing running → false"

    # ---- Scenario 5: all layers active ----
    def test_all_active(self):
        deployer, conn = _make_deployer()
        self._setup(deployer, conn, systemd_active=True, pid_state="alive", pgrep_hit=True)
        assert deployer.check_running() is True

    # ---- Scenario 6: systemd active + pid stale ----
    def test_systemd_active_pid_stale(self):
        deployer, conn = _make_deployer()
        self._setup(deployer, conn, systemd_active=True, pid_state="stale", pgrep_hit=False)
        assert deployer.check_running() is True, "systemd active takes priority"


# ===================================================================
# C. Consistency tests — check_running() == get_agent_status()["running"]
# ===================================================================


class TestRunningConsistency:
    """For every state combination, check_running() and
    get_agent_status()['running'] must agree.
    """

    @staticmethod
    def _setup(deployer, conn, systemd_active, pid_state, pgrep_hit):
        TestRunningStateMatrix._setup(deployer, conn, systemd_active, pid_state, pgrep_hit)

    COMBOS = [
        (True, "alive", True),
        (True, "alive", False),
        (True, "stale", True),
        (True, "stale", False),
        (True, "missing", True),
        (True, "missing", False),
        (False, "alive", True),
        (False, "alive", False),
        (False, "stale", True),
        (False, "stale", False),
        (False, "missing", True),
        (False, "missing", False),
    ]

    @pytest.mark.parametrize("systemd_active,pid_state,pgrep_hit", COMBOS)
    def test_check_running_matches_get_agent_status(
        self, systemd_active, pid_state, pgrep_hit
    ):
        deployer, conn = _make_deployer()
        self._setup(deployer, conn, systemd_active, pid_state, pgrep_hit)
        check_result = deployer.check_running()

        # Re-setup because the mock's side_effect is consumed
        self._setup(deployer, conn, systemd_active, pid_state, pgrep_hit)
        status_result = deployer.get_agent_status()

        assert check_result == status_result["running"], (
            f"Inconsistency! systemd={systemd_active} pid={pid_state} pgrep={pgrep_hit}: "
            f"check_running()={check_result} vs get_agent_status()['running']={status_result['running']}"
        )


# ===================================================================
# D. Deploy semantics tests
# ===================================================================


class TestDeploySemantics:
    """Deploy: distinguish full success, success-with-warnings, and real failure."""

    @patch.object(AgentDeployer, "_build_package", return_value="/tmp/test.tar.gz")
    @patch.object(AgentDeployer, "_upload_package", return_value=True)
    @patch("pathlib.Path.exists", return_value=False)
    def test_deploy_package_success_service_install_fail(self, _exists, _upload, _build):
        """Package deployed OK, but systemd install fails → ok=True with warnings."""
        deployer, conn = _make_deployer()
        conn.execute.side_effect = _cmd_router({
            "daemon-reload": (1, "", "daemon-reload failed"),
        }, default=(0, "", ""))
        result = deployer.deploy()
        assert result["ok"] is True
        assert "warnings" in result
        assert any("daemon-reload" in w or "Service install" in w for w in result["warnings"])

    @patch.object(AgentDeployer, "_build_package", return_value="/tmp/test.tar.gz")
    @patch.object(AgentDeployer, "_upload_package", return_value=False)
    @patch("pathlib.Path.exists", return_value=False)
    def test_deploy_package_fail_upload(self, _exists, _upload, _build):
        """Upload failure → ok=False, no ambiguity."""
        deployer, conn = _make_deployer()
        conn.execute.return_value = (0, "", "")
        result = deployer.deploy()
        assert result["ok"] is False
        assert "Upload" in result.get("error", "")

    @patch.object(AgentDeployer, "_build_package", return_value="/tmp/test.tar.gz")
    @patch.object(AgentDeployer, "_upload_package", return_value=True)
    @patch("pathlib.Path.exists", return_value=False)
    def test_deploy_extract_fail(self, _exists, _upload, _build):
        """Extract failure → ok=False."""
        deployer, conn = _make_deployer()
        conn.execute.side_effect = _cmd_router({
            "tar -xzf": (1, "", "tar: error"),
        }, default=(0, "", ""))
        result = deployer.deploy()
        assert result["ok"] is False
        assert "Extract" in result.get("error", "")

    @patch.object(AgentDeployer, "_build_package", return_value="/tmp/test.tar.gz")
    @patch.object(AgentDeployer, "_upload_package", return_value=True)
    @patch("pathlib.Path.exists", return_value=False)
    def test_deploy_layout_validation_fail(self, _exists, _upload, _build):
        """Layout validation failure → ok=False."""
        deployer, conn = _make_deployer()
        conn.execute.side_effect = _cmd_router({
            "test -f": (1, "", "missing entrypoints"),
        }, default=(0, "", ""))
        result = deployer.deploy()
        assert result["ok"] is False
        assert "entrypoints" in result.get("error", "").lower() or "validation" in result.get("error", "").lower()

    @patch.object(AgentDeployer, "_build_package", return_value="/tmp/test.tar.gz")
    @patch.object(AgentDeployer, "_upload_package", return_value=True)
    @patch("pathlib.Path.exists", return_value=False)
    def test_deploy_full_success_no_warnings(self, _exists, _upload, _build):
        """All steps succeed → ok=True, no warnings."""
        deployer, conn = _make_deployer()
        conn.execute.return_value = (0, "", "")
        result = deployer.deploy()
        assert result["ok"] is True
        assert result.get("warnings") is None or result.get("warnings") == []

    def test_deploy_not_connected(self):
        deployer, conn = _make_deployer(connected=False)
        result = deployer.deploy()
        assert result["ok"] is False
        assert "Not connected" in result.get("error", "")


# ===================================================================
# E. wait_for_ready tests
# ===================================================================


class TestWaitForReady:
    """Branch coverage for wait_for_ready async method."""

    @pytest.mark.asyncio
    async def test_wait_for_ready_immediate_active(self):
        deployer, conn = _make_deployer()
        conn.execute.side_effect = [
            (0, "", ""),  # _is_systemd_available
            (0, "active\n", ""),  # is-active check
        ]
        with patch("backend.core.agent_deployer.asyncio.sleep", new=AsyncMock()):
            ready = await deployer.wait_for_ready(timeout=10, interval=2)
        assert ready is True

    @pytest.mark.asyncio
    async def test_wait_for_ready_timeout(self):
        deployer, conn = _make_deployer()
        conn.execute.side_effect = [
            (0, "", ""),  # _is_systemd_available
            (1, "inactive\n", ""),  # is-active check
            (1, "inactive\n", ""),
            (1, "inactive\n", ""),
            (1, "inactive\n", ""),
            (1, "inactive\n", ""),
            (1, "inactive\n", ""),
        ]
        with patch("backend.core.agent_deployer.asyncio.sleep", new=AsyncMock()):
            ready = await deployer.wait_for_ready(timeout=6, interval=2)
        assert ready is False

    @pytest.mark.asyncio
    async def test_wait_for_ready_no_systemd(self):
        deployer, conn = _make_deployer()
        conn.execute.return_value = (1, "", "")
        with patch("backend.core.agent_deployer.asyncio.sleep", new=AsyncMock()):
            ready = await deployer.wait_for_ready(timeout=5, interval=1)
        assert ready is False


# ===================================================================
# F. Start agent branch coverage
# ===================================================================


class TestStartAgentBranches:
    """Branch coverage for start_agent and _start_agent_legacy."""

    def test_start_agent_not_connected(self):
        deployer, _ = _make_deployer(connected=False)
        result = deployer.start_agent()
        assert result["ok"] is False

    @patch.object(AgentDeployer, "stop_agent", return_value={"ok": True})
    @patch("backend.core.agent_deployer.time.sleep")
    def test_start_agent_legacy_success(self, _sleep, _stop):
        deployer, conn = _make_deployer()
        # _start_agent_legacy doesn't check systemd, it's called as fallback
        conn.execute.side_effect = [
            (0, "8888\n", ""),  # start script → PID
            (0, "alive\n", ""),  # process alive check
            (0, "", ""),  # write PID file
            (0, "warning: some module not found\n", ""),  # read start log
        ]
        result = deployer._start_agent_legacy()
        assert result["ok"] is True
        assert result["pid"] == 8888

    @patch.object(AgentDeployer, "stop_agent", return_value={"ok": True})
    @patch("backend.core.agent_deployer.time.sleep")
    def test_start_agent_legacy_process_dies(self, _sleep, _stop):
        deployer, conn = _make_deployer()
        conn.execute.side_effect = [
            (0, "8888\n", ""),  # start script → PID
            (0, "", ""),  # process NOT alive (no 'alive' in output)
            (0, "", ""),  # second alive check
            (0, "", ""),  # third
            (0, "", ""),  # fourth
            (0, "", ""),  # fifth
            (0, "", ""),  # sixth
            (0, "", ""),  # seventh
            (0, "", ""),  # eighth
            (0, "", ""),  # ninth
            (0, "", ""),  # tenth
            (0, "ImportError: no module named foo", ""),  # cat start log
        ]
        result = deployer._start_agent_legacy()
        assert result["ok"] is False

    @patch.object(AgentDeployer, "stop_agent", return_value={"ok": True})
    @patch("backend.core.agent_deployer.time.sleep")
    def test_start_agent_legacy_no_pid(self, _sleep, _stop):
        deployer, conn = _make_deployer()
        conn.execute.side_effect = [
            (0, "\n", ""),  # start script → empty PID
        ]
        result = deployer._start_agent_legacy()
        assert result["ok"] is False
        assert "PID" in result.get("error", "")

    @patch.object(AgentDeployer, "stop_agent", return_value={"ok": True})
    @patch("backend.core.agent_deployer.time.sleep")
    def test_start_agent_legacy_with_startup_warnings(self, _sleep, _stop):
        deployer, conn = _make_deployer()
        conn.execute.side_effect = [
            (0, "8888\n", ""),
            (0, "alive\n", ""),
            (0, "", ""),  # write pid
            (0, "warning: some module not found\n", ""),  # start log
        ]
        result = deployer._start_agent_legacy()
        assert result["ok"] is True
        assert "warnings" in result
        assert len(result["warnings"]) >= 1
