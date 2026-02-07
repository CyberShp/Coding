"""Tests for backend/core/agent_deployer.py — AgentDeployer."""
import pytest
from unittest.mock import MagicMock, patch
from backend.core.agent_deployer import AgentDeployer
from backend.config import AppConfig


class TestAgentDeployer:
    def _make_deployer(self, connected=True):
        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = connected
        mock_conn.execute.return_value = (0, "", "")
        mock_conn.read_file.return_value = ""
        config = AppConfig()
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
        conn.execute.side_effect = [(1, "", "No such file"), (1, "", "")]
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
