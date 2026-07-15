"""
进程崩溃监控观察点

监控 /var/log/messages 中的 core dump、segfault、OOM killer 等关键事件。
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

# Critical keywords to search for
CRASH_PATTERNS = [
    (r'segfault\s+at', 'segfault'),
    (r'core\s+dumped', 'core_dump'),
    (r'Out\s+of\s+memory.*Killed\s+process', 'oom_kill'),
    (r'Killed\s+process\s+\d+', 'oom_kill'),
    (r'general\s+protection\s+fault', 'gp_fault'),
    (r'kernel\s+BUG\s+at', 'kernel_bug'),
    (r'Call\s+Trace:', 'kernel_panic'),
    (r'Oops:', 'kernel_oops'),
    (r'trapping.*fault', 'trap_fault'),
]


class ProcessCrashObserver(BaseObserver):
    """
    进程崩溃监控

    自动扫描系统日志，无需用户配置命令。
    内置检查 /var/log/messages 和 dmesg。
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.log_paths = config.get('log_paths', ['/var/log/messages', '/var/log/syslog'])
        self._log_cursors = {}  # path -> {offset, inode}
        self._seen_dmesg = []
        self._dmesg_initialized = False

    def check(self, reporter=None) -> ObserverResult:
        all_crashes = []

        # Method 1: Check log files
        for log_path in self.log_paths:
            crashes = self._scan_log(log_path)
            all_crashes.extend(crashes)

        # Method 2: Check dmesg
        dmesg_crashes, dmesg_ok = self._scan_dmesg()
        all_crashes.extend(dmesg_crashes)

        if not dmesg_ok and not any(Path(path).exists() for path in self.log_paths):
            return self.create_error_result(
                "进程崩溃监控无可用日志源",
                {'log_paths': self.log_paths},
            )

        if all_crashes:
            msgs = [f"{c['process'] or '?'}: {c['type']}" for c in all_crashes[:5]]
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.CRITICAL,
                message=f"检测到 {len(all_crashes)} 个进程崩溃事件: " + "; ".join(msgs),
                details={
                    'crashes': all_crashes[:20],
                    'log_path': self.log_paths[0] if self.log_paths else '',
                },
                sticky=False,
            )

        return self.create_result(
            has_alert=False,
            message="进程崩溃监控正常",
        )

    def _scan_log(self, log_path: str) -> List[Dict]:
        """Scan a log file for crash events from last known position."""
        path = Path(log_path)
        if not path.exists():
            return []

        crashes = []
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
                for pattern, crash_type in CRASH_PATTERNS:
                    if re.search(pattern, line, re.IGNORECASE):
                        process = self._extract_process(line)
                        crashes.append({
                            'type': crash_type,
                            'process': process,
                            'line': line.strip()[:200],
                            'source': log_path,
                        })
                        break
        except Exception as e:
            logger.debug(f"Failed to scan {log_path}: {e}")

        return crashes

    def _scan_dmesg(self):
        """Scan dmesg for recent crash events."""
        ret, stdout, stderr = run_command('dmesg -T 2>/dev/null | tail -200', shell=True, timeout=10)
        if ret != 0:
            return [], False

        crashes = []
        seen = set(self._seen_dmesg)
        current_hashes = []
        for line in stdout.split('\n'):
            for pattern, crash_type in CRASH_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    fingerprint = hashlib.sha256(line.strip().encode('utf-8')).hexdigest()
                    current_hashes.append(fingerprint)
                    if fingerprint in seen or not self._dmesg_initialized:
                        break
                    process = self._extract_process(line)
                    crashes.append({
                        'type': crash_type,
                        'process': process,
                        'line': line.strip()[:200],
                        'source': 'dmesg',
                    })
                    break
        self._dmesg_initialized = True
        self._seen_dmesg = (self._seen_dmesg + current_hashes)[-2000:]
        return crashes, True

    def _extract_process(self, line: str) -> str:
        """Try to extract process name from log line."""
        # "process_name[12345]: segfault..."
        m = re.search(r'(\w[\w.-]+)\[(\d+)\]', line)
        if m:
            return f"{m.group(1)}[{m.group(2)}]"
        # "Killed process 12345 (proc_name)"
        m2 = re.search(r'process\s+(\d+)\s*\((\w+)\)', line)
        if m2:
            return f"{m2.group(2)}[{m2.group(1)}]"
        return ''
    persistent_state_fields = BaseObserver.persistent_state_fields + (
        '_log_cursors', '_seen_dmesg', '_dmesg_initialized',
    )
