"""
敏感信息监测观察点

监测 messages 日志中是否打印了敏感信息，如明文密码、NQN、IQN 等。
检测到敏感信息时告警，便于及时修复。

优化：
- 上下文排除规则：排除配置项名称、文件路径、提示文本等误报场景
- 值验证增强：检查值的合理性，排除纯数字配置值、常见配置值等
- 配置白名单：支持配置白名单模式和路径
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.base import BaseObserver, ObserverResult, AlertLevel
from ..utils.helpers import tail_file

logger = logging.getLogger(__name__)


class SensitiveInfoObserver(BaseObserver):
    """
    敏感信息监测观察点
    
    功能：
    - 扫描日志文件中的敏感信息
    - 支持多种敏感信息模式（密码、NQN、IQN等）
    - 上下文感知，减少误报
    - 支持白名单配置
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
            # IP + 用户名/密码组合（更严格的模式）
            r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s*[,;]\s*(?:user|admin|root)\s*[,;]\s*([^\s,;]+)',
        ],
    }
    
    # 已知的安全模式（不应告警）
    SAFE_PATTERNS = [
        r'password\s*[=:]\s*\*+',           # 已脱敏的密码
        r'password\s*[=:]\s*<masked>',
        r'password\s*[=:]\s*\[hidden\]',
        r'password\s*[=:]\s*\[REDACTED\]',
        r'password\s*[=:]\s*#',              # 注释
    ]
    
    # 上下文排除模式（匹配这些模式的行不告警）
    EXCLUDE_CONTEXT_PATTERNS = [
        # 配置项名称（password_xxx = value）
        r'password_\w+\s*[=:]',
        r'passwd_\w+\s*[=:]',
        # 文件路径
        r'password[^=:]*[/\\][a-zA-Z0-9_/\\]+',
        # 提示文本
        r'(?:enter|input|type|confirm|prompt)\s+(?:your\s+)?password',
        r'password\s+(?:is\s+)?(?:required|needed|missing)',
        # 状态消息
        r'password\s+(?:check|verify|valid|invalid|correct|incorrect|match|mismatch|fail|error|success)',
        r'(?:check|verify|validate)\s+password',
        # 字段名定义
        r'(?:field|column|key|name|label|param)\s*[=:]\s*["\']?password',
        # 函数/方法名
        r'(?:get|set|read|write|check|verify|validate)_?password',
        r'password_(?:hash|encrypt|decrypt|encode|decode)',
        # 长度、策略等配置
        r'password[_-]?(?:length|size|min|max|policy|strength|expire|age)',
        # 日志格式字符串
        r'%\(password\)s',
        r'\{password\}',
    ]
    
    # 常见的非密码配置值
    NON_PASSWORD_VALUES = [
        # 布尔值
        'true', 'false', 'yes', 'no', 'on', 'off',
        # 状态值
        'enabled', 'disabled', 'required', 'optional',
        'strong', 'weak', 'medium', 'none', 'null', 'empty',
        # 常见默认值
        'default', 'auto', 'manual',
        # 文件路径关键字
        'file', 'path', 'dir', 'directory',
    ]
    
    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        
        self.log_paths = [Path(p) for p in config.get('log_paths', ['/var/log/messages'])]
        self.max_lines_per_check = config.get('max_lines_per_check', 500)
        self.cooldown_seconds = config.get('cooldown_seconds', 300)
        
        # 白名单配置
        self.whitelist_patterns = config.get('whitelist_patterns', [])
        self.whitelist_paths = config.get('whitelist_paths', [
            '/etc/passwd', '/etc/shadow', 'passwd.txt'
        ])
        
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
        
        # 编译上下文排除模式
        self._exclude_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.EXCLUDE_CONTEXT_PATTERNS
        ]
        
        # 编译白名单模式
        self._whitelist_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.whitelist_patterns
        ]
        
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
                        f"[SensitiveInfo] {finding['category']} in {log_path.name}:{line_num}"
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
            message="",  # 无告警时不输出
            details={'files_checked': details['files_checked']},
        )
    
    def _scan_line(self, line: str) -> List[Dict]:
        """扫描单行内容"""
        findings = []
        
        # 1. 检查是否匹配安全模式
        for safe_pattern in self._safe_patterns:
            if safe_pattern.search(line):
                return []
        
        # 2. 检查是否匹配上下文排除模式
        for exclude_pattern in self._exclude_patterns:
            if exclude_pattern.search(line):
                return []
        
        # 3. 检查是否匹配用户白名单模式
        for whitelist_pattern in self._whitelist_patterns:
            if whitelist_pattern.search(line):
                return []
        
        # 4. 检查是否包含白名单路径
        for whitelist_path in self.whitelist_paths:
            if whitelist_path in line:
                return []
        
        # 5. 检查各类敏感模式
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
                        
                        # 增强的值验证
                        if category in ('password', 'secret') and not self._is_likely_password(value, line):
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
            'xxx', 'XXX', '***', '---', '...',
            'password', 'passwd', 'secret', 'token',
            'your_password', 'your_secret', 'your_token',
            '<password>', '<secret>', '<token>',
            '${PASSWORD}', '${SECRET}', '${TOKEN}',
            '$PASSWORD', '$SECRET', '$TOKEN',
            'null', 'none', 'empty', 'undefined',
            'example', 'sample', 'test', 'demo',
            'placeholder', 'changeme', 'fixme',
        ]
        
        value_lower = value.lower().strip()
        
        # 检查是否全是特殊字符
        if all(c in '*-_x.' for c in value_lower):
            return True
        
        # 检查是否是占位符
        if value_lower in [p.lower() for p in placeholders]:
            return True
        
        # 检查是否是常见的模板变量格式
        if re.match(r'^\$\{?\w+\}?$', value):
            return True
        
        return False
    
    def _is_likely_password(self, value: str, line: str) -> bool:
        """
        判断是否可能是真实密码
        
        Args:
            value: 匹配到的值
            line: 原始日志行
            
        Returns:
            是否可能是真实密码
        """
        # 1. 长度检查（真实密码通常 6-64 字符）
        if len(value) < 6 or len(value) > 64:
            return False
        
        # 2. 排除纯数字（可能是配置值如 password_length=8）
        if value.isdigit():
            return False
        
        # 3. 排除常见配置值
        if value.lower() in self.NON_PASSWORD_VALUES:
            return False
        
        # 4. 排除文件路径
        if value.startswith('/') or value.startswith('./') or value.startswith('..'):
            return False
        
        # 5. 排除看起来像变量名的值（全小写下划线分隔）
        if re.match(r'^[a-z][a-z0-9_]+$', value) and '_' in value:
            # 但如果看起来像真密码（包含数字且较长），则保留
            if not any(c.isdigit() for c in value) or len(value) < 10:
                return False
        
        # 6. 排除以特定后缀结尾的值（可能是配置项名）
        config_suffixes = ['_file', '_path', '_dir', '_name', '_type', '_mode', '_policy']
        for suffix in config_suffixes:
            if value.lower().endswith(suffix):
                return False
        
        # 7. 检查是否是赋值语句上下文（更可能是真实密码）
        # password=xxx 或 password: xxx 形式
        assign_pattern = r'(?:password|passwd|pwd)\s*[=:]\s*[\'"]?' + re.escape(value)
        if re.search(assign_pattern, line, re.IGNORECASE):
            return True
        
        # 如果以上检查都通过，认为可能是密码
        return True
    
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
