"""Tests for misc API endpoints — system alerts, query, ingest, health."""
import pytest


@pytest.mark.asyncio
class TestHealthAPI:
    async def test_health(self, app_client):
        resp = await app_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    async def test_api_info(self, app_client):
        resp = await app_client.get("/api")
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data
        assert "endpoints" in data


@pytest.mark.asyncio
class TestSystemAlertAPI:
    async def test_list_system_alerts(self, app_client):
        resp = await app_client.get("/api/system-alerts")
        assert resp.status_code == 200

    async def test_system_alert_stats(self, app_client):
        resp = await app_client.get("/api/system-alerts/stats")
        assert resp.status_code == 200

    async def test_debug_info(self, app_client):
        resp = await app_client.get("/api/system-alerts/debug")
        assert resp.status_code == 200
        data = resp.json()
        assert "system_info" in data

    async def test_clear_system_alerts(self, app_client):
        resp = await app_client.delete("/api/system-alerts")
        assert resp.status_code == 200

    async def test_create_test_alert(self, app_client):
        resp = await app_client.post("/api/system-alerts/test?level=info&message=test")
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestQueryAPI:
    async def test_list_templates(self, app_client):
        resp = await app_client.get("/api/query/templates")
        assert resp.status_code == 200

    async def test_validate_pattern_valid(self, app_client):
        resp = await app_client.post("/api/query/validate-pattern",
                                     json={"pattern": r"\d+"})
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    async def test_validate_pattern_invalid(self, app_client):
        resp = await app_client.post("/api/query/validate-pattern",
                                     json={"pattern": r"[invalid"})
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    async def test_delete_builtin_template(self, app_client):
        """BUG-MARKER: Deleting built-in template (negative ID) should be rejected."""
        resp = await app_client.delete("/api/query/templates/-1")
        assert resp.status_code in [400, 403]


@pytest.mark.asyncio
class TestIngestAPI:
    async def test_ingest_alert(self, app_client):
        payload = {
            "type": "alert",
            "observer_name": "cpu_usage",
            "level": "warning",
            "message": "CPU high",
            "timestamp": "2026-02-05T10:00:00",
            "details": {"cpu": 95}
        }
        resp = await app_client.post("/api/ingest", json=payload)
        assert resp.status_code == 200

    async def test_ingest_metrics(self, app_client):
        payload = {
            "type": "metrics",
            "ts": "2026-02-05T10:00:00",
            "cpu0": 45.2,
            "mem_used_mb": 3200
        }
        resp = await app_client.post("/api/ingest", json=payload)
        assert resp.status_code == 200

    async def test_ingest_unknown_type(self, app_client):
        payload = {"type": "unknown"}
        resp = await app_client.post("/api/ingest", json=payload)
        assert resp.status_code == 400

    async def test_ingest_batch(self, app_client):
        payload = [
            {"type": "metrics", "ts": "2026-02-05T10:00:00", "cpu0": 50},
            {"type": "metrics", "ts": "2026-02-05T10:01:00", "cpu0": 55},
        ]
        resp = await app_client.post("/api/ingest/batch", json=payload)
        assert resp.status_code == 200

    async def test_ingest_invalid_level_defaults(self, app_client):
        payload = {
            "type": "alert",
            "observer_name": "test",
            "level": "invalid_level",
            "message": "test",
        }
        resp = await app_client.post("/api/ingest", json=payload)
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestSchedulerAPI:
    async def test_list_tasks(self, app_client):
        resp = await app_client.get("/api/tasks")
        assert resp.status_code == 200

    async def test_get_task_not_found(self, app_client):
        resp = await app_client.get("/api/tasks/99999")
        assert resp.status_code == 404

    async def test_delete_task_not_found(self, app_client):
        resp = await app_client.delete("/api/tasks/99999")
        assert resp.status_code == 404

    async def test_recent_results(self, app_client):
        resp = await app_client.get("/api/tasks/results/recent")
        assert resp.status_code == 200
