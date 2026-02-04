"""
告警与上报模块

支持多种输出方式：文件、syslog、控制台。
包含告警冷却、去重、脱敏功能。
"""

import json
import logging
import re
import syslog
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from .base import ObserverResult, AlertLevel

logger = logging.getLogger(__name__)


@dataclass
class Alert:
    """告警记录"""
    observer_name: str
    level: AlertLevel
    message: str
    timestamp: datetime
    details: Dict[str, Any]
    
    def to_json(self) -> str:
        """转换为 JSON 字符串"""
        return json.dumps({
            'observer_name': self.observer_name,
            'level': self.level.value,
            'message': self.message,
            'timestamp': self.timestamp.isoformat(),
            'details': self.details,
        }, ensure_ascii=False)


class Reporter:
    """
    告警上报器
    
    功能：
    - 多输出方式：文件、syslog、控制台
    - 告警冷却：同一观察点的相同告警在冷却期内不重复上报
    - 脱敏：自动对敏感信息进行脱敏处理
    """
    
    # 默认脱敏规则
    DEFAULT_SANITIZE_PATTERNS = [
        (r'(password\s*[=:]\s*)\S+', r'\1***'),
        (r'(passwd\s*[=:]\s*)\S+', r'\1***'),
        (r'(secret\s*[=:]\s*)\S+', r'\1***'),
        (r'(token\s*[=:]\s*)\S+', r'\1***'),
        (r'(nqn\.[a-zA-Z0-9.\-:]+)', r'nqn.***'),
        (r'(iqn\.[a-zA-Z0-9.\-:]+)', r'iqn.***'),
    ]
    
    # 告警级别优先级（用于筛选）
    LEVEL_PRIORITY = {
        AlertLevel.INFO: 0,
        AlertLevel.WARNING: 1,
        AlertLevel.ERROR: 2,
        AlertLevel.CRITICAL: 3,
    }
    
    def __init__(self, config: Dict[str, Any], dry_run: bool = False, min_level: str = 'INFO'):
        """
        初始化上报器
        
        Args:
            config: 上报器配置
            dry_run: 试运行模式
            min_level: 最低告警级别筛选（INFO/WARNING/ERROR）
        """
        self.config = config
        self.dry_run = dry_run
        
        # 解析最低告警级别
        level_map = {
            'INFO': AlertLevel.INFO,
            'WARNING': AlertLevel.WARNING,
            'ERROR': AlertLevel.ERROR,
            'CRITICAL': AlertLevel.CRITICAL,
        }
        self.min_level = level_map.get(min_level.upper(), AlertLevel.INFO)
        
        self.output_mode = config.get('output', 'file')  # file, syslog, both, console
        self.file_path = Path(config.get('file_path', '/var/log/observation-points/alerts.log'))
        self.syslog_facility = config.get('syslog_facility', 'local0')
        self.cooldown_seconds = config.get('cooldown_seconds', 300)
        
        # 告警冷却记录
        self._cooldown_cache = {}  # type: Dict[str, Dict[str, datetime]]
        
        # 初始化输出
        self._init_outputs()
        
        # 编译脱敏正则
        self._sanitize_patterns = [
            (re.compile(pattern, re.IGNORECASE), replacement)
            for pattern, replacement in self.DEFAULT_SANITIZE_PATTERNS
        ]
    
    def _init_outputs(self):
        """初始化输出通道"""
        if self.output_mode in ('file', 'both'):
            # 确保目录存在
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
        
        if self.output_mode in ('syslog', 'both'):
            # 映射 syslog facility
            facility_map = {
                'local0': syslog.LOG_LOCAL0,
                'local1': syslog.LOG_LOCAL1,
                'local2': syslog.LOG_LOCAL2,
                'local3': syslog.LOG_LOCAL3,
                'local4': syslog.LOG_LOCAL4,
                'local5': syslog.LOG_LOCAL5,
                'local6': syslog.LOG_LOCAL6,
                'local7': syslog.LOG_LOCAL7,
                'user': syslog.LOG_USER,
            }
            facility = facility_map.get(self.syslog_facility, syslog.LOG_LOCAL0)
            syslog.openlog('observation-points', syslog.LOG_PID, facility)
    
    def report(self, result: ObserverResult):
        """
        上报告警
        
        Args:
            result: 观察点检查结果
        """
        if not result.has_alert:
            return
        
        # 检查告警级别是否达到最低要求
        result_priority = self.LEVEL_PRIORITY.get(result.alert_level, 0)
        min_priority = self.LEVEL_PRIORITY.get(self.min_level, 0)
        if result_priority < min_priority:
            return  # 低于最低级别，静默跳过
        
        # 检查冷却（sticky 告警不受冷却限制）
        if not result.sticky and self._is_in_cooldown(result):
            return  # 冷却期内，静默跳过
        
        # 为 sticky 告警添加标记
        message = self._sanitize(result.message)
        if result.sticky:
            message = f"[持续] {message}"
        
        # 创建告警
        alert = Alert(
            observer_name=result.observer_name,
            level=result.alert_level,
            message=message,
            timestamp=result.timestamp,
            details=self._sanitize_dict(result.details),
        )
        
        # 试运行模式
        if self.dry_run:
            logger.info(f"[DRY-RUN] {alert.observer_name}: {alert.message}")
            return
        
        # 实际上报
        self._do_report(alert)
        
        # 更新冷却缓存（sticky 告警也更新，以便跟踪）
        self._update_cooldown(result)
    
    def _is_in_cooldown(self, result: ObserverResult) -> bool:
        """检查告警是否在冷却期内"""
        observer_cache = self._cooldown_cache.get(result.observer_name, {})
        msg_hash = hash(result.message)
        
        last_time = observer_cache.get(str(msg_hash))
        if last_time is None:
            return False
        
        elapsed = (datetime.now() - last_time).total_seconds()
        return elapsed < self.cooldown_seconds
    
    def _update_cooldown(self, result: ObserverResult):
        """更新冷却缓存"""
        if result.observer_name not in self._cooldown_cache:
            self._cooldown_cache[result.observer_name] = {}
        
        msg_hash = str(hash(result.message))
        self._cooldown_cache[result.observer_name][msg_hash] = datetime.now()
        
        # 清理过期的冷却记录（避免内存泄漏）
        self._cleanup_cooldown_cache()
    
    def _cleanup_cooldown_cache(self):
        """清理过期的冷却记录"""
        now = datetime.now()
        max_age = self.cooldown_seconds * 2  # 保留2倍冷却时间
        
        for observer_name in list(self._cooldown_cache.keys()):
            cache = self._cooldown_cache[observer_name]
            expired_keys = [
                k for k, v in cache.items()
                if (now - v).total_seconds() > max_age
            ]
            for k in expired_keys:
                del cache[k]
            
            if not cache:
                del self._cooldown_cache[observer_name]
    
    def _sanitize(self, text: str) -> str:
        """脱敏处理"""
        result = text
        for pattern, replacement in self._sanitize_patterns:
            result = pattern.sub(replacement, result)
        return result
    
    def _sanitize_dict(self, data: Dict) -> Dict:
        """对字典中的字符串值进行脱敏，datetime 转为 isoformat 以便 JSON 序列化"""
        result = {}
        for key, value in data.items():
            if isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, str):
                result[key] = self._sanitize(value)
            elif isinstance(value, dict):
                result[key] = self._sanitize_dict(value)
            elif isinstance(value, list):
                result[key] = [
                    (v.isoformat() if isinstance(v, datetime) else
                     (self._sanitize(v) if isinstance(v, str) else v))
                    for v in value
                ]
            else:
                result[key] = value
        return result
    
    def _do_report(self, alert: Alert):
        """执行实际上报"""
        json_str = alert.to_json()
        
        # 控制台输出
        if self.output_mode == 'console':
            print(f"[ALERT] {json_str}")
            return
        
        # 文件输出
        if self.output_mode in ('file', 'both'):
            try:
                with open(self.file_path, 'a', encoding='utf-8') as f:
                    f.write(json_str + '\n')
            except Exception as e:
                logger.error(f"写入告警文件失败: {e}")
        
        # syslog 输出
        if self.output_mode in ('syslog', 'both'):
            try:
                level_map = {
                    AlertLevel.INFO: syslog.LOG_INFO,
                    AlertLevel.WARNING: syslog.LOG_WARNING,
                    AlertLevel.ERROR: syslog.LOG_ERR,
                    AlertLevel.CRITICAL: syslog.LOG_CRIT,
                }
                syslog_level = level_map.get(alert.level, syslog.LOG_INFO)
                syslog.syslog(syslog_level, json_str)
            except Exception as e:
                logger.error(f"写入 syslog 失败: {e}")
        
        # 简洁的日志输出
        level_tag = alert.level.value.upper()
        logger.info(f"[{level_tag}] {alert.observer_name}: {alert.message}")
