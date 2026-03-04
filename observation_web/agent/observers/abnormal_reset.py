"""
异常复位检查观察点

归属：系统级检查
通过 os_cli 进入阵列环境，读取 log_reset.txt，检测异常复位原因。
"""

import logging
import re
from typing import Any, Dict, List, Set

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command

logger = logging.getLogger(__name__)

# 异常复位关键字（不区分大小写）
DEFAULT_ABNORMAL_REASONS = [
    'watchDog reset',
    'oops reset',
    'unknown reset',
    'oom reset',
    'panic reset',
    'kernel reset',
    'mce reset',
    'bios reset',
    'software unknown reset',
    'failure recovery reset',
]


class AbnormalResetObserver(BaseObserver):
    """
    异常复位检查

    工作流程：
    1. 执行 os_cli ./ 进入阵列命令环境
    2. cat log_reset.txt 获取复位日志
    3. 解析 reason 和 time 字段
    4. 匹配异常关键字则上报告警
    5. 记录已上报时间戳，避免重复上报
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        # os_cli_path: 可选，指定 os_cli 完整路径（如 /usr/local/bin/os_cli）
        self.os_cli_path = config.get('os_cli_path', '')
        base_cmd = config.get('command', 'os_cli "cat ./log_reset.txt"')
        if self.os_cli_path:
            # 使用完整路径替换命令中的 os_cli
            base_cmd = base_cmd.replace('os_cli', self.os_cli_path, 1)
        self.command = base_cmd
        self.ensure_path = config.get('ensure_path', True)  # 默认添加 PATH 解决 cmd not found
        reasons = config.get('abnormal_reasons', DEFAULT_ABNORMAL_REASONS)
        self.abnormal_patterns = [
            re.compile(re.escape(r), re.IGNORECASE)
            for r in reasons
        ]
        self._last_reported_times: Set[str] = set()

    def check(self) -> ObserverResult:
        ret, stdout, stderr = run_command(
            self.command, shell=True, timeout=15, ensure_path=self.ensure_path
        )
        if ret != 0:
            err_preview = (stderr or '')[:200]
            if 'not found' in err_preview.lower() or 'no such file' in err_preview.lower():
                logger.warning(
                    f"[abnormal_reset] 命令不存在或路径错误 (可配置 os_cli_path): {err_preview}"
                )
            else:
                logger.warning(f"[abnormal_reset] 命令执行失败: {err_preview}")
            return self.create_result(
                has_alert=False,
                message="异常复位: 命令执行失败",
            )

        entries = self._parse_log(stdout)
        alerts = []

        for entry in entries:
            reason = entry.get('reason', '')
            ts = entry.get('time', '')
            if not reason or not ts:
                continue

            if ts in self._last_reported_times:
                continue

            for pat in self.abnormal_patterns:
                if pat.search(reason):
                    alerts.append({
                        'reason': reason,
                        'time': ts,
                    })
                    self._last_reported_times.add(ts)
                    logger.warning(f"[abnormal_reset] 异常复位: {reason} @ {ts}")
                    break

        if alerts:
            msgs = [f"{a['reason']} ({a['time']})" for a in alerts]
            msg = "; ".join(msgs[:5])
            if len(msgs) > 5:
                msg += f" ... 共 {len(msgs)} 条"
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message=f"异常复位: {msg}",
                details={'alerts': alerts},
            )

        return self.create_result(
            has_alert=False,
            message="异常复位: 无新增异常",
        )

    def _parse_log(self, text: str) -> List[Dict[str, str]]:
        """解析 log_reset.txt，提取 reason 和 time"""
        entries = []
        current = {}

        for line in text.split('\n'):
            line = line.strip()
            if not line:
                if current:
                    entries.append(current)
                    current = {}
                continue

            if ':' in line:
                key, _, val = line.partition(':')
                key = key.strip().lower()
                val = val.strip()
                if key in ('reason', 'time'):
                    current[key] = val

        if current:
            entries.append(current)
        return entries
