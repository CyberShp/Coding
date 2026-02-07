"""Tests for backend/api/alerts.py — Alert API endpoints."""
import json
import pytest
import pytest_asyncio
from datetime import datetime, timedelta


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
