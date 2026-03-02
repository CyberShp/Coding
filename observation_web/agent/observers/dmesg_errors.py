"""
Dmesg 错误监测观察点

监测内核日志中的 error/warning 消息。
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command

logger = logging.getLogger(__name__)


class DmesgErrorsObserver(BaseObserver):
    """Dmesg 错误监测观察点"""

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)

        self.lookback_minutes = config.get('lookback_minutes', 5)
        self.error_threshold = config.get('error_threshold', 0)
        self.exclude_patterns = config.get('exclude_patterns', [
            r'audit:.*',
            r'IPv6:.*',
        ])
        self._compiled_excludes = [re.compile(p, re.IGNORECASE) for p in self.exclude_patterns]
        self._last_errors: List[Dict] = []

    def check(self, reporter=None) -> ObserverResult:
        """检查 dmesg 错误"""
        errors, warnings = self._get_recent_dmesg()

        if reporter and hasattr(reporter, 'record_metrics'):
            reporter.record_metrics({
                'dmesg_errors': len(errors),
                'dmesg_warnings': len(warnings),
                'observer': self.name,
            })

        details = {
            'errors': errors[:20],
            'warnings': warnings[:20],
            'error_count': len(errors),
            'warning_count': len(warnings),
            'lookback_minutes': self.lookback_minutes,
        }

        new_errors = [e for e in errors if e not in self._last_errors]
        self._last_errors = errors

        if new_errors:
            message = f"检测到 {len(new_errors)} 个新的内核错误"
            if new_errors:
                message += f": {new_errors[0].get('message', '')[:100]}"

            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING if len(errors) <= 5 else AlertLevel.ERROR,
                message=message,
                details=details,
            )

        return self.create_result(
            has_alert=False,
            message=f"内核日志正常 (最近{self.lookback_minutes}分钟: {len(errors)}错误, {len(warnings)}警告)",
            details=details,
        )

    def _should_exclude(self, message: str) -> bool:
        """判断是否排除该消息"""
        for pattern in self._compiled_excludes:
            if pattern.search(message):
                return True
        return False

    def _get_recent_dmesg(self):
        """获取最近的 dmesg 错误和警告"""
        errors = []
        warnings = []

        ret, stdout, _ = run_command(
            f'dmesg --level=err,warn --since="{self.lookback_minutes} minutes ago" 2>/dev/null || dmesg -T | tail -100',
            shell=True,
            timeout=10
        )

        if ret != 0 or not stdout:
            return errors, warnings

        for line in stdout.strip().split('\n'):
            if not line.strip():
                continue

            if self._should_exclude(line):
                continue

            line_lower = line.lower()
            entry = {
                'message': line[:500],
                'timestamp': datetime.now().isoformat(),
            }

            if 'error' in line_lower or 'fail' in line_lower or 'fault' in line_lower:
                errors.append(entry)
            elif 'warn' in line_lower:
                warnings.append(entry)

        return errors, warnings
