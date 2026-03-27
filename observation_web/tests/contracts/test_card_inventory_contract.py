"""
Layer 2 – API Contract Tests for card inventory endpoints.

Exercises /api/card-inventory (list, search, last-sync, sync) through the
ASGI test client.
"""

import json
from datetime import datetime

import pytest
from sqlalchemy import select

from backend.models.card_inventory import CardInventoryModel
from backend.models.array import ArrayModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_array(db, array_id="arr1", name="Array-1", host="10.0.0.1"):
    arr = ArrayModel(
        array_id=array_id, name=name, host=host,
        port=22, username="root", key_path="", folder="",
    )
    db.add(arr)
    await db.flush()
    return arr


async def _seed_card(db, array_id="arr1", card_no="No001", board_id="BOARD001",
                      health="Normal", running="RUNNING", model="X100"):
    card = CardInventoryModel(
        array_id=array_id,
        card_no=card_no,
        board_id=board_id,
        health_state=health,
        running_state=running,
        model=model,
        raw_fields=json.dumps({"BoardId": board_id}),
        last_updated=datetime.now(),
    )
    db.add(card)
    await db.flush()
    return card


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCardInventoryList:
    """Tests for GET /api/card-inventory."""

    async def test_get_cards_empty(self, app_client_with_db):
        """No cards → empty list."""
        client, _db = app_client_with_db
        resp = await client.get("/api/card-inventory")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_get_cards_with_data(self, app_client_with_db):
        """Inject cards → returns them."""
        client, db = app_client_with_db
        await _seed_array(db)
        await _seed_card(db, card_no="No001", board_id="B001")
        await _seed_card(db, card_no="No002", board_id="B002")
        await db.commit()

        resp = await client.get("/api/card-inventory")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2


class TestCardInventorySearch:
    """Tests for GET /api/card-inventory?q=..."""

    async def test_search_cards_by_board_id(self, app_client_with_db):
        """Search by board_id keyword → correct results."""
        client, db = app_client_with_db
        await _seed_array(db)
        await _seed_card(db, card_no="No010", board_id="BOARD123", model="X200")
        await _seed_card(db, card_no="No011", board_id="BOARD456", model="Y300")
        await db.commit()

        resp = await client.get("/api/card-inventory", params={"q": "BOARD123"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert any(c["board_id"] == "BOARD123" for c in data)

    async def test_search_cards_by_ip(self, app_client_with_db):
        """Search by array host → finds cards."""
        client, db = app_client_with_db
        await _seed_array(db, host="192.168.99.1")
        await _seed_card(db, card_no="No020", board_id="BIP1")
        await db.commit()

        resp = await client.get("/api/card-inventory", params={"q": "192.168.99.1"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1

    async def test_search_cards_no_results(self, app_client_with_db):
        """Non-existent keyword → empty."""
        client, db = app_client_with_db
        await _seed_array(db)
        await _seed_card(db)
        await db.commit()

        resp = await client.get("/api/card-inventory", params={"q": "NONEXISTENT999"})
        assert resp.status_code == 200
        assert resp.json() == []


class TestCardSync:
    """Tests for POST /api/card-inventory/sync."""

    async def test_card_sync_endpoint(self, app_client_with_db):
        """POST sync → triggers sync operation (returns result shape)."""
        client, _db = app_client_with_db
        resp = await client.post("/api/card-inventory/sync")
        assert resp.status_code == 200
        body = resp.json()
        # Sync without any SSH connections should still return a valid result
        assert "synced" in body
        assert "errors" in body
        assert isinstance(body["synced"], int)
