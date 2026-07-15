"""Tests for backend/api/alerts.py — Alert API endpoints."""
import json
import pytest
import pytest_asyncio
from datetime import datetime, timedelta

from backend.models.alert import AlertModel


@pytest.mark.asyncio
class TestAlertAPI:
    async def test_list_alerts_empty(self, app_client):
        resp = await app_client.get("/api/alerts")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_list_alerts_with_level_filter(self, app_client):
        resp = await app_client.get("/api/alerts?level=error&hours=24")
        assert resp.status_code == 200

    async def test_list_alerts_with_observer_filter(self, app_client):
        resp = await app_client.get("/api/alerts?observer_name=alarm_type")
        assert resp.status_code == 200

    async def test_list_alerts_pagination(self, app_client):
        resp = await app_client.get("/api/alerts?limit=10&offset=0")
        assert resp.status_code == 200

    async def test_personal_scope_filters_data_total_and_stats(self, app_client_with_db):
        client, db = app_client_with_db
        db.add_all([
            AlertModel(
                array_id="array-1", observer_name="cpu_usage", level="warning",
                message="in scope", details="{}", timestamp=datetime.now(),
            ),
            AlertModel(
                array_id="array-2", observer_name="cpu_usage", level="warning",
                message="wrong array", details="{}", timestamp=datetime.now(),
            ),
            AlertModel(
                array_id="array-1", observer_name="link_status", level="error",
                message="wrong observer", details="{}", timestamp=datetime.now(),
            ),
        ])
        await db.commit()

        params = {"array_ids": "array-1", "observer_names": "cpu_usage"}
        response = await client.get("/api/alerts", params=params)
        stats = await client.get("/api/alerts/stats", params={"hours": 24, **params})

        assert [item["message"] for item in response.json()] == ["in scope"]
        assert response.headers["x-total-count"] == "1"
        assert stats.json()["total"] == 1

    async def test_alert_stats(self, app_client):
        resp = await app_client.get("/api/alerts/stats?hours=24")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data

    async def test_alert_recent(self, app_client):
        resp = await app_client.get("/api/alerts/recent?limit=5")
        assert resp.status_code == 200

    async def test_alert_summary(self, app_client):
        resp = await app_client.get("/api/alerts/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_24h" in data

    async def test_export_csv(self, app_client):
        resp = await app_client.get("/api/alerts/export?format=csv&hours=24")
        assert resp.status_code == 200

    async def test_cleanup_alerts(self, app_client):
        resp = await app_client.delete("/api/alerts/cleanup?days=30")
        assert resp.status_code == 200
        data = resp.json()
        assert "deleted" in data
