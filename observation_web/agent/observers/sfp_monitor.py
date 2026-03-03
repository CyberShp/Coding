"""
光模块监控观察点

归属：硬件级检查
通过 anytest sfpallinfo 获取光模块信息，监测温度、健康状态、运行状态及 FC 速率。
"""

import logging
import re
from typing import Any, Dict, List

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command, safe_float

logger = logging.getLogger(__name__)


class SfpMonitorObserver(BaseObserver):
    """
    光模块监控

    工作流程：
    1. 执行 anytest sfpallinfo
    2. 按 '---+' 分隔符切分为各光模块块
    3. 解析 PortId, parentID, Name, TempReal, HealthState, RunningState
    4. 温度 >= 105 度上报；HealthState 非 NORMAL 上报；RunningState 非 LINK_UP 上报
    5. FC 光模块：MaxSpeed != RunSpeed 或 RunSpeed 为 unknown 上报降速告警
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.command = config.get('command', 'anytest sfpallinfo')
        self.temp_threshold = config.get('temp_threshold', 105)

    def check(self) -> ObserverResult:
        ret, stdout, stderr = run_command(self.command, shell=True, timeout=30)
        if ret != 0:
            logger.warning(f"[sfp_monitor] 命令执行失败: {stderr[:200]}")
            return self.create_result(
                has_alert=False,
                message="光模块: 命令执行失败",
            )

        blocks = self._split_blocks(stdout)
        alerts = []

        for block in blocks:
            info = self._parse_block(block)
            if not info:
                continue

            port_id = info.get('PortId', '')
            parent_id = info.get('parentID', '')
            name = info.get('Name', 'P0')
            slot_str = f"Slot {parent_id}" if parent_id else ""

            # 温度
            temp = info.get('TempReal')
            if temp is not None and temp >= self.temp_threshold:
                alerts.append(
                    f"光模块 {name} ({slot_str}, PortId {port_id}) 温度过高: {temp}°C"
                )

            # 健康状态
            health = info.get('HealthState', '')
            if health and health.upper() != 'NORMAL':
                alerts.append(
                    f"光模块 {name} ({slot_str}) HealthState 异常: {health}"
                )

            # 运行状态
            running = info.get('RunningState', '')
            if running and running.upper() != 'LINK_UP':
                alerts.append(
                    f"光模块 {name} ({slot_str}) RunningState 异常: {running}"
                )

            # FC 速率
            run_speed = info.get('RunSpeed', '')
            max_speed = info.get('MaxSpeed', '')
            conf_speed = info.get('ConfSpeed', '')

            if run_speed or max_speed or conf_speed:
                run_lower = run_speed.lower() if run_speed else ''
                max_lower = max_speed.lower() if max_speed else ''
                if run_lower == 'unknown speed' or 'unknown' in run_lower:
                    alerts.append(
                        f"FC 光模块 {name} ({slot_str}) 速率异常: RunSpeed=unknown"
                    )
                elif max_speed and run_speed and max_lower != run_lower:
                    alerts.append(
                        f"FC 光模块 {name} ({slot_str}) 速率不一致: "
                        f"RunSpeed={run_speed}, MaxSpeed={max_speed}"
                    )

        if alerts:
            msg = "; ".join(alerts[:5])
            if len(alerts) > 5:
                msg += f" ... 共 {len(alerts)} 项"
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message=f"光模块: {msg}",
                details={'alerts': alerts},
            )

        return self.create_result(
            has_alert=False,
            message=f"光模块: 正常 ({len(blocks)} 个)",
        )

    def _split_blocks(self, text: str) -> List[str]:
        """按 '---+' 分隔为块"""
        return [
            b.strip() for b in re.split(r'---+', text)
            if b.strip()
        ]

    def _parse_block(self, block: str) -> Dict[str, Any]:
        """解析单个光模块块"""
        info = {}
        for line in block.split('\n'):
            line = line.strip()
            if ':' not in line:
                continue
            key, _, val = line.partition(':')
            key = key.strip()
            val = val.strip()

            if key in ('PortId', 'parentID', 'Name', 'HealthState', 'RunningState',
                       'RunSpeed', 'MaxSpeed', 'ConfSpeed'):
                info[key] = val
            elif 'TempReal' in key:
                # 可能为 "TempReal(`C): 45" 或 "TempReal: 45"
                num = re.search(r'[\d.-]+', val)
                if num:
                    info['TempReal'] = safe_float(num.group(), 0)
        return info
