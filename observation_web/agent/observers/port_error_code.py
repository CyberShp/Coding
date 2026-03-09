"""
端口误码观察点

归属：端口级检查
通过 anytest portallinfo 获取端口列表，anytest portgeterr 获取误码统计。
0x2 前缀为以太网卡件，0x11 为 FC 卡件，解析逻辑不同。
"""

import logging
import re
from typing import Any, Dict, List, Tuple

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command, safe_int

logger = logging.getLogger(__name__)

# portId 提取正则
PORT_ID_PATTERN = re.compile(r'portId\s*[=:]\s*(0x[0-9a-fA-F]+)', re.IGNORECASE)

# 0x11 FC 卡件误码字段
FC_ERROR_FIELDS = [
    ('LossOfSignal Count', 'LossOfSignal Count'),
    ('BadRXChar Count', 'BadRXChar Count'),
    ('LossOfSync Count', 'LossOfSync Count'),
    ('InvalidCRC Count', 'InvalidCRC Count'),
    ('ProtocolErr Count', 'ProtocolErr Count'),
    ('LinkFail Count', 'LinkFail Count'),
    ('LinkLoss Count', 'LinkLoss Count'),
]

# 0x2 以太网卡件误码字段（ethtool 风格命名）
ETH_ERROR_FIELDS = [
    ('Rx Errors', 'Rx Errors'),
    ('Tx Errors', 'Tx Errors'),
    ('Rx Dropped', 'Rx Dropped'),
    ('Tx Dropped', 'Tx Dropped'),
    ('Collisions', 'Collisions'),
]


class PortErrorCodeObserver(BaseObserver):
    """
    端口误码监测

    工作流程：
    1. anytest portallinfo -t 2 | grep portId | grep 0x2|0x11 获取端口列表
    2. 对每个端口执行 anytest portgeterr -p {port_id} -n 0
    3. 0x11 FC 卡件：解析 LossOfSignal Count, BadRXChar Count 等，非零上报告警
    4. 0x2 以太网卡件：解析 Rx Errors, Tx Errors 等，非零上报告警
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.cmd_list_ports = config.get(
            'command_list_ports',
            'anytest portallinfo -t 2'
        )
        self.cmd_list_ports_fc = config.get(
            'command_list_ports_fc',
            'anytest portallinfo -t 1'
        )
        self.cmd_get_errors = config.get(
            'command_get_errors',
            'anytest portgeterr -p {port_id} -n 0'
        )

    def check(self) -> ObserverResult:
        ports_0x2, ports_0x11 = self._get_port_list()
        if not ports_0x2 and not ports_0x11:
            return self.create_result(
                has_alert=False,
                message="端口误码: 无 0x2/0x11 端口",
            )

        alerts = []
        for port_id in ports_0x2:
            errs = self._get_eth_errors(port_id)
            for field, val in errs:
                if val > 0:
                    alerts.append(f"端口 {port_id} {field}: {val}")

        for port_id in ports_0x11:
            errs = self._get_fc_errors(port_id)
            for field, val in errs:
                if val > 0:
                    alerts.append(f"端口 {port_id} {field}: {val}")

        if alerts:
            msg = "; ".join(alerts[:10])
            if len(alerts) > 10:
                msg += f" ... 共 {len(alerts)} 项"
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message=f"端口误码: {msg}",
                details={'alerts': alerts},
            )

        return self.create_result(
            has_alert=False,
            message=f"端口误码: 正常 ({len(ports_0x2) + len(ports_0x11)} 端口)",
        )

    def _get_port_list(self) -> Tuple[List[str], List[str]]:
        """获取 0x2 和 0x11 端口列表。以太网用 -t 2，FC 用 -t 1，分别查询后合并。"""
        ports_0x2 = []
        ports_0x11 = []

        # Query Ethernet ports (-t 2)
        cmd_eth = f"{self.cmd_list_ports} | grep -iE 'portId' | grep -aiE '0x2|0x11'"
        ret, stdout, stderr = run_command(cmd_eth, shell=True, timeout=15)
        if ret == 0:
            for line in stdout.strip().split('\n'):
                line = line.strip()
                if not line:
                    continue
                m = PORT_ID_PATTERN.search(line)
                if m:
                    port_id = m.group(1)
                    if port_id.upper().startswith('0X11'):
                        ports_0x11.append(port_id)
                    elif port_id.upper().startswith('0X2'):
                        ports_0x2.append(port_id)

        # Query FC ports (-t 1)
        cmd_fc = f"{self.cmd_list_ports_fc} | grep -iE 'portId' | grep -aiE '0x2|0x11'"
        ret, stdout, stderr = run_command(cmd_fc, shell=True, timeout=15)
        if ret != 0:
            logger.info(f"[port_error_code] FC 端口列表不可用，跳过 FC 检查: {stderr[:200]}")
        else:
            for line in stdout.strip().split('\n'):
                line = line.strip()
                if not line:
                    continue
                m = PORT_ID_PATTERN.search(line)
                if m:
                    port_id = m.group(1)
                    if port_id.upper().startswith('0X11'):
                        if port_id not in ports_0x11:
                            ports_0x11.append(port_id)
                    elif port_id.upper().startswith('0X2'):
                        if port_id not in ports_0x2:
                            ports_0x2.append(port_id)

        return ports_0x2, ports_0x11

    def _get_fc_errors(self, port_id: str) -> List[Tuple[str, int]]:
        """解析 0x11 FC 卡件误码"""
        cmd = self.cmd_get_errors.format(port_id=port_id)
        ret, stdout, _ = run_command(cmd, shell=True, timeout=10)
        if ret != 0:
            return []

        result = []
        for display_name, field_name in FC_ERROR_FIELDS:
            # 支持 "LossOfSignal Count: 0" 或 "LossOfSignal Count = 0"
            pat = re.compile(
                rf'{re.escape(field_name)}\s*[=:]\s*(\d+)',
                re.IGNORECASE
            )
            m = pat.search(stdout)
            if m:
                val = safe_int(m.group(1), 0)
                result.append((display_name, val))
        return result

    def _get_eth_errors(self, port_id: str) -> List[Tuple[str, int]]:
        """解析 0x2 以太网卡件误码"""
        cmd = self.cmd_get_errors.format(port_id=port_id)
        ret, stdout, _ = run_command(cmd, shell=True, timeout=10)
        if ret != 0:
            return []

        result = []
        for display_name, field_name in ETH_ERROR_FIELDS:
            pat = re.compile(
                rf'{re.escape(field_name)}\s*[=:]\s*(\d+)',
                re.IGNORECASE
            )
            m = pat.search(stdout)
            if m:
                val = safe_int(m.group(1), 0)
                result.append((display_name, val))
        return result
