"""
僵尸进程监测观察点

监测系统中的僵尸进程数量。
"""

import logging
from typing import Any, Dict, List

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command

logger = logging.getLogger(__name__)


class ZombieProcessesObserver(BaseObserver):
    """僵尸进程监测观察点"""

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)

        self.zombie_threshold = config.get('zombie_threshold', 0)
        self.consecutive_threshold = config.get('consecutive_threshold', 3)
        self._consecutive_count = 0
        self._was_alerting = False

    def check(self, reporter=None) -> ObserverResult:
        """检查僵尸进程"""
        zombie_info = self._get_zombie_processes()

        if zombie_info is None:
            return self.create_result(
                has_alert=False,
                message="无法获取进程信息",
                details={'error': '执行 ps 命令失败'},
            )

        zombie_count = zombie_info['count']
        zombie_list = zombie_info['processes']

        if reporter and hasattr(reporter, 'record_metrics'):
            reporter.record_metrics({
                'zombie_count': zombie_count,
                'observer': self.name,
            })

        details = {
            'zombie_count': zombie_count,
            'zombie_threshold': self.zombie_threshold,
            'zombies': zombie_list[:10],
        }

        if zombie_count > self.zombie_threshold:
            self._consecutive_count += 1
        else:
            self._consecutive_count = 0

        if self._consecutive_count >= self.consecutive_threshold:
            self._was_alerting = True
            message = f"检测到 {zombie_count} 个僵尸进程 (连续 {self._consecutive_count} 次)"
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message=message,
                details=details,
                sticky=True,
            )

        if self._was_alerting and zombie_count <= self.zombie_threshold:
            self._was_alerting = False
            details['recovered'] = True
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.INFO,
                message="僵尸进程已清除",
                details=details,
                sticky=True,
            )

        return self.create_result(
            has_alert=False,
            message=f"僵尸进程数: {zombie_count}",
            details=details,
        )

    def _get_zombie_processes(self) -> Dict[str, Any]:
        """获取僵尸进程列表"""
        ret, stdout, _ = run_command(['ps', 'aux'], timeout=10)

        if ret != 0:
            return None

        zombies = []
        for line in stdout.strip().split('\n')[1:]:
            parts = line.split()
            if len(parts) >= 11:
                stat = parts[7]
                if 'Z' in stat:
                    zombies.append({
                        'pid': parts[1],
                        'ppid': self._get_ppid(parts[1]),
                        'user': parts[0],
                        'command': ' '.join(parts[10:])[:100],
                    })

        return {
            'count': len(zombies),
            'processes': zombies,
        }

    def _get_ppid(self, pid: str) -> str:
        """获取父进程 ID"""
        ret, stdout, _ = run_command(['ps', '-o', 'ppid=', '-p', pid], timeout=5)
        if ret == 0 and stdout:
            return stdout.strip()
        return 'unknown'
