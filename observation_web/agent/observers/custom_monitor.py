"""
Custom monitor observer — v2.

Execution: user-defined shell/curl commands.
Extraction: 6 strategies (pipe/kv/json/table/lines/diff) via ExtractionEngine.
Backward compat: v1 configs (match_type/match_expression) auto-convert to v2 strategy.
Deployed via admin monitor templates -> config.json custom_monitors.
"""

import json
import logging
import re
import time
from typing import Any, Dict, Optional, Tuple

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..core.extraction import ExtractionEngine, ExtractionResult
from ..utils.helpers import run_command

logger = logging.getLogger(__name__)


def _level_from_str(s: str) -> AlertLevel:
    m = {"info": AlertLevel.INFO, "warning": AlertLevel.WARNING,
         "error": AlertLevel.ERROR, "critical": AlertLevel.CRITICAL}
    return m.get((s or "").lower(), AlertLevel.WARNING)


_V2_STRATEGIES = {"pipe", "kv", "json", "table", "lines", "diff", "exit_code"}


def _v1_to_v2_strategy(match_type: str, match_expression: str) -> Tuple[str, Dict]:
    """Auto-convert v1 match_type/match_expression to v2 strategy + strategy_config.

    If match_type is already a v2 strategy name (saved by the Phase 3 template
    builder), decode match_expression as JSON strategy_config and pass through.
    """
    # v2 passthrough: template builder stores strategy name in match_type
    if match_type in _V2_STRATEGIES:
        try:
            cfg = json.loads(match_expression) if match_expression else {}
            if not isinstance(cfg, dict):
                cfg = {}
        except (json.JSONDecodeError, TypeError, ValueError):
            cfg = {}
        return match_type, cfg

    # v1 legacy mappings
    if match_type == "regex":
        return "lines", {"pattern": match_expression, "mode": "first"}
    if match_type == "jsonpath":
        return "json", {"path": match_expression}
    if match_type == "contains":
        return "lines", {"pattern": re.escape(match_expression), "mode": "count"}
    if match_type == "exit_code":
        # exit_code is handled outside extraction engine
        return "exit_code", {}
    return "lines", {"pattern": match_expression or ".", "mode": "first"}


