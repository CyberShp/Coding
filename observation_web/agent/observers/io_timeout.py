"""
IO 超时监控观察点

监控系统日志中的 IO timeout、IO error、scsi error 等事件。
使用内置关键字匹配，无需用户提供命令。
"""

import logging
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command, tail_file

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
        self._log_cursors = {}
        self._seen_dmesg = []
        self._dmesg_initialized = False

    def check(self, reporter=None) -> ObserverResult:
        all_events = []

        for log_path in self.log_paths:
            events = self._scan_log(log_path)
            all_events.extend(events)

        # Also check dmesg
        dmesg_events, dmesg_ok = self._scan_dmesg()
        all_events.extend(dmesg_events)

        if not dmesg_ok and not any(Path(path).exists() for path in self.log_paths):
            return self.create_error_result(
                "IO 超时监控无可用日志源",
                {'log_paths': self.log_paths},
            )

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
                sticky=False,
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
        cursor = self._log_cursors.get(log_path)

        try:
            stat = path.stat()
            inode = getattr(stat, 'st_ino', 0)
            if cursor is None:
                lines, position = tail_file(path, 0, max_lines=500, skip_existing=True)
            else:
                last_pos = int(cursor.get('offset', 0))
                if cursor.get('inode') != inode:
                    last_pos = 0
                lines, position = tail_file(path, last_pos, max_lines=500)
            self._log_cursors[log_path] = {'offset': position, 'inode': inode}

            for line in lines:
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

    def _scan_dmesg(self):
        ret, stdout, stderr = run_command('dmesg -T 2>/dev/null | tail -200', shell=True, timeout=10)
        if ret != 0:
            return [], False

        events = []
        seen = set(self._seen_dmesg)
        current_hashes = []
        for line in stdout.split('\n'):
            for pattern, io_type in IO_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    fingerprint = hashlib.sha256(line.strip().encode('utf-8')).hexdigest()
                    current_hashes.append(fingerprint)
                    if fingerprint in seen or not self._dmesg_initialized:
                        break
                    events.append({
                        'type': io_type,
                        'summary': f"{io_type}: {line.strip()[:80]}",
                        'line': line.strip()[:200],
                        'source': 'dmesg',
                    })
                    break
        self._dmesg_initialized = True
        self._seen_dmesg = (self._seen_dmesg + current_hashes)[-2000:]
        return events, True
    persistent_state_fields = BaseObserver.persistent_state_fields + (
        '_log_cursors', '_seen_dmesg', '_dmesg_initialized',
    )
