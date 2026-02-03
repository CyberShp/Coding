"""
CPU0 利用率监测观察点

通过解析 /proc/stat 或 top 命令监测 CPU0 的利用率。
当连续 N 次（默认6次）检测超过阈值（默认90%）时告警。
"""

import logging
import re
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import run_command

logger = logging.getLogger(__name__)


class CpuUsageObserver(BaseObserver):
    """
    CPU0 利用率监测观察点
    
    功能：
    - 定期检测 CPU0 利用率
    - 连续 N 次（默认6次，即3分钟）超过阈值则告警
    - 告警后持续报告（sticky_alert），直到线程退出
    """
    
    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        
        # 利用率阈值（默认90%）
        self.threshold_percent = config.get('threshold_percent', 90)
        
        # 连续超阈值次数阈值（默认6次）
        self.consecutive_threshold = config.get('consecutive_threshold', 6)
        
        # 历史数据
        self._history = deque(maxlen=self.consecutive_threshold)  # type: deque
        
        # 上次 /proc/stat 数据（用于计算利用率）
        self._last_cpu_stats = None  # type: Optional[Tuple[int, int]]
        
        # 是否已触发告警（sticky状态）
        self._alert_triggered = False
    
    def check(self) -> ObserverResult:
        """检查 CPU0 利用率"""
        # 获取当前 CPU0 利用率
        cpu_usage = self._get_cpu0_usage()
        
        if cpu_usage is None:
            return self.create_result(
                has_alert=False,
                message="无法获取 CPU0 利用率",
                details={'error': '读取 /proc/stat 失败'},
            )
        
        # 记录当前值
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        is_over_threshold = cpu_usage >= self.threshold_percent
        
        self._history.append({
            'timestamp': timestamp,
            'usage_percent': cpu_usage,
            'over_threshold': is_over_threshold,
        })
        
        # 构建详情
        details = {
            'current_usage_percent': cpu_usage,
            'threshold_percent': self.threshold_percent,
            'history': list(self._history),
            'consecutive_threshold': self.consecutive_threshold,
            'consecutive_over_threshold': self._count_consecutive_over_threshold(),
        }
        
        # 检查是否连续超阈值
        if self._is_continuous_over_threshold():
            self._alert_triggered = True
            message = (
                f"CPU0 利用率告警: 连续 {self.consecutive_threshold} 次检测超过 {self.threshold_percent}% "
                f"(当前: {cpu_usage:.1f}%)"
            )
            logger.error(message)
            
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.ERROR,
                message=message,
                details=details,
                sticky=True,
            )
        
        # 如果之前触发过告警，持续报告
        if self._alert_triggered:
            message = f"CPU0 利用率告警持续中 (当前: {cpu_usage:.1f}%)"
            
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.ERROR,
                message=message,
                details=details,
                sticky=True,
            )
        
        return self.create_result(
            has_alert=False,
            message=f"CPU0 检查正常 (当前: {cpu_usage:.1f}%)",
            details=details,
        )
    
    def _get_cpu0_usage(self) -> Optional[float]:
        """
        获取 CPU0 利用率
        
        通过读取 /proc/stat 计算 CPU0 的利用率。
        利用率 = (非空闲时间增量 / 总时间增量) * 100
        """
        proc_stat = Path('/proc/stat')
        
        if not proc_stat.exists():
            # 回退到 top 命令
            return self._get_cpu0_usage_from_top()
        
        try:
            content = proc_stat.read_text()
        except Exception as e:
            logger.error(f"读取 /proc/stat 失败: {e}")
            return self._get_cpu0_usage_from_top()
        
        # 解析 cpu0 行
        # 格式: cpu0 user nice system idle iowait irq softirq steal guest guest_nice
        for line in content.split('\n'):
            if line.startswith('cpu0 '):
                parts = line.split()
                if len(parts) >= 5:
                    try:
                        user = int(parts[1])
                        nice = int(parts[2])
                        system = int(parts[3])
                        idle = int(parts[4])
                        iowait = int(parts[5]) if len(parts) > 5 else 0
                        
                        # 计算总时间和空闲时间
                        total = user + nice + system + idle + iowait
                        idle_total = idle + iowait
                        
                        # 如果是首次运行，保存数据并返回 None
                        if self._last_cpu_stats is None:
                            self._last_cpu_stats = (total, idle_total)
                            return None
                        
                        # 计算增量
                        last_total, last_idle = self._last_cpu_stats
                        total_delta = total - last_total
                        idle_delta = idle_total - last_idle
                        
                        # 更新缓存
                        self._last_cpu_stats = (total, idle_total)
                        
                        if total_delta <= 0:
                            return None
                        
                        # 计算利用率
                        usage = ((total_delta - idle_delta) / total_delta) * 100
                        return max(0.0, min(100.0, usage))
                        
                    except (ValueError, IndexError) as e:
                        logger.error(f"解析 /proc/stat 失败: {e}")
                        return None
        
        return None
    
    def _get_cpu0_usage_from_top(self) -> Optional[float]:
        """通过 top 命令获取 CPU0 利用率（备用方案）"""
        ret, stdout, stderr = run_command('top -bn1 -1', shell=True, timeout=10)
        
        if ret != 0:
            logger.error(f"执行 top 命令失败: {stderr}")
            return None
        
        # 解析 top 输出，查找 CPU0 行
        # 格式类似: %Cpu0  :  5.9 us,  2.0 sy,  0.0 ni, 91.8 id,  0.3 wa,  0.0 hi,  0.0 si,  0.0 st
        for line in stdout.split('\n'):
            if 'Cpu0' in line or 'cpu0' in line:
                # 提取 idle 值
                idle_match = re.search(r'(\d+\.?\d*)\s*id', line)
                if idle_match:
                    try:
                        idle = float(idle_match.group(1))
                        return 100.0 - idle
                    except ValueError:
                        pass
        
        return None
    
    def _is_continuous_over_threshold(self) -> bool:
        """检查是否连续超阈值"""
        if len(self._history) < self.consecutive_threshold:
            return False
        
        return all(h['over_threshold'] for h in self._history)
    
    def _count_consecutive_over_threshold(self) -> int:
        """计算当前连续超阈值次数"""
        count = 0
        
        for h in reversed(self._history):
            if h['over_threshold']:
                count += 1
            else:
                break
        
        return count
