"""Tests for backend/api/data_lifecycle.py — Data Lifecycle API endpoints."""
import pytest


@pytest.mark.asyncio
class TestDataSyncState:
    async def test_get_sync_state_not_found(self, app_client):
        """Test getting sync state for non-existent array."""
        resp = await app_client.get("/api/data/sync-state/nonexistent-array")
        # May return null/None or 404 depending on implementation
        assert resp.status_code in [200, 404]

    async def test_get_sync_state_empty_result(self, app_client):
        """Test getting sync state returns null for no data."""
        resp = await app_client.get("/api/data/sync-state/test-array")
        assert resp.status_code in [200, 404]


@pytest.mark.asyncio
class TestDataLogFiles:
    async def test_get_log_files_not_connected(self, app_client):
        """Test getting log files from disconnected array."""
        resp = await app_client.get("/api/data/log-files/nonexistent-array")
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestDataImport:
    async def test_import_not_connected(self, app_client):
        """Test importing data from disconnected array."""
        resp = await app_client.post(
            "/api/data/import/nonexistent-array",
            json={"mode": "incremental", "days": 7},
        )
        assert resp.status_code == 400

    async def test_import_invalid_mode(self, app_client):
        """Test importing with invalid mode."""
        resp = await app_client.post(
            "/api/data/import/test-array",
            json={"mode": "invalid_mode", "days": 7},
        )
        # Should fail validation
        assert resp.status_code in [400, 422]

    async def test_import_incremental_mode(self, app_client):
        """Test importing with incremental mode."""
        resp = await app_client.post(
            "/api/data/import/test-array",
            json={"mode": "incremental", "days": 7},
        )
        assert resp.status_code == 400  # Not connected

    async def test_import_full_mode(self, app_client):
        """Test importing with full mode."""
        resp = await app_client.post(
            "/api/data/import/test-array",
            json={"mode": "full"},
        )
        assert resp.status_code == 400  # Not connected

    async def test_import_selective_mode(self, app_client):
        """Test importing with selective mode."""
        resp = await app_client.post(
            "/api/data/import/test-array",
            json={
                "mode": "selective",
                "log_files": ["/var/log/alerts.log.1", "/var/log/alerts.log.2"],
            },
        )
        assert resp.status_code == 400  # Not connected


@pytest.mark.asyncio
class TestArchiveConfig:
    async def test_get_archive_config(self, app_client):
        """Test getting archive configuration."""
        resp = await app_client.get("/api/data/archive/config")
        assert resp.status_code == 200
        data = resp.json()
        # Should have config fields
        assert "enabled" in data or "retention_days" in data or isinstance(data, dict)

    async def test_update_archive_config(self, app_client):
        """Test updating archive configuration."""
        # Get current config first
        get_resp = await app_client.get("/api/data/archive/config")
        assert get_resp.status_code == 200
        current_config = get_resp.json()
        
        # Update with same or modified config
        resp = await app_client.put(
            "/api/data/archive/config",
            json=current_config,
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestArchiveRun:
    async def test_run_archive(self, app_client):
        """Test manually triggering archive process."""
        resp = await app_client.post("/api/data/archive/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "success" in data
        assert "archived" in data
        assert "deleted" in data


@pytest.mark.asyncio
class TestArchiveStats:
    async def test_get_archive_stats(self, app_client):
        """Test getting archive statistics."""
        resp = await app_client.get("/api/data/archive/stats")
        assert resp.status_code == 200
        data = resp.json()
        # Should have stats fields
        assert isinstance(data, dict)


@pytest.mark.asyncio
class TestArchiveQuery:
    async def test_query_archive_default(self, app_client):
        """Test querying archive with default parameters."""
        resp = await app_client.get("/api/data/archive/query")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    async def test_query_archive_with_array_filter(self, app_client):
        """Test querying archive with array filter."""
        resp = await app_client.get("/api/data/archive/query?array_id=test-array")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    async def test_query_archive_with_year_month(self, app_client):
        """Test querying archive with year_month filter."""
        resp = await app_client.get("/api/data/archive/query?year_month=2024-01")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    async def test_query_archive_with_limit(self, app_client):
        """Test querying archive with custom limit."""
        resp = await app_client.get("/api/data/archive/query?limit=100")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    async def test_query_archive_limit_too_high(self, app_client):
        """Test querying archive with limit exceeding max."""
        resp = await app_client.get("/api/data/archive/query?limit=10000")
        # Should be capped or return error
        assert resp.status_code in [200, 422]

    async def test_query_archive_invalid_year_month(self, app_client):
        """Test querying archive with invalid year_month format."""
        resp = await app_client.get("/api/data/archive/query?year_month=invalid")
        # May accept or reject depending on validation
        assert resp.status_code in [200, 400, 422]


@pytest.mark.asyncio
class TestDataLifecycleEdgeCases:
    async def test_import_negative_days(self, app_client):
        """Test importing with negative days."""
        resp = await app_client.post(
            "/api/data/import/test-array",
            json={"mode": "incremental", "days": -1},
        )
        # Should fail validation
        assert resp.status_code in [400, 422]

    async def test_import_zero_days(self, app_client):
        """Test importing with zero days."""
        resp = await app_client.post(
            "/api/data/import/test-array",
            json={"mode": "incremental", "days": 0},
        )
        # Should fail validation (should be > 0)
        assert resp.status_code in [400, 422]

    async def test_import_very_large_days(self, app_client):
        """Test importing with very large days."""
        resp = await app_client.post(
            "/api/data/import/test-array",
            json={"mode": "incremental", "days": 10000},
        )
        # Should fail validation
        assert resp.status_code in [400, 422]

    async def test_query_archive_special_characters_array_id(self, app_client):
        """Test querying archive with special characters in array_id."""
        resp = await app_client.get("/api/data/archive/query?array_id=array@#$%")
        # Should handle gracefully
        assert resp.status_code in [200, 400, 422]

    async def test_query_archive_unicode_array_id(self, app_client):
        """Test querying archive with unicode characters in array_id."""
        resp = await app_client.get("/api/data/archive/query?array_id=测试阵列")
        # Should handle gracefully
        assert resp.status_code in [200, 400, 422]
