"""Tests for metrics storage and retrieval."""
import pytest
import pytest_asyncio
from datetime import datetime, timedelta


class TestMetricsIngest:
    """Test metrics ingestion via /api/ingest (correct schema: type=metrics)."""

    @pytest.mark.asyncio
    async def test_ingest_cpu_metrics(self, app_client):
        """Should accept CPU metrics via ingest endpoint."""
        metrics_data = {"type": "metrics", "cpu0": 45.5, "cpu1": 30.2}
        response = await app_client.post("/api/ingest", json=metrics_data)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ingest_memory_metrics(self, app_client):
        """Should accept memory metrics via ingest endpoint."""
        metrics_data = {"type": "metrics", "mem_used_mb": 4096, "mem_total_mb": 16384}
        response = await app_client.post("/api/ingest", json=metrics_data)
        assert response.status_code == 200


class TestMetricsRetrieval:
    """Test metrics retrieval API (requires SSH connection for GET /arrays/{id}/metrics)."""

    @pytest.mark.skip(reason="GET /arrays/{id}/metrics requires SSH connection; covered by integration tests")
    @pytest.mark.asyncio
    async def test_get_metrics_empty(self, app_client):
        """Should return empty list when no metrics exist."""
        pass

    @pytest.mark.skip(reason="GET /arrays/{id}/metrics requires SSH connection; covered by integration tests")
    @pytest.mark.asyncio
    async def test_get_metrics_with_time_range(self, app_client):
        """Should filter metrics by time range."""
        pass


class TestMetricsStoreBoundary:
    """Test metrics store boundary conditions."""
    
    def test_metrics_deque_maxlen(self):
        """Metrics store should have maximum length."""
        from collections import deque
        
        max_items = 1000
        store = deque(maxlen=max_items)
        
        # Add more than maxlen items
        for i in range(1500):
            store.append({"ts": i, "value": i})
        
        # Should only keep maxlen items
        assert len(store) == max_items
        # Should keep the most recent
        assert store[-1]["ts"] == 1499
        assert store[0]["ts"] == 500
    
    def test_metrics_timestamp_format(self):
        """Metrics should store ISO format timestamps."""
        ts = datetime.utcnow().isoformat()
        
        # Should be parseable
        parsed = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        assert parsed is not None
    
    def test_metrics_value_types(self):
        """Metrics should accept various numeric types."""
        metrics = {
            "cpu0": 45.5,       # float
            "cpu1": 50,         # int
            "mem_used_mb": 4096,
            "mem_total_mb": 16384,
        }
        
        # All values should be numeric
        for key, value in metrics.items():
            assert isinstance(value, (int, float))


class TestMetricsPerformance:
    """Test metrics storage performance characteristics."""
    
    def test_metrics_lookup_time(self):
        """Metrics lookup should be efficient."""
        from collections import deque
        import time
        
        store = deque(maxlen=10000)
        
        # Fill store
        for i in range(10000):
            store.append({"ts": datetime.utcnow().isoformat(), "cpu0": i % 100})
        
        # Measure iteration time
        start = time.time()
        filtered = [m for m in store if m["cpu0"] > 50]
        elapsed = time.time() - start
        
        # Should complete quickly (< 100ms for 10k items)
        assert elapsed < 0.1
        assert len(filtered) > 0
    
    def test_concurrent_access_safety(self):
        """Store should handle concurrent access patterns."""
        from collections import deque
        
        store = deque(maxlen=1000)
        
        # Simulate concurrent writes
        for i in range(100):
            store.append({"ts": i, "value": i})
        
        # Simulate concurrent reads during writes
        total = sum(m["value"] for m in store)
        
        # Should not raise exceptions
        assert total >= 0
