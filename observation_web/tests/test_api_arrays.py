"""Tests for backend/api/arrays.py — Array API endpoints."""
import pytest


@pytest.mark.asyncio
class TestArrayAPI:
    async def test_list_arrays(self, app_client):
        resp = await app_client.get("/api/arrays")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_create_array(self, app_client):
        data = {
            "name": "测试阵列",
            "host": "10.0.0.200",
            "port": 22,
            "username": "admin"
        }
        resp = await app_client.post("/api/arrays", json=data)
        assert resp.status_code in [200, 201, 400]

    async def test_get_array_not_found(self, app_client):
        resp = await app_client.get("/api/arrays/nonexistent-id")
        assert resp.status_code == 404

    async def test_delete_array_not_found(self, app_client):
        resp = await app_client.delete("/api/arrays/nonexistent-id")
        assert resp.status_code == 404

    async def test_list_statuses(self, app_client):
        resp = await app_client.get("/api/arrays/statuses")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_connect_array_not_found(self, app_client):
        resp = await app_client.post("/api/arrays/nonexistent/connect?password=test")
        assert resp.status_code == 404

    async def test_disconnect_array_not_found(self, app_client):
        resp = await app_client.post("/api/arrays/nonexistent/disconnect")
        # FIXED: Now returns 404 for nonexistent arrays
        assert resp.status_code == 404

    async def test_refresh_array_not_found(self, app_client):
        resp = await app_client.post("/api/arrays/nonexistent/refresh")
        # FIXED: Now returns 404 for nonexistent arrays
        assert resp.status_code == 404

    async def test_deploy_agent_not_found(self, app_client):
        resp = await app_client.post("/api/arrays/nonexistent/deploy-agent")
        # FIXED: Now returns 404 for nonexistent arrays
        assert resp.status_code == 404

    async def test_get_array_status_not_found(self, app_client):
        resp = await app_client.get("/api/arrays/nonexistent/status")
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestArrayAPIEdgeCases:
    async def test_create_array_missing_fields(self, app_client):
        resp = await app_client.post("/api/arrays", json={"name": "Test"})
        assert resp.status_code == 422

    async def test_create_array_empty_name(self, app_client):
        """FIXED: Empty name now rejected by Pydantic field_validator."""
        data = {"name": "", "host": "10.0.0.201", "port": 22, "username": "admin"}
        resp = await app_client.post("/api/arrays", json=data)
        assert resp.status_code == 422

    async def test_create_array_invalid_port(self, app_client):
        """FIXED: Port validation now enforced (1-65535)."""
        data = {"name": "Test", "host": "10.0.0.202", "port": -1, "username": "admin"}
        resp = await app_client.post("/api/arrays", json=data)
        assert resp.status_code == 422

    async def test_create_array_port_too_high(self, app_client):
        """Port 70000 exceeds maximum (65535)."""
        data = {"name": "Test", "host": "10.0.0.203", "port": 70000, "username": "admin"}
        resp = await app_client.post("/api/arrays", json=data)
        assert resp.status_code == 422
