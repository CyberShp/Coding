"""Tests for ConfigManager."""

import json
import pytest
from pathlib import Path

from packet_storm.core.config import ConfigManager, ConfigError


class TestConfigManager:
    """Test suite for ConfigManager."""

    def test_load_default_config(self):
        """ConfigManager loads default config without user file."""
        mgr = ConfigManager()
        assert mgr.config is not None
        assert "network" in mgr.config
        assert "protocol" in mgr.config
        assert "transport" in mgr.config

    def test_get_by_key_path(self):
        """Get nested config values by dot-path."""
        mgr = ConfigManager()
        assert mgr.get("protocol.type") == "iscsi"
        assert mgr.get("network.src_ip") is not None
        assert mgr.get("nonexistent.key", "default") == "default"

    def test_set_value(self):
        """Set config values at runtime."""
        mgr = ConfigManager()
        mgr.set("network.src_ip", "10.0.0.1")
        assert mgr.get("network.src_ip") == "10.0.0.1"

    def test_set_nested_creates_path(self):
        """Set creates intermediate dict keys."""
        mgr = ConfigManager()
        mgr.set("custom.nested.value", 42)
        assert mgr.get("custom.nested.value") == 42

    def test_get_protocol_type(self):
        """Get active protocol type."""
        mgr = ConfigManager()
        assert mgr.get_protocol_type() == "iscsi"
        mgr.set("protocol.type", "nvmeof")
        assert mgr.get_protocol_type() == "nvmeof"

    def test_get_network_config(self):
        """Get network configuration section."""
        mgr = ConfigManager()
        net_cfg = mgr.get_network_config()
        assert isinstance(net_cfg, dict)
        assert "interface" in net_cfg

    def test_get_execution_config(self):
        """Get execution configuration section."""
        mgr = ConfigManager()
        exec_cfg = mgr.get_execution_config()
        assert isinstance(exec_cfg, dict)
        assert "interval_ms" in exec_cfg

    def test_export_import_config(self, tmp_path):
        """Export and import configuration files."""
        mgr = ConfigManager()
        mgr.set("network.src_ip", "172.16.0.1")

        export_file = str(tmp_path / "exported.json")
        mgr.export_config(export_file)

        assert Path(export_file).exists()

        # Import into new manager
        mgr2 = ConfigManager()
        mgr2.import_config(export_file)
        assert mgr2.get("network.src_ip") == "172.16.0.1"

    def test_deep_merge(self):
        """Deep merge preserves nested keys."""
        base = {"a": {"b": 1, "c": 2}, "d": 3}
        override = {"a": {"b": 10, "e": 5}}
        result = ConfigManager._deep_merge(base, override)
        assert result["a"]["b"] == 10
        assert result["a"]["c"] == 2
        assert result["a"]["e"] == 5
        assert result["d"] == 3

    def test_reload(self):
        """Reload configuration from files."""
        mgr = ConfigManager()
        mgr.set("network.src_ip", "changed")
        mgr.reload()
        # After reload, should revert to default
        assert mgr.get("network.src_ip") != "changed"

    def test_invalid_config_file(self, tmp_path):
        """Loading invalid JSON raises ConfigError."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json")
        with pytest.raises(Exception):
            ConfigManager(str(bad_file))
