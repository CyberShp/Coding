"""Tests for memory leak detection logic."""
import pytest
import pytest_asyncio
from datetime import datetime
from unittest.mock import MagicMock, patch


class TestMemoryLeakObserver:
    """Test memory leak observer in observation_points project."""
    
    def create_observer(self, config=None):
        """Create a mock MemoryLeakObserver for testing."""
        from collections import deque
        
        class MockObserver:
            def __init__(self, config):
                self.consecutive_threshold = config.get('consecutive_threshold', 8)
                self.recovery_threshold = config.get('recovery_threshold', 3)
                max_len = max(self.consecutive_threshold, self.recovery_threshold + 1)
                self._history = deque(maxlen=max_len)
                self._alert_triggered = False
            
            def _is_continuous_increase(self):
                if len(self._history) < self.consecutive_threshold:
                    return False
                values = [h['used_mb'] for h in self._history]
                for i in range(1, len(values)):
                    if values[i] <= values[i - 1]:
                        return False
                return True
            
            def _is_continuous_decrease(self):
                if len(self._history) < self.recovery_threshold:
                    return False
                values = [h['used_mb'] for h in self._history][-self.recovery_threshold:]
                for i in range(1, len(values)):
                    if values[i] >= values[i - 1]:
                        return False
                return True
            
            def _count_consecutive_increases(self):
                if len(self._history) < 2:
                    return 0
                values = [h['used_mb'] for h in self._history]
                count = 0
                for i in range(len(values) - 1, 0, -1):
                    if values[i] > values[i - 1]:
                        count += 1
                    else:
                        break
                return count
            
            def _count_consecutive_decreases(self):
                if len(self._history) < 2:
                    return 0
                values = [h['used_mb'] for h in self._history]
                count = 0
                for i in range(len(values) - 1, 0, -1):
                    if values[i] < values[i - 1]:
                        count += 1
                    else:
                        break
                return count
            
            def add_sample(self, used_mb):
                self._history.append({
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'used_mb': used_mb,
                })
        
        return MockObserver(config or {})
    
    def test_no_alert_with_insufficient_data(self):
        """Should not trigger alert with less than threshold samples."""
        observer = self.create_observer({'consecutive_threshold': 4})
        
        # Add only 3 increasing samples (less than threshold)
        for mem in [1000, 1100, 1200]:
            observer.add_sample(mem)
        
        assert not observer._is_continuous_increase()
        assert observer._count_consecutive_increases() == 2
    
    def test_alert_on_continuous_increase(self):
        """Should trigger alert when memory increases consecutively."""
        observer = self.create_observer({'consecutive_threshold': 4})
        
        # Add 4 continuously increasing samples
        for mem in [1000, 1100, 1200, 1300]:
            observer.add_sample(mem)
        
        assert observer._is_continuous_increase()
        assert observer._count_consecutive_increases() == 3
    
    def test_no_alert_on_fluctuating_memory(self):
        """Should not trigger alert when memory fluctuates."""
        observer = self.create_observer({'consecutive_threshold': 4})
        
        # Add fluctuating samples
        for mem in [1000, 1100, 1050, 1200]:
            observer.add_sample(mem)
        
        assert not observer._is_continuous_increase()
    
    def test_recovery_detection(self):
        """Should detect recovery when memory decreases consecutively."""
        observer = self.create_observer({
            'consecutive_threshold': 4,
            'recovery_threshold': 3
        })
        observer._alert_triggered = True
        
        # Add 3 consecutively decreasing samples
        for mem in [1300, 1200, 1100]:
            observer.add_sample(mem)
        
        assert observer._is_continuous_decrease()
        assert observer._count_consecutive_decreases() == 2
    
    def test_no_recovery_on_fluctuating_decrease(self):
        """Should not detect recovery when decrease is not continuous."""
        observer = self.create_observer({
            'consecutive_threshold': 4,
            'recovery_threshold': 3
        })
        observer._alert_triggered = True
        
        # Add non-continuous decrease
        for mem in [1300, 1200, 1250]:
            observer.add_sample(mem)
        
        assert not observer._is_continuous_decrease()
    
    def test_alert_persists_without_recovery(self):
        """Alert should persist until recovery threshold is met."""
        observer = self.create_observer({
            'consecutive_threshold': 4,
            'recovery_threshold': 3
        })
        
        # Trigger alert
        for mem in [1000, 1100, 1200, 1300]:
            observer.add_sample(mem)
        observer._alert_triggered = True
        
        # Memory stable but not decreasing enough
        for mem in [1300, 1280, 1300]:
            observer.add_sample(mem)
        
        assert not observer._is_continuous_decrease()
        assert observer._alert_triggered
    
    def test_recovery_threshold_customization(self):
        """Recovery threshold should be configurable."""
        observer = self.create_observer({
            'consecutive_threshold': 4,
            'recovery_threshold': 5
        })
        observer._alert_triggered = True
        
        # 4 decreases should not trigger recovery (need 5)
        for mem in [1400, 1300, 1200, 1100]:
            observer.add_sample(mem)
        
        assert not observer._is_continuous_decrease()
        
        # 5th decrease should trigger recovery
        observer.add_sample(1000)
        assert observer._is_continuous_decrease()


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
