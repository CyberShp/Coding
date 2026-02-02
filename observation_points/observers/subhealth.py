"""
亚健康监测观察点

监测端口级网络链路亚健康比例，包括时延、丢包、乱序。
仅在数值激增时告警，避免频繁打印影响观察。
"""

import logging
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command, read_sysfs, safe_int, safe_float

logger = logging.getLogger(__name__)


class SubhealthObserver(BaseObserver):
    """
    亚健康监测观察点
    
    功能：
    - 监测时延、丢包、乱序等亚健康指标
    - 滑动窗口检测激增
    - 支持端口级和 bond 级聚合
    """
    
    def __init__(self, name: str, config: dict[str, Any]):
        super().__init__(name, config)
        
        self.window_size = config.get('window_size', 5)
        self.spike_threshold_percent = config.get('spike_threshold_percent', 50)
        self.metrics = config.get('metrics', ['latency', 'packet_loss', 'out_of_order'])
        self.ports = config.get('ports', [])
        self.cooldown_seconds = config.get('cooldown_seconds', 60)
        
        # 每个端口的历史数据窗口: {port: {metric: deque}}
        self._history: dict[str, dict[str, deque]] = {}
        
        # 上次告警时间: {port_metric: timestamp}
        self._last_alert_time: dict[str, datetime] = {}
        
        # 内部命令配置（可能需要调用内部工具获取亚健康数据）
        self.internal_command = config.get('internal_command', None)
    
    def check(self) -> ObserverResult:
        """检查亚健康指标"""
        alerts = []
        details = {
            'metrics': {},
            'spikes': [],
        }
        
        ports = self._get_ports_to_check()
        
        for port in ports:
            port_metrics = self._get_port_metrics(port)
            if not port_metrics:
                continue
            
            details['metrics'][port] = port_metrics
            
            # 检查每个指标是否激增
            for metric, value in port_metrics.items():
                if metric not in self.metrics:
                    continue
                
                is_spike, change_percent = self._check_spike(port, metric, value)
                
                if is_spike and self._can_alert(port, metric):
                    alert_msg = f"{port} {metric} 激增 {change_percent:.1f}%"
                    alerts.append(alert_msg)
                    details['spikes'].append({
                        'port': port,
                        'metric': metric,
                        'value': value,
                        'change_percent': change_percent,
                        'timestamp': datetime.now().isoformat(),
                    })
                    
                    self._update_alert_time(port, metric)
                    logger.warning(f"亚健康指标激增: {alert_msg}")
                
                # 更新历史数据
                self._update_history(port, metric, value)
        
        if alerts:
            message = f"检测到亚健康激增: {'; '.join(alerts[:3])}"
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
            message="亚健康检查正常",
            details=details,
        )
    
    def _get_ports_to_check(self) -> list[str]:
        """获取要检查的端口列表"""
        if self.ports:
            return self.ports
        
        # 自动发现网络接口
        ports = []
        net_path = Path('/sys/class/net')
        
        if net_path.exists():
            for item in net_path.iterdir():
                name = item.name
                if name == 'lo' or name.startswith('veth') or name.startswith('docker'):
                    continue
                ports.append(name)
        
        return sorted(ports)
    
    def _get_port_metrics(self, port: str) -> dict[str, float]:
        """获取端口亚健康指标"""
        metrics = {}
        
        # 如果配置了内部命令，使用内部命令获取
        if self.internal_command:
            metrics = self._get_metrics_from_command(port)
            if metrics:
                return metrics
        
        # 否则从 sysfs/netstat 等获取
        metrics = self._get_metrics_from_system(port)
        
        return metrics
    
    def _get_metrics_from_command(self, port: str) -> dict[str, float]:
        """从内部命令获取指标"""
        metrics = {}
        
        cmd = self.internal_command.replace('{port}', port)
        ret, stdout, _ = run_command(cmd, shell=True, timeout=5)
        
        if ret != 0:
            return metrics
        
        # 解析输出（假设格式为 key=value 或 JSON）
        for line in stdout.split('\n'):
            if '=' in line:
                parts = line.split('=', 1)
                if len(parts) == 2:
                    key = parts[0].strip().lower()
                    value = safe_float(parts[1].strip())
                    if key in self.metrics:
                        metrics[key] = value
        
        return metrics
    
    def _get_metrics_from_system(self, port: str) -> dict[str, float]:
        """从系统获取指标"""
        metrics = {}
        
        stats_path = Path(f'/sys/class/net/{port}/statistics')
        
        # 丢包率：通过 rx_dropped/tx_dropped 估算
        if 'packet_loss' in self.metrics:
            rx_packets = safe_int(read_sysfs(stats_path / 'rx_packets'))
            rx_dropped = safe_int(read_sysfs(stats_path / 'rx_dropped'))
            tx_packets = safe_int(read_sysfs(stats_path / 'tx_packets'))
            tx_dropped = safe_int(read_sysfs(stats_path / 'tx_dropped'))
            
            total_packets = rx_packets + tx_packets
            total_dropped = rx_dropped + tx_dropped
            
            if total_packets > 0:
                metrics['packet_loss'] = (total_dropped / total_packets) * 100
            else:
                metrics['packet_loss'] = 0.0
        
        # 乱序：TCP 相关统计
        if 'out_of_order' in self.metrics:
            # 尝试从 /proc/net/netstat 获取 TCP 乱序统计
            out_of_order = self._get_tcp_out_of_order()
            if out_of_order is not None:
                metrics['out_of_order'] = out_of_order
        
        # 时延：需要主动探测或从应用层获取
        # 这里提供一个示例，实际可能需要调用内部命令
        if 'latency' in self.metrics:
            # 尝试使用 ss 或其他工具获取 RTT
            latency = self._get_tcp_rtt(port)
            if latency is not None:
                metrics['latency'] = latency
        
        return metrics
    
    def _get_tcp_out_of_order(self) -> float | None:
        """获取 TCP 乱序统计"""
        try:
            netstat_path = Path('/proc/net/netstat')
            if not netstat_path.exists():
                return None
            
            content = netstat_path.read_text()
            lines = content.split('\n')
            
            # 查找 TcpExt 行
            for i, line in enumerate(lines):
                if line.startswith('TcpExt:') and i + 1 < len(lines):
                    headers = line.split()
                    values = lines[i + 1].split()
                    
                    # 查找 TCPSACKReorder 或类似字段
                    for j, header in enumerate(headers):
                        if 'reorder' in header.lower() or 'ofo' in header.lower():
                            if j < len(values):
                                return safe_float(values[j])
            
            return None
        except Exception as e:
            logger.debug(f"获取 TCP 乱序统计失败: {e}")
            return None
    
    def _get_tcp_rtt(self, port: str) -> float | None:
        """获取 TCP RTT（时延）"""
        try:
            # 使用 ss 命令获取 RTT
            ret, stdout, _ = run_command(['ss', '-ti'], timeout=3)
            if ret != 0:
                return None
            
            rtts = []
            for line in stdout.split('\n'):
                # 查找 rtt: 字段
                if 'rtt:' in line:
                    match = __import__('re').search(r'rtt:(\d+\.?\d*)', line)
                    if match:
                        rtts.append(float(match.group(1)))
            
            if rtts:
                return sum(rtts) / len(rtts)  # 返回平均 RTT
            
            return None
        except Exception as e:
            logger.debug(f"获取 TCP RTT 失败: {e}")
            return None
    
    def _check_spike(self, port: str, metric: str, current_value: float) -> tuple[bool, float]:
        """检测指标是否激增"""
        history = self._get_history(port, metric)
        
        if len(history) < 2:
            return False, 0.0
        
        # 计算历史平均值
        avg = sum(history) / len(history)
        
        if avg == 0:
            # 如果历史平均为0，且当前值大于阈值，认为是激增
            return current_value > 0, 100.0 if current_value > 0 else 0.0
        
        change_percent = ((current_value - avg) / avg) * 100
        is_spike = change_percent > self.spike_threshold_percent
        
        return is_spike, change_percent
    
    def _get_history(self, port: str, metric: str) -> deque:
        """获取历史数据"""
        if port not in self._history:
            self._history[port] = {}
        if metric not in self._history[port]:
            self._history[port][metric] = deque(maxlen=self.window_size)
        return self._history[port][metric]
    
    def _update_history(self, port: str, metric: str, value: float):
        """更新历史数据"""
        history = self._get_history(port, metric)
        history.append(value)
    
    def _can_alert(self, port: str, metric: str) -> bool:
        """检查是否可以告警（冷却检查）"""
        key = f"{port}_{metric}"
        last_time = self._last_alert_time.get(key)
        
        if last_time is None:
            return True
        
        elapsed = (datetime.now() - last_time).total_seconds()
        return elapsed >= self.cooldown_seconds
    
    def _update_alert_time(self, port: str, metric: str):
        """更新告警时间"""
        key = f"{port}_{metric}"
        self._last_alert_time[key] = datetime.now()
