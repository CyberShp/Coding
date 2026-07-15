"""
控制器状态监控观察点

监控存储阵列控制器的在线/离线/降级状态变化。
需要用户在配置中提供查询命令（command 字段）。
命令回显应包含控制器标识和状态关键字。
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command

logger = logging.getLogger(__name__)


class ControllerStateObserver(BaseObserver):
    """
    控制器状态监控

    配置示例:
    {
        "enabled": true,
        "interval": 60,
        "command": "show controller status",
        "keywords": ["online", "offline", "degraded"]
    }
    """
    persistent_state_fields = BaseObserver.persistent_state_fields + ('_last_states',)

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.command = config.get('command', '')
        self.keywords = config.get('keywords', ['online', 'offline', 'degraded', 'normal'])
        self._last_states = {}  # controller_id -> state

    def check(self, reporter=None) -> ObserverResult:
        if not self.command:
            return self.create_error_result(
                message="控制器状态监控：未配置命令，请在 config.json 中设置 command",
            )

        ret, stdout, stderr = run_command(self.command, shell=True, timeout=30)
        if ret != 0:
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message=f"控制器状态查询失败: {stderr[:100]}",
                details={'stderr': stderr, 'return_code': ret},
                collection_ok=False,
            )

        # Parse controller states from output
        current_states = self._parse_states(stdout)
        if not current_states:
            return self.create_error_result(
                message="控制器状态查询正常，未识别到控制器条目",
                details={'raw': stdout[:500]},
            )

        # Detect changes
        changes = []
        for ctrl_id, state in current_states.items():
            old_state = self._last_states.get(ctrl_id)
            if old_state is not None and old_state != state:
                changes.append({
                    'id': ctrl_id,
                    'old_state': old_state,
                    'new_state': state,
                })
            # Alert on non-normal states
            if old_state is None and state.lower() in ('offline', 'degraded', 'fault', 'absent'):
                if not any(c['id'] == ctrl_id for c in changes):
                    changes.append({
                        'id': ctrl_id,
                        'old_state': old_state or '未知',
                        'new_state': state,
                    })

        self._last_states = current_states

        if changes:
            msgs = [f"控制器 {c['id']}: {c['old_state']} → {c['new_state']}" for c in changes[:5]]
            anomalous = ('offline', 'degraded', 'fault', 'absent')
            is_recovery = all(c['new_state'].lower() not in anomalous for c in changes)
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.INFO if is_recovery else AlertLevel.ERROR,
                message=("控制器状态恢复: " if is_recovery else "控制器状态变化: ") + "; ".join(msgs),
                details={'changes': changes, 'all_states': current_states, 'recovered': is_recovery},
                sticky=False,
            )

        return self.create_result(
            has_alert=False,
            message=f"控制器状态正常 ({len(current_states)} 个控制器)",
            details={'all_states': current_states},
        )

    def _parse_states(self, output: str) -> Dict[str, str]:
        """Parse controller states from command output."""
        states = {}
        # Try common patterns:
        # "Controller A: Online"  or  "CTE0.A  Running Status: Normal"
        for line in output.split('\n'):
            line = line.strip()
            if not line:
                continue
            # Pattern: Controller <ID> <sep> <state>
            m = re.search(
                r'(?:controller|ctrl|cte)\s*\.?\s*(\w+)[\s:=🟰]+.*?(?:status|state)[\s:=🟰]+(\w+)',
                line, re.IGNORECASE
            )
            if m:
                states[m.group(1)] = m.group(2)
                continue
            # Simpler: "Controller A Online"
            m2 = re.search(
                r'(?:controller|ctrl)\s+(\w+)\s*[\s:=🟰]+\s*(\w+)',
                line, re.IGNORECASE
            )
            if m2:
                states[m2.group(1)] = m2.group(2)

        return states
