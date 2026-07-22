"""Unified-monitor canonical rule helpers (backend rule judging via QueryEngine)."""
import json

from backend.core.monitor_rule import (
    build_backend_rule_spec,
    evaluate_backend,
    query_template_to_backend_fields,
)


def test_build_backend_rule_spec_roundtrips():
    spec = json.loads(build_backend_rule_spec("valid_match", "OK", True, []))
    assert spec == {"rule_type": "valid_match", "pattern": "OK",
                    "expect_match": True, "extract_fields": []}


def test_valid_match_normal_when_pattern_present():
    spec = build_backend_rule_spec("valid_match", "OK", True)
    assert evaluate_backend(spec, "status: OK").is_normal is True
    assert evaluate_backend(spec, "status: FAIL").is_normal is False


def test_match_present_means_abnormal():
    # "seeing 'degraded' is abnormal" — the correct QueryEngine expression is
    # valid_match + expect_match=False (is_normal = has_match == expect_match).
    # (INVALID_MATCH has a counter-intuitive semantics; evaluate_backend stays
    # faithful to the engine, so migrated query rules behave exactly as before.)
    spec = build_backend_rule_spec("valid_match", "degraded|failed", False)
    assert evaluate_backend(spec, "md0 active").is_normal is True      # no match → normal
    assert evaluate_backend(spec, "md0 degraded").is_normal is False   # match → abnormal


def test_invalid_spec_does_not_raise():
    # garbage / None spec must not crash the scheduler
    assert evaluate_backend(None, "x") is not None
    assert evaluate_backend("{not json", "x") is not None


def test_query_template_to_backend_fields():
    class QT:
        commands = '["df -h", "cat /proc/mdstat"]'
        monitor_arrays = '["arr1", "arr2"]'
        monitor_interval = 120
        rule_type = "invalid_match"
        pattern = "degraded"
        expect_match = False
        extract_fields = "[]"

    fields = query_template_to_backend_fields(QT())
    assert fields["exec_location"] == "backend"
    assert json.loads(fields["commands_json"]) == ["df -h", "cat /proc/mdstat"]
    assert json.loads(fields["monitor_arrays"]) == ["arr1", "arr2"]
    assert fields["interval"] == 120
    assert json.loads(fields["rule_spec_json"])["rule_type"] == "invalid_match"
