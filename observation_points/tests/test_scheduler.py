"""Tests for core/scheduler.py — Scheduler lifecycle."""
import pytest
from unittest.mock import patch, MagicMock
from observation_points.core.scheduler import Scheduler
from observation_points.core.base import ObserverResult, AlertLevel
from datetime import datetime
import time


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
