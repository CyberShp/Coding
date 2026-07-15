"""
告警与上报模块

支持多种输出方式：文件、syslog、控制台、HTTP 推送。
包含告警冷却、去重、脱敏功能。
支持指标数据记录（CPU/内存等时序数据）。
"""

import json
import hashlib
import logging
import os
import re
import sqlite3
import syslog
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .base import ObserverResult, AlertLevel, utc_now

logger = logging.getLogger(__name__)


class PersistentPushQueue:
    """Durable, bounded HTTP outbox with batched retries."""

    def __init__(self, url: str, array_id: str, path: Path, timeout: float = 5,
                 max_pending: int = 10000, batch_size: int = 100):
        self.batch_url = url.rstrip('/') + '/batch'
        self.array_id = array_id
        self.path = Path(path)
        self.timeout = float(timeout)
        self.max_pending = max(100, int(max_pending))
        self.batch_size = max(1, min(500, int(batch_size)))
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=10)
        self._conn.execute('PRAGMA journal_mode=WAL')
        self._conn.execute('PRAGMA synchronous=NORMAL')
        self._conn.execute(
            'CREATE TABLE IF NOT EXISTS outbox ('
            'id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, '
            'payload TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, '
            'next_attempt REAL NOT NULL DEFAULT 0, created_at REAL NOT NULL)'
        )
        self._conn.execute('CREATE INDEX IF NOT EXISTS ix_outbox_due ON outbox(next_attempt, id)')
        self._conn.commit()
        self._thread = threading.Thread(target=self._run, name='agent-push-outbox', daemon=True)
        self._thread.start()

    def enqueue(self, kind: str, payload: Dict[str, Any]):
        self.enqueue_many(kind, [payload])

    def enqueue_many(self, kind: str, payloads):
        if not payloads:
            return
        rows = [
            (kind, json.dumps({'type': kind, 'array_id': self.array_id, **payload}, ensure_ascii=False), time.time())
            for payload in payloads
        ]
        with self._lock:
            self._conn.executemany(
                'INSERT INTO outbox(kind, payload, created_at) VALUES (?, ?, ?)', rows,
            )
            self._trim_locked()
            self._conn.commit()

    def _trim_locked(self):
        total = self._conn.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]
        overflow = max(0, int(total) - self.max_pending)
        if not overflow:
            return
        self._conn.execute(
            'DELETE FROM outbox WHERE id IN ('
            "SELECT id FROM outbox ORDER BY CASE kind WHEN 'metrics' THEN 0 ELSE 1 END, id LIMIT ?)",
            (overflow,),
        )
        logger.warning('HTTP outbox 已满，丢弃 %s 条最旧低优先级数据', overflow)

    def _fetch_due(self):
        with self._lock:
            return self._conn.execute(
                'SELECT id, payload, attempts FROM outbox '
                'WHERE next_attempt <= ? ORDER BY id LIMIT ?',
                (time.time(), self.batch_size),
            ).fetchall()

    def _send(self, rows):
        import urllib.request

        data = json.dumps([json.loads(row[1]) for row in rows], ensure_ascii=False).encode('utf-8')
        request = urllib.request.Request(
            self.batch_url,
            data=data,
            headers={'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = response.read()
            if body:
                result = json.loads(body.decode('utf-8'))
                if isinstance(result, dict) and result.get('errors', 0):
                    raise RuntimeError('批量接收返回 errors=%s' % result['errors'])

    def _mark_success(self, rows):
        ids = [row[0] for row in rows]
        placeholders = ','.join('?' for _ in ids)
        with self._lock:
            self._conn.execute('DELETE FROM outbox WHERE id IN (%s)' % placeholders, ids)
            self._conn.commit()

    def _mark_failure(self, rows):
        with self._lock:
            for row_id, _, attempts in rows:
                next_attempts = attempts + 1
                delay = min(300, max(1, 2 ** min(next_attempts, 8)))
                self._conn.execute(
                    'UPDATE outbox SET attempts=?, next_attempt=? WHERE id=?',
                    (next_attempts, time.time() + delay, row_id),
                )
            self._conn.commit()

    def _run(self):
        while not self._stop.is_set():
            rows = self._fetch_due()
            if not rows:
                self._stop.wait(0.5)
                continue
            try:
                self._send(rows)
                self._mark_success(rows)
            except Exception as exc:
                self._mark_failure(rows)
                logger.warning('HTTP outbox 推送失败，将重试: %s', exc)
                self._stop.wait(1.0)

    def stats(self) -> Dict[str, int]:
        with self._lock:
            total, alerts, metrics = self._conn.execute(
                "SELECT COUNT(*), SUM(CASE kind WHEN 'alert' THEN 1 ELSE 0 END), "
                "SUM(CASE kind WHEN 'metrics' THEN 1 ELSE 0 END) FROM outbox"
            ).fetchone()
        return {'pending': total or 0, 'alerts': alerts or 0, 'metrics': metrics or 0}

    def close(self, drain_timeout: float = 5.0):
        deadline = time.monotonic() + max(0, drain_timeout)
        while time.monotonic() < deadline and self.stats()['pending']:
            time.sleep(0.1)
        self._stop.set()
        self._thread.join(timeout=max(1.0, self.timeout + 0.5))
        with self._lock:
            self._conn.commit()
            self._conn.close()


@dataclass
class Alert:
    """告警记录"""
    observer_name: str
    level: AlertLevel
    message: str
    timestamp: datetime
    details: Dict[str, Any]
    event_id: str = ""

    def __post_init__(self):
        if not self.event_id:
            self.event_id = uuid.uuid4().hex
    
    def to_json(self) -> str:
        """转换为 JSON 字符串"""
        return json.dumps({
            'event_id': self.event_id,
            'observer_name': self.observer_name,
            'level': self.level.value,
            'message': self.message,
            'timestamp': self.timestamp.isoformat(),
            'details': self.details,
        }, ensure_ascii=False)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'event_id': self.event_id,
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
        self.max_alert_file_size = max(1, int(config.get('max_alert_file_size_mb', 100))) * 1024 * 1024
        self.alert_backup_count = max(1, int(config.get('alert_backup_count', 3)))
        
        # HTTP push configuration
        self.push_enabled = config.get('push_enabled', False)
        self.push_url = config.get('push_url', '')  # e.g., "http://192.168.1.100:8000/api/ingest"
        self.push_timeout = config.get('push_timeout', 5)
        self.array_id = config.get('array_id', '')
        self._file_lock = threading.RLock()
        self._push_queue = None
        
        # Metrics recording
        self.metrics_enabled = config.get('metrics_enabled', True)
        metrics_dir = self.file_path.parent if self.file_path else Path('/var/log/observation-points')
        self.metrics_path = metrics_dir / 'metrics.jsonl'
        self.cooldown_path = Path(config.get(
            'cooldown_path', metrics_dir / 'cooldown.json'
        ))
        if self.push_enabled and self.push_url:
            outbox_path = Path(config.get('outbox_path', metrics_dir / 'outbox.sqlite3'))
            self._push_queue = PersistentPushQueue(
                self.push_url,
                self.array_id,
                outbox_path,
                timeout=self.push_timeout,
                max_pending=config.get('push_queue_max', 10000),
                batch_size=config.get('push_batch_size', 100),
            )
        
        # 告警冷却记录
        self._cooldown_cache = self._load_cooldown_cache()
        
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
        msg_hash = self._message_key(result.message)
        
        last_time = observer_cache.get(msg_hash)
        if last_time is None:
            return False
        
        elapsed = (datetime.now() - last_time).total_seconds()
        return elapsed < self.cooldown_seconds
    
    def _update_cooldown(self, result: ObserverResult):
        """更新冷却缓存"""
        if result.observer_name not in self._cooldown_cache:
            self._cooldown_cache[result.observer_name] = {}
        
        msg_hash = self._message_key(result.message)
        self._cooldown_cache[result.observer_name][msg_hash] = datetime.now()
        
        # 清理过期的冷却记录（避免内存泄漏）
        self._cleanup_cooldown_cache()
        self._save_cooldown_cache()

    @staticmethod
    def _message_key(message: str) -> str:
        return hashlib.sha256(message.encode('utf-8')).hexdigest()

    def _load_cooldown_cache(self):
        try:
            raw = json.loads(self.cooldown_path.read_text(encoding='utf-8'))
            return {
                observer: {
                    key: datetime.fromisoformat(value)
                    for key, value in entries.items()
                }
                for observer, entries in raw.items()
                if isinstance(entries, dict)
            }
        except (OSError, ValueError, TypeError):
            return {}

    def _save_cooldown_cache(self):
        try:
            self.cooldown_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.cooldown_path.with_suffix(self.cooldown_path.suffix + '.tmp')
            payload = {
                observer: {key: value.isoformat() for key, value in entries.items()}
                for observer, entries in self._cooldown_cache.items()
            }
            with open(temp_path, 'w', encoding='utf-8') as handle:
                json.dump(payload, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(str(temp_path), str(self.cooldown_path))
        except OSError as exc:
            logger.warning('告警冷却状态写入失败: %s', exc)
    
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
        
        # 文件输出
        if self.output_mode in ('file', 'both'):
            try:
                with self._file_lock:
                    self._rotate_alert_file_if_safe()
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
    
    def _push_to_web(self, alert: Alert):
        """Persist an alert for ordered background delivery."""
        if self._push_queue is not None:
            self._push_queue.enqueue('alert', alert.to_dict())

    def _rotate_alert_file_if_safe(self):
        """Bound disk use only after push confirms all older alerts were delivered."""
        if not self.file_path.exists() or self.file_path.stat().st_size < self.max_alert_file_size:
            return
        if self._push_queue is None or self._push_queue.stats().get('alerts', 0):
            logger.warning('告警文件达到上限，但仍有未投递告警，暂缓轮转')
            return
        oldest = self.file_path.with_name(self.file_path.name + '.%d' % self.alert_backup_count)
        if oldest.exists():
            oldest.unlink()
        for index in range(self.alert_backup_count - 1, 0, -1):
            source = self.file_path.with_name(self.file_path.name + '.%d' % index)
            if source.exists():
                source.rename(self.file_path.with_name(self.file_path.name + '.%d' % (index + 1)))
        self.file_path.rename(self.file_path.with_name(self.file_path.name + '.1'))
    
    def record_metrics(self, metrics: Dict[str, Any]):
        """
        记录指标数据到 metrics.jsonl 文件。
        
        Args:
            metrics: 指标字典，例如 {"cpu0": 45.2, "mem_used_mb": 3200}
        """
        self.record_metrics_batch([metrics])

    def record_metrics_batch(self, metrics_list):
        """Write and enqueue several metric samples with one file and DB transaction."""
        if not self.metrics_enabled or not metrics_list:
            return
        try:
            self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
            records = [
                {'ts': utc_now().isoformat(), 'sample_id': uuid.uuid4().hex, **metrics}
                for metrics in metrics_list
            ]
            with self._file_lock:
                if self.metrics_path.exists() and self.metrics_path.stat().st_size > self.MAX_METRICS_FILE_SIZE:
                    self._rotate_metrics()
                with open(self.metrics_path, 'a', encoding='utf-8') as f:
                    for record in records:
                        f.write(json.dumps(record, ensure_ascii=False) + '\n')
            if self._push_queue is not None:
                self._push_queue.enqueue_many('metrics', records)
        except Exception as e:
            logger.error(f"写入指标文件失败: {e}")
    
    def _push_metrics_to_web(self, record: Dict[str, Any]):
        """Persist metrics for ordered background delivery."""
        if self._push_queue is not None:
            self._push_queue.enqueue('metrics', record)

    def get_delivery_stats(self) -> Dict[str, int]:
        if self._push_queue is None:
            return {'pending': 0, 'alerts': 0, 'metrics': 0}
        return self._push_queue.stats()

    def close(self, drain_timeout: float = 5.0):
        if self._push_queue is not None:
            self._push_queue.close(drain_timeout=drain_timeout)
    
    def _rotate_metrics(self):
        """轮转指标文件"""
        try:
            rotated = self.metrics_path.with_suffix('.jsonl.1')
            if rotated.exists():
                rotated.unlink()
            self.metrics_path.rename(rotated)
            logger.info("指标文件已轮转")
        except Exception as e:
            logger.error(f"指标文件轮转失败: {e}")
