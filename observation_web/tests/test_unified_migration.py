"""U3: idempotent migration of query auto-monitors → unified backend definitions."""
import json

import pytest
from sqlalchemy import select

from backend.core.monitor_migration import migrate_query_auto_monitors, migrate_all
from backend.models.monitor_template import MonitorTemplateModel
from backend.models.query import QueryTemplateModel


async def _seed_query_auto_monitor(db, name="raid-check"):
    qt = QueryTemplateModel(
        name=name,
        commands='["cat /proc/mdstat"]',
        rule_type="valid_match",
        pattern="degraded",
        expect_match=False,
        extract_fields="[]",
        is_builtin=False,
        auto_monitor=True,
        monitor_interval=120,
        monitor_arrays='["arr1"]',
        alert_on_mismatch=True,
    )
    db.add(qt)
    await db.flush()
    return qt


@pytest.mark.asyncio
async def test_query_auto_monitor_migrates_to_backend_def(db_session):
    await _seed_query_auto_monitor(db_session)
    created = await migrate_query_auto_monitors(db_session)
    assert created == 1

    m = (await db_session.execute(
        select(MonitorTemplateModel).where(MonitorTemplateModel.name == "query:raid-check")
    )).scalar_one()
    assert m.exec_location == "backend"
    assert json.loads(m.commands_json) == ["cat /proc/mdstat"]
    assert json.loads(m.monitor_arrays) == ["arr1"]
    assert m.interval == 120
    assert json.loads(m.rule_spec_json)["pattern"] == "degraded"


@pytest.mark.asyncio
async def test_migration_is_idempotent(db_session):
    await _seed_query_auto_monitor(db_session, name="svc-check")
    first = await migrate_query_auto_monitors(db_session)
    second = await migrate_query_auto_monitors(db_session)
    assert first == 1
    assert second == 0  # already migrated, not duplicated


@pytest.mark.asyncio
async def test_migrate_all_empty_is_safe(db_session):
    result = await migrate_all(db_session)
    assert result == {"query_auto_monitors": 0, "scheduled_templates": 0}
