"""
文件描述符监测观察点

监测系统文件描述符使用情况。
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ..core.base import BaseObserver, ObserverResult, AlertLevel

logger = logging.getLogger(__name__)


class FileDescriptorsObserver(BaseObserver):
    """文件描述符监测观察点"""

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)

        self.usage_threshold_percent = config.get('usage_threshold_percent', 80)
        self._was_alerting = False

    def check(self, reporter=None) -> ObserverResult:
        """检查文件描述符使用情况"""
        fd_info = self._get_fd_info()

        if fd_info is None:
            return self.create_result(
                has_alert=False,
                message="无法获取文件描述符信息",
                details={'error': '读取 /proc/sys/fs/file-nr 失败'},
            )

        allocated, free, max_fds = fd_info
        used = allocated - free
        usage_percent = (used / max_fds) * 100 if max_fds > 0 else 0

        if reporter and hasattr(reporter, 'record_metrics'):
            reporter.record_metrics({
                'fd_allocated': allocated,
                'fd_used': used,
                'fd_max': max_fds,
                'fd_usage_percent': round(usage_percent, 1),
                'observer': self.name,
            })

        details = {
            'allocated': allocated,
            'free': free,
            'used': used,
            'max': max_fds,
            'usage_percent': round(usage_percent, 1),
            'threshold_percent': self.usage_threshold_percent,
        }

        if usage_percent >= self.usage_threshold_percent:
            self._was_alerting = True
            message = f"文件描述符使用率过高: {usage_percent:.1f}% >= {self.usage_threshold_percent}% ({used}/{max_fds})"
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
                message="文件描述符使用率恢复正常",
                details=details,
                sticky=True,
            )

        return self.create_result(
            has_alert=False,
            message=f"文件描述符正常 ({used}/{max_fds}, {usage_percent:.1f}%)",
            details=details,
        )

    def _get_fd_info(self) -> Optional[Tuple[int, int, int]]:
        """获取文件描述符信息"""
        file_nr_path = Path('/proc/sys/fs/file-nr')

        if not file_nr_path.exists():
            return None

        try:
            content = file_nr_path.read_text().strip()
            parts = content.split()

            if len(parts) >= 3:
                allocated = int(parts[0])
                free = int(parts[1])
                max_fds = int(parts[2])
                return (allocated, free, max_fds)

        except Exception as e:
            logger.error(f"读取 /proc/sys/fs/file-nr 失败: {e}")

        return None
