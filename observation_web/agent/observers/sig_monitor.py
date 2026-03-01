"""
sig 信号监控观察点

监测 /OSM/log/cur_debug/messages 日志中的 sig 信号日志。
除白名单（sig 15、sig 61）外的信号出现即上报 ERROR。
"""

import logging
import re
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import tail_file

logger = logging.getLogger(__name__)


class SigMonitorObserver(BaseObserver):
    """
    sig 信号监控观察点
    
    功能：
    - 监测 messages 日志中的 sig 信号日志
    - 白名单信号（默认 sig 15、sig 61）不告警
    - 其他信号出现即上报 ERROR
    - 从脚本启动时刻开始监控，不处理历史数据
    """
    
    # 匹配 sig 后跟数字的正则
    SIG_PATTERN = re.compile(r'\bsig\s*(\d+)\b', re.IGNORECASE)
    
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
        
        # 白名单信号（不告警）
        self.whitelist = set(config.get('whitelist', [15, 61]))  # type: Set[int]
        
        # 文件读取位置
        self._file_position = 0
        self._first_run = True
        
        # 统计数据
        self._total_alerts = 0
        self._recent_events = deque(maxlen=20)  # type: deque
    
    def check(self) -> ObserverResult:
        """检查 sig 信号日志"""
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
        
        # 本次检测到的非白名单信号
        new_alerts = []
        
        # 分析每一行
        for line in new_lines:
            matches = self.SIG_PATTERN.findall(line)
            
            for sig_str in matches:
                try:
                    sig_num = int(sig_str)
                except ValueError:
                    continue
                
                # 检查是否在白名单中
                if sig_num in self.whitelist:
                    logger.debug(f"忽略白名单信号 sig {sig_num}")
                    continue
                
                # 非白名单信号，记录告警
                self._total_alerts += 1
                event = self._parse_event(line, sig_num)
                new_alerts.append(event)
                self._recent_events.append(event)
                
                logger.error(f"检测到异常信号: sig {sig_num}")
        
        # 构建结果
        details = {
            'total_alerts': self._total_alerts,
            'new_alerts': new_alerts,
            'recent_events': list(self._recent_events),
            'log_path': str(self.log_path),
            'whitelist': list(self.whitelist),
        }
        
        if new_alerts:
            sig_nums = [e['signal'] for e in new_alerts]
            message = f"检测到异常信号: {', '.join(f'sig {s}' for s in sig_nums[:5])}"
            if len(sig_nums) > 5:
                message += f" (共 {len(sig_nums)} 个)"
            
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.ERROR,
                message=message,
                details=details,
            )
        
        return self.create_result(
            has_alert=False,
            message=f"sig 信号检查正常（累计告警: {self._total_alerts}）",
            details=details,
        )
    
    def _parse_event(self, line: str, sig_num: int) -> Dict[str, Any]:
        """解析日志行，提取时间戳和信号信息"""
        timestamp = self._parse_timestamp(line)
        
        return {
            'timestamp': timestamp or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'signal': sig_num,
            'line': line[:300],  # 保留部分原始行
        }
    
    def _parse_timestamp(self, line: str) -> Optional[str]:
        """尝试从日志行解析时间戳"""
        for pattern in self.TIMESTAMP_PATTERNS:
            match = re.search(pattern, line)
            if match:
                return match.group(1)
        return None
