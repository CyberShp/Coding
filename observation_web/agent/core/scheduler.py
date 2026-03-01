"""
轻量级调度器

负责按配置的周期调度各观察点执行检查。
使用单线程 + select/sleep 模式，避免多线程开销。
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Tuple

from .base import BaseObserver
from .reporter import Reporter

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
        self._observers = []  # type: List[Tuple[BaseObserver, float]]
        
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
                logger.debug(f"注册: {name} (间隔 {observer.get_interval()}s)")
            except Exception as e:
                logger.error(f"初始化失败 {name}: {e}")
    
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
            
            for i, (observer, next_run) in enumerate(self._observers):
                if not observer.is_enabled():
                    continue
                
                if now >= next_run:
                    # 执行检查
                    try:
                        # Pass reporter to observers that support metrics recording
                        try:
                            result = observer.check(reporter=self.reporter)
                        except TypeError:
                            # Fallback for observers that don't accept reporter
                            result = observer.check()
                        
                        if result.has_alert:
                            self.reporter.report(result)
                        
                    except Exception as e:
                        logger.error(f"[{observer.name}] 执行失败: {e}")
                    
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
