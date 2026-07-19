"""Tests for core/scheduler.py — Scheduler lifecycle."""
import pytest
from unittest.mock import patch, MagicMock
from observation_points.core.scheduler import Scheduler
from observation_points.core.base import ObserverResult, AlertLevel
from observation_points.config.loader import ConfigLoader
from datetime import datetime
import time

# DEFAULT_CONFIG observer 键中，当前没有 agent 侧实现的（后端/前端概念，agent 尚未提供
# 观察点模块）。这些键在注册表缺失属已知情况，不视为回归。
_KNOWN_UNIMPLEMENTED_OBSERVERS = {'port_traffic'}

# 此前从注册表遗漏、本次补全的系统类观察点配置键。
_PREVIOUSLY_MISSING_OBSERVERS = [
    'disk_io', 'disk_space', 'load_average', 'network_errors', 'swap_usage',
    'tcp_connections', 'zombie_processes', 'file_descriptors', 'thermal',
    'dmesg_errors', 'system_uptime',
]


class DummyObserver:
    def __init__(self, has_alert=False):
        self.name = "dummy"
        self._has_alert = has_alert
        self._enabled = True
        self._interval = 1

    def is_enabled(self):
        return self._enabled

    def get_interval(self):
        return self._interval

    def check(self, reporter=None):
        return ObserverResult(
            observer_name=self.name,
            timestamp=datetime.now(),
            has_alert=self._has_alert,
            alert_level=AlertLevel.INFO,
            message="test", details={}
        )

    def cleanup(self):
        pass


class TestScheduler:
    def test_register_observer(self):
        reporter = MagicMock()
        sched = Scheduler.__new__(Scheduler)
        sched._observers = []
        sched._running = False
        sched.reporter = reporter
        obs = DummyObserver()
        sched.register(obs)
        assert len(sched._observers) == 1

    def test_stop_calls_cleanup(self):
        sched = Scheduler.__new__(Scheduler)
        sched._observers = []
        sched._running = True
        obs = DummyObserver()
        obs.cleanup = MagicMock()
        sched._observers.append((obs, time.time()))
        sched.stop()
        obs.cleanup.assert_called_once()
        assert sched._running is False

    def test_stop_cleanup_exception_handled(self):
        """BUG-CANDIDATE: If cleanup raises, scheduler should still stop."""
        sched = Scheduler.__new__(Scheduler)
        sched._observers = []
        sched._running = True
        obs = DummyObserver()
        obs.cleanup = MagicMock(side_effect=Exception("cleanup error"))
        sched._observers.append((obs, time.time()))
        sched.stop()
        assert sched._running is False


class TestObserverRegistry:
    """回归：注册表必须覆盖所有有实现的观察点，防止配置启用后永不实例化。"""

    def _registry(self):
        sched = Scheduler.__new__(Scheduler)
        return sched._get_observer_classes()

    def test_registry_includes_previously_missing_observers(self):
        # Arrange
        registry = self._registry()
        # Act / Assert
        for key in _PREVIOUSLY_MISSING_OBSERVERS:
            assert key in registry, f"观察点 {key} 未在调度器注册表中，配置启用后将永不实例化"

    def test_registry_entries_are_instantiable_classes(self):
        # Arrange
        registry = self._registry()
        # Act / Assert — 每个注册项都能用 (name, config) 实例化
        for key in _PREVIOUSLY_MISSING_OBSERVERS:
            cls = registry[key]
            observer = cls(key, {'enabled': True, 'interval': 30})
            assert observer.name == key

    def test_every_default_config_observer_has_implementation(self):
        # Arrange
        registry_keys = set(self._registry().keys())
        default_keys = set(ConfigLoader.DEFAULT_CONFIG.get('observers', {}).keys())
        # Act
        missing = (default_keys - registry_keys) - _KNOWN_UNIMPLEMENTED_OBSERVERS
        # Assert
        assert not missing, f"DEFAULT_CONFIG 中以下 observer 键在注册表无实现: {sorted(missing)}"
