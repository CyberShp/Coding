"""Tests for backend/core/system_alert.py — SystemAlertStore."""
import pytest
from backend.core.system_alert import (
    SystemAlertStore, SystemAlert, AlertLevel,
    sys_info, sys_warning, sys_error, sys_critical,
    get_system_alert_store,
)


class TestSystemAlertStore:
    def test_add_and_get(self):
        store = SystemAlertStore()
        store.add(AlertLevel.ERROR, "test", "Error occurred", {"key": "val"})
        alerts = store.get_all()
        assert len(alerts) == 1
        assert alerts[0]["module"] == "test"

    def test_add_with_exception(self):
        store = SystemAlertStore()
        try:
            raise ValueError("test error")
        except Exception as e:
            store.add(AlertLevel.ERROR, "test", "Error", exception=e)
        alerts = store.get_all()
        assert len(alerts) == 1
        assert "traceback" in alerts[0]

    def test_max_alerts_limit(self):
        """MAX_ALERTS expanded to 2000; archiving triggers at 80% (1600)."""
        store = SystemAlertStore()
        for i in range(600):
            store.add(AlertLevel.INFO, "test", f"Alert {i}")
        alerts = store.get_all()
        assert len(alerts) <= store.MAX_ALERTS

    def test_filter_by_level(self):
        store = SystemAlertStore()
        store.add(AlertLevel.INFO, "test", "info")
        store.add(AlertLevel.ERROR, "test", "error")
        errors = store.get_all(level="error")
        assert all(a["level"] == "error" for a in errors)

    def test_filter_by_module(self):
        store = SystemAlertStore()
        store.add(AlertLevel.INFO, "ssh", "ssh alert")
        store.add(AlertLevel.INFO, "http", "http alert")
        ssh_alerts = store.get_all(module="ssh")
        assert all("ssh" in a["module"].lower() for a in ssh_alerts)

    def test_clear(self):
        store = SystemAlertStore()
        store.add(AlertLevel.INFO, "test", "alert")
        store.clear()
        assert len(store.get_all()) == 0

    def test_get_stats(self):
        store = SystemAlertStore()
        store.add(AlertLevel.INFO, "t", "a")
        store.add(AlertLevel.ERROR, "t", "b")
        store.add(AlertLevel.ERROR, "t", "c")
        stats = store.get_stats()
        assert stats["error"] == 2
        assert stats["info"] == 1

    def test_limit_param(self):
        store = SystemAlertStore()
        for i in range(10):
            store.add(AlertLevel.INFO, "t", f"alert {i}")
        limited = store.get_all(limit=5)
        assert len(limited) == 5


class TestConvenienceFunctions:
    def test_sys_info(self):
        sys_info("test", "info message")

    def test_sys_warning(self):
        sys_warning("test", "warning message")

    def test_sys_error(self):
        sys_error("test", "error message")

    def test_sys_critical(self):
        sys_critical("test", "critical message")


class TestSystemAlert:
    def test_to_dict(self):
        alert = SystemAlert(
            level=AlertLevel.ERROR, module="test",
            message="Error", details={"k": "v"}
        )
        d = alert.to_dict()
        assert d["level"] == "error"
        assert d["module"] == "test"
        assert "timestamp" in d
