"""
轻量级调度器

负责按配置的周期调度各观察点执行检查。
使用单线程 + select/sleep 模式，避免多线程开销。
"""

import logging
import time
from datetime import datetime
from typing import Any

from .base import BaseObserver
from .reporter import Reporter

logger = logging.getLogger(__name__)


class Scheduler:
    """
    轻量级调度器
    
    单线程轮询模式，按各观察点配置的间隔执行检查。
    """
    
    def __init__(self, config: dict[str, Any], reporter: Reporter):
        """
        初始化调度器
        
        Args:
            config: 全局配置
            reporter: 告警器
        """
        self.config = config
        self.reporter = reporter
        self._running = False
        self._observers: list[tuple[BaseObserver, float]] = []  # (观察点, 下次执行时间)
        
        # 从配置加载并注册观察点
        self._load_observers()
    
    def _load_observers(self):
        """从配置加载观察点"""
        observers_config = self.config.get('observers', {})
        
        # 动态导入观察点模块
        observer_classes = self._get_observer_classes()
        
        for name, obs_config in observers_config.items():
            if not obs_config.get('enabled', True):
                logger.info(f"观察点 {name} 已禁用，跳过")
                continue
            
            obs_class = observer_classes.get(name)
            if obs_class is None:
                logger.warning(f"未找到观察点类: {name}")
                continue
            
            try:
                observer = obs_class(name, obs_config)
                self.register(observer)
                logger.info(f"观察点 {name} 已注册，间隔: {observer.get_interval()}s")
            except Exception as e:
                logger.error(f"初始化观察点 {name} 失败: {e}")
    
    def _get_observer_classes(self) -> dict[str, type]:
        """获取所有观察点类的映射"""
        from ..observers.error_code import ErrorCodeObserver
        from ..observers.link_status import LinkStatusObserver
        from ..observers.card_recovery import CardRecoveryObserver
        from ..observers.subhealth import SubhealthObserver
        from ..observers.sensitive_info import SensitiveInfoObserver
        from ..observers.performance import PerformanceObserver
        from ..observers.custom_command import CustomCommandObserver
        
        return {
            'error_code': ErrorCodeObserver,
            'link_status': LinkStatusObserver,
            'card_recovery': CardRecoveryObserver,
            'subhealth': SubhealthObserver,
            'sensitive_info': SensitiveInfoObserver,
            'performance': PerformanceObserver,
            'custom_commands': CustomCommandObserver,
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
        logger.info(f"调度器启动，已注册 {len(self._observers)} 个观察点")
        
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
                        result = observer.check()
                        
                        if result.has_alert:
                            self.reporter.report(result)
                        
                    except Exception as e:
                        logger.error(f"观察点 {observer.name} 执行失败: {e}")
                    
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
        logger.info("调度器正在停止...")
        
        # 清理所有观察点
        for observer, _ in self._observers:
            try:
                observer.cleanup()
            except Exception as e:
                logger.error(f"清理观察点 {observer.name} 失败: {e}")
        
        logger.info("调度器已停止")
