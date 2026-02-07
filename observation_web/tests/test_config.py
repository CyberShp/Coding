"""Tests for backend/config.py — AppConfig."""
import json
import os
import tempfile
import pytest
from backend.config import AppConfig, get_config, DatabaseConfig, SSHConfig, ServerConfig


class TestAppConfig:
    def test_default_values(self):
        c = AppConfig()
        assert c.server.host == "0.0.0.0"
        assert c.server.port == 8000
        assert c.database.path == "observation_web.db"
        assert c.ssh.default_port == 22

    def test_load_missing_file(self):
        c = AppConfig()
        c.load()  # Should not crash with missing config file

    def test_save_and_load(self):
        """Config save/load round-trip."""
        c = AppConfig()
        c.server.port = 9999
        c.save()
        # Just verify it doesn't crash

    def test_singleton_getter(self):
        c1 = get_config()
        c2 = get_config()
        assert c1 is c2


class TestDatabaseConfig:
    def test_defaults(self):
        c = DatabaseConfig()
        assert c.path == "observation_web.db"
        assert c.echo is False


class TestSSHConfig:
    def test_defaults(self):
        c = SSHConfig()
        assert c.default_port == 22
        assert c.timeout == 10
        assert c.keepalive_interval == 30


class TestServerConfig:
    def test_defaults(self):
        c = ServerConfig()
        assert c.host == "0.0.0.0"
        assert c.debug is False
        assert "*" in c.cors_origins
