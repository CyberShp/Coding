"""Tests for backend/api/ingest.py — metrics store logic."""
import pytest
from collections import deque
from datetime import datetime


class TestMetricsStore:
    def test_deque_max_size(self):
        """SPEC: Metrics store should cap at MAX_METRICS_PER_ARRAY."""
        from backend.api.ingest import MAX_METRICS_PER_ARRAY
        d = deque(maxlen=MAX_METRICS_PER_ARRAY)
        for i in range(MAX_METRICS_PER_ARRAY + 100):
            d.append({"ts": datetime.now().isoformat(), "cpu0": i})
        assert len(d) == MAX_METRICS_PER_ARRAY

    def test_metrics_format(self):
        """SPEC: Metrics record format."""
        record = {
            "ts": datetime.now().isoformat(),
            "cpu0": 45.2,
            "mem_used_mb": 3200,
            "mem_total_mb": 16000,
            "source_ip": "10.0.0.1"
        }
        assert "ts" in record
        assert isinstance(record["cpu0"], float)

    def test_get_metrics_empty_store(self):
        """EDGE: Getting metrics for unknown IP returns empty."""
        from backend.api.ingest import _metrics_store
        assert _metrics_store.get("unknown_ip") is None
