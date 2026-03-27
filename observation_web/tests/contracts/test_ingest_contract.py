"""
Layer 2 – API Contract Tests for /api/ingest and /api/ingest/batch.

Uses the ASGI test client from conftest (app_client_with_db) so every
request goes through the real FastAPI router/middleware stack.
"""

import json
from datetime import datetime

import pytest
from sqlalchemy import select

from backend.models.alert import AlertModel
from backend.models.array import ArrayModel


# ---------------------------------------------------------------------------
# A. Single alert ingest
# ---------------------------------------------------------------------------

class TestIngestSingleAlert:
    """Tests for POST /api/ingest with type=alert."""

    async def test_ingest_single_alert(self, app_client_with_db):
        """Valid alert payload → 200, alert stored in DB."""
        client, db = app_client_with_db
        payload = {
            "type": "alert",
            "observer_name": "link_check",
            "level": "error",
            "message": "Link down on port 3",
            "timestamp": datetime.now().isoformat(),
        }
        resp = await client.post("/api/ingest", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True

        # Verify persisted in DB
        result = await db.execute(select(AlertModel))
        alerts = result.scalars().all()
        assert len(alerts) >= 1
        stored = alerts[-1]
        assert stored.observer_name == "link_check"
        assert stored.level == "error"

    async def test_ingest_alert_with_details(self, app_client_with_db):
        """Alert with details dict → stored correctly."""
        client, db = app_client_with_db
        details = {"port": 5, "speed": "10G", "errors": 42}
        payload = {
            "type": "alert",
            "observer_name": "phy_observer",
            "level": "warning",
            "message": "CRC errors rising",
            "details": details,
            "timestamp": datetime.now().isoformat(),
        }
        resp = await client.post("/api/ingest", json=payload)
        assert resp.status_code == 200

        result = await db.execute(
            select(AlertModel).where(AlertModel.observer_name == "phy_observer")
        )
        stored = result.scalars().first()
        assert stored is not None
        parsed = json.loads(stored.details)
        assert parsed["port"] == 5
        assert parsed["errors"] == 42

    async def test_ingest_metrics(self, app_client_with_db):
        """Valid metrics payload → 200."""
        client, _db = app_client_with_db
        payload = {
            "type": "metrics",
            "ts": datetime.now().isoformat(),
            "cpu0": 45.2,
            "mem_used_mb": 1024.0,
            "mem_total_mb": 4096.0,
        }
        resp = await client.post("/api/ingest", json=payload)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    async def test_ingest_unknown_type(self, app_client_with_db):
        """type != 'alert'|'metrics' → 400."""
        client, _db = app_client_with_db
        resp = await client.post("/api/ingest", json={"type": "bogus"})
        assert resp.status_code == 400

    async def test_ingest_missing_type(self, app_client_with_db):
        """No type field → 422 validation error."""
        client, _db = app_client_with_db
        resp = await client.post("/api/ingest", json={"observer_name": "x"})
        assert resp.status_code == 422

    async def test_ingest_alert_missing_fields(self, app_client_with_db):
        """Alert without observer_name → handled gracefully (defaults to 'unknown')."""
        client, db = app_client_with_db
        payload = {
            "type": "alert",
            "level": "info",
            "message": "bare alert",
        }
        resp = await client.post("/api/ingest", json=payload)
        assert resp.status_code == 200

        result = await db.execute(
            select(AlertModel).where(AlertModel.message == "bare alert")
        )
        stored = result.scalars().first()
        assert stored is not None
        assert stored.observer_name == "unknown"

    async def test_ingest_alert_with_invalid_timestamp(self, app_client_with_db):
        """Bad timestamp format → still ingested (falls back to now())."""
        client, db = app_client_with_db
        payload = {
            "type": "alert",
            "observer_name": "ts_test",
            "level": "info",
            "message": "bad ts",
            "timestamp": "not-a-date",
        }
        resp = await client.post("/api/ingest", json=payload)
        assert resp.status_code == 200

        result = await db.execute(
            select(AlertModel).where(AlertModel.observer_name == "ts_test")
        )
        stored = result.scalars().first()
        assert stored is not None
        # Timestamp should still be set (fallback to now)
        assert stored.timestamp is not None

    async def test_ingest_empty_body(self, app_client_with_db):
        """Empty JSON object → 422 (missing required 'type')."""
        client, _db = app_client_with_db
        resp = await client.post("/api/ingest", json={})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# B. Batch ingest
# ---------------------------------------------------------------------------

class TestIngestBatch:
    """Tests for POST /api/ingest/batch."""

    async def test_ingest_batch_valid(self, app_client_with_db):
        """Array of valid payloads → 200 with correct counts."""
        client, _db = app_client_with_db
        payloads = [
            {"type": "alert", "observer_name": "obs1", "level": "info", "message": "a1"},
            {"type": "alert", "observer_name": "obs2", "level": "warning", "message": "a2"},
        ]
        resp = await client.post("/api/ingest/batch", content=json.dumps(payloads))
        assert resp.status_code == 200
        body = resp.json()
        assert body["alerts"] == 2
        assert body["errors"] == 0

    async def test_ingest_batch_mixed(self, app_client_with_db):
        """Alerts + metrics mixed → all processed."""
        client, _db = app_client_with_db
        payloads = [
            {"type": "alert", "observer_name": "mix", "level": "info", "message": "m1"},
            {"type": "metrics", "cpu0": 10.0},
            {"type": "alert", "observer_name": "mix", "level": "error", "message": "m2"},
        ]
        resp = await client.post("/api/ingest/batch", content=json.dumps(payloads))
        assert resp.status_code == 200
        body = resp.json()
        assert body["alerts"] == 2
        assert body["metrics"] == 1

    async def test_ingest_batch_empty_array(self, app_client_with_db):
        """Empty array → 200 with 0 processed."""
        client, _db = app_client_with_db
        resp = await client.post("/api/ingest/batch", content=json.dumps([]))
        assert resp.status_code == 200
        body = resp.json()
        assert body["alerts"] == 0
        assert body["metrics"] == 0
        assert body["errors"] == 0

    async def test_ingest_batch_non_array(self, app_client_with_db):
        """Object instead of array → 400."""
        client, _db = app_client_with_db
        resp = await client.post("/api/ingest/batch", content=json.dumps({"type": "alert"}))
        assert resp.status_code == 400

    async def test_ingest_batch_partial_invalid(self, app_client_with_db):
        """Some valid, some invalid → partial success."""
        client, _db = app_client_with_db
        payloads = [
            {"type": "alert", "observer_name": "ok", "level": "info", "message": "good"},
            {"not_a_type": "missing type field"},  # fails IngestPayload(**item) → error
            {"type": "alert", "observer_name": "ok2", "level": "error", "message": "also good"},
        ]
        resp = await client.post("/api/ingest/batch", content=json.dumps(payloads))
        assert resp.status_code == 200
        body = resp.json()
        assert body["alerts"] == 2
        assert body["errors"] == 1


# ---------------------------------------------------------------------------
# C. Source IP derivation
# ---------------------------------------------------------------------------

class TestIngestSourceIP:
    """Tests for source-IP → array_id mapping."""

    async def test_ingest_source_ip_derives_array(self, app_client_with_db):
        """When an array exists with matching host, alert gets push_{source_ip} as array_id."""
        client, db = app_client_with_db

        # Create an array with a known host
        arr = ArrayModel(
            array_id="arr_10",
            name="TestArray10",
            host="192.168.1.10",
            port=22,
            username="root",
            key_path="",
            folder="",
        )
        db.add(arr)
        await db.flush()

        payload = {
            "type": "alert",
            "observer_name": "ip_test",
            "level": "info",
            "message": "from known host",
        }
        resp = await client.post("/api/ingest", json=payload)
        assert resp.status_code == 200

        # The ingest handler uses "push_{source_ip}" as array_id.
        # In the test client the source IP is typically "127.0.0.1".
        result = await db.execute(
            select(AlertModel).where(AlertModel.observer_name == "ip_test")
        )
        stored = result.scalars().first()
        assert stored is not None
        assert stored.array_id.startswith("push_")
