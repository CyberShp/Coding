"""
端口速率变化监测观察点

归属：端口级检查
监测各端口的协商速率是否发生变化（如 100000 -> 25000 Mbps）。

内置通用方式：通过 /sys/class/net/<port>/speed 读取，
或回退到 ethtool <port> 解析 Speed 字段。
如果配置了 command 则优先使用自定义命令。
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command, read_sysfs

logger = logging.getLogger(__name__)


class PortSpeedObserver(BaseObserver):
    """
    端口速率变化监测

    工作方式（二选一）：
    1. 内置模式（默认）：通过 sysfs 或 ethtool 读取各端口速率
    2. 自定义命令模式：配置 command 字段

    配置项：
    - command: 自定义命令（可选，留空则使用内置 sysfs/ethtool）
    - ports: 要监测的端口列表（可选，为空则自动发现）
    - parse_pattern: 自定义命令的解析正则（需含 port 和 speed 命名组）
    """

    # ethtool 输出中提取 Speed
    SPEED_PATTERN = re.compile(r'Speed:\s*(\S+)', re.IGNORECASE)
    # 自定义命令的默认解析正则
    DEFAULT_PATTERN = r'(?P<port>\S+)\s+(?P<speed>\S+)'

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.command = config.get('command', '')
        self.ports_filter = set(config.get('ports', []))
        self.parse_pattern = re.compile(
            config.get('parse_pattern', self.DEFAULT_PATTERN)
        )
        self._last_speed = {}  # type: Dict[str, str]
        self._first_run = True

    def check(self) -> ObserverResult:
        if self.command:
            current_speed = self._collect_via_command()
        else:
            current_speed = self._collect_via_sysfs()

        if not current_speed:
            return self.create_result(
                has_alert=False,
                message="端口速率查询无数据（可能无网络端口）",
            )

        changes = []
        if not self._first_run:
            for port, speed in current_speed.items():
                old_speed = self._last_speed.get(port)
                if old_speed is not None and old_speed != speed:
                    changes.append({
                        'port': port,
                        'old_speed': old_speed,
                        'new_speed': speed,
                    })
                    logger.warning(f"[PortSpeed] {port} 速率变化: {old_speed} -> {speed}")

        self._last_speed = current_speed
        self._first_run = False

        if changes:
            msgs = [f"{c['port']}: {c['old_speed']} -> {c['new_speed']}" for c in changes]
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message=f"端口速率变化: {'; '.join(msgs[:5])}",
                details={'changes': changes, 'current': current_speed},
            )

        return self.create_result(
            has_alert=False,
            message=f"端口速率正常 ({len(current_speed)} 端口)",
            details={'current': current_speed},
        )

    # ---------- 内置 sysfs / ethtool 模式 ----------

    def _collect_via_sysfs(self) -> Dict[str, str]:
        """通过 sysfs 读取各端口速率，回退到 ethtool"""
        result = {}
        ports = self._discover_ports()

        for port in ports:
            # 优先 sysfs
            speed = read_sysfs(Path(f'/sys/class/net/{port}/speed'))
            if speed and speed != '-1':
                result[port] = f"{speed}Mb/s"
                continue

            # 回退到 ethtool
            ret, stdout, _ = run_command(['ethtool', port], timeout=5)
            if ret == 0:
                m = self.SPEED_PATTERN.search(stdout)
                if m:
                    result[port] = m.group(1)

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
            logger.warning(f"[PortSpeed] 自定义命令执行失败: {stderr[:200]}")
            return {}

        result = {}
        for line in stdout.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            m = self.parse_pattern.search(line)
            if m:
                port = m.group('port')
                speed = m.group('speed')
                if self.ports_filter and port not in self.ports_filter:
                    continue
                result[port] = speed
        return result
