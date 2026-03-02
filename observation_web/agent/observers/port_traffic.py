"""
端口流量采集观察点

归属：端口级（仅采集，不产生告警）
定期采集各端口 TX/RX 流量数据，输出到 traffic.jsonl 文件，
供 web 端拉取后显示流量曲线图。本地保留 2 小时数据。

支持多种采集模式：
- auto: 自动检测协议类型，按优先级尝试各模式
- ethtool: 通过 ethtool -S 获取 NIC 层统计（内核协议栈流量）
- sysfs: 通过 /sys/class/net/ 获取统计（回退模式）
- rdma: 通过 /sys/class/infiniband/ 获取 RDMA/RoCE 流量
- toe: 通过 ethtool 获取 TCP Offload Engine 流量
- command: 使用用户自定义命令

对于绕过内核协议栈的协议（RDMA/RoCE、iSCSI with TOE），
需使用对应的采集模式才能获取真实数据平面流量。
"""

import json
import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command, read_sysfs

logger = logging.getLogger(__name__)


# 采集模式常量
MODE_AUTO = 'auto'
MODE_ETHTOOL = 'ethtool'
MODE_SYSFS = 'sysfs'
MODE_RDMA = 'rdma'
MODE_TOE = 'toe'
MODE_COMMAND = 'command'

# 协议类型
PROTOCOL_ETHERNET = 'ethernet'
PROTOCOL_RDMA = 'rdma'
PROTOCOL_ROCE = 'roce'
PROTOCOL_TOE = 'toe'
PROTOCOL_UNKNOWN = 'unknown'