class CustomMonitorObserver(BaseObserver):
    """
    Custom monitor — v2.

    Config (from custom_monitors item):
    - command, command_type (shell/curl), interval, timeout

    v2 schema:
    - strategy: pipe | kv | json | table | lines | diff | exit_code
    - strategy_config: dict of strategy-specific options
    - consecutive_threshold: int, default 1 (alert after N consecutive triggers)
    - match_condition: found | not_found | gt | lt | eq | ne  (for numeric compare)
    - match_threshold: numeric threshold for gt/lt/eq/ne
    - alert_level, alert_message_template, cooldown

    v1 compat (auto-converted):
    - match_type → strategy
    - match_expression → strategy_config
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.command = config.get("command", "")
        self.command_type = config.get("command_type", "shell")
        self.timeout = config.get("timeout", 30)

        # v2 strategy resolution (with v1 backward compat)
        if "strategy" in config:
            self.strategy: str = config["strategy"]
            self.strategy_config: Dict = config.get("strategy_config") or {}
        else:
            # v1 → v2 auto-convert
            mt = config.get("match_type", "regex")
            me = config.get("match_expression", "")
            self.strategy, self.strategy_config = _v1_to_v2_strategy(mt, me)

        # Condition evaluation
        self.match_condition: str = config.get("match_condition", "found")
        self.match_threshold: Optional[str] = config.get("match_threshold")

        # Alert settings
        self.alert_level = _level_from_str(config.get("alert_level", "warning"))
        self.alert_message_template = config.get("alert_message_template", "") or "{value}"
        self.cooldown = config.get("cooldown", 300)

        # Consecutive threshold — alert only after N consecutive hits
        self.consecutive_threshold: int = max(1, int(config.get("consecutive_threshold", 1)))
        self._consecutive_count: int = 0

        # Stateful extraction engine (owns diff-strategy previous-value store)
        self._engine = ExtractionEngine()
        self._last_alert_time: Optional[float] = None

    # ── Command execution ──────────────────────────────────────────────────

    def _run_command(self) -> Tuple[str, int, str]:
        """Run command, return (stdout, exit_code, stderr)."""
        cmd = self.command.strip()
        if not cmd:
            return "", -1, "Empty command"
        ret, stdout, stderr = run_command(cmd, timeout=self.timeout, shell=True)
        return stdout or "", ret, stderr or ""

    # ── Condition evaluation ───────────────────────────────────────────────

    def _check_condition(self, result: ExtractionResult, exit_code: int) -> bool:
        """Return True if the extraction result should trigger an alert."""
        cond = self.match_condition

        # exit_code strategy handled separately
        if self.strategy == "exit_code":
            thresh = self.match_threshold
            try:
                expected = int(thresh) if thresh is not None else 0
            except (ValueError, TypeError):
                expected = 0
            return exit_code == expected if cond == "eq" else (
                exit_code != expected if cond == "ne" else False
            )

        # diff strategy: use "triggered" from metadata
        if self.strategy == "diff":
            return result.metadata.get("triggered", False)

        # lines + count mode: value is an integer count
        value = result.value

        if cond == "found":
            # lines strategy returns an int count; treat count>0 as "found"
            # all other strategies: any non-None value (including 0) = found
            if self.strategy == "lines" and isinstance(value, int):
                return value > 0
            return value is not None
        if cond == "not_found":
            if self.strategy == "lines" and isinstance(value, int):
                return value == 0
            return value is None

        # gt/lt/eq/ne — numeric comparison
        thresh = self.match_threshold
        if thresh is None:
            return False
        try:
            v = float(value) if value is not None else 0
            t = float(thresh)
        except (ValueError, TypeError):
            return False
        return {"gt": v > t, "lt": v < t, "eq": v == t, "ne": v != t}.get(cond, False)

    # ── Message rendering ──────────────────────────────────────────────────

    def _render_message(self, result: ExtractionResult, exit_code: int) -> str:
        tpl = self.alert_message_template or "{value}"
        value = result.value
        old = result.metadata.get("previous", "")
        new = result.metadata.get("current", "")
        return (
            tpl
            .replace("{value}", str(value or ""))
            .replace("{command}", self.command)
            .replace("{exit_code}", str(exit_code))
            .replace("{old}", str(old or ""))
            .replace("{new}", str(new or ""))
        )

    # ── Public check ──────────────────────────────────────────────────────

    def check(self) -> ObserverResult:
        if not self.command:
            return self.create_result(has_alert=False, message="No command configured")

        output, exit_code, stderr = self._run_command()

        # Extract value
        if self.strategy == "exit_code":
            result = ExtractionResult(success=True, value=exit_code, raw_output=output[:500])
        else:
            result = self._engine.extract(self.strategy, output, self.strategy_config, state_key=self.name)

        should_alert = self._check_condition(result, exit_code)

        if should_alert:
            self._consecutive_count += 1
        else:
            self._consecutive_count = 0

        if not should_alert or self._consecutive_count < self.consecutive_threshold:
            return self.create_result(
                has_alert=False,
                message=f"Custom monitor {self.name} OK",
                details={
                    "command": self.command[:80],
                    "strategy": self.strategy,
                    "value": str(result.value)[:200] if result.value is not None else None,
                    "consecutive": self._consecutive_count,
                },
            )

        # Cooldown guard
        now = time.time()
        if self._last_alert_time and (now - self._last_alert_time) < self.cooldown:
            remaining = int(self.cooldown - (now - self._last_alert_time))
            return self.create_result(
                has_alert=False,
                message=f"Custom monitor {self.name} (cooldown {remaining}s)",
                details={"cooldown_remaining": remaining},
            )
        self._last_alert_time = now
        self._consecutive_count = 0  # reset after alert fires

        msg = self._render_message(result, exit_code)
        if not msg.strip():
            msg = f"Custom monitor {self.name}: condition {self.match_condition} met"

        return self.create_result(
            has_alert=True,
            alert_level=self.alert_level,
            message=msg,
            details={
                "command": self.command,
                "strategy": self.strategy,
                "value": str(result.value)[:200] if result.value is not None else None,
                "exit_code": exit_code,
                "output_preview": output[:500],
                "extraction_metadata": result.metadata,
            },
        )

    # ── Test execution (P3-4 API support) ─────────────────────────────────

    def test_execute(self) -> Dict[str, Any]:
        """
        Run the command and extract the value without firing an alert.
        Returns a serializable dict for the test-execute API response.
        """
        if not self.command:
            return {"success": False, "error": "No command configured", "raw_output": ""}

        output, exit_code, stderr = self._run_command()

        if self.strategy == "exit_code":
            result = ExtractionResult(success=True, value=exit_code, raw_output=output[:500])
        else:
            result = self._engine.extract(self.strategy, output, self.strategy_config, state_key=self.name)

        return {
            "success": result.success,
            "value": result.value,
            "raw_output": output[:2000],
            "stderr": stderr[:500] if stderr else "",
            "exit_code": exit_code,
            "strategy": self.strategy,
            "extraction_metadata": result.metadata,
            "error": result.error,
        }
