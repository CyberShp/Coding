"""
磁盘空间监测观察点

监测文件系统和 inode 使用率。
"""

import logging
import re
from typing import Any, Dict, List

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command

logger = logging.getLogger(__name__)


class DiskSpaceObserver(BaseObserver):
    """磁盘空间监测观察点"""

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)

        self.space_threshold_percent = config.get('space_threshold_percent', 85)
        self.inode_threshold_percent = config.get('inode_threshold_percent', 90)
        self.exclude_fs_types = config.get('exclude_fs_types', ['tmpfs', 'devtmpfs', 'squashfs', 'overlay'])
        self.exclude_mounts = config.get('exclude_mounts', ['/dev', '/run', '/snap'])

        self._was_alerting = False

    def check(self, reporter=None) -> ObserverResult:
        """检查磁盘空间"""
        space_data = self._get_disk_space()
        inode_data = self._get_inode_usage()

        if not space_data and not inode_data:
            return self.create_result(
                has_alert=False,
                message="无法获取磁盘空间信息",
                details={'error': '执行 df 命令失败'},
            )

        alerts = []
        filesystems = {}

        for mount, info in space_data.items():
            if self._should_exclude(mount, info.get('fstype', '')):
                continue

            filesystems[mount] = info

            if reporter and hasattr(reporter, 'record_metrics'):
                reporter.record_metrics({
                    'mount': mount,
                    'space_percent': info['use_percent'],
                    'observer': self.name,
                })

            if info['use_percent'] >= self.space_threshold_percent:
                alerts.append(
                    f"{mount}: 空间使用率 {info['use_percent']}% >= {self.space_threshold_percent}%"
                )

        for mount, info in inode_data.items():
            if self._should_exclude(mount, ''):
                continue

            if mount in filesystems:
                filesystems[mount]['inode_percent'] = info['use_percent']
            else:
                filesystems[mount] = {'inode_percent': info['use_percent']}

            if info['use_percent'] >= self.inode_threshold_percent:
                alerts.append(
                    f"{mount}: inode 使用率 {info['use_percent']}% >= {self.inode_threshold_percent}%"
                )

        details = {
            'filesystems': filesystems,
            'thresholds': {
                'space_percent': self.space_threshold_percent,
                'inode_percent': self.inode_threshold_percent,
            },
        }

        if alerts:
            self._was_alerting = True
            message = f"磁盘空间告警: {'; '.join(alerts)}"
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
                message="磁盘空间恢复正常",
                details=details,
                sticky=True,
            )

        return self.create_result(
            has_alert=False,
            message="磁盘空间正常",
            details=details,
        )

    def _should_exclude(self, mount: str, fstype: str) -> bool:
        """判断是否排除该挂载点"""
        if fstype in self.exclude_fs_types:
            return True
        for prefix in self.exclude_mounts:
            if mount.startswith(prefix):
                return True
        return False

    def _get_disk_space(self) -> Dict[str, Dict]:
        """获取磁盘空间使用情况"""
        result = {}
        ret, stdout, _ = run_command(['df', '-T', '-P'], timeout=10)

        if ret != 0:
            return result

        for line in stdout.strip().split('\n')[1:]:
            parts = line.split()
            if len(parts) < 7:
                continue

            fstype = parts[1]
            mount = parts[6]
            total_kb = int(parts[2])
            used_kb = int(parts[3])
            use_percent = int(parts[5].rstrip('%'))

            result[mount] = {
                'fstype': fstype,
                'total_gb': round(total_kb / (1024 * 1024), 2),
                'used_gb': round(used_kb / (1024 * 1024), 2),
                'use_percent': use_percent,
            }

        return result

    def _get_inode_usage(self) -> Dict[str, Dict]:
        """获取 inode 使用情况"""
        result = {}
        ret, stdout, _ = run_command(['df', '-i', '-P'], timeout=10)

        if ret != 0:
            return result

        for line in stdout.strip().split('\n')[1:]:
            parts = line.split()
            if len(parts) < 6:
                continue

            mount = parts[5]
            use_str = parts[4].rstrip('%')

            try:
                use_percent = int(use_str) if use_str != '-' else 0
            except ValueError:
                use_percent = 0

            result[mount] = {'use_percent': use_percent}

        return result
