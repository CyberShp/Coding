"""
Layer 2 – API Contract Tests for alert query/management endpoints.

Exercises /api/alerts, /api/alerts/stats, /api/alerts/recent, /api/alerts/summary
through the ASGI test client.
"""

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from backend.models.alert import AlertModel
from backend.models.array import ArrayModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_array(db, array_id="arr1", name="Array-1", host="10.0.0.1"):
    """Insert a test array."""
    arr = ArrayModel(
        array_id=array_id, name=name, host=host,
        port=22, username="root", key_path="", folder="",
    )
    db.add(arr)
    await db.flush()
    return arr


async def _seed_alert(db, array_id="arr1", observer="obs", level="info",
                       message="msg", details=None, ts=None):
    """Insert a test alert."""
    a = AlertModel(
        array_id=array_id,
        observer_name=observer,
        level=level,
        message=message,
        details=json.dumps(details or {}),
        timestamp=ts or datetime.now(),
    )
    db.add(a)
    await db.flush()
    return a


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetAlerts:
    """Tests for GET /api/alerts."""

    async def test_get_alerts_empty(self, app_client_with_db):
        """No matching alerts → empty list."""
        client, db = app_client_with_db
        # Seed a recent alert so the DB connection is "warm" (works around
        # aiosqlite commit-after-idle-SELECT race condition).
        await _seed_array(db)
        await _seed_alert(db, level="info", message="seed")
        await db.commit()

        # First, make a request that returns data (warms the connection)
        resp_warm = await client.get("/api/alerts", params={"hours": 1})
        assert resp_warm.status_code == 200

        # Now query with a filter that matches nothing
        resp = await client.get(
            "/api/alerts",
            params={"level": "critical", "hours": 1},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_get_alerts_with_data(self, app_client_with_db):
        """Inject alerts → returns them."""
        client, db = app_client_with_db
        await _seed_array(db)
        await _seed_alert(db, message="hello1")
        await _seed_alert(db, message="hello2")
        await db.commit()

        resp = await client.get("/api/alerts", params={"hours": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2

    async def test_get_alerts_filter_by_level(self, app_client_with_db):
        """?level=error → only error alerts."""
        client, db = app_client_with_db
        await _seed_array(db)
        await _seed_alert(db, level="error", message="err1")
        await _seed_alert(db, level="info", message="info1")
        await db.commit()

        resp = await client.get("/api/alerts", params={"level": "error", "hours": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert all(a["level"] == "error" for a in data)
        assert len(data) >= 1

    async def test_get_alerts_filter_by_observer(self, app_client_with_db):
        """?observer_name=special → filtered."""
        client, db = app_client_with_db
        await _seed_array(db)
        await _seed_alert(db, observer="special", message="s1")
        await _seed_alert(db, observer="other", message="o1")
        await db.commit()

        resp = await client.get("/api/alerts", params={"observer_name": "special", "hours": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert all(a["observer_name"] == "special" for a in data)

    async def test_get_alerts_pagination(self, app_client_with_db):
        """?offset=0&limit=5 → correct page size."""
        client, db = app_client_with_db
        await _seed_array(db)
        for i in range(10):
            await _seed_alert(db, message=f"pg-{i}")
        await db.commit()

        resp = await client.get("/api/alerts", params={"limit": 5, "offset": 0, "hours": 1})
        assert resp.status_code == 200
        assert len(resp.json()) == 5


class TestAlertStats:
    """Tests for GET /api/alerts/stats."""

    async def test_get_alerts_stats(self, app_client_with_db):
        """Stats endpoint returns correct structure."""
        client, db = app_client_with_db
        await _seed_array(db)
        await _seed_alert(db, level="error", message="e1")
        await _seed_alert(db, level="warning", message="w1")
        await _seed_alert(db, level="info", message="i1")
        await db.commit()

        resp = await client.get("/api/alerts/stats", params={"hours": 1})
        assert resp.status_code == 200
        body = resp.json()
        assert "total" in body
        assert body["total"] >= 3
        assert "by_level" in body
        assert "by_observer" in body
        assert "by_array" in body


class TestAlertRecent:
    """Tests for GET /api/alerts/recent."""

    async def test_get_alerts_recent(self, app_client_with_db):
        """Recent endpoint returns alerts, most recent first."""
        client, db = app_client_with_db
        await _seed_array(db)
        t1 = datetime.now() - timedelta(minutes=30)
        t2 = datetime.now()
        await _seed_alert(db, message="older", ts=t1)
        await _seed_alert(db, message="newer", ts=t2)
        await db.commit()

        resp = await client.get("/api/alerts/recent", params={"limit": 10, "hours": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2
        # Most recent first (descending timestamp)
        assert data[0]["message"] == "newer"


class TestAlertSummary:
    """Tests for GET /api/alerts/summary."""

    async def test_get_alerts_summary(self, app_client_with_db):
        """Summary endpoint returns correct shape."""
        client, db = app_client_with_db
        await _seed_array(db)
        await _seed_alert(db, level="error", message="se1")
        await _seed_alert(db, level="info", message="si1")
        await db.commit()

        resp = await client.get("/api/alerts/summary", params={"hours": 2})
        assert resp.status_code == 200
        body = resp.json()
        assert "total" in body
        assert "error_count" in body
        assert "warning_count" in body
        assert body["total"] >= 2
