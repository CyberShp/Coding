"""
结果解析器

解析远程监控结果，格式化显示数据。
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class AlertInfo:
    """告警信息"""
    observer_name: str
    level: str
    message: str
    timestamp: str
    details: Dict[str, Any]
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AlertInfo':
        """从字典创建"""
        return cls(
            observer_name=data.get('observer_name', ''),
            level=data.get('level', 'info'),
            message=data.get('message', ''),
            timestamp=data.get('timestamp', ''),
            details=data.get('details', {}),
        )
    
    def get_level_display(self) -> Tuple[str, str]:
        """
        获取级别显示
        
        Returns:
            (显示文本, 颜色)
        """
        level_map = {
            'info': ('信息', '#2196F3'),
            'warning': ('警告', '#FF9800'),
            'error': ('错误', '#F44336'),
            'critical': ('严重', '#9C27B0'),
        }
        return level_map.get(self.level, ('未知', '#9E9E9E'))
    
    def format_time(self) -> str:
        """格式化时间显示"""
        if not self.timestamp:
            return ''
        
        try:
            # 尝试解析 ISO 格式
            dt = datetime.fromisoformat(self.timestamp.replace('Z', '+00:00'))
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            return self.timestamp[:19] if len(self.timestamp) >= 19 else self.timestamp


class ResultParser:
    """
    结果解析器
    
    功能：
    - 解析告警 JSON
    - 格式化观察点状态
    - 生成显示数据
    """
    
    # 观察点名称映射
    OBSERVER_NAMES = {
        'error_code': '误码监测',
        'link_status': '链路状态',
        'card_recovery': '卡修复',
        'alarm_type': 'AlarmType',
        'memory_leak': '内存泄漏',
        'cpu_usage': 'CPU利用率',
        'cmd_response': '命令响应',
        'sig_monitor': 'sig信号',
        'sensitive_info': '敏感信息',
        'custom_commands': '自定义命令',
    }
    
    # 状态图标
    STATUS_ICONS = {
        'ok': '✓',
        'warning': '⚠',
        'error': '✗',
        'unknown': '?',
    }
    
    @classmethod
    def parse_alerts(cls, json_lines: str) -> List[AlertInfo]:
        """
        解析告警 JSON 行
        
        Args:
            json_lines: NDJSON 格式的告警数据
            
        Returns:
            告警列表
        """
        alerts = []
        
        for line in json_lines.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            
            try:
                data = json.loads(line)
                alerts.append(AlertInfo.from_dict(data))
            except json.JSONDecodeError:
                logger.debug(f"无法解析告警: {line[:100]}")
        
        return alerts
    
    @classmethod
    def get_observer_display_name(cls, name: str) -> str:
        """获取观察点显示名称"""
        return cls.OBSERVER_NAMES.get(name, name)
    
    @classmethod
    def format_observer_status(
        cls,
        status: Dict[str, Dict[str, str]]
    ) -> List[Dict[str, Any]]:
        """
        格式化观察点状态用于显示
        
        Args:
            status: 观察点状态字典
            
        Returns:
            格式化后的显示数据列表
        """
        result = []
        
        for name, info in status.items():
            # 跳过元信息
            if name == '_meta':
                continue
            
            state = info.get('status', 'unknown')
            message = info.get('message', '')
            
            result.append({
                'name': name,
                'display_name': cls.get_observer_display_name(name),
                'status': state,
                'icon': cls.STATUS_ICONS.get(state, '?'),
                'message': message,
                'color': cls._get_status_color(state),
            })
        
        return result
    
    @classmethod
    def get_meta_info(cls, status: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
        """
        获取元信息
        
        Args:
            status: 观察点状态字典
            
        Returns:
            元信息字典
        """
        return status.get('_meta', {})
    
    @classmethod
    def _get_status_color(cls, status: str) -> str:
        """获取状态颜色"""
        colors = {
            'ok': '#4CAF50',      # 绿色
            'warning': '#FF9800',  # 橙色
            'error': '#F44336',    # 红色
            'unknown': '#9E9E9E',  # 灰色
        }
        return colors.get(status, '#9E9E9E')
    
    @classmethod
    def format_alert_for_display(cls, alert: AlertInfo) -> Dict[str, Any]:
        """
        格式化单条告警用于显示
        
        Args:
            alert: 告警信息
            
        Returns:
            格式化后的显示数据
        """
        level_text, level_color = alert.get_level_display()
        
        return {
            'observer_name': alert.observer_name,
            'observer_display': cls.get_observer_display_name(alert.observer_name),
            'level': alert.level,
            'level_text': level_text,
            'level_color': level_color,
            'message': alert.message,
            'time': alert.format_time(),
            'timestamp': alert.timestamp,
        }
    
    @classmethod
    def summarize_alerts(
        cls,
        alerts: List[AlertInfo]
    ) -> Dict[str, Any]:
        """
        汇总告警统计
        
        Args:
            alerts: 告警列表
            
        Returns:
            汇总统计
        """
        by_level = {'info': 0, 'warning': 0, 'error': 0, 'critical': 0}
        by_observer = {}
        
        for alert in alerts:
            level = alert.level.lower()
            if level in by_level:
                by_level[level] += 1
            
            observer = alert.observer_name
            if observer not in by_observer:
                by_observer[observer] = 0
            by_observer[observer] += 1
        
        return {
            'total': len(alerts),
            'by_level': by_level,
            'by_observer': by_observer,
        }
