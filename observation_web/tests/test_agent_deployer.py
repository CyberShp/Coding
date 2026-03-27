"""Tests for backend/core/agent_deployer.py — AgentDeployer."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.core.agent_deployer import AgentDeployer, AGENT_PID_FILE
from backend.config import AppConfig


class TestAgentDeployer:
    def _make_deployer(self, connected=True):
        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = connected
        mock_conn.host = "10.0.0.1"
        mock_conn.execute.return_value = (0, "", "")
        mock_conn.read_file.return_value = ""
        config = AppConfig()
        config.server.host = "backend.local"
        deployer = AgentDeployer(mock_conn, config)
        return deployer, mock_conn

    def test_check_deployed_when_connected(self):
        deployer, conn = self._make_deployer(True)
        conn.execute.return_value = (0, "main.py\n__init__.py\n", "")
        result = deployer.check_deployed()
        assert isinstance(result, bool)

    def test_check_deployed_when_disconnected(self):
        deployer, conn = self._make_deployer(False)
        try:
            deployer.check_deployed()
        except Exception:
            pass  # Expected

    def test_check_running_pid_file_exists(self):
        deployer, conn = self._make_deployer(True)
        conn.execute.return_value = (0, "12345\n", "")
        result = deployer.check_running()

    def test_check_running_no_pid_file(self):
        deployer, conn = self._make_deployer(True)
        conn.execute.side_effect = [(1, "", ""), (1, "", "No such file"), (1, "", "")]
        result = deployer.check_running()
        assert result is False

    def test_get_agent_status(self):
        deployer, conn = self._make_deployer(True)
        conn.execute.return_value = (0, "12345\n", "")
        status = deployer.get_agent_status()
        assert isinstance(status, dict)

    def test_stop_agent_no_process(self):
        deployer, conn = self._make_deployer(True)
        conn.execute.return_value = (1, "", "No such file")
        deployer.stop_agent()  # Should not raise

    def test_start_agent_not_connected(self):
        """BUG-MARKER: Starting agent without connection should fail cleanly."""
        deployer, conn = self._make_deployer(False)
        try:
            deployer.start_agent()
        except Exception:
            pass  # Expected

    @patch.object(AgentDeployer, "_build_package", return_value="/tmp/test.tar.gz")
    @patch("builtins.open")
    @patch("pathlib.Path.exists", return_value=False)
    def test_deploy_installs_systemd_service(self, _exists, mock_open, _build):
        deployer, conn = self._make_deployer(True)
        mock_open.return_value.__enter__.return_value.read.return_value = b"pkg"
        conn.upload_content.return_value = True

        result = deployer.deploy()

        assert result["ok"] is True
        commands = [call.args[0] for call in conn.execute.call_args_list]
        assert any("/etc/systemd/system/observation-points.service" in cmd for cmd in commands)
        assert any("backend.local" in cmd for cmd in commands)
        assert "systemctl daemon-reload" in commands
        assert "systemctl enable observation-points" in commands

    def test_start_agent_prefers_systemctl(self):
        deployer, conn = self._make_deployer(True)
        conn.execute.side_effect = lambda *args, **kwargs: (
            (0, "active\n", "")
            if args[0] == "systemctl is-active observation-points 2>/dev/null"
            else (0, "", "")
        )

        with patch.object(AgentDeployer, "stop_agent", return_value={"ok": True}):
            result = deployer.start_agent()

        assert result["ok"] is True
        commands = [call.args[0] for call in conn.execute.call_args_list]
        assert "systemctl start observation-points" in commands
        assert "systemctl is-active observation-points 2>/dev/null" in commands

    def test_stop_agent_prefers_systemctl(self):
        deployer, conn = self._make_deployer(True)
        conn.execute.side_effect = lambda *args, **kwargs: (0, "", "")

        result = deployer.stop_agent()

        assert result["ok"] is True
        commands = [call.args[0] for call in conn.execute.call_args_list]
        assert "systemctl stop observation-points" in commands

    @patch.object(AgentDeployer, "_build_package", return_value="/tmp/test.tar.gz")
    @patch("builtins.open")
    @patch("pathlib.Path.exists", return_value=False)
    def test_deploy_does_not_require_run_sh(self, _exists, mock_open, _build):
        deployer, conn = self._make_deployer(True)
        mock_open.return_value.__enter__.return_value.read.return_value = b"pkg"
        conn.upload_content.return_value = True

        result = deployer.deploy()

        assert result["ok"] is True
        commands = [call.args[0] for call in conn.execute.call_args_list]
        assert not any("run.sh" in cmd for cmd in commands)

    def test_validate_deploy_layout_requires_package_entrypoints(self):
        deployer, conn = self._make_deployer(True)
        conn.execute.return_value = (1, "", "missing")

        result = deployer._validate_deploy_layout("/OSM/coffer_data/observation_points")

        assert result["ok"] is False
        assert "package entrypoints" in result["error"]

    def test_start_agent_legacy_runs_module_from_parent_directory(self):
        deployer, conn = self._make_deployer(True)
        conn.execute.side_effect = [
            (0, "1234\n", ""),  # start script
            (0, "alive\n", ""),  # wait_for_process
            (0, "", ""),  # write pid file
            (0, "", ""),  # read start log
        ]

        result = deployer._start_agent_legacy()

        assert result["ok"] is True
        commands = [call.args[0] for call in conn.execute.call_args_list]
        start_cmd = next(cmd for cmd in commands if "nohup" in cmd)
        assert "cd /OSM/coffer_data &&" in start_cmd
        assert "-m observation_points" in start_cmd

    @pytest.mark.asyncio
    async def test_wait_for_ready_polls_until_service_active(self):
        deployer, conn = self._make_deployer(True)
        conn.execute.side_effect = [
            (0, "", ""),
            (3, "inactive\n", ""),
            (0, "active\n", ""),
        ]

        with patch("backend.core.agent_deployer.asyncio.sleep", new=AsyncMock()) as sleep_mock:
            ready = await deployer.wait_for_ready(timeout=60, interval=5)

        assert ready is True
        assert conn.execute.call_count == 3
        sleep_mock.assert_awaited_once_with(5)


class TestDeployServiceInstallWarning:
    """Regression: deploy() must not fail when _install_systemd_service() fails."""

    def _make_deployer(self, connected=True):
        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = connected
        mock_conn.host = "10.0.0.1"
        mock_conn.execute.return_value = (0, "", "")
        mock_conn.upload_content.return_value = True
        config = AppConfig()
        config.server.host = "backend.local"
        return AgentDeployer(mock_conn, config), mock_conn

    @patch.object(AgentDeployer, "_build_package", return_value="/tmp/test.tar.gz")
    @patch("builtins.open")
    @patch("pathlib.Path.exists", return_value=False)
    def test_deploy_success_even_if_service_install_warns(self, _exists, mock_open, _build):
        """deploy() returns ok=true, deployed=true, service_installed=false when
        _install_systemd_service() fails but upload/extract/layout succeeded."""
        deployer, conn = self._make_deployer(True)
        mock_open.return_value.__enter__.return_value.read.return_value = b"pkg"

        original_install = deployer._install_systemd_service

        def fail_service_install():
            return {"ok": False, "error": "systemctl daemon-reload failed"}

        with patch.object(deployer, "_install_systemd_service", side_effect=fail_service_install):
            result = deployer.deploy()

        assert result["ok"] is True
        assert result["deployed"] is True
        assert result["service_installed"] is False
        assert "warnings" in result
        assert any("daemon-reload" in w for w in result["warnings"])


class TestUnifiedRunningState:
    """Regression: check_running() and get_agent_status() must share the same
    3-layer detection logic (_resolve_running_state)."""

    def _make_deployer(self):
        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = True
        mock_conn.host = "10.0.0.1"
        config = AppConfig()
        return AgentDeployer(mock_conn, config), mock_conn

    def test_running_when_systemd_active_but_pidfile_missing(self):
        """systemd reports active → running=true even if PID file is absent."""
        deployer, conn = self._make_deployer()

        def execute_side_effect(cmd, **kw):
            if "systemctl" in cmd and "is-active" in cmd:
                return (0, "active\n", "")
            if "systemctl show" in cmd:
                return (0, "4567\n", "")
            if "test -d /run/systemd/system" in cmd or "command -v systemctl" in cmd:
                return (0, "", "")
            if AGENT_PID_FILE in cmd and "cat" in cmd:
                return (1, "", "No such file")
            return (0, "", "")

        conn.execute.side_effect = execute_side_effect
        status = deployer.get_agent_status()
        assert status["running"] is True
        assert status["running_source"] == "systemd"
        # check_running must agree
        conn.execute.side_effect = execute_side_effect
        assert deployer.check_running() is True

    def test_running_when_pidfile_missing_but_pgrep_hits(self):
        """PID file missing, systemd inactive, but pgrep finds the process."""
        deployer, conn = self._make_deployer()

        def execute_side_effect(cmd, **kw):
            if "systemctl" in cmd and "is-active" in cmd:
                return (3, "inactive\n", "")
            if "test -d /run/systemd/system" in cmd or "command -v systemctl" in cmd:
                return (0, "", "")
            if AGENT_PID_FILE in cmd and "cat" in cmd:
                return (1, "", "No such file")
            if "pgrep" in cmd:
                return (0, "9999\n", "")
            return (0, "", "")

        conn.execute.side_effect = execute_side_effect
        status = deployer.get_agent_status()
        assert status["running"] is True
        assert status["running_source"] == "pgrep"
        assert status["pid"] == 9999

    def test_not_running_when_all_checks_fail(self):
        """systemd inactive, PID file missing, pgrep empty → not running."""
        deployer, conn = self._make_deployer()

        def execute_side_effect(cmd, **kw):
            if "systemctl" in cmd and "is-active" in cmd:
                return (3, "inactive\n", "")
            if "test -d /run/systemd/system" in cmd or "command -v systemctl" in cmd:
                return (0, "", "")
            if AGENT_PID_FILE in cmd and "cat" in cmd:
                return (1, "", "No such file")
            if "pgrep" in cmd:
                return (1, "", "")
            if "test -d" in cmd:
                return (1, "", "")
            return (0, "", "")

        conn.execute.side_effect = execute_side_effect
        status = deployer.get_agent_status()
        assert status["running"] is False
        assert status["running_source"] == "none"
        assert deployer.check_running() is False

    @pytest.mark.parametrize("scenario,systemd_active,pid_alive,pgrep_hit,expected_running", [
        ("systemd_active_pid_missing",  True,  False, False, True),
        ("systemd_inactive_pid_alive",  False, True,  False, True),
        ("systemd_inactive_pid_stale_pgrep_hit", False, False, True, True),
        ("all_fail",                    False, False, False, False),
    ])
    def test_check_running_and_get_agent_status_are_consistent(
        self, scenario, systemd_active, pid_alive, pgrep_hit, expected_running
    ):
        """Parameterised: check_running() must equal get_agent_status()['running']."""
        deployer, conn = self._make_deployer()

        def execute_side_effect(cmd, **kw):
            if "command -v systemctl" in cmd or "test -d /run/systemd/system" in cmd:
                return (0, "", "")
            if "systemctl" in cmd and "is-active" in cmd:
                if systemd_active:
                    return (0, "active\n", "")
                return (3, "inactive\n", "")
            if "systemctl show" in cmd:
                return (0, "1234\n", "") if systemd_active else (1, "", "")
            if AGENT_PID_FILE in cmd and "cat" in cmd:
                if pid_alive:
                    return (0, "5678\n", "")
                return (1, "", "")
            if "kill -0" in cmd:
                if pid_alive:
                    return (0, "alive\n", "")
                return (1, "", "")
            if "pgrep" in cmd:
                if pgrep_hit:
                    return (0, "9999\n", "")
                return (1, "", "")
            if "test -d" in cmd:
                return (0, "deployed\n", "")
            return (0, "", "")

        conn.execute.side_effect = execute_side_effect
        cr = deployer.check_running()
        conn.execute.side_effect = execute_side_effect
        status = deployer.get_agent_status()

        assert cr == expected_running, f"check_running mismatch in {scenario}"
        assert status["running"] == expected_running, f"get_agent_status mismatch in {scenario}"
        assert cr == status["running"], f"Consistency mismatch in {scenario}"
