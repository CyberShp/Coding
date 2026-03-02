"""
网络错误监测观察点

监测网络接口的 dropped/errors/overruns 等异常。
"""

import logging
from pathlib import Path
from typing import Any, Dict

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import get_network_interfaces, safe_int

logger = logging.getLogger(__name__)


class NetworkErrorsObserver(BaseObserver):
    """网络错误监测观察点"""

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)

        self.error_rate_threshold = config.get('error_rate_threshold', 10)
        self.include_interfaces = config.get('include_interfaces', [])
        self.exclude_interfaces = config.get('exclude_interfaces', ['lo', 'docker0', 'br-'])

        self._last_stats: Dict[str, Dict] = {}
        self._was_alerting = False

    def check(self, reporter=None) -> ObserverResult:
        """检查网络错误"""
        current_stats = self._get_network_stats()

        if not current_stats:
            return self.create_result(
                has_alert=False,
                message="无法获取网络统计信息",
                details={'error': '读取网络统计信息失败'},
            )

        alerts = []
        interface_stats = {}

        for iface, stats in current_stats.items():
            if self._should_exclude(iface):
                continue

            last = self._last_stats.get(iface, {})
            deltas = {}

            for key in ['rx_errors', 'tx_errors', 'rx_dropped', 'tx_dropped', 'rx_overruns', 'tx_overruns']:
                current = stats.get(key, 0)
                previous = last.get(key, 0)
                delta = current - previous if current >= previous else current
                deltas[key] = delta

            interface_stats[iface] = {
                **stats,
                'deltas': deltas,
            }

            if reporter and hasattr(reporter, 'record_metrics'):
                reporter.record_metrics({
                    'interface': iface,
                    'rx_errors_delta': deltas.get('rx_errors', 0),
                    'tx_errors_delta': deltas.get('tx_errors', 0),
                    'observer': self.name,
                })

            total_errors = sum(deltas.values())
            if total_errors > self.error_rate_threshold:
                error_details = [f"{k}:{v}" for k, v in deltas.items() if v > 0]
                alerts.append(f"{iface}: {', '.join(error_details)}")

        self._last_stats = current_stats

        details = {
            'interfaces': interface_stats,
            'error_rate_threshold': self.error_rate_threshold,
        }

        if alerts:
            self._was_alerting = True
            message = f"网络错误告警: {'; '.join(alerts)}"
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
                message="网络错误恢复正常",
                details=details,
                sticky=True,
            )

        return self.create_result(
            has_alert=False,
            message="网络状态正常",
            details=details,
        )

    def _should_exclude(self, iface: str) -> bool:
        """判断是否排除该接口"""
        if self.include_interfaces and iface not in self.include_interfaces:
            return True
        for prefix in self.exclude_interfaces:
            if iface.startswith(prefix) or iface == prefix:
                return True
        return False

    def _get_network_stats(self) -> Dict[str, Dict]:
        """获取网络统计信息"""
        stats = {}
        net_path = Path('/sys/class/net')

        if not net_path.exists():
            return stats

        for iface_path in net_path.iterdir():
            iface = iface_path.name
            stats_path = iface_path / 'statistics'

            if not stats_path.exists():
                continue

            iface_stats = {}
            for stat_name in ['rx_errors', 'tx_errors', 'rx_dropped', 'tx_dropped', 'rx_overruns', 'tx_overruns', 'rx_bytes', 'tx_bytes', 'rx_packets', 'tx_packets']:
                stat_file = stats_path / stat_name
                if stat_file.exists():
                    try:
                        iface_stats[stat_name] = safe_int(stat_file.read_text().strip())
                    except Exception:
                        iface_stats[stat_name] = 0

            if iface_stats:
                stats[iface] = iface_stats

        return stats
