"""Tests for memory leak detection logic.

These tests exercise the REAL ``MemoryLeakObserver`` from the agent package
(agent/observers/memory_leak.py) — not a re-implemented copy. Samples are fed
into the observer's ``_history`` deque exactly the way its own ``check()`` does,
then the real detection methods are asserted.
"""
import sys
from datetime import datetime
from pathlib import Path

import pytest
import pytest_asyncio
from unittest.mock import MagicMock, patch

# Ensure the agent package (sibling of backend/) is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.observers.memory_leak import MemoryLeakObserver
from agent.core.base import AlertLevel


def _add_sample(observer, used_mb):
    """Append a memory sample the same way the real ``check()`` records it."""
    observer._history.append({
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'used_mb': used_mb,
    })


class TestMemoryLeakObserver:
    """Test the real MemoryLeakObserver detection logic."""

    def _make_observer(self, config=None):
        return MemoryLeakObserver("memory_leak", config or {})

    def test_no_alert_with_insufficient_data(self):
        """Should not trigger alert with less than threshold samples."""
        observer = self._make_observer({'consecutive_threshold': 4})

        # Add only 3 increasing samples (less than threshold)
        for mem in [1000, 1100, 1200]:
            _add_sample(observer, mem)

        assert not observer._is_continuous_increase()
        assert observer._count_consecutive_increases() == 2

    def test_alert_on_continuous_increase(self):
        """Should trigger alert when memory increases consecutively."""
        observer = self._make_observer({'consecutive_threshold': 4})

        # Add 4 continuously increasing samples
        for mem in [1000, 1100, 1200, 1300]:
            _add_sample(observer, mem)

        assert observer._is_continuous_increase()
        assert observer._count_consecutive_increases() == 3

    def test_no_alert_on_fluctuating_memory(self):
        """Should not trigger alert when memory fluctuates."""
        observer = self._make_observer({'consecutive_threshold': 4})

        # Add fluctuating samples
        for mem in [1000, 1100, 1050, 1200]:
            _add_sample(observer, mem)

        assert not observer._is_continuous_increase()

    def test_recovery_detection(self):
        """Should detect recovery when memory decreases consecutively."""
        observer = self._make_observer({
            'consecutive_threshold': 4,
            'recovery_threshold': 3
        })
        observer._alert_triggered = True

        # Add 3 consecutively decreasing samples
        for mem in [1300, 1200, 1100]:
            _add_sample(observer, mem)

        assert observer._is_continuous_decrease()
        assert observer._count_consecutive_decreases() == 2

    def test_no_recovery_on_fluctuating_decrease(self):
        """Should not detect recovery when decrease is not continuous."""
        observer = self._make_observer({
            'consecutive_threshold': 4,
            'recovery_threshold': 3
        })
        observer._alert_triggered = True

        # Add non-continuous decrease
        for mem in [1300, 1200, 1250]:
            _add_sample(observer, mem)

        assert not observer._is_continuous_decrease()

    def test_alert_persists_without_recovery(self):
        """Alert should persist until recovery threshold is met."""
        observer = self._make_observer({
            'consecutive_threshold': 4,
            'recovery_threshold': 3
        })

        # Trigger alert
        for mem in [1000, 1100, 1200, 1300]:
            _add_sample(observer, mem)
        observer._alert_triggered = True

        # Memory stable but not decreasing enough
        for mem in [1300, 1280, 1300]:
            _add_sample(observer, mem)

        assert not observer._is_continuous_decrease()
        assert observer._alert_triggered

    def test_recovery_threshold_customization(self):
        """Recovery threshold should be configurable."""
        observer = self._make_observer({
            'consecutive_threshold': 4,
            'recovery_threshold': 5
        })
        observer._alert_triggered = True

        # 4 decreases should not trigger recovery (need 5)
        for mem in [1400, 1300, 1200, 1100]:
            _add_sample(observer, mem)

        assert not observer._is_continuous_decrease()

        # 5th decrease should trigger recovery
        _add_sample(observer, 1000)
        assert observer._is_continuous_decrease()

    def test_check_raises_error_alert_on_continuous_increase(self):
        """End-to-end: check() emits an ERROR sticky alert on a leak and
        flips the sticky _alert_triggered flag (real check() code path)."""
        observer = self._make_observer({'consecutive_threshold': 4})

        with patch.object(observer, "_get_memory_total", return_value=16000):
            values = [1000, 1100, 1200, 1300]
            with patch.object(observer, "_get_memory_used", side_effect=values):
                results = [observer.check() for _ in values]

        last = results[-1]
        assert last.has_alert is True
        assert last.alert_level == AlertLevel.ERROR
        assert last.sticky is True
        assert observer._alert_triggered is True
        assert last.details['consecutive_increases'] == 3

    def test_check_no_alert_when_memory_unavailable(self):
        """check() must not alert when `free -m` cannot be read."""
        observer = self._make_observer({'consecutive_threshold': 4})

        with patch.object(observer, "_get_memory_used", return_value=None):
            result = observer.check()

        assert result.has_alert is False
        assert observer._alert_triggered is False


class TestMemoryLeakAlertWebBackend:
    """Test memory leak alert handling in web backend."""

    @pytest.mark.asyncio
    async def test_memory_leak_alert_creates_active_issue(self, app_client_with_db):
        """Memory leak alert should create an active issue."""
        from tests.conftest import create_test_array, inject_test_alert

        client, db = app_client_with_db
        await create_test_array(db, "test-array-1", host="192.168.1.1")
        await inject_test_alert(
            db, "test-array-1", "memory_leak", "error", "Memory leak detected",
            {"current_used_mb": 8000, "consecutive_increases": 8},
        )
        await db.commit()

        status_response = await client.get("/api/arrays/test-array-1/status")
        assert status_response.status_code == 200
        data = status_response.json()
        issues = data.get("active_issues", [])
        assert any(i.get("observer") == "memory_leak" for i in issues)

    @pytest.mark.asyncio
    async def test_memory_leak_recovery_removes_active_issue(self, app_client_with_db):
        """Recovery alert should remove memory leak from active issues."""
        from tests.conftest import create_test_array, inject_test_alert

        client, db = app_client_with_db
        await create_test_array(db, "test-array-2", host="192.168.1.2")
        await inject_test_alert(
            db, "test-array-2", "memory_leak", "error", "Memory leak detected",
            {"current_used_mb": 8000},
        )
        await inject_test_alert(
            db, "test-array-2", "memory_leak", "info", "Memory leak recovered",
            {"current_used_mb": 4000, "recovered": True},
        )
        await db.commit()

        status_response = await client.get("/api/arrays/test-array-2/status")
        assert status_response.status_code == 200
        data = status_response.json()
        issues = data.get("active_issues", [])
        assert not any(i.get("observer") == "memory_leak" for i in issues)
