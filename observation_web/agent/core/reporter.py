"""
告警与上报模块

支持多种输出方式：文件、syslog、控制台、HTTP 推送。
包含告警冷却、去重、脱敏功能。
支持指标数据记录（CPU/内存等时序数据）。
"""

import json
import logging
import queue
import re
import syslog
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

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
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'observer_name': self.observer_name,
            'level': self.level.value,
            'message': self.message,
            'timestamp': self.timestamp.isoformat(),
            'details': self.details,
        }


class Reporter:
    """
    告警上报器
    
    功能：
    - 多输出方式：文件、syslog、控制台
    - HTTP 推送：主动将告警推送到 Web 后端
    - 告警冷却：同一观察点的相同告警在冷却期内不重复上报
    - 脱敏：自动对敏感信息进行脱敏处理
    - 指标记录：记录 CPU/内存等时序数据到 metrics.jsonl
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
    
    # 最大指标文件大小 (10MB), 超过后轮转
    MAX_METRICS_FILE_SIZE = 10 * 1024 * 1024

    # 最大告警文件大小 (10MB), 超过后轮转（与指标文件同阈值）
    MAX_ALERT_FILE_SIZE = 10 * 1024 * 1024

    # HTTP 推送队列默认容量（有界，防止风暴时无限堆积/线程爆炸）
    DEFAULT_PUSH_QUEUE_SIZE = 1000
    
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
        
        # HTTP push configuration
        self.push_enabled = config.get('push_enabled', False)
        self.push_url = config.get('push_url', '')  # e.g., "http://192.168.1.100:8000/api/ingest"
        self.push_timeout = config.get('push_timeout', 5)

        # HTTP 推送采用「单后台线程 + 有界队列」模式：
        # 每条告警/指标不再单独起线程，避免风暴时线程爆炸；队满时丢弃并计数。
        self._push_queue = None  # type: Optional[queue.Queue]
        self._push_worker = None  # type: Optional[threading.Thread]
        self._push_queue_size = config.get('push_queue_size', self.DEFAULT_PUSH_QUEUE_SIZE)
        self._push_dropped = 0
        self._push_lock = threading.Lock()
        
        # Metrics recording
        self.metrics_enabled = config.get('metrics_enabled', True)
        metrics_dir = self.file_path.parent if self.file_path else Path('/var/log/observation-points')
        self.metrics_path = metrics_dir / 'metrics.jsonl'
        
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
                # 轮转检查：alerts.log 也会持续增长，超过阈值时轮转，
                # 否则会无限增长写满被监控机磁盘。
                if (self.file_path.exists()
                        and self.file_path.stat().st_size > self.MAX_ALERT_FILE_SIZE):
                    self._rotate_alerts()
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
        
        # HTTP 推送（异步，不阻塞主流程）
        if self.push_enabled and self.push_url:
            self._push_to_web(alert)
        
        # 简洁的日志输出
        level_tag = alert.level.value.upper()
        logger.info(f"[{level_tag}] {alert.observer_name}: {alert.message}")
    
    def _ensure_push_worker(self):
        """惰性启动单个后台推送线程与有界队列（首次推送时创建）。"""
        if self._push_queue is not None:
            return
        with self._push_lock:
            if self._push_queue is not None:
                return
            self._push_queue = queue.Queue(maxsize=self._push_queue_size)
            self._push_worker = threading.Thread(
                target=self._push_worker_loop,
                name='reporter-push',
                daemon=True,
            )
            self._push_worker.start()

    def _push_worker_loop(self):
        """后台推送线程主循环：从队列取出 payload 顺序 POST 到 Web 后端。"""
        import urllib.request
        while True:
            payload = self._push_queue.get()
            try:
                data = json.dumps(payload).encode('utf-8')
                req = urllib.request.Request(
                    self.push_url,
                    data=data,
                    headers={'Content-Type': 'application/json'},
                )
                urllib.request.urlopen(req, timeout=self.push_timeout)
            except Exception as e:
                # 推送失败非致命，debug 记录避免日志膨胀
                logger.debug(f"推送失败 (非致命): {e}")
            finally:
                self._push_queue.task_done()

    def _enqueue_push(self, payload: Dict[str, Any]):
        """将 payload 投递到有界推送队列；队满则丢弃并计数（背压）。"""
        self._ensure_push_worker()
        try:
            self._push_queue.put_nowait(payload)
        except queue.Full:
            self._push_dropped += 1
            logger.warning(
                "推送队列已满 (容量=%d)，丢弃 %s 消息 (累计丢弃 %d 条)",
                self._push_queue_size,
                payload.get('type', 'unknown'),
                self._push_dropped,
            )

    def _push_to_web(self, alert: Alert):
        """将告警投递到后台推送队列（fire-and-forget，带背压）"""
        self._enqueue_push({'type': 'alert', **alert.to_dict()})
    
    def record_metrics(self, metrics: Dict[str, Any]):
        """
        记录指标数据到 metrics.jsonl 文件。
        
        Args:
            metrics: 指标字典，例如 {"cpu0": 45.2, "mem_used_mb": 3200}
        """
        if not self.metrics_enabled:
            return
        
        try:
            # 确保目录存在
            self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 轮转检查
            if self.metrics_path.exists() and self.metrics_path.stat().st_size > self.MAX_METRICS_FILE_SIZE:
                self._rotate_metrics()
            
            # 添加时间戳
            record = {
                'ts': datetime.now().isoformat(),
                **metrics,
            }
            
            with open(self.metrics_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
            
            # 也推送指标到 Web 后端（如果启用）
            if self.push_enabled and self.push_url:
                self._push_metrics_to_web(record)
                
        except Exception as e:
            logger.error(f"写入指标文件失败: {e}")
    
    def _push_metrics_to_web(self, record: Dict[str, Any]):
        """将指标投递到后台推送队列（fire-and-forget，带背压）"""
        self._enqueue_push({'type': 'metrics', **record})

    def _rotate_file(self, path: Path, rotated_suffix: str):
        """通用文件轮转：将 path 重命名为带 rotated_suffix 的备份文件。

        Args:
            path: 待轮转的文件
            rotated_suffix: 备份文件后缀（如 '.jsonl.1' / '.log.1'）
        """
        try:
            rotated = path.with_suffix(rotated_suffix)
            if rotated.exists():
                rotated.unlink()
            # 再次确认源文件存在（可能已被其他轮转/清理动作移走）
            if path.exists():
                path.rename(rotated)
                logger.info(f"文件已轮转: {path.name} -> {rotated.name}")
        except FileNotFoundError:
            # 源文件在重命名瞬间消失，视为已轮转，无需处理
            pass
        except Exception as e:
            logger.error(f"文件轮转失败 ({path}): {e}")

    def _rotate_metrics(self):
        """轮转指标文件"""
        self._rotate_file(self.metrics_path, '.jsonl.1')

    def _rotate_alerts(self):
        """轮转告警文件"""
        self._rotate_file(self.file_path, self.file_path.suffix + '.1')
