"""
AlarmType 监测观察点

监测 /OSM/log/cur_debug/messages 日志中的 alarm type 相关事件。
"""

import logging
import re
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import tail_file

logger = logging.getLogger(__name__)


class AlarmTypeObserver(BaseObserver):
    """
    AlarmType 监测观察点
    
    功能：
    - 监测 messages 日志中的 "alarm type" 关键字（不区分大小写）
    - 从脚本启动时刻开始监控，不处理历史数据
    """
    
    # 匹配 "alarm type" 的正则（忽略大小写）
    ALARM_TYPE_PATTERN = re.compile(r'alarm\s*type', re.IGNORECASE)
    
    # 日志时间戳格式
    TIMESTAMP_PATTERNS = [
        r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})',
        r'([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})',
        r'\[(\d+\.\d+)\]',
    ]
    
    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        
        self.log_path = Path(config.get('log_path', '/OSM/log/cur_debug/messages'))
        self.max_lines_per_check = config.get('max_lines_per_check', 1000)
        
        # 文件读取位置
        self._file_position = 0
        self._first_run = True
        
        # 统计数据
        self._total_count = 0
        self._recent_events = deque(maxlen=10)  # type: deque
    
    def check(self) -> ObserverResult:
        """检查 AlarmType 事件"""
        # 首次运行时跳过历史数据
        skip_existing = self._first_run
        self._first_run = False
        
        # 读取新增日志行
        new_lines, new_position = tail_file(
            self.log_path,
            self._file_position,
            self.max_lines_per_check,
            skip_existing=skip_existing
        )
        self._file_position = new_position
        
        # 本次检测到的事件
        new_events = []
        
        # 分析每一行
        for line in new_lines:
            if self.ALARM_TYPE_PATTERN.search(line):
                self._total_count += 1
                event = self._parse_event(line)
                new_events.append(event)
                self._recent_events.append(event)
                logger.warning(f"检测到 AlarmType 事件: {event['timestamp']}")
        
        # 构建结果
        details = {
            'total_count': self._total_count,
            'new_events': new_events,
            'recent_events': list(self._recent_events),
            'log_path': str(self.log_path),
        }
        
        if new_events:
            message = f"检测到 {len(new_events)} 个 AlarmType 事件（累计: {self._total_count}）"
            
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message=message,
                details=details,
            )
        
        return self.create_result(
            has_alert=False,
            message=f"AlarmType 检查正常（累计: {self._total_count}）",
            details=details,
        )
    
    def _parse_event(self, line: str) -> Dict[str, Any]:
        """解析日志行，提取时间戳"""
        timestamp = self._parse_timestamp(line)
        
        return {
            'timestamp': timestamp or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'line': line[:300],  # 保留部分原始行
        }
    
    def _parse_timestamp(self, line: str) -> Optional[str]:
        """尝试从日志行解析时间戳"""
        for pattern in self.TIMESTAMP_PATTERNS:
            match = re.search(pattern, line)
            if match:
                return match.group(1)
        return None
