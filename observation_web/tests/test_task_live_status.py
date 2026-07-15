"""Tests for the test-task realtime ingestion view."""

import json
from datetime import datetime, timedelta

import pytest

from backend.models.alert import AlertModel
from backend.models.array import ArrayModel
from backend.models.lifecycle import SyncStateModel
from backend.models.task_session import TaskSessionModel


@pytest.mark.asyncio
async def test_live_status_reports_freshness_and_task_alerts(app_client_with_db):
    client, db = app_client_with_db
    now = datetime.now()
    array = ArrayModel(
        array_id="array-live", name="Live Array", host="10.0.0.9",
        port=22, username="root", key_path="", folder="",
    )
    task = TaskSessionModel(
        name="Live Test", task_type="custom",
        array_ids=json.dumps(["array-live"]), status="running",
        started_at=now - timedelta(minutes=2),
    )
    db.add_all([array, task])
    await db.flush()
    db.add_all([
        SyncStateModel(
            array_id="array-live", last_position=10,
            last_sync_at=now - timedelta(seconds=20),
        ),
        AlertModel(
            array_id="array-live", observer_name="link_status", level="critical",
            message="link down", details="{}", timestamp=now - timedelta(seconds=10),
            task_id=task.id,
        ),
    ])
    await db.commit()

    response = await client.get(f"/api/test-tasks/{task.id}/live-status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["fresh_count"] == 1
    assert payload["attention_count"] == 0
    assert payload["arrays"][0]["freshness"] == "fresh"
    assert payload["arrays"][0]["alert_count"] == 1
    assert payload["arrays"][0]["critical_count"] == 1
