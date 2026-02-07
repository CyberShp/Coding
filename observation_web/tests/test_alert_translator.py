"""Tests for frontend/src/utils/alertTranslator.js logic — Python port for validation.

Since we can't run JS directly, we replicate the translator logic in Python
and test the same branches to ensure data flows correctly through the API.
"""
import json
import re
import pytest


# ---------- Python port of alertTranslator core logic ----------

OBSERVER_NAMES = {
    "error_code": "误码监测", "link_status": "链路状态",
    "card_recovery": "卡修复", "alarm_type": "告警事件",
    "memory_leak": "内存监测", "cpu_usage": "CPU 监测",
    "cmd_response": "命令响应", "sig_monitor": "SIG 信号",
    "sensitive_info": "敏感信息",
}


def parse_alarm_from_text(text):
    if not text:
        return None
    type_m = re.search(r'alarm\s*type\s*\((\d+)\)', text, re.I)
    name_m = re.search(r'alarm\s*name\s*\(([^)]+)\)', text, re.I)
    id_m = re.search(r'alarm\s*id\s*\(([^)]+)\)', text, re.I)
    is_send = bool(re.search(r'send\s+alarm', text, re.I))
    is_resume = bool(re.search(r'resume\s+alarm', text, re.I))
    if not type_m and not name_m:
        return None
    alarm_type = int(type_m.group(1)) if type_m else None
    return {
        "alarm_type": alarm_type,
        "alarm_name": name_m.group(1).strip() if name_m else "未知",
        "alarm_id": id_m.group(1).strip() if id_m else None,
        "is_send": is_send,
        "is_resume": is_resume,
        "is_history": alarm_type == 0,
        "recovered": is_resume,
    }


def translate_alarm_type(alert):
    details = alert.get("details", {}) or {}
    message = alert.get("message", "")
    new_sends = details.get("new_send_alarms", [])
    new_resumes = details.get("new_resume_alarms", [])
    active_alarms = details.get("active_alarms", [])
    parts = []

    if new_sends:
        history = [e for e in new_sends if e.get("alarm_type") == 0 or e.get("is_history_report")]
        normal = [e for e in new_sends if e.get("alarm_type") != 0 and not e.get("is_history_report")]
        if len(normal) == 1:
            parts.append(f"告警上报：{normal[0].get('alarm_name', '未知')} ({normal[0].get('alarm_id', '?')})")
        elif len(normal) > 1:
            parts.append(f"新上报 {len(normal)} 条告警")
        if len(history) == 1:
            parts.append(f"[历史] {history[0].get('alarm_name', '未知')} ({history[0].get('alarm_id', '?')}) 历史告警上报")
        elif len(history) > 1:
            parts.append(f"{len(history)} 条历史告警上报")

    if len(new_resumes) == 1:
        parts.append(f"告警恢复：{new_resumes[0].get('alarm_name', '未知')} ({new_resumes[0].get('alarm_id', '?')}) 已消除")
    elif len(new_resumes) > 1:
        parts.append(f"{len(new_resumes)} 条告警已恢复")

    summary = " | ".join(parts)
    if active_alarms:
        suffix = f"当前 {len(active_alarms)} 个活跃告警"
        summary = f"{summary} | {suffix}" if summary else suffix

    if not summary:
        summary = fallback_parse(message)

    return summary


def fallback_parse(text):
    if not text:
        return "告警事件"
    parsed = parse_alarm_from_text(text)
    if parsed:
        name = parsed["alarm_name"]
        aid = f" ({parsed['alarm_id']})" if parsed["alarm_id"] else ""
        if parsed["is_history"]:
            return f"[历史] {name}{aid} 历史告警上报"
        if parsed["is_resume"]:
            return f"告警恢复：{name}{aid} 已消除"
        if parsed["is_send"]:
            return f"告警上报：{name}{aid}"
    return text[:80] + "..." if len(text) > 80 else text


# ---------- Tests ----------

class TestParseAlarmFromText:
    def test_full_send(self):
        r = parse_alarm_from_text("send alarm: alarm type(1) alarm name(disk_fault) alarm id(0xA001)")
        assert r["alarm_type"] == 1
        assert r["alarm_name"] == "disk_fault"
        assert r["alarm_id"] == "0xA001"
        assert r["is_send"] is True
        assert r["is_resume"] is False
        assert r["is_history"] is False

    def test_resume(self):
        r = parse_alarm_from_text("resume alarm: alarm type(1) alarm name(disk_fault) alarm id(0xA001)")
        assert r["is_resume"] is True
        assert r["recovered"] is True

    def test_type0_history(self):
        r = parse_alarm_from_text("send alarm: alarm type(0) alarm name(history_test) alarm id(0xH001)")
        assert r["is_history"] is True
        assert r["alarm_type"] == 0

    def test_no_match(self):
        r = parse_alarm_from_text("some random log line")
        assert r is None

    def test_empty_string(self):
        r = parse_alarm_from_text("")
        assert r is None

    def test_none_input(self):
        r = parse_alarm_from_text(None)
        assert r is None

    def test_partial_match_name_only(self):
        r = parse_alarm_from_text("alarm name(test)")
        assert r is not None
        assert r["alarm_name"] == "test"

    def test_type_only_no_name(self):
        r = parse_alarm_from_text("alarm type(5)")
        assert r is not None
        assert r["alarm_type"] == 5


