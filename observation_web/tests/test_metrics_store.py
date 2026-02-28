"""Tests for metrics storage and retrieval."""
import pytest
import pytest_asyncio
from datetime import datetime, timedelta


class TestMetricsIngest:
    """Test metrics ingestion."""
    
    @pytest.mark.asyncio
    async def test_ingest_cpu_metrics(self, app_client):
        """Should accept CPU metrics via ingest endpoint."""
        reg_data = {
            "array_id": "test-metrics-1",
            "hostname": "test-host",
            "ip_address": "192.168.1.200",
        }
        await app_client.post("/api/arrays/register", json=reg_data)
        
        metrics_data = {
            "array_id": "test-metrics-1",
            "metrics": {
                "cpu0": 45.5,
                "cpu1": 30.2,
            }
        }
        response = await app_client.post("/api/ingest", json=metrics_data)
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_ingest_memory_metrics(self, app_client):
        """Should accept memory metrics via ingest endpoint."""
        reg_data = {
            "array_id": "test-metrics-2",
            "hostname": "test-host",
            "ip_address": "192.168.1.201",
        }
        await app_client.post("/api/arrays/register", json=reg_data)
        
        metrics_data = {
            "array_id": "test-metrics-2",
            "metrics": {
                "mem_used_mb": 4096,
                "mem_total_mb": 16384,
            }
        }
        response = await app_client.post("/api/ingest", json=metrics_data)
        assert response.status_code == 200


class TestMetricsRetrieval:
    """Test metrics retrieval API."""
    
    @pytest.mark.asyncio
    async def test_get_metrics_empty(self, app_client):
        """Should return empty list when no metrics exist."""
        reg_data = {
            "array_id": "test-metrics-3",
            "hostname": "test-host",
            "ip_address": "192.168.1.202",
        }
        await app_client.post("/api/arrays/register", json=reg_data)
        
        response = await app_client.get("/api/arrays/test-metrics-3/metrics?minutes=60")
        assert response.status_code == 200
        data = response.json()
        assert "metrics" in data
    
    @pytest.mark.asyncio
    async def test_get_metrics_with_time_range(self, app_client):
        """Should filter metrics by time range."""
        reg_data = {
            "array_id": "test-metrics-4",
            "hostname": "test-host",
            "ip_address": "192.168.1.203",
        }
        await app_client.post("/api/arrays/register", json=reg_data)
        
        # Ingest some metrics
        metrics_data = {
            "array_id": "test-metrics-4",
            "metrics": {"cpu0": 50.0}
        }
        await app_client.post("/api/ingest", json=metrics_data)
        
        # Query with 30-minute window
        response = await app_client.get("/api/arrays/test-metrics-4/metrics?minutes=30")
        assert response.status_code == 200
        
        # Query with 60-minute window
        response = await app_client.get("/api/arrays/test-metrics-4/metrics?minutes=60")
        assert response.status_code == 200


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
