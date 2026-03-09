"""
阵列开工状态观察点

通过 anytest sysgetstartwork 检测模块开工状态。
若存在任一模块状态非 1，则判定为未开工。
"""

import logging
import re
from typing import Any, Dict

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command

logger = logging.getLogger(__name__)

_MODULE_LINE_RE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*[:：]\s*([0-9]+)\s*$")


class StartWorkObserver(BaseObserver):
    """开工状态检查观察点。"""

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.command = config.get("command", "anytest sysgetstartwork")

    def check(self) -> ObserverResult:
        ret, stdout, stderr = run_command(self.command, shell=True, timeout=20)
        if ret != 0:
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message=f"开工检查命令失败: {(stderr or '')[:200]}",
                details={"started": False, "reason": "command_failed"},
            )

        modules = {}
        for line in (stdout or "").splitlines():
            line = line.strip()
            m = _MODULE_LINE_RE.match(line)
            if not m:
                continue
            mod_name = m.group(1)
            mod_state = m.group(2)
            modules[mod_name] = mod_state

        if not modules:
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message="开工检查解析失败：未发现模块状态",
                details={"started": False, "reason": "parse_failed"},
            )

        not_started = [name for name, state in modules.items() if state != "1"]
        if not_started:
            preview = ", ".join(not_started[:8])
            if len(not_started) > 8:
                preview += f" 等 {len(not_started)} 个模块"
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message=f"阵列未开工: {preview}",
                details={
                    "started": False,
                    "failed_modules": not_started,
                    "total_modules": len(modules),
                    "raw_modules": modules,
                },
            )

        return self.create_result(
            has_alert=False,
            message=f"阵列开工状态正常 ({len(modules)} 模块)",
            details={"started": True, "total_modules": len(modules)},
        )
