"""Tests for backend/api/data_lifecycle.py — Data Lifecycle API."""
import pytest


@pytest.mark.asyncio
class TestDataLifecycle:
    """Test data lifecycle endpoints."""
    
    async def test_get_data_lifecycle_config(self, app_client):
        """Test getting data lifecycle configuration."""
        resp = await app_client.get("/api/data/lifecycle/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "retention_days" in data or "config" in data

    async def test_update_data_lifecycle_config(self, app_client):
        """Test updating data lifecycle configuration."""
        resp = await app_client.post(
            "/api/data/lifecycle/config",
            json={"retention_days": 30}
        )
        assert resp.status_code in [200, 201, 400]

    async def test_get_data_lifecycle_status(self, app_client):
        """Test getting data lifecycle status."""
        resp = await app_client.get("/api/data/lifecycle/status")
        assert resp.status_code == 200

    async def test_trigger_data_cleanup(self, app_client):
        """Test triggering manual data cleanup."""
        resp = await app_client.post("/api/data/lifecycle/cleanup")
        assert resp.status_code in [200, 202, 400]

    async def test_get_storage_usage(self, app_client):
        """Test getting storage usage information."""
        resp = await app_client.get("/api/data/lifecycle/storage")
        assert resp.status_code == 200
        data = resp.json()
        assert "used" in data or "total" in data or "storage" in data

    async def test_get_data_lifecycle_stats(self, app_client):
        """Test getting data lifecycle statistics."""
        resp = await app_client.get("/api/data/lifecycle/stats")
        assert resp.status_code == 200

    async def test_invalid_retention_days(self, app_client):
        """Test updating with invalid retention days."""
        resp = await app_client.post(
            "/api/data/lifecycle/config",
            json={"retention_days": -1}
        )
        assert resp.status_code == 422

    async def test_retention_too_large(self, app_client):
        """Test updating with retention days too large."""
        resp = await app_client.post(
            "/api/data/lifecycle/config",
            json={"retention_days": 10000}
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestDataLifecycleArrays:
    """Test per-array data lifecycle endpoints."""
    
    async def test_get_array_lifecycle_config(self, app_client):
        """Test getting array-specific lifecycle config."""
        resp = await app_client.get("/api/data/lifecycle/array/test-array/config")
        assert resp.status_code == 200

    async def test_update_array_lifecycle_config(self, app_client):
        """Test updating array-specific lifecycle config."""
        resp = await app_client.post(
            "/api/data/lifecycle/array/test-array/config",
            json={"retention_days": 15}
        )
        assert resp.status_code in [200, 201, 400]

    async def test_get_array_storage_usage(self, app_client):
        """Test getting array-specific storage usage."""
        resp = await app_client.get("/api/data/lifecycle/array/test-array/storage")
        assert resp.status_code == 200
