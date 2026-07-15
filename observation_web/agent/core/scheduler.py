"""
轻量级调度器

负责按配置的周期调度各观察点执行检查。
使用单线程 + select/sleep 模式，避免多线程开销。
"""

import logging
import inspect
import hashlib
import json
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import Any, Dict, List, Tuple

from .base import BaseObserver, ObserverResult, AlertLevel, utc_now
from .reporter import Reporter
from .updater import AgentUpdater
from .state_store import StateStore

logger = logging.getLogger(__name__)


class Scheduler:
    """
    轻量级调度器
    
    单线程轮询模式，按各观察点配置的间隔执行检查。
    """
    
    def __init__(self, config: Dict[str, Any], reporter: Reporter):
        """
        初始化调度器
        
        Args:
            config: 全局配置
            reporter: 告警器
        """
        self.config = config
        self.reporter = reporter
        self._running = False
        self._stopped = False
        self._observers = []  # type: List[Tuple[BaseObserver, float]]
        self._start_work_ready = True
        self._updater = AgentUpdater(config)
        global_config = config.get('global', {}) or {}
        self._next_update_check = time.monotonic() + 60
        self._update_interval_seconds = int(global_config.get('update_check_interval_seconds', 1800))
        self._max_workers = max(1, min(16, int(global_config.get('max_workers', 4))))
        self._max_memory_mb = max(1, int(global_config.get('max_memory_mb', 50)))
        self._resource_alerted = False
        self._config_fingerprint = hashlib.sha256(
            json.dumps(config, sort_keys=True, default=str).encode('utf-8')
        ).hexdigest()[:16]
        self._health_interval = max(10, int(global_config.get('health_report_interval_seconds', 30)))
        # Publish a boot heartbeat as soon as the scheduler starts. The platform
        # can then distinguish "starting" from a stopped or unreachable Agent.
        self._next_health_report = time.monotonic()
        self._executor = None
        self._update_future = None  # type: Any
        self._futures = {}  # type: Dict[str, Tuple[Future, BaseObserver, float]]
        self._health = {}  # type: Dict[str, Dict[str, Any]]
        state_path = global_config.get('state_path', '/var/lib/observation-points/state.json')
        self._state_store = StateStore(state_path)
        
        # 从配置加载并注册观察点
        self._load_observers()
    
    def _load_observers(self):
        """从配置加载观察点"""
        observers_config = self.config.get('observers', {})
        
        # 动态导入观察点模块
        observer_classes = self._get_observer_classes()
        
        for name, obs_config in observers_config.items():
            if not obs_config.get('enabled', True):
                logger.debug(f"跳过禁用的观察点: {name}")
                continue
            
            obs_class = observer_classes.get(name)
            if obs_class is None:
                logger.warning(f"未知观察点: {name}")
                continue
            
            try:
                observer = obs_class(name, obs_config)
                self.register(observer)
                if name == 'start_work':
                    self._start_work_ready = False
                logger.debug(f"注册: {name} (间隔 {observer.get_interval()}s)")
            except Exception as e:
                logger.error(f"初始化失败 {name}: {e}")

        # Load custom_monitors (from admin-deployed templates)
        from ..observers.custom_monitor import CustomMonitorObserver as CustomMonCls
        custom_monitors = self.config.get('custom_monitors', [])
        for i, mon_config in enumerate(custom_monitors):
            name = mon_config.get('name') or f'custom_monitor_{i}'
            obs_config = {
                'enabled': True,
                'interval': mon_config.get('interval', 60),
                **mon_config,
            }
            try:
                observer = CustomMonCls(name, obs_config)
                self.register(observer)
                logger.debug(f"注册自定义监控: {name} (间隔 {observer.get_interval()}s)")
            except Exception as e:
                logger.error(f"自定义监控 {name} 初始化失败: {e}")
    
    def _get_observer_classes(self) -> Dict[str, type]:
        """获取所有观察点类的映射"""
        from ..observers.error_code import ErrorCodeObserver
        from ..observers.link_status import LinkStatusObserver
        from ..observers.card_recovery import CardRecoveryObserver
        from ..observers.sensitive_info import SensitiveInfoObserver
        from ..observers.custom_command import CustomCommandObserver
        from ..observers.alarm_type import AlarmTypeObserver
        from ..observers.memory_leak import MemoryLeakObserver
        from ..observers.cpu_usage import CpuUsageObserver
        from ..observers.cmd_response import CmdResponseObserver
        from ..observers.sig_monitor import SigMonitorObserver
        from ..observers.port_fec import PortFecObserver
        from ..observers.port_speed import PortSpeedObserver
        from ..observers.pcie_bandwidth import PcieBandwidthObserver
        from ..observers.card_info import CardInfoObserver
        from ..observers.port_traffic import PortTrafficObserver
        from ..observers.controller_state import ControllerStateObserver
        from ..observers.disk_state import DiskStateObserver
        from ..observers.process_crash import ProcessCrashObserver
        from ..observers.io_timeout import IoTimeoutObserver
        from ..observers.port_error_code import PortErrorCodeObserver
        from ..observers.process_restart import ProcessRestartObserver
        from ..observers.sfp_monitor import SfpMonitorObserver
        from ..observers.abnormal_reset import AbnormalResetObserver
        from ..observers.custom_monitor import CustomMonitorObserver
        from ..observers.start_work import StartWorkObserver
        
        return {
            'error_code': ErrorCodeObserver,
            'link_status': LinkStatusObserver,
            'card_recovery': CardRecoveryObserver,
            'sensitive_info': SensitiveInfoObserver,
            'custom_commands': CustomCommandObserver,
            'alarm_type': AlarmTypeObserver,
            'memory_leak': MemoryLeakObserver,
            'cpu_usage': CpuUsageObserver,
            'cmd_response': CmdResponseObserver,
            'sig_monitor': SigMonitorObserver,
            'port_fec': PortFecObserver,
            'port_speed': PortSpeedObserver,
            'pcie_bandwidth': PcieBandwidthObserver,
            'card_info': CardInfoObserver,
            'port_traffic': PortTrafficObserver,
            'controller_state': ControllerStateObserver,
            'disk_state': DiskStateObserver,
            'process_crash': ProcessCrashObserver,
            'io_timeout': IoTimeoutObserver,
            'port_error_code': PortErrorCodeObserver,
            'process_restart': ProcessRestartObserver,
            'sfp_monitor': SfpMonitorObserver,
            'abnormal_reset': AbnormalResetObserver,
            'start_work': StartWorkObserver,
            'custom_monitor': CustomMonitorObserver,
        }
    
    def register(self, observer: BaseObserver):
        """
        注册观察点
        
        Args:
            observer: 观察点实例
        """
        # 设置下次执行时间为立即执行
        next_run = time.monotonic()
        state_store = getattr(self, '_state_store', None)
        if state_store is not None and hasattr(observer, 'restore_state'):
            observer.restore_state(state_store.get(observer.name))
        self._observers.append((observer, next_run))
        if not hasattr(self, '_health'):
            self._health = {}
        self._health[observer.name] = {
            'status': 'waiting',
            'consecutive_failures': 0,
            'runs': 0,
        }

    def _invoke_observer(self, observer: BaseObserver):
        """Invoke an observer once without masking TypeError raised by its body."""
        parameters = inspect.signature(observer.check).parameters
        if 'reporter' in parameters:
            return observer.check(reporter=self.reporter)
        return observer.check()

    def _submit_observer(self, observer: BaseObserver, now: float):
        health = self._health[observer.name]
        health['status'] = 'running'
        health['last_started_at'] = utc_now().isoformat()
        future = self._executor.submit(self._invoke_observer, observer)
        self._futures[observer.name] = (future, observer, now)

    def _collect_completed(self):
        for name, (future, observer, started) in list(self._futures.items()):
            if not future.done():
                continue
            del self._futures[name]
            health = self._health[name]
            health['last_duration_ms'] = round((time.monotonic() - started) * 1000, 2)
            health['runs'] = health.get('runs', 0) + 1
            try:
                result = future.result()
                collection_ok = bool(getattr(result, 'collection_ok', True))
                if collection_ok:
                    health['status'] = 'ok'
                    health['last_success_at'] = utc_now().isoformat()
                    health['consecutive_failures'] = 0
                    health.pop('last_error', None)
                else:
                    health['status'] = 'degraded'
                    health['consecutive_failures'] = health.get('consecutive_failures', 0) + 1
                    health['last_error'] = result.message or '采集无有效数据'

                if observer.name == 'start_work':
                    self._start_work_ready = bool(
                        collection_ok and (result.details or {}).get('started', not result.has_alert)
                    )
                if result.has_alert:
                    self.reporter.report(result)
            except Exception as exc:
                health['status'] = 'error'
                health['consecutive_failures'] = health.get('consecutive_failures', 0) + 1
                health['last_error'] = str(exc)[:300]
                health['last_failure_at'] = utc_now().isoformat()
                if observer.name == 'start_work':
                    self._start_work_ready = False
                logger.exception("[%s] 执行失败", observer.name)
            finally:
                self._state_store.set(observer.name, observer.export_state())

    def _advance_schedule(self, scheduled: float, interval: int, now: float) -> float:
        """Advance one fixed-rate slot and skip missed slots without catch-up storms."""
        next_run = scheduled + max(1, interval)
        if next_run <= now:
            next_run = now + max(1, interval)
        return next_run

    def _report_health(self):
        memory_mb = self._read_memory_mb()
        self.reporter.record_metrics({
            'observer': '__agent_health__',
            'agent_health': self._health,
            'running_observers': len(self._futures),
            'configured_observers': len(self._observers),
            'start_work_ready': self._start_work_ready,
            'delivery': self.reporter.get_delivery_stats(),
            'memory_mb': memory_mb,
            'memory_limit_mb': self._max_memory_mb,
            'config_fingerprint': self._config_fingerprint,
        })
        over_limit = memory_mb is not None and memory_mb > self._max_memory_mb
        if over_limit and not self._resource_alerted:
            self.reporter.report(ObserverResult(
                observer_name='__agent_health__',
                has_alert=True,
                alert_level=AlertLevel.WARNING,
                message='Agent 内存超过配置上限: %.1fMB > %dMB' % (memory_mb, self._max_memory_mb),
                details={'memory_mb': memory_mb, 'limit_mb': self._max_memory_mb},
            ))
        elif self._resource_alerted and not over_limit:
            self.reporter.report(ObserverResult(
                observer_name='__agent_health__',
                has_alert=True,
                alert_level=AlertLevel.INFO,
                message='Agent 内存恢复到配置上限以内',
                details={'memory_mb': memory_mb, 'limit_mb': self._max_memory_mb, 'recovered': True},
            ))
        self._resource_alerted = over_limit

    @staticmethod
    def _read_memory_mb():
        try:
            with open('/proc/self/status', 'r', encoding='utf-8') as handle:
                for line in handle:
                    if line.startswith('VmRSS:'):
                        return round(float(line.split()[1]) / 1024.0, 2)
        except (OSError, ValueError, IndexError):
            return None
        return None
    
    def start(self):
        """启动调度器"""
        self._running = True
        logger.info(f"调度器启动 ({len(self._observers)} 个观察点)")
        
        self._executor = ThreadPoolExecutor(max_workers=self._max_workers, thread_name_prefix='observer')
        while self._running:
            now = time.monotonic()
            self._collect_completed()

            if self._update_future is not None and self._update_future.done():
                try:
                    self._update_future.result()
                except Exception:
                    logger.exception("Agent 更新检查失败")
                self._update_future = None
            if now >= self._next_update_check and self._update_future is None:
                self._update_future = self._executor.submit(self._updater.check_and_apply_update)
                self._next_update_check = now + max(300, self._update_interval_seconds)

            start_work_pending = 'start_work' in self._futures
            for index, (observer, next_run) in enumerate(self._observers):
                if not observer.is_enabled() or observer.name in self._futures or now < next_run:
                    continue
                if observer.name != 'start_work' and (start_work_pending or not self._start_work_ready):
                    continue
                self._submit_observer(observer, now)
                self._observers[index] = (
                    observer,
                    self._advance_schedule(next_run, observer.get_interval(), now),
                )
                if observer.name == 'start_work':
                    start_work_pending = True

            if now >= self._next_health_report:
                self._report_health()
                self._next_health_report = now + self._health_interval
            self._state_store.flush()
            time.sleep(0.1)
    
    def stop(self):
        """停止调度器"""
        if getattr(self, '_stopped', False):
            return
        self._stopped = True
        self._running = False
        logger.info("调度器停止中...")
        state_store = getattr(self, '_state_store', None)
        if state_store is not None:
            state_store.flush(force=True)
        
        # 清理所有观察点
        for observer, _ in self._observers:
            try:
                observer.cleanup()
            except Exception as e:
                logger.error(f"[{observer.name}] 清理失败: {e}")

        executor = getattr(self, '_executor', None)
        if executor is not None:
            pending = [entry[0] for entry in getattr(self, '_futures', {}).values()]
            if pending:
                wait(pending, timeout=10)
                self._collect_completed()
            executor.shutdown(wait=False)
        
        logger.info("调度器已停止")
