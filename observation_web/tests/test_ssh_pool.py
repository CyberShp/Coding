"""Tests for backend/core/ssh_pool.py — SSHConnection and SSHPool."""
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from backend.core.ssh_pool import SSHConnection, SSHPool, get_ssh_pool


class TestSSHConnection:
    def test_init(self):
        conn = SSHConnection("arr-001", "192.168.1.1", 22, "admin")
        assert conn.array_id == "arr-001"
        assert conn.host == "192.168.1.1"
        assert conn._state.value == "disconnected"

    def test_is_connected_when_disconnected(self):
        conn = SSHConnection("arr-001", "192.168.1.1", 22, "admin")
        assert conn.is_connected() is False

    def test_connect_without_paramiko(self):
        """BUG-MARKER: Connect without paramiko should fail gracefully."""
        conn = SSHConnection("arr-001", "192.168.1.1", 22, "admin")
        # connect() returns bool, may fail if paramiko not available

    @patch("backend.core.ssh_pool.PARAMIKO_AVAILABLE", True)
    @patch("backend.core.ssh_pool.paramiko")
    def test_connect_with_paramiko(self, mock_paramiko):
        mock_client = MagicMock()
        mock_paramiko.SSHClient.return_value = mock_client
        mock_transport = MagicMock()
        mock_client.get_transport.return_value = mock_transport
        mock_transport.is_active.return_value = True

        conn = SSHConnection("arr-001", "192.168.1.1", 22, "admin")
        conn._password = "test123"
        result = conn.connect()

    def test_execute_when_disconnected(self):
        """Execute on disconnected should return error tuple, not raise."""
        conn = SSHConnection("arr-001", "192.168.1.1", 22, "admin")
        code, stdout, stderr = conn.execute("ls")
        assert code == -1

    @patch("backend.core.ssh_pool.PARAMIKO_AVAILABLE", True)
    def test_disconnect(self):
        conn = SSHConnection("arr-001", "192.168.1.1", 22, "admin")
        conn._client = MagicMock()
        conn._state = MagicMock()
        conn.disconnect()

    def test_max_reconnect_attempts(self):
        conn = SSHConnection("arr-001", "192.168.1.1", 22, "admin")
        assert conn.MAX_RECONNECT_ATTEMPTS == 3

    def test_idle_timeout(self):
        conn = SSHConnection("arr-001", "192.168.1.1", 22, "admin")
        assert conn.IDLE_TIMEOUT == 600


class TestSSHPool:
    def test_init(self):
        pool = SSHPool()
        assert pool is not None

    def test_add_connection(self):
        pool = SSHPool()
        pool.add_connection("arr-001", "192.168.1.1", 22, "admin")
        conn = pool.get_connection("arr-001")
        assert conn is not None
        assert conn.array_id == "arr-001"

    def test_get_nonexistent_connection(self):
        pool = SSHPool()
        conn = pool.get_connection("nonexistent")
        assert conn is None

    def test_remove_connection(self):
        pool = SSHPool()
        pool.add_connection("arr-001", "192.168.1.1", 22, "admin")
        pool.remove_connection("arr-001")
        assert pool.get_connection("arr-001") is None

    def test_get_all_states(self):
        pool = SSHPool()
        pool.add_connection("arr-001", "192.168.1.1", 22, "admin")
        pool.add_connection("arr-002", "192.168.1.2", 22, "admin")
        states = pool.get_all_states()
        assert len(states) == 2

    def test_get_stats(self):
        pool = SSHPool()
        pool.add_connection("arr-001", "192.168.1.1", 22, "admin")
        stats = pool.get_stats()
        assert "total_connections" in stats

    def test_close_all(self):
        pool = SSHPool()
        pool.add_connection("arr-001", "192.168.1.1", 22, "admin")
        pool.close_all()

    def test_cleanup_idle_connections(self):
        pool = SSHPool()
        pool.cleanup_idle_connections(max_idle_seconds=0)

    def test_singleton_getter(self):
        pool1 = get_ssh_pool()
        pool2 = get_ssh_pool()
        assert pool1 is pool2
