"""
AlarmType 监测观察点

监测 /OSM/log/cur_debug/messages 日志中的 alarm type 相关事件。

告警逻辑：
- 所有 alarm type 条目都有 "send alarm" 或 "resume alarm" 字样
- "send alarm" = 告警上报（加入活跃告警）
- "resume alarm" = 告警恢复（从活跃告警中移除）
- alarm type(0) = 历史告警上报，仅通知，不加入活跃告警，不会有 resume
- alarm type(1) = 事件生成
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
    - 根据 "send alarm" / "resume alarm" 判断上报或恢复
    - 活跃告警清晰标记 id 和 name
    - 最近5次告警标记是否已恢复
    - 无新告警时不输出例行日志
    """
    
    # 提取 alarm type(X) 的正则
    ALARM_TYPE_PATTERN = re.compile(r'alarm\s*type\s*\(\s*(\d+)\s*\)', re.IGNORECASE)
    
    # 提取 alarm name(XXX) 的正则
    ALARM_NAME_PATTERN = re.compile(r'alarm\s*name\s*\(\s*([^)]+)\s*\)', re.IGNORECASE)
    
    # 提取 alarm id(0xXXXXXX) 的正则
    ALARM_ID_PATTERN = re.compile(r'alarm\s*id\s*\(\s*(0x[0-9a-fA-F]+|[0-9a-fA-F]+)\s*\)', re.IGNORECASE)
    
    # 检测 send alarm / resume alarm
    SEND_ALARM_PATTERN = re.compile(r'send\s+alarm', re.IGNORECASE)
    RESUME_ALARM_PATTERN = re.compile(r'resume\s+alarm', re.IGNORECASE)
    
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
        self._total_send_count = 0     # 累计告警上报次数
        self._total_resume_count = 0   # 累计告警恢复次数
        
        # 活跃告警（未恢复）：alarm_id -> event_info
        self._active_alarms = OrderedDict()  # type: OrderedDict[str, Dict[str, Any]]
        
        # 最近的告警事件（用于展示，包含 recovered 标记）
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
        new_send_alarms = []     # 新上报的告警
        new_resume_alarms = []   # 新恢复的告警
        
        # 分析每一行
        for line in new_lines:
            event = self._parse_event(line)
            if event is None:
                continue
            
            alarm_id = event['alarm_id']
            is_send = event['is_send']
            is_resume = event['is_resume']
            
            if is_send:
                # 告警上报
                self._total_send_count += 1
                new_send_alarms.append(event)
                
                alarm_type = event.get('alarm_type', -1)
                
                if alarm_type == 0:
                    # alarm type(0) 为历史告警上报，仅通知，不加入活跃告警
                    event['recovered'] = True  # 标记为"已处理"（不期待恢复）
                    event['is_history_report'] = True  # 标记为历史告警上报
                    self._recent_events.append(event)
                    logger.info(
                        f"[历史告警上报] name={event['alarm_name']} id={alarm_id}"
                    )
                else:
                    # 普通告警上报，加入活跃告警
                    event['recovered'] = False
                    event['is_history_report'] = False
                    self._recent_events.append(event)
                    
                    # 加入活跃告警
                    if alarm_id:
                        self._active_alarms[alarm_id] = event
                    
                    logger.warning(
                        f"[告警上报] name={event['alarm_name']} id={alarm_id}"
                    )
            
            elif is_resume:
                # 告警恢复
                self._total_resume_count += 1
                new_resume_alarms.append(event)
                
                # 从活跃告警中移除
                if alarm_id and alarm_id in self._active_alarms:
                    self._active_alarms.pop(alarm_id)
                    # 标记最近事件中的该告警为已恢复
                    self._mark_as_recovered(alarm_id)
                    logger.info(f"[告警恢复] name={event['alarm_name']} id={alarm_id}")
                else:
                    logger.info(f"[告警恢复] name={event['alarm_name']} id={alarm_id} (无匹配活跃告警)")
        
        # 构建结果
        active_list = list(self._active_alarms.values())
        recent_list = list(self._recent_events)
        
        details = {
            'total_send_count': self._total_send_count,
            'total_resume_count': self._total_resume_count,
            'active_count': len(self._active_alarms),
            'new_send_alarms': new_send_alarms,
            'new_resume_alarms': new_resume_alarms,
            'active_alarms': active_list,
            'recent_events': recent_list,
            'log_path': str(self.log_path),
        }
        
        # 只有有新事件时才产生告警
        if new_send_alarms or new_resume_alarms:
            # 格式化消息
            message_parts = []
            
            if new_send_alarms:
                message_parts.append(f"新上报 {len(new_send_alarms)} 条")
            if new_resume_alarms:
                message_parts.append(f"恢复 {len(new_resume_alarms)} 条")
            
            # 活跃告警信息
            active_str = self._format_active_alarms()
            recent_str = self._format_recent_events()
            
            message = (
                f"[Alarm] {', '.join(message_parts)}; "
                f"累计上报 {self._total_send_count}, 累计恢复 {self._total_resume_count}, "
                f"当前活跃 {len(self._active_alarms)} 个"
            )
            
            if active_str:
                message += f"\n  活跃告警: {active_str}"
            if recent_str:
                message += f"\n  最近{len(self._recent_events)}条: {recent_str}"
            
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING if new_send_alarms else AlertLevel.INFO,
                message=message,
                details=details,
            )
        
        # 无新告警时不输出（has_alert=False，不会被 reporter 打印）
        return self.create_result(
            has_alert=False,
            message="",  # 无新告警，不需要消息
            details=details,
        )
    
    def _parse_event(self, line: str) -> Optional[Dict[str, Any]]:
        """解析日志行，提取告警信息"""
        # 必须匹配 alarm type
        type_match = self.ALARM_TYPE_PATTERN.search(line)
        if not type_match:
            return None
        
        alarm_type = int(type_match.group(1))
        
        # 检测是 send alarm 还是 resume alarm
        is_send = bool(self.SEND_ALARM_PATTERN.search(line))
        is_resume = bool(self.RESUME_ALARM_PATTERN.search(line))
        
        # 如果都不是，跳过
        if not is_send and not is_resume:
            logger.debug(f"跳过无 send/resume 标记的行: {line[:100]}")
            return None
        
        # 提取 alarm name
        name_match = self.ALARM_NAME_PATTERN.search(line)
        alarm_name = name_match.group(1).strip() if name_match else '未知'
        
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
            'is_send': is_send,
            'is_resume': is_resume,
            'line': line,
        }
    
    def _parse_timestamp(self, line: str) -> Optional[str]:
        """尝试从日志行解析时间戳"""
        for pattern in self.TIMESTAMP_PATTERNS:
            match = re.search(pattern, line)
            if match:
                return match.group(1)
        return None
    
    def _mark_as_recovered(self, alarm_id: str):
        """将最近事件中指定 alarm_id 的告警标记为已恢复"""
        for event in self._recent_events:
            if event.get('alarm_id') == alarm_id:
                event['recovered'] = True
    
    def _format_active_alarms(self) -> str:
        """格式化活跃告警列表"""
        if not self._active_alarms:
            return ""
        
        items = []
        for alarm_id, event in self._active_alarms.items():
            name = event.get('alarm_name', '未知')
            items.append(f"{name}({alarm_id})")
        
        return "; ".join(items)
    
    def _format_recent_events(self) -> str:
        """格式化最近事件列表（标记是否已恢复）"""
        if not self._recent_events:
            return ""
        
        items = []
        for event in self._recent_events:
            name = event.get('alarm_name', '未知')
            alarm_id = event.get('alarm_id', '?')
            ts = event.get('timestamp', '')
            recovered = event.get('recovered', False)
            is_history_report = event.get('is_history_report', False)
            
            if is_history_report:
                status = "[历史告警上报]"
            elif recovered:
                status = "[已恢复]"
            else:
                status = "[活跃]"
            items.append(f"{status} {name}({alarm_id}) @{ts}")
        
        return "; ".join(items)
