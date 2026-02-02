"""
性能波动监测观察点

监测存储协议性能场景（iSCSI/NAS/NVMe）的 IOPS、带宽、时延波动。
波动率超过 10% 时告警。
支持 bond 级、单端口级、多端口级的性能监测。
"""

import logging
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command, read_sysfs, safe_int, safe_float

logger = logging.getLogger(__name__)


class PerformanceObserver(BaseObserver):
    """
    性能波动监测观察点
    
    功能：
    - 监测 IOPS、带宽、时延
    - 滑动窗口检测波动率
    - 支持多维度（bond、端口）
    - 可配置最小阈值避免低负载误报
    """
    
    def __init__(self, name: str, config: dict[str, Any]):
        super().__init__(name, config)
        
        self.window_size = config.get('window_size', 5)
        self.fluctuation_threshold_percent = config.get('fluctuation_threshold_percent', 10)
        self.min_iops_threshold = config.get('min_iops_threshold', 100)
        self.min_bandwidth_threshold_mbps = config.get('min_bandwidth_threshold_mbps', 10)
        self.metrics = config.get('metrics', ['iops', 'bandwidth', 'latency'])
        self.dimensions = config.get('dimensions', ['bond', 'port'])
        self.protocols = config.get('protocols', ['iscsi', 'nvme', 'nas'])
        self.cooldown_seconds = config.get('cooldown_seconds', 60)
        
        # 内部命令（用于获取性能数据）
        self.internal_command = config.get('internal_command', None)
        
        # 历史数据: {dimension_id: {metric: deque}}
        self._history: dict[str, dict[str, deque]] = {}
        
        # 上次采集的原始数据（用于计算增量）
        self._last_raw: dict[str, dict[str, Any]] = {}
        
        # 上次告警时间
        self._last_alert_time: dict[str, datetime] = {}
    
    def check(self) -> ObserverResult:
        """检查性能波动"""
        alerts = []
        details = {
            'metrics': {},
            'fluctuations': [],
        }
        
        # 获取各维度的性能数据
        performance_data = self._collect_performance_data()
        
        for dimension_id, metrics in performance_data.items():
            details['metrics'][dimension_id] = metrics
            
            for metric, value in metrics.items():
                if metric not in self.metrics:
                    continue
                
                # 检查最小阈值
                if not self._meets_minimum_threshold(metric, value):
                    continue
                
                # 检查波动率
                is_fluctuating, change_percent = self._check_fluctuation(
                    dimension_id, metric, value
                )
                
                if is_fluctuating and self._can_alert(dimension_id, metric):
                    alert_msg = (
                        f"{dimension_id} {metric} 波动 {abs(change_percent):.1f}% "
                        f"(当前: {self._format_value(metric, value)})"
                    )
                    alerts.append(alert_msg)
                    details['fluctuations'].append({
                        'dimension': dimension_id,
                        'metric': metric,
                        'value': value,
                        'change_percent': change_percent,
                        'timestamp': datetime.now().isoformat(),
                    })
                    
                    self._update_alert_time(dimension_id, metric)
                    logger.warning(f"性能波动告警: {alert_msg}")
                
                # 更新历史
                self._update_history(dimension_id, metric, value)
        
        if alerts:
            message = f"检测到性能波动: {'; '.join(alerts[:3])}"
            if len(alerts) > 3:
                message += f" (共 {len(alerts)} 项)"
            
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message=message,
                details=details,
            )
        
        return self.create_result(
            has_alert=False,
            message="性能检查正常",
            details=details,
        )
    
    def _collect_performance_data(self) -> dict[str, dict[str, float]]:
        """收集各维度的性能数据"""
        data = {}
        
        # 如果有内部命令，优先使用
        if self.internal_command:
            data = self._collect_from_command()
            if data:
                return data
        
        # 否则从系统收集
        data = self._collect_from_system()
        
        return data
    
    def _collect_from_command(self) -> dict[str, dict[str, float]]:
        """从内部命令收集性能数据"""
        data = {}
        
        ret, stdout, _ = run_command(self.internal_command, shell=True, timeout=10)
        if ret != 0:
            logger.debug(f"内部命令执行失败: {self.internal_command}")
            return data
        
        # 解析输出
        # 期望格式：
        # dimension metric=value metric2=value2
        # 或 JSON 格式
        current_dimension = None
        
        for line in stdout.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # 尝试解析 key=value 格式
            if '=' in line:
                parts = line.split()
                if len(parts) >= 2 and '=' not in parts[0]:
                    # 第一个部分是维度名
                    current_dimension = parts[0]
                    data[current_dimension] = {}
                    parts = parts[1:]
                
                if current_dimension:
                    for part in parts:
                        if '=' in part:
                            key, val = part.split('=', 1)
                            data[current_dimension][key.lower()] = safe_float(val)
            else:
                # 可能是维度名
                current_dimension = line
                data[current_dimension] = {}
        
        return data
    
    def _collect_from_system(self) -> dict[str, dict[str, float]]:
        """从系统收集性能数据"""
        data = {}
        
        # 收集网络接口性能
        if 'port' in self.dimensions:
            port_data = self._collect_port_performance()
            data.update(port_data)
        
        # 收集 bond 性能
        if 'bond' in self.dimensions:
            bond_data = self._collect_bond_performance()
            data.update(bond_data)
        
        # 收集块设备性能（用于 iSCSI/NVMe 目标）
        block_data = self._collect_block_performance()
        data.update(block_data)
        
        return data
    
    def _collect_port_performance(self) -> dict[str, dict[str, float]]:
        """收集端口级性能"""
        data = {}
        
        net_path = Path('/sys/class/net')
        if not net_path.exists():
            return data
        
        for item in net_path.iterdir():
            name = item.name
            if name == 'lo' or name.startswith('veth') or name.startswith('docker'):
                continue
            
            stats_path = item / 'statistics'
            if not stats_path.exists():
                continue
            
            # 读取当前值
            rx_bytes = safe_int(read_sysfs(stats_path / 'rx_bytes'))
            tx_bytes = safe_int(read_sysfs(stats_path / 'tx_bytes'))
            rx_packets = safe_int(read_sysfs(stats_path / 'rx_packets'))
            tx_packets = safe_int(read_sysfs(stats_path / 'tx_packets'))
            
            # 计算增量（需要与上次比较）
            port_key = f"port:{name}"
            last = self._last_raw.get(port_key, {})
            
            now = datetime.now()
            last_time = last.get('timestamp')
            
            if last_time:
                elapsed = (now - last_time).total_seconds()
                if elapsed > 0:
                    # 计算速率
                    bandwidth_rx = (rx_bytes - last.get('rx_bytes', rx_bytes)) * 8 / elapsed / 1_000_000  # Mbps
                    bandwidth_tx = (tx_bytes - last.get('tx_bytes', tx_bytes)) * 8 / elapsed / 1_000_000
                    iops_rx = (rx_packets - last.get('rx_packets', rx_packets)) / elapsed
                    iops_tx = (tx_packets - last.get('tx_packets', tx_packets)) / elapsed
                    
                    data[port_key] = {
                        'bandwidth': bandwidth_rx + bandwidth_tx,
                        'iops': iops_rx + iops_tx,
                    }
            
            # 更新原始数据
            self._last_raw[port_key] = {
                'rx_bytes': rx_bytes,
                'tx_bytes': tx_bytes,
                'rx_packets': rx_packets,
                'tx_packets': tx_packets,
                'timestamp': now,
            }
        
        return data
    
    def _collect_bond_performance(self) -> dict[str, dict[str, float]]:
        """收集 bond 级性能"""
        data = {}
        
        net_path = Path('/sys/class/net')
        if not net_path.exists():
            return data
        
        for item in net_path.iterdir():
            # 检查是否是 bond
            if not (item / 'bonding').exists():
                continue
            
            name = item.name
            stats_path = item / 'statistics'
            
            if not stats_path.exists():
                continue
            
            # 与端口类似的处理
            rx_bytes = safe_int(read_sysfs(stats_path / 'rx_bytes'))
            tx_bytes = safe_int(read_sysfs(stats_path / 'tx_bytes'))
            rx_packets = safe_int(read_sysfs(stats_path / 'rx_packets'))
            tx_packets = safe_int(read_sysfs(stats_path / 'tx_packets'))
            
            bond_key = f"bond:{name}"
            last = self._last_raw.get(bond_key, {})
            
            now = datetime.now()
            last_time = last.get('timestamp')
            
            if last_time:
                elapsed = (now - last_time).total_seconds()
                if elapsed > 0:
                    bandwidth_rx = (rx_bytes - last.get('rx_bytes', rx_bytes)) * 8 / elapsed / 1_000_000
                    bandwidth_tx = (tx_bytes - last.get('tx_bytes', tx_bytes)) * 8 / elapsed / 1_000_000
                    iops_rx = (rx_packets - last.get('rx_packets', rx_packets)) / elapsed
                    iops_tx = (tx_packets - last.get('tx_packets', tx_packets)) / elapsed
                    
                    data[bond_key] = {
                        'bandwidth': bandwidth_rx + bandwidth_tx,
                        'iops': iops_rx + iops_tx,
                    }
            
            self._last_raw[bond_key] = {
                'rx_bytes': rx_bytes,
                'tx_bytes': tx_bytes,
                'rx_packets': rx_packets,
                'tx_packets': tx_packets,
                'timestamp': now,
            }
        
        return data
    
    def _collect_block_performance(self) -> dict[str, dict[str, float]]:
        """收集块设备性能（用于 iSCSI/NVMe 目标侧）"""
        data = {}
        
        # 读取 /proc/diskstats 或 /sys/block/*/stat
        block_path = Path('/sys/block')
        if not block_path.exists():
            return data
        
        for item in block_path.iterdir():
            name = item.name
            # 过滤常见的本地盘，只关注可能是 iSCSI/NVMe 的设备
            if name.startswith(('loop', 'ram', 'dm-')):
                continue
            
            stat_path = item / 'stat'
            if not stat_path.exists():
                continue
            
            stat_content = read_sysfs(stat_path)
            if not stat_content:
                continue
            
            # /sys/block/*/stat 格式（空格分隔）：
            # read_ios read_merges read_sectors read_ticks
            # write_ios write_merges write_sectors write_ticks
            # in_flight io_ticks time_in_queue
            parts = stat_content.split()
            if len(parts) < 11:
                continue
            
            read_ios = safe_int(parts[0])
            read_sectors = safe_int(parts[2])
            write_ios = safe_int(parts[4])
            write_sectors = safe_int(parts[6])
            io_ticks = safe_int(parts[9])  # 毫秒
            
            block_key = f"block:{name}"
            last = self._last_raw.get(block_key, {})
            
            now = datetime.now()
            last_time = last.get('timestamp')
            
            if last_time:
                elapsed = (now - last_time).total_seconds()
                if elapsed > 0:
                    iops = ((read_ios - last.get('read_ios', read_ios)) +
                            (write_ios - last.get('write_ios', write_ios))) / elapsed
                    
                    sectors = ((read_sectors - last.get('read_sectors', read_sectors)) +
                               (write_sectors - last.get('write_sectors', write_sectors)))
                    bandwidth = sectors * 512 / elapsed / 1_000_000  # MB/s
                    
                    # 时延估算
                    io_count = iops * elapsed
                    if io_count > 0:
                        ticks_delta = io_ticks - last.get('io_ticks', io_ticks)
                        latency = ticks_delta / io_count if io_count > 0 else 0  # ms
                    else:
                        latency = 0
                    
                    data[block_key] = {
                        'iops': iops,
                        'bandwidth': bandwidth,
                        'latency': latency,
                    }
            
            self._last_raw[block_key] = {
                'read_ios': read_ios,
                'read_sectors': read_sectors,
                'write_ios': write_ios,
                'write_sectors': write_sectors,
                'io_ticks': io_ticks,
                'timestamp': now,
            }
        
        return data
    
    def _meets_minimum_threshold(self, metric: str, value: float) -> bool:
        """检查是否达到最小阈值"""
        if metric == 'iops':
            return value >= self.min_iops_threshold
        elif metric == 'bandwidth':
            return value >= self.min_bandwidth_threshold_mbps
        return True  # 其他指标默认检查
    
    def _check_fluctuation(self, dimension_id: str, metric: str, 
                          current_value: float) -> tuple[bool, float]:
        """检测波动率"""
        history = self._get_history(dimension_id, metric)
        
        if len(history) < 2:
            return False, 0.0
        
        # 计算历史平均值
        avg = sum(history) / len(history)
        
        if avg == 0:
            return False, 0.0
        
        change_percent = ((current_value - avg) / avg) * 100
        is_fluctuating = abs(change_percent) > self.fluctuation_threshold_percent
        
        return is_fluctuating, change_percent
    
    def _get_history(self, dimension_id: str, metric: str) -> deque:
        """获取历史数据"""
        if dimension_id not in self._history:
            self._history[dimension_id] = {}
        if metric not in self._history[dimension_id]:
            self._history[dimension_id][metric] = deque(maxlen=self.window_size)
        return self._history[dimension_id][metric]
    
    def _update_history(self, dimension_id: str, metric: str, value: float):
        """更新历史数据"""
        history = self._get_history(dimension_id, metric)
        history.append(value)
    
    def _can_alert(self, dimension_id: str, metric: str) -> bool:
        """检查是否可以告警"""
        key = f"{dimension_id}_{metric}"
        last_time = self._last_alert_time.get(key)
        
        if last_time is None:
            return True
        
        elapsed = (datetime.now() - last_time).total_seconds()
        return elapsed >= self.cooldown_seconds
    
    def _update_alert_time(self, dimension_id: str, metric: str):
        """更新告警时间"""
        key = f"{dimension_id}_{metric}"
        self._last_alert_time[key] = datetime.now()
    
    def _format_value(self, metric: str, value: float) -> str:
        """格式化指标值"""
        if metric == 'iops':
            return f"{value:.0f} IOPS"
        elif metric == 'bandwidth':
            if value >= 1000:
                return f"{value/1000:.2f} Gbps"
            return f"{value:.2f} Mbps"
        elif metric == 'latency':
            if value >= 1000:
                return f"{value/1000:.2f} s"
            return f"{value:.2f} ms"
        return f"{value:.2f}"