class PortTrafficObserver(BaseObserver):
    """
    端口流量采集器

    工作方式（多种模式）：
    1. auto 模式（默认）：自动检测协议类型，选择合适的采集方式
       - 检测到 RDMA/RoCE 设备时使用 rdma 模式
       - 检测到 TOE offload 时使用 toe 模式
       - 否则使用 ethtool/sysfs
    2. ethtool 模式：通过 ethtool -S <port> 获取 NIC 层统计
    3. sysfs 模式：通过 /sys/class/net/ 读取（回退）
    4. rdma 模式：通过 /sys/class/infiniband/ 读取 RDMA 流量
    5. toe 模式：通过 ethtool 读取 TOE offload 统计
    6. command 模式：使用用户自定义命令

    配置项：
    - mode: 采集模式 (auto/ethtool/sysfs/rdma/toe/command)
    - command: 自定义命令（mode=command 时使用）
    - output_path: traffic.jsonl 文件路径
    - ports: 要采集的端口列表（可选，为空则自动发现）
    - retention_hours: 本地保留时长（默认 2）
    - parse_pattern: 自定义命令的解析正则
    """

    DEFAULT_PATTERN = r'(?P<port>\S+)\s+(?P<tx_bytes>\d+)\s+(?P<rx_bytes>\d+)'

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.mode = config.get('mode', MODE_AUTO)
        self.command = config.get('command', '')
        self.output_path = Path(
            config.get('output_path', '/var/log/observation-points/traffic.jsonl')
        )
        self.ports_filter = set(config.get('ports', []))
        self.parse_pattern = re.compile(
            config.get('parse_pattern', self.DEFAULT_PATTERN)
        )
        self.retention_hours = config.get('retention_hours', 2)

        self._last_bytes: Dict[str, Dict[str, int]] = {}
        self._last_ts: Optional[float] = None
        self._cleanup_counter = 0
        self._detected_protocol: str = PROTOCOL_UNKNOWN
        self._detected_mode: str = MODE_ETHTOOL
        self._rdma_devices: Dict[str, Dict] = {}
        self._toe_ports: List[str] = []

    def check(self, reporter=None) -> ObserverResult:
        """采集流量数据（不产生告警）"""
        current: Dict[str, Dict[str, int]] = {}
        active_mode = self.mode
        detected_protocol = PROTOCOL_ETHERNET

        if self.mode == MODE_COMMAND and self.command:
            current = self._collect_via_command()
            active_mode = MODE_COMMAND
        elif self.mode == MODE_AUTO:
            current, active_mode, detected_protocol = self._collect_auto()
        elif self.mode == MODE_RDMA:
            current = self._collect_via_rdma()
            detected_protocol = PROTOCOL_RDMA if current else PROTOCOL_UNKNOWN
        elif self.mode == MODE_TOE:
            current = self._collect_via_toe()
            detected_protocol = PROTOCOL_TOE if current else PROTOCOL_UNKNOWN
        elif self.mode == MODE_ETHTOOL:
            current = self._collect_via_ethtool()
        elif self.mode == MODE_SYSFS:
            current = self._collect_via_sysfs()
        else:
            current = self._collect_via_ethtool()
            if not current:
                current = self._collect_via_sysfs()

        self._detected_mode = active_mode
        self._detected_protocol = detected_protocol

        if not current:
            return self.create_result(
                has_alert=False,
                message="端口流量采集无数据（可能无网络端口）",
                details={
                    'mode': active_mode,
                    'protocol': detected_protocol,
                },
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
                'mode': active_mode,
                'protocol': bytes_data.get('protocol', detected_protocol),
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

        if reporter and hasattr(reporter, 'record_metrics'):
            for rec in records:
                reporter.record_metrics({
                    'port': rec['port'],
                    'tx_rate_bps': rec.get('tx_rate_bps', 0),
                    'rx_rate_bps': rec.get('rx_rate_bps', 0),
                    'mode': active_mode,
                    'protocol': detected_protocol,
                    'observer': self.name,
                })

        return self.create_result(
            has_alert=False,
            message=f"已采集 {len(records)} 端口流量数据 (模式: {active_mode}, 协议: {detected_protocol})",
            details={
                'ports': list(current.keys()),
                'record_count': len(records),
                'mode': active_mode,
                'protocol': detected_protocol,
            },
        )

    # ---------- 自动检测模式 ----------

    def _collect_auto(self) -> Tuple[Dict[str, Dict[str, int]], str, str]:
        """
        自动检测协议类型并选择合适的采集方式。
        优先级：RDMA > TOE > ethtool > sysfs
        """
        # 检测 RDMA/RoCE 设备
        rdma_data = self._collect_via_rdma()
        if rdma_data:
            logger.info("[PortTraffic] 检测到 RDMA/RoCE 流量，使用 rdma 模式")
            return rdma_data, MODE_RDMA, PROTOCOL_RDMA

        # 检测 TOE offload
        toe_data = self._collect_via_toe()
        if toe_data:
            logger.info("[PortTraffic] 检测到 TOE offload 流量，使用 toe 模式")
            return toe_data, MODE_TOE, PROTOCOL_TOE

        # 回退到 ethtool
        ethtool_data = self._collect_via_ethtool()
        if ethtool_data:
            return ethtool_data, MODE_ETHTOOL, PROTOCOL_ETHERNET

        # 最后回退到 sysfs
        sysfs_data = self._collect_via_sysfs()
        return sysfs_data, MODE_SYSFS, PROTOCOL_ETHERNET

    # ---------- RDMA/InfiniBand 模式 ----------

    def _collect_via_rdma(self) -> Dict[str, Dict[str, int]]:
        """
        通过 /sys/class/infiniband/ 采集 RDMA/RoCE 流量。
        RDMA 流量绕过内核 TCP/IP 协议栈，普通 ethtool/sysfs 无法采集。
        """
        result = {}
        infiniband_path = Path('/sys/class/infiniband')

        if not infiniband_path.exists():
            return result

        for device_path in infiniband_path.iterdir():
            device_name = device_path.name
            ports_path = device_path / 'ports'

            if not ports_path.exists():
                continue

            for port_path in ports_path.iterdir():
                port_num = port_path.name
                counters_path = port_path / 'counters'
                hw_counters_path = port_path / 'hw_counters'

                tx_bytes = 0
                rx_bytes = 0
                port_key = f"{device_name}/{port_num}"

                # 尝试硬件计数器（更准确）
                if hw_counters_path.exists():
                    tx = read_sysfs(hw_counters_path / 'port_xmit_data')
                    rx = read_sysfs(hw_counters_path / 'port_rcv_data')
                    if tx is not None:
                        try:
                            tx_bytes = int(tx) * 4  # IB 计数器单位是 4 字节
                        except ValueError:
                            pass
                    if rx is not None:
                        try:
                            rx_bytes = int(rx) * 4
                        except ValueError:
                            pass

                # 回退到标准计数器
                if tx_bytes == 0 and rx_bytes == 0 and counters_path.exists():
                    tx = read_sysfs(counters_path / 'port_xmit_data')
                    rx = read_sysfs(counters_path / 'port_rcv_data')
                    if tx is not None:
                        try:
                            tx_bytes = int(tx) * 4
                        except ValueError:
                            pass
                    if rx is not None:
                        try:
                            rx_bytes = int(rx) * 4
                        except ValueError:
                            pass

                if tx_bytes > 0 or rx_bytes > 0:
                    # 检测是否为 RoCE（通过 link_layer）
                    link_layer = read_sysfs(port_path / 'link_layer')
                    protocol = PROTOCOL_ROCE if link_layer == 'Ethernet' else PROTOCOL_RDMA

                    result[port_key] = {
                        'tx_bytes': tx_bytes,
                        'rx_bytes': rx_bytes,
                        'protocol': protocol,
                        'device': device_name,
                        'port': port_num,
                    }

                    self._rdma_devices[port_key] = {
                        'device': device_name,
                        'port': port_num,
                        'link_layer': link_layer,
                    }

        return result

    # ---------- TOE (TCP Offload Engine) 模式 ----------

    def _collect_via_toe(self) -> Dict[str, Dict[str, int]]:
        """
        采集 TCP Offload Engine (TOE) 流量。
        iSCSI with TOE 会绕过内核协议栈，需要从网卡获取 offload 统计。
        """
        result = {}
        ports = self._discover_ports()

        for port in ports:
            # 检测是否支持 TOE
            ret, stdout, _ = run_command(['ethtool', '-k', port], timeout=5)
            if ret != 0:
                continue

            has_toe = False
            for line in stdout.split('\n'):
                line_lower = line.lower()
                if 'tcp-segmentation-offload' in line_lower or 'tso' in line_lower:
                    if ': on' in line_lower:
                        has_toe = True
                        break

            if not has_toe:
                continue

            # 获取 TOE 统计
            ret, stdout, _ = run_command(['ethtool', '-S', port], timeout=5)
            if ret != 0:
                continue

            tx_bytes = 0
            rx_bytes = 0
            toe_tx = 0
            toe_rx = 0

            for line in stdout.split('\n'):
                line = line.strip()
                if ':' not in line:
                    continue
                key, value = line.split(':', 1)
                key = key.strip().lower()
                value = value.strip()

                try:
                    val = int(value)
                except ValueError:
                    continue

                # TOE 特定计数器（因驱动而异）
                if 'tso_packets' in key or 'tx_tso' in key:
                    toe_tx += val
                elif 'lro_bytes' in key or 'rx_lro' in key:
                    toe_rx += val
                elif key in ('tx_bytes', 'tx_octets', 'tx_good_bytes'):
                    tx_bytes = val
                elif key in ('rx_bytes', 'rx_octets', 'rx_good_bytes'):
                    rx_bytes = val

            # 如果有 TOE 流量，记录
            if toe_tx > 0 or toe_rx > 0 or (tx_bytes > 0 and rx_bytes > 0):
                result[port] = {
                    'tx_bytes': tx_bytes,
                    'rx_bytes': rx_bytes,
                    'toe_tx_packets': toe_tx,
                    'toe_rx_bytes': toe_rx,
                    'protocol': PROTOCOL_TOE,
                }
                self._toe_ports.append(port)

        return result

    def get_diagnostic_info(self) -> Dict[str, Any]:
        """获取流量采集诊断信息"""
        return {
            'configured_mode': self.mode,
            'active_mode': self._detected_mode,
            'detected_protocol': self._detected_protocol,
            'rdma_devices': self._rdma_devices,
            'toe_ports': self._toe_ports,
            'ports_filter': list(self.ports_filter),
            'available_modes': [MODE_AUTO, MODE_ETHTOOL, MODE_SYSFS, MODE_RDMA, MODE_TOE, MODE_COMMAND],
        }

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
