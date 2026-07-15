"""Regression tests for lossless and idempotent alert ingestion."""

import json
import re
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from backend.api.arrays import _get_sync_position, sync_array_alerts
from backend.core.alert_store import AlertStore
from backend.models.alert import AlertCreate, AlertLevel, AlertModel
from backend.models.task_session import TaskSessionModel


class FakeAlertLogConnection:
    def __init__(self, records):
        self.lines = [json.dumps(record) for record in records]

    async def execute_async(self, command, timeout):
        if command.startswith("wc -l"):
            return 0, str(len(self.lines)), ""
        match = re.search(r"sed -n '(\d+),(\d+)p'", command)
        if match:
            start, end = (int(value) for value in match.groups())
            return 0, "\n".join(self.lines[start - 1:end]), ""
        raise AssertionError(f"Unexpected command: {command}")


def make_records(count):
    base = datetime(2026, 1, 1)
    return [
        {
            "event_id": f"evt-{index}",
            "observer_name": "link_status",
            "level": "warning",
            "message": f"event {index}",
            "timestamp": (base + timedelta(seconds=index)).isoformat(),
            "details": {"index": index},
        }
        for index in range(count)
    ]


@pytest.mark.asyncio
async def test_sync_advances_only_by_consumed_chunk(db_session):
    conn = FakeAlertLogConnection(make_records(650))
    config = SimpleNamespace(remote=SimpleNamespace(agent_log_path="/tmp/alerts.log"))

    first_count = await sync_array_alerts("array-1", db_session, conn, config)
    assert first_count == 500
    assert await _get_sync_position(db_session, "array-1") == 500

    second_count = await sync_array_alerts("array-1", db_session, conn, config)
    assert second_count == 150
    assert await _get_sync_position(db_session, "array-1") == 650

    total = await db_session.scalar(select(func.count(AlertModel.id)))
    assert total == 650


@pytest.mark.asyncio
async def test_batch_ingestion_is_idempotent_by_source_event_id(db_session):
    store = AlertStore()
    alert = AlertCreate(
        array_id="array-1",
        observer_name="link_status",
        level=AlertLevel.ERROR,
        message="link down",
        details={},
        timestamp=datetime.now(),
        source_event_id="evt-stable",
    )

    first_count, _ = await store.create_alerts_batch(db_session, [alert])
    second_count, _ = await store.create_alerts_batch(db_session, [alert])

    assert first_count == 1
    assert second_count == 0
    assert await db_session.scalar(select(func.count(AlertModel.id))) == 1


@pytest.mark.asyncio
async def test_late_alert_is_attached_to_completed_task(db_session):
    now = datetime.now()
    task = TaskSessionModel(
        name="late-data-test",
        task_type="custom",
        array_ids=json.dumps(["array-1"]),
        status="completed",
        started_at=now - timedelta(minutes=10),
        ended_at=now - timedelta(minutes=5),
    )
    db_session.add(task)
    await db_session.commit()

    alert = await AlertStore().create_alert(
        db_session,
        AlertCreate(
            array_id="array-1",
            observer_name="error_code",
            level=AlertLevel.ERROR,
            message="arrived late",
            details={},
            timestamp=now - timedelta(minutes=7),
            source_event_id="late-event",
        ),
    )

    assert alert.task_id == task.id
