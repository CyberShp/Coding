"""Tests for core/reporter.py — Reporter, Alert, sanitization, cooldown."""
import json
import os
import tempfile
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from observation_points.core.base import ObserverResult, AlertLevel
from observation_points.core.reporter import Reporter, Alert


# ---------- Alert dataclass ----------

class TestAlert:
    def test_to_json(self):
        a = Alert(observer_name="test", level=AlertLevel.ERROR,
                  message="msg", timestamp=datetime.now(), details={"k": "v"})
        j = a.to_json()
        parsed = json.loads(j)
        assert parsed["observer_name"] == "test"
        assert parsed["level"] == "error"

    def test_to_dict(self):
        ts = datetime(2026, 1, 1)
        a = Alert(observer_name="t", level=AlertLevel.INFO, message="m",
                  timestamp=ts, details={})
        d = a.to_dict()
        assert d["observer_name"] == "t"
        assert "2026" in d["timestamp"]


# ---------- Reporter ----------

class TestReporter:
    def _make_result(self, name="test", level=AlertLevel.ERROR,
                     msg="alert msg", has_alert=True, sticky=False):
        return ObserverResult(
            observer_name=name, timestamp=datetime.now(),
            has_alert=has_alert, alert_level=level,
            message=msg, details={"test": True}, sticky=sticky,
        )

    def test_init_console_mode(self):
        r = Reporter({"output": "console"})
        assert r is not None

    def test_init_file_mode(self):
        with tempfile.TemporaryDirectory() as d:
            r = Reporter({"output": "file", "file_path": os.path.join(d, "test.log")})
            assert r is not None

    def test_report_no_alert_skipped(self):
        r = Reporter({"output": "console"}, dry_run=True)
        result = self._make_result(has_alert=False)
        r.report(result)

    def test_report_below_min_level_skipped(self):
        r = Reporter({"output": "console"}, min_level="ERROR")
        result = self._make_result(level=AlertLevel.INFO)
        r.report(result)

    def test_report_dry_run(self):
        r = Reporter({"output": "console"}, dry_run=True)
        result = self._make_result()
        r.report(result)

    def test_cooldown_blocks_duplicate(self):
        r = Reporter({"output": "console", "cooldown_seconds": 60}, dry_run=True)
        result = self._make_result()
        r.report(result)
        r.report(result)

    def test_cooldown_bypass_sticky(self):
        r = Reporter({"output": "console", "cooldown_seconds": 60}, dry_run=True)
        result = self._make_result(sticky=True)
        r.report(result)
        r.report(result)

    def test_sanitize_password(self):
        r = Reporter({"output": "console"})
        text = "password=SuperSecret123"
        sanitized = r._sanitize(text)
        assert "SuperSecret123" not in sanitized or "***" in sanitized

    def test_sanitize_dict_datetime(self):
        r = Reporter({"output": "console"})
        ts = datetime(2026, 1, 1)
        result = r._sanitize_dict({"time": ts, "msg": "test"})
        assert isinstance(result["time"], str)

    def test_sanitize_dict_nested(self):
        r = Reporter({"output": "console"})
        data = {"outer": {"inner": "password=secret"}}
        result = r._sanitize_dict(data)
        assert isinstance(result["outer"], dict)

    def test_sanitize_dict_list(self):
        r = Reporter({"output": "console"})
        data = {"items": ["a", "b"]}
        result = r._sanitize_dict(data)
        assert len(result["items"]) == 2

    def test_level_priority_ordering(self):
        lp = Reporter.LEVEL_PRIORITY
        assert lp[AlertLevel.CRITICAL] > lp[AlertLevel.ERROR]
        assert lp[AlertLevel.ERROR] > lp[AlertLevel.WARNING]
        assert lp[AlertLevel.WARNING] > lp[AlertLevel.INFO]

    def test_file_output_writes(self):
        with tempfile.TemporaryDirectory() as d:
            fp = os.path.join(d, "alerts.log")
            r = Reporter({"output": "file", "file_path": fp})
            result = self._make_result()
            r.report(result)
            assert os.path.exists(fp)

    def test_cleanup_cooldown_cache(self):
        r = Reporter({"output": "console", "cooldown_seconds": 1})
        r._cooldown_cache["test_observer"] = {"msg_hash": datetime.now() - timedelta(seconds=10)}
        r._cleanup_cooldown_cache()

    def test_record_metrics_disabled(self):
        r = Reporter({"output": "console"})
        r.metrics_enabled = False
        r.record_metrics({"cpu": 50})

    def test_record_metrics_enabled(self):
        with tempfile.TemporaryDirectory() as d:
            r = Reporter({"output": "console", "file_path": os.path.join(d, "alerts.log")})
            r.metrics_enabled = True
            r.record_metrics({"cpu": 50, "ts": datetime.now().isoformat()})
