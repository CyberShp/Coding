"""Tests for backend/config.py — AppConfig."""
import json
import os
import tempfile
from pathlib import Path
import pytest
from backend.config import AppConfig, get_config, DatabaseConfig, SSHConfig, ServerConfig


class TestAppConfig:
    def test_default_values(self):
        c = AppConfig()
        assert c.server.host == "0.0.0.0"
        assert c.server.port == 8002
        assert c.database.path == "observation_web.db"
        assert c.ssh.default_port == 22

    def test_load_missing_file(self):
        """Loading a non-existent config returns an all-defaults AppConfig."""
        missing = Path(tempfile.gettempdir()) / "observation_web_missing_config_xyz.json"
        if missing.exists():
            missing.unlink()

        c = AppConfig.load(missing)
        assert c.server.port == 8002
        assert c.server.host == "0.0.0.0"
        assert c.database.path == "observation_web.db"

    def test_save_and_load(self):
        """Config save/load round-trip (isolated temp file — never the real config.json)."""
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"

            c = AppConfig()
            c.server.port = 8002          # governance default; must survive round-trip
            c.server.host = "127.0.0.1"   # non-default, proves the round-trip is real
            c.save(path)
            assert path.exists()

            loaded = AppConfig.load(path)
            assert loaded.server.port == 8002
            assert loaded.server.host == "127.0.0.1"

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
