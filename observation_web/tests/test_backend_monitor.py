"""U2: unified backend-exec monitor definitions (create/store/health)."""
import pytest


async def _create_backend_monitor(client, name="be-mon"):
    return await client.post("/api/admin/monitor-templates", json={
        "name": name,
        "command": "placeholder",          # agent field kept non-null
        "match_expression": "placeholder",
        "exec_location": "backend",
        "commands": ["cat /proc/mdstat"],
        "monitor_arrays": ["arr1"],
        "rule_spec": {"rule_type": "valid_match", "pattern": "degraded", "expect_match": False},
    })


@pytest.mark.asyncio
async def test_create_backend_monitor_stores_unified_fields(app_client):
    r = await _create_backend_monitor(app_client)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["exec_location"] == "backend"
    assert d["commands"] == ["cat /proc/mdstat"]
    assert d["monitor_arrays"] == ["arr1"]
    assert d["rule_spec"]["pattern"] == "degraded"


@pytest.mark.asyncio
async def test_backend_monitor_appears_in_health(app_client):
    await _create_backend_monitor(app_client, name="be-health")
    h = await app_client.get("/api/admin/monitor-templates/health")
    assert h.status_code == 200
    rows = h.json()
    assert any(
        row.get("exec_location") == "backend" and row.get("template_name") == "be-health"
        for row in rows
    )


@pytest.mark.asyncio
async def test_agent_monitor_still_defaults(app_client):
    r = await app_client.post("/api/admin/monitor-templates", json={
        "name": "agent-mon", "command": "df -h", "match_expression": "/",
    })
    assert r.status_code == 200, r.text
    assert r.json()["exec_location"] == "agent"
