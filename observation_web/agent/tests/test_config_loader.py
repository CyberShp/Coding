"""Tests for config/loader.py — ConfigLoader."""
import os
import json
import tempfile
import pytest
from observation_points.config.loader import ConfigLoader


class TestConfigLoader:
    def test_load_default_when_missing(self):
        config = ConfigLoader.load("/nonexistent/config.json")
        assert "global" in config or "reporter" in config

    def test_load_valid_json(self):
        data = {
            "global": {"check_interval": 10},
            "reporter": {"output": "console"},
            "observers": {}
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            fname = f.name
        try:
            config = ConfigLoader.load(fname)
            assert config["global"]["check_interval"] == 10
        finally:
            os.unlink(fname)

    def test_load_non_json_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("key: value")
            f.flush()
            fname = f.name
        try:
            config = ConfigLoader.load(fname)
            assert isinstance(config, dict)
        finally:
            os.unlink(fname)

    def test_load_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{invalid json}")
            f.flush()
            fname = f.name
        try:
            with pytest.raises(Exception):
                ConfigLoader.load(fname)
        finally:
            os.unlink(fname)

    def test_deep_merge(self):
        base = {"a": {"b": 1, "c": 2}, "d": 3}
        override = {"a": {"b": 10}, "e": 5}
        result = ConfigLoader._deep_merge(base, override)
        assert result["a"]["b"] == 10
        assert result["a"]["c"] == 2
        assert result["d"] == 3
        assert result["e"] == 5

    def test_validate_good_config(self):
        config = {
            "global": {"check_interval": 5, "subprocess_timeout": 10},
            "observers": {"test": {"interval": 5}}
        }
        errors = ConfigLoader.validate(config)
        assert len(errors) == 0

    def test_validate_bad_interval(self):
        config = {
            "global": {"check_interval": 0},
            "observers": {}
        }
        errors = ConfigLoader.validate(config)
        assert len(errors) > 0

    def test_validate_bad_observer_interval(self):
        config = {
            "global": {"check_interval": 5},
            "observers": {"test": {"interval": 0}}
        }
        errors = ConfigLoader.validate(config)
        assert len(errors) > 0

    def test_validate_observer_not_dict(self):
        config = {
            "global": {"check_interval": 5},
            "observers": {"test": "not_a_dict"}
        }
        errors = ConfigLoader.validate(config)
        assert len(errors) > 0

    def test_empty_json_uses_defaults(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{}")
            f.flush()
            fname = f.name
        try:
            config = ConfigLoader.load(fname)
            assert isinstance(config, dict)
        finally:
            os.unlink(fname)
