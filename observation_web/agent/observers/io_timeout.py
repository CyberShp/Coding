"""
IO 超时监控观察点

监控系统日志中的 IO timeout、IO error、scsi error 等事件。
使用内置关键字匹配，无需用户提供命令。
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command

logger = logging.getLogger(__name__)

# IO error patterns
IO_PATTERNS = [
    (r'I/O\s+error', 'io_error'),
    (r'io\s+timeout', 'io_timeout'),
    (r'scsi\s+error', 'scsi_error'),
    (r'Medium\s+Error', 'medium_error'),
    (r'Hardware\s+Error', 'hw_error'),
    (r'task\s+abort', 'task_abort'),
    (r'device\s+offline', 'device_offline'),
    (r'reset\s+target', 'target_reset'),
    (r'EXT4-fs.*error', 'fs_error'),
    (r'XFS.*error', 'fs_error'),
    (r'Buffer\s+I/O\s+error', 'buffer_io_error'),
]


class IoTimeoutObserver(BaseObserver):
    """
    IO 超时 / IO 错误监控

    自动扫描系统日志，无需用户配置命令。
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.log_paths = config.get('log_paths', ['/var/log/messages', '/var/log/syslog'])
        self._last_positions = {}

    def check(self, reporter=None) -> ObserverResult:
        all_events = []

        for log_path in self.log_paths:
            events = self._scan_log(log_path)
            all_events.extend(events)

        # Also check dmesg
        dmesg_events = self._scan_dmesg()
        all_events.extend(dmesg_events)

        if all_events:
            summaries = [e['summary'] for e in all_events[:5]]
            level = AlertLevel.CRITICAL if len(all_events) >= 5 else AlertLevel.ERROR
            return self.create_result(
                has_alert=True,
                alert_level=level,
                message=f"检测到 {len(all_events)} 个 IO 异常事件: " + "; ".join(summaries),
                details={
                    'events': all_events[:30],
                    'log_path': self.log_paths[0] if self.log_paths else '',
                },
                sticky=True,
            )

        return self.create_result(
            has_alert=False,
            message="IO 超时监控正常",
        )

    def _scan_log(self, log_path: str) -> List[Dict]:
        path = Path(log_path)
        if not path.exists():
            return []

        events = []
        last_pos = self._last_positions.get(log_path, 0)

        try:
            size = path.stat().st_size
            if size < last_pos:
                last_pos = 0

            with open(path, 'r', errors='ignore') as f:
                f.seek(last_pos)
                new_lines = f.readlines()
                self._last_positions[log_path] = f.tell()

            for line in new_lines[-500:]:
                for pattern, io_type in IO_PATTERNS:
                    if re.search(pattern, line, re.IGNORECASE):
                        events.append({
                            'type': io_type,
                            'summary': f"{io_type}: {line.strip()[:80]}",
                            'line': line.strip()[:200],
                            'source': log_path,
                        })
                        break
        except Exception as e:
            logger.debug(f"Failed to scan {log_path}: {e}")

        return events

    def _scan_dmesg(self) -> List[Dict]:
        ret, stdout, stderr = run_command('dmesg -T 2>/dev/null | tail -200', shell=True, timeout=10)
        if ret != 0:
            return []

        events = []
        for line in stdout.split('\n'):
            for pattern, io_type in IO_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    events.append({
                        'type': io_type,
                        'summary': f"{io_type}: {line.strip()[:80]}",
                        'line': line.strip()[:200],
                        'source': 'dmesg',
                    })
                    break

        return events
