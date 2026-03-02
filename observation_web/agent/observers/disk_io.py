"""
磁盘 I/O 监测观察点

通过 /proc/diskstats 监测磁盘 IOPS、吞吐量和延迟。
"""

import logging
import re
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command

logger = logging.getLogger(__name__)


class DiskIoObserver(BaseObserver):
    """磁盘 I/O 监测观察点"""

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)

        self.iops_threshold = config.get('iops_threshold', 5000)
        self.latency_threshold_ms = config.get('latency_threshold_ms', 100)
        self.throughput_threshold_mbps = config.get('throughput_threshold_mbps', 500)
        self.consecutive_threshold = config.get('consecutive_threshold', 3)
        self.disk_filter = config.get('disk_filter', r'^(sd[a-z]+|nvme\d+n\d+|vd[a-z]+)$')

        self._last_stats: Dict[str, Dict] = {}
        self._alerts_history = deque(maxlen=self.consecutive_threshold)
        self._was_alerting = False

    def check(self, reporter=None) -> ObserverResult:
        """检查磁盘 I/O"""
        current_stats = self._read_diskstats()

        if not current_stats:
            return self.create_result(
                has_alert=False,
                message="无法获取磁盘统计信息",
                details={'error': '读取 /proc/diskstats 失败'},
            )

        alerts = []
        disk_metrics = {}

        for disk, stats in current_stats.items():
            last = self._last_stats.get(disk)
            if last is None:
                continue

            time_delta = (stats['timestamp'] - last['timestamp']).total_seconds()
            if time_delta <= 0:
                continue

            read_iops = (stats['reads'] - last['reads']) / time_delta
            write_iops = (stats['writes'] - last['writes']) / time_delta
            total_iops = read_iops + write_iops

            read_bytes = (stats['read_sectors'] - last['read_sectors']) * 512
            write_bytes = (stats['write_sectors'] - last['write_sectors']) * 512
            read_mbps = read_bytes / (1024 * 1024) / time_delta
            write_mbps = write_bytes / (1024 * 1024) / time_delta
            total_mbps = read_mbps + write_mbps

            io_time_delta = stats['io_time_ms'] - last['io_time_ms']
            io_count = (stats['reads'] + stats['writes']) - (last['reads'] + last['writes'])
            avg_latency_ms = io_time_delta / io_count if io_count > 0 else 0

            disk_metrics[disk] = {
                'read_iops': round(read_iops, 1),
                'write_iops': round(write_iops, 1),
                'total_iops': round(total_iops, 1),
                'read_mbps': round(read_mbps, 2),
                'write_mbps': round(write_mbps, 2),
                'total_mbps': round(total_mbps, 2),
                'avg_latency_ms': round(avg_latency_ms, 2),
            }

            if reporter and hasattr(reporter, 'record_metrics'):
                reporter.record_metrics({
                    'disk': disk,
                    'iops': round(total_iops, 1),
                    'throughput_mbps': round(total_mbps, 2),
                    'latency_ms': round(avg_latency_ms, 2),
                    'observer': self.name,
                })

            if total_iops > self.iops_threshold:
                alerts.append(f"{disk}: IOPS 过高 ({total_iops:.0f} > {self.iops_threshold})")
            if avg_latency_ms > self.latency_threshold_ms:
                alerts.append(f"{disk}: 延迟过高 ({avg_latency_ms:.0f}ms > {self.latency_threshold_ms}ms)")
            if total_mbps > self.throughput_threshold_mbps:
                alerts.append(f"{disk}: 吞吐量过高 ({total_mbps:.0f}MB/s > {self.throughput_threshold_mbps}MB/s)")

        self._last_stats = current_stats
        self._alerts_history.append(len(alerts) > 0)

        details = {
            'disk_metrics': disk_metrics,
            'thresholds': {
                'iops': self.iops_threshold,
                'latency_ms': self.latency_threshold_ms,
                'throughput_mbps': self.throughput_threshold_mbps,
            },
        }

        if alerts and all(self._alerts_history):
            self._was_alerting = True
            message = f"磁盘 I/O 异常: {'; '.join(alerts)}"
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message=message,
                details=details,
                sticky=True,
            )

        if self._was_alerting and not alerts:
            self._was_alerting = False
            details['recovered'] = True
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.INFO,
                message="磁盘 I/O 恢复正常",
                details=details,
                sticky=True,
            )

        return self.create_result(
            has_alert=False,
            message="磁盘 I/O 正常",
            details=details,
        )

    def _read_diskstats(self) -> Dict[str, Dict]:
        """读取 /proc/diskstats"""
        stats = {}
        diskstats_path = Path('/proc/diskstats')

        if not diskstats_path.exists():
            return stats

        try:
            content = diskstats_path.read_text()
            pattern = re.compile(self.disk_filter)
            now = datetime.now()

            for line in content.strip().split('\n'):
                parts = line.split()
                if len(parts) < 14:
                    continue

                disk_name = parts[2]
                if not pattern.match(disk_name):
                    continue

                stats[disk_name] = {
                    'timestamp': now,
                    'reads': int(parts[3]),
                    'read_sectors': int(parts[5]),
                    'writes': int(parts[7]),
                    'write_sectors': int(parts[9]),
                    'io_time_ms': int(parts[12]),
                }

        except Exception as e:
            logger.error(f"读取 /proc/diskstats 失败: {e}")

        return stats
