"""Phase 3: per-tag / per-array observer config override layer.

Covers resolve_observer_config layering (global < tag < array), param deep
merge, tri-state enabled, no-override fallthrough, plus the override CRUD API.
"""
import json

import pytest

from backend.api.observer_configs import resolve_observer_config
from backend.models.array import ArrayModel
from backend.models.observer_config import (
    ObserverConfigModel,
    ObserverConfigOverrideModel,
)


async def _seed_array(db, array_id="arr-1", tag_id=10):
    arr = ArrayModel(
        array_id=array_id,
        name=array_id,
        host=f"host-{array_id}",
        tag_id=tag_id,
    )
    db.add(arr)
    await db.flush()
    return arr


async def _seed_global(db, name="port_traffic", enabled=True, interval=60, params=None):
    row = ObserverConfigModel(
        observer_name=name,
        enabled=enabled,
        interval=interval,
        params_json=json.dumps(params or {}),
    )
    db.add(row)
    await db.flush()
    return row


async def _seed_override(db, name, scope_type, scope_id, params=None, enabled=None):
    row = ObserverConfigOverrideModel(
        observer_name=name,
        scope_type=scope_type,
        scope_id=str(scope_id),
        params_json=json.dumps(params or {}),
        enabled=enabled,
    )
    db.add(row)
    await db.flush()
    return row


@pytest.mark.asyncio
async def test_resolve_returns_global_default(db_session):
    await _seed_array(db_session, "arr-1", tag_id=10)
    await _seed_global(db_session, "port_traffic", enabled=True, interval=60,
                       params={"threshold": 90})

    cfg = await resolve_observer_config(db_session, "port_traffic", "arr-1")

    assert cfg["enabled"] is True
    assert cfg["interval"] == 60
    assert cfg["threshold"] == 90


@pytest.mark.asyncio
async def test_resolve_no_override_observer_falls_through_to_global(db_session):
    """An observer with only a global row and no overrides resolves to global."""
    await _seed_array(db_session, "arr-1", tag_id=10)
    await _seed_global(db_session, "cpu_usage", enabled=False, interval=30,
                       params={"limit": 80})

    cfg = await resolve_observer_config(db_session, "cpu_usage", "arr-1")

    assert cfg["enabled"] is False
    assert cfg["interval"] == 30
    assert cfg["limit"] == 80


@pytest.mark.asyncio
async def test_resolve_unknown_observer_returns_empty(db_session):
    """No global and no overrides -> empty effective config."""
    await _seed_array(db_session, "arr-1", tag_id=10)
    cfg = await resolve_observer_config(db_session, "port_traffic", "arr-1")
    assert cfg == {}


@pytest.mark.asyncio
async def test_tag_override_applies(db_session):
    await _seed_array(db_session, "arr-1", tag_id=10)
    await _seed_global(db_session, "port_traffic", params={"threshold": 90})
    await _seed_override(db_session, "port_traffic", "tag", 10,
                         params={"threshold": 70})

    cfg = await resolve_observer_config(db_session, "port_traffic", "arr-1")
    assert cfg["threshold"] == 70


@pytest.mark.asyncio
async def test_array_override_applies(db_session):
    await _seed_array(db_session, "arr-1", tag_id=10)
    await _seed_global(db_session, "port_traffic", params={"threshold": 90})
    await _seed_override(db_session, "port_traffic", "array", "arr-1",
                         params={"threshold": 55})

    cfg = await resolve_observer_config(db_session, "port_traffic", "arr-1")
    assert cfg["threshold"] == 55


@pytest.mark.asyncio
async def test_priority_array_beats_tag_beats_global(db_session):
    await _seed_array(db_session, "arr-1", tag_id=10)
    await _seed_global(db_session, "port_traffic", params={"threshold": 90})
    await _seed_override(db_session, "port_traffic", "tag", 10,
                         params={"threshold": 70})
    await _seed_override(db_session, "port_traffic", "array", "arr-1",
                         params={"threshold": 55})

    cfg = await resolve_observer_config(db_session, "port_traffic", "arr-1")
    assert cfg["threshold"] == 55  # array wins

    # Remove array override -> tag wins
    row = (await db_session.execute(
        __import__("sqlalchemy").select(ObserverConfigOverrideModel).where(
            ObserverConfigOverrideModel.scope_type == "array"
        )
    )).scalars().first()
    await db_session.delete(row)
    await db_session.flush()
    cfg = await resolve_observer_config(db_session, "port_traffic", "arr-1")
    assert cfg["threshold"] == 70  # tag wins over global


