"""
观察点基类

所有观察点都需要继承此基类，实现统一接口。
"""

import logging
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class AlertLevel(Enum):
    """告警级别"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ObserverResult:
    """观察点检查结果"""
    observer_name: str
    timestamp: datetime = field(default_factory=datetime.now)
    has_alert: bool = False
    alert_level: AlertLevel = AlertLevel.INFO
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    raw_data: Any = None
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            'observer_name': self.observer_name,
            'timestamp': self.timestamp.isoformat(),
            'has_alert': self.has_alert,
            'alert_level': self.alert_level.value,
            'message': self.message,
            'details': self.details,
        }


class BaseObserver(ABC):
    """
    观察点基类
    
    所有观察点都需要继承此类，并实现以下方法：
    - check(): 执行检查，返回 ObserverResult
    - cleanup(): 清理资源（可选）
    """
    
    def __init__(self, name: str, config: dict[str, Any]):
        """
        初始化观察点
        
        Args:
            name: 观察点名称
            config: 观察点配置
        """
        self.name = name
        self.config = config
        self.enabled = config.get('enabled', True)
        self.interval = config.get('interval', 30)
        self.logger = logging.getLogger(f'observer.{name}')
        
        # 上次检查时间
        self._last_check: datetime | None = None
        
        # 历史数据窗口（用于滑动窗口计算）
        window_size = config.get('window_size', 5)
        self._history: deque = deque(maxlen=window_size)
        
        # 上次值（用于增量检测）
        self._last_values: dict[str, Any] = {}
        
        self.logger.debug(f"观察点 {name} 初始化完成")
    
    @abstractmethod
    def check(self) -> ObserverResult:
        """
        执行检查
        
        Returns:
            ObserverResult: 检查结果
        """
        pass
    
    def cleanup(self):
        """清理资源（子类可覆盖）"""
        pass
    
    def is_enabled(self) -> bool:
        """是否启用"""
        return self.enabled
    
    def get_interval(self) -> int:
        """获取检查间隔（秒）"""
        return self.interval
    
    def record_history(self, data: Any):
        """
        记录历史数据
        
        Args:
            data: 要记录的数据
        """
        self._history.append({
            'timestamp': datetime.now(),
            'data': data,
        })
    
    def get_history(self) -> list[dict]:
        """获取历史数据"""
        return list(self._history)
    
    def calculate_average(self, key: str | None = None) -> float | None:
        """
        计算历史数据平均值
        
        Args:
            key: 如果历史数据是字典，指定要计算的键
            
        Returns:
            平均值，或 None（如果无数据）
        """
        if not self._history:
            return None
        
        values = []
        for item in self._history:
            data = item['data']
            if key and isinstance(data, dict):
                val = data.get(key)
            else:
                val = data
            
            if isinstance(val, (int, float)):
                values.append(val)
        
        return sum(values) / len(values) if values else None
    
    def detect_spike(self, current_value: float, key: str | None = None, 
                     threshold_percent: float = 50) -> tuple[bool, float]:
        """
        检测激增
        
        Args:
            current_value: 当前值
            key: 历史数据中的键（如果是字典）
            threshold_percent: 激增阈值百分比
            
        Returns:
            (是否激增, 变化百分比)
        """
        avg = self.calculate_average(key)
        if avg is None or avg == 0:
            return False, 0.0
        
        change_percent = ((current_value - avg) / avg) * 100
        is_spike = change_percent > threshold_percent
        
        return is_spike, change_percent
    
    def get_delta(self, key: str, current_value: float) -> float:
        """
        获取与上次值的差值（增量检测）
        
        Args:
            key: 键名
            current_value: 当前值
            
        Returns:
            差值
        """
        last = self._last_values.get(key, 0)
        self._last_values[key] = current_value
        return current_value - last
    
    def create_result(self, has_alert: bool = False,
                      alert_level: AlertLevel = AlertLevel.INFO,
                      message: str = "",
                      details: dict | None = None,
                      raw_data: Any = None) -> ObserverResult:
        """
        创建检查结果
        
        Args:
            has_alert: 是否有告警
            alert_level: 告警级别
            message: 告警消息
            details: 详细信息
            raw_data: 原始数据
            
        Returns:
            ObserverResult
        """
        return ObserverResult(
            observer_name=self.name,
            has_alert=has_alert,
            alert_level=alert_level,
            message=message,
            details=details or {},
            raw_data=raw_data,
        )
