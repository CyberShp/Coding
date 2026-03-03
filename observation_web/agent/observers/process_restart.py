"""
进程拉起检查观察点

归属：进程级检查
监控指定进程的 -v N 参数，若 N 增大说明进程被重拉。
"""

import logging
import re
from typing import Any, Dict, List, Optional

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command, safe_int

logger = logging.getLogger(__name__)

# ps -aux | grep 输出中提取 -v N 参数
V_PARAM_PATTERN = re.compile(r'-v\s+(\d+)', re.IGNORECASE)


class ProcessRestartObserver(BaseObserver):
    """
    进程拉起检查

    工作流程：
    1. 默认监控 app_data, devm, memf（可配置）
    2. 每周期执行 ps -aux | grep -aiE {进程名}
    3. 解析回显中的 -v N 参数
    4. 若 -v 值增大（如 1 -> 2），说明进程被重拉，上报告警
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.processes = config.get('processes', ['app_data', 'devm', 'memf'])

    def check(self) -> ObserverResult:
        alerts = []
        for proc_name in self.processes:
            current_v = self._get_v_param(proc_name)
            if current_v is None:
                continue

            last_key = f'v_{proc_name}'
            last_v = self._last_values.get(last_key)
            self._last_values[last_key] = current_v

            if last_v is not None and current_v > last_v:
                alerts.append(
                    f"进程 {proc_name} 被重拉: -v {last_v} -> {current_v}"
                )
                logger.warning(
                    f"[process_restart] {proc_name} 重拉: -v {last_v} -> {current_v}"
                )

        if alerts:
            msg = "; ".join(alerts)
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message=f"进程拉起: {msg}",
                details={'alerts': alerts},
            )

        return self.create_result(
            has_alert=False,
            message=f"进程拉起: 正常 ({len(self.processes)} 个进程)",
        )

    def _get_v_param(self, proc_name: str) -> Optional[int]:
        """从 ps 输出中解析 -v N"""
        cmd = f"ps -aux | grep -aiE '{proc_name}'"
        ret, stdout, _ = run_command(cmd, shell=True, timeout=5)
        if ret != 0 and not stdout.strip():
            return None

        # 取最大的 -v 值（可能有多个进程实例）
        max_v = None
        for line in stdout.strip().split('\n'):
            line = line.strip()
            if not line or 'grep' in line:
                continue
            m = V_PARAM_PATTERN.search(line)
            if m:
                v = safe_int(m.group(1), 0)
                if max_v is None or v > max_v:
                    max_v = v

        return max_v
