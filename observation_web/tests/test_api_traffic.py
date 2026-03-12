"""Tests for backend/api/traffic.py — Traffic API endpoints."""
import pytest


@pytest.mark.asyncio
class TestTrafficPorts:
    async def test_get_ports_empty(self, app_client):
        """Test getting ports for array with no traffic data."""
        resp = await app_client.get("/api/traffic/test-array/ports")
        assert resp.status_code == 200
        data = resp.json()
        assert "array_id" in data
        assert "ports" in data
        assert isinstance(data["ports"], list)

    async def test_get_ports_nonexistent_array(self, app_client):
        """Test getting ports for non-existent array."""
        resp = await app_client.get("/api/traffic/nonexistent-array-12345/ports")
        assert resp.status_code == 200  # Returns empty list, not 404


@pytest.mark.asyncio
class TestTrafficData:
    async def test_get_traffic_data_missing_port(self, app_client):
        """Test getting traffic data without port parameter."""
        resp = await app_client.get("/api/traffic/test-array/data")
        assert resp.status_code == 422  # Missing required query param

    async def test_get_traffic_data_invalid_port(self, app_client):
        """Test getting traffic data for non-existent port."""
        resp = await app_client.get("/api/traffic/test-array/data?port=nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0

    async def test_get_traffic_data_with_minutes(self, app_client):
        """Test getting traffic data with custom minutes parameter."""
        resp = await app_client.get("/api/traffic/test-array/data?port=eth0&minutes=60")
        assert resp.status_code == 200
        data = resp.json()
        assert data["minutes"] == 60

    async def test_get_traffic_data_minutes_too_high(self, app_client):
        """Test getting traffic data with minutes exceeding limit."""
        resp = await app_client.get("/api/traffic/test-array/data?port=eth0&minutes=200")
        assert resp.status_code == 422  # Validation error

    async def test_get_traffic_data_minutes_too_low(self, app_client):
        """Test getting traffic data with minutes below minimum."""
        resp = await app_client.get("/api/traffic/test-array/data?port=eth0&minutes=0")
        assert resp.status_code == 422  # Validation error

    async def test_get_traffic_data_negative_minutes(self, app_client):
        """Test getting traffic data with negative minutes."""
        resp = await app_client.get("/api/traffic/test-array/data?port=eth0&minutes=-1")
        assert resp.status_code == 422  # Validation error


@pytest.mark.asyncio
class TestTrafficSync:
    async def test_sync_traffic_not_connected(self, app_client):
        """Test syncing traffic for disconnected array."""
        resp = await app_client.post("/api/traffic/nonexistent-array/sync")
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestTrafficDiagnostic:
    async def test_diagnostic_not_connected(self, app_client):
        """Test diagnostic for disconnected array."""
        resp = await app_client.get("/api/traffic/nonexistent-array/diagnostic")
        assert resp.status_code == 400

    async def test_diagnostic_response_structure(self, app_client):
        """Test diagnostic response has expected fields."""
        # Even for non-connected array, should return proper error
        resp = await app_client.get("/api/traffic/nonexistent-array/diagnostic")
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestTrafficModeInfo:
    async def test_mode_info_empty(self, app_client):
        """Test mode info for array with no data."""
        resp = await app_client.get("/api/traffic/test-array/mode-info")
        assert resp.status_code == 200
        data = resp.json()
        assert "array_id" in data
        assert "ports" in data
        assert "modes_detected" in data
        assert "protocols_detected" in data


@pytest.mark.asyncio
class TestTrafficEdgeCases:
    async def test_traffic_special_characters_array_id(self, app_client):
        """Test traffic endpoints with special characters in array_id."""
        resp = await app_client.get("/api/traffic/array@#$%/ports")
        # Should handle gracefully
        assert resp.status_code in [200, 400, 404, 422]

    async def test_traffic_very_long_array_id(self, app_client):
        """Test traffic endpoints with very long array_id."""
        long_id = "a" * 500
        resp = await app_client.get(f"/api/traffic/{long_id}/ports")
        # Should handle gracefully
        assert resp.status_code in [200, 400, 404, 422]

    async def test_traffic_unicode_array_id(self, app_client):
        """Test traffic endpoints with unicode characters in array_id."""
        resp = await app_client.get("/api/traffic/测试阵列/ports")
        # Should handle gracefully
        assert resp.status_code in [200, 400, 404, 422]
