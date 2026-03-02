"""
TCP 连接状态监测观察点

监测 TIME_WAIT、ESTABLISHED 等 TCP 连接状态。
"""

import logging
from typing import Any, Dict

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command

logger = logging.getLogger(__name__)


class TcpConnectionsObserver(BaseObserver):
    """TCP 连接状态监测观察点"""

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)

        self.time_wait_threshold = config.get('time_wait_threshold', 10000)
        self.established_threshold = config.get('established_threshold', 50000)
        self._was_alerting = False

    def check(self, reporter=None) -> ObserverResult:
        """检查 TCP 连接状态"""
        conn_stats = self._get_tcp_stats()

        if not conn_stats:
            return self.create_result(
                has_alert=False,
                message="无法获取 TCP 连接统计",
                details={'error': '执行 ss 命令失败'},
            )

        if reporter and hasattr(reporter, 'record_metrics'):
            reporter.record_metrics({
                **conn_stats,
                'observer': self.name,
            })

        details = {
            'connection_stats': conn_stats,
            'thresholds': {
                'time_wait': self.time_wait_threshold,
                'established': self.established_threshold,
            },
        }

        alerts = []
        time_wait = conn_stats.get('TIME-WAIT', 0) + conn_stats.get('TIME_WAIT', 0)
        established = conn_stats.get('ESTAB', 0) + conn_stats.get('ESTABLISHED', 0)

        if time_wait > self.time_wait_threshold:
            alerts.append(f"TIME_WAIT 连接数 {time_wait} > {self.time_wait_threshold}")

        if established > self.established_threshold:
            alerts.append(f"ESTABLISHED 连接数 {established} > {self.established_threshold}")

        if alerts:
            self._was_alerting = True
            message = f"TCP 连接异常: {'; '.join(alerts)}"
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
                message="TCP 连接状态恢复正常",
                details=details,
                sticky=True,
            )

        return self.create_result(
            has_alert=False,
            message=f"TCP 连接正常 (ESTABLISHED: {established}, TIME_WAIT: {time_wait})",
            details=details,
        )

    def _get_tcp_stats(self) -> Dict[str, int]:
        """获取 TCP 连接统计"""
        stats = {}

        ret, stdout, _ = run_command('ss -s', shell=True, timeout=10)
        if ret == 0 and stdout:
            for line in stdout.strip().split('\n'):
                if 'TCP:' in line:
                    parts = line.split(',')
                    for part in parts:
                        part = part.strip()
                        if 'estab' in part.lower():
                            try:
                                stats['ESTAB'] = int(part.split()[0])
                            except (IndexError, ValueError):
                                pass
                        elif 'timewait' in part.lower():
                            try:
                                stats['TIME-WAIT'] = int(part.split()[0])
                            except (IndexError, ValueError):
                                pass

        ret, stdout, _ = run_command('ss -tan state all | tail -n +2 | awk \'{print $1}\' | sort | uniq -c', shell=True, timeout=10)
        if ret == 0 and stdout:
            for line in stdout.strip().split('\n'):
                parts = line.strip().split()
                if len(parts) == 2:
                    try:
                        count = int(parts[0])
                        state = parts[1]
                        stats[state] = count
                    except ValueError:
                        pass

        return stats
