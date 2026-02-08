"""Tests for Registry."""

import pytest

from packet_storm.core.registry import Registry


class TestRegistry:
    """Test suite for Registry."""

    def test_register_and_get(self):
        """Register and retrieve a plugin."""
        reg = Registry("test")
        reg.register("foo", dict)
        assert reg.get("foo") is dict

    def test_get_unknown_returns_none(self):
        """Getting unregistered name returns None."""
        reg = Registry("test")
        assert reg.get("nonexistent") is None

    def test_create_instance(self):
        """Create an instance of a registered plugin."""
        reg = Registry("test")
        reg.register("list", list)
        instance = reg.create("list", [1, 2, 3])
        assert instance == [1, 2, 3]

    def test_create_unknown_raises(self):
        """Creating instance of unknown plugin raises KeyError."""
        reg = Registry("test")
        with pytest.raises(KeyError, match="Unknown test"):
            reg.create("nonexistent")

    def test_list_names(self):
        """List registered names."""
        reg = Registry("test")
        reg.register("beta", int)
        reg.register("alpha", str)
        assert reg.list_names() == ["alpha", "beta"]

    def test_list_all(self):
        """Get all registered entries."""
        reg = Registry("test")
        reg.register("a", int)
        reg.register("b", str)
        all_entries = reg.list_all()
        assert all_entries == {"a": int, "b": str}

    def test_contains(self):
        """Registry supports 'in' operator."""
        reg = Registry("test")
        reg.register("exists", dict)
        assert "exists" in reg
        assert "missing" not in reg

    def test_len(self):
        """Registry supports len()."""
        reg = Registry("test")
        assert len(reg) == 0
        reg.register("a", int)
        reg.register("b", str)
        assert len(reg) == 2

    def test_overwrite_warning(self):
        """Overwriting registration doesn't raise but overwrites."""
        reg = Registry("test")
        reg.register("x", int)
        reg.register("x", str)
        assert reg.get("x") is str
