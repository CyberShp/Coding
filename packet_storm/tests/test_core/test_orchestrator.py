"""Tests for BatchOrchestrator."""

import pytest

from packet_storm.core.orchestrator import (
    BatchOrchestrator, BatchResult, ScenarioResult, ScenarioStatus,
)


class TestScenarioResult:
    """Test suite for ScenarioResult."""

    def test_default_values(self):
        """ScenarioResult has correct defaults."""
        result = ScenarioResult(scenario_id="s1", name="Test")
        assert result.status == ScenarioStatus.PENDING
        assert result.packets_sent == 0
        assert result.duration == 0.0

    def test_success_rate(self):
        """Success rate calculation."""
        result = ScenarioResult(
            scenario_id="s1", name="Test",
            packets_sent=90, packets_failed=10,
        )
        assert result.success_rate == 0.9

    def test_to_dict(self):
        """Serialization to dict."""
        result = ScenarioResult(
            scenario_id="s1", name="Test",
            status=ScenarioStatus.COMPLETED,
            packets_sent=100,
        )
        d = result.to_dict()
        assert d["scenario_id"] == "s1"
        assert d["status"] == "completed"
        assert d["packets_sent"] == 100


class TestBatchResult:
    """Test suite for BatchResult."""

    def test_empty_batch(self):
        """Empty batch result."""
        result = BatchResult(batch_id="b1")
        assert result.total_scenarios == 0
        assert result.completed_count == 0
        assert result.all_passed

    def test_aggregate_stats(self):
        """Aggregate statistics from scenarios."""
        result = BatchResult(batch_id="b1")
        result.scenarios = [
            ScenarioResult("s1", "A", ScenarioStatus.COMPLETED,
                           packets_sent=100, bytes_sent=1000),
            ScenarioResult("s2", "B", ScenarioStatus.COMPLETED,
                           packets_sent=200, bytes_sent=2000),
            ScenarioResult("s3", "C", ScenarioStatus.FAILED,
                           packets_sent=50, bytes_sent=500),
        ]
        assert result.total_scenarios == 3
        assert result.completed_count == 2
        assert result.failed_count == 1
        assert result.total_packets == 350
        assert result.total_bytes == 3500
        assert not result.all_passed

    def test_export_json(self, tmp_path):
        """Export batch result to JSON."""
        result = BatchResult(batch_id="b1")
        result.scenarios = [
            ScenarioResult("s1", "Test", ScenarioStatus.COMPLETED),
        ]
        path = str(tmp_path / "result.json")
        result.export_json(path)

        import json
        with open(path) as f:
            data = json.load(f)
        assert data["batch_id"] == "b1"
        assert len(data["scenarios"]) == 1


class TestBatchOrchestrator:
    """Test suite for BatchOrchestrator."""

    def test_load_list_format(self, tmp_path):
        """Load batch file in list format."""
        import json
        batch = [
            {"name": "Test 1"},
            {"name": "Test 2"},
        ]
        path = str(tmp_path / "batch.json")
        with open(path, "w") as f:
            json.dump(batch, f)

        orch = BatchOrchestrator()
        scenarios = orch.load_batch_file(path)
        assert len(scenarios) == 2

    def test_load_dict_format(self, tmp_path):
        """Load batch file in dict format with scenarios key."""
        import json
        batch = {
            "batch_name": "My Batch",
            "scenarios": [
                {"name": "Test 1"},
                {"name": "Test 2"},
            ],
        }
        path = str(tmp_path / "batch.json")
        with open(path, "w") as f:
            json.dump(batch, f)

        orch = BatchOrchestrator()
        scenarios = orch.load_batch_file(path)
        assert len(scenarios) == 2
