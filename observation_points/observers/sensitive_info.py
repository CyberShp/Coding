"""
敏感信息监测观察点

监测 messages 日志中是否打印了敏感信息，如明文密码、NQN、IQN 等。
检测到敏感信息时告警，便于及时修复。
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import tail_file

logger = logging.getLogger(__name__)


class SensitiveInfoObserver(BaseObserver):
    """
    敏感信息监测观察点
    
    功能：
    - 扫描日志文件中的敏感信息
    - 支持多种敏感信息模式（密码、NQN、IQN等）
    - 检测到后立即告警
    """
    
    # 默认敏感信息模式
    DEFAULT_PATTERNS = {
        'password': [
            r'password\s*[=:]\s*[\'"]?([^\s\'"]+)',
            r'passwd\s*[=:]\s*[\'"]?([^\s\'"]+)',
            r'pwd\s*[=:]\s*[\'"]?([^\s\'"]+)',
        ],
        'secret': [
            r'secret\s*[=:]\s*[\'"]?([^\s\'"]+)',
            r'token\s*[=:]\s*[\'"]?([^\s\'"]+)',
            r'api[_-]?key\s*[=:]\s*[\'"]?([^\s\'"]+)',
        ],
        'nqn': [
            r'(nqn\.[a-zA-Z0-9.\-:]+)',
        ],
        'iqn': [
            r'(iqn\.[a-zA-Z0-9.\-:]+)',
        ],
        'ip_with_cred': [
            # IP + 用户名/密码组合
            r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s*[,;]\s*(user|admin|root)\s*[,;]\s*([^\s]+)',
        ],
    }
    
    # 已知的安全模式（不应告警）
    SAFE_PATTERNS = [
        r'password\s*[=:]\s*\*+',  # 已脱敏的密码
        r'password\s*[=:]\s*<masked>',
        r'password\s*[=:]\s*\[hidden\]',
    ]
    
    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        
        self.log_paths = [Path(p) for p in config.get('log_paths', ['/var/log/messages'])]
        self.max_lines_per_check = config.get('max_lines_per_check', 500)
        self.cooldown_seconds = config.get('cooldown_seconds', 300)
        
        # 用户自定义模式
        user_patterns = config.get('patterns', [])
        
        # 编译所有模式
        self._patterns = {}  # type: Dict[str, List[Any]]
        for category, patterns in self.DEFAULT_PATTERNS.items():
            self._patterns[category] = [re.compile(p, re.IGNORECASE) for p in patterns]
        
        # 添加用户自定义模式
        if user_patterns:
            self._patterns['custom'] = [re.compile(p, re.IGNORECASE) for p in user_patterns]
        
        # 编译安全模式
        self._safe_patterns = [re.compile(p, re.IGNORECASE) for p in self.SAFE_PATTERNS]
        
        # 文件位置缓存
        self._file_positions = {}  # type: Dict[str, int]
        self._last_alerts = {}  # type: Dict[str, datetime]
        self._first_run = {}  # type: Dict[str, bool]
    
    def check(self) -> ObserverResult:
        """检查敏感信息"""
        alerts = []
        details = {
            'findings': [],
            'files_checked': [],
        }
        
        for log_path in self.log_paths:
            if not log_path.exists():
                continue
            
            details['files_checked'].append(str(log_path))
            
            # 读取新增内容
            position_key = str(log_path)
            last_position = self._file_positions.get(position_key, 0)
            
            # 首次运行时跳过历史数据
            skip_existing = self._first_run.get(position_key, True)
            self._first_run[position_key] = False
            
            new_lines, new_position = tail_file(
                log_path,
                last_position,
                self.max_lines_per_check,
                skip_existing=skip_existing
            )
            self._file_positions[position_key] = new_position
            
            # 检查每一行
            for line_num, line in enumerate(new_lines, start=1):
                findings = self._scan_line(line)
                
                for finding in findings:
                    # 检查冷却
                    alert_key = f"{finding['category']}:{finding['pattern']}"
                    if not self._can_alert(alert_key):
                        continue
                    
                    finding['file'] = str(log_path)
                    finding['line_num'] = line_num
                    
                    # 脱敏后的行内容
                    finding['context'] = self._redact_line(line)[:200]
                    
                    alerts.append(f"{finding['category']} 在 {log_path.name}")
                    details['findings'].append(finding)
                    
                    self._update_alert_time(alert_key)
                    
                    logger.warning(
                        f"检测到敏感信息: {finding['category']} 在 {log_path}:{line_num}"
                    )
        
        if alerts:
            # 去重统计
            alert_summary = {}
            for a in alerts:
                alert_summary[a] = alert_summary.get(a, 0) + 1
            
            summary_parts = [f"{k}({v})" if v > 1 else k for k, v in alert_summary.items()]
            message = f"检测到敏感信息: {', '.join(summary_parts[:5])}"
            
            return self.create_result(
                has_alert=True,
                alert_level=AlertLevel.ERROR,
                message=message,
                details=details,
            )
        
        return self.create_result(
            has_alert=False,
            message="敏感信息检查正常",
            details={'files_checked': details['files_checked']},
        )
    
    def _scan_line(self, line: str) -> List[Dict]:
        """扫描单行内容"""
        findings = []
        
        # 先检查是否匹配安全模式
        for safe_pattern in self._safe_patterns:
            if safe_pattern.search(line):
                return []  # 匹配安全模式，跳过
        
        # 检查各类敏感模式
        for category, patterns in self._patterns.items():
            for pattern in patterns:
                matches = pattern.findall(line)
                if matches:
                    for match in matches:
                        # 获取匹配的值
                        if isinstance(match, tuple):
                            value = match[0] if match else ''
                        else:
                            value = match
                        
                        # 过滤明显的占位符
                        if self._is_placeholder(value):
                            continue
                        
                        findings.append({
                            'category': category,
                            'pattern': pattern.pattern,
                            'match': self._redact_value(value),
                            'timestamp': datetime.now().isoformat(),
                        })
        
        return findings
    
    def _is_placeholder(self, value: str) -> bool:
        """检查是否是占位符"""
        placeholders = [
            'xxx', 'XXX', '***', '---',
            'password', 'passwd', 'secret',
            'your_password', 'your_secret',
            '<password>', '<secret>',
            '${PASSWORD}', '${SECRET}',
            'null', 'none', 'empty',
        ]
        
        value_lower = value.lower().strip()
        
        # 检查是否全是特殊字符
        if all(c in '*-_x' for c in value_lower):
            return True
        
        return value_lower in [p.lower() for p in placeholders]
    
    def _redact_value(self, value: str) -> str:
        """脱敏敏感值"""
        if len(value) <= 4:
            return '***'
        return value[:2] + '***' + value[-2:]
    
    def _redact_line(self, line: str) -> str:
        """脱敏整行内容"""
        result = line
        
        # 脱敏所有敏感模式匹配
        for category, patterns in self._patterns.items():
            for pattern in patterns:
                result = pattern.sub(lambda m: self._redact_match(m), result)
        
        return result
    
    def _redact_match(self, match: re.Match) -> str:
        """脱敏正则匹配结果"""
        full_match = match.group(0)
        groups = match.groups()
        
        if groups:
            # 替换捕获组中的敏感值
            result = full_match
            for g in groups:
                if g and len(g) > 3:
                    result = result.replace(g, '***')
            return result
        
        return '***'
    
    def _can_alert(self, alert_key: str) -> bool:
        """检查是否可以告警"""
        last_time = self._last_alerts.get(alert_key)
        if last_time is None:
            return True
        
        elapsed = (datetime.now() - last_time).total_seconds()
        return elapsed >= self.cooldown_seconds
    
    def _update_alert_time(self, alert_key: str):
        """更新告警时间"""
        self._last_alerts[alert_key] = datetime.now()
        
        # 清理过期记录
        now = datetime.now()
        expired = [
            k for k, v in self._last_alerts.items()
            if (now - v).total_seconds() > self.cooldown_seconds * 2
        ]
        for k in expired:
            del self._last_alerts[k]
