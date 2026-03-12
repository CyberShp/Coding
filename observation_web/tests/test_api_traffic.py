"""Tests for backend/api/traffic.py — Traffic API endpoints."""
import pytest


@pytest.mark.asyncio
class TestTrafficPorts:
    """Test traffic ports endpoints."""
    
    async def test_get_ports_empty(self, app_client):
        """Test getting ports for array with no traffic data."""
        resp = await app_client.get("/api/traffic/test-array/ports")
        assert resp.status_code == 200
        data = resp.json()
        assert "array_id" in data
        assert "ports" in data
        assert isinstance(data["ports"], list)

    async def test_get_ports_nonexistent_array(self, app_client):
        """Test getting ports for non-existent array returns empty."""
        resp = await app_client.get("/api/traffic/nonexistent-array-12345/ports")
        assert resp.status_code == 200  # Returns empty list for nonexistent arrays
        data = resp.json()
        assert "ports" in data


@pytest.mark.asyncio
class TestTrafficData:
    """Test traffic data endpoints."""
    
    async def test_get_traffic_data_missing_port(self, app_client):
        """Test getting traffic data without port parameter returns 422."""
        resp = await app_client.get("/api/traffic/test-array/data")
        assert resp.status_code == 422  # Missing required query param

    async def test_get_traffic_data_invalid_port(self, app_client):
        """Test getting traffic data for non-existent port returns empty."""
        resp = await app_client.get("/api/traffic/test-array/data?port=nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert "data" in data

    async def test_get_traffic_data_with_minutes(self, app_client):
        """Test getting traffic data with custom minutes parameter."""
        resp = await app_client.get("/api/traffic/test-array/data?port=eth0&minutes=60")
        assert resp.status_code == 200
        data = resp.json()
        assert data["minutes"] == 60

    async def test_get_traffic_data_minutes_too_high(self, app_client):
        """Test getting traffic data with minutes exceeding limit returns 422."""
        resp = await app_client.get("/api/traffic/test-array/data?port=eth0&minutes=200")
        assert resp.status_code == 422

    async def test_get_traffic_data_minutes_too_low(self, app_client):
        """Test getting traffic data with minutes below minimum returns 422."""
        resp = await app_client.get("/api/traffic/test-array/data?port=eth0&minutes=0")
        assert resp.status_code == 422

    async def test_get_traffic_data_invalid_array(self, app_client):
        """Test getting traffic data for invalid array."""
        resp = await app_client.get("/api/traffic//data?port=eth0")
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestTrafficSummary:
    """Test traffic summary endpoints."""
    
    async def test_get_traffic_summary_success(self, app_client):
        """Test getting traffic summary."""
        resp = await app_client.get("/api/traffic/test-array/summary?port=eth0")
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data

    async def test_get_traffic_summary_no_port(self, app_client):
        """Test getting traffic summary without port returns 422."""
        resp = await app_client.get("/api/traffic/test-array/summary")
        assert resp.status_code == 422


@pytest.mark.asyncio
class TestTrafficAlerts:
    """Test traffic alert endpoints."""
    
    async def test_get_traffic_alerts_success(self, app_client):
        """Test getting traffic alerts."""
        resp = await app_client.get("/api/traffic/test-array/alerts?port=eth0")
        assert resp.status_code == 200
        data = resp.json()
        assert "alerts" in data

    async def test_get_traffic_alerts_no_port(self, app_client):
        """Test getting traffic alerts without port returns 422."""
        resp = await app_client.get("/api/traffic/test-array/alerts")
        assert resp.status_code == 422
