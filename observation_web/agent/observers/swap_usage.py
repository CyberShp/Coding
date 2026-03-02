"""
Swap 使用率监测观察点

监测系统 swap 空间使用情况。
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import parse_key_value

logger = logging.getLogger(__name__)


class SwapUsageObserver(BaseObserver):
    """Swap 使用率监测观察点"""

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)

        self.usage_threshold_percent = config.get('usage_threshold_percent', 50)
        self._was_alerting = False

    def check(self, reporter=None) -> ObserverResult:
        """检查 Swap 使用率"""
        swap_info = self._get_swap_info()

        if swap_info is None:
            return self.create_result(
                has_alert=False,
                message="无法获取 Swap 信息",
                details={'error': '读取 /proc/meminfo 失败'},
            )

        total_kb = swap_info.get('SwapTotal', 0)
        free_kb = swap_info.get('SwapFree', 0)
        used_kb = total_kb - free_kb

        if total_kb == 0:
            return self.create_result(
                has_alert=False,
                message="系统未配置 Swap",
                details={'swap_total': 0},
            )

        usage_percent = (used_kb / total_kb) * 100

        if reporter and hasattr(reporter, 'record_metrics'):
            reporter.record_metrics({
                'swap_total_mb': round(total_kb / 1024, 2),
                'swap_used_mb': round(used_kb / 1024, 2),
                'swap_usage_percent': round(usage_percent, 1),
                'observer': self.name,
            })

        details = {
            'swap_total_mb': round(total_kb / 1024, 2),
            'swap_free_mb': round(free_kb / 1024, 2),
            'swap_used_mb': round(used_kb / 1024, 2),
            'usage_percent': round(usage_percent, 1),
            'threshold_percent': self.usage_threshold_percent,
        }

        if usage_percent >= self.usage_threshold_percent:
            self._was_alerting = True
            message = f"Swap 使用率过高: {usage_percent:.1f}% >= {self.usage_threshold_percent}%"
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
                message="Swap 使用率恢复正常",
                details=details,
                sticky=True,
            )

        return self.create_result(
            has_alert=False,
            message=f"Swap 使用率正常 ({usage_percent:.1f}%)",
            details=details,
        )

    def _get_swap_info(self) -> Optional[Dict[str, int]]:
        """获取 Swap 信息"""
        meminfo_path = Path('/proc/meminfo')

        if not meminfo_path.exists():
            return None

        try:
            content = meminfo_path.read_text()
            info = {}

            for line in content.strip().split('\n'):
                if ':' not in line:
                    continue
                key, value = line.split(':', 1)
                key = key.strip()

                if key in ['SwapTotal', 'SwapFree', 'SwapCached']:
                    value = value.strip().replace(' kB', '')
                    try:
                        info[key] = int(value)
                    except ValueError:
                        info[key] = 0

            return info

        except Exception as e:
            logger.error(f"读取 /proc/meminfo 失败: {e}")
            return None
