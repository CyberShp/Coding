"""
AlarmType 监测观察点

监测 /OSM/log/cur_debug/messages 日志中的 alarm type 相关事件。
- alarm type(0): 告警产生
- alarm type(1): 告警恢复（从活跃告警中剔除）
"""

import logging
import re
from collections import deque, OrderedDict
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
    - 监测 messages 日志中的 alarm type 事件
    - 提取 alarm type、alarm name、alarm id、时间戳
    - alarm type(0) = 产生告警，alarm type(1) = 告警恢复
    - 告警恢复时从活跃告警中剔除
    - 打印累计事件个数和最近5次活跃告警详情
    """
    
    # 提取 alarm type(X) 的正则
    ALARM_TYPE_PATTERN = re.compile(r'alarm\s*type\s*\(\s*(\d+)\s*\)', re.IGNORECASE)
    
    # 提取 alarm name(XXX) 的正则
    ALARM_NAME_PATTERN = re.compile(r'alarm\s*name\s*\(\s*([^)]+)\s*\)', re.IGNORECASE)
    
    # 提取 alarm id(0xXXXXXX) 的正则
    ALARM_ID_PATTERN = re.compile(r'alarm\s*id\s*\(\s*(0x[0-9a-fA-F]+|[0-9a-fA-F]+)\s*\)', re.IGNORECASE)
    
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
        self.recent_count = config.get('recent_count', 5)  # 最近事件数量
        
        # 文件读取位置
        self._file_position = 0
        self._first_run = True
        
        # 统计数据
        self._total_count = 0  # 累计告警产生次数（不含恢复）
        self._recovered_count = 0  # 累计告警恢复次数
        
        # 活跃告警（未恢复）：alarm_id -> event_info
        self._active_alarms = OrderedDict()  # type: OrderedDict[str, Dict[str, Any]]
        
        # 最近的告警事件（用于展示，包含已恢复的历史）
        self._recent_events = deque(maxlen=self.recent_count)  # type: deque
    
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
        new_alarms = []  # 新产生的告警
        recovered_alarms = []  # 恢复的告警
        
        # 分析每一行
        for line in new_lines:
            event = self._parse_event(line)
            if event is None:
                continue
            
            alarm_type = event['alarm_type']
            alarm_id = event['alarm_id']
            
            if alarm_type == 0:
                # 告警产生
                self._total_count += 1
                new_alarms.append(event)
                self._recent_events.append(event)
                
                # 加入活跃告警（用 alarm_id 作为 key）
                if alarm_id:
                    self._active_alarms[alarm_id] = event
                
                logger.warning(
                    f"告警产生: name={event['alarm_name']}, id={alarm_id}, time={event['timestamp']}"
                )
            
            elif alarm_type == 1:
                # 告警恢复
                self._recovered_count += 1
                recovered_alarms.append(event)
                
                # 从活跃告警中剔除
                if alarm_id and alarm_id in self._active_alarms:
                    removed = self._active_alarms.pop(alarm_id)
                    # 同时从最近事件中剔除
                    self._remove_from_recent(alarm_id)
                    logger.info(
                        f"告警恢复: name={event['alarm_name']}, id={alarm_id}, "
                        f"原告警时间={removed['timestamp']}"
                    )
                else:
                    logger.info(
                        f"告警恢复（无匹配）: name={event['alarm_name']}, id={alarm_id}"
                    )
        
        # 构建结果
        active_list = list(self._active_alarms.values())
        recent_list = list(self._recent_events)
        
        details = {
            'total_count': self._total_count,
            'recovered_count': self._recovered_count,
            'active_count': len(self._active_alarms),
            'new_alarms': new_alarms,
            'recovered_alarms': recovered_alarms,
            'active_alarms': active_list,
            'recent_events': recent_list,
            'log_path': str(self.log_path),
        }
        
        if new_alarms:
            # 格式化最近活跃告警
            recent_str = self._format_recent_events()
            message = (
                f"告警统计: 累计 {self._total_count} 次，本次新增 {len(new_alarms)} 次，"
                f"活跃 {len(self._active_alarms)} 个。{recent_str}"
            )
            
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message=message,
                details=details,
            )
        
        # 即使没有新告警，也报告当前状态
        return self.create_result(
            has_alert=False,
            message=f"AlarmType 检查正常（累计: {self._total_count}，活跃: {len(self._active_alarms)}）",
            details=details,
        )
    
    def _parse_event(self, line: str) -> Optional[Dict[str, Any]]:
        """解析日志行，提取告警信息"""
        # 必须匹配 alarm type
        type_match = self.ALARM_TYPE_PATTERN.search(line)
        if not type_match:
            return None
        
        alarm_type = int(type_match.group(1))
        
        # 提取 alarm name
        name_match = self.ALARM_NAME_PATTERN.search(line)
        alarm_name = name_match.group(1).strip() if name_match else None
        
        # 提取 alarm id
        id_match = self.ALARM_ID_PATTERN.search(line)
        alarm_id = id_match.group(1).strip() if id_match else None
        
        # 提取时间戳
        timestamp = self._parse_timestamp(line)
        
        return {
            'timestamp': timestamp or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'alarm_type': alarm_type,
            'alarm_name': alarm_name,
            'alarm_id': alarm_id,
            'line': line[:300],
        }
    
    def _parse_timestamp(self, line: str) -> Optional[str]:
        """尝试从日志行解析时间戳"""
        for pattern in self.TIMESTAMP_PATTERNS:
            match = re.search(pattern, line)
            if match:
                return match.group(1)
        return None
    
    def _remove_from_recent(self, alarm_id: str):
        """从最近事件列表中移除指定 alarm_id 的事件"""
        # deque 不支持直接删除，需要重建
        new_recent = deque(maxlen=self.recent_count)
        for event in self._recent_events:
            if event.get('alarm_id') != alarm_id:
                new_recent.append(event)
        self._recent_events = new_recent
    
    def _format_recent_events(self) -> str:
        """格式化最近活跃告警列表"""
        if not self._recent_events:
            return ""
        
        items = []
        for event in self._recent_events:
            name = event.get('alarm_name') or '未知'
            alarm_id = event.get('alarm_id') or '未知'
            ts = event.get('timestamp', '')
            items.append(f"[{ts} name={name} id={alarm_id}]")
        
        return f"最近{len(items)}次: " + ", ".join(items)
