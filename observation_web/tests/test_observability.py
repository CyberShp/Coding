"""Observability endpoints: /livez, /readyz, /metrics.

These replace the single /health that returned 200 unconditionally (couldn't be
used to drain traffic) and expose runtime signals previously only in logs.
"""
import pytest


@pytest.mark.asyncio
async def test_livez_always_alive(app_client):
    r = await app_client.get("/livez")
    assert r.status_code == 200
    assert r.json()["status"] == "alive"


@pytest.mark.asyncio
async def test_readyz_reports_checks(app_client):
    r = await app_client.get("/readyz")
    # 200 when fully ready, 503 otherwise — either is a valid response shape here
    # (scheduler isn't started in the test app), but the checks must be reported.
    assert r.status_code in (200, 503)
    body = r.json()
    assert "checks" in body
    assert "db" in body["checks"] and "scheduler" in body["checks"]
    assert body["checks"]["db"] is True  # in-memory DB is reachable


@pytest.mark.asyncio
async def test_metrics_prometheus_text(app_client):
    r = await app_client.get("/metrics")
    assert r.status_code == 200
    assert "observation_ssh_connections" in r.text
    # Prometheus text format: has HELP/TYPE comment lines
    assert "# TYPE" in r.text
