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
        """Valid alert payload with real array_id → 200, alert stored in DB."""
        client, db = app_client_with_db

        # Create an array so the array_id is valid
        arr = ArrayModel(
            array_id="arr_ingest_1", name="IngestTest1", host="10.0.0.1",
            port=22, username="root", key_path="", folder="",
        )
        db.add(arr)
        await db.flush()

        payload = {
            "type": "alert",
            "array_id": "arr_ingest_1",
            "observer_name": "link_check",
            "level": "error",
            "message": "Link down on port 3",
            "timestamp": datetime.now().isoformat(),
        }
        resp = await client.post("/api/ingest", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["array_id"] == "arr_ingest_1"

        # Verify persisted in DB
        result = await db.execute(select(AlertModel))
        alerts = result.scalars().all()
        assert len(alerts) >= 1
        stored = alerts[-1]
        assert stored.observer_name == "link_check"
        assert stored.level == "error"
        assert stored.array_id == "arr_ingest_1"  # real array_id, not push_xxx

    async def test_ingest_alert_with_details(self, app_client_with_db):
        """Alert with details dict → stored correctly."""
        client, db = app_client_with_db
        details = {"port": 5, "speed": "10G", "errors": 42}
        payload = {
            "type": "alert",
            "array_id": "arr_detail_test",
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

    async def test_ingest_alert_missing_array_id(self, app_client_with_db):
        """Alert without array_id and no IP mapping → 400."""
        client, db = app_client_with_db
        payload = {
            "type": "alert",
            "observer_name": "no_id",
            "level": "info",
            "message": "no array_id",
        }
        resp = await client.post("/api/ingest", json=payload)
        assert resp.status_code == 400
        assert "array_id" in resp.json()["detail"].lower()

    async def test_ingest_alert_with_invalid_timestamp(self, app_client_with_db):
        """Bad timestamp format → still ingested (falls back to now())."""
        client, db = app_client_with_db
        payload = {
            "type": "alert",
            "array_id": "arr_ts_test",
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
        """Array of valid payloads with array_id → 200 with correct counts."""
        client, _db = app_client_with_db
        payloads = [
            {"type": "alert", "array_id": "arr_batch_1", "observer_name": "obs1", "level": "info", "message": "a1"},
            {"type": "alert", "array_id": "arr_batch_1", "observer_name": "obs2", "level": "warning", "message": "a2"},
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
            {"type": "alert", "array_id": "arr_mix", "observer_name": "mix", "level": "info", "message": "m1"},
            {"type": "metrics", "cpu0": 10.0},
            {"type": "alert", "array_id": "arr_mix", "observer_name": "mix", "level": "error", "message": "m2"},
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
            {"type": "alert", "array_id": "arr_ok", "observer_name": "ok", "level": "info", "message": "good"},
            {"not_a_type": "missing type field"},  # fails IngestPayload(**item) → error
            {"type": "alert", "array_id": "arr_ok", "observer_name": "ok2", "level": "error", "message": "also good"},
        ]
        resp = await client.post("/api/ingest/batch", content=json.dumps(payloads))
        assert resp.status_code == 200
        body = resp.json()
        assert body["alerts"] == 2
        assert body["errors"] == 1


# ---------------------------------------------------------------------------
# C. Source IP / array_id resolution
# ---------------------------------------------------------------------------

class TestIngestArrayIdResolution:
    """Tests for array_id resolution: real array_id required, push_xxx rejected."""

    async def test_ingest_with_real_array_id(self, app_client_with_db):
        """When payload has a real array_id, it is used directly."""
        client, db = app_client_with_db
        payload = {
            "type": "alert",
            "array_id": "real_arr_100",
            "observer_name": "resolution_test",
            "level": "info",
            "message": "has real id",
        }
        resp = await client.post("/api/ingest", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["array_id"] == "real_arr_100"

    async def test_ingest_rejects_push_prefix_id(self, app_client_with_db):
        """push_xxx pseudo IDs are rejected → falls back to IP mapping or error."""
        client, db = app_client_with_db
        payload = {
            "type": "alert",
            "array_id": "push_192.168.1.10",
            "observer_name": "push_test",
            "level": "info",
            "message": "should reject",
        }
        resp = await client.post("/api/ingest", json=payload)
        # push_ prefix is rejected; no IP mapping registered → 400
        assert resp.status_code == 400

    async def test_ingest_no_array_id_no_mapping(self, app_client_with_db):
        """No array_id and no IP mapping → 400."""
        client, db = app_client_with_db
        payload = {
            "type": "alert",
            "observer_name": "no_id",
            "level": "info",
            "message": "missing id",
        }
        resp = await client.post("/api/ingest", json=payload)
        assert resp.status_code == 400
        assert "array_id" in resp.json()["detail"].lower()
