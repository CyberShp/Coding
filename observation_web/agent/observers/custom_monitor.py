"""
Custom monitor observer.

Executes user-defined commands and matches output (regex/jsonpath/contains/exit_code).
Deployed via admin monitor templates -> config.json custom_monitors.
"""

import json
import logging
import re
import time
from typing import Any, Dict, Optional

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command

logger = logging.getLogger(__name__)

# Optional jsonpath_ng for JSONPath matching
try:
    from jsonpath_ng import parse as jsonpath_parse
    HAS_JSONPATH = True
except ImportError:
    HAS_JSONPATH = False


def _level_from_str(s: str) -> AlertLevel:
    m = {"info": AlertLevel.INFO, "warning": AlertLevel.WARNING,
         "error": AlertLevel.ERROR, "critical": AlertLevel.CRITICAL}
    return m.get((s or "").lower(), AlertLevel.WARNING)


class CustomMonitorObserver(BaseObserver):
    """
    Custom monitor: run command, match output, optionally alert.

    Config (from custom_monitors item):
    - command, command_type (shell/curl), interval, timeout
    - match_type: regex | jsonpath | contains | exit_code
    - match_expression, match_condition (found/not_found/gt/lt/eq/ne), match_threshold
    - alert_level, alert_message_template, cooldown
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.command = config.get("command", "")
        self.command_type = config.get("command_type", "shell")
        self.timeout = config.get("timeout", 30)
        self.match_type = config.get("match_type", "regex")
        self.match_expression = config.get("match_expression", "")
        self.match_condition = config.get("match_condition", "found")
        self.match_threshold = config.get("match_threshold")
        self.alert_level = _level_from_str(config.get("alert_level", "warning"))
        self.alert_message_template = config.get("alert_message_template", "") or "{value}"
        self.cooldown = config.get("cooldown", 300)
        self._last_alert_time: Optional[float] = None

    def _run_command(self) -> tuple:
        """Run command, return (output_str, exit_code, error)."""
        cmd = self.command.strip()
        if not cmd:
            return "", -1, "Empty command"

        if self.command_type == "curl":
            ret, stdout, stderr = run_command(cmd, timeout=self.timeout, shell=True)
            return stdout or "", ret, stderr or ""
        else:
            ret, stdout, stderr = run_command(cmd, timeout=self.timeout, shell=True)
            return stdout or "", ret, stderr or ""

    def _extract_value(self, output: str) -> Optional[Any]:
        """Extract value based on match_type."""
        if self.match_type == "regex":
            if not self.match_expression:
                return None
            m = re.search(self.match_expression, output, re.DOTALL)
            return m.group(0) if m else None
        if self.match_type == "jsonpath":
            if not HAS_JSONPATH or not self.match_expression:
                return None
            try:
                data = json.loads(output)
                expr = jsonpath_parse(self.match_expression)
                matches = [m.value for m in expr.find(data)]
                return matches[0] if matches else None
            except (json.JSONDecodeError, Exception) as e:
                logger.debug("JSONPath parse error: %s", e)
                return None
        if self.match_type == "contains":
            if self.match_expression in output:
                return self.match_expression
            return None
        if self.match_type == "exit_code":
            return "exit_code"  # Handled separately
        return None

    def _check_condition(self, value: Any, exit_code: int) -> bool:
        """Check if condition is met (should alert)."""
        cond = self.match_condition
        if self.match_type == "exit_code":
            thresh = self.match_threshold
            try:
                expected = int(thresh) if thresh is not None else 0
            except (ValueError, TypeError):
                expected = 0
            if cond == "eq":
                return exit_code == expected
            if cond == "ne":
                return exit_code != expected
            return False

        if cond == "found":
            return value is not None
        if cond == "not_found":
            return value is None

        # gt/lt/eq/ne for numeric comparison
        thresh = self.match_threshold
        if thresh is None:
            return False
        try:
            v = float(value) if value is not None else 0
            t = float(thresh)
        except (ValueError, TypeError):
            return False
        if cond == "gt":
            return v > t
        if cond == "lt":
            return v < t
        if cond == "eq":
            return v == t
        if cond == "ne":
            return v != t
        return False

    def _render_message(self, value: Any, match_content: str, exit_code: int) -> str:
        """Render alert message from template."""
        tpl = self.alert_message_template or "{value}"
        return tpl.replace("{value}", str(value or "")).replace(
            "{command}", self.command
        ).replace("{match}", str(match_content or "")).replace(
            "{exit_code}", str(exit_code)
        )

    def check(self) -> ObserverResult:
        """Execute check."""
        if not self.command:
            return self.create_result(has_alert=False, message="No command configured")

        output, exit_code, stderr = self._run_command()
        value = self._extract_value(output) if self.match_type != "exit_code" else None

        if self.match_type == "exit_code":
            should_alert = self._check_condition(None, exit_code)
            match_content = str(exit_code)
        else:
            should_alert = self._check_condition(value, exit_code)
            match_content = str(value) if value is not None else ""

        if not should_alert:
            return self.create_result(
                has_alert=False,
                message=f"Custom monitor {self.name} OK",
                details={"command": self.command[:80], "output_preview": (output or "")[:200]},
            )

        # Cooldown
        now = time.time()
        if self._last_alert_time and (now - self._last_alert_time) < self.cooldown:
            return self.create_result(
                has_alert=False,
                message=f"Custom monitor {self.name} (cooldown)",
                details={"cooldown_remaining": int(self.cooldown - (now - self._last_alert_time))},
            )
        self._last_alert_time = now

        msg = self._render_message(value, match_content, exit_code)
        if not msg.strip():
            msg = f"Custom monitor {self.name}: condition {self.match_condition} met"

        return self.create_result(
            has_alert=True,
            alert_level=self.alert_level,
            message=msg,
            details={
                "command": self.command,
                "match_type": self.match_type,
                "match_expression": self.match_expression[:100],
                "value": str(value)[:200] if value is not None else None,
                "exit_code": exit_code,
                "output_preview": (output or "")[:500],
            },
        )
