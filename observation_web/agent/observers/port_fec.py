"""
端口 FEC 模式变化监测观察点

归属：端口级检查
监测各端口的 FEC（Forward Error Correction）模式是否发生变化。

内置通用命令：通过 ethtool --show-fec 逐端口查询。
如果配置了 command 则优先使用自定义命令。
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command

logger = logging.getLogger(__name__)


class PortFecObserver(BaseObserver):
    """
    FEC 模式变化监测

    工作方式（二选一）：
    1. 内置模式（默认）：自动发现网络端口，逐个调用 ethtool --show-fec 获取 FEC 模式
    2. 自定义命令模式：配置 command 字段，输出每行 "端口名 FEC模式" 格式

    配置项：
    - command: 自定义命令（可选，留空则使用内置 ethtool）
    - ports: 要监测的端口列表（可选，为空则自动发现）
    - parse_pattern: 自定义命令的解析正则（需含 port 和 fec 命名组）
    """

    # ethtool --show-fec 输出中提取 Active FEC encoding
    ACTIVE_FEC_PATTERN = re.compile(r'Active\s+FEC\s+encodings?\s*:\s*(.+)', re.IGNORECASE)
    # 自定义命令的默认解析正则
    DEFAULT_PATTERN = r'(?P<port>\S+)\s+(?P<fec>\S+)'

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.command = config.get('command', '')
        self.ports_filter = set(config.get('ports', []))
        self.parse_pattern = re.compile(
            config.get('parse_pattern', self.DEFAULT_PATTERN)
        )
        self._last_fec = {}  # type: Dict[str, str]
        self._first_run = True

    def check(self) -> ObserverResult:
        if self.command:
            current_fec = self._collect_via_command()
        else:
            current_fec = self._collect_via_ethtool()

        if not current_fec:
            return self.create_result(
                has_alert=False,
                message="FEC 查询无数据（可能无网络端口或 ethtool 不可用）",
            )

        changes = []
        if not self._first_run:
            for port, fec in current_fec.items():
                old_fec = self._last_fec.get(port)
                if old_fec is not None and old_fec != fec:
                    changes.append({
                        'port': port,
                        'old_fec': old_fec,
                        'new_fec': fec,
                    })
                    logger.warning(f"[PortFEC] {port} FEC 变化: {old_fec} -> {fec}")

        self._last_fec = current_fec
        self._first_run = False

        if changes:
            msgs = [f"{c['port']}: {c['old_fec']} -> {c['new_fec']}" for c in changes]
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message=f"FEC 模式变化: {'; '.join(msgs[:5])}",
                details={'changes': changes, 'current': current_fec},
            )

        return self.create_result(
            has_alert=False,
            message=f"FEC 模式正常 ({len(current_fec)} 端口)",
            details={'current': current_fec},
        )

    # ---------- 内置 ethtool 模式 ----------

    def _collect_via_ethtool(self) -> Dict[str, str]:
        """使用 ethtool --show-fec 逐端口收集 FEC 模式"""
        result = {}
        ports = self._discover_ports()

        for port in ports:
            ret, stdout, _ = run_command(
                ['ethtool', '--show-fec', port], timeout=5
            )
            if ret != 0:
                continue
            m = self.ACTIVE_FEC_PATTERN.search(stdout)
            if m:
                fec_mode = m.group(1).strip()
                result[port] = fec_mode

        return result

    def _discover_ports(self) -> List[str]:
        """发现要监测的网络端口"""
        if self.ports_filter:
            return sorted(self.ports_filter)

        ports = []
        net_path = Path('/sys/class/net')
        if net_path.exists():
            for item in net_path.iterdir():
                name = item.name
                # 排除 lo、虚拟接口、管理口
                if name == 'lo' or name.startswith(('veth', 'docker', 'virbr', 'br-')):
                    continue
                if name.startswith('eth-m') or name.startswith('eno'):
                    continue
                ports.append(name)
        return sorted(ports)

    # ---------- 自定义命令模式 ----------

    def _collect_via_command(self) -> Dict[str, str]:
        """使用用户自定义命令收集"""
        ret, stdout, stderr = run_command(self.command, shell=True, timeout=10)
        if ret != 0:
            logger.warning(f"[PortFEC] 自定义命令执行失败: {stderr[:200]}")
            return {}

        result = {}
        for line in stdout.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            m = self.parse_pattern.search(line)
            if m:
                port = m.group('port')
                fec = m.group('fec')
                if self.ports_filter and port not in self.ports_filter:
                    continue
                result[port] = fec
        return result
