"""Tests for backend/core/query_engine.py — QueryEngine pattern matching."""
import pytest
from backend.core.query_engine import QueryEngine
from backend.models.query import QueryRule, RuleType


class TestQueryEngine:
    def setup_method(self):
        self.engine = QueryEngine()

    def test_validate_pattern_valid(self):
        is_valid, msg = self.engine.validate_pattern(r"\d+")
        assert is_valid is True

    def test_validate_pattern_invalid(self):
        is_valid, msg = self.engine.validate_pattern(r"[invalid")
        assert is_valid is False
        assert len(msg) > 0

    def test_validate_pattern_empty(self):
        """FIXED: Empty pattern now correctly returns invalid."""
        is_valid, msg = self.engine.validate_pattern("")
        assert is_valid is False
        assert "empty" in msg.lower()

    def test_test_pattern_valid_match_found(self):
        result = self.engine.test_pattern(
            pattern=r"OK", test_text="Status: OK",
            rule_type=RuleType.VALID_MATCH, expect_match=True
        )
        assert result["is_normal"] is True

    def test_test_pattern_valid_match_not_found(self):
        result = self.engine.test_pattern(
            pattern=r"OK", test_text="Status: FAIL",
            rule_type=RuleType.VALID_MATCH, expect_match=True
        )
        assert result["is_normal"] is False

    def test_test_pattern_invalid_match(self):
        result = self.engine.test_pattern(
            pattern=r"ERROR", test_text="Status: ERROR found",
            rule_type=RuleType.INVALID_MATCH, expect_match=False
        )
        assert result["valid"] is True

    def test_test_pattern_regex_extract(self):
        result = self.engine.test_pattern(
            pattern=r"cpu:\s*(\d+)%", test_text="cpu: 85%",
            rule_type=RuleType.REGEX_EXTRACT, expect_match=True
        )
        assert result["valid"] is True
        assert len(result["matches"]) > 0

    def test_test_pattern_invalid_regex(self):
        """BUG-CANDIDATE: Invalid regex should return valid=False."""
        result = self.engine.test_pattern(
            pattern=r"[invalid", test_text="test",
            rule_type=RuleType.VALID_MATCH, expect_match=True
        )
        assert result["valid"] is False

    def test_apply_rule_multiline(self):
        result = self.engine.test_pattern(
            pattern=r"OK", test_text="line1\nStatus: OK\nline3",
            rule_type=RuleType.VALID_MATCH, expect_match=True
        )
        assert result["is_normal"] is True

    def test_apply_rule_no_match(self):
        result = self.engine.test_pattern(
            pattern=r"NOTFOUND", test_text="some text",
            rule_type=RuleType.VALID_MATCH, expect_match=True
        )
        assert result["is_normal"] is False
