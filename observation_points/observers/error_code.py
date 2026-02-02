"""
误码监测观察点

监测端口误码和 PCIe 链路误码。
支持增量检测，仅当新增误码超过阈值时告警。
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command, read_sysfs, safe_int

logger = logging.getLogger(__name__)


class ErrorCodeObserver(BaseObserver):
    """
    误码监测观察点
    
    功能：
    - 监测网络端口误码（通过 ethtool 或 sysfs）
    - 监测 PCIe 链路误码
    - 增量检测：仅告警新增的误码
    """
    
    # 关注的 ethtool 误码计数器
    ETHTOOL_ERROR_COUNTERS = [
        'rx_errors',
        'tx_errors',
        'rx_dropped',
        'tx_dropped',
        'rx_crc_errors',
        'rx_frame_errors',
        'rx_fifo_errors',
        'tx_fifo_errors',
        'rx_missed_errors',
        'collisions',
    ]
    
    # PCIe AER 错误类型
    PCIE_AER_ERRORS = [
        'BadTLP',
        'BadDLLP',
        'CorrIntErr',
        'RxErr',
        'Rollover',
        'Timeout',
        'NonFatalErr',
        'FatalErr',
        'UnsupReq',
    ]
    
    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.threshold = config.get('threshold', 0)
        self.ports = config.get('ports', [])
        self.pcie_enabled = config.get('pcie_enabled', True)
        self.protocols = config.get('protocols', ['iscsi', 'nvme', 'nas'])
        self._last_port_errors = {}  # type: Dict[str, Dict[str, int]]
        self._last_pcie_errors = {}  # type: Dict[str, Dict[str, int]]
    
    def check(self) -> ObserverResult:
        """执行误码检查"""
        alerts = []
        details = {
            'port_errors': {},
            'pcie_errors': {},
        }
        
        # 检查端口误码
        port_alerts = self._check_port_errors()
        alerts.extend(port_alerts)
        details['port_errors'] = self._last_port_errors
        
        # 检查 PCIe 误码
        if self.pcie_enabled:
            pcie_alerts = self._check_pcie_errors()
            alerts.extend(pcie_alerts)
            details['pcie_errors'] = self._last_pcie_errors
        
        if alerts:
            message = f"检测到误码: {'; '.join(alerts[:5])}"
            if len(alerts) > 5:
                message += f" (共 {len(alerts)} 项)"
            
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message=message,
                details=details,
            )
        
        return self.create_result(
            has_alert=False,
            message="误码检查正常",
            details=details,
        )
    
    def _check_port_errors(self) -> List[str]:
        """检查端口误码"""
        alerts = []
        
        # 获取要检查的端口列表
        ports = self._get_ports_to_check()
        
        for port in ports:
            errors = self._get_port_error_counters(port)
            if not errors:
                continue
            
            # 获取上次值
            last_errors = self._last_port_errors.get(port, {})
            
            # 检查增量
            for counter, value in errors.items():
                last_value = last_errors.get(counter, 0)
                delta = value - last_value
                
                # 首次运行或值回绕时，不告警
                if port not in self._last_port_errors:
                    continue
                
                if delta < 0:
                    # 计数器回绕或重置，跳过
                    continue
                
                if delta > self.threshold:
                    alerts.append(f"{port}.{counter} 新增 {delta}")
                    logger.warning(f"端口 {port} 误码 {counter} 新增: {delta}")
            
            # 更新缓存
            self._last_port_errors[port] = errors
        
        return alerts
    
    def _check_pcie_errors(self) -> List[str]:
        """检查 PCIe 误码"""
        alerts = []
        
        # 获取 PCIe 设备的 AER 错误
        pcie_errors = self._get_pcie_aer_errors()
        
        for device, errors in pcie_errors.items():
            last_errors = self._last_pcie_errors.get(device, {})
            
            for error_type, count in errors.items():
                last_count = last_errors.get(error_type, 0)
                delta = count - last_count
                
                if device not in self._last_pcie_errors:
                    continue
                
                if delta < 0:
                    continue
                
                if delta > self.threshold:
                    alerts.append(f"PCIe {device} {error_type} 新增 {delta}")
                    logger.warning(f"PCIe 设备 {device} 错误 {error_type} 新增: {delta}")
            
            self._last_pcie_errors[device] = errors
        
        return alerts
    
    def _get_ports_to_check(self) -> List[str]:
        """获取要检查的端口列表"""
        if self.ports:
            return self.ports
        
        # 自动发现网络接口
        ports = []
        net_path = Path('/sys/class/net')
        
        if net_path.exists():
            for item in net_path.iterdir():
                name = item.name
                # 排除 lo 和虚拟接口
                if name == 'lo' or name.startswith('veth') or name.startswith('docker'):
                    continue
                ports.append(name)
        
        return sorted(ports)
    
    def _get_port_error_counters(self, port: str) -> Dict[str, int]:
        """获取端口误码计数器"""
        errors = {}
        
        # 方法1: 通过 sysfs 读取
        stats_path = Path(f'/sys/class/net/{port}/statistics')
        if stats_path.exists():
            for counter in self.ETHTOOL_ERROR_COUNTERS:
                value = read_sysfs(stats_path / counter)
                if value is not None:
                    errors[counter] = safe_int(value)
        
        # 方法2: 通过 ethtool（如果 sysfs 不完整）
        if not errors:
            errors = self._get_ethtool_stats(port)
        
        return errors
    
    def _get_ethtool_stats(self, port: str) -> Dict[str, int]:
        """通过 ethtool 获取统计信息"""
        errors = {}
        
        ret, stdout, _ = run_command(['ethtool', '-S', port], timeout=5)
        if ret != 0:
            return errors
        
        for line in stdout.split('\n'):
            line = line.strip()
            if ':' not in line:
                continue
            
            key, value = line.split(':', 1)
            key = key.strip().lower()
            value = value.strip()
            
            # 只关注错误相关的计数器
            if any(err in key for err in ['error', 'drop', 'crc', 'fifo', 'miss', 'collision']):
                errors[key] = safe_int(value)
        
        return errors
    
    def _get_pcie_aer_errors(self) -> Dict[str, Dict[str, int]]:
        """获取 PCIe AER 错误统计"""
        result = {}
        
        # 遍历 /sys/bus/pci/devices/*/aer_dev_correctable
        pci_path = Path('/sys/bus/pci/devices')
        if not pci_path.exists():
            return result
        
        for device_path in pci_path.iterdir():
            device_name = device_path.name
            errors = {}
            
            # 读取可纠正错误
            correctable = read_sysfs(device_path / 'aer_dev_correctable')
            if correctable:
                errors.update(self._parse_aer_stats(correctable))
            
            # 读取不可纠正错误
            uncorrectable = read_sysfs(device_path / 'aer_dev_nonfatal')
            if uncorrectable:
                errors.update(self._parse_aer_stats(uncorrectable, prefix='nonfatal_'))
            
            fatal = read_sysfs(device_path / 'aer_dev_fatal')
            if fatal:
                errors.update(self._parse_aer_stats(fatal, prefix='fatal_'))
            
            if errors:
                result[device_name] = errors
        
        return result
    
    def _parse_aer_stats(self, content: str, prefix: str = '') -> Dict[str, int]:
        """解析 AER 统计信息"""
        errors = {}
        
        for line in content.split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # 格式: ErrorType 123
            parts = line.split()
            if len(parts) >= 2:
                error_type = prefix + parts[0]
                count = safe_int(parts[-1])
                if count > 0:
                    errors[error_type] = count
        
        return errors