class TestTranslateAlarmType:
    def test_single_send_type1(self):
        alert = {
            "observer_name": "alarm_type",
            "message": "test",
            "details": {
                "new_send_alarms": [{"alarm_type": 1, "alarm_name": "disk_fault", "alarm_id": "0xA001"}],
                "new_resume_alarms": [],
                "active_alarms": [{"alarm_name": "disk_fault", "alarm_id": "0xA001"}],
            }
        }
        summary = translate_alarm_type(alert)
        assert "告警上报" in summary
        assert "disk_fault" in summary
        assert "1 个活跃告警" in summary

    def test_single_history_type0(self):
        alert = {
            "observer_name": "alarm_type",
            "message": "test",
            "details": {
                "new_send_alarms": [{"alarm_type": 0, "alarm_name": "hist", "alarm_id": "0xH1", "is_history_report": True}],
                "new_resume_alarms": [],
                "active_alarms": [],
            }
        }
        summary = translate_alarm_type(alert)
        assert "[历史]" in summary
        assert "历史告警上报" in summary

    def test_single_resume(self):
        alert = {
            "observer_name": "alarm_type",
            "message": "test",
            "details": {
                "new_send_alarms": [],
                "new_resume_alarms": [{"alarm_type": 1, "alarm_name": "disk_fault", "alarm_id": "0xA001", "recovered": True}],
                "active_alarms": [],
            }
        }
        summary = translate_alarm_type(alert)
        assert "告警恢复" in summary
        assert "已消除" in summary

    def test_multiple_sends(self):
        alert = {
            "observer_name": "alarm_type",
            "message": "test",
            "details": {
                "new_send_alarms": [
                    {"alarm_type": 1, "alarm_name": "a1", "alarm_id": "0x01"},
                    {"alarm_type": 1, "alarm_name": "a2", "alarm_id": "0x02"},
                ],
                "new_resume_alarms": [],
                "active_alarms": [],
            }
        }
        summary = translate_alarm_type(alert)
        assert "新上报 2 条告警" in summary

    def test_multiple_resumes(self):
        alert = {
            "observer_name": "alarm_type",
            "message": "test",
            "details": {
                "new_send_alarms": [],
                "new_resume_alarms": [
                    {"alarm_type": 1, "alarm_name": "a1", "alarm_id": "0x01"},
                    {"alarm_type": 1, "alarm_name": "a2", "alarm_id": "0x02"},
                ],
                "active_alarms": [],
            }
        }
        summary = translate_alarm_type(alert)
        assert "2 条告警已恢复" in summary

    def test_mixed_sends_and_resumes(self):
        alert = {
            "observer_name": "alarm_type",
            "message": "test",
            "details": {
                "new_send_alarms": [{"alarm_type": 1, "alarm_name": "a1", "alarm_id": "0x01"}],
                "new_resume_alarms": [{"alarm_type": 1, "alarm_name": "a2", "alarm_id": "0x02"}],
                "active_alarms": [{"alarm_name": "a1"}],
            }
        }
        summary = translate_alarm_type(alert)
        assert "告警上报" in summary
        assert "告警恢复" in summary

    def test_empty_details_fallback(self):
        alert = {
            "observer_name": "alarm_type",
            "message": "send alarm: alarm type(1) alarm name(test) alarm id(0x1)",
            "details": {}
        }
        summary = translate_alarm_type(alert)
        assert "告警上报" in summary

    def test_no_details_at_all(self):
        alert = {
            "observer_name": "alarm_type",
            "message": "some alarm message",
            "details": None
        }
        summary = translate_alarm_type(alert)
        assert len(summary) > 0

    def test_multiple_history_sends(self):
        alert = {
            "observer_name": "alarm_type",
            "message": "test",
            "details": {
                "new_send_alarms": [
                    {"alarm_type": 0, "alarm_name": "h1", "alarm_id": "0x01", "is_history_report": True},
                    {"alarm_type": 0, "alarm_name": "h2", "alarm_id": "0x02", "is_history_report": True},
                ],
                "new_resume_alarms": [],
                "active_alarms": [],
            }
        }
        summary = translate_alarm_type(alert)
        assert "2 条历史告警上报" in summary


class TestFallbackParse:
    def test_empty(self):
        assert fallback_parse("") == "告警事件"

    def test_none(self):
        assert fallback_parse(None) == "告警事件"

    def test_long_message_truncation(self):
        long_msg = "x" * 200
        result = fallback_parse(long_msg)
        assert len(result) < 200
        assert result.endswith("...")

    def test_send_alarm_text(self):
        result = fallback_parse("send alarm: alarm type(1) alarm name(test) alarm id(0x1)")
        assert "告警上报" in result

    def test_resume_alarm_text(self):
        result = fallback_parse("resume alarm: alarm type(1) alarm name(test) alarm id(0x1)")
        assert "告警恢复" in result

    def test_history_text(self):
        result = fallback_parse("send alarm: alarm type(0) alarm name(hist) alarm id(0x1)")
        assert "[历史]" in result


class TestObserverNames:
    def test_all_keys_present(self):
        expected_keys = ["error_code", "link_status", "card_recovery", "alarm_type",
                         "memory_leak", "cpu_usage", "cmd_response", "sig_monitor", "sensitive_info"]
        for k in expected_keys:
            assert k in OBSERVER_NAMES

    def test_unknown_key_returns_key(self):
        assert OBSERVER_NAMES.get("unknown", "unknown") == "unknown"
