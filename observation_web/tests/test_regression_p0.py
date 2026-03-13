"""P0 regression tests for recent critical fixes."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.models.array import ArrayModel, ConnectionState
from backend.models.card_inventory import CardInventoryModel
from backend.models.observer_config import ObserverConfigModel


def _parse_sse_events(payload: str):
    events = []
    for line in payload.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


@pytest.mark.asyncio
async def test_batch_connect_stream_uses_saved_password_and_emits_progress(app_client_with_db, monkeypatch):
    """Regression: batch connect should fallback to saved password and stream progress events."""
    from backend.api import arrays as arrays_api

    client, db = app_client_with_db
    app = client._transport.app

    arr1 = ArrayModel(
        array_id="arr-batch-1",
        name="arr-batch-1",
        host="10.10.1.1",
        port=22,
        username="root",
        key_path="",
        folder="",
        saved_password="same-pass",
    )
    arr2 = ArrayModel(
        array_id="arr-batch-2",
        name="arr-batch-2",
        host="10.10.1.2",
        port=22,
        username="root",
        key_path="",
        folder="",
        saved_password="same-pass",
    )
    db.add_all([arr1, arr2])
    await db.commit()

    class FakeConn:
        def __init__(self):
            self.password = ""
            self.state = ConnectionState.CONNECTED
            self.last_error = ""

        def connect(self):
            return True

    class FakePool:
        def __init__(self):
            self.calls = []

        def get_connection(self, array_id):
            return None

        def add_connection(self, **kwargs):
            self.calls.append(kwargs)
            conn = FakeConn()
            conn.password = kwargs.get("password", "")
            return conn

    fake_pool = FakePool()
    app.dependency_overrides[arrays_api.get_ssh_pool] = lambda: fake_pool
    try:
        resp = await client.post(
            "/api/arrays/batch/connect?stream=true",
            json={"array_ids": ["arr-batch-1", "arr-batch-2"]},
        )
        assert resp.status_code == 200

        events = _parse_sse_events(resp.text)
        assert events[0]["type"] == "start"
        assert events[-1]["type"] == "done"
        progress = [e for e in events if e.get("type") == "progress"]
        assert len(progress) == 2
        assert events[-1]["completed"] == 2
        assert events[-1]["total"] == 2
        assert {e["result"]["array_id"] for e in progress} == {"arr-batch-1", "arr-batch-2"}

        # Must fallback to each array's saved_password when request.password is empty.
        assert len(fake_pool.calls) == 2
        assert all(call["password"] == "same-pass" for call in fake_pool.calls)
    finally:
        app.dependency_overrides.pop(arrays_api.get_ssh_pool, None)


@pytest.mark.asyncio
async def test_auto_reconnect_saved_arrays_skips_empty_password_records(app_client_with_db, monkeypatch):
    """Regression: startup auto-reconnect should only target arrays with non-empty saved passwords."""
    import backend.main as main_mod
    from backend.api import arrays as arrays_api

    _, db = app_client_with_db

    db.add_all(
        [
            ArrayModel(
                array_id="arr-auto-ok",
                name="arr-auto-ok",
                host="10.20.1.1",
                port=22,
                username="root",
                key_path="",
                folder="",
                saved_password="pw-ok",
            ),
            ArrayModel(
                array_id="arr-auto-fail",
                name="arr-auto-fail",
                host="10.20.1.2",
                port=22,
                username="root",
                key_path="",
                folder="",
                saved_password="pw-fail",
            ),
            ArrayModel(
                array_id="arr-auto-skip",
                name="arr-auto-skip",
                host="10.20.1.3",
                port=22,
                username="root",
                key_path="",
                folder="",
                saved_password="   ",
            ),
        ]
    )
    await db.commit()

    class FakeConn:
        def __init__(self, array_id):
            self.array_id = array_id
            self.state = ConnectionState.DISCONNECTED
            self.last_error = "connect failed"

        def connect(self):
            if self.array_id == "arr-auto-ok":
                self.state = ConnectionState.CONNECTED
                self.last_error = ""
                return True
            return False

    class FakePool:
        def __init__(self):
            self.added = []

        def add_connection(self, **kwargs):
            self.added.append(kwargs)
            return FakeConn(kwargs["array_id"])

    fake_pool = FakePool()
    status_map = {}

    def fake_get_status(array_id):
        if array_id not in status_map:
            status_map[array_id] = SimpleNamespace(state=None, last_refresh=None)
        return status_map[array_id]

    monkeypatch.setattr(main_mod, "get_ssh_pool", lambda: fake_pool)
    monkeypatch.setattr(arrays_api, "_get_array_status", fake_get_status)

    await main_mod._auto_reconnect_saved_arrays()

    called_ids = {item["array_id"] for item in fake_pool.added}
    assert called_ids == {"arr-auto-ok", "arr-auto-fail"}
    assert "arr-auto-skip" not in called_ids

    assert status_map["arr-auto-ok"].state == ConnectionState.CONNECTED
    assert status_map["arr-auto-fail"].state == ConnectionState.DISCONNECTED
    assert status_map["arr-auto-ok"].last_refresh is not None
    assert status_map["arr-auto-fail"].last_refresh is not None


@pytest.mark.asyncio
async def test_card_sync_skips_unstarted_array_and_keeps_last_updated(app_client_with_db, monkeypatch):
    """Regression: when start_work is enabled and array is not started, card sync must skip updates."""
    from backend.api import card_inventory as card_api
    from backend.api import arrays as arrays_api
    from backend.core import ssh_pool as ssh_pool_mod

    client, db = app_client_with_db

    db.add(
        ArrayModel(
            array_id="arr-card-1",
            name="arr-card-1",
            host="10.30.1.1",
            port=22,
            username="root",
            key_path="",
            folder="",
            saved_password="pw",
        )
    )
    db.add(ObserverConfigModel(observer_name="start_work", enabled=True))
    old_ts = datetime.now() - timedelta(hours=2)
    db.add(
        CardInventoryModel(
            array_id="arr-card-1",
            card_no="No001",
            board_id="B001",
            health_state="NORMAL",
            running_state="RUNNING",
            model="X",
            raw_fields="{}",
            last_updated=old_ts,
        )
    )
    await db.commit()

    class FakeConn:
        def __init__(self):
            self.card_sync_called = False

        def is_connected(self):
            return True

        async def execute_async(self, cmd, timeout):
            if cmd == "anytest sysgetstartwork":
                # Has module state != 1 -> should be treated as not started.
                return 0, "system module num: 2\nmod_a: 1\nmod_b: 0\n", ""
            if cmd == "anytest intfboardallinfo":
                self.card_sync_called = True
                return 0, "", ""
            return 1, "", "unknown command"

    class FakePool:
        def __init__(self, conn):
            self._conn = conn

        def get_connection(self, array_id):
            if array_id == "arr-card-1":
                return self._conn
            return None

    fake_conn = FakeConn()
    fake_pool = FakePool(fake_conn)
    monkeypatch.setattr(ssh_pool_mod, "get_ssh_pool", lambda: fake_pool)
    monkeypatch.setattr(
        arrays_api,
        "_get_array_status",
        lambda _aid: SimpleNamespace(agent_deployed=True),
    )

    resp = await client.post("/api/card-inventory/sync")
    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] == 0
    assert any("未开工" in msg for msg in data["errors"])
    assert fake_conn.card_sync_called is False

    result = await db.execute(
        select(CardInventoryModel).where(
            CardInventoryModel.array_id == "arr-card-1",
            CardInventoryModel.card_no == "No001",
        )
    )
    refreshed = result.scalar_one_or_none()
    assert refreshed is not None
    assert refreshed.last_updated == old_ts


@pytest.mark.asyncio
async def test_card_sync_reports_disconnected_arrays_and_per_array_results(app_client_with_db, monkeypatch):
    """Regression: disconnected arrays must be reported explicitly instead of silently skipped."""
    from backend.core import ssh_pool as ssh_pool_mod

    client, db = app_client_with_db

    db.add_all(
        [
            ArrayModel(
                array_id="arr-card-offline",
                name="arr-card-offline",
                host="10.30.2.1",
                port=22,
                username="root",
                key_path="",
                folder="",
                saved_password="pw",
            ),
            ArrayModel(
                array_id="arr-card-online",
                name="arr-card-online",
                host="10.30.2.2",
                port=22,
                username="root",
                key_path="",
                folder="",
                saved_password="pw",
            ),
        ]
    )
    await db.commit()

    class OfflineConn:
        def is_connected(self):
            return False

    class OnlineConn:
        def is_connected(self):
            return True

        async def execute_async(self, cmd, timeout):
            if cmd == "anytest intfboardallinfo":
                return 0, "No001  BoardId: B100\nNo001  Model: X1\nNo001  HealthState: NORMAL\nNo001  RunningState: RUNNING\n", ""
            return 1, "", "unknown command"

    class FakePool:
        def get_connection(self, array_id):
            if array_id == "arr-card-offline":
                return OfflineConn()
            if array_id == "arr-card-online":
                return OnlineConn()
            return None

    monkeypatch.setattr(ssh_pool_mod, "get_ssh_pool", lambda: FakePool())

    resp = await client.post("/api/card-inventory/sync")
    assert resp.status_code == 200
    data = resp.json()

    assert data["synced"] == 1
    assert data["skipped_arrays"] == ["arr-card-offline"]
    assert data["synced_arrays"] == ["arr-card-online"]
    assert any("SSH 未连接" in msg for msg in data["errors"])
