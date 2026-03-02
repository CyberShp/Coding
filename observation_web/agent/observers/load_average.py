"""
系统负载监测观察点

监测 1/5/15 分钟平均负载。
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict

from ..core.base import BaseObserver, ObserverResult, AlertLevel

logger = logging.getLogger(__name__)


class LoadAverageObserver(BaseObserver):
    """系统负载监测观察点"""

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)

        self.cpu_count = os.cpu_count() or 1
        self.load_multiplier = config.get('load_multiplier', 2.0)
        self.threshold = self.cpu_count * self.load_multiplier

        self._was_alerting = False

    def check(self, reporter=None) -> ObserverResult:
        """检查系统负载"""
        load_avg = self._get_load_average()

        if load_avg is None:
            return self.create_result(
                has_alert=False,
                message="无法获取系统负载",
                details={'error': '读取 /proc/loadavg 失败'},
            )

        load1, load5, load15 = load_avg

        if reporter and hasattr(reporter, 'record_metrics'):
            reporter.record_metrics({
                'load1': load1,
                'load5': load5,
                'load15': load15,
                'cpu_count': self.cpu_count,
                'observer': self.name,
            })

        details = {
            'load1': load1,
            'load5': load5,
            'load15': load15,
            'cpu_count': self.cpu_count,
            'threshold': self.threshold,
            'load_multiplier': self.load_multiplier,
        }

        alerts = []
        if load1 > self.threshold:
            alerts.append(f"1分钟负载 {load1:.2f} > {self.threshold:.1f}")
        if load5 > self.threshold:
            alerts.append(f"5分钟负载 {load5:.2f} > {self.threshold:.1f}")
        if load15 > self.threshold:
            alerts.append(f"15分钟负载 {load15:.2f} > {self.threshold:.1f}")

        if alerts:
            self._was_alerting = True
            message = f"系统负载过高: {'; '.join(alerts)} (CPU核心数: {self.cpu_count})"
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message=message,
                details=details,
                sticky=True,
            )

        if self._was_alerting:
            self._was_alerting = False
            details['recovered'] = True
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.INFO,
                message="系统负载恢复正常",
                details=details,
                sticky=True,
            )

        return self.create_result(
            has_alert=False,
            message=f"系统负载正常 (1/5/15分钟: {load1:.2f}/{load5:.2f}/{load15:.2f})",
            details=details,
        )

    def _get_load_average(self):
        """获取系统负载"""
        loadavg_path = Path('/proc/loadavg')

        if not loadavg_path.exists():
            try:
                return os.getloadavg()
            except OSError:
                return None

        try:
            content = loadavg_path.read_text().strip()
            parts = content.split()
            if len(parts) >= 3:
                return float(parts[0]), float(parts[1]), float(parts[2])
        except Exception as e:
            logger.error(f"读取 /proc/loadavg 失败: {e}")

        return None
