"""
内存泄漏监测观察点

通过 free -m 命令监测内存使用量，当连续 N 次采集都在增长时告警。
"""

import logging
import re
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command

logger = logging.getLogger(__name__)


class MemoryLeakObserver(BaseObserver):
    """
    内存泄漏监测观察点
    
    功能：
    - 定期执行 free -m 获取内存使用量
    - 连续 N 次（默认8次，即12小时）增长则告警
    - 连续 M 次（默认3次）下降则自动恢复
    """
    
    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        
        # 连续增长阈值（默认8次 = 12小时，间隔1.5h）
        self.consecutive_threshold = config.get('consecutive_threshold', 8)
        
        # 连续下降恢复阈值（默认3次）
        self.recovery_threshold = config.get('recovery_threshold', 3)
        
        # 历史数据（保留足够长度用于恢复判断）
        max_len = max(self.consecutive_threshold, self.recovery_threshold + 1)
        self._history = deque(maxlen=max_len)  # type: deque
        
        # 是否已触发告警（sticky状态）
        self._alert_triggered = False
    
    def check(self, reporter=None) -> ObserverResult:
        """检查内存使用情况"""
        # 获取当前内存使用量
        used_mb = self._get_memory_used()
        total_mb = self._get_memory_total()
        
        if used_mb is None:
            return self.create_result(
                has_alert=False,
                message="无法获取内存信息",
                details={'error': '执行 free -m 失败'},
            )
        
        # 记录指标数据（每次都记录，无论是否告警）
        if reporter and hasattr(reporter, 'record_metrics'):
            reporter.record_metrics({
                'mem_used_mb': used_mb,
                'mem_total_mb': total_mb or 0,
                'observer': self.name,
            })
        
        # 记录当前值
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self._history.append({
            'timestamp': timestamp,
            'used_mb': used_mb,
        })
        
        # 构建详情
        consecutive_increases = self._count_consecutive_increases()
        consecutive_decreases = self._count_consecutive_decreases()
        details = {
            'current_used_mb': used_mb,
            'history': list(self._history),
            'consecutive_threshold': self.consecutive_threshold,
            'recovery_threshold': self.recovery_threshold,
            'consecutive_increases': consecutive_increases,
            'consecutive_decreases': consecutive_decreases,
        }
        
        # 检查是否连续增长 -> 触发告警
        if self._is_continuous_increase():
            self._alert_triggered = True
            message = (
                f"内存疑似泄漏: 连续 {self.consecutive_threshold} 次采集内存持续增长 "
                f"(当前: {used_mb}MB)"
            )
            logger.error(message)
            
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.ERROR,
                message=message,
                details=details,
                sticky=True,
            )
        
        # 检查是否连续下降 -> 恢复
        if self._alert_triggered and self._is_continuous_decrease():
            self._alert_triggered = False
            details['recovered'] = True
            message = (
                f"内存泄漏已恢复: 连续 {self.recovery_threshold} 次采集内存下降 "
                f"(当前: {used_mb}MB)"
            )
            logger.info(message)
            
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.INFO,
                message=message,
                details=details,
                sticky=False,
            )
        
        # 如果之前触发过告警且未恢复，持续报告
        if self._alert_triggered:
            message = f"内存泄漏告警持续中 (当前: {used_mb}MB)"
            
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.ERROR,
                message=message,
                details=details,
                sticky=True,
            )
        
        return self.create_result(
            has_alert=False,
            message=f"内存检查正常 (当前: {used_mb}MB)",
            details=details,
        )
    
    def _get_memory_used(self) -> Optional[int]:
        """执行 free -m 获取已用内存（MB）"""
        ret, stdout, stderr = run_command('free -m', shell=True, timeout=5)
        
        if ret != 0:
            logger.error(f"执行 free -m 失败: {stderr}")
            return None
        
        for line in stdout.split('\n'):
            if line.startswith('Mem:'):
                parts = line.split()
                if len(parts) >= 3:
                    try:
                        return int(parts[2])  # used 列
                    except ValueError:
                        pass
        
        return None
    
    def _get_memory_total(self) -> Optional[int]:
        """获取总内存（MB）"""
        ret, stdout, stderr = run_command('free -m', shell=True, timeout=5)
        
        if ret != 0:
            return None
        
        for line in stdout.split('\n'):
            if line.startswith('Mem:'):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        return int(parts[1])  # total 列
                    except ValueError:
                        pass
        
        return None
    
    def _is_continuous_increase(self) -> bool:
        """检查是否连续增长"""
        if len(self._history) < self.consecutive_threshold:
            return False
        
        # 检查每次采集是否都比前一次大
        values = [h['used_mb'] for h in self._history]
        
        for i in range(1, len(values)):
            if values[i] <= values[i - 1]:
                return False
        
        return True
    
    def _count_consecutive_increases(self) -> int:
        """计算当前连续增长次数"""
        if len(self._history) < 2:
            return 0
        
        values = [h['used_mb'] for h in self._history]
        count = 0
        
        for i in range(len(values) - 1, 0, -1):
            if values[i] > values[i - 1]:
                count += 1
            else:
                break
        
        return count
    
    def _is_continuous_decrease(self) -> bool:
        """检查是否连续下降（用于恢复判断）"""
        if len(self._history) < self.recovery_threshold:
            return False
        
        # 只检查最近 recovery_threshold 次采集
        values = [h['used_mb'] for h in self._history][-self.recovery_threshold:]
        
        for i in range(1, len(values)):
            if values[i] >= values[i - 1]:
                return False
        
        return True
    
    def _count_consecutive_decreases(self) -> int:
        """计算当前连续下降次数"""
        if len(self._history) < 2:
            return 0
        
        values = [h['used_mb'] for h in self._history]
        count = 0
        
        for i in range(len(values) - 1, 0, -1):
            if values[i] < values[i - 1]:
                count += 1
            else:
                break
        
        return count
