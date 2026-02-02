"""
卡修复监测观察点

监测 /OSM/log/coffer_log/cur_debug/messages 日志中的 recovery 相关事件。
检测异常的 probe/remove 和卡修复行为。
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import tail_file

logger = logging.getLogger(__name__)


class CardRecoveryObserver(BaseObserver):
    """
    卡修复监测观察点
    
    功能：
    - 监测 messages 日志中的 recovery 关键字
    - 检测 probe/remove 事件
    - 支持排除已知的故障注入场景
    """
    
    # 默认关键字模式
    DEFAULT_PATTERNS = [
        r'recovery',
        r'probe.*failed',
        r'remove.*device',
        r'pci.*error',
        r'link.*reset',
        r'device.*reset',
        r'fatal.*error',
        r'uncorrectable.*error',
    ]
    
    def __init__(self, name: str, config: dict[str, Any]):
        super().__init__(name, config)
        
        self.log_path = Path(config.get('log_path', '/OSM/log/coffer_log/cur_debug/messages'))
        self.keywords = config.get('keywords', ['recovery', 'probe', 'remove'])
        self.exclude_patterns = config.get('exclude_patterns', [])
        self.max_lines_per_check = config.get('max_lines_per_check', 1000)
        
        # 编译正则表达式
        patterns = config.get('patterns', self.DEFAULT_PATTERNS)
        self._patterns = [re.compile(p, re.IGNORECASE) for p in patterns]
        self._exclude_patterns = [re.compile(p, re.IGNORECASE) for p in self.exclude_patterns]
        
        # 文件读取位置
        self._file_position = 0
        
        # 已检测到的事件（用于去重）
        self._recent_events: list[dict] = []
        self._max_recent_events = 100
    
    def check(self) -> ObserverResult:
        """检查卡修复事件"""
        alerts = []
        details = {
            'events': [],
            'log_path': str(self.log_path),
        }
        
        # 读取新增日志行
        new_lines, new_position = tail_file(
            self.log_path,
            self._file_position,
            self.max_lines_per_check
        )
        self._file_position = new_position
        
        # 分析每一行
        for line in new_lines:
            event = self._analyze_line(line)
            if event:
                # 检查是否应该排除
                if self._should_exclude(line):
                    logger.debug(f"排除事件: {line[:100]}")
                    continue
                
                # 检查是否重复
                if self._is_duplicate(event):
                    continue
                
                alerts.append(event['summary'])
                details['events'].append(event)
                self._add_recent_event(event)
                
                logger.warning(f"检测到卡修复事件: {event['summary']}")
        
        if alerts:
            message = f"检测到卡修复事件: {len(alerts)} 个"
            if alerts:
                message += f" - {alerts[0]}"
            
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.ERROR,
                message=message,
                details=details,
            )
        
        return self.create_result(
            has_alert=False,
            message="卡修复检查正常",
            details={'lines_checked': len(new_lines)},
        )
    
    def _analyze_line(self, line: str) -> dict | None:
        """分析日志行，检测关键事件"""
        if not line.strip():
            return None
        
        # 检查是否匹配任何关键字模式
        matched_patterns = []
        for pattern in self._patterns:
            if pattern.search(line):
                matched_patterns.append(pattern.pattern)
        
        if not matched_patterns:
            return None
        
        # 解析时间戳（尝试多种格式）
        timestamp = self._parse_timestamp(line)
        
        # 提取关键信息
        event = {
            'timestamp': timestamp or datetime.now().isoformat(),
            'line': line[:500],  # 限制长度
            'matched_patterns': matched_patterns,
            'event_type': self._classify_event(line, matched_patterns),
            'summary': self._generate_summary(line, matched_patterns),
        }
        
        return event
    
    def _parse_timestamp(self, line: str) -> str | None:
        """尝试从日志行解析时间戳"""
        # 常见的日志时间戳格式
        patterns = [
            # 2024-01-15 10:30:45
            r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})',
            # Jan 15 10:30:45
            r'([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})',
            # [12345.678901]
            r'\[(\d+\.\d+)\]',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                return match.group(1)
        
        return None
    
    def _classify_event(self, line: str, patterns: list[str]) -> str:
        """分类事件类型"""
        line_lower = line.lower()
        
        if 'recovery' in line_lower:
            if 'start' in line_lower or 'begin' in line_lower:
                return 'recovery_start'
            elif 'complete' in line_lower or 'success' in line_lower:
                return 'recovery_complete'
            elif 'fail' in line_lower or 'error' in line_lower:
                return 'recovery_failed'
            return 'recovery'
        
        if 'probe' in line_lower:
            if 'fail' in line_lower:
                return 'probe_failed'
            return 'probe'
        
        if 'remove' in line_lower:
            return 'device_remove'
        
        if 'reset' in line_lower:
            return 'device_reset'
        
        if 'fatal' in line_lower or 'uncorrectable' in line_lower:
            return 'fatal_error'
        
        return 'unknown'
    
    def _generate_summary(self, line: str, patterns: list[str]) -> str:
        """生成事件摘要"""
        # 提取关键部分
        summary_parts = []
        
        # 添加匹配的关键字
        keywords = set()
        for p in patterns:
            # 从正则中提取关键词
            word = re.sub(r'[.*?+\[\]()\\]', '', p).split('|')[0]
            if word:
                keywords.add(word.lower())
        
        if keywords:
            summary_parts.append('/'.join(sorted(keywords)))
        
        # 尝试提取设备信息
        device_match = re.search(r'(pci|device|port|eth|ens|bond)\S*', line, re.IGNORECASE)
        if device_match:
            summary_parts.append(device_match.group(0)[:30])
        
        if summary_parts:
            return ' - '.join(summary_parts)
        
        # 如果无法提取，返回截断的原始行
        return line[:80].strip()
    
    def _should_exclude(self, line: str) -> bool:
        """检查是否应该排除该行"""
        for pattern in self._exclude_patterns:
            if pattern.search(line):
                return True
        return False
    
    def _is_duplicate(self, event: dict) -> bool:
        """检查事件是否重复"""
        # 简单的去重：检查最近是否有相同的摘要
        for recent in self._recent_events:
            if recent.get('summary') == event.get('summary'):
                return True
        return False
    
    def _add_recent_event(self, event: dict):
        """添加到最近事件列表"""
        self._recent_events.append(event)
        # 保持列表大小
        if len(self._recent_events) > self._max_recent_events:
            self._recent_events.pop(0)
    
    def set_fault_injection_mode(self, enabled: bool, patterns: list[str] | None = None):
        """
        设置故障注入模式
        
        在故障注入期间，可以临时排除某些模式，避免误报。
        
        Args:
            enabled: 是否启用故障注入模式
            patterns: 要排除的额外模式
        """
        if enabled and patterns:
            for p in patterns:
                try:
                    compiled = re.compile(p, re.IGNORECASE)
                    self._exclude_patterns.append(compiled)
                    logger.info(f"故障注入模式：添加排除模式 {p}")
                except re.error as e:
                    logger.error(f"无效的正则表达式: {p}, 错误: {e}")
        elif not enabled:
            # 恢复原始排除模式
            self._exclude_patterns = [
                re.compile(p, re.IGNORECASE) 
                for p in self.exclude_patterns
            ]
            logger.info("故障注入模式：已禁用")
