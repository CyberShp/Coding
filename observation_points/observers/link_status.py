"""
链路状态观察点

监测端口链路状态变化（link down/up）。
支持白名单排除已知的维护操作。
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from typing import Any, Dict, List, Optional

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import read_sysfs

logger = logging.getLogger(__name__)


class LinkStatusObserver(BaseObserver):
    """
    链路状态观察点
    
    功能：
    - 监测网络端口的 carrier/operstate 状态
    - 检测 link down/up 事件
    - 支持白名单排除
    """
    
    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.whitelist = set(config.get('whitelist', []))
        self.protocols = config.get('protocols', ['iscsi', 'nvme', 'nas'])
        self.ports = config.get('ports', [])
        self._last_states = {}  # type: Dict[str, Dict[str, Any]]
        
        # 首次运行标记
        self._first_run = True
    
    def check(self) -> ObserverResult:
        """检查链路状态"""
        alerts = []
        details = {
            'changes': [],
            'current_states': {},
        }
        
        ports = self._get_ports_to_check()
        
        for port in ports:
            state = self._get_port_state(port)
            if not state:
                continue
            
            details['current_states'][port] = state
            # 跳过白名单端口
            if port in self.whitelist:
                continue
            
            # 检查状态变化
            last_state = self._last_states.get(port)
            
            if last_state and not self._first_run:
                changes = self._detect_changes(port, last_state, state)
                if changes:
                    alerts.extend(changes)
                    details['changes'].extend([
                        {
                            'port': port,
                            'change': c,
                            'timestamp': datetime.now().isoformat(),
                        }
                        for c in changes
                    ])
            
            # 更新缓存
            self._last_states[port] = state
        
        self._first_run = False
        
        if alerts:
            message = f"检测到链路状态变化: {'; '.join(alerts[:3])}"
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
            message="链路状态正常",
            details=details,
        )
    
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
                # 排除 bond slave（只监控 bond 本身）
                if self._is_bond_slave(name):
                    continue
                ports.append(name)
        
        return sorted(ports)
    
    def _is_bond_slave(self, port: str) -> bool:
        """检查端口是否是 bond 的 slave"""
        master_path = Path(f'/sys/class/net/{port}/master')
        return master_path.exists()
    
    def _get_port_state(self, port: str):  # type: (...) -> Optional[Dict[str, Any]]
        """获取端口状态"""
        port_path = Path(f'/sys/class/net/{port}')
        
        if not port_path.exists():
            return None
        
        state = {
            'carrier': read_sysfs(port_path / 'carrier') or '0',
            'operstate': read_sysfs(port_path / 'operstate') or 'unknown',
            'speed': read_sysfs(port_path / 'speed'),
            'duplex': read_sysfs(port_path / 'duplex'),
            'timestamp': datetime.now().isoformat(),
        }
        
        # 获取 bond 信息（如果是 bond）
        if (port_path / 'bonding').exists():
            state['is_bond'] = True
            state['bond_mode'] = read_sysfs(port_path / 'bonding/mode')
            state['bond_slaves'] = read_sysfs(port_path / 'bonding/slaves')
        
        return state
    
    def _detect_changes(self, port: str, last: Dict, current: Dict) -> List[str]:
        """检测状态变化"""
        changes = []
        
        # carrier 变化 (1=up, 0=down)
        if last.get('carrier') != current.get('carrier'):
            old_carrier = last.get('carrier', '0')
            new_carrier = current.get('carrier', '0')
            
            if new_carrier == '0' and old_carrier == '1':
                changes.append(f"{port} link DOWN")
                logger.warning(f"[LinkStatus] {port} DOWN")
            elif new_carrier == '1' and old_carrier == '0':
                changes.append(f"{port} link UP")
                logger.info(f"[LinkStatus] {port} UP")
        
        # operstate 变化
        if last.get('operstate') != current.get('operstate'):
            old_state = last.get('operstate', 'unknown')
            new_state = current.get('operstate', 'unknown')
            
            if new_state in ('down', 'notpresent', 'lowerlayerdown'):
                changes.append(f"{port} operstate: {old_state} -> {new_state}")
                logger.warning(f"[LinkStatus] {port} state: {old_state} -> {new_state}")
        
        # 速率变化（降速可能表示问题）
        old_speed = last.get('speed')
        new_speed = current.get('speed')
        if old_speed and new_speed and old_speed != new_speed:
            try:
                if int(new_speed) < int(old_speed):
                    changes.append(f"{port} 速率降低: {old_speed} -> {new_speed} Mbps")
                    logger.warning(f"[LinkStatus] {port} speed: {old_speed} -> {new_speed}")
            except ValueError:
                pass
        
        return changes
    
    def add_to_whitelist(self, port: str):
        """添加端口到白名单"""
        self.whitelist.add(port)
        logger.debug(f"白名单+: {port}")
    
    def remove_from_whitelist(self, port: str):
        """从白名单移除端口"""
        self.whitelist.discard(port)
        logger.debug(f"白名单-: {port}")
