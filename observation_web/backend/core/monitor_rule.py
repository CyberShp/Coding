"""Canonical rule handling for unified custom monitors.

Rule judging uses different engines per exec_location:
- agent  definitions are judged on the agent (v2 strategy engine)
- backend definitions are judged HERE via the existing QueryEngine, using a
  ``rule_spec_json`` (rule_type/pattern/expect_match/extract_fields).

This module does NOT reinvent the rule engine — it maps to/from QueryEngine.
"""
import json
from typing import Any, Dict, List, Optional


def build_backend_rule_spec(
    rule_type: str,
    pattern: str,
    expect_match: Optional[bool] = True,
    extract_fields: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Serialize a QueryEngine rule into the unified backend rule_spec_json."""
    return json.dumps(
        {
            "rule_type": rule_type or "valid_match",
            "pattern": pattern or "",
            "expect_match": True if expect_match is None else bool(expect_match),
            "extract_fields": extract_fields or [],
        },
        ensure_ascii=False,
    )


def _safe_json_list(raw: Any) -> list:
    try:
        val = json.loads(raw) if raw else []
        return val if isinstance(val, list) else []
    except (ValueError, TypeError):
        return []


def query_template_to_backend_fields(qt) -> Dict[str, Any]:
    """Map a QueryTemplateModel (auto_monitor) to unified backend-definition fields.

    Used by the U3 migration to fold query auto-monitors into monitor_templates
    as exec_location=backend definitions.
    """
    return {
        "exec_location": "backend",
        "commands_json": json.dumps(_safe_json_list(qt.commands), ensure_ascii=False),
        "monitor_arrays": json.dumps(_safe_json_list(qt.monitor_arrays), ensure_ascii=False),
        "interval": qt.monitor_interval or 300,
        "rule_spec_json": build_backend_rule_spec(
            qt.rule_type, qt.pattern, qt.expect_match, _safe_json_list(qt.extract_fields)
        ),
    }


def evaluate_backend(rule_spec_json: Optional[str], output: str):
    """Judge command output for a backend definition via QueryEngine.

    Returns a MatchResult (is_normal / matched_values / extracted_fields).
    Missing/invalid spec → treated as a bare presence rule (normal unless empty).
    """
    from .query_engine import QueryEngine
    from ..models.query import QueryRule, RuleType, ExtractField

    spec: Dict[str, Any] = {}
    if rule_spec_json:
        try:
            loaded = json.loads(rule_spec_json)
            if isinstance(loaded, dict):
                spec = loaded
        except (ValueError, TypeError):
            spec = {}

    try:
        rule_type = RuleType(spec.get("rule_type", "valid_match"))
    except ValueError:
        rule_type = RuleType.VALID_MATCH

    fields = []
    for f in spec.get("extract_fields", []):
        if isinstance(f, dict) and "name" in f and "pattern" in f:
            fields.append(ExtractField(name=f["name"], pattern=f["pattern"]))

    rule = QueryRule(
        rule_type=rule_type,
        pattern=spec.get("pattern", ""),
        expect_match=spec.get("expect_match", True),
        extract_fields=fields,
    )
    return QueryEngine()._apply_rule(output or "", rule)
