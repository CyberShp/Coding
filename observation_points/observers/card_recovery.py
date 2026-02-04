"""
卡修复监测观察点

监测 /OSM/log/cur_debug/messages 日志中的 recover chiperr 相关事件。
统计总次数并保留最近3次的详细信息（时间戳、PCIe槽位）。
"""

import logging
import re
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import tail_file

logger = logging.getLogger(__name__)


class CardRecoveryObserver(BaseObserver):
    """
    卡修复监测观察点
    
    功能：
    - 监测 messages 日志中的 "recover chiperr" 关键字
    - 统计累计修复次数
    - 记录最近3次修复的时间和 PCIe 槽位号
    """
    
    # PCIe 槽位号提取正则：完整提取 dev(0:x.0) 或 top(0:x.0) 格式
    PCIE_SLOT_PATTERN = re.compile(r'((?:dev|top)\(0:\d+\.0\))', re.IGNORECASE)
    
    # 日志时间戳格式
    TIMESTAMP_PATTERNS = [
        # 2024-01-15 10:30:45
        r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})',
        # Jan 15 10:30:45
        r'([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})',
        # [12345.678901]
        r'\[(\d+\.\d+)\]',
    ]
    
    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        
        self.log_path = Path(config.get('log_path', '/OSM/log/cur_debug/messages'))
        self.keyword = config.get('keyword', 'recover chiperr')
        self.max_lines_per_check = config.get('max_lines_per_check', 1000)
        
        # 文件读取位置
        self._file_position = 0
        self._first_run = True
        
        # 统计数据
        self._total_count = 0
        self._recent_events = deque(maxlen=3)  # type: deque
    
    def check(self) -> ObserverResult:
        """检查卡修复事件"""
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
        
        # 本次检测到的事件数
        new_count = 0
        
        # 分析每一行
        for line in new_lines:
            if self.keyword.lower() in line.lower():
                new_count += 1
                self._total_count += 1
                
                # 解析事件详情
                event = self._parse_event(line)
                self._recent_events.append(event)
                
                logger.warning(f"[CardRecovery] slot={event['slot']} @{event['timestamp']}")
        
        # 构建结果
        details = {
            'total_count': self._total_count,
            'recent_events': list(self._recent_events),
            'log_path': str(self.log_path),
            'new_count': new_count,
        }
        
        if new_count > 0:
            # 格式化最近3次事件信息
            recent_str = self._format_recent_events()
            message = f"卡修复统计: 总计 {self._total_count} 次，本次新增 {new_count} 次。{recent_str}"
            
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.ERROR,
                message=message,
                details=details,
            )
        
        return self.create_result(
            has_alert=False,
            message=f"卡修复检查正常（累计: {self._total_count} 次）",
            details=details,
        )
    
    def _parse_event(self, line: str) -> Dict[str, Any]:
        """解析日志行，提取时间戳和PCIe槽位号"""
        timestamp = self._parse_timestamp(line)
        slot = self._parse_pcie_slot(line)
        
        return {
            'timestamp': timestamp or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'slot': slot,
            'line': line[:200],  # 保留部分原始行
        }
    
    def _parse_timestamp(self, line: str) -> Optional[str]:
        """尝试从日志行解析时间戳"""
        for pattern in self.TIMESTAMP_PATTERNS:
            match = re.search(pattern, line)
            if match:
                return match.group(1)
        return None
    
    def _parse_pcie_slot(self, line: str) -> Optional[str]:
        """从日志行提取PCIe槽位号"""
        match = self.PCIE_SLOT_PATTERN.search(line)
        if match:
            return match.group(1)
        return None
    
    def _format_recent_events(self) -> str:
        """格式化最近事件列表"""
        if not self._recent_events:
            return ""
        
        items = []
        for event in self._recent_events:
            slot_str = f"slot={event['slot']}" if event['slot'] else "slot=未知"
            items.append(f"[{event['timestamp']} {slot_str}]")
        
        return f"最近{len(items)}次: " + ", ".join(items)
