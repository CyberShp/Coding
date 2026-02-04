"""
端口计数器监测观察点

监测端口统计计数器和 PCIe 链路误码。
按类型分类：误码、丢包、FIFO/队列、聚合统计等。
支持增量检测，仅当新增计数超过阈值时告警。
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
    端口计数器监测观察点
    
    功能：
    - 监测网络端口统计计数器（通过 ethtool 或 sysfs）
    - 监测 PCIe 链路误码
    - 按类型分类告警：误码、丢包、FIFO/队列、聚合统计
    - 增量检测：仅告警新增的计数
    """
    
    # 计数器分类
    COUNTER_CATEGORIES = {
        # 真正的误码（链路层错误）
        'error_code': {
            'name': '误码',
            'level': AlertLevel.WARNING,
            'counters': [
                'rx_crc_errors',
                'fcs_errors',
                'rx_frame_errors',
                'tx_carrier_errors',
            ]
        },
        # 丢包统计
        'dropped': {
            'name': '丢包',
            'level': AlertLevel.WARNING,
            'counters': [
                'rx_dropped',
                'tx_dropped',
            ]
        },
        # FIFO/队列错误
        'fifo': {
            'name': 'FIFO队列',
            'level': AlertLevel.INFO,
            'counters': [
                'rx_fifo_errors',
                'tx_fifo_errors',
                'rx_missed_errors',
            ]
        },
        # 聚合统计（可能包含上述分类的汇总）
        'aggregated': {
            'name': '聚合统计',
            'level': AlertLevel.INFO,
            'counters': [
                'rx_errors',
                'tx_errors',
                'collisions',
            ]
        },
    }
    
    # 所有要监控的计数器（扁平化列表）
    ALL_COUNTERS = []
    for cat_info in COUNTER_CATEGORIES.values():
        ALL_COUNTERS.extend(cat_info['counters'])
    
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
    
    def _get_counter_category(self, counter_name: str) -> tuple:
        """获取计数器所属分类及其信息"""
        for cat_key, cat_info in self.COUNTER_CATEGORIES.items():
            if counter_name in cat_info['counters']:
                return cat_key, cat_info['name'], cat_info['level']
        # 默认归类为聚合统计
        return 'aggregated', '其他', AlertLevel.INFO
    
    def check(self) -> ObserverResult:
        """执行计数器检查"""
        # 按分类收集告警
        categorized_alerts = {}  # type: Dict[str, List[str]]
        details = {
            'port_counters': {},
            'pcie_errors': {},
            'by_category': {},
        }
        
        # 检查端口计数器
        port_alerts = self._check_port_counters()
        for alert_info in port_alerts:
            cat_key = alert_info['category']
            if cat_key not in categorized_alerts:
                categorized_alerts[cat_key] = []
            categorized_alerts[cat_key].append(alert_info['message'])
        
        details['port_counters'] = self._last_port_errors
        
        # 检查 PCIe 误码
        if self.pcie_enabled:
            pcie_alerts = self._check_pcie_errors()
            if pcie_alerts:
                if 'pcie' not in categorized_alerts:
                    categorized_alerts['pcie'] = []
                categorized_alerts['pcie'].extend(pcie_alerts)
            details['pcie_errors'] = self._last_pcie_errors
        
        # 汇总统计
        details['by_category'] = {
            cat: len(alerts) for cat, alerts in categorized_alerts.items()
        }
        
        if categorized_alerts:
            # 构建分类消息
            message_parts = []
            max_level = AlertLevel.INFO
            
            for cat_key, alerts in categorized_alerts.items():
                if cat_key == 'pcie':
                    cat_name = 'PCIe误码'
                    cat_level = AlertLevel.WARNING
                else:
                    cat_info = self.COUNTER_CATEGORIES.get(cat_key, {})
                    cat_name = cat_info.get('name', cat_key)
                    cat_level = cat_info.get('level', AlertLevel.INFO)
                
                # 取最高告警级别
                if cat_level.value > max_level.value:
                    max_level = cat_level
                
                # 每个分类显示前2个告警
                sample = alerts[:2]
                if len(alerts) > 2:
                    message_parts.append(f"{cat_name}: {'; '.join(sample)} (共{len(alerts)}项)")
                else:
                    message_parts.append(f"{cat_name}: {'; '.join(sample)}")
            
            message = " | ".join(message_parts)
            
            return self.create_result(
                has_alert=True,
                alert_level=max_level,
                message=message,
                details=details,
            )
        
        return self.create_result(
            has_alert=False,
            message="端口计数器检查正常",
            details=details,
        )
    
    def _check_port_counters(self) -> List[Dict[str, Any]]:
        """检查端口计数器"""
        alerts = []
        
        # 获取要检查的端口列表
        ports = self._get_ports_to_check()
        
        for port in ports:
            counters = self._get_port_counter_values(port)
            if not counters:
                continue
            
            # 获取上次值
            last_counters = self._last_port_errors.get(port, {})
            
            # 检查增量
            for counter_name, value in counters.items():
                last_value = last_counters.get(counter_name, 0)
                delta = value - last_value
                
                # 首次运行或值回绕时，不告警
                if port not in self._last_port_errors:
                    continue
                
                if delta < 0:
                    # 计数器回绕或重置，跳过
                    continue
                
                if delta > self.threshold:
                    cat_key, cat_name, cat_level = self._get_counter_category(counter_name)
                    alerts.append({
                        'category': cat_key,
                        'message': f"{port}.{counter_name} +{delta}",
                        'level': cat_level,
                    })
                    logger.log(
                        logging.WARNING if cat_level in (AlertLevel.WARNING, AlertLevel.ERROR) else logging.INFO,
                        f"[ErrorCode] {port}.{counter_name} +{delta}"
                    )
            
            # 更新缓存
            self._last_port_errors[port] = counters
        
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
                    alerts.append(f"{device} {error_type} +{delta}")
                    logger.warning(f"[ErrorCode] PCIe {device} {error_type} +{delta}")
            
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
                # 排除管理口和 eno 接口
                if name.startswith('eth-m') or name.startswith('eno'):
                    continue
                ports.append(name)
        
        return sorted(ports)
    
    def _get_port_counter_values(self, port: str) -> Dict[str, int]:
        """获取端口计数器值"""
        counters = {}
        
        # 方法1: 通过 sysfs 读取
        stats_path = Path(f'/sys/class/net/{port}/statistics')
        if stats_path.exists():
            for counter_name in self.ALL_COUNTERS:
                value = read_sysfs(stats_path / counter_name)
                if value is not None:
                    counters[counter_name] = safe_int(value)
        
        # 方法2: 通过 ethtool（如果 sysfs 不完整）
        if not counters:
            counters = self._get_ethtool_stats(port)
        
        return counters
    
    def _get_ethtool_stats(self, port: str) -> Dict[str, int]:
        """通过 ethtool 获取统计信息"""
        counters = {}
        
        ret, stdout, _ = run_command(['ethtool', '-S', port], timeout=5)
        if ret != 0:
            return counters
        
        for line in stdout.split('\n'):
            line = line.strip()
            if ':' not in line:
                continue
            
            key, value = line.split(':', 1)
            key = key.strip().lower()
            value = value.strip()
            
            # 匹配所有相关计数器
            if any(err in key for err in ['error', 'drop', 'crc', 'fifo', 'miss', 'collision', 'carrier', 'fcs', 'frame']):
                counters[key] = safe_int(value)
        
        return counters
    
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
