"""
轻量级调度器

负责按配置的周期调度各观察点执行检查。
使用单线程 + select/sleep 模式，避免多线程开销。
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Tuple

from .base import BaseObserver, ObserverResult, AlertLevel
from .reporter import Reporter
from .updater import AgentUpdater

logger = logging.getLogger(__name__)


_FAILURE_LOG_THRESHOLD = 3    # escalate to local ERROR log after this many failures
_ALERT_REPORT_THRESHOLD = 10  # report sticky alert to backend every N failures
_BACKOFF_MAX_SECONDS = 900    # absolute backoff cap: 15 minutes


class Scheduler:
    """
    轻量级调度器

    单线程轮询模式，按各观察点配置的间隔执行检查。
    失败的观察点会应用指数退避，连续失败超过阈值时升级日志级别。
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
        self._observers = []  # type: List[Tuple[BaseObserver, float]]
        self._start_work_ready = True
        self._updater = AgentUpdater(config)
        self._next_update_check = time.time() + 60
        self._update_interval_seconds = int((config.get('global', {}) or {}).get('update_check_interval_seconds', 1800))
        # Per-observer consecutive failure counts for backoff tracking
        self._observer_failures: Dict[str, int] = {}

        # 从配置加载并注册观察点
        self._load_observers()

    def _record_failure(self, name: str, exc: Exception) -> None:
        """Record an observer failure.

        Logging: escalates to ERROR at _FAILURE_LOG_THRESHOLD (3) consecutive failures.
        Backend alert: emits a sticky ObserverResult every _ALERT_REPORT_THRESHOLD (10)
        consecutive failures so the backend surfaces sustained outages without flooding
        on transient blips.
        """
        count = self._observer_failures.get(name, 0) + 1
        self._observer_failures[name] = count
        if count >= _FAILURE_LOG_THRESHOLD:
            logger.error("[%s] 连续失败 %d 次: %s", name, count, exc)
        else:
            logger.warning("[%s] 执行失败: %s", name, exc)
        # Only report to backend at multiples of the alert threshold (10, 20, 30 …)
        if count >= _ALERT_REPORT_THRESHOLD and count % _ALERT_REPORT_THRESHOLD == 0:
            synthetic = ObserverResult(
                observer_name=name,
                has_alert=True,
                alert_level=AlertLevel.ERROR,
                message=f"观察点 {name} 连续失败 {count} 次: {exc}",
                details={"consecutive_failures": count, "last_error": str(exc)},
                sticky=True,
            )
            self.reporter.report(synthetic)

    def _backoff_delay(self, name: str, base_interval: float) -> float:
        """Return absolute backoff delay in seconds, capped at _BACKOFF_MAX_SECONDS."""
        count = self._observer_failures.get(name, 0)
        return min(base_interval * (2 ** count), _BACKOFF_MAX_SECONDS)

    def _record_success(self, name: str) -> None:
        """Reset failure counter; log recovery if it had escalated."""
        prev = self._observer_failures.pop(name, 0)
        if prev >= _FAILURE_LOG_THRESHOLD:
            logger.info("[%s] 恢复正常运行（此前连续失败 %d 次）", name, prev)
    
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
        from ..observers.port_counters import PortCountersObserver
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
            'port_counters': PortCountersObserver,
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
        next_run = time.time()
        self._observers.append((observer, next_run))
    
    def start(self):
        """启动调度器"""
        self._running = True
        logger.info(f"调度器启动 ({len(self._observers)} 个观察点)")
        
        # 主循环
        while self._running:
            now = time.time()
            next_wakeup = now + 60  # 默认最长等待60秒

            if now >= self._next_update_check:
                self._updater.check_and_apply_update()
                self._next_update_check = now + max(300, self._update_interval_seconds)

            # Execute start_work first (if configured) to decide whether to skip other observers.
            for i, (observer, next_run) in enumerate(self._observers):
                if observer.name != 'start_work' or not observer.is_enabled():
                    continue
                if now < next_run:
                    continue
                try:
                    result = observer.check()
                    self._start_work_ready = bool((result.details or {}).get('started', not result.has_alert))
                    if result.has_alert:
                        self.reporter.report(result)
                    self._record_success(observer.name)
                except Exception as e:
                    self._start_work_ready = False
                    self._record_failure(observer.name, e)
                    next_run = now + self._backoff_delay(observer.name, observer.get_interval())
                    self._observers[i] = (observer, next_run)
                    break
                next_run = now + observer.get_interval()
                self._observers[i] = (observer, next_run)
                break

            for i, (observer, next_run) in enumerate(self._observers):
                if not observer.is_enabled():
                    continue
                if observer.name == 'start_work':
                    if next_run < next_wakeup:
                        next_wakeup = next_run
                    continue

                if now >= next_run:
                    if not self._start_work_ready:
                        # Array is not started, skip other observers in this cycle.
                        next_run = now + observer.get_interval()
                        self._observers[i] = (observer, next_run)
                        if next_run < next_wakeup:
                            next_wakeup = next_run
                        continue
                    # 执行检查
                    failed = False
                    try:
                        try:
                            result = observer.check(reporter=self.reporter)
                        except TypeError:
                            result = observer.check()

                        if result.has_alert:
                            self.reporter.report(result)
                        self._record_success(observer.name)

                    except Exception as e:
                        self._record_failure(observer.name, e)
                        next_run = now + self._backoff_delay(observer.name, observer.get_interval())
                        self._observers[i] = (observer, next_run)
                        failed = True

                    if not failed:
                        # 更新下次执行时间
                        next_run = now + observer.get_interval()
                        self._observers[i] = (observer, next_run)

                # 计算最近的下次唤醒时间
                if next_run < next_wakeup:
                    next_wakeup = next_run
            
            # 休眠到下次执行时间
            sleep_time = max(0.1, next_wakeup - time.time())
            time.sleep(sleep_time)
    
    def stop(self):
        """停止调度器"""
        self._running = False
        logger.info("调度器停止中...")
        
        # 清理所有观察点
        for observer, _ in self._observers:
            try:
                observer.cleanup()
            except Exception as e:
                logger.error(f"[{observer.name}] 清理失败: {e}")
        
        logger.info("调度器已停止")
