"""Structured JSON log formatter (opt-in via OBSERVATION_LOG_FORMAT=json).

The plain-text formatter silently dropped `extra=` fields (array_id, event_type)
that several call sites pass; the JSON formatter surfaces them.
"""
import json
import logging

from backend.main import _JsonLogFormatter


def test_json_formatter_emits_valid_json_with_core_fields():
    rec = logging.LogRecord("obs.test", logging.WARNING, __file__, 10, "boom %s", ("x",), None)
    out = json.loads(_JsonLogFormatter().format(rec))
    assert out["level"] == "WARNING"
    assert out["logger"] == "obs.test"
    assert out["msg"] == "boom x"
    assert "ts" in out


def test_json_formatter_includes_extra_fields():
    rec = logging.LogRecord("obs.test", logging.INFO, __file__, 1, "synced", None, None)
    rec.array_id = "arr-42"
    rec.event_type = "alert_sync"
    out = json.loads(_JsonLogFormatter().format(rec))
    assert out["array_id"] == "arr-42"
    assert out["event_type"] == "alert_sync"


def test_json_formatter_handles_non_serializable_extra():
    rec = logging.LogRecord("obs.test", logging.INFO, __file__, 1, "x", None, None)
    rec.obj = object()  # not JSON-serializable → coerced to str, must not raise
    out = json.loads(_JsonLogFormatter().format(rec))
    assert isinstance(out["obj"], str)
