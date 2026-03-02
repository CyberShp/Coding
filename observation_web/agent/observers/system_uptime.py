"""
系统运行时间监测观察点

检测意外重启（uptime 突然变小）。
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from ..core.base import BaseObserver, ObserverResult, AlertLevel

logger = logging.getLogger(__name__)


class SystemUptimeObserver(BaseObserver):
    """系统运行时间监测观察点"""

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)

        self.min_expected_uptime_seconds = config.get('min_expected_uptime_seconds', 300)
        self._last_uptime: Optional[float] = None
        self._boot_detected = False

    def check(self, reporter=None) -> ObserverResult:
        """检查系统运行时间"""
        uptime_seconds = self._get_uptime()

        if uptime_seconds is None:
            return self.create_result(
                has_alert=False,
                message="无法获取系统运行时间",
                details={'error': '读取 /proc/uptime 失败'},
            )

        uptime_str = self._format_uptime(uptime_seconds)
        boot_time = datetime.now() - timedelta(seconds=uptime_seconds)

        if reporter and hasattr(reporter, 'record_metrics'):
            reporter.record_metrics({
                'uptime_seconds': round(uptime_seconds, 0),
                'uptime_hours': round(uptime_seconds / 3600, 2),
                'observer': self.name,
            })

        details = {
            'uptime_seconds': round(uptime_seconds, 0),
            'uptime_formatted': uptime_str,
            'boot_time': boot_time.isoformat(),
        }

        reboot_detected = False
        if self._last_uptime is not None:
            if uptime_seconds < self._last_uptime - 60:
                reboot_detected = True
                details['previous_uptime_seconds'] = round(self._last_uptime, 0)

        self._last_uptime = uptime_seconds

        if reboot_detected:
            message = f"检测到系统重启！当前运行时间: {uptime_str}"
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message=message,
                details=details,
            )

        if uptime_seconds < self.min_expected_uptime_seconds and not self._boot_detected:
            self._boot_detected = True
            message = f"系统刚启动，运行时间: {uptime_str}"
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.INFO,
                message=message,
                details=details,
            )

        return self.create_result(
            has_alert=False,
            message=f"系统运行时间: {uptime_str}",
            details=details,
        )

    def _get_uptime(self) -> Optional[float]:
        """获取系统运行时间（秒）"""
        uptime_path = Path('/proc/uptime')

        if not uptime_path.exists():
            return None

        try:
            content = uptime_path.read_text().strip()
            parts = content.split()
            if parts:
                return float(parts[0])
        except Exception as e:
            logger.error(f"读取 /proc/uptime 失败: {e}")

        return None

    def _format_uptime(self, seconds: float) -> str:
        """格式化运行时间"""
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)

        parts = []
        if days > 0:
            parts.append(f"{days}天")
        if hours > 0 or days > 0:
            parts.append(f"{hours}小时")
        parts.append(f"{minutes}分钟")

        return ' '.join(parts)
