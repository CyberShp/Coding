"""Tests for core/base.py — BaseObserver, ObserverResult, AlertLevel."""
import pytest
from datetime import datetime
from observation_points.core.base import BaseObserver, ObserverResult, AlertLevel


# ---------- AlertLevel ----------

class TestAlertLevel:
    def test_enum_values(self):
        assert AlertLevel.INFO.value == "info"
        assert AlertLevel.WARNING.value == "warning"
        assert AlertLevel.ERROR.value == "error"
        assert AlertLevel.CRITICAL.value == "critical"

    def test_enum_count(self):
        assert len(AlertLevel) == 4


# ---------- ObserverResult ----------

class TestObserverResult:
    def test_default_fields(self):
        r = ObserverResult(observer_name="test", timestamp=datetime.now(),
                           has_alert=False, alert_level=AlertLevel.INFO,
                           message="ok", details={})
        assert r.raw_data is None
        assert r.sticky is False

    def test_to_dict_keys(self):
        r = ObserverResult(observer_name="test", timestamp=datetime.now(),
                           has_alert=True, alert_level=AlertLevel.ERROR,
                           message="err", details={"k": "v"}, raw_data="raw")
        d = r.to_dict()
        assert "observer_name" in d
        assert d["alert_level"] == "error"
        assert d["details"] == {"k": "v"}

    def test_to_dict_timestamp_iso(self):
        ts = datetime(2026, 1, 1, 12, 0, 0)
        r = ObserverResult(observer_name="t", timestamp=ts,
                           has_alert=False, alert_level=AlertLevel.INFO,
                           message="", details={})
        d = r.to_dict()
        assert "2026-01-01" in d["timestamp"]

    def test_sticky_default_false(self):
        r = ObserverResult(observer_name="t", timestamp=datetime.now(),
                           has_alert=True, alert_level=AlertLevel.WARNING,
                           message="", details={}, sticky=True)
        assert r.sticky is True


# ---------- BaseObserver (via concrete subclass) ----------

class DummyObserver(BaseObserver):
    def check(self):
        return self.create_result(has_alert=False, alert_level=AlertLevel.INFO,
                                  message="ok", details={})


class TestBaseObserver:
    def test_default_config(self):
        obs = DummyObserver("dummy", {})
        assert obs.is_enabled() is True
        assert obs.get_interval() == 30

    def test_custom_config(self):
        obs = DummyObserver("dummy", {"enabled": False, "interval": 10, "window_size": 3})
        assert obs.is_enabled() is False
        assert obs.get_interval() == 10

    def test_record_history_limits(self):
        obs = DummyObserver("dummy", {"window_size": 3})
        for i in range(10):
            obs.record_history({"val": i})
        assert len(obs.get_history()) == 3

    def test_calculate_average_empty(self):
        obs = DummyObserver("dummy", {})
        assert obs.calculate_average() is None

    def test_calculate_average_numeric(self):
        obs = DummyObserver("dummy", {})
        obs.record_history(10)
        obs.record_history(20)
        obs.record_history(30)
        assert obs.calculate_average() == 20.0

    def test_calculate_average_with_key(self):
        obs = DummyObserver("dummy", {})
        obs.record_history({"cpu": 10})
        obs.record_history({"cpu": 30})
        assert obs.calculate_average(key="cpu") == 20.0

    def test_calculate_average_non_numeric_filtered(self):
        obs = DummyObserver("dummy", {})
        obs.record_history("not_a_number")
        obs.record_history("also_not")
        assert obs.calculate_average() is None

    def test_detect_spike_no_history(self):
        obs = DummyObserver("dummy", {})
        is_spike, change = obs.detect_spike(100)
        assert is_spike is False
        assert change == 0.0

    def test_detect_spike_positive(self):
        obs = DummyObserver("dummy", {})
        obs.record_history(10)
        obs.record_history(10)
        is_spike, change = obs.detect_spike(20, threshold_percent=50)
        assert is_spike is True
        assert change == 100.0

    def test_detect_spike_negative_no_spike(self):
        obs = DummyObserver("dummy", {})
        obs.record_history(100)
        obs.record_history(100)
        is_spike, change = obs.detect_spike(110, threshold_percent=50)
        assert is_spike is False

    def test_get_delta_first_run(self):
        obs = DummyObserver("dummy", {})
        delta = obs.get_delta("counter", 100)
        assert delta == 100

    def test_get_delta_subsequent(self):
        obs = DummyObserver("dummy", {})
        obs.get_delta("counter", 100)
        delta = obs.get_delta("counter", 150)
        assert delta == 50

    def test_create_result(self):
        obs = DummyObserver("dummy", {})
        r = obs.check()
        assert isinstance(r, ObserverResult)
        assert r.observer_name == "dummy"
        assert r.has_alert is False

    def test_cleanup_no_error(self):
        obs = DummyObserver("dummy", {})
        obs.cleanup()
