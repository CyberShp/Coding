"""
AlarmType 监测观察点

监测 /OSM/log/cur_debug/system_alarm.txt 日志中的 AlarmType 相关事件。

告警逻辑：
- 匹配 AlarmType:X action 格式，X 为 0/1/2
- AlarmType:0 event  = 事件上报，INFO 级别，无恢复策略，仅上报
- AlarmType:1 fault  = 故障告警上报，WARNING 级别，有恢复策略
- AlarmType:2 resume = 告警恢复，与 AlarmType:1 对应
- 同一条目中还包含 AlarmId: 和 objType: 字段
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
    - 监测 system_alarm.txt 日志中的 AlarmType 事件
    - 提取 AlarmType、AlarmId、objType、时间戳
    - AlarmType:0 event → 事件上报 (INFO)
    - AlarmType:1 fault → 故障告警 (WARNING)，加入活跃告警
    - AlarmType:2 resume → 告警恢复 (INFO)，从活跃告警移除
    - 最近事件标记是否已恢复
    - 无新告警时不输出例行日志
    """
    
    # 匹配 AlarmType:X action（X=0/1/2, action=event/fault/resume）
    ALARM_TYPE_PATTERN = re.compile(r'AlarmType:(\d+)\s+(event|fault|resume)', re.IGNORECASE)
    
    # 匹配 AlarmId:XXX
    ALARM_ID_PATTERN = re.compile(r'AlarmId:(\S+)', re.IGNORECASE)
    
    # 匹配 objType:XXX
    OBJ_TYPE_PATTERN = re.compile(r'objType:(\S+)', re.IGNORECASE)
    
    # 日志时间戳格式
    TIMESTAMP_PATTERNS = [
        r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})',
        r'([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})',
        r'\[(\d+\.\d+)\]',
    ]
    
    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        
        self.log_path = Path(config.get('log_path', '/OSM/log/cur_debug/system_alarm.txt'))
        self.max_lines_per_check = config.get('max_lines_per_check', 1000)
        self.recent_count = config.get('recent_count', 5)  # 最近事件数量
        
        # 文件读取位置
        self._file_position = 0
        self._first_run = True
        
        # 统计数据
        self._total_event_count = 0    # 累计事件上报次数 (type 0)
        self._total_send_count = 0     # 累计故障告警次数 (type 1)
        self._total_resume_count = 0   # 累计告警恢复次数 (type 2)
        
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
        new_events = []          # 新事件上报 (type 0)
        new_send_alarms = []     # 新故障告警 (type 1)
        new_resume_alarms = []   # 新恢复告警 (type 2)
        
        # 分析每一行
        for line in new_lines:
            event = self._parse_event(line)
            if event is None:
                continue
            
            alarm_id = event['alarm_id']
            alarm_type_val = event['alarm_type']
            
            if alarm_type_val == 0:
                # AlarmType:0 event — 事件上报，INFO，无恢复策略
                self._total_event_count += 1
                new_events.append(event)
                event['recovered'] = True  # 不期待恢复
                event['is_event_report'] = True
                self._recent_events.append(event)
                logger.info(
                    f"[事件上报] AlarmId={alarm_id} objType={event.get('obj_type', '?')}"
                )
            
            elif alarm_type_val == 1:
                # AlarmType:1 fault — 故障告警，WARNING，有恢复策略
                self._total_send_count += 1
                new_send_alarms.append(event)
                event['recovered'] = False
                event['is_event_report'] = False
                self._recent_events.append(event)
                
                if alarm_id:
                    self._active_alarms[alarm_id] = event
                
                logger.warning(
                    f"[故障告警] AlarmId={alarm_id} objType={event.get('obj_type', '?')}"
                )
            
            elif alarm_type_val == 2:
                # AlarmType:2 resume — 告警恢复
                self._total_resume_count += 1
                new_resume_alarms.append(event)
                
                if alarm_id and alarm_id in self._active_alarms:
                    self._active_alarms.pop(alarm_id)
                    self._mark_as_recovered(alarm_id)
                    logger.warning(f"[告警恢复] AlarmId={alarm_id} objType={event.get('obj_type', '?')}")
                else:
                    logger.warning(f"[告警恢复] AlarmId={alarm_id} (无匹配活跃告警)")
        
        # 构建结果
        active_list = list(self._active_alarms.values())
        recent_list = list(self._recent_events)
        
        details = {
            'total_event_count': self._total_event_count,
            'total_send_count': self._total_send_count,
            'total_resume_count': self._total_resume_count,
            'active_count': len(self._active_alarms),
            'new_events': new_events,
            'new_send_alarms': new_send_alarms,
            'new_resume_alarms': new_resume_alarms,
            'active_alarms': active_list,
            'recent_events': recent_list,
            'log_path': str(self.log_path),
        }
        
        # 只有有新事件时才产生告警
        if new_events or new_send_alarms or new_resume_alarms:
            # 格式化消息
            message_parts = []
            
            if new_events:
                message_parts.append(f"事件 {len(new_events)} 条")
            if new_send_alarms:
                message_parts.append(f"故障 {len(new_send_alarms)} 条")
            if new_resume_alarms:
                message_parts.append(f"恢复 {len(new_resume_alarms)} 条")
            
            # 活跃告警信息
            active_str = self._format_active_alarms()
            recent_str = self._format_recent_events()
            
            message = (
                f"[Alarm] {', '.join(message_parts)}; "
                f"累计事件 {self._total_event_count}, "
                f"累计故障 {self._total_send_count}, 累计恢复 {self._total_resume_count}, "
                f"当前活跃 {len(self._active_alarms)} 个"
            )
            
            if active_str:
                message += f"\n  活跃告警: {active_str}"
            if recent_str:
                message += f"\n  最近{len(self._recent_events)}条: {recent_str}"
            
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.WARNING if (new_send_alarms or new_resume_alarms) else AlertLevel.INFO,
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
        """解析日志行，提取 AlarmType 告警信息"""
        # 匹配 AlarmType:X action
        type_match = self.ALARM_TYPE_PATTERN.search(line)
        if not type_match:
            return None
        
        alarm_type = int(type_match.group(1))
        action = type_match.group(2).lower()  # event / fault / resume
        
        # 提取 AlarmId
        id_match = self.ALARM_ID_PATTERN.search(line)
        alarm_id = id_match.group(1).strip() if id_match else None
        
        # 提取 objType
        obj_match = self.OBJ_TYPE_PATTERN.search(line)
        obj_type = obj_match.group(1).strip() if obj_match else '未知'
        
        # 提取时间戳
        timestamp = self._parse_timestamp(line)
        
        return {
            'timestamp': timestamp or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'alarm_type': alarm_type,
            'action': action,
            'alarm_id': alarm_id,
            'obj_type': obj_type,
            'alarm_name': obj_type,  # 兼容旧字段
            'is_send': alarm_type == 1,
            'is_resume': alarm_type == 2,
            'is_event': alarm_type == 0,
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
            obj_type = event.get('obj_type', '未知')
            items.append(f"AlarmId:{alarm_id} objType:{obj_type}")
        
        return "; ".join(items)
    
    def _format_recent_events(self) -> str:
        """格式化最近事件列表（标记是否已恢复）"""
        if not self._recent_events:
            return ""
        
        items = []
        for event in self._recent_events:
            obj_type = event.get('obj_type', '未知')
            alarm_id = event.get('alarm_id', '?')
            ts = event.get('timestamp', '')
            recovered = event.get('recovered', False)
            is_event_report = event.get('is_event_report', False)
            action = event.get('action', '?')
            
            if is_event_report:
                status = "[事件]"
            elif recovered:
                status = "[已恢复]"
            else:
                status = "[活跃]"
            items.append(f"{status} AlarmId:{alarm_id} objType:{obj_type} ({action}) @{ts}")
        
        return "; ".join(items)
