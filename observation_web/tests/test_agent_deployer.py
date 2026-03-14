"""Tests for backend/core/agent_deployer.py — AgentDeployer."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.core.agent_deployer import AgentDeployer
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