@pytest.mark.asyncio
async def test_params_deep_merge_across_layers(db_session):
    """Each layer merges keys; unset keys from lower layers persist."""
    await _seed_array(db_session, "arr-1", tag_id=10)
    await _seed_global(db_session, "port_traffic",
                       params={"a": 1, "b": 2, "c": 3})
    await _seed_override(db_session, "port_traffic", "tag", 10,
                         params={"b": 20})
    await _seed_override(db_session, "port_traffic", "array", "arr-1",
                         params={"c": 300})

    cfg = await resolve_observer_config(db_session, "port_traffic", "arr-1")
    assert cfg["a"] == 1     # from global
    assert cfg["b"] == 20    # from tag
    assert cfg["c"] == 300   # from array


@pytest.mark.asyncio
async def test_enabled_none_does_not_override(db_session):
    """enabled=None on an override leaves the global switch untouched."""
    await _seed_array(db_session, "arr-1", tag_id=10)
    await _seed_global(db_session, "port_traffic", enabled=True,
                       params={"threshold": 90})
    # override only tweaks params, enabled stays None
    await _seed_override(db_session, "port_traffic", "array", "arr-1",
                         params={"threshold": 55}, enabled=None)

    cfg = await resolve_observer_config(db_session, "port_traffic", "arr-1")
    assert cfg["enabled"] is True   # unchanged by the override
    assert cfg["threshold"] == 55


@pytest.mark.asyncio
async def test_enabled_non_none_overrides(db_session):
    await _seed_array(db_session, "arr-1", tag_id=10)
    await _seed_global(db_session, "port_traffic", enabled=True)
    await _seed_override(db_session, "port_traffic", "array", "arr-1",
                         enabled=False)

    cfg = await resolve_observer_config(db_session, "port_traffic", "arr-1")
    assert cfg["enabled"] is False


# ---------------------------------------------------------------------------
# API contract
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_override_crud_api(app_client):
    # upsert an array override
    resp = await app_client.post(
        "/api/admin/observer-configs/port_traffic/overrides",
        json={"scope_type": "array", "scope_id": "arr-1",
              "params": {"threshold": 55}, "enabled": False},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["scope_type"] == "array"
    assert body["params"]["threshold"] == 55
    assert body["enabled"] is False
    assert body["updated_by"]  # attributed to the seeded test user

    # list
    resp = await app_client.get("/api/admin/observer-configs/port_traffic/overrides")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["scope_id"] == "arr-1"

    # upsert again updates in place (no duplicate)
    resp = await app_client.post(
        "/api/admin/observer-configs/port_traffic/overrides",
        json={"scope_type": "array", "scope_id": "arr-1",
              "params": {"threshold": 44}},
    )
    assert resp.status_code == 200
    rows = (await app_client.get(
        "/api/admin/observer-configs/port_traffic/overrides")).json()
    assert len(rows) == 1
    assert rows[0]["params"]["threshold"] == 44

    # delete
    resp = await app_client.delete(
        "/api/admin/observer-configs/port_traffic/overrides/array/arr-1")
    assert resp.status_code == 200
    rows = (await app_client.get(
        "/api/admin/observer-configs/port_traffic/overrides")).json()
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_override_upsert_rejects_bad_scope_type(app_client):
    resp = await app_client.post(
        "/api/admin/observer-configs/port_traffic/overrides",
        json={"scope_type": "bogus", "scope_id": "x"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_override_upsert_rejects_unknown_observer(app_client):
    resp = await app_client.post(
        "/api/admin/observer-configs/not_an_observer/overrides",
        json={"scope_type": "array", "scope_id": "arr-1"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_override_write_requires_login(anonymous_client):
    resp = await anonymous_client.post(
        "/api/admin/observer-configs/port_traffic/overrides",
        json={"scope_type": "array", "scope_id": "arr-1"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_override_delete_missing_returns_404(app_client):
    resp = await app_client.delete(
        "/api/admin/observer-configs/port_traffic/overrides/array/nope")
    assert resp.status_code == 404
