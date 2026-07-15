"""
磁盘状态监控观察点

监控存储阵列磁盘的在线/离线/重建/降级状态变化。
需要用户在配置中提供查询命令（command 字段）。
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command

logger = logging.getLogger(__name__)


class DiskStateObserver(BaseObserver):
    """
    磁盘状态监控

    配置示例:
    {
        "enabled": true,
        "interval": 60,
        "command": "show disk status"
    }
    """
    persistent_state_fields = BaseObserver.persistent_state_fields + ('_last_states',)

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.command = config.get('command', '')
        self._last_states = {}  # disk_id -> state

    def check(self, reporter=None) -> ObserverResult:
        if not self.command:
            return self.create_error_result(
                message="磁盘状态监控：未配置命令，请在 config.json 中设置 command",
            )

        ret, stdout, stderr = run_command(self.command, shell=True, timeout=30)
        if ret != 0:
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message=f"磁盘状态查询失败: {stderr[:100]}",
                details={'stderr': stderr},
                collection_ok=False,
            )

        current_states = self._parse_states(stdout)
        if not current_states:
            return self.create_error_result(
                message="磁盘状态查询正常，未识别到磁盘条目",
                details={'raw': stdout[:500]},
            )

        changes = []
        anomalous = ('offline', 'fault', 'failed', 'degraded', 'rebuilding', 'absent')
        for disk_id, state in current_states.items():
            old_state = self._last_states.get(disk_id)
            if old_state is not None and old_state != state:
                changes.append({
                    'id': disk_id,
                    'old_state': old_state,
                    'new_state': state,
                })
            elif old_state is None and state.lower() in anomalous:
                changes.append({
                    'id': disk_id,
                    'old_state': old_state or '未知',
                    'new_state': state,
                })

        self._last_states = current_states

        if changes:
            msgs = [f"磁盘 {c['id']}: {c['old_state']} → {c['new_state']}" for c in changes[:5]]
            has_anomaly = any(c['new_state'].lower() in anomalous for c in changes)
            level = AlertLevel.ERROR if any(
                c['new_state'].lower() in ('offline', 'fault', 'failed')
                for c in changes
            ) else (AlertLevel.WARNING if has_anomaly else AlertLevel.INFO)
            return self.create_result(
                has_alert=True,
                alert_level=level,
                message=("磁盘状态变化: " if has_anomaly else "磁盘状态恢复: ") + "; ".join(msgs),
                details={'changes': changes, 'all_states': current_states, 'recovered': not has_anomaly},
                sticky=False,
            )

        return self.create_result(
            has_alert=False,
            message=f"磁盘状态正常 ({len(current_states)} 块磁盘)",
            details={'all_states': current_states},
        )

    def _parse_states(self, output: str) -> Dict[str, str]:
        states = {}
        for line in output.split('\n'):
            line = line.strip()
            if not line:
                continue
            # Pattern: "Disk 0:1 Online" or "CTE0.0  Health Status: Normal"
            m = re.search(
                r'(?:disk|hdd|ssd)\s*[_\s]?(\S+)[\s:=🟰]+.*?(?:status|state)[\s:=🟰]+(\w+)',
                line, re.IGNORECASE
            )
            if m:
                states[m.group(1)] = m.group(2)
                continue
            m2 = re.search(
                r'(?:disk|hdd|ssd)\s+(\S+)\s+(\w+)',
                line, re.IGNORECASE
            )
            if m2:
                states[m2.group(1)] = m2.group(2)

        return states
