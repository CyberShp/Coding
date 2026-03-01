"""
端口流量采集观察点

归属：端口级（仅采集，不产生告警）
定期采集各端口 TX/RX 流量数据，输出到 traffic.jsonl 文件，
供 web 端拉取后显示流量曲线图。本地保留 2 小时数据。

内置通用方式：优先使用 ethtool -S <port> 获取准确的 tx_bytes / rx_bytes；
如果 ethtool 不可用或失败，回退到 /sys/class/net/<port>/statistics/。
如果配置了 command 则优先使用自定义命令。
"""

import json
import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command, read_sysfs

logger = logging.getLogger(__name__)


class PortTrafficObserver(BaseObserver):
    """
    端口流量采集器

    工作方式（三选一，按优先级）：
    1. 自定义命令模式：配置 command 字段（最高优先级）
    2. ethtool 模式（默认）：通过 ethtool -S <port> 获取准确的
       tx_bytes / rx_bytes，自动计算速率（bps）
    3. sysfs 回退模式：ethtool 不可用时通过 /sys/class/net/ 读取

    配置项：
    - command: 自定义命令（可选，留空则使用 ethtool）
    - output_path: traffic.jsonl 文件路径
    - ports: 要采集的端口列表（可选，为空则自动发现）
    - retention_hours: 本地保留时长（默认 2）
    - parse_pattern: 自定义命令的解析正则
    """

    # 自定义命令的默认解析正则
    DEFAULT_PATTERN = r'(?P<port>\S+)\s+(?P<tx_bytes>\d+)\s+(?P<rx_bytes>\d+)'

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.command = config.get('command', '')
        self.output_path = Path(
            config.get('output_path', '/var/log/observation-points/traffic.jsonl')
        )
        self.ports_filter = set(config.get('ports', []))
        self.parse_pattern = re.compile(
            config.get('parse_pattern', self.DEFAULT_PATTERN)
        )
        self.retention_hours = config.get('retention_hours', 2)

        self._last_bytes = {}  # type: Dict[str, Dict[str, int]]
        self._last_ts = None  # type: float
        self._cleanup_counter = 0

    def check(self) -> ObserverResult:
        """采集流量数据（不产生告警）"""
        if self.command:
            current = self._collect_via_command()
        else:
            # 优先 ethtool，回退 sysfs
            current = self._collect_via_ethtool()
            if not current:
                current = self._collect_via_sysfs()

        if not current:
            return self.create_result(
                has_alert=False,
                message="端口流量采集无数据（可能无网络端口）",
            )

        now = time.time()
        ts_iso = datetime.now().isoformat()

        records = []
        for port, bytes_data in current.items():
            record = {
                'ts': ts_iso,
                'port': port,
                'tx_bytes': bytes_data['tx_bytes'],
                'rx_bytes': bytes_data['rx_bytes'],
            }

            # 计算速率（需要上次数据）
            if self._last_ts and port in self._last_bytes:
                dt = now - self._last_ts
                if dt > 0:
                    last = self._last_bytes[port]
                    tx_delta = bytes_data['tx_bytes'] - last['tx_bytes']
                    rx_delta = bytes_data['rx_bytes'] - last['rx_bytes']
                    # 处理计数器回绕（64位计数器极少回绕，但做防御）
                    if tx_delta < 0:
                        tx_delta = 0
                    if rx_delta < 0:
                        rx_delta = 0
                    record['tx_rate_bps'] = round(tx_delta * 8 / dt, 2)
                    record['rx_rate_bps'] = round(rx_delta * 8 / dt, 2)

            records.append(record)

        # 更新缓存
        self._last_bytes = current
        self._last_ts = now

        # 写入文件
        if records:
            self._write_records(records)

        # 每 10 次采集清理一次过期数据（避免每次都做 I/O）
        self._cleanup_counter += 1
        if self._cleanup_counter >= 10:
            self._cleanup_counter = 0
            self._cleanup_old_data()

        return self.create_result(
            has_alert=False,
            message=f"已采集 {len(records)} 端口流量数据",
            details={'ports': list(current.keys()), 'record_count': len(records)},
        )

    # ---------- 内置 ethtool 模式（推荐） ----------

    def _collect_via_ethtool(self) -> Dict[str, Dict[str, int]]:
        """
        通过 ethtool -S <port> 获取准确的 TX/RX 字节数。
        ethtool 直接从网卡驱动读取硬件计数器，比 sysfs 更精确。
        """
        result = {}
        ports = self._discover_ports()

        for port in ports:
            ret, stdout, _ = run_command(['ethtool', '-S', port], timeout=5)
            if ret != 0:
                continue

            tx_bytes = None
            rx_bytes = None

            for line in stdout.split('\n'):
                line = line.strip()
                if ':' not in line:
                    continue
                key, value = line.split(':', 1)
                key = key.strip().lower()
                value = value.strip()

                # ethtool -S 的字段名因驱动而异，做通用匹配
                if key in ('tx_bytes', 'tx_octets', 'tx_good_bytes',
                           'port.tx_bytes', 'tx_bytes_nic'):
                    try:
                        tx_bytes = int(value)
                    except (ValueError, TypeError):
                        pass
                elif key in ('rx_bytes', 'rx_octets', 'rx_good_bytes',
                             'port.rx_bytes', 'rx_bytes_nic'):
                    try:
                        rx_bytes = int(value)
                    except (ValueError, TypeError):
                        pass

            if tx_bytes is not None and rx_bytes is not None:
                result[port] = {
                    'tx_bytes': tx_bytes,
                    'rx_bytes': rx_bytes,
                }

        return result

    # ---------- sysfs 回退模式 ----------

    def _collect_via_sysfs(self) -> Dict[str, Dict[str, int]]:
        """
        通过 /sys/class/net/<port>/statistics/ 读取 TX/RX 字节数。
        这是 Linux 标准接口，当 ethtool 不可用时作为回退。
        注意：sysfs 数据可能不如 ethtool 精确。
        """
        result = {}
        ports = self._discover_ports()

        for port in ports:
            stats_path = Path(f'/sys/class/net/{port}/statistics')
            if not stats_path.exists():
                continue

            tx = read_sysfs(stats_path / 'tx_bytes')
            rx = read_sysfs(stats_path / 'rx_bytes')

            if tx is not None and rx is not None:
                try:
                    result[port] = {
                        'tx_bytes': int(tx),
                        'rx_bytes': int(rx),
                    }
                except (ValueError, TypeError):
                    continue

        return result

    def _discover_ports(self) -> List[str]:
        """发现要采集的网络端口"""
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

    def _collect_via_command(self) -> Dict[str, Dict[str, int]]:
        """使用用户自定义命令收集"""
        ret, stdout, stderr = run_command(self.command, shell=True, timeout=10)
        if ret != 0:
            logger.warning(f"[PortTraffic] 自定义命令执行失败: {stderr[:200]}")
            return {}

        result = {}
        for line in stdout.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            m = self.parse_pattern.search(line)
            if m:
                port = m.group('port')
                if self.ports_filter and port not in self.ports_filter:
                    continue
                result[port] = {
                    'tx_bytes': int(m.group('tx_bytes')),
                    'rx_bytes': int(m.group('rx_bytes')),
                }
        return result

    # ---------- 文件写入与清理 ----------

    def _write_records(self, records: List[Dict]):
        """追加写入 traffic.jsonl"""
        try:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.output_path, 'a', encoding='utf-8') as f:
                for rec in records:
                    f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        except Exception as e:
            logger.error(f"写入 traffic.jsonl 失败: {e}")

    def _cleanup_old_data(self):
        """清理超过 retention_hours 的数据"""
        if not self.output_path.exists():
            return

        try:
            cutoff = datetime.now() - timedelta(hours=self.retention_hours)
            cutoff_iso = cutoff.isoformat()

            lines_to_keep = []
            with open(self.output_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if rec.get('ts', '') >= cutoff_iso:
                            lines_to_keep.append(line)
                    except json.JSONDecodeError:
                        continue

            with open(self.output_path, 'w', encoding='utf-8') as f:
                for line in lines_to_keep:
                    f.write(line + '\n')

        except Exception as e:
            logger.error(f"清理 traffic.jsonl 失败: {e}")
